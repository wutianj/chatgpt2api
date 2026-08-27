from __future__ import annotations

import hashlib
import hmac
import os


class PaymentSignatureError(ValueError):
    pass


class PaymentConfigurationError(RuntimeError):
    pass


class PaymentService:
    """Provider-neutral payment boundary with fail-closed webhook verification."""

    def webhook_secret(self) -> str:
        return os.getenv("CHATGPT2API_PAYMENT_WEBHOOK_SECRET", "").strip()

    def verify_webhook(self, payload: bytes, signature: str | None) -> None:
        secret = self.webhook_secret()
        if not secret:
            raise PaymentConfigurationError("支付回调密钥尚未配置")
        supplied = str(signature or "").strip()
        if supplied.lower().startswith("sha256="):
            supplied = supplied[7:]
        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied.lower(), expected):
            raise PaymentSignatureError("支付回调签名无效")


payment_service = PaymentService()
