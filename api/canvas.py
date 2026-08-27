from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from api.support import extract_bearer_token, require_identity, resolve_image_base_url
from contracts.canvas import CanvasSessionView
from services.canvas_token_service import canvas_token_service
from services.storage.portal_repository import portal_repository


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/integrations/infinite-canvas/session", response_model=CanvasSessionView)
    async def create_canvas_session(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        role = str(identity.get("role") or "").strip().lower()
        user_id = str(identity.get("user_id") or identity.get("id") or "").strip()
        if role not in {"user", "admin"} or not user_id:
            raise HTTPException(status_code=403, detail={"error": "需要注册用户会话"})
        try:
            return await run_in_threadpool(canvas_token_service.issue, user_id=user_id, role=role)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc

    @router.get("/api/canvas/session")
    async def get_legacy_canvas_session(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        """Serve the session shape expected by the previously deployed canvas build."""
        token = extract_bearer_token(authorization)
        identity = canvas_token_service.authenticate(token)
        if identity is None:
            identity = require_identity(authorization)

        role = str(identity.get("role") or "").strip()
        if role not in {"user", "admin"}:
            raise HTTPException(status_code=403, detail={"error": "需要用户权限"})

        user_id = str(identity.get("user_id") or identity.get("id") or "").strip()
        balance_units = 0
        if role == "user" and user_id:
            wallet = await run_in_threadpool(portal_repository.get_wallet, user_id)
            balance_units = int(wallet["balance_units"])

        return {
            "data": {
                "id": user_id or "admin",
                "username": str(identity.get("name") or "").strip(),
                "email": str(identity.get("email") or "").strip(),
                "role": role,
                "balance_usd_cents": balance_units,
                "can_manage_updates": role == "admin",
                "portal_url": resolve_image_base_url(request),
            }
        }

    return router
