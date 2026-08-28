from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from contracts.auth import _StrictModel


class WalletLedgerView(_StrictModel):
    id: str
    entry_type: str
    amount_units: int
    balance_after: int
    reference_type: str | None = None
    reference_id: str | None = None
    created_at: str | None = None


class WalletView(_StrictModel):
    balance_units: int
    ledger: list[WalletLedgerView] = Field(default_factory=list)


class PlanView(_StrictModel):
    id: str
    name: str
    price_units: int
    credits_units: int
    validity_days: int
    enabled: bool = True


class PlanListView(_StrictModel):
    items: list[PlanView] = Field(default_factory=list)


class PricingView(_StrictModel):
    chat_cost_units: int
    image_cost_units: int
    image_1k_cost_units: int
    image_2k_cost_units: int
    image_4k_cost_units: int
    image_4k_enabled: bool
    search_cost_units: int
    file_cost_units: int


class RedeemRequest(_StrictModel):
    code: str = Field(min_length=4, max_length=128)


class RedeemResult(_StrictModel):
    plan: PlanView
    balance_units: int


OrderStatus = Literal["created", "pending", "paid", "failed", "refunded", "expired"]


class OrderView(_StrictModel):
    id: str
    user_id: str | None = None
    user_email: str | None = None
    plan_id: str
    plan_name: str
    amount_units: int
    credits_units: int
    status: OrderStatus
    provider: str
    provider_order_id: str | None = None
    checkout_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    paid_at: str | None = None
    refunded_at: str | None = None
    expires_at: str | None = None


class OrderListView(_StrictModel):
    items: list[OrderView] = Field(default_factory=list)


class OrderCreateRequest(_StrictModel):
    plan_id: str = Field(min_length=1, max_length=64)
    provider: str = Field(default="manual", min_length=1, max_length=32)


class UsageView(_StrictModel):
    id: str
    task_id: str | None = None
    reference_type: str
    reference_id: str
    endpoint: str | None = None
    model: str | None = None
    units: int
    amount_units: int
    status: Literal["reserved", "completed", "refunded"]
    created_at: str | None = None
    updated_at: str | None = None


class UsageListView(_StrictModel):
    items: list[UsageView] = Field(default_factory=list)


class PaymentWebhookRequest(_StrictModel):
    event_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=64)
    status: Literal["paid", "failed", "refunded"]
    amount_units: int | None = Field(default=None, ge=0)
    provider_order_id: str | None = Field(default=None, max_length=160)


class AuditLogView(_StrictModel):
    id: str
    actor_id: str
    actor_role: str
    action: str
    target_type: str
    target_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class AuditLogListView(_StrictModel):
    items: list[AuditLogView] = Field(default_factory=list)


class UserTaskView(_StrictModel):
    id: str
    task_type: str
    model: str
    status: str
    request: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    error_code: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class UserTaskListView(_StrictModel):
    items: list[UserTaskView] = Field(default_factory=list)


class UserTaskCancelResult(_StrictModel):
    item: UserTaskView
