"""Access-code sessions: one isolated SQLite database per browser."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

from .config import settings

COOKIE = "hap_sid"
SESSION_DAYS = 7
SID_RE = re.compile(r"^[a-f0-9]{16}$")
BASE = Path(__file__).resolve().parents[1]
SECRET_FILE = BASE / "data" / ".session-secret"


def _secret() -> bytes:
    if settings.secret_key:
        return settings.secret_key.encode()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(SECRET_FILE, 0o600)
        except OSError:
            pass
    return SECRET_FILE.read_text(encoding="utf-8").strip().encode()


def new_sid() -> str:
    return secrets.token_hex(8)


def sign(sid: str) -> str:
    digest = hmac.new(_secret(), sid.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{sid}.{digest}"


def verify(cookie: str | None) -> str | None:
    if not cookie or "." not in cookie:
        return None
    sid, digest = cookie.split(".", 1)
    if not SID_RE.match(sid):
        return None
    expected = hmac.new(_secret(), sid.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(digest, expected):
        return None
    return sid


def ensure(sid: str) -> None:
    from . import db

    db.seed(sid)
