from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from curl_cffi import requests

from services.config import DEFAULT_GEMINI_PROVIDER, config
from services.gemini_account_pool import gemini_account_pool


GEMINI_MODEL_PREFIX = "gemini-"


class GeminiProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, code: str = "gemini_provider_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def is_gemini_model(model: object) -> bool:
    return str(model or "").strip().lower().startswith(GEMINI_MODEL_PREFIX)


def settings() -> dict[str, object]:
    return config.get_gemini_provider_settings()


def is_ready() -> bool:
    current = settings()
    return bool(
        current.get("enabled") and str(current.get("base_url") or "").strip()
    ) or gemini_account_pool.has_enabled_accounts()


def configured_models(kind: str) -> list[str]:
    if not is_ready():
        return []
    current = settings()
    key = "image_models" if kind == "image" else "chat_models"
    values = current.get(key) or DEFAULT_GEMINI_PROVIDER[key]
    if not isinstance(values, list):
        return []
    return [
        model
        for raw in values
        if (model := str(raw or "").strip()) and is_gemini_model(model)
    ]


def ensure_available(model: object) -> None:
    if not is_gemini_model(model):
        return
    current = settings()
    if gemini_account_pool.has_enabled_accounts():
        return
    if not current.get("enabled"):
        raise GeminiProviderError("Gemini 服务尚未启用", status_code=503, code="gemini_provider_disabled")
    if not str(current.get("base_url") or "").strip():
        raise GeminiProviderError("Gemini 服务地址尚未配置", status_code=503, code="gemini_provider_unconfigured")


def _base_url() -> str:
    value = str(settings().get("base_url") or "").strip().rstrip("/")
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


def _timeout() -> int:
    try:
        return max(5, min(600, int(settings().get("timeout_secs") or DEFAULT_GEMINI_PROVIDER["timeout_secs"])))
    except (TypeError, ValueError):
        return int(DEFAULT_GEMINI_PROVIDER["timeout_secs"])


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = str(settings().get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _public_payload(body: Mapping[str, Any], *, omit: set[str] | None = None) -> dict[str, Any]:
    omitted = omit or set()
    return {
        str(key): value
        for key, value in body.items()
        if not str(key).startswith("_") and str(key) not in omitted
    }


def _response_json(response: requests.Response) -> object:
    try:
        return response.json()
    except (TypeError, ValueError, json.JSONDecodeError):
        try:
            return json.loads(response.text or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}


def _error_message(payload: object, status_code: int) -> str:
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = str(error.get("message") or error.get("detail") or "").strip()
            if message:
                return message[:1000]
        for key in ("message", "detail"):
            message = str(payload.get(key) or "").strip()
            if message:
                return message[:1000]
    return f"Gemini 上游请求失败（HTTP {status_code}）"


def _check_response(response: requests.Response) -> dict[str, Any]:
    payload = _response_json(response)
    status_code = int(response.status_code or 502)
    if status_code >= 400:
        raise GeminiProviderError(
            _error_message(payload, status_code),
            status_code=status_code,
            code="gemini_upstream_error",
        )
    if not isinstance(payload, dict):
        raise GeminiProviderError("Gemini 上游返回格式无效", code="gemini_invalid_response")
    if isinstance(payload.get("error"), Mapping):
        raise GeminiProviderError(
            _error_message(payload, status_code),
            status_code=status_code,
            code="gemini_upstream_error",
        )
    return dict(payload)


def _new_session() -> requests.Session:
    return requests.Session(verify=True)


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _new_session()
    try:
        response = session.post(
            f"{_base_url()}/{path.lstrip('/')}",
            headers=_headers(),
            json=payload,
            timeout=_timeout(),
        )
        return _check_response(response)
    except GeminiProviderError:
        raise
    except requests.exceptions.RequestException as exc:
        raise GeminiProviderError(f"Gemini 服务连接失败：{exc}", code="gemini_connection_failed") from exc
    finally:
        session.close()


def _stream_chat(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    session = _new_session()
    response = None
    try:
        response = session.post(
            f"{_base_url()}/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=_timeout(),
            stream=True,
        )
        if int(response.status_code or 502) >= 400:
            raise GeminiProviderError(
                _error_message(_response_json(response), int(response.status_code or 502)),
                status_code=int(response.status_code or 502),
                code="gemini_upstream_error",
            )
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
            line = line.strip()
            if not line or line.startswith(":") or line.startswith("event:"):
                continue
            if line.lower().startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                continue
            try:
                item = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("error"), Mapping):
                raise GeminiProviderError(_error_message(item, 502), code="gemini_upstream_error")
            yield item
    except GeminiProviderError:
        raise
    except requests.exceptions.RequestException as exc:
        raise GeminiProviderError(f"Gemini 服务连接失败：{exc}", code="gemini_connection_failed") from exc
    finally:
        if response is not None:
            response.close()
        session.close()


def chat(body: Mapping[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    model = str(body.get("model") or "").strip()
    ensure_available(model)
    if gemini_account_pool.has_enabled_accounts():
        return gemini_account_pool.chat(body)
    payload = _public_payload(body, omit={"base_url"})
    if body.get("stream"):
        return _stream_chat(payload)
    return _post_json("chat/completions", payload)


def image_generation(body: Mapping[str, Any]) -> dict[str, Any]:
    model = str(body.get("model") or "").strip()
    ensure_available(model)
    if gemini_account_pool.has_enabled_accounts():
        return gemini_account_pool.generate_image(body)
    payload = _public_payload(body, omit={"base_url", "progress_callback", "images", "mask"})
    return _post_json("images/generations", payload)


def image_edit(body: Mapping[str, Any]) -> dict[str, Any]:
    model = str(body.get("model") or "").strip()
    ensure_available(model)
    if gemini_account_pool.has_enabled_accounts():
        raise GeminiProviderError(
            "当前 Gemini Business 账号池已接管生图；图生图接口暂未接入 Business 文件上传能力",
            status_code=501,
            code="gemini_business_image_edit_unavailable",
        )
    data = _public_payload(body, omit={"base_url", "progress_callback", "images", "mask"})
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for field, source in (("image", body.get("images")), ("mask", body.get("mask"))):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, (tuple, list)) or len(item) != 3:
                continue
            content, filename, mime = item
            if isinstance(content, (str, Path)):
                try:
                    content = Path(content).read_bytes()
                except OSError as exc:
                    raise GeminiProviderError(
                        "Gemini 图像编辑参考图读取失败",
                        status_code=400,
                        code="image_read_failed",
                    ) from exc
            if isinstance(content, bytes):
                files.append((field, (str(filename or "image.png"), content, str(mime or "application/octet-stream"))))
    if not files:
        raise GeminiProviderError("Gemini 图像编辑缺少参考图", status_code=400, code="missing_image")
    session = _new_session()
    try:
        response = session.post(
            f"{_base_url()}/images/edits",
            headers={key: value for key, value in _headers().items() if key != "Content-Type"},
            data=data,
            files=files,
            timeout=_timeout(),
        )
        return _check_response(response)
    except GeminiProviderError:
        raise
    except requests.exceptions.RequestException as exc:
        raise GeminiProviderError(f"Gemini 服务连接失败：{exc}", code="gemini_connection_failed") from exc
    finally:
        session.close()
