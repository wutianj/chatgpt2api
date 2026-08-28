from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from api.support import require_user
from contracts.portal import UserTaskCancelResult, UserTaskListView, UserTaskView
from services.editable_file_task_service import editable_file_task_service
from services.portal_billing import portal_billing
from services.portal_file_tasks import sync_portal_file_task
from services.portal_file_tasks import file_task_reference
from services.storage.portal_repository import portal_repository


def _identity(authorization: str | None) -> dict[str, object]:
    identity = require_user(authorization)
    user_id = str(identity.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=403, detail={"error": "需要注册用户会话"})
    return identity


def _user_id(authorization: str | None) -> str:
    return str(_identity(authorization)["user_id"])


async def _sync_file_tasks(identity: dict[str, object], items: list[dict[str, object]]) -> None:
    source_items = []
    for item in items:
        if item.get("task_type") != "file":
            continue
        request = item.get("request") if isinstance(item.get("request"), dict) else {}
        source_id = str(request.get("source_task_id") or "").strip()
        kind = str(request.get("kind") or "").strip().lower()
        if source_id and kind in {"ppt", "psd"}:
            source_items.append((source_id, kind, str(request.get("prompt") or "文件任务")))
    if not source_items:
        return
    page = await run_in_threadpool(
        editable_file_task_service.list_tasks,
        identity,
        [source_id for source_id, _, _ in source_items],
        limit=len(source_items),
    )
    by_id = {str(item.get("id") or ""): item for item in page.get("items", [])}
    for source_id, kind, prompt in source_items:
        source_item = by_id.get(source_id)
        if source_item is None:
            continue
        await run_in_threadpool(
            sync_portal_file_task,
            identity,
            source_item,
            kind=kind,
            prompt=prompt,
        )


async def _refund_cancelled_task(identity: dict[str, object], item: dict[str, object]) -> None:
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    reference_type = str(request.get("billing_reference_type") or "").strip()
    reference_id = str(request.get("billing_reference_id") or "").strip()
    if not reference_type or not reference_id:
        task_type = str(item.get("task_type") or "").strip().lower()
        if task_type == "chat" and str(item.get("id") or "").startswith("call_"):
            reference_type = "api_call"
            reference_id = str(item["id"])[len("call_"):]
        elif task_type == "image":
            reference_type = "image_task"
            reference_id = f"{identity.get('user_id', '')}:{request.get('source_task_id', '')}"
        elif task_type == "file":
            kind = str(request.get("kind") or "").strip().lower()
            source_id = str(request.get("source_task_id") or "").strip()
            if kind in {"ppt", "psd"} and source_id:
                reference_type = "file_task"
                reference_id = file_task_reference(str(identity.get("user_id") or ""), kind, source_id)
    if not reference_type or not reference_id:
        return
    await run_in_threadpool(
        portal_billing.refund_reserved,
        identity,
        reference_type=reference_type,
        reference_id=reference_id,
    )


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/tasks", response_model=UserTaskListView)
    async def list_tasks(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        identity = _identity(authorization)
        user_id = str(identity["user_id"])
        items = await run_in_threadpool(portal_repository.list_tasks, user_id, limit)
        await _sync_file_tasks(identity, items)
        return {"items": await run_in_threadpool(portal_repository.list_tasks, user_id, limit)}

    @router.get("/api/tasks/{task_id}", response_model=UserTaskView)
    async def get_task(task_id: str, authorization: str | None = Header(default=None)):
        identity = _identity(authorization)
        item = await run_in_threadpool(
            portal_repository.get_task,
            user_id=str(identity["user_id"]),
            task_id=task_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "任务不存在"})
        await _sync_file_tasks(identity, [item])
        return await run_in_threadpool(
            portal_repository.get_task,
            user_id=str(identity["user_id"]),
            task_id=task_id,
        ) or item

    @router.post("/api/tasks/{task_id}/cancel", response_model=UserTaskCancelResult)
    async def cancel_task(task_id: str, authorization: str | None = Header(default=None)):
        identity = _identity(authorization)
        item = await run_in_threadpool(
            portal_repository.cancel_task,
            user_id=str(identity["user_id"]),
            task_id=task_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "任务不存在"})
        if item.get("status") == "cancelled":
            await _refund_cancelled_task(identity, item)
        return {"item": item}

    return router
