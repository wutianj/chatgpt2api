from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from services.application_database import DatabaseBase, initialize_application_database, resolve_database_url
# Import domain models so foreign-key targets are registered before create_all().
from services.storage.user_repository import UserApiKeyModel, UserModel


CUSTOM_REDEEM_PLAN_ID = "custom"


class UserWalletModel(DatabaseBase):
    __tablename__ = "user_wallets"

    user_id = Column(String(64), ForeignKey("users.id"), primary_key=True)
    balance_units = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class WalletLedgerModel(DatabaseBase):
    __tablename__ = "wallet_ledger"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String(32), nullable=False)
    amount_units = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    reference_type = Column(String(64), nullable=True)
    reference_id = Column(String(128), nullable=True)
    idempotency_key = Column(String(160), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)


class PlanModel(DatabaseBase):
    __tablename__ = "plans"

    id = Column(String(64), primary_key=True)
    name = Column(String(120), nullable=False)
    price_units = Column(Integer, nullable=False)
    credits_units = Column(Integer, nullable=False)
    validity_days = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class OrderModel(DatabaseBase):
    __tablename__ = "orders"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(String(64), ForeignKey("plans.id"), nullable=False, index=True)
    plan_name = Column(String(120), nullable=False)
    amount_units = Column(Integer, nullable=False)
    credits_units = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="created", index=True)
    provider = Column(String(32), nullable=False, default="manual")
    provider_order_id = Column(String(160), unique=True, nullable=True, index=True)
    idempotency_key = Column(String(160), unique=True, nullable=True)
    checkout_url = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class RedeemCodeModel(DatabaseBase):
    __tablename__ = "redeem_codes"

    id = Column(String(64), primary_key=True)
    code_hash = Column(String(128), unique=True, nullable=False, index=True)
    plan_id = Column(String(64), ForeignKey("plans.id"), nullable=False)
    status = Column(String(16), nullable=False, default="available")
    claimed_by = Column(String(64), ForeignKey("users.id"), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class RedeemCodeCreditModel(DatabaseBase):
    __tablename__ = "redeem_code_credits"

    redeem_code_id = Column(String(64), ForeignKey("redeem_codes.id"), primary_key=True)
    credits_units = Column(Integer, nullable=False)


class UserTaskModel(DatabaseBase):
    __tablename__ = "user_tasks"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    api_key_id = Column(String(64), ForeignKey("user_api_keys.id"), nullable=True, index=True)
    task_type = Column(String(32), nullable=False)
    model = Column(String(120), nullable=False)
    status = Column(String(24), nullable=False, index=True)
    request_json = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class UsageRecordModel(DatabaseBase):
    __tablename__ = "usage_records"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    reference_type = Column(String(64), nullable=False)
    reference_id = Column(String(160), nullable=False)
    endpoint = Column(String(160), nullable=True)
    model = Column(String(120), nullable=True)
    units = Column(Integer, nullable=False)
    amount_units = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="reserved", index=True)
    idempotency_key = Column(String(200), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AuditLogModel(DatabaseBase):
    __tablename__ = "portal_audit_logs"

    id = Column(String(64), primary_key=True)
    actor_id = Column(String(64), nullable=False, index=True)
    actor_role = Column(String(16), nullable=False)
    action = Column(String(80), nullable=False, index=True)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(160), nullable=True, index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)


class PaymentEventModel(DatabaseBase):
    __tablename__ = "payment_events"

    id = Column(String(64), primary_key=True)
    event_key = Column(String(220), unique=True, nullable=False, index=True)
    provider = Column(String(32), nullable=False)
    event_id = Column(String(160), nullable=False)
    payload_hash = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="processing", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hash_code(value: str) -> str:
    return hashlib.sha256(value.strip().upper().encode("utf-8")).hexdigest()


