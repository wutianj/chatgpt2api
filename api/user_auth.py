from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from api.support import extract_bearer_token, require_identity
from contracts.user_auth import (
    RegisteredUserView,
    UserLoginRequest,
    UserProfileView,
    UserRegisterRequest,
    UserSessionView,
)
from services.user_auth_service import user_auth_service


def _session_view(token: str, user: dict[str, object]) -> UserSessionView:
    return UserSessionView(
        access_token=token,
        user=RegisteredUserView(**user),
    )


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/auth/register", response_model=UserSessionView, status_code=status.HTTP_201_CREATED)
    async def register(body: UserRegisterRequest):
        try:
            token, user = await run_in_threadpool(
                user_auth_service.register,
                email=body.email,
                password=body.password,
                display_name=body.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return _session_view(token, user)

    @router.post("/api/auth/login", response_model=UserSessionView)
    async def login(body: UserLoginRequest):
        try:
            token, user = await run_in_threadpool(
                user_auth_service.login,
                email=body.email,
                password=body.password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=401, detail={"error": str(exc)}) from exc
        return _session_view(token, user)

    @router.get("/api/auth/session", response_model=UserProfileView)
    async def session(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        user_id = str(identity.get("user_id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=403, detail={"error": "需要注册用户会话"})
        user = await run_in_threadpool(user_auth_service.get_user, user_id)
        if user is None:
            raise HTTPException(status_code=401, detail={"error": "用户会话已失效"})
        return UserProfileView(user=RegisteredUserView(**user))

    @router.post("/api/auth/logout")
    async def logout(authorization: str | None = Header(default=None)):
        token = extract_bearer_token(authorization)
        await run_in_threadpool(user_auth_service.logout, token)
        return {"ok": True}

    return router
