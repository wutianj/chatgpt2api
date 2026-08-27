from __future__ import annotations

from contracts.auth import _StrictModel


class CanvasSessionView(_StrictModel):
    access_token: str
    expires_at: str

