from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from services.config import config
from services.storage.user_repository import user_repository


_TOKEN_PREFIX = "canvas_"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _ttl_seconds() -> int:
    try:
        value = int(os.getenv("CHATGPT2API_CANVAS_TOKEN_TTL_SECONDS", str(24 * 3600)))
    except (TypeError, ValueError):
        value = 24 * 3600
    return max(900, min(value, 7 * 24 * 3600))


def _sign(payload: str) -> str:
    secret = str(config.auth_key or "").encode("utf-8")
    return _encode(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())


class CanvasTokenService:
    def issue(self, *, user_id: str, role: str = "user") -> dict[str, str]:
        normalized_role = str(role or "").strip().lower()
        subject = str(user_id or "").strip()
        if normalized_role == "admin":
            subject = "admin"
        else:
            normalized_role = "user"
            user = user_repository.get_user_by_id(subject)
            if user is None or not bool(user.get("enabled")) or user.get("role") != "user":
                raise ValueError("用户不存在或已被禁用")
        expires_at = int(time.time()) + _ttl_seconds()
        payload = _encode(json.dumps(
            {
                "sub": subject,
                "role": normalized_role,
                "scope": "canvas:ai",
                "exp": expires_at,
                "nonce": secrets.token_hex(8),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"))
        token = f"{_TOKEN_PREFIX}{payload}.{_sign(payload)}"
        return {
            "access_token": token,
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
        }

    def authenticate(self, token: str) -> dict[str, object] | None:
        candidate = str(token or "").strip()
        if not candidate.startswith(_TOKEN_PREFIX):
            return None
        encoded = candidate.removeprefix(_TOKEN_PREFIX)
        payload, separator, signature = encoded.partition(".")
        if not payload or not separator or not signature or not hmac.compare_digest(signature, _sign(payload)):
            return None
        try:
            claims: dict[str, Any] = json.loads(_decode(payload))
            user_id = str(claims.get("sub") or "").strip()
            role = str(claims.get("role") or "user").strip().lower()
            expires_at = int(claims.get("exp") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if claims.get("scope") != "canvas:ai" or role not in {"user", "admin"} or not user_id or expires_at <= int(time.time()):
            return None
        if role == "admin" and user_id == "admin":
            return {
                "id": "admin",
                "name": "管理员",
                "role": "admin",
                "auth_type": "canvas_token",
                "auth_scope": "canvas:ai",
            }
        user = user_repository.get_user_by_id(user_id)
        if user is None or not bool(user.get("enabled")) or user.get("role") != "user":
            return None
        return {
            "id": user["id"],
            "user_id": user["id"],
            "name": user["display_name"],
            "email": user["email"],
            "role": "user",
            "auth_type": "canvas_token",
            "auth_scope": "canvas:ai",
        }


canvas_token_service = CanvasTokenService()
