from __future__ import annotations

from typing import Literal

from pydantic import Field

from contracts.auth import _StrictModel
from contracts.portal import AuditLogView, OrderView


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
