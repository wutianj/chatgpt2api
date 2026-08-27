from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from services.storage.user_repository import user_repository


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def _clean(value: object) -> str:
    return str(value or "").strip()


def normalize_email(value: object) -> str:
    email = _clean(value).lower()
    if not _EMAIL_RE.fullmatch(email):
        raise ValueError("请输入有效的邮箱地址")
    return email


def hash_password(password: str) -> str:
    raw = _clean(password)
    if len(raw) < 8:
        raise ValueError("密码至少需要 8 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        raw.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    )
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${encode(salt)}${encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        expected = decode(digest_text)
        actual = hashlib.scrypt(
            _clean(password).encode("utf-8"),
            salt=decode(salt_text),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session_ttl() -> timedelta:
    try:
        seconds = int(os.getenv("CHATGPT2API_SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
    except ValueError:
        seconds = 7 * 24 * 3600
    return timedelta(seconds=max(900, min(seconds, 30 * 24 * 3600)))


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "role": user["role"],
        "enabled": user["enabled"],
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }


class UserAuthService:
    def __init__(self, repository=user_repository):
        self.repository = repository

    def register(self, *, email: str, password: str, display_name: str = "") -> tuple[str, dict[str, Any]]:
        normalized_email = normalize_email(email)
        if self.repository.get_user_by_email(normalized_email) is not None:
            raise ValueError("这个邮箱已经注册")
        name = _clean(display_name)[:120] or normalized_email.split("@", 1)[0]
        try:
            user = self.repository.create_user(
                user_id=uuid.uuid4().hex,
                email=normalized_email,
                display_name=name,
                password_hash=hash_password(password),
            )
        except IntegrityError as exc:
            raise ValueError("这个邮箱已经注册") from exc
        return self._issue_session(user)

    def login(self, *, email: str, password: str) -> tuple[str, dict[str, Any]]:
        normalized_email = normalize_email(email)
        user = self.repository.get_user_by_email(normalized_email)
        if user is None or not bool(user["enabled"]) or not verify_password(password, user["password_hash"]):
            raise ValueError("邮箱或密码错误")
        self.repository.touch_last_login(user["id"])
        user = self.repository.get_user_by_id(user["id"]) or user
        return self._issue_session(user)

    def authenticate_session(self, token: str) -> dict[str, object] | None:
        candidate = _clean(token)
        if not candidate.startswith("sess_"):
            return None
        user = self.repository.get_session_identity(_hash_token(candidate))
        if user is None:
            return None
        return {
            "id": user["id"],
            "user_id": user["id"],
            "name": user["display_name"],
            "email": user["email"],
            "role": user["role"],
            "auth_type": "user_session",
        }

    def logout(self, token: str) -> bool:
        candidate = _clean(token)
        return bool(candidate) and self.repository.revoke_session(_hash_token(candidate))

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        user = self.repository.get_user_by_id(_clean(user_id))
        if user is None or not bool(user["enabled"]):
            return None
        return _public_user(user)

    def create_api_key(self, *, user_id: str, name: str = "") -> tuple[str, dict[str, Any]]:
        user = self.repository.get_user_by_id(_clean(user_id))
        if user is None or not bool(user["enabled"]):
            raise ValueError("用户不存在或已被禁用")
        normalized_name = _clean(name)[:120] or "默认 API Key"
        raw_key = f"uk_{secrets.token_urlsafe(32)}"
        item = self.repository.create_api_key(
            key_id=uuid.uuid4().hex,
            user_id=user["id"],
            name=normalized_name,
            key_hash=_hash_token(raw_key),
        )
        return raw_key, item

    def list_api_keys(self, user_id: str) -> list[dict[str, Any]]:
        return self.repository.list_api_keys(_clean(user_id))

    def revoke_api_key(self, *, user_id: str, key_id: str) -> bool:
        return self.repository.revoke_api_key(user_id=_clean(user_id), key_id=_clean(key_id))

    def authenticate_api_key(self, token: str) -> dict[str, object] | None:
        candidate = _clean(token)
        if not candidate.startswith("uk_"):
            return None
        item = self.repository.authenticate_api_key(_hash_token(candidate))
        if item is None:
            return None
        return {
            "id": item["id"],
            "user_id": item["id"],
            "api_key_id": item["api_key_id"],
            "api_key_name": item["api_key_name"],
            "name": item["display_name"],
            "email": item["email"],
            "role": item["role"],
            "auth_type": "user_api_key",
        }

    def _issue_session(self, user: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        token = f"sess_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc)
        self.repository.create_session(
            session_id=uuid.uuid4().hex,
            user_id=user["id"],
            token_hash=_hash_token(token),
            expires_at=now + _session_ttl(),
        )
        return token, _public_user(user)


user_auth_service = UserAuthService()
