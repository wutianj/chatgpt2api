from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool

from api.support import require_user
from contracts.portal import (
    OrderCreateRequest,
    OrderListView,
    OrderView,
    PaymentWebhookRequest,
    PlanListView,
    PricingView,
    RedeemRequest,
    RedeemResult,
    WalletView,
)
from services.payment_service import PaymentConfigurationError, PaymentSignatureError, payment_service
from services.portal_billing import portal_billing
from services.storage.portal_repository import portal_repository


def _user_id(authorization: str | None) -> str:
    identity = require_user(authorization)
    user_id = str(identity.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=403, detail={"error": "需要注册用户会话"})
    return user_id


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/wallet", response_model=WalletView)
    async def wallet(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        user_id = _user_id(authorization)
        wallet_view, ledger = await run_in_threadpool(
            lambda: (portal_repository.get_wallet(user_id), portal_repository.list_ledger(user_id, limit)),
        )
        return {"balance_units": wallet_view["balance_units"], "ledger": ledger}

    @router.get("/api/plans", response_model=PlanListView)
    async def plans():
        return {"items": await run_in_threadpool(portal_repository.list_plans)}

    @router.get("/api/pricing", response_model=PricingView)
    async def pricing():
        return {
            "chat_cost_units": portal_billing.chat_cost_units,
            "image_cost_units": portal_billing.image_cost_units,
            "search_cost_units": portal_billing.search_cost_units,
            "file_cost_units": portal_billing.file_cost_units,
        }

    @router.post("/api/orders", response_model=OrderView, status_code=status.HTTP_201_CREATED)
    async def create_order(
        body: OrderCreateRequest,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        user_id = _user_id(authorization)
        try:
            return await run_in_threadpool(
                portal_repository.create_order,
                user_id=user_id,
                plan_id=body.plan_id,
                provider=body.provider,
                idempotency_key=(idempotency_key or "").strip()[:160] or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/orders", response_model=OrderListView)
    async def list_orders(
        authorization: str | None = Header(default=None),
        order_status: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        user_id = _user_id(authorization)
        return {
            "items": await run_in_threadpool(
                portal_repository.list_orders,
                user_id=user_id,
                status=order_status,
                limit=limit,
            )
        }

    @router.post("/api/redeem", response_model=RedeemResult)
    async def redeem(body: RedeemRequest, authorization: str | None = Header(default=None)):
        user_id = _user_id(authorization)
        try:
            return await run_in_threadpool(portal_repository.redeem, user_id=user_id, code=body.code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/payments/webhook/{provider}")
    async def payment_webhook(
        provider: str,
        request: Request,
        x_payment_signature: str | None = Header(default=None, alias="X-Payment-Signature"),
    ):
        raw_payload = await request.body()
        try:
            payment_service.verify_webhook(raw_payload, x_payment_signature)
            body = PaymentWebhookRequest.model_validate(json.loads(raw_payload.decode("utf-8")))
        except PaymentConfigurationError as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
        except PaymentSignatureError as exc:
            raise HTTPException(status_code=401, detail={"error": str(exc)}) from exc
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"error": "支付回调格式无效"}) from exc

        normalized_provider = provider.strip().lower()
        order = await run_in_threadpool(portal_repository.get_order, body.order_id)
        if order is None:
            raise HTTPException(status_code=404, detail={"error": "订单不存在"})
        if order["provider"] != normalized_provider:
            raise HTTPException(status_code=400, detail={"error": "支付渠道与订单不匹配"})
        payload_hash = hashlib.sha256(raw_payload).hexdigest()
        try:
            should_process = await run_in_threadpool(
                portal_repository.claim_payment_event,
                provider=normalized_provider,
                event_id=body.event_id,
                payload_hash=payload_hash,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        if not should_process:
            return {"ok": True, "duplicate": True, "event_id": body.event_id, "order": order}

        try:
            if body.status == "paid":
                updated = await run_in_threadpool(
                    portal_repository.fulfill_order,
                    order_id=body.order_id,
                    provider_order_id=body.provider_order_id,
                    amount_units=body.amount_units,
                    actor_id=f"payment:{normalized_provider}",
                    actor_role="system",
                )
            elif body.status == "failed":
                updated = await run_in_threadpool(
                    portal_repository.fail_order,
                    order_id=body.order_id,
                    actor_id=f"payment:{normalized_provider}",
                    actor_role="system",
                )
            else:
                updated = await run_in_threadpool(
                    portal_repository.refund_order,
                    order_id=body.order_id,
                    actor_id=f"payment:{normalized_provider}",
                    actor_role="system",
                )
        except ValueError as exc:
            await run_in_threadpool(
                portal_repository.finish_payment_event,
                provider=normalized_provider,
                event_id=body.event_id,
                status="failed",
            )
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        await run_in_threadpool(
            portal_repository.finish_payment_event,
            provider=normalized_provider,
            event_id=body.event_id,
            status="processed",
        )
        return {"ok": True, "duplicate": False, "event_id": body.event_id, "order": updated}

    return router
