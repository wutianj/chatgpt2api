from __future__ import annotations

import os
from typing import Any

from services.storage.portal_repository import portal_repository


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


class PortalBillingService:
    """Keeps portal pricing deterministic until a configurable pricing table is added."""

    def __init__(self) -> None:
        self.chat_cost_units = _positive_int("CHATGPT2API_CHAT_COST_UNITS", 1)
        self.search_cost_units = _positive_int("CHATGPT2API_SEARCH_COST_UNITS", 2)
        self.image_cost_units = _positive_int("CHATGPT2API_IMAGE_COST_UNITS", 10)
        self.file_cost_units = _positive_int("CHATGPT2API_FILE_COST_UNITS", 20)

    def cost_for_endpoint(self, endpoint: str, *, count: int = 1) -> int:
        normalized = str(endpoint or "").strip().lower()
        if "/images/" in normalized:
            return self.image_cost_units * max(1, min(int(count), 4))
        if "editable-file" in normalized or "/ppt/" in normalized or "/psd/" in normalized:
            return self.file_cost_units
        if normalized.endswith("/search"):
            return self.search_cost_units
        return self.chat_cost_units

    def cost_for_task(self, task_type: str, *, count: int = 1) -> int:
        normalized = str(task_type or "chat").strip().lower()
        if normalized == "image":
            return self.image_cost_units * max(1, min(int(count), 4))
        if normalized == "file":
            return self.file_cost_units
        if normalized == "search":
            return self.search_cost_units
        return self.chat_cost_units

    @staticmethod
    def user_id(identity: dict[str, object]) -> str:
        return str(identity.get("user_id") or "").strip()

    def reserve(
        self,
        identity: dict[str, object],
        *,
        amount_units: int,
        reference_type: str,
        reference_id: str,
        endpoint: str | None = None,
        model: str | None = None,
        task_id: str | None = None,
        units: int = 1,
    ) -> dict[str, Any] | None:
        user_id = self.user_id(identity)
        if not user_id:
            return None
        return portal_repository.reserve_usage(
            user_id=user_id,
            task_id=task_id or reference_id,
            reference_type=reference_type,
            reference_id=reference_id,
            endpoint=endpoint,
            model=model,
            units=units,
            amount_units=amount_units,
            idempotency_key=f"usage-record:{reference_type}:{reference_id}",
        )

    def refund(
        self,
        identity: dict[str, object],
        *,
        amount_units: int,
        reference_type: str,
        reference_id: str,
    ) -> dict[str, Any] | None:
        user_id = self.user_id(identity)
        if not user_id or amount_units <= 0:
            return None
        ledger = portal_repository.credit_wallet(
            user_id=user_id,
            amount_units=amount_units,
            entry_type="refund",
            reference_type=reference_type,
            reference_id=reference_id,
            idempotency_key=f"refund:{reference_type}:{reference_id}",
        )
        portal_repository.record_usage(
            user_id=user_id,
            task_id=reference_id,
            reference_type=reference_type,
            reference_id=reference_id,
            endpoint=None,
            model=None,
            units=0,
            amount_units=amount_units,
            status="refunded",
            idempotency_key=f"usage-record:{reference_type}:{reference_id}",
        )
        return ledger

    def complete(
        self,
        identity: dict[str, object],
        *,
        reference_type: str,
        reference_id: str,
    ) -> dict[str, Any] | None:
        user_id = self.user_id(identity)
        if not user_id:
            return None
        usage = portal_repository.get_usage(
            user_id=user_id,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        if usage is None:
            return None
        return portal_repository.record_usage(
            user_id=user_id,
            task_id=usage.get("task_id"),
            reference_type=reference_type,
            reference_id=reference_id,
            endpoint=usage.get("endpoint"),
            model=usage.get("model"),
            units=int(usage.get("units") or 0),
            amount_units=int(usage.get("amount_units") or 0),
            status="completed",
            idempotency_key=f"usage-record:{reference_type}:{reference_id}",
        )

    def refund_reserved(
        self,
        identity: dict[str, object],
        *,
        reference_type: str,
        reference_id: str,
    ) -> dict[str, Any] | None:
        user_id = self.user_id(identity)
        if not user_id:
            return None
        usage = portal_repository.get_usage(
            user_id=user_id,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        if usage is None or usage.get("status") != "reserved":
            return None
        return self.refund(
            identity,
            amount_units=int(usage.get("amount_units") or 0),
            reference_type=reference_type,
            reference_id=reference_id,
        )


portal_billing = PortalBillingService()
