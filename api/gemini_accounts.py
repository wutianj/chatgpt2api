from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from api.support import require_admin
from services.gemini_account_pool import GeminiAccountError, gemini_account_pool
from services.gemini_oauth import GeminiOAuthError, gemini_oauth_flow


class GeminiAccountWriteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str = ""
    email: str = ""
    secure_c_ses: str = ""
    host_c_oses: str = ""
    csesidx: str = ""
    config_id: str = ""
    credentials: dict[str, Any] | None = None
    auth_type: str = ""
    oauth_type: str = ""
    tier_id: str = ""
    project_id: str = ""
    api_key: str = ""
    base_url: str = ""
    location: str = ""
    service_account_json: dict[str, Any] | str | None = None
    group_id: str = ""
    proxy: str = ""
    concurrency: int = Field(default=1, ge=1, le=30)
    priority: int = Field(default=50, ge=0, le=1000)
    enabled: bool = True


class GeminiAccountPatchRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    email: str | None = None
    secure_c_ses: str | None = None
    host_c_oses: str | None = None
    csesidx: str | None = None
    config_id: str | None = None
    credentials: dict[str, Any] | None = None
    auth_type: str | None = None
    oauth_type: str | None = None
    tier_id: str | None = None
    project_id: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    location: str | None = None
    service_account_json: dict[str, Any] | str | None = None
    group_id: str | None = None
    proxy: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=30)
    priority: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None


class GeminiAccountImportRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    records: list[dict[str, Any]] = Field(default_factory=list)
    accounts: list[dict[str, Any]] = Field(default_factory=list)


class GeminiAccountToggleRequest(BaseModel):
    enabled: bool


class GeminiOAuthAuthorizeRequest(BaseModel):
    oauth_type: str = "code_assist"
    tier_id: str = ""
    project_id: str = ""
    proxy: str = ""


class GeminiOAuthExchangeRequest(BaseModel):
    session_id: str
    state: str
    code: str
    proxy: str = ""


def _error(exc: GeminiAccountError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error": str(exc), "code": exc.code})


def _oauth_error(exc: GeminiOAuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error": str(exc), "code": exc.code})


def _payload(body: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    value = body.model_dump(mode="python", exclude_none=True, exclude_unset=exclude_unset)
    credentials = dict(value.get("credentials") or {})
    for key in (
        "secure_c_ses", "host_c_oses", "csesidx", "config_id",
        "oauth_type", "tier_id", "project_id", "api_key", "base_url",
        "location", "service_account_json",
    ):
        if key in value and value[key] is not None and value[key] != "":
            credentials.setdefault(key, value[key])
    if credentials:
        value["credentials"] = credentials
    return value


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/gemini/accounts")
    async def list_gemini_accounts(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        items = await run_in_threadpool(gemini_account_pool.list_public)
        return {"items": items, "total": len(items)}

    @router.get("/api/gemini/oauth/capabilities")
    async def gemini_oauth_capabilities(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {
            "oauth_types": ["google_one", "code_assist", "ai_studio"],
            "account_types": ["oauth", "api_key", "service_account", "business_cookie"],
            "manual_oauth": True,
            "import_formats": ["sub2api_json", "json", "jsonl"],
        }

    @router.post("/api/gemini/oauth/authorize")
    async def gemini_oauth_authorize(
        body: GeminiOAuthAuthorizeRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            return await run_in_threadpool(
                gemini_oauth_flow.create,
                oauth_type=body.oauth_type,
                tier_id=body.tier_id,
                project_id=body.project_id,
                proxy=body.proxy,
            )
        except GeminiOAuthError as exc:
            raise _oauth_error(exc) from exc

    @router.post("/api/gemini/oauth/exchange")
    async def gemini_oauth_exchange(
        body: GeminiOAuthExchangeRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            return await run_in_threadpool(
                gemini_oauth_flow.exchange,
                session_id=body.session_id,
                state=body.state,
                code=body.code,
                proxy=body.proxy,
            )
        except GeminiOAuthError as exc:
            raise _oauth_error(exc) from exc

    @router.post("/api/gemini/accounts")
    async def create_gemini_account(
        body: GeminiAccountWriteRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(gemini_account_pool.upsert, _payload(body))
        except GeminiAccountError as exc:
            raise _error(exc) from exc
        return {"item": item}

    @router.post("/api/gemini/accounts/import")
    async def import_gemini_accounts(
        body: GeminiAccountImportRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        records = body.records or body.accounts
        result = await run_in_threadpool(gemini_account_pool.import_many, records)
        return result

    @router.patch("/api/gemini/accounts/{account_id}")
    async def update_gemini_account(
        account_id: str,
        body: GeminiAccountPatchRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(
                gemini_account_pool.update,
                account_id,
                _payload(body, exclude_unset=True),
            )
        except GeminiAccountError as exc:
            raise _error(exc) from exc
        return {"item": item}

    @router.post("/api/gemini/accounts/{account_id}/toggle")
    async def toggle_gemini_account(
        account_id: str,
        body: GeminiAccountToggleRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(gemini_account_pool.update, account_id, {"enabled": body.enabled})
        except GeminiAccountError as exc:
            raise _error(exc) from exc
        return {"item": item}

    @router.post("/api/gemini/accounts/{account_id}/test")
    async def test_gemini_account(
        account_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            return await run_in_threadpool(gemini_account_pool.test, account_id)
        except GeminiAccountError as exc:
            raise _error(exc) from exc

    @router.delete("/api/gemini/accounts/{account_id}")
    async def delete_gemini_account(
        account_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            await run_in_threadpool(gemini_account_pool.delete, account_id)
        except GeminiAccountError as exc:
            raise _error(exc) from exc
        return {"deleted": True, "id": account_id}

    return router
