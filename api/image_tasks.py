from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from hashlib import sha256
from pydantic import BaseModel, Field

from api.image_inputs import parse_image_edit_request, read_image_sources
from api.image_task_contract import ImageTaskPage, ImageTaskRow
from api.support import require_identity, resolve_image_base_url
from services.content_filter import check_request
from services import gemini_provider
from services.image_task_service import ImageTaskQueueFullError, image_task_service
from services.log_service import LoggedCall
from services.portal_billing import UnsupportedImageResolutionError, portal_billing
from services.storage.portal_repository import portal_repository


class ImageGenerationTaskRequest(BaseModel):
    client_task_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    quality: str = "auto"


class ResumePollRequest(BaseModel):
    extra_timeout_secs: float = Field(default=30.0, ge=5.0, le=120.0)


def _parse_task_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _queue_full_http_error(exc: ImageTaskQueueFullError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": exc.code, "error": str(exc)},
    )


def _ensure_model_provider_available(model: object) -> None:
    try:
        gemini_provider.ensure_available(model)
    except gemini_provider.GeminiProviderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": str(exc), "code": exc.code},
        ) from exc


def _portal_task_id(identity: dict[str, object], image_task_id: str) -> str:
    seed = f"{identity.get('user_id')}:{image_task_id}".encode("utf-8")
    return f"image_{sha256(seed).hexdigest()[:48]}"


async def _sync_portal_task(
    identity: dict[str, object],
    item: dict[str, object],
    *,
    prompt: str,
    task_type: str = "image",
    charge_units: int = 0,
    billing_reference_id: str | None = None,
) -> None:
    user_id = str(identity.get("user_id") or "").strip()
    image_task_id = str(item.get("id") or "").strip()
    if not user_id or not image_task_id:
        return
    status = str(item.get("status") or "queued").strip().lower()
    if status == "partial_success":
        status = "success"
    if status == "text_review":
        status = "failed"
    if status not in {"queued", "running", "success", "failed"}:
        status = "running"
    task_id = _portal_task_id(identity, image_task_id)
    await run_in_threadpool(
        portal_repository.create_task,
        task_id=task_id,
        user_id=user_id,
        api_key_id=str(identity.get("api_key_id") or "") or None,
        task_type=task_type,
        model=str(item.get("model") or "gpt-image-2"),
        request={
            "prompt": prompt,
            "source_task_id": image_task_id,
            "charge_units": charge_units,
            "billing_reference_type": "image_task",
            "billing_reference_id": billing_reference_id or f"{user_id}:{image_task_id}",
        },
        status=status,
    )
    if status in {"success", "failed"}:
        await run_in_threadpool(
            portal_repository.update_task,
            user_id=user_id,
            task_id=task_id,
            status=status,
            result={"source_task_id": image_task_id},
            error_code=str(item.get("error_code") or "") or None,
        )
        billing_id = billing_reference_id or f"{user_id}:{image_task_id}"
        if status == "success":
            await run_in_threadpool(
                portal_billing.complete,
                identity,
                reference_type="image_task",
                reference_id=billing_id,
            )
        else:
            if charge_units > 0:
                await run_in_threadpool(
                    portal_billing.refund,
                    identity,
                    amount_units=charge_units,
                    reference_type="image_task",
                    reference_id=billing_id,
                )
            else:
                await run_in_threadpool(
                    portal_billing.refund_reserved,
                    identity,
                    reference_type="image_task",
                    reference_id=billing_id,
                )


async def _reserve_image_task(
    identity: dict[str, object],
    *,
    count: int,
    size: object,
    reference_id: str,
    endpoint: str,
    model: str,
) -> int:
    if not portal_billing.user_id(identity):
        return 0
    try:
        amount = portal_billing.cost_for_task("image", count=count, size=size)
        await run_in_threadpool(
            portal_billing.reserve,
            identity,
            amount_units=amount,
            reference_type="image_task",
            reference_id=reference_id,
            endpoint=endpoint,
            model=model,
            task_id=reference_id,
            units=count,
        )
    except UnsupportedImageResolutionError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=402, detail={"error": str(exc)}) from exc
    return amount


async def _refund_image_task(identity: dict[str, object], *, amount: int, reference_id: str) -> None:
    if amount <= 0:
        return
    await run_in_threadpool(
        portal_billing.refund,
        identity,
        amount_units=amount,
        reference_type="image_task",
        reference_id=reference_id,
    )


