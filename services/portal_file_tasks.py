from __future__ import annotations

from hashlib import sha256
from typing import Any

from services.portal_billing import portal_billing
from services.storage.portal_repository import portal_repository


FILE_TASK_MODEL = "gpt-5-5-thinking"


def _clean(value: object) -> str:
    return str(value or "").strip()


def file_task_reference(user_id: str, kind: str, source_task_id: str) -> str:
    normalized_user = _clean(user_id)[:64]
    normalized_kind = _clean(kind).lower()[:8]
    normalized_task = _clean(source_task_id)
    if len(normalized_task) > 80:
        normalized_task = sha256(normalized_task.encode("utf-8")).hexdigest()
    return f"{normalized_user}:{normalized_kind}:{normalized_task}"[:120]


def portal_file_task_id(reference_id: str) -> str:
    return f"file_{sha256(reference_id.encode('utf-8')).hexdigest()[:48]}"


def sync_portal_file_task(
    identity: dict[str, object],
    item: dict[str, object],
    *,
    kind: str,
    prompt: str,
    reference_id: str | None = None,
    charge_units: int = 0,
) -> dict[str, Any] | None:
    """Mirror one editable-file task into the user task and billing domains."""
    user_id = _clean(identity.get("user_id"))
    source_task_id = _clean(item.get("id"))
    normalized_kind = _clean(kind).lower()
    if not user_id or not source_task_id or normalized_kind not in {"ppt", "psd"}:
        return None

    billing_reference = reference_id or file_task_reference(user_id, normalized_kind, source_task_id)
    task_id = portal_file_task_id(billing_reference)
    source_status = _clean(item.get("status")).lower()
    status = {
        "queued": "queued",
        "running": "running",
        "success": "success",
        "error": "failed",
    }.get(source_status, "failed")
    error_text = _clean(item.get("error"))
    model = _clean(item.get("model")) or FILE_TASK_MODEL
    request = {
        "prompt": _clean(prompt)[:4000],
        "kind": normalized_kind,
        "source_task_id": source_task_id,
        "charge_units": max(0, int(charge_units)),
        "billing_reference_type": "file_task",
        "billing_reference_id": billing_reference,
    }
    portal_repository.create_task(
        task_id=task_id,
        user_id=user_id,
        api_key_id=_clean(identity.get("api_key_id")) or None,
        task_type="file",
        model=model,
        request=request,
        status=status,
    )
    updated = portal_repository.update_task(
        user_id=user_id,
        task_id=task_id,
        status=status,
        result={"source_task_id": source_task_id} if status == "success" else None,
        error_code=(error_text[:64] or "file_task_failed") if status == "failed" else None,
    )

    if status == "success":
        portal_billing.complete(
            identity,
            reference_type="file_task",
            reference_id=billing_reference,
        )
    elif status == "failed":
        portal_billing.refund_reserved(
            identity,
            reference_type="file_task",
            reference_id=billing_reference,
        )
    return updated
