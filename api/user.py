from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from api.support import require_user
from contracts.auth import UserKeyCreateRequest, UserKeyDeleteResult, UserKeyListView, UserKeyView
from contracts.portal import UsageListView
from contracts.user_auth import RegisteredUserView, UserProfileView
from services.storage.portal_repository import portal_repository
from services.user_auth_service import user_auth_service


def _user_id(identity: dict[str, object]) -> str:
    value = str(identity.get("user_id") or "").strip()
    if not value:
        raise HTTPException(status_code=403, detail={"error": "需要注册用户会话"})
    return value


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/user/profile", response_model=UserProfileView)
    async def profile(authorization: str | None = Header(default=None)):
        identity = require_user(authorization)
        user = await run_in_threadpool(user_auth_service.get_user, _user_id(identity))
        if user is None:
            raise HTTPException(status_code=401, detail={"error": "用户会话已失效"})
        return {"user": RegisteredUserView(**user)}

    @router.get("/api/user/keys", response_model=UserKeyListView)
    async def list_keys(authorization: str | None = Header(default=None)):
        identity = require_user(authorization)
        items = await run_in_threadpool(user_auth_service.list_api_keys, _user_id(identity))
        return {"items": items}

    @router.post("/api/user/keys", status_code=status.HTTP_201_CREATED)
    async def create_key(
        body: UserKeyCreateRequest,
        authorization: str | None = Header(default=None),
    ):
        identity = require_user(authorization)
        try:
            raw_key, item = await run_in_threadpool(
                user_auth_service.create_api_key,
                user_id=_user_id(identity),
                name=body.name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        await run_in_threadpool(
            portal_repository.append_audit,
            actor_id=_user_id(identity),
            actor_role="user",
            action="user_api_key_created",
            target_type="user_api_key",
            target_id=str(item["id"]),
            metadata={"name": item["name"]},
        )
        return {"item": UserKeyView(**item), "raw_key": raw_key}

    @router.delete("/api/user/keys/{key_id}", response_model=UserKeyDeleteResult)
    async def revoke_key(key_id: str, authorization: str | None = Header(default=None)):
        identity = require_user(authorization)
        deleted = await run_in_threadpool(
            user_auth_service.revoke_api_key,
            user_id=_user_id(identity),
            key_id=key_id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail={"error": "这条用户密钥不存在或已经被撤销"})
        await run_in_threadpool(
            portal_repository.append_audit,
            actor_id=_user_id(identity),
            actor_role="user",
            action="user_api_key_revoked",
            target_type="user_api_key",
            target_id=key_id,
        )
        return {"deleted_id": key_id}

    @router.get("/api/user/usage", response_model=UsageListView)
    async def usage(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        identity = require_user(authorization)
        return {
            "items": await run_in_threadpool(
                portal_repository.list_usage,
                user_id=_user_id(identity),
                limit=limit,
            )
        }

    return router
