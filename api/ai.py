from __future__ import annotations

from hashlib import sha256

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from uuid import uuid4

from api.image_inputs import parse_image_edit_request, read_image_sources
from api.support import require_ai_identity as require_identity, resolve_image_base_url
from services.content_filter import check_request, request_shape, request_text
from services.editable_file_task_service import (
    EditableFileTaskCleanupError,
    EditableFileTaskInvalidIdError,
    EditableFileTaskNotFoundError,
    EditableFileTaskNotTerminalError,
    editable_file_task_service,
)
from services.log_service import LoggedCall
from services.portal_billing import UnsupportedImageResolutionError, portal_billing
from services import gemini_provider
from services.portal_file_tasks import (
    file_task_reference,
    portal_file_task_id,
    sync_portal_file_task,
)
from services.storage.portal_repository import portal_repository
from services.protocol import (
    anthropic_v1_messages,
    openai_v1_chat_complete,
    openai_v1_image_edit,
    openai_v1_image_generations,
    openai_v1_models,
    openai_v1_response,
    openai_search,
)
from utils.helper import has_response_image_generation_tool, is_image_chat_request


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    quality: str = "auto"
    response_format: str = "b64_json"
    history_disabled: bool = True
    stream: bool | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    prompt: str | None = None
    n: int | None = None
    stream: bool | None = None
    modalities: list[str] | None = None
    messages: list[dict[str, object]] | None = None


class ResponseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    input: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None


class AnthropicMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict[str, object]] | None = None
    system: object | None = None
    stream: bool | None = None


class SearchRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class EditableFileTaskRequest(BaseModel):
    prompt: str = ""
    kind: str = "ppt"
    base64_images: list[str] = Field(default_factory=list)
    client_task_id: str | None = None


TRACE_REQUEST_HEADERS = {
    "x-request-id": "x_request_id",
    "x-newapi-request-id": "x_newapi_request_id",
    "x-oneapi-request-id": "x_oneapi_request_id",
    "x-channel-id": "x_channel_id",
    "x-channel-name": "x_channel_name",
}


def _call_id_for_request(identity: dict[str, object], endpoint: str, request: Request) -> str:
    key = str(request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        return uuid4().hex[:16]
    if len(key) > 160:
        raise HTTPException(status_code=400, detail={"error": "Idempotency-Key 最多 160 个字符"})
    user_id = str(identity.get("user_id") or "").strip()
    if not user_id:
        return uuid4().hex[:16]
    seed = f"{user_id}:{endpoint}:{key}".encode("utf-8")
    return f"idem_{sha256(seed).hexdigest()[:48]}"


def attach_trace_headers(call: LoggedCall, request: Request) -> None:
    if not call._trace_image_perf():
        return
    headers: dict[str, str] = {}
    for header, field in TRACE_REQUEST_HEADERS.items():
        value = str(request.headers.get(header) or "").strip()
        if value:
            headers[field] = value[:160]
    if headers:
        existing = call.trace_metadata.get("request_headers")
        if isinstance(existing, dict):
            existing.update(headers)
        else:
            call.trace_metadata["request_headers"] = headers


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("调用失败", status="failed", error=str(exc.detail))
        raise


async def _start_user_task(call: LoggedCall, prompt: str, task_type: str) -> str:
    user_id = str(call.identity.get("user_id") or "").strip()
    if not user_id:
        return ""
    task_id = f"call_{call.call_id}"
    await run_in_threadpool(
        portal_repository.create_task,
        task_id=task_id,
        user_id=user_id,
        api_key_id=str(call.identity.get("api_key_id") or "") or None,
        task_type=task_type,
        model=str(call.model or "auto"),
        request={
            "prompt": prompt[:4000],
            "endpoint": call.endpoint,
            "billing_reference_type": "api_call",
            "billing_reference_id": call.call_id,
        },
        status="running",
    )
    return task_id


async def _start_billed_user_task(
    call: LoggedCall,
    prompt: str,
    task_type: str,
    charged_units: int,
) -> str:
    try:
        return await _start_user_task(call, prompt, task_type)
    except Exception:
        await _refund_call(call, charged_units)
        raise


async def _finish_user_task(call: LoggedCall, task_id: str, result: object, status: str = "success") -> None:
    if not task_id:
        return
    user_id = str(call.identity.get("user_id") or "").strip()
    if not user_id:
        return
    result_data = result if isinstance(result, dict) else {}
    await run_in_threadpool(
        portal_repository.update_task,
        user_id=user_id,
        task_id=task_id,
        status=status,
        result={"endpoint": call.endpoint, "call_id": call.call_id},
        error_code=str(result_data.get("error_code") or "") or None,
    )


async def _settle_call_result(
    call: LoggedCall,
    task_id: str,
    result: object,
    charged_units: int,
) -> object:
    if not isinstance(result, StreamingResponse):
        status_code = int(getattr(result, "status_code", 200) or 200)
        if status_code >= 400:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, result, status="failed")
        else:
            await _complete_call(call)
            await _finish_user_task(call, task_id, result)
        return result

    original_iterator = result.body_iterator

    async def stream_with_task_state():
        try:
            async for chunk in original_iterator:
                yield chunk
        except Exception:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, {}, status="failed")
            raise
        else:
            await _complete_call(call)
            await _finish_user_task(call, task_id, {})

    result.body_iterator = stream_with_task_state()
    return result


