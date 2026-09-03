from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from curl_cffi import requests

from services.gemini_account_pool import GEMINI_CODE_ASSIST_BASE, GEMINI_TOKEN_URL


AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT_CODE_ASSIST = "https://codeassist.google.com/authcode"
REDIRECT_AI_STUDIO = "http://localhost:1455/auth/callback"
DEFAULT_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
DEFAULT_SCOPES = "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"
AI_STUDIO_SCOPES = "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/generative-language.retriever"
SESSION_TTL = 30 * 60


class GeminiOAuthError(RuntimeError):
    def __init__(self, message: str, *, code: str = "gemini_oauth_error", status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class OAuthSession:
    state: str
    verifier: str
    oauth_type: str
    tier_id: str
    project_id: str
    proxy: str
    redirect_uri: str
    created_at: float


class GeminiOAuthFlow:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, OAuthSession] = {}

    def _cleanup(self) -> None:
        cutoff = time.time() - SESSION_TTL
        self._sessions = {key: value for key, value in self._sessions.items() if value.created_at > cutoff}

    @staticmethod
    def _b64url(raw: bytes) -> str:
        import base64

        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def create(self, *, oauth_type: str, tier_id: str = "", project_id: str = "", proxy: str = "") -> dict[str, str]:
        oauth_type = str(oauth_type or "code_assist").strip().lower()
        if oauth_type not in {"google_one", "code_assist", "ai_studio"}:
            raise GeminiOAuthError("oauth_type 必须是 google_one、code_assist 或 ai_studio", code="gemini_oauth_type_invalid")
        if oauth_type == "ai_studio":
            client_id = str(os.getenv("GEMINI_OAUTH_CLIENT_ID") or "").strip()
            client_secret = str(os.getenv("GEMINI_OAUTH_CLIENT_SECRET") or "").strip()
            if not client_id or not client_secret:
                raise GeminiOAuthError("AI Studio OAuth 需要配置 GEMINI_OAUTH_CLIENT_ID 和 GEMINI_OAUTH_CLIENT_SECRET", code="gemini_oauth_client_missing")
            redirect_uri = REDIRECT_AI_STUDIO
            scopes = AI_STUDIO_SCOPES
        else:
            client_id = str(os.getenv("GEMINI_OAUTH_CLIENT_ID") or DEFAULT_CLIENT_ID).strip()
            redirect_uri = REDIRECT_CODE_ASSIST
            scopes = DEFAULT_SCOPES
        state = self._b64url(secrets.token_bytes(32))
        verifier = self._b64url(secrets.token_bytes(32))
        challenge = self._b64url(__import__("hashlib").sha256(verifier.encode()).digest())
        session_id = secrets.token_hex(16)
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if project_id.strip():
            params["project_id"] = project_id.strip()
        with self._lock:
            self._cleanup()
            self._sessions[session_id] = OAuthSession(
                state=state,
                verifier=verifier,
                oauth_type=oauth_type,
                tier_id=tier_id.strip(),
                project_id=project_id.strip(),
                proxy=proxy.strip(),
                redirect_uri=redirect_uri,
                created_at=time.time(),
            )
        return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}", "session_id": session_id, "state": state, "redirect_uri": redirect_uri}

    @staticmethod
    def _callback_value(value: str, key: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if "://" in raw:
            parsed = urlparse(raw)
            query = parse_qs(parsed.query)
            return str((query.get(key) or [""])[0]).strip()
        return raw

    @staticmethod
    def _session(proxy: str) -> requests.Session:
        kwargs: dict[str, Any] = {"verify": True, "impersonate": "chrome"}
        if proxy.strip():
            kwargs["proxy"] = proxy.strip()
        return requests.Session(**kwargs)

    @staticmethod
    def _token_fields(payload: Any, session: OAuthSession) -> dict[str, Any]:
        if not isinstance(payload, dict) or not str(payload.get("access_token") or "").strip():
            raise GeminiOAuthError("Google OAuth 未返回 access_token", code="gemini_oauth_token_invalid", status_code=502)
        try:
            expires_in = int(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600
        return {
            "access_token": str(payload.get("access_token") or "").strip(),
            "refresh_token": str(payload.get("refresh_token") or "").strip(),
            "expires_in": expires_in,
            "expires_at": int(time.time()) + max(60, expires_in - 60),
            "token_type": str(payload.get("token_type") or "Bearer").strip(),
            "scope": str(payload.get("scope") or "").strip(),
            "project_id": session.project_id,
            "oauth_type": session.oauth_type,
            "tier_id": session.tier_id,
        }

    @staticmethod
    def _detect_project(session: requests.Session, token: str, project_id: str) -> tuple[str, str]:
        if project_id.strip():
            return project_id.strip(), ""
        response = session.post(
            f"{GEMINI_CODE_ASSIST_BASE}/v1internal:loadCodeAssist",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "GeminiCLI/0.1.5 (Windows; AMD64)"},
            json={"metadata": {"ideType": "ANTIGRAVITY", "ideVersion": "1.0.0", "ideName": "antigravity"}},
            timeout=30,
        )
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        if int(response.status_code or 502) >= 400 or not isinstance(payload, dict):
            return "", ""
        project = str(payload.get("cloudaicompanionProject") or "").strip()
        tier = ""
        for key in ("paidTier", "currentTier"):
            item = payload.get(key)
            if isinstance(item, dict):
                tier = str(item.get("id") or "").strip()
            elif isinstance(item, str):
                tier = item.strip()
            if tier:
                break
        return project, tier

    def exchange(self, *, session_id: str, state: str, code: str, proxy: str = "") -> dict[str, Any]:
        with self._lock:
            self._cleanup()
            session = self._sessions.get(session_id)
        if session is None:
            raise GeminiOAuthError("OAuth 会话不存在或已过期", code="gemini_oauth_session_expired")
        supplied_state = self._callback_value(state, "state")
        supplied_code = self._callback_value(code, "code")
        if not supplied_state or supplied_state != session.state:
            raise GeminiOAuthError("OAuth state 校验失败", code="gemini_oauth_state_invalid")
        if not supplied_code:
            raise GeminiOAuthError("缺少 OAuth code", code="gemini_oauth_code_missing")
        client_id = str(os.getenv("GEMINI_OAUTH_CLIENT_ID") or (DEFAULT_CLIENT_ID if session.oauth_type != "ai_studio" else "")).strip()
        client_secret = str(os.getenv("GEMINI_OAUTH_CLIENT_SECRET") or "").strip()
        form = {"grant_type": "authorization_code", "client_id": client_id, "code": supplied_code, "code_verifier": session.verifier, "redirect_uri": session.redirect_uri}
        if client_secret:
            form["client_secret"] = client_secret
        request_session = self._session(proxy.strip() or session.proxy)
        try:
            response = request_session.post(GEMINI_TOKEN_URL, data=form, timeout=30)
            try:
                payload = response.json()
            except (TypeError, ValueError):
                payload = {}
            if int(response.status_code or 502) >= 400:
                raise GeminiOAuthError("Google OAuth code 交换失败", code="gemini_oauth_exchange_failed", status_code=int(response.status_code or 502))
            token = self._token_fields(payload, session)
            if session.oauth_type in {"google_one", "code_assist"}:
                project_id, detected_tier = self._detect_project(request_session, token["access_token"], session.project_id)
                token["project_id"] = project_id
                if detected_tier:
                    token["tier_id"] = detected_tier
            token["client_id"] = client_id
            return token
        finally:
            request_session.close()
            with self._lock:
                self._sessions.pop(session_id, None)


gemini_oauth_flow = GeminiOAuthFlow()
