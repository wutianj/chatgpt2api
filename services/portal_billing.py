from __future__ import annotations

import os
import re
from typing import Any

from services.config import config
from services.storage.portal_repository import portal_repository


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


class UnsupportedImageResolutionError(ValueError):
    """Raised before reservation when a configured image tier is disabled."""


def _boolean(name: str, default: bool = False) -> bool:
    value = str(os.getenv(name, "true" if default else "false")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _configured_portal_billing() -> dict[str, object]:
    raw = getattr(config, "data", {}).get("portal_billing")
    return raw if isinstance(raw, dict) else {}


class PortalBillingService:
    """Keeps portal pricing deterministic until a configurable pricing table is added."""

    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        configured = config.get_portal_billing_settings()
        configured_raw = _configured_portal_billing()

        def configured_or_env(
            key: str,
            env_name: str,
            legacy_env_name: str | None = None,
            *,
            allow_env_when_configured: bool = True,
        ) -> int:
            if key in configured_raw and not allow_env_when_configured:
                return max(1, int(configured[key]))
            fallback = configured[key]
            if key not in configured_raw and legacy_env_name:
                fallback = os.getenv(legacy_env_name, str(fallback))
            return _positive_int(env_name, int(fallback))

        self.chat_cost_units = configured_or_env(
            "chat_cost_units",
            "CHATGPT2API_CHAT_COST_UNITS",
            allow_env_when_configured=False,
        )
        self.search_cost_units = configured_or_env(
            "search_cost_units",
            "CHATGPT2API_SEARCH_COST_UNITS",
            allow_env_when_configured=False,
        )
        legacy_image_cost = configured_or_env(
            "image_1k_cost_units",
            "CHATGPT2API_IMAGE_1K_COST_UNITS",
            "CHATGPT2API_IMAGE_COST_UNITS",
        )
        self.image_1k_cost_units = _positive_int(
            "CHATGPT2API_IMAGE_1K_COST_UNITS",
            legacy_image_cost,
        )
        self.image_2k_cost_units = configured_or_env(
            "image_2k_cost_units",
            "CHATGPT2API_IMAGE_2K_COST_UNITS",
        )
        self.image_4k_cost_units = configured_or_env(
            "image_4k_cost_units",
            "CHATGPT2API_IMAGE_4K_COST_UNITS",
        )
        self.image_4k_enabled = _boolean(
            "CHATGPT2API_IMAGE_4K_ENABLED",
            bool(configured["image_4k_enabled"]),
        )
        # Keep the legacy field for older callers and clients.
        self.image_cost_units = self.image_1k_cost_units
        self.file_cost_units = configured_or_env(
            "file_cost_units",
            "CHATGPT2API_FILE_COST_UNITS",
            allow_env_when_configured=False,
        )

    def pricing(self) -> dict[str, object]:
        return {
            "chat_cost_units": self.chat_cost_units,
            "image_cost_units": self.image_cost_units,
            "image_1k_cost_units": self.image_1k_cost_units,
            "image_2k_cost_units": self.image_2k_cost_units,
            "image_4k_cost_units": self.image_4k_cost_units,
            "image_4k_enabled": self.image_4k_enabled,
            "search_cost_units": self.search_cost_units,
            "file_cost_units": self.file_cost_units,
        }

    @staticmethod
    def image_resolution_for_size(size: object) -> str:
        normalized = str(size or "").strip().upper().replace(" ", "")
        if not normalized or normalized in {"AUTO", "DEFAULT"}:
            return "1K"
        if normalized in {"1K", "2K", "4K"}:
            return normalized
        match = re.fullmatch(r"(\d+)X(\d+)", normalized)
        if not match:
            return "1K"
        width, height = (int(value) for value in match.groups())
        max_edge = max(width, height)
        if max_edge >= 3840:
            return "4K"
        if max_edge > 1920:
            return "2K"
        return "1K"

    def image_cost_for_size(self, size: object = None, *, count: int = 1) -> int:
        resolution = self.image_resolution_for_size(size)
        if resolution == "4K" and not self.image_4k_enabled:
            raise UnsupportedImageResolutionError("4K 生图目前暂未开放")
        price = {
            "1K": self.image_1k_cost_units,
            "2K": self.image_2k_cost_units,
            "4K": self.image_4k_cost_units,
        }[resolution]
        return price * max(1, min(int(count), 4))

    def cost_for_endpoint(self, endpoint: str, *, count: int = 1, size: object = None) -> int:
        normalized = str(endpoint or "").strip().lower()
        if "/images/" in normalized:
            return self.image_cost_for_size(size, count=count)
        if "editable-file" in normalized or "/ppt/" in normalized or "/psd/" in normalized:
            return self.file_cost_units
        if normalized.endswith("/search"):
            return self.search_cost_units
        return self.chat_cost_units

    def cost_for_task(self, task_type: str, *, count: int = 1, size: object = None) -> int:
        normalized = str(task_type or "chat").strip().lower()
        if normalized == "image":
            return self.image_cost_for_size(size, count=count)
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
