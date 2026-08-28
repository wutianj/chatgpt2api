from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            if "\n" not in stripped:
                raise
        else:
            if isinstance(payload, list):
                return _require_dict_items(payload, "array")
            if isinstance(payload, dict):
                for key in ("records", "accounts"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        return _require_dict_items(value, key)
                return [payload]
            return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        records.append(value)
    return records


def _require_dict_items(items: list[Any], label: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{label} item {index} is not a JSON object")
        records.append(item)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the reg2 account import API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--admin-key", default="local-test-admin-key")
    parser.add_argument(
        "--file",
        default=str(Path(__file__).resolve().parents[1] / "docs" / "runbooks" / "examples" / "reg2-image-site-sample.jsonl"),
    )
    parser.add_argument("--target-group-id", default="")
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()

    records = _load_records(Path(args.file))
    body = {
        "records": records,
        "sync_after_import": not args.no_sync,
        "return_items": False,
        "target_group_id": args.target_group_id or None,
    }
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/accounts/import/reg2",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {args.admin_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1

    expected = {
        "requested": 3,
        "accepted": 1,
        "missing_access_token": 1,
        "missing_password": 1,
    }
    for key, value in expected.items():
        if int(payload.get(key) or 0) != value:
            print(f"unexpected {key}: {payload.get(key)!r}; expected {value}", file=sys.stderr)
            return 2
    print(json.dumps({
        "requested": payload.get("requested"),
        "accepted": payload.get("accepted"),
        "added": payload.get("added"),
        "skipped": payload.get("skipped"),
        "missing_access_token": payload.get("missing_access_token"),
        "missing_password": payload.get("missing_password"),
        "synced": payload.get("synced"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
