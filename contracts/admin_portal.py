from __future__ import annotations

from typing import Literal

from pydantic import Field

from contracts.auth import _StrictModel
from contracts.portal import AuditLogView, OrderView, PlanView


class AdminUserView(_StrictModel):
    id: str
    email: str
    display_name: str
    role: str
    enabled: bool
    balance_units: int
    usage_count: int = 0
    last_used_at: str | None = None
    created_at: str
    last_login_at: str | None = None


class AdminUserListView(_StrictModel):
    items: list[AdminUserView] = Field(default_factory=list)


class AdminUserCreditRequest(_StrictModel):
    amount_units: int = Field(gt=0, le=10_000_000)
    note: str = Field(default="管理员调整", max_length=160)


class AdminUserEnabledRequest(_StrictModel):
    enabled: bool


class AdminRedeemCodeRequest(_StrictModel):
    plan_id: str = Field(min_length=1, max_length=64)
    count: int = Field(default=1, ge=1, le=50)
    credits_units: int | None = Field(default=None, gt=0, le=1_000_000_000)


class AdminRedeemCodeResult(_StrictModel):
    plan_id: str
    codes: list[str]


class AdminRedeemCodeDisableRequest(_StrictModel):
    code: str = Field(min_length=4, max_length=128)


class AdminOrderListView(_StrictModel):
    items: list[OrderView] = Field(default_factory=list)


class AdminOrderStatusRequest(_StrictModel):
    status: Literal["paid", "failed", "refunded"]


class AdminAuditLogListView(_StrictModel):
    items: list[AuditLogView] = Field(default_factory=list)


class AdminPlanUpsertRequest(_StrictModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    price_units: int = Field(gt=0, le=100_000_000)
    credits_units: int = Field(gt=0, le=1_000_000_000)
    validity_days: int = Field(default=0, ge=0, le=3650)
    enabled: bool = True


class AdminPlanListView(_StrictModel):
    items: list[PlanView] = Field(default_factory=list)


class AdminPricingUpdateRequest(_StrictModel):
    chat_cost_units: int = Field(gt=0, le=1_000_000)
    image_1k_cost_units: int = Field(gt=0, le=1_000_000)
    image_2k_cost_units: int = Field(gt=0, le=1_000_000)
    image_4k_cost_units: int = Field(gt=0, le=1_000_000)
    image_4k_enabled: bool = False
    search_cost_units: int = Field(gt=0, le=1_000_000)
    file_cost_units: int = Field(gt=0, le=1_000_000)