async def _reserve_call(call: LoggedCall, *, count: int = 1, size: object = None) -> int:
    try:
        amount = (
            portal_billing.cost_for_task("image", count=count, size=size)
            if call.image_request
            else portal_billing.cost_for_endpoint(call.endpoint, count=count, size=size)
        )
        reservation = await run_in_threadpool(
            portal_billing.reserve,
            call.identity,
            amount_units=amount,
            reference_type="api_call",
            reference_id=call.call_id,
            endpoint=call.endpoint,
            model=call.model,
            task_id=f"call_{call.call_id}",
            units=count,
        )
        if isinstance(reservation, dict) and reservation.get("created") is False:
            usage = reservation.get("usage") if isinstance(reservation.get("usage"), dict) else {}
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "相同 Idempotency-Key 的请求已经处理或正在处理",
                    "status": str(usage.get("status") or "reserved"),
                    "task_id": str(usage.get("task_id") or f"call_{call.call_id}"),
                },
            )
    except UnsupportedImageResolutionError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=402, detail={"error": str(exc)}) from exc
    if not portal_billing.user_id(call.identity):
        return 0
    return amount


async def _refund_call(call: LoggedCall, amount: int) -> None:
    if amount <= 0:
        return
    try:
        await run_in_threadpool(
            portal_billing.refund,
            call.identity,
            amount_units=amount,
            reference_type="api_call",
            reference_id=call.call_id,
        )
    except Exception as exc:
        call.log("额度退款失败", status="failed", error=str(exc))


async def _complete_call(call: LoggedCall) -> None:
    if not portal_billing.user_id(call.identity):
        return
    try:
        await run_in_threadpool(
            portal_billing.complete,
            call.identity,
            reference_type="api_call",
            reference_id=call.call_id,
        )
    except Exception as exc:
        call.log("用量记录结算失败", status="failed", error=str(exc))


def _attach_image_billing_callback(call: LoggedCall, payload: dict[str, object]) -> None:
    if not call.image_request or not portal_billing.user_id(call.identity):
        return

    def adjust(resolved_sizes: list[str]) -> None:
        portal_billing.adjust_reserved_image_amount(
            call.identity,
            resolved_sizes=resolved_sizes,
            reference_type="api_call",
            reference_id=call.call_id,
        )

    payload["_billing_resolution_callback"] = adjust


def _ensure_model_provider_available(model: object) -> None:
    try:
        gemini_provider.ensure_available(model)
    except gemini_provider.GeminiProviderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": str(exc), "code": exc.code},
        ) from exc


def _image_generation_handler(payload: dict[str, object]):
    if gemini_provider.is_gemini_model(payload.get("model")):
        return gemini_provider.image_generation(payload)
    return openai_v1_image_generations.handle(payload)


def _image_edit_handler(payload: dict[str, object]):
    if gemini_provider.is_gemini_model(payload.get("model")):
        return gemini_provider.image_edit(payload)
    return openai_v1_image_edit.handle(payload)


def _chat_completion_handler(payload: dict[str, object]):
    if gemini_provider.is_gemini_model(payload.get("model")):
        return gemini_provider.chat(payload)
    return openai_v1_chat_complete.handle(payload)


