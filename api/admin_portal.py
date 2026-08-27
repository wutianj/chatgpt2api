from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from api.support import require_admin
from contracts.admin_portal import (
    AdminAuditLogListView,
    AdminOrderListView,
    AdminOrderStatusRequest,
    AdminRedeemCodeDisableRequest,
    AdminRedeemCodeRequest,
    AdminRedeemCodeResult,
    AdminUserCreditRequest,
    AdminUserEnabledRequest,
    AdminUserListView,
    AdminUserView,
)
from contracts.portal import OrderView
from services.storage.portal_repository import portal_repository
from services.storage.user_repository import user_repository


def _admin_user(
    user: dict[str, object],
    balance_units: int,
    usage_summary: dict[str, object] | None = None,
) -> AdminUserView:
    summary = usage_summary or {}
    return AdminUserView(
        id=str(user["id"]),
        email=str(user["email"]),
        display_name=str(user["display_name"]),
        role=str(user["role"]),
        enabled=bool(user["enabled"]),
        balance_units=balance_units,
        usage_count=int(summary.get("usage_count") or 0),
        last_used_at=str(summary["last_used_at"]) if summary.get("last_used_at") else None,
        created_at=str(user["created_at"]),
        last_login_at=str(user["last_login_at"]) if user.get("last_login_at") else None,
    )


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/admin/users", response_model=AdminUserListView)
    async def list_users(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=200, ge=1, le=500),
    ):
        require_admin(authorization)
        users = await run_in_threadpool(user_repository.list_users, limit)
        items = []
        for user in users:
            wallet = await run_in_threadpool(portal_repository.get_wallet, user["id"])
            summary = await run_in_threadpool(portal_repository.usage_summary, user_id=user["id"])
            items.append(_admin_user(user, wallet["balance_units"], summary))
        return {"items": items}

    @router.post("/api/admin/users/{user_id}/credit", response_model=AdminUserView)
    async def credit_user(
        user_id: str,
        body: AdminUserCreditRequest,
        authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        user = await run_in_threadpool(user_repository.get_user_by_id, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail={"error": "用户不存在"})
        await run_in_threadpool(
            portal_repository.credit_wallet,
            user_id=user_id,
            amount_units=body.amount_units,
            entry_type="admin_credit",
            reference_type="admin_note",
            reference_id=body.note,
            idempotency_key=f"admin-credit:{user_id}:{secrets.token_hex(12)}",
        )
        await run_in_threadpool(
            portal_repository.append_audit,
            actor_id=str(admin.get("id") or "admin"),
            actor_role="admin",
            action="user_credit",
            target_type="user",
            target_id=user_id,
            metadata={"amount_units": body.amount_units, "note": body.note},
        )
        wallet = await run_in_threadpool(portal_repository.get_wallet, user_id)
        summary = await run_in_threadpool(portal_repository.usage_summary, user_id=user_id)
        return _admin_user(user, wallet["balance_units"], summary)

    @router.post("/api/admin/users/{user_id}/enabled", response_model=AdminUserView)
    async def set_user_enabled(
        user_id: str,
        body: AdminUserEnabledRequest,
        authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        user = await run_in_threadpool(user_repository.set_user_enabled, user_id=user_id, enabled=body.enabled)
        if user is None:
            raise HTTPException(status_code=404, detail={"error": "用户不存在"})
        await run_in_threadpool(
            portal_repository.append_audit,
            actor_id=str(admin.get("id") or "admin"),
            actor_role="admin",
            action="user_enabled" if body.enabled else "user_disabled",
            target_type="user",
            target_id=user_id,
            metadata={"enabled": body.enabled},
        )
        wallet = await run_in_threadpool(portal_repository.get_wallet, user_id)
        summary = await run_in_threadpool(portal_repository.usage_summary, user_id=user_id)
        return _admin_user(user, wallet["balance_units"], summary)

    @router.post("/api/admin/redeem-codes", response_model=AdminRedeemCodeResult)
    async def create_redeem_codes(
        body: AdminRedeemCodeRequest,
        authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        plans = await run_in_threadpool(portal_repository.list_plans)
        if not any(plan["id"] == body.plan_id for plan in plans):
            raise HTTPException(status_code=404, detail={"error": "套餐不存在"})
        codes: list[str] = []
        for _ in range(body.count):
            raw_code = f"AI-{secrets.token_urlsafe(9).replace('_', '').replace('-', '').upper()}"
            await run_in_threadpool(portal_repository.create_redeem_code, plan_id=body.plan_id, raw_code=raw_code)
            codes.append(raw_code)
        await run_in_threadpool(
            portal_repository.append_audit,
            actor_id=str(admin.get("id") or "admin"),
            actor_role="admin",
            action="redeem_codes_created",
            target_type="plan",
            target_id=body.plan_id,
            metadata={"count": len(codes)},
        )
        return {"plan_id": body.plan_id, "codes": codes}

    @router.post("/api/admin/redeem-codes/disable")
    async def disable_redeem_code(
        body: AdminRedeemCodeDisableRequest,
        authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        try:
            return await run_in_threadpool(
                portal_repository.disable_redeem_code,
                code=body.code,
                actor_id=str(admin.get("id") or "admin"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc

    @router.get("/api/admin/orders", response_model=AdminOrderListView)
    async def list_orders(
        authorization: str | None = Header(default=None),
        order_status: str | None = Query(default=None, alias="status"),
        keyword: str = Query(default="", max_length=160),
        limit: int = Query(default=200, ge=1, le=500),
    ):
        require_admin(authorization)
        return {
            "items": await run_in_threadpool(
                portal_repository.list_admin_orders,
                status=order_status,
                keyword=keyword,
                limit=limit,
            )
        }

    @router.post("/api/admin/orders/{order_id}/status", response_model=OrderView)
    async def update_order_status(
        order_id: str,
        body: AdminOrderStatusRequest,
        authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        actor_id = str(admin.get("id") or "admin")
        try:
            if body.status == "paid":
                return await run_in_threadpool(
                    portal_repository.fulfill_order,
                    order_id=order_id,
                    actor_id=actor_id,
                    actor_role="admin",
                )
            if body.status == "failed":
                return await run_in_threadpool(
                    portal_repository.fail_order,
                    order_id=order_id,
                    actor_id=actor_id,
                    actor_role="admin",
                )
            return await run_in_threadpool(
                portal_repository.refund_order,
                order_id=order_id,
                actor_id=actor_id,
                actor_role="admin",
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc

    @router.get("/api/admin/audit", response_model=AdminAuditLogListView)
    async def list_audit(
        authorization: str | None = Header(default=None),
        action: str | None = Query(default=None, max_length=80),
        limit: int = Query(default=200, ge=1, le=500),
    ):
        require_admin(authorization)
        return {
            "items": await run_in_threadpool(
                portal_repository.list_audit,
                action=action,
                limit=limit,
            )
        }

    return router
