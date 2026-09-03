"""PKCE (Proof Key for Code Exchange) 工具函数"""
from __future__ import annotations

import base64
import hashlib
import secrets


def generate_pkce() -> tuple[str, str]:
    """生成 PKCE code_verifier 与对应的 code_challenge（S256）。

    Returns:
        (code_verifier, code_challenge) 元组
    """
    # OpenAI's Codex client uses a 64-byte random value rendered as hex.
    # Keep the challenge in the RFC 7636 base64url-without-padding format.
    code_verifier = secrets.token_bytes(64).hex()
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge
