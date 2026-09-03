from __future__ import annotations

import base64
from io import BytesIO
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from curl_cffi import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from PIL import Image

from services.config import DATA_DIR
from services.json_file import read_json_object, write_json_file
from services.storage.file_lock import interprocess_lock


logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://biz-discoveryengine.googleapis.com/v1alpha"
GEMINI_AI_STUDIO_BASE = "https://generativelanguage.googleapis.com"
GEMINI_CODE_ASSIST_BASE = "https://cloudcode-pa.googleapis.com"
GEMINI_VERTEX_BASE = "https://aiplatform.googleapis.com"
GEMINI_TOKEN_URL = "https://oauth2.googleapis.com/token"
GEMINI_OAUTH_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
GEMINI_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ACCOUNT_FILE = DATA_DIR / "gemini_accounts.json"
ACCOUNT_LOCK = DATA_DIR / "gemini_accounts.lock"
AUTH_TYPES = {"business_cookie", "oauth", "api_key", "service_account"}


class GeminiAccountError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str = "gemini_account_error",
        account_id: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.account_id = account_id


def _text(value: object) -> str:
    return str(value or "").strip()


def _int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return _text(value).lower() in {"1", "true", "yes", "on", "enabled", "启用"}


def _now() -> float:
    return time.time()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _kq_encode(value: str) -> str:
    raw = bytearray()
    for char in value:
        code = ord(char)
        if code > 255:
            raw.append(code & 255)
            raw.append(code >> 8)
        else:
            raw.append(code)
    return _encode(bytes(raw))


def _create_jwt(key: bytes, key_id: str, csesidx: str) -> str:
    issued_at = int(_now())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {
        "iss": "https://business.gemini.google",
        "aud": "https://biz-discoveryengine.googleapis.com",
        "sub": f"csesidx/{csesidx}",
        "iat": issued_at,
        "exp": issued_at + 300,
        "nbf": issued_at,
    }
    head = _kq_encode(json.dumps(header, separators=(",", ":")))
    body = _kq_encode(json.dumps(payload, separators=(",", ":")))
    message = f"{head}.{body}"
    signature = hmac.new(key, message.encode(), hashlib.sha256).digest()
    return f"{message}.{_encode(signature)}"


def _decode_xsrf_token(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode())


def _error_text(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = _text(error.get("message") or error.get("status"))
            if message:
                return message[:500]
        message = _text(payload.get("message") or payload.get("detail"))
        if message:
            return message[:500]
    return _text(getattr(response, "text", ""))[:500]


def _response_json(response: Any) -> object:
    try:
        return response.json()
    except Exception:
        try:
            return json.loads(_text(getattr(response, "text", "")) or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}


def _flatten_stream_item(item: object) -> Iterator[dict[str, Any]]:
    if isinstance(item, Mapping):
        yield dict(item)
    elif isinstance(item, list):
        for child in item:
            yield from _flatten_stream_item(child)


def _iter_stream_objects(response: Any) -> Iterator[dict[str, Any]]:
    pending = ""
    for raw in response.iter_lines():
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else _text(raw)
        line = line.strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        if line.lower().startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            parsed = json.loads(line)
            pending = ""
        except (TypeError, ValueError, json.JSONDecodeError):
            pending += line
            try:
                parsed = json.loads(pending)
                pending = ""
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        yield from _flatten_stream_item(parsed)


def _common_headers(jwt: str) -> dict[str, str]:
    return {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "authorization": f"Bearer {jwt}",
        "content-type": "application/json",
        "origin": "https://business.gemini.google",
        "referer": "https://business.gemini.google/",
        "user-agent": DEFAULT_USER_AGENT,
        "x-server-timeout": "1800",
    }


def _canonical_model(model: object) -> str:
    normalized = _text(model).lower()
    return {
        "gemini-3.1-flash-image": "gemini-imagen",
        "nano-banana-2": "gemini-imagen",
    }.get(normalized, normalized or "gemini-imagen")


def _requested_resolution(size: object) -> str:
    normalized = _text(size).upper().replace(" ", "")
    if normalized in {"2K", "4K", "1K"}:
        return normalized
    if "X" in normalized:
        try:
            width, height = (int(value) for value in normalized.split("X", 1))
        except (TypeError, ValueError):
            return "1K"
        edge = max(width, height)
        return "4K" if edge >= 3840 else "2K" if edge > 1920 else "1K"
    return "1K"


def _resolved_size(metadata: Mapping[str, Any], requested: object) -> str:
    candidates: list[Mapping[str, Any]] = [metadata]
    for key in ("image", "file", "media"):
        nested = metadata.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    for candidate in candidates:
        try:
            width = int(candidate.get("width") or 0)
            height = int(candidate.get("height") or 0)
        except (TypeError, ValueError):
            width = height = 0
        if width > 0 and height > 0:
            return f"{width}x{height}"
        size = _text(candidate.get("size") or candidate.get("resolution"))
        if size:
            return size
    return _text(requested) or "1024x1024"


def _image_size_from_bytes(data: bytes, requested: object) -> str:
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width > 0 and height > 0:
                return f"{width}x{height}"
    except (OSError, ValueError):
        pass
    return _text(requested) or "1024x1024"


def _canonical_auth_type(value: object) -> str:
    normalized = _text(value).lower().replace("-", "_")
    aliases = {
        "cookie": "business_cookie",
        "business": "business_cookie",
        "business_cookie": "business_cookie",
        "oauth": "oauth",
        "oauth_based": "oauth",
        "oauth_based_gemini": "oauth",
        "oauth_based_account": "oauth",
        "apikey": "api_key",
        "api_key": "api_key",
        "aistudio": "api_key",
        "serviceaccount": "service_account",
        "service_account": "service_account",
        "vertex": "service_account",
    }
    return aliases.get(normalized, normalized if normalized in AUTH_TYPES else "")


def _extract_content(data: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]], str]:
    text_parts: list[str] = []
    files: list[dict[str, str]] = []
    session_name = ""
    seen: set[str] = set()
    for item in data:
        response = item.get("streamAssistResponse") or {}
        if not isinstance(response, Mapping):
            continue
        session_info = response.get("sessionInfo") or {}
        if isinstance(session_info, Mapping) and _text(session_info.get("session")):
            session_name = _text(session_info.get("session"))
        answer = response.get("answer") or {}
        replies = answer.get("replies") if isinstance(answer, Mapping) else []
        for reply in replies or []:
            if not isinstance(reply, Mapping):
                continue
            content = (reply.get("groundedContent") or {}).get("content", {})
            if not isinstance(content, Mapping):
                continue
            content_text = _text(content.get("text"))
            if content_text:
                text_parts.append(content_text)
            file = content.get("file")
            if isinstance(file, Mapping) and _text(file.get("fileId")):
                file_id = _text(file.get("fileId"))
                if file_id not in seen:
                    seen.add(file_id)
                    files.append({
                        "fileId": file_id,
                        "mimeType": _text(file.get("mimeType")) or "image/png",
                    })
    return "\n".join(dict.fromkeys(text_parts)), files, session_name


def _rest_model(model: object) -> str:
    normalized = _text(model).lower()
    return {
        "gemini-imagen": "gemini-3.1-flash-image",
        "nano-banana-2": "gemini-3.1-flash-image",
    }.get(normalized, normalized or "gemini-2.5-flash")


def _prompt_from_body(body: Mapping[str, Any]) -> str:
    prompt = _text(body.get("prompt"))
    if prompt:
        return prompt
    messages = body.get("messages")
    parts: list[str] = []
    if isinstance(messages, list):
        for item in messages:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
            elif isinstance(content, list):
                parts.extend(
                    _text(part.get("text"))
                    for part in content
                    if isinstance(part, Mapping) and _text(part.get("text"))
                )
    return "\n".join(parts).strip()


def _gemini_contents(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    messages = body.get("messages")
    contents: list[dict[str, Any]] = []
    if isinstance(messages, list):
        for item in messages:
            if not isinstance(item, Mapping):
                continue
            role = _text(item.get("role")).lower()
            role = "model" if role in {"assistant", "model"} else "user"
            content = item.get("content")
            parts: list[dict[str, Any]] = []
            if isinstance(content, str) and content.strip():
                parts.append({"text": content.strip()})
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    if _text(part.get("text")):
                        parts.append({"text": _text(part.get("text"))})
                    image_url = part.get("image_url") or part.get("imageUrl")
                    if isinstance(image_url, Mapping):
                        image_url = image_url.get("url")
                    value = _text(image_url)
                    if value.startswith("data:") and ";base64," in value:
                        header, encoded = value.split(",", 1)
                        parts.append({"inlineData": {"mimeType": header[5:].split(";", 1)[0] or "image/png", "data": encoded}})
            if parts:
                contents.append({"role": role, "parts": parts})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": _prompt_from_body(body)}]}]
    return contents


def _extract_rest_parts(payloads: list[Mapping[str, Any]]) -> tuple[str, list[tuple[bytes, str]]]:
    text_parts: list[str] = []
    images: list[tuple[bytes, str]] = []
    for payload in payloads:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            content = candidate.get("content")
            if not isinstance(content, Mapping):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, Mapping):
                    continue
                text = _text(part.get("text"))
                if text:
                    text_parts.append(text)
                inline = part.get("inlineData") or part.get("inline_data")
                if isinstance(inline, Mapping) and _text(inline.get("data")):
                    try:
                        data = base64.b64decode(_text(inline.get("data")), validate=True)
                    except (ValueError, TypeError):
                        continue
                    images.append((data, _text(inline.get("mimeType") or inline.get("mime_type")) or "image/png"))
    return "\n".join(dict.fromkeys(text_parts)), images


class GeminiAccountPool:
    def __init__(self, path: Path = ACCOUNT_FILE) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self._state_lock = threading.RLock()
        self._inflight: dict[str, int] = {}
        self._cursor = 0

    @staticmethod
    def _credentials(source: Mapping[str, Any]) -> dict[str, Any]:
        nested = source.get("credentials")
        credentials: dict[str, Any] = dict(nested) if isinstance(nested, Mapping) else {}
        for key, aliases in {
            "secure_c_ses": ("secure_c_ses", "secureCses"),
            "host_c_oses": ("host_c_oses", "hostCOses"),
            "csesidx": ("csesidx",),
            "config_id": ("config_id", "configId"),
            "access_token": ("access_token", "accessToken"),
            "refresh_token": ("refresh_token", "refreshToken"),
            "expires_at": ("expires_at", "expiresAt"),
            "expires_in": ("expires_in", "expiresIn"),
            "token_type": ("token_type", "tokenType"),
            "scope": ("scope", "scopes"),
            "project_id": ("project_id", "projectId"),
            "oauth_type": ("oauth_type", "oauthType"),
            "tier_id": ("tier_id", "tierId"),
            "api_key": ("api_key", "apiKey"),
            "base_url": ("base_url", "baseUrl"),
            "location": ("location", "region"),
            "service_account_json": ("service_account_json", "serviceAccountJson"),
            "service_account": ("service_account", "serviceAccount"),
            "client_id": ("client_id", "clientId"),
            "client_secret": ("client_secret", "clientSecret"),
        }.items():
            if _text(credentials.get(key)):
                continue
            for alias in aliases:
                if _text(credentials.get(alias)):
                    credentials[key] = credentials[alias]
                    break
                if _text(source.get(alias)):
                    credentials[key] = source[alias]
                    break
        for key in ("secure_c_ses", "host_c_oses", "csesidx", "config_id", "access_token", "refresh_token", "token_type", "scope", "project_id", "oauth_type", "tier_id", "api_key", "base_url", "location", "client_id", "client_secret"):
            if key in credentials:
                credentials[key] = _text(credentials[key])
        return credentials

    @staticmethod
    def _auth_type(source: Mapping[str, Any], credentials: Mapping[str, Any]) -> str:
        explicit = _canonical_auth_type(source.get("auth_type") or source.get("account_type") or source.get("type"))
        if explicit:
            return explicit
        if all(_text(credentials.get(key)) for key in ("secure_c_ses", "csesidx", "config_id")):
            return "business_cookie"
        if _text(credentials.get("api_key")):
            return "api_key"
        if _text(credentials.get("service_account_json") or credentials.get("service_account")):
            return "service_account"
        if _text(credentials.get("access_token") or credentials.get("refresh_token")):
            return "oauth"
        return ""

    @staticmethod
    def _service_account_key(credentials: Mapping[str, Any]) -> dict[str, Any]:
        raw = credentials.get("service_account_json") or credentials.get("service_account")
        if isinstance(raw, Mapping):
            return dict(raw)
        if not _text(raw):
            return {}
        try:
            parsed = json.loads(_text(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}

    @classmethod
    def _service_account_ready(cls, credentials: Mapping[str, Any]) -> bool:
        key = cls._service_account_key(credentials)
        return bool(
            _text(key.get("client_email"))
            and _text(key.get("private_key"))
            and (_text(credentials.get("project_id")) or _text(key.get("project_id")))
        )

    @staticmethod
    def _credential_error(auth_type: str) -> GeminiAccountError:
        messages = {
            "business_cookie": "Gemini Business 账号缺少 secure_c_ses、csesidx 或 config_id",
            "oauth": "Gemini OAuth 账号缺少 access_token 或 refresh_token",
            "api_key": "Gemini AI Studio 账号缺少 api_key",
            "service_account": "Gemini Vertex 账号缺少 service_account_json 或 access_token/project_id",
        }
        return GeminiAccountError(
            messages.get(auth_type, "Gemini 账号缺少可识别的凭据类型"),
            status_code=400,
            code="gemini_account_credentials_missing",
        )

    def _normalize(self, source: Mapping[str, Any], *, require_credentials: bool = False) -> dict[str, Any]:
        credentials = self._credentials(source)
        auth_type = self._auth_type(source, credentials)
        if auth_type == "service_account" and not _text(credentials.get("project_id")):
            key = self._service_account_key(credentials)
            if _text(key.get("project_id")):
                credentials["project_id"] = _text(key["project_id"])
        if require_credentials and not auth_type:
            raise self._credential_error("")
        if require_credentials:
            ready = {
                "business_cookie": all(_text(credentials.get(key)) for key in ("secure_c_ses", "csesidx", "config_id")),
                "oauth": bool(_text(credentials.get("access_token") or credentials.get("refresh_token"))),
                "api_key": bool(_text(credentials.get("api_key"))),
                "service_account": self._service_account_ready(credentials) or bool(_text(credentials.get("access_token")) and _text(credentials.get("project_id"))),
            }.get(auth_type, False)
            if not ready:
                raise self._credential_error(auth_type)
        seed = "|".join((
            "gemini",
            auth_type,
            _text(source.get("email")),
            _text(credentials.get("project_id")),
            _text(credentials.get("csesidx")),
            _text(credentials.get("config_id")),
            _text(source.get("name")),
        ))
        account_id = _text(source.get("id")) or f"gemini_{hashlib.sha256(seed.encode()).hexdigest()[:20]}"
        existing = source.get("id")
        return {
            "id": account_id,
            "name": _text(source.get("name") or source.get("email") or account_id),
            "email": _text(source.get("email")),
            "provider": "gemini",
            "auth_type": auth_type or "unknown",
            "credentials": credentials,
            "group_id": _text(source.get("group_id") or source.get("group")),
            "proxy": _text(source.get("proxy") or source.get("proxy_url") or source.get("proxyUrl")),
            "concurrency": _int(source.get("concurrency"), 1, 1, 30),
            "priority": _int(source.get("priority"), 50, 0, 1000),
            "enabled": _bool(source.get("enabled"), True),
            "status": _text(source.get("status")) or "正常",
            "error_message": _text(source.get("error_message")),
            "cooldown_until": float(source.get("cooldown_until") or 0),
            "cooldown_reason": _text(source.get("cooldown_reason")),
            "success_count": _int(source.get("success_count"), 0, 0, 2_000_000_000),
            "failure_count": _int(source.get("failure_count"), 0, 0, 2_000_000_000),
            "created_at": float(source.get("created_at") or _now()),
            "last_used_at": float(source.get("last_used_at") or 0),
            "last_test_at": float(source.get("last_test_at") or 0),
            "_legacy_id_present": bool(existing),
        }

    def _read(self) -> list[dict[str, Any]]:
        payload = read_json_object(self.path, name="Gemini 账号池")
        raw = payload.get("accounts") if isinstance(payload, Mapping) else []
        if not isinstance(raw, list):
            raw = []
        return [self._normalize(item) for item in raw if isinstance(item, Mapping)]

    def _write_locked(self, accounts: list[dict[str, Any]]) -> None:
        write_json_file(self.path, {"version": 2, "accounts": accounts})

    def _mutate(self, account_id: str, callback) -> dict[str, Any] | None:
        with interprocess_lock(self.lock_path):
            accounts = self._read()
            for index, account in enumerate(accounts):
                if account["id"] != account_id:
                    continue
                callback(account)
                self._write_locked(accounts)
                return dict(account)
        return None

    @staticmethod
    def _public(account: Mapping[str, Any], inflight: int = 0) -> dict[str, Any]:
        cooldown_until = float(account.get("cooldown_until") or 0)
        available = bool(account.get("enabled")) and cooldown_until <= _now()
        return {
            "id": _text(account.get("id")),
            "name": _text(account.get("name")),
            "email": _text(account.get("email")),
            "provider": "gemini",
            "auth_type": _text(account.get("auth_type")) or "unknown",
            "oauth_type": _text((account.get("credentials") or {}).get("oauth_type")) or None,
            "tier_id": _text((account.get("credentials") or {}).get("tier_id")) or None,
            "project_id": _text((account.get("credentials") or {}).get("project_id")) or None,
            "group_id": _text(account.get("group_id")),
            "proxy": "已配置" if _text(account.get("proxy")) else "直连",
            "concurrency": int(account.get("concurrency") or 1),
            "priority": int(account.get("priority") or 0),
            "enabled": bool(account.get("enabled")),
            "status": _text(account.get("status")) or "正常",
            "available": available and inflight < int(account.get("concurrency") or 1),
            "inflight": inflight,
            "success_count": int(account.get("success_count") or 0),
            "failure_count": int(account.get("failure_count") or 0),
            "cooldown_until": cooldown_until or None,
            "cooldown_reason": _text(account.get("cooldown_reason")),
            "error_message": _text(account.get("error_message")),
            "created_at": account.get("created_at"),
            "last_used_at": account.get("last_used_at") or None,
            "last_test_at": account.get("last_test_at") or None,
            "credentials_present": GeminiAccountPool._is_ready(account),
        }

    @staticmethod
    def _is_ready(account: Mapping[str, Any]) -> bool:
        credentials = account.get("credentials") or {}
        auth_type = _canonical_auth_type(account.get("auth_type"))
        if auth_type == "business_cookie":
            return all(_text(credentials.get(key)) for key in ("secure_c_ses", "csesidx", "config_id"))
        if auth_type == "oauth":
            return bool(_text(credentials.get("access_token") or credentials.get("refresh_token")))
        if auth_type == "api_key":
            return bool(_text(credentials.get("api_key")))
        if auth_type == "service_account":
            return GeminiAccountPool._service_account_ready(credentials) or bool(_text(credentials.get("access_token")) and _text(credentials.get("project_id")))
        return False

    def list_public(self) -> list[dict[str, Any]]:
        with self._state_lock:
            return [self._public(item, self._inflight.get(item["id"], 0)) for item in self._read()]

    def has_enabled_accounts(self) -> bool:
        return any(item["enabled"] and self._is_ready(item) for item in self._read())

    @staticmethod
    def _normalize_import_record(record: Mapping[str, Any]) -> dict[str, Any]:
        """Map Sub2API exports and the local Gemini formats into one account shape."""
        source: dict[str, Any] = dict(record)
        nested_account = source.get("account")
        if isinstance(nested_account, Mapping):
            merged = dict(nested_account)
            merged.update(source)
            source = merged
        nested_extra = source.get("extra")
        extra = nested_extra if isinstance(nested_extra, Mapping) else {}
        nested_tokens = source.get("tokens")
        if isinstance(nested_tokens, Mapping):
            source["credentials"] = {**(source.get("credentials") or {}), **nested_tokens}
        credentials = GeminiAccountPool._credentials(source)
        provider = _text(source.get("provider") or source.get("platform")).lower()
        if provider and provider not in {"gemini", "google", "google_gemini"}:
            raise GeminiAccountError("导入文件包含非 Gemini 账号", status_code=400, code="gemini_import_platform_mismatch")
        if not source.get("email"):
            source["email"] = _text(extra.get("email") or credentials.get("email"))
        if not source.get("name"):
            source["name"] = _text(extra.get("name") or source.get("email"))
        source["credentials"] = credentials
        source["auth_type"] = _canonical_auth_type(source.get("auth_type") or source.get("type") or source.get("account_type")) or GeminiAccountPool._auth_type(source, credentials)
        if not source["auth_type"]:
            raise GeminiAccountError("导入记录缺少 Gemini 凭据类型", status_code=400, code="gemini_import_auth_type_missing")
        return source

    def upsert(self, source: Mapping[str, Any]) -> dict[str, Any]:
        with interprocess_lock(self.lock_path):
            accounts = self._read()
            source_id = _text(source.get("id"))
            existing_index = next((i for i, item in enumerate(accounts) if source_id and item["id"] == source_id), -1)
            if existing_index >= 0:
                current = accounts[existing_index]
                merged = dict(current)
                merged.update(dict(source))
                incoming_credentials = self._credentials(source)
                merged["credentials"] = {**current.get("credentials", {}), **incoming_credentials}
                item = self._normalize(merged, require_credentials=True)
                for key in ("created_at", "success_count", "failure_count", "cooldown_until", "cooldown_reason", "last_used_at", "last_test_at"):
                    if key not in source:
                        item[key] = current.get(key, item[key])
                accounts[existing_index] = item
            else:
                item = self._normalize(source, require_credentials=True)
                accounts.append(item)
            self._write_locked(accounts)
            return self._public(item, self._inflight.get(item["id"], 0))

    def import_many(self, records: list[Mapping[str, Any]]) -> dict[str, Any]:
        added = updated = failed = 0
        errors: list[dict[str, str]] = []
        for record in records:
            try:
                normalized = self._normalize_import_record(record)
                candidate = self._normalize(normalized)
                existed = any(item["id"] == candidate["id"] for item in self._read())
                self.upsert(normalized)
                updated += int(existed)
                added += int(not existed)
            except GeminiAccountError as exc:
                failed += 1
                errors.append({"code": exc.code, "message": str(exc)})
        return {"added": added, "updated": updated, "failed": failed, "errors": errors}

    def update(self, account_id: str, source: Mapping[str, Any]) -> dict[str, Any]:
        with interprocess_lock(self.lock_path):
            accounts = self._read()
            for index, current in enumerate(accounts):
                if current["id"] != account_id:
                    continue
                merged = dict(current)
                merged.update(dict(source))
                merged["id"] = account_id
                incoming_credentials = self._credentials(source)
                merged["credentials"] = {**current.get("credentials", {}), **incoming_credentials}
                item = self._normalize(merged, require_credentials=True)
                for key in ("created_at", "success_count", "failure_count", "cooldown_until", "cooldown_reason", "last_used_at", "last_test_at"):
                    if key not in source:
                        item[key] = current.get(key, item[key])
                accounts[index] = item
                self._write_locked(accounts)
                return self._public(item, self._inflight.get(account_id, 0))
        raise GeminiAccountError("Gemini 账号不存在", status_code=404, code="gemini_account_not_found", account_id=account_id)

    def delete(self, account_id: str) -> None:
        with interprocess_lock(self.lock_path):
            accounts = self._read()
            remaining = [item for item in accounts if item["id"] != account_id]
            if len(remaining) == len(accounts):
                raise GeminiAccountError("Gemini 账号不存在", status_code=404, code="gemini_account_not_found", account_id=account_id)
            self._write_locked(remaining)

    def _select(self, excluded: set[str] | None = None) -> dict[str, Any]:
        excluded = excluded or set()
        now = _now()
        candidates = [
            item for item in self._read()
            if item["id"] not in excluded
            and item["enabled"]
            and self._is_ready(item)
            and float(item.get("cooldown_until") or 0) <= now
            and self._inflight.get(item["id"], 0) < int(item.get("concurrency") or 1)
        ]
        if not candidates:
            raise GeminiAccountError("没有可用的 Gemini 账号", status_code=503, code="gemini_no_available_account")
        candidates.sort(key=lambda item: (-int(item.get("priority") or 0), float(item.get("last_used_at") or 0), item["id"]))
        selected = candidates[self._cursor % len(candidates)]
        self._cursor += 1
        self._inflight[selected["id"]] = self._inflight.get(selected["id"], 0) + 1
        return selected

    def _release(self, account_id: str) -> None:
        current = self._inflight.get(account_id, 0)
        if current <= 1:
            self._inflight.pop(account_id, None)
        else:
            self._inflight[account_id] = current - 1

    def _session(self, account: Mapping[str, Any]) -> requests.Session:
        kwargs: dict[str, Any] = {"verify": True, "impersonate": "chrome"}
        proxy = _text(account.get("proxy"))
        if proxy:
            kwargs["proxy"] = proxy
        return requests.Session(**kwargs)

    @staticmethod
    def _oauth_token_expired(credentials: Mapping[str, Any]) -> bool:
        value = credentials.get("expires_at")
        try:
            expires_at = float(value)
        except (TypeError, ValueError):
            return False
        if expires_at > 100_000_000_000:
            expires_at /= 1000
        return expires_at <= _now() + 60

    def _refresh_oauth(self, account: Mapping[str, Any], session: requests.Session) -> str:
        credentials = account.get("credentials") or {}
        refresh_token = _text(credentials.get("refresh_token"))
        if not refresh_token:
            raise GeminiAccountError("Gemini OAuth 缺少 refresh_token，请重新授权", status_code=401, code="gemini_oauth_refresh_token_missing", account_id=_text(account.get("id")))
        client_id = _text(credentials.get("client_id")) or _text(os.getenv("GEMINI_OAUTH_CLIENT_ID")) or GEMINI_OAUTH_CLIENT_ID
        client_secret = _text(credentials.get("client_secret")) or _text(os.getenv("GEMINI_OAUTH_CLIENT_SECRET")) or _text(os.getenv("GEMINI_CLI_OAUTH_CLIENT_SECRET"))
        form: dict[str, str] = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
        if client_secret:
            form["client_secret"] = client_secret
        try:
            response = session.post(GEMINI_TOKEN_URL, data=form, timeout=30)
        except requests.exceptions.RequestException as exc:
            raise GeminiAccountError("Gemini OAuth 刷新连接失败", code="gemini_oauth_refresh_connection_failed", account_id=_text(account.get("id"))) from exc
        payload = _response_json(response)
        if int(response.status_code or 502) >= 400 or not isinstance(payload, Mapping) or not _text(payload.get("access_token")):
            status = int(response.status_code or 502)
            raise GeminiAccountError(
                _error_text(response) or f"Gemini OAuth 刷新失败（HTTP {status}）",
                status_code=401 if status in {400, 401} else status,
                code="gemini_oauth_refresh_failed",
                account_id=_text(account.get("id")),
            )
        access_token = _text(payload.get("access_token"))
        new_refresh_token = _text(payload.get("refresh_token")) or refresh_token
        try:
            expires_in = int(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600
        expires_at = int(_now()) + max(60, expires_in - 60)

        def update(item: dict[str, Any]) -> None:
            item_credentials = dict(item.get("credentials") or {})
            item_credentials.update({
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "expires_in": expires_in,
                "expires_at": expires_at,
                "token_type": _text(payload.get("token_type")) or "Bearer",
                "scope": _text(payload.get("scope")) or item_credentials.get("scope", ""),
            })
            item["credentials"] = item_credentials

        self._mutate(_text(account.get("id")), update)
        return access_token

    def _oauth_access_token(self, account: Mapping[str, Any], session: requests.Session) -> str:
        if _canonical_auth_type(account.get("auth_type")) == "service_account":
            return self._service_account_access_token(account, session)
        credentials = account.get("credentials") or {}
        access_token = _text(credentials.get("access_token"))
        if access_token and not self._oauth_token_expired(credentials):
            return access_token
        return self._refresh_oauth(account, session)

    def _service_account_access_token(self, account: Mapping[str, Any], session: requests.Session) -> str:
        credentials = account.get("credentials") or {}
        cached = _text(credentials.get("access_token"))
        if cached and not self._oauth_token_expired(credentials):
            return cached
        key = self._service_account_key(credentials)
        client_email = _text(key.get("client_email"))
        private_key = _text(key.get("private_key"))
        if not client_email or not private_key:
            raise GeminiAccountError(
                "Gemini Vertex 账号缺少有效 service_account_json",
                status_code=401,
                code="gemini_service_account_invalid",
                account_id=_text(account.get("id")),
            )
        issued_at = int(_now())
        header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
        if _text(key.get("private_key_id")):
            header["kid"] = _text(key["private_key_id"])
        claims = {
            "iss": client_email,
            "scope": GEMINI_CLOUD_PLATFORM_SCOPE,
            "aud": GEMINI_TOKEN_URL,
            "iat": issued_at,
            "exp": issued_at + 3600,
        }
        signing_input = ".".join((
            _encode(json.dumps(header, separators=(",", ":")).encode()),
            _encode(json.dumps(claims, separators=(",", ":")).encode()),
        ))
        try:
            signing_key = serialization.load_pem_private_key(private_key.encode(), password=None)
            signature = signing_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise GeminiAccountError(
                "Gemini Vertex service account 私钥无效",
                status_code=401,
                code="gemini_service_account_private_key_invalid",
                account_id=_text(account.get("id")),
            ) from exc
        assertion = f"{signing_input}.{_encode(signature)}"
        try:
            response = session.post(
                GEMINI_TOKEN_URL,
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            raise GeminiAccountError("Gemini Vertex token 请求失败", code="gemini_service_account_token_connection_failed", account_id=_text(account.get("id"))) from exc
        payload = _response_json(response)
        if int(response.status_code or 502) >= 400 or not isinstance(payload, Mapping) or not _text(payload.get("access_token")):
            status = int(response.status_code or 502)
            raise GeminiAccountError(
                _error_text(response) or f"Gemini Vertex token 请求失败（HTTP {status}）",
                status_code=401 if status in {400, 401, 403} else status,
                code="gemini_service_account_token_failed",
                account_id=_text(account.get("id")),
            )
        access_token = _text(payload.get("access_token"))
        try:
            expires_in = int(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600
        expires_at = int(_now()) + max(60, expires_in - 60)

        def update(item: dict[str, Any]) -> None:
            item_credentials = dict(item.get("credentials") or {})
            item_credentials.update({
                "access_token": access_token,
                "expires_in": expires_in,
                "expires_at": expires_at,
                "token_type": _text(payload.get("token_type")) or "Bearer",
            })
            item["credentials"] = item_credentials

        self._mutate(_text(account.get("id")), update)
        return access_token

    @staticmethod
    def _rest_request_body(body: Mapping[str, Any], *, image: bool) -> dict[str, Any]:
        request: dict[str, Any] = {"contents": _gemini_contents(body)}
        if image:
            generation_config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
            size = _requested_resolution(body.get("size") or body.get("resolution") or body.get("image_size"))
            if size in {"1K", "2K", "4K"}:
                generation_config["imageConfig"] = {"imageSize": size}
            ratio = _text(body.get("aspect_ratio") or body.get("aspectRatio") or body.get("ratio"))
            if ratio:
                generation_config.setdefault("imageConfig", {})["aspectRatio"] = ratio
            request["generationConfig"] = generation_config
        return request

    @staticmethod
    def _rest_url(account: Mapping[str, Any], model: str, *, stream: bool) -> str:
        credentials = account.get("credentials") or {}
        auth_type = _canonical_auth_type(account.get("auth_type"))
        project_id = _text(credentials.get("project_id"))
        oauth_type = _text(credentials.get("oauth_type")).lower()
        action = "streamGenerateContent" if stream else "generateContent"
        if auth_type == "service_account":
            location = _text(credentials.get("location")) or "us-central1"
            configured_base = _text(credentials.get("base_url"))
            base = configured_base or (GEMINI_VERTEX_BASE if location == "global" else f"https://{location}-aiplatform.googleapis.com")
            return f"{base.rstrip('/')}/v1/projects/{project_id}/locations/{location}/publishers/google/models/{model}:{action}"
        if auth_type == "oauth" and project_id and oauth_type in {"", "google_one", "code_assist"}:
            return f"{GEMINI_CODE_ASSIST_BASE}/v1internal:{action}" + ("?alt=sse" if stream else "")
        base = _text(credentials.get("base_url")) or GEMINI_AI_STUDIO_BASE
        return f"{base.rstrip('/')}/v1beta/models/{model}:{action}" + ("?alt=sse" if stream else "")

    def _execute_rest(
        self,
        account: Mapping[str, Any],
        body: Mapping[str, Any],
        *,
        image: bool,
    ) -> dict[str, Any]:
        auth_type = _canonical_auth_type(account.get("auth_type"))
        model = _rest_model(body.get("model"))
        session = self._session(account)
        try:
            headers = {"accept": "application/json", "content-type": "application/json"}
            credentials = account.get("credentials") or {}
            if auth_type == "api_key":
                api_key = _text(credentials.get("api_key"))
                if not api_key:
                    raise GeminiAccountError("Gemini API Key 缺失", status_code=401, code="gemini_api_key_missing", account_id=_text(account.get("id")))
                headers["x-goog-api-key"] = api_key
            elif auth_type in {"oauth", "service_account"}:
                headers["authorization"] = f"Bearer {self._oauth_access_token(account, session)}"
                if auth_type == "oauth" and _text(credentials.get("project_id")):
                    headers["user-agent"] = "GeminiCLI/0.1.5 (Windows; AMD64)"
            else:
                raise GeminiAccountError("Gemini 账号类型不支持 REST 请求", code="gemini_auth_type_unsupported", account_id=_text(account.get("id")))
            request_body = self._rest_request_body(body, image=image)
            project_id = _text(credentials.get("project_id"))
            oauth_type = _text(credentials.get("oauth_type")).lower()
            if auth_type == "oauth" and project_id and oauth_type in {"", "google_one", "code_assist"}:
                request_body = {"model": model, "project": project_id, "request": request_body}
            stream = bool(body.get("stream")) and not image
            response = session.post(
                self._rest_url(account, model, stream=stream),
                headers=headers,
                json=request_body,
                timeout=180 if image else 120,
                stream=stream,
            )
            self._check(response, _text(account.get("id")))
            if stream:
                payloads = list(_iter_stream_objects(response))
            else:
                payload = _response_json(response)
                payloads = [payload] if isinstance(payload, Mapping) else []
            text_result, images = _extract_rest_parts(payloads)
            if image:
                data = [{"b64_json": base64.b64encode(raw).decode(), "mime_type": mime} for raw, mime in images]
                if not data:
                    raise GeminiAccountError("Gemini OAuth 未返回图片", code="gemini_no_image", account_id=_text(account.get("id")))
                requested_size = body.get("size") or body.get("resolution") or body.get("image_size")
                return {
                    "created": int(_now()),
                    "data": data[:_int(body.get("n"), 1, 1, 4)],
                    "_account_email": _text(account.get("email") or account.get("name")),
                    "_gemini_account_id": _text(account.get("id")),
                    "_resolved_sizes": [_image_size_from_bytes(raw, requested_size) for raw, _ in images[:_int(body.get("n"), 1, 1, 4)]],
                }
            created = int(_now())
            completion_seed = f"{_text(account.get('id'))}:{created}"
            completion_id = f"chatcmpl-gemini-{hashlib.sha256(completion_seed.encode()).hexdigest()[:16]}"
            return {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": _text(body.get("model")) or model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text_result}, "finish_reason": "stop"}],
                "_account_email": _text(account.get("email") or account.get("name")),
            }
        except GeminiAccountError:
            raise
        except requests.exceptions.RequestException as exc:
            raise GeminiAccountError("Gemini REST 请求连接失败", code="gemini_connection_failed", account_id=_text(account.get("id"))) from exc
        finally:
            session.close()

    def _jwt(self, session: requests.Session, account: Mapping[str, Any]) -> str:
        credentials = account["credentials"]
        cookie = f"__Secure-C_SES={credentials['secure_c_ses']}"
        if credentials.get("host_c_oses"):
            cookie += f"; __Host-C_OSES={credentials['host_c_oses']}"
        try:
            response = session.get(
                "https://business.gemini.google/auth/getoxsrf",
                params={"csesidx": credentials["csesidx"]},
                headers={"cookie": cookie, "user-agent": DEFAULT_USER_AGENT, "referer": "https://business.gemini.google/"},
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            raise GeminiAccountError("Gemini 账号连接失败", code="gemini_account_connection_failed", account_id=account["id"]) from exc
        if int(response.status_code or 502) >= 400:
            raise GeminiAccountError(
                f"Gemini 账号认证失败（HTTP {response.status_code}）",
                status_code=int(response.status_code or 502),
                code="gemini_account_auth_failed",
                account_id=account["id"],
            )
        raw = _text(response.text)
        if raw.startswith(")]}'"):
            raw = raw[4:]
        try:
            data = json.loads(raw)
            return _create_jwt(_decode_xsrf_token(_text(data["xsrfToken"])), _text(data["keyId"]), credentials["csesidx"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GeminiAccountError("Gemini 账号认证返回格式无效", code="gemini_account_auth_invalid", account_id=account["id"]) from exc

    @staticmethod
    def _check(response: Any, account_id: str) -> None:
        if int(response.status_code or 502) >= 400:
            status = int(response.status_code or 502)
            raise GeminiAccountError(
                _error_text(response) or f"Gemini 上游请求失败（HTTP {status}）",
                status_code=status,
                code="gemini_upstream_error",
                account_id=account_id,
            )

    def _create_session(self, session: requests.Session, account: Mapping[str, Any], jwt: str) -> str:
        credentials = account["credentials"]
        response = session.post(
            f"{GEMINI_API_BASE}/locations/global/widgetCreateSession",
            headers=_common_headers(jwt),
            json={
                "configId": credentials["config_id"],
                "additionalParams": {"token": "-"},
                "createSessionRequest": {"session": {"name": "", "displayName": ""}},
            },
            timeout=30,
        )
        self._check(response, account["id"])
        payload = _response_json(response)
        session_name = payload.get("session", {}).get("name") if isinstance(payload, Mapping) else ""
        if not _text(session_name):
            raise GeminiAccountError("Gemini 会话创建失败", code="gemini_session_invalid", account_id=account["id"])
        return _text(session_name)

    def _stream_assist(
        self,
        session: requests.Session,
        account: Mapping[str, Any],
        jwt: str,
        session_name: str,
        prompt: str,
        model: str,
        *,
        image: bool,
    ) -> list[dict[str, Any]]:
        credentials = account["credentials"]
        tools_spec: dict[str, Any] = {"imageGenerationSpec": {}} if image else {
            "webGroundingSpec": {},
            "toolRegistry": "default_tool_registry",
        }
        request: dict[str, Any] = {
            "session": session_name,
            "query": {"parts": [{"text": prompt}]},
            "filter": "",
            "fileIds": [],
            "answerGenerationMode": "NORMAL",
            "toolsSpec": tools_spec,
            "languageCode": "zh-CN",
            "userMetadata": {"timeZone": "Asia/Shanghai"},
            "assistSkippingMode": "REQUEST_ASSIST",
        }
        canonical = _canonical_model(model)
        if not image and canonical not in {"gemini-auto", "gemini-imagen"}:
            request["assistGenerationConfig"] = {"modelId": canonical}
        response = session.post(
            f"{GEMINI_API_BASE}/locations/global/widgetStreamAssist",
            headers=_common_headers(jwt),
            json={"configId": credentials["config_id"], "additionalParams": {"token": "-"}, "streamAssistRequest": request},
            timeout=180,
            stream=True,
        )
        self._check(response, account["id"])
        try:
            return list(_iter_stream_objects(response))
        finally:
            response.close()

    def _download_image(
        self,
        session: requests.Session,
        account: Mapping[str, Any],
        jwt: str,
        session_name: str,
        file_ref: Mapping[str, str],
    ) -> tuple[bytes, str, dict[str, Any]]:
        credentials = account["credentials"]
        metadata_response = session.post(
            f"{GEMINI_API_BASE}/locations/global/widgetListSessionFileMetadata",
            headers=_common_headers(jwt),
            json={
                "configId": credentials["config_id"],
                "additionalParams": {"token": "-"},
                "listSessionFileMetadataRequest": {"name": session_name, "filter": "file_origin_type = AI_GENERATED"},
            },
            timeout=30,
        )
        self._check(metadata_response, account["id"])
        payload = _response_json(metadata_response)
        metadata_items = {}
        if isinstance(payload, Mapping):
            response = payload.get("listSessionFileMetadataResponse") or {}
            if isinstance(response, Mapping):
                metadata_items = {
                    _text(item.get("fileId")): item
                    for item in response.get("fileMetadata", [])
                    if isinstance(item, Mapping) and _text(item.get("fileId"))
                }
        metadata = metadata_items.get(_text(file_ref.get("fileId")), {})
        download_session = _text(metadata.get("session")) or session_name
        response = session.get(
            f"{GEMINI_API_BASE}/{download_session}:downloadFile",
            params={"fileId": _text(file_ref.get("fileId")), "alt": "media"},
            headers=_common_headers(jwt),
            timeout=180,
        )
        self._check(response, account["id"])
        return bytes(response.content), _text(metadata.get("mimeType")) or _text(file_ref.get("mimeType")) or "image/png", dict(metadata)

    def _execute(
        self,
        account: Mapping[str, Any],
        prompt: str,
        model: str,
        *,
        image: bool,
        requested_size: object = None,
    ) -> dict[str, Any]:
        if _canonical_auth_type(account.get("auth_type")) != "business_cookie":
            return self._execute_rest(account, {"model": model, "prompt": prompt, "size": requested_size}, image=image)
        session = self._session(account)
        try:
            jwt = self._jwt(session, account)
            session_name = self._create_session(session, account, jwt)
            stream_items = self._stream_assist(session, account, jwt, session_name, prompt, model, image=image)
            content, file_refs, stream_session = _extract_content(stream_items)
            session_name = stream_session or session_name
            result: dict[str, Any] = {"text": content, "data": [], "resolved_sizes": []}
            if image:
                for file_ref in file_refs:
                    data, mime, metadata = self._download_image(session, account, jwt, session_name, file_ref)
                    result["data"].append({
                        "b64_json": base64.b64encode(data).decode(),
                        "mime_type": mime,
                    })
                    result["resolved_sizes"].append(_resolved_size(metadata, requested_size))
            return result
        finally:
            session.close()

    def _mark_success(self, account_id: str) -> None:
        def update(item: dict[str, Any]) -> None:
            item["success_count"] = int(item.get("success_count") or 0) + 1
            item["status"] = "正常"
            item["error_message"] = ""
            item["cooldown_until"] = 0
            item["cooldown_reason"] = ""
            item["last_used_at"] = _now()

        self._mutate(account_id, update)

    def _mark_failure(self, account_id: str, error: Exception) -> None:
        status_code = int(getattr(error, "status_code", 502) or 502)
        cooldown = 900 if status_code in {401, 403} else 120 if status_code == 429 else 30
        message = _text(error)[:500]

        def update(item: dict[str, Any]) -> None:
            item["failure_count"] = int(item.get("failure_count") or 0) + 1
            item["status"] = "冷却" if cooldown else "异常"
            item["error_message"] = message
            item["cooldown_until"] = _now() + cooldown
            item["cooldown_reason"] = getattr(error, "code", "gemini_request_failed")

        self._mutate(account_id, update)

    def test(self, account_id: str) -> dict[str, Any]:
        with self._state_lock:
            account = next((item for item in self._read() if item["id"] == account_id), None)
            if account is None:
                raise GeminiAccountError("Gemini 账号不存在", status_code=404, code="gemini_account_not_found", account_id=account_id)
            self._inflight[account_id] = self._inflight.get(account_id, 0) + 1
        started = time.perf_counter()
        try:
            session = self._session(account)
            try:
                auth_type = _canonical_auth_type(account.get("auth_type"))
                if auth_type == "business_cookie":
                    self._jwt(session, account)
                elif auth_type in {"oauth", "service_account"}:
                    self._oauth_access_token(account, session)
                elif auth_type == "api_key" and _text((account.get("credentials") or {}).get("api_key")):
                    pass
                else:
                    raise self._credential_error(auth_type)
            finally:
                session.close()
            self._mark_success(account_id)
            return {"status": "success", "account_id": account_id, "duration_ms": int((time.perf_counter() - started) * 1000), "message": "认证成功" if auth_type == "business_cookie" else "凭据可用"}
        except Exception as exc:
            self._mark_failure(account_id, exc)
            if isinstance(exc, GeminiAccountError):
                raise
            raise GeminiAccountError("Gemini 账号测试失败", code="gemini_account_test_failed", account_id=account_id) from exc
        finally:
            with self._state_lock:
                self._release(account_id)

    def generate_image(self, body: Mapping[str, Any]) -> dict[str, Any]:
        prompt = _text(body.get("prompt"))
        model = _text(body.get("model")) or "gemini-imagen"
        requested_size = body.get("size")
        count = _int(body.get("n"), 1, 1, 4)
        attempted: set[str] = set()
        last_error: Exception | None = None
        for _ in range(min(4, max(1, len(self._read())))):
            with self._state_lock:
                account = self._select(attempted)
            attempted.add(account["id"])
            try:
                if _canonical_auth_type(account.get("auth_type")) == "business_cookie":
                    result = self._execute(account, prompt, model, image=True, requested_size=requested_size)
                else:
                    result = self._execute_rest(account, body, image=True)
                if not result["data"]:
                    raise GeminiAccountError("Gemini 未返回图片", code="gemini_no_image", account_id=account["id"])
                result["data"] = result["data"][:count]
                result["resolved_sizes"] = (result.get("resolved_sizes") or result.get("_resolved_sizes") or [])[:len(result["data"])]
                self._mark_success(account["id"])
                callback = body.get("_billing_resolution_callback")
                if callable(callback) and result["resolved_sizes"]:
                    callback(list(result["resolved_sizes"]))
                return {
                    "created": int(_now()),
                    "data": [{"b64_json": item["b64_json"]} for item in result["data"]],
                    "_account_email": _text(account.get("email") or account.get("name")),
                    "_gemini_account_id": account["id"],
                    "_resolved_sizes": list(result["resolved_sizes"]),
                }
            except Exception as exc:
                last_error = exc
                self._mark_failure(account["id"], exc)
            finally:
                with self._state_lock:
                    self._release(account["id"])
        if isinstance(last_error, GeminiAccountError):
            raise last_error
        raise GeminiAccountError("Gemini 账号池未能生成图片", code="gemini_pool_generation_failed") from last_error

    def chat(self, body: Mapping[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
        messages = body.get("messages")
        parts: list[str] = []
        if isinstance(messages, list):
            for item in messages:
                if not isinstance(item, Mapping):
                    continue
                role = _text(item.get("role")) or "user"
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    parts.append(f"{role}: {content.strip()}")
                elif isinstance(content, list):
                    text_parts = [_text(part.get("text")) for part in content if isinstance(part, Mapping) and _text(part.get("text"))]
                    if text_parts:
                        parts.append(f"{role}: {' '.join(text_parts)}")
        prompt = "\n".join(parts) or _text(body.get("prompt"))
        model = _text(body.get("model")) or "gemini-auto"
        attempted: set[str] = set()
        last_error: Exception | None = None
        for _ in range(min(4, max(1, len(self._read())))):
            with self._state_lock:
                account = self._select(attempted)
            attempted.add(account["id"])
            try:
                if _canonical_auth_type(account.get("auth_type")) == "business_cookie":
                    result = self._execute(account, prompt, model, image=False)
                else:
                    result = self._execute_rest(account, body, image=False)
                self._mark_success(account["id"])
                text_result = result["text"] or ""
                created = int(_now())
                account_id = _text(account["id"])
                completion_id = f"chatcmpl-gemini-{hashlib.sha256(f'{account_id}:{created}'.encode()).hexdigest()[:16]}"
                response = {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text_result}, "finish_reason": "stop"}],
                    "_account_email": _text(account.get("email") or account.get("name")),
                }
                if body.get("stream"):
                    return iter([
                        {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text_result}, "finish_reason": None}]},
                        {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                    ])
                return response
            except Exception as exc:
                last_error = exc
                self._mark_failure(account["id"], exc)
            finally:
                with self._state_lock:
                    self._release(account["id"])
        if isinstance(last_error, GeminiAccountError):
            raise last_error
        raise GeminiAccountError("Gemini 账号池对话失败", code="gemini_pool_chat_failed") from last_error


gemini_account_pool = GeminiAccountPool()