class PortalRepository:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or resolve_database_url()
        self.engine = initialize_application_database(self.database_url)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def ensure_default_plans(self) -> None:
        defaults = (
            ("starter", "入门额度", 990, 1000, True),
            ("creator", "创作者额度", 2990, 3500, True),
            ("pro", "专业额度", 6990, 10000, True),
            (CUSTOM_REDEEM_PLAN_ID, "自定义点数", 1, 1, False),
        )
        with self.Session() as session:
            existing = {row.id for row in session.scalars(select(PlanModel)).all()}
            now = _utc_now()
            for plan_id, name, price, credits, enabled in defaults:
                if plan_id not in existing:
                    session.add(PlanModel(
                        id=plan_id,
                        name=name,
                        price_units=price,
                        credits_units=credits,
                        validity_days=0,
                        enabled=enabled,
                        created_at=now,
                    ))
            session.commit()

    def get_wallet(self, user_id: str) -> dict[str, Any]:
        with self.Session() as session:
            wallet = session.get(UserWalletModel, user_id)
            if wallet is None:
                now = _utc_now()
                wallet = UserWalletModel(user_id=user_id, balance_units=0, created_at=now, updated_at=now)
                session.add(wallet)
                session.commit()
            return {"user_id": user_id, "balance_units": int(wallet.balance_units)}

    def list_ledger(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.scalars(
                select(WalletLedgerModel)
                .where(WalletLedgerModel.user_id == user_id)
                .order_by(WalletLedgerModel.created_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
            return [
                {
                    "id": row.id,
                    "entry_type": row.entry_type,
                    "amount_units": int(row.amount_units),
                    "balance_after": int(row.balance_after),
                    "reference_type": row.reference_type,
                    "reference_id": row.reference_id,
                    "created_at": _iso(row.created_at),
                }
                for row in rows
            ]

    def create_order(
        self,
        *,
        user_id: str,
        plan_id: str,
        provider: str = "manual",
        idempotency_key: str | None = None,
        checkout_url: str | None = None,
        expires_in_hours: int = 24,
    ) -> dict[str, Any]:
        self.ensure_default_plans()
        normalized_provider = provider.strip().lower() or "manual"
        if len(normalized_provider) > 32:
            raise ValueError("支付渠道名称过长")
        scoped_idempotency_key = (
            f"{user_id}:{hashlib.sha256(idempotency_key.strip().encode('utf-8')).hexdigest()}"
            if idempotency_key and idempotency_key.strip()
            else None
        )
        with self.Session() as session:
            if scoped_idempotency_key:
                existing = session.scalar(
                    select(OrderModel).where(OrderModel.idempotency_key == scoped_idempotency_key)
                )
                if existing is not None:
                    return self._order_dict(existing)
            plan = session.get(PlanModel, plan_id)
            if plan is None or not bool(plan.enabled):
                raise ValueError("套餐不存在或已下架")
            now = _utc_now()
            row = OrderModel(
                id=f"order_{uuid4().hex}",
                user_id=user_id,
                plan_id=plan.id,
                plan_name=plan.name,
                amount_units=int(plan.price_units),
                credits_units=int(plan.credits_units),
                status="pending",
                provider=normalized_provider,
                checkout_url=(checkout_url or "").strip()[:1000] or None,
                idempotency_key=scoped_idempotency_key,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=max(1, min(int(expires_in_hours), 168))),
            )
            session.add(row)
            self._add_audit(
                session,
                actor_id=user_id,
                actor_role="user",
                action="order_created",
                target_type="order",
                target_id=row.id,
                metadata={"plan_id": row.plan_id, "provider": row.provider},
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if scoped_idempotency_key:
                    existing = session.scalar(
                        select(OrderModel).where(OrderModel.idempotency_key == scoped_idempotency_key)
                    )
                    if existing is not None:
                        return self._order_dict(existing)
                raise
            return self._order_dict(row)

    def list_orders(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.Session() as session:
            statement = select(OrderModel).where(OrderModel.user_id == user_id)
            if status:
                statement = statement.where(OrderModel.status == status)
            rows = session.scalars(
                statement.order_by(OrderModel.created_at.desc()).limit(max(1, min(limit, 200)))
            ).all()
            return [self._order_dict(row) for row in rows]

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.get(OrderModel, order_id)
            return self._order_dict(row) if row is not None else None

    def list_admin_orders(
        self,
        *,
        status: str | None = None,
        keyword: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self.Session() as session:
            statement = select(OrderModel, UserModel.email).join(UserModel, UserModel.id == OrderModel.user_id)
            if status:
                statement = statement.where(OrderModel.status == status)
            normalized_keyword = keyword.strip()
            if normalized_keyword:
                pattern = f"%{normalized_keyword}%"
                statement = statement.where(
                    (OrderModel.id.ilike(pattern))
                    | (OrderModel.provider_order_id.ilike(pattern))
                    | (UserModel.email.ilike(pattern))
                    | (OrderModel.plan_name.ilike(pattern))
                )
            rows = session.execute(
                statement.order_by(OrderModel.created_at.desc()).limit(max(1, min(limit, 500)))
            ).all()
            return [self._order_dict(row, user_email=email) for row, email in rows]

    def fulfill_order(
        self,
        *,
        order_id: str,
        provider_order_id: str | None = None,
        amount_units: int | None = None,
        actor_id: str = "payment-webhook",
        actor_role: str = "system",
    ) -> dict[str, Any]:
        with self.Session() as session:
            row = session.get(OrderModel, order_id)
            if row is None:
                raise ValueError("订单不存在")
            if amount_units is not None and int(amount_units) != int(row.amount_units):
                raise ValueError("订单金额不匹配")
            if row.status == "paid":
                return self._order_dict(row)
            if row.status in {"refunded", "failed", "expired"}:
                raise ValueError(f"订单当前状态不可到账：{row.status}")
            now = _utc_now()
            if row.expires_at and (_as_utc(row.expires_at) or now) <= now:
                row.status = "expired"
                row.updated_at = now
                session.commit()
                raise ValueError("订单已经过期")
            wallet = session.get(UserWalletModel, row.user_id)
            if wallet is None:
                wallet = UserWalletModel(
                    user_id=row.user_id,
                    balance_units=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(wallet)
                session.flush()
            ledger_key = f"order:{row.id}:credit"
            ledger = session.scalar(
                select(WalletLedgerModel).where(WalletLedgerModel.idempotency_key == ledger_key)
            )
            if ledger is None:
                wallet.balance_units += int(row.credits_units)
                wallet.updated_at = now
                ledger = WalletLedgerModel(
                    id=f"ledger_{uuid4().hex}",
                    user_id=row.user_id,
                    entry_type="order_credit",
                    amount_units=int(row.credits_units),
                    balance_after=int(wallet.balance_units),
                    reference_type="order",
                    reference_id=row.id,
                    idempotency_key=ledger_key,
                    created_at=now,
                )
                session.add(ledger)
            row.status = "paid"
            row.provider_order_id = (provider_order_id or row.provider_order_id or "").strip()[:160] or None
            row.paid_at = row.paid_at or now
            row.updated_at = now
            self._add_audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action="order_paid",
                target_type="order",
                target_id=row.id,
                metadata={"user_id": row.user_id, "credits_units": int(row.credits_units)},
            )
            session.commit()
            return self._order_dict(row)

    def fail_order(
        self,
        *,
        order_id: str,
        actor_id: str = "payment-webhook",
        actor_role: str = "system",
    ) -> dict[str, Any]:
        with self.Session() as session:
            row = session.get(OrderModel, order_id)
            if row is None:
                raise ValueError("订单不存在")
            if row.status in {"paid", "refunded"}:
                return self._order_dict(row)
            now = _utc_now()
            row.status = "failed"
            row.updated_at = now
            self._add_audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action="order_failed",
                target_type="order",
                target_id=row.id,
                metadata={"user_id": row.user_id},
            )
            session.commit()
            return self._order_dict(row)

    def refund_order(
        self,
        *,
        order_id: str,
        actor_id: str = "admin",
        actor_role: str = "admin",
    ) -> dict[str, Any]:
        with self.Session() as session:
            row = session.get(OrderModel, order_id)
            if row is None:
                raise ValueError("订单不存在")
            if row.status == "refunded":
                return self._order_dict(row)
            if row.status != "paid":
                raise ValueError("只有已支付订单可以退款")
            now = _utc_now()
            wallet = session.get(UserWalletModel, row.user_id)
            if wallet is None:
                raise ValueError("用户余额不存在")
            ledger_key = f"order:{row.id}:refund"
            existing = session.scalar(
                select(WalletLedgerModel).where(WalletLedgerModel.idempotency_key == ledger_key)
            )
            if existing is None:
                result = session.execute(
                    update(UserWalletModel)
                    .where(
                        UserWalletModel.user_id == row.user_id,
                        UserWalletModel.balance_units >= int(row.credits_units),
                    )
                    .values(
                        balance_units=UserWalletModel.balance_units - int(row.credits_units),
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    raise ValueError("用户当前余额不足，无法自动扣回退款额度")
                session.refresh(wallet)
                session.add(WalletLedgerModel(
                    id=f"ledger_{uuid4().hex}",
                    user_id=row.user_id,
                    entry_type="order_refund",
                    amount_units=-int(row.credits_units),
                    balance_after=int(wallet.balance_units),
                    reference_type="order",
                    reference_id=row.id,
                    idempotency_key=ledger_key,
                    created_at=now,
                ))
            row.status = "refunded"
            row.refunded_at = row.refunded_at or now
            row.updated_at = now
            self._add_audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action="order_refunded",
                target_type="order",
                target_id=row.id,
                metadata={"user_id": row.user_id, "credits_units": int(row.credits_units)},
            )
            session.commit()
            return self._order_dict(row)

    def record_usage(
        self,
        *,
        user_id: str,
        task_id: str | None,
        reference_type: str,
        reference_id: str,
        endpoint: str | None,
        model: str | None,
        units: int,
        amount_units: int,
        status: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self.Session() as session:
            row = session.scalar(
                select(UsageRecordModel).where(UsageRecordModel.idempotency_key == idempotency_key)
            )
            now = _utc_now()
            normalized_status = status if status in {"reserved", "completed", "refunded"} else "reserved"
            if row is None:
                row = UsageRecordModel(
                    id=f"usage_{uuid4().hex}",
                    user_id=user_id,
                    task_id=task_id,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    endpoint=(endpoint or "")[:160] or None,
                    model=(model or "")[:120] or None,
                    units=max(0, int(units)),
                    amount_units=max(0, int(amount_units)),
                    status=normalized_status,
                    idempotency_key=idempotency_key,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                if row.user_id != user_id:
                    raise ValueError("用量幂等键已经属于其他用户")
                current_status = str(row.status or "reserved")
                # Retries must not reopen terminal usage or undo a refund.
                if not (
                    current_status in {"completed", "refunded"}
                    and normalized_status == "reserved"
                ) and not (
                    current_status == "refunded"
                    and normalized_status == "completed"
                ):
                    row.status = normalized_status
                row.updated_at = now
            session.commit()
            return self._usage_dict(row)

    def get_usage(
        self,
        *,
        user_id: str,
        reference_type: str,
        reference_id: str,
    ) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.scalar(
                select(UsageRecordModel).where(
                    UsageRecordModel.user_id == user_id,
                    UsageRecordModel.reference_type == reference_type,
                    UsageRecordModel.reference_id == reference_id,
                )
            )
            return self._usage_dict(row) if row is not None else None

    def list_usage(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.scalars(
                select(UsageRecordModel)
                .where(UsageRecordModel.user_id == user_id)
                .order_by(UsageRecordModel.created_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
            return [self._usage_dict(row) for row in rows]

    def usage_summary(self, *, user_id: str) -> dict[str, Any]:
        with self.Session() as session:
            count, last_used_at = session.execute(
                select(func.count(UsageRecordModel.id), func.max(UsageRecordModel.created_at))
                .where(UsageRecordModel.user_id == user_id)
            ).one()
            return {
                "usage_count": int(count or 0),
                "last_used_at": _iso(last_used_at),
            }

    def append_audit(
        self,
        *,
        actor_id: str,
        actor_role: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.Session() as session:
            row = self._add_audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                metadata=metadata,
            )
            session.commit()
            return self._audit_dict(row)

    def claim_payment_event(
        self,
        *,
        provider: str,
        event_id: str,
        payload_hash: str,
    ) -> bool:
        event_key = f"{provider.strip().lower()}:{event_id.strip()}"
        with self.Session() as session:
            row = session.scalar(
                select(PaymentEventModel).where(PaymentEventModel.event_key == event_key)
            )
            if row is not None:
                if row.payload_hash != payload_hash:
                    raise ValueError("支付事件内容与历史记录不一致")
                return row.status == "failed"
            session.add(PaymentEventModel(
                id=f"payment_event_{uuid4().hex}",
                event_key=event_key,
                provider=provider.strip().lower()[:32],
                event_id=event_id.strip()[:160],
                payload_hash=payload_hash,
                status="processing",
                created_at=_utc_now(),
            ))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True

    def finish_payment_event(self, *, provider: str, event_id: str, status: str) -> None:
        event_key = f"{provider.strip().lower()}:{event_id.strip()}"
        with self.Session() as session:
            row = session.scalar(
                select(PaymentEventModel).where(PaymentEventModel.event_key == event_key)
            )
            if row is None:
                return
            row.status = status if status in {"processed", "failed"} else "failed"
            row.processed_at = _utc_now()
            session.commit()

    def list_audit(
        self,
        *,
        action: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self.Session() as session:
            statement = select(AuditLogModel)
            if action:
                statement = statement.where(AuditLogModel.action == action)
            rows = session.scalars(
                statement.order_by(AuditLogModel.created_at.desc()).limit(max(1, min(limit, 500)))
            ).all()
            return [self._audit_dict(row) for row in rows]

    def credit_wallet(
        self,
        *,
        user_id: str,
        amount_units: int,
        entry_type: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if amount_units <= 0:
            raise ValueError("充值额度必须大于 0")
        with self.Session() as session:
            if idempotency_key:
                previous = session.scalar(
                    select(WalletLedgerModel).where(WalletLedgerModel.idempotency_key == idempotency_key)
                )
                if previous is not None:
                    return self._ledger_dict(previous)
            now = _utc_now()
            wallet = session.get(UserWalletModel, user_id)
            if wallet is None:
                wallet = UserWalletModel(user_id=user_id, balance_units=0, created_at=now, updated_at=now)
                session.add(wallet)
                session.flush()
            wallet.balance_units += amount_units
            wallet.updated_at = now
            row = WalletLedgerModel(
                id=f"ledger_{uuid4().hex}",
                user_id=user_id,
                entry_type=entry_type,
                amount_units=amount_units,
                balance_after=wallet.balance_units,
                reference_type=reference_type,
                reference_id=reference_id,
                idempotency_key=idempotency_key,
                created_at=now,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if idempotency_key:
                    previous = session.scalar(
                        select(WalletLedgerModel).where(WalletLedgerModel.idempotency_key == idempotency_key)
                    )
                    if previous is not None:
                        return self._ledger_dict(previous)
                raise
            return self._ledger_dict(row)

    def debit_wallet(
        self,
        *,
        user_id: str,
        amount_units: int,
        entry_type: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if amount_units <= 0:
            raise ValueError("扣除额度必须大于 0")
        with self.Session() as session:
            if idempotency_key:
                previous = session.scalar(
                    select(WalletLedgerModel).where(WalletLedgerModel.idempotency_key == idempotency_key)
                )
                if previous is not None:
                    return self._ledger_dict(previous)
            now = _utc_now()
            wallet = session.get(UserWalletModel, user_id)
            if wallet is None:
                wallet = UserWalletModel(user_id=user_id, balance_units=0, created_at=now, updated_at=now)
                session.add(wallet)
                session.flush()
            result = session.execute(
                update(UserWalletModel)
                .where(
                    UserWalletModel.user_id == user_id,
                    UserWalletModel.balance_units >= amount_units,
                )
                .values(
                    balance_units=UserWalletModel.balance_units - amount_units,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                raise ValueError("余额不足，请先充值或兑换额度")
            session.refresh(wallet)
            row = WalletLedgerModel(
                id=f"ledger_{uuid4().hex}",
                user_id=user_id,
                entry_type=entry_type,
                amount_units=-amount_units,
                balance_after=wallet.balance_units,
                reference_type=reference_type,
                reference_id=reference_id,
                idempotency_key=idempotency_key,
                created_at=now,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if idempotency_key:
                    previous = session.scalar(
                        select(WalletLedgerModel).where(WalletLedgerModel.idempotency_key == idempotency_key)
                    )
                    if previous is not None:
                        return self._ledger_dict(previous)
                raise
            return self._ledger_dict(row)

    def reserve_usage(
        self,
        *,
        user_id: str,
        task_id: str | None,
        reference_type: str,
        reference_id: str,
        endpoint: str | None,
        model: str | None,
        units: int,
        amount_units: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Atomically claim a usage key and debit its wallet exactly once."""
        if amount_units <= 0:
            raise ValueError("扣除额度必须大于 0")
        with self.Session() as session:
            try:
                if self.engine.dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                existing = session.scalar(
                    select(UsageRecordModel)
                    .where(UsageRecordModel.idempotency_key == idempotency_key)
                    .with_for_update()
                )
                if existing is not None:
                    if existing.user_id != user_id:
                        raise ValueError("用量幂等键已经属于其他用户")
                    session.commit()
                    return {
                        "created": False,
                        "ledger": None,
                        "usage": self._usage_dict(existing),
                    }

                now = _utc_now()
                wallet = session.scalar(
                    select(UserWalletModel)
                    .where(UserWalletModel.user_id == user_id)
                    .with_for_update()
                )
                if wallet is None:
                    wallet = UserWalletModel(
                        user_id=user_id,
                        balance_units=0,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(wallet)
                    session.flush()

                ledger_key = f"usage:{reference_type}:{reference_id}"
                ledger = session.scalar(
                    select(WalletLedgerModel)
                    .where(WalletLedgerModel.idempotency_key == ledger_key)
                    .with_for_update()
                )
                if ledger is None:
                    result = session.execute(
                        update(UserWalletModel)
                        .where(
                            UserWalletModel.user_id == user_id,
                            UserWalletModel.balance_units >= amount_units,
                        )
                        .values(
                            balance_units=UserWalletModel.balance_units - amount_units,
                            updated_at=now,
                        )
                    )
                    if result.rowcount != 1:
                        session.rollback()
                        raise ValueError("余额不足，请先充值或兑换额度")
                    session.refresh(wallet)
                    ledger = WalletLedgerModel(
                        id=f"ledger_{uuid4().hex}",
                        user_id=user_id,
                        entry_type="usage",
                        amount_units=-amount_units,
                        balance_after=wallet.balance_units,
                        reference_type=reference_type,
                        reference_id=reference_id,
                        idempotency_key=ledger_key,
                        created_at=now,
                    )
                    session.add(ledger)
                elif ledger.user_id != user_id:
                    raise ValueError("用量扣费记录已经属于其他用户")

                usage = UsageRecordModel(
                    id=f"usage_{uuid4().hex}",
                    user_id=user_id,
                    task_id=task_id,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    endpoint=(endpoint or "")[:160] or None,
                    model=(model or "")[:120] or None,
                    units=max(0, int(units)),
                    amount_units=max(0, int(amount_units)),
                    status="reserved",
                    idempotency_key=idempotency_key,
                    created_at=now,
                    updated_at=now,
                )
                session.add(usage)
                session.commit()
                return {
                    "created": True,
                    "ledger": self._ledger_dict(ledger),
                    "usage": self._usage_dict(usage),
                }
            except IntegrityError:
                # PostgreSQL can observe the same idempotency key concurrently.
                # The losing transaction must reuse the committed usage record
                # instead of surfacing a duplicate-key 500 to the caller.
                session.rollback()
                existing = session.scalar(
                    select(UsageRecordModel).where(
                        UsageRecordModel.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    if existing.user_id != user_id:
                        raise ValueError("用量幂等键已经属于其他用户")
                    return {
                        "created": False,
                        "ledger": None,
                        "usage": self._usage_dict(existing),
                    }
                raise
            except Exception:
                session.rollback()
                raise

    def list_plans(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        self.ensure_default_plans()
        with self.Session() as session:
            query = select(PlanModel)
            if not include_disabled:
                query = query.where(PlanModel.enabled.is_(True))
            return [self._plan_dict(row) for row in session.scalars(query.order_by(PlanModel.price_units)).all()]

    def upsert_plan(
        self,
        *,
        plan_id: str,
        name: str,
        price_units: int,
        credits_units: int,
        validity_days: int = 0,
        enabled: bool = True,
    ) -> dict[str, Any]:
        normalized_id = plan_id.strip().lower()
        normalized_name = name.strip()
        if normalized_id == CUSTOM_REDEEM_PLAN_ID:
            raise ValueError("自定义点数是系统兑换码类型，不能作为套餐编辑")
        if not normalized_id or len(normalized_id) > 64:
            raise ValueError("套餐 ID 无效")
        if not normalized_name or len(normalized_name) > 120:
            raise ValueError("套餐名称无效")
        if price_units <= 0 or credits_units <= 0 or validity_days < 0:
            raise ValueError("套餐价格、额度必须大于 0，有效期不能为负数")
        with self.Session() as session:
            row = session.get(PlanModel, normalized_id)
            now = _utc_now()
            if row is None:
                row = PlanModel(
                    id=normalized_id,
                    name=normalized_name,
                    price_units=price_units,
                    credits_units=credits_units,
                    validity_days=validity_days,
                    enabled=enabled,
                    created_at=now,
                )
                session.add(row)
            else:
                row.name = normalized_name
                row.price_units = price_units
                row.credits_units = credits_units
                row.validity_days = validity_days
                row.enabled = enabled
            session.commit()
            return self._plan_dict(row)

    def create_redeem_code(
        self,
        *,
        plan_id: str,
        raw_code: str,
        expires_at: datetime | None = None,
        credits_units: int | None = None,
    ) -> dict[str, Any]:
        normalized = raw_code.strip().upper()
        if len(normalized) < 4:
            raise ValueError("兑换码至少需要 4 位")
        normalized_credits: int | None = None
        if credits_units is not None:
            normalized_credits = int(credits_units)
            if normalized_credits <= 0 or normalized_credits > 1_000_000_000:
                raise ValueError("自定义点数必须在 1 到 1,000,000,000 之间")
            plan_id = CUSTOM_REDEEM_PLAN_ID
        self.ensure_default_plans()
        with self.Session() as session:
            if session.get(PlanModel, plan_id) is None:
                raise ValueError("套餐不存在")
            row = RedeemCodeModel(
                id=f"redeem_{uuid4().hex}",
                code_hash=_hash_code(normalized),
                plan_id=plan_id,
                status="available",
                expires_at=expires_at,
                created_at=_utc_now(),
            )
            session.add(row)
            session.flush()
            if normalized_credits is not None:
                session.add(RedeemCodeCreditModel(
                    redeem_code_id=row.id,
                    credits_units=normalized_credits,
                ))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("兑换码已经存在") from exc
            return {
                "id": row.id,
                "plan_id": row.plan_id,
                "credits_units": normalized_credits,
                "status": row.status,
                "expires_at": _iso(row.expires_at),
            }

    def redeem(self, *, user_id: str, code: str) -> dict[str, Any]:
        normalized = code.strip().upper()
        if not normalized:
            raise ValueError("请输入兑换码")
        with self.Session() as session:
            row = session.scalar(select(RedeemCodeModel).where(RedeemCodeModel.code_hash == _hash_code(normalized)))
            if row is None or row.status != "available":
                raise ValueError("兑换码无效或已经使用")
            now = _utc_now()
            if row.expires_at and (_as_utc(row.expires_at) or now) <= now:
                row.status = "expired"
                session.commit()
                raise ValueError("兑换码已经过期")
            plan = session.get(PlanModel, row.plan_id)
            if plan is None or (not bool(plan.enabled) and plan.id != CUSTOM_REDEEM_PLAN_ID):
                raise ValueError("兑换套餐不可用")
            override = session.get(RedeemCodeCreditModel, row.id)
            credits_units = int(override.credits_units) if override is not None else int(plan.credits_units)
            claim = session.execute(
                update(RedeemCodeModel)
                .where(
                    RedeemCodeModel.id == row.id,
                    RedeemCodeModel.status == "available",
                )
                .values(
                    status="claimed",
                    claimed_by=user_id,
                    claimed_at=now,
                )
            )
            if claim.rowcount != 1:
                session.rollback()
                raise ValueError("兑换码无效或已经使用")
            wallet = session.get(UserWalletModel, user_id)
            if wallet is None:
                wallet = UserWalletModel(user_id=user_id, balance_units=0, created_at=now, updated_at=now)
                session.add(wallet)
                session.flush()
            wallet.balance_units += credits_units
            wallet.updated_at = now
            session.refresh(row)
            ledger = WalletLedgerModel(
                id=f"ledger_{uuid4().hex}",
                user_id=user_id,
                entry_type="redeem",
                amount_units=credits_units,
                balance_after=wallet.balance_units,
                reference_type="redeem_code",
                reference_id=row.id,
                idempotency_key=f"redeem:{row.id}",
                created_at=now,
            )
            session.add(ledger)
            self._add_audit(
                session,
                actor_id=user_id,
                actor_role="user",
                action="redeem_claimed",
                target_type="redeem_code",
                target_id=row.id,
                metadata={"plan_id": plan.id, "credits_units": credits_units},
            )
            session.commit()
            plan_view = self._plan_dict(plan)
            plan_view["credits_units"] = credits_units
            return {"plan": plan_view, "balance_units": int(wallet.balance_units)}

    def disable_redeem_code(self, *, code: str, actor_id: str = "admin") -> dict[str, Any]:
        normalized = code.strip().upper()
        if not normalized:
            raise ValueError("请输入兑换码")
        with self.Session() as session:
            row = session.scalar(
                select(RedeemCodeModel).where(RedeemCodeModel.code_hash == _hash_code(normalized))
            )
            if row is None:
                raise ValueError("兑换码不存在")
            if row.status != "available":
                raise ValueError("只有未使用兑换码可以禁用")
            row.status = "disabled"
            self._add_audit(
                session,
                actor_id=actor_id,
                actor_role="admin",
                action="redeem_code_disabled",
                target_type="redeem_code",
                target_id=row.id,
                metadata={},
            )
            session.commit()
            return {"id": row.id, "status": row.status}

    def create_task(
        self,
        *,
        task_id: str,
        user_id: str,
        api_key_id: str | None,
        task_type: str,
        model: str,
        request: dict[str, Any],
        status: str = "queued",
    ) -> dict[str, Any]:
        with self.Session() as session:
            existing = session.get(UserTaskModel, task_id)
            if existing is not None:
                return self._task_dict(existing)
            row = UserTaskModel(
                id=task_id,
                user_id=user_id,
                api_key_id=api_key_id,
                task_type=task_type,
                model=model,
                status=status,
                request_json=json.dumps(request, ensure_ascii=False, default=str),
                created_at=_utc_now(),
            )
            session.add(row)
            session.commit()
            return self._task_dict(row)

    def update_task(
        self,
        *,
        user_id: str,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.scalar(select(UserTaskModel).where(UserTaskModel.id == task_id, UserTaskModel.user_id == user_id))
            if row is None:
                return None
            if row.status == "cancelled" and status != "cancelled":
                return self._task_dict(row)
            row.status = status
            row.error_code = error_code
            if result is not None:
                row.result_json = json.dumps(result, ensure_ascii=False, default=str)
            if status in {"success", "failed", "cancelled"}:
                row.completed_at = _utc_now()
            session.commit()
            return self._task_dict(row)

    def list_tasks(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.scalars(
                select(UserTaskModel)
                .where(UserTaskModel.user_id == user_id)
                .order_by(UserTaskModel.created_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
            return [self._task_dict(row) for row in rows]

    def get_task(self, *, user_id: str, task_id: str) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.scalar(select(UserTaskModel).where(UserTaskModel.id == task_id, UserTaskModel.user_id == user_id))
            return self._task_dict(row) if row else None

    def cancel_task(self, *, user_id: str, task_id: str) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.scalar(select(UserTaskModel).where(UserTaskModel.id == task_id, UserTaskModel.user_id == user_id))
            if row is None:
                return None
            if row.status in {"success", "failed", "cancelled"}:
                return self._task_dict(row)
            row.status = "cancelled"
            row.completed_at = _utc_now()
            session.commit()
            return self._task_dict(row)

    @staticmethod
    def _ledger_dict(row: WalletLedgerModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "entry_type": row.entry_type,
            "amount_units": int(row.amount_units),
            "balance_after": int(row.balance_after),
            "reference_type": row.reference_type,
            "reference_id": row.reference_id,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _plan_dict(row: PlanModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "price_units": int(row.price_units),
            "credits_units": int(row.credits_units),
            "validity_days": int(row.validity_days),
            "enabled": bool(row.enabled),
        }

    @staticmethod
    def _order_dict(
        row: OrderModel,
        *,
        user_email: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "user_email": user_email,
            "plan_id": row.plan_id,
            "plan_name": row.plan_name,
            "amount_units": int(row.amount_units),
            "credits_units": int(row.credits_units),
            "status": row.status,
            "provider": row.provider,
            "provider_order_id": row.provider_order_id,
            "checkout_url": row.checkout_url,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "paid_at": _iso(row.paid_at),
            "refunded_at": _iso(row.refunded_at),
            "expires_at": _iso(row.expires_at),
        }

    @staticmethod
    def _usage_dict(row: UsageRecordModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "task_id": row.task_id,
            "reference_type": row.reference_type,
            "reference_id": row.reference_id,
            "endpoint": row.endpoint,
            "model": row.model,
            "units": int(row.units),
            "amount_units": int(row.amount_units),
            "status": row.status,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    @staticmethod
    def _audit_dict(row: AuditLogModel) -> dict[str, Any]:
        try:
            metadata = json.loads(row.metadata_json)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return {
            "id": row.id,
            "actor_id": row.actor_id,
            "actor_role": row.actor_role,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _add_audit(
        session,
        *,
        actor_id: str,
        actor_role: str,
        action: str,
        target_type: str,
        target_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> AuditLogModel:
        row = AuditLogModel(
            id=f"audit_{uuid4().hex}",
            actor_id=str(actor_id or "system")[:64],
            actor_role=str(actor_role or "system")[:16],
            action=str(action or "unknown")[:80],
            target_type=str(target_type or "unknown")[:64],
            target_id=str(target_id)[:160] if target_id is not None else None,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
            created_at=_utc_now(),
        )
        session.add(row)
        return row

    @staticmethod
    def _task_dict(row: UserTaskModel) -> dict[str, Any]:
        try:
            request = json.loads(row.request_json)
        except (TypeError, json.JSONDecodeError):
            request = {}
        try:
            result = json.loads(row.result_json) if row.result_json else None
        except (TypeError, json.JSONDecodeError):
            result = None
        return {
            "id": row.id,
            "task_type": row.task_type,
            "model": row.model,
            "status": row.status,
            "request": request,
            "result": result,
            "error_code": row.error_code,
            "created_at": _iso(row.created_at),
            "completed_at": _iso(row.completed_at),
        }


portal_repository = PortalRepository()