def create_router() -> APIRouter:
    router = APIRouter()

    async def submit_editable_file_task(
        submit,
        identity,
        *,
        kind: str,
        endpoint: str,
        prompt: str,
        client_task_id: str,
        base64_images: list[str],
        base_url: str,
    ):
        normalized_task_id = str(client_task_id or "").strip() or f"{kind}-{uuid4().hex}"
        user_id = str(identity.get("user_id") or "").strip()
        if not user_id:
            try:
                return await run_in_threadpool(
                    submit,
                    identity,
                    client_task_id=normalized_task_id,
                    prompt=prompt,
                    base64_images=base64_images,
                    base_url=base_url,
                )
            except EditableFileTaskInvalidIdError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

        reference_id = file_task_reference(user_id, kind, normalized_task_id)
        charged_units = portal_billing.cost_for_task("file")
        try:
            await run_in_threadpool(
                portal_billing.reserve,
                identity,
                amount_units=charged_units,
                reference_type="file_task",
                reference_id=reference_id,
                endpoint=endpoint,
                model="gpt-5-5-thinking",
                task_id=portal_file_task_id(reference_id),
                units=1,
            )
        except ValueError as exc:
            raise HTTPException(status_code=402, detail={"error": str(exc)}) from exc

        try:
            await run_in_threadpool(
                portal_repository.create_task,
                task_id=portal_file_task_id(reference_id),
                user_id=user_id,
                api_key_id=str(identity.get("api_key_id") or "") or None,
                task_type="file",
                model="gpt-5-5-thinking",
                request={
                    "prompt": prompt[:4000],
                    "kind": kind,
                    "source_task_id": normalized_task_id,
                    "endpoint": endpoint,
                    "charge_units": charged_units,
                },
                status="queued",
            )

            def on_terminal(item: dict[str, object], terminal_identity: dict[str, object]) -> None:
                sync_portal_file_task(
                    terminal_identity,
                    item,
                    kind=kind,
                    prompt=prompt,
                    reference_id=reference_id,
                    charge_units=charged_units,
                )

            result = await run_in_threadpool(
                submit,
                identity,
                client_task_id=normalized_task_id,
                prompt=prompt,
                base64_images=base64_images,
                base_url=base_url,
                on_terminal=on_terminal,
            )
            await run_in_threadpool(
                sync_portal_file_task,
                identity,
                result,
                kind=kind,
                prompt=prompt,
                reference_id=reference_id,
                charge_units=charged_units,
            )
            return result
        except EditableFileTaskInvalidIdError as exc:
            await run_in_threadpool(
                sync_portal_file_task,
                identity,
                {"id": normalized_task_id, "kind": kind, "status": "error", "error": str(exc)},
                kind=kind,
                prompt=prompt,
                reference_id=reference_id,
                charge_units=charged_units,
            )
            raise HTTPException(
                status_code=400,
                detail={"error": str(exc)},
            ) from exc
        except Exception as exc:
            await run_in_threadpool(
                sync_portal_file_task,
                identity,
                {"id": normalized_task_id, "kind": kind, "status": "error", "error": str(exc)},
                kind=kind,
                prompt=prompt,
                reference_id=reference_id,
                charge_units=charged_units,
            )
            raise

    @router.get("/v1/models")
    async def list_models(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        try:
            return await run_in_threadpool(openai_v1_models.list_models)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        payload["base_url"] = resolve_image_base_url(request)
        _ensure_model_provider_available(body.model)
        call = LoggedCall(
            identity,
            "/v1/images/generations",
            body.model,
            "文生图",
            request_text=body.prompt,
            call_id=_call_id_for_request(identity, "/v1/images/generations", request),
        )
        attach_trace_headers(call, request)
        call.attach_trace_metadata(payload)
        await filter_or_log(call, body.prompt)
        charged_units = await _reserve_call(call, count=body.n, size=body.size)
        _attach_image_billing_callback(call, payload)
        task_id = await _start_billed_user_task(call, body.prompt, "image", charged_units)
        try:
            result = await call.run(_image_generation_handler, payload)
        except Exception:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, {}, status="failed")
            raise
        return await _settle_call_result(call, task_id, result, charged_units)

    @router.post("/v1/images/edits")
    async def edit_images(
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload, image_sources, mask_sources = await parse_image_edit_request(request)
        prompt = str(payload["prompt"])
        model = str(payload["model"])
        call = LoggedCall(
            identity,
            "/v1/images/edits",
            model,
            "图生图",
            request_text=prompt,
            call_id=_call_id_for_request(identity, "/v1/images/edits", request),
        )
        attach_trace_headers(call, request)
        call.attach_trace_metadata(payload)
        await filter_or_log(call, prompt)
        payload["images"] = await read_image_sources(image_sources)
        if mask_sources:
            payload["mask"] = await read_image_sources(mask_sources)
        payload["base_url"] = resolve_image_base_url(request)
        _ensure_model_provider_available(model)
        charged_units = await _reserve_call(
            call,
            count=int(payload.get("n") or 1),
            size=payload.get("size"),
        )
        _attach_image_billing_callback(call, payload)
        task_id = await _start_billed_user_task(call, prompt, "image", charged_units)
        try:
            result = await call.run(_image_edit_handler, payload)
        except Exception:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, {}, status="failed")
            raise
        return await _settle_call_result(call, task_id, result, charged_units)

    @router.post("/v1/chat/completions")
    async def create_chat_completion(body: ChatCompletionRequest, request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        payload["base_url"] = resolve_image_base_url(request)
        model = str(payload.get("model") or "auto")
        _ensure_model_provider_available(model)
        request_preview = request_text(payload.get("prompt"), payload.get("messages"))
        image_chat = is_image_chat_request(payload)
        call = LoggedCall(
            identity,
            "/v1/chat/completions",
            model,
            "聊天生图" if image_chat else "文本生成",
            request_text=request_preview,
            request_shape=request_shape(payload.get("messages")),
            image_request=image_chat,
            call_id=_call_id_for_request(identity, "/v1/chat/completions", request),
        )
        attach_trace_headers(call, request)
        call.attach_trace_metadata(payload)
        await filter_or_log(call, request_preview)
        charged_units = await _reserve_call(
            call,
            count=int(payload.get("n") or 1) if image_chat else 1,
            size=payload.get("size") if image_chat else None,
        )
        _attach_image_billing_callback(call, payload)
        task_id = await _start_billed_user_task(
            call,
            request_preview,
            "image" if image_chat else "chat",
            charged_units,
        )
        try:
            result = await call.run(_chat_completion_handler, payload)
        except Exception:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, {}, status="failed")
            raise
        return await _settle_call_result(call, task_id, result, charged_units)

    @router.post("/v1/responses")
    async def create_response(
        body: ResponseCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("input"), payload.get("instructions"))
        image_response = has_response_image_generation_tool(payload)
        call = LoggedCall(
            identity,
            "/v1/responses",
            model,
            "Responses",
            request_text=request_preview,
            request_shape=request_shape(payload.get("input")),
            image_request=image_response,
            call_id=_call_id_for_request(identity, "/v1/responses", request),
        )
        attach_trace_headers(call, request)
        call.attach_trace_metadata(payload)
        await filter_or_log(call, request_preview)
        charged_units = await _reserve_call(
            call,
            count=int(payload.get("n") or 1) if image_response else 1,
            size=payload.get("size") if image_response else None,
        )
        _attach_image_billing_callback(call, payload)
        task_id = await _start_billed_user_task(call, request_preview, "image" if image_response else "chat", charged_units)
        try:
            result = await call.run(openai_v1_response.handle, payload)
        except Exception:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, {}, status="failed")
            raise
        return await _settle_call_result(call, task_id, result, charged_units)

    @router.post("/v1/messages")
    async def create_message(
            body: AnthropicMessageRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            anthropic_version: str | None = Header(default=None, alias="anthropic-version"),
    ):
        identity = require_identity(authorization or (f"Bearer {x_api_key}" if x_api_key else None))
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("system"), payload.get("messages"), payload.get("tools"))
        call = LoggedCall(
            identity,
            "/v1/messages",
            model,
            "Messages",
            request_text=request_preview,
            call_id=_call_id_for_request(identity, "/v1/messages", request),
        )
        attach_trace_headers(call, request)
        await filter_or_log(call, request_preview)
        charged_units = await _reserve_call(call)
        task_id = await _start_billed_user_task(call, request_preview, "chat", charged_units)
        try:
            result = await call.run(anthropic_v1_messages.handle, payload, sse="anthropic")
        except Exception:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, {}, status="failed")
            raise
        return await _settle_call_result(call, task_id, result, charged_units)

    @router.post("/v1/search")
    async def search(
        body: SearchRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        call = LoggedCall(
            identity,
            "/v1/search",
            openai_search.MODEL,
            "搜索",
            request_text=body.prompt,
            call_id=_call_id_for_request(identity, "/v1/search", request),
        )
        attach_trace_headers(call, request)
        await filter_or_log(call, body.prompt)
        charged_units = await _reserve_call(call)
        task_id = await _start_billed_user_task(call, body.prompt, "search", charged_units)
        try:
            result = await call.run(openai_search.handle, body.model_dump(mode="python"))
        except Exception:
            await _refund_call(call, charged_units)
            await _finish_user_task(call, task_id, {}, status="failed")
            raise
        return await _settle_call_result(call, task_id, result, charged_units)

    @router.get("/v1/editable-file-tasks")
    async def list_editable_file_tasks(
            ids: str = "",
            limit: int = Query(default=0, ge=0, le=100),
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        task_ids = [item.strip() for item in ids.split(",") if item.strip()]
        result = await run_in_threadpool(editable_file_task_service.list_tasks, identity, task_ids, limit=limit)
        for item in result.get("items", []):
            kind = str(item.get("kind") or "").strip().lower()
            if kind in {"ppt", "psd"}:
                await run_in_threadpool(
                    sync_portal_file_task,
                    identity,
                    item,
                    kind=kind,
                    prompt="文件任务",
                )
        return result

    @router.post("/v1/editable-file-tasks")
    async def create_editable_file_task(body: EditableFileTaskRequest, request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        kind = (body.kind or "ppt").strip().lower()
        if kind not in {"ppt", "psd"}:
            raise HTTPException(status_code=400, detail={"error": "kind must be ppt or psd"})
        endpoint = f"/v1/{kind}/generations"
        await filter_or_log(
            LoggedCall(identity, endpoint, "gpt-5-5-thinking", f"{kind.upper()} generation task", request_text=body.prompt),
            body.prompt,
        )
        submit = editable_file_task_service.submit_psd if kind == "psd" else editable_file_task_service.submit_ppt
        return await submit_editable_file_task(
            submit,
            identity,
            kind=kind,
            endpoint=endpoint,
            prompt=body.prompt,
            client_task_id=body.client_task_id or "",
            base64_images=body.base64_images,
            base_url=resolve_image_base_url(request),
        )

    @router.delete("/v1/editable-file-tasks/{task_id}")
    async def delete_editable_file_task(
            task_id: str,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        try:
            return await run_in_threadpool(
                editable_file_task_service.delete_task,
                identity,
                task_id,
            )
        except EditableFileTaskNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": str(exc)},
            ) from exc
        except EditableFileTaskNotTerminalError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": str(exc)},
            ) from exc
        except EditableFileTaskCleanupError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": str(exc)},
            ) from exc

    @router.get("/files/{file_path:path}")
    async def download_editable_file(file_path: str):
        try:
            path = await run_in_threadpool(
                editable_file_task_service.public_file_path,
                file_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"error": "file not found"}) from exc
        return FileResponse(path, filename=path.name)

    @router.post("/v1/ppt/generations")
    async def create_ppt_task(body: EditableFileTaskRequest, request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        await filter_or_log(LoggedCall(identity, "/v1/ppt/generations", "gpt-5-5-thinking", "PPT生成任务", request_text=body.prompt), body.prompt)
        return await submit_editable_file_task(
            editable_file_task_service.submit_ppt,
            identity,
            kind="ppt",
            endpoint="/v1/ppt/generations",
            prompt=body.prompt,
            client_task_id=body.client_task_id or "",
            base64_images=body.base64_images,
            base_url=resolve_image_base_url(request),
        )

    @router.post("/v1/psd/generations")
    async def create_psd_task(body: EditableFileTaskRequest, request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        await filter_or_log(LoggedCall(identity, "/v1/psd/generations", "gpt-5-5-thinking", "PSD生成任务", request_text=body.prompt), body.prompt)
        return await submit_editable_file_task(
            editable_file_task_service.submit_psd,
            identity,
            kind="psd",
            endpoint="/v1/psd/generations",
            prompt=body.prompt,
            client_task_id=body.client_task_id or "",
            base64_images=body.base64_images,
            base_url=resolve_image_base_url(request),
        )

    return router