def _adjust_image_task_billing(
    identity: dict[str, object],
    reference_id: str,
    resolved_sizes: list[str],
) -> None:
    portal_billing.adjust_reserved_image_amount(
        identity,
        resolved_sizes=resolved_sizes,
        reference_type="image_task",
        reference_id=reference_id,
    )


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("调用失败", status="failed", error=str(exc.detail))
        raise


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-tasks", response_model=ImageTaskPage)
    async def list_image_tasks(
        ids: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        page = await run_in_threadpool(image_task_service.list_tasks, identity, _parse_task_ids(ids))
        user_id = str(identity.get("user_id") or "").strip()
        for item in page.get("items", []):
            await _sync_portal_task(
                identity,
                item,
                prompt="图片任务",
                billing_reference_id=f"{user_id}:{item.get('id', '')}" if user_id else None,
            )
        return page

    @router.post("/api/image-tasks/generations", response_model=ImageTaskRow)
    async def create_generation_task(
        body: ImageGenerationTaskRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        _ensure_model_provider_available(body.model)
        await filter_or_log(LoggedCall(identity, "/api/image-tasks/generations", body.model, "文生图任务", request_text=body.prompt), body.prompt)
        reference_id = f"{identity.get('user_id', '')}:{body.client_task_id}"
        charged_units = await _reserve_image_task(
            identity,
            count=body.n,
            size=body.size,
            reference_id=reference_id,
            endpoint="/api/image-tasks/generations",
            model=body.model,
        )
        try:
            result = await run_in_threadpool(
                image_task_service.submit_generation,
                identity,
                client_task_id=body.client_task_id,
                prompt=body.prompt,
                model=body.model,
                n=body.n,
                size=body.size,
                quality=body.quality,
                base_url=resolve_image_base_url(request),
                billing_resolution_callback=lambda sizes: _adjust_image_task_billing(
                    identity, reference_id, sizes
                ),
            )
        except ImageTaskQueueFullError as exc:
            await _refund_image_task(identity, amount=charged_units, reference_id=reference_id)
            raise _queue_full_http_error(exc) from exc
        except ValueError as exc:
            await _refund_image_task(identity, amount=charged_units, reference_id=reference_id)
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except Exception:
            await _refund_image_task(identity, amount=charged_units, reference_id=reference_id)
            raise
        await _sync_portal_task(
            identity,
            result,
            prompt=body.prompt,
            charge_units=charged_units,
            billing_reference_id=reference_id,
        )
        return result

    @router.post("/api/image-tasks/edits", response_model=ImageTaskRow)
    async def create_edit_task(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload, image_sources, mask_sources = await parse_image_edit_request(request)
        client_task_id = str(payload.get("client_task_id") or "").strip()
        if not client_task_id:
            raise HTTPException(status_code=400, detail={"error": "client_task_id is required"})
        prompt = str(payload["prompt"])
        model = str(payload["model"])
        _ensure_model_provider_available(model)
        await filter_or_log(LoggedCall(identity, "/api/image-tasks/edits", model, "图生图任务", request_text=prompt), prompt)
        reference_id = f"{identity.get('user_id', '')}:{client_task_id}"
        charged_units = await _reserve_image_task(
            identity,
            count=int(payload.get("n") or 1),
            size=payload.get("size"),
            reference_id=reference_id,
            endpoint="/api/image-tasks/edits",
            model=model,
        )
        reservation = None
        try:
            reservation = await run_in_threadpool(image_task_service.reserve_submission)
            images = await read_image_sources(image_sources)
            masks = await read_image_sources(mask_sources) if mask_sources else None
            result = await run_in_threadpool(
                image_task_service.submit_edit,
                identity,
                client_task_id=client_task_id,
                prompt=prompt,
                model=model,
                n=payload.get("n", 1),
                size=payload["size"],
                quality=payload["quality"],
                base_url=resolve_image_base_url(request),
                images=images,
                masks=masks,
                reservation=reservation,
                billing_resolution_callback=lambda sizes: _adjust_image_task_billing(
                    identity, reference_id, sizes
                ),
            )
        except ImageTaskQueueFullError as exc:
            await _refund_image_task(identity, amount=charged_units, reference_id=reference_id)
            raise _queue_full_http_error(exc) from exc
        except ValueError as exc:
            await _refund_image_task(identity, amount=charged_units, reference_id=reference_id)
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except Exception:
            await _refund_image_task(identity, amount=charged_units, reference_id=reference_id)
            raise
        finally:
            if reservation is not None:
                reservation.rollback()
        await _sync_portal_task(
            identity,
            result,
            prompt=prompt,
            charge_units=charged_units,
            billing_reference_id=reference_id,
        )
        return result

    @router.post("/api/image-tasks/{task_id}/resume-poll", response_model=ImageTaskRow)
    async def resume_image_poll(
        task_id: str,
        body: ResumePollRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        try:
            result = await run_in_threadpool(
                image_task_service.resume_poll,
                identity,
                task_id,
                body.extra_timeout_secs,
            )
            await _sync_portal_task(
                identity,
                result,
                prompt="任务轮询",
                billing_reference_id=f"{identity.get('user_id', '')}:{task_id}",
            )
            return result
        except ImageTaskQueueFullError as exc:
            raise _queue_full_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    return router
