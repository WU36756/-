"""Web Push subscriptions: reminders when the page is closed or on another device."""

from __future__ import annotations

import base64
import ipaddress
import json
import socket
from urllib.parse import urlparse
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
KEYS_PATH = Path(__file__).resolve().parents[1] / "data" / "vapid.json"
LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS push_subscriptions (
                   endpoint TEXT PRIMARY KEY, p256dh TEXT, auth TEXT, created_at TEXT)"""
        )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def keys() -> dict[str, str]:
    if KEYS_PATH.is_file():
        data = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
        if data.get("private_pem") and data.get("public_key"):
            return data
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    public = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    data = {"private_pem": pem, "public_key": _b64(public)}
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEYS_PATH.write_text(json.dumps(data), encoding="utf-8")
    return data


def _validate_endpoint(endpoint: str) -> bool:
    parsed = urlparse(str(endpoint))
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, 443)
    except OSError:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast or address.is_unspecified):
            return False
    return True


def subscribe(subscription: dict[str, Any]) -> bool:
    endpoint = subscription.get("endpoint")
    keys_info = subscription.get("keys") or {}
    if not endpoint or not keys_info.get("p256dh") or not keys_info.get("auth"):
        return False
    if len(str(endpoint)) > 500 or not _validate_endpoint(str(endpoint)):
        return False
    with LOCK, _connect() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh,
                   auth = excluded.auth""",
            (endpoint, keys_info["p256dh"], keys_info["auth"],
             datetime.now().isoformat(timespec="seconds")),
        )
    return True


def unsubscribe(endpoint: str) -> bool:
    with LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    return cursor.rowcount > 0


def count() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM push_subscriptions").fetchone()
    return int(row["total"] or 0)


def send(title: str, body: str, tag: str = "health") -> dict[str, Any]:
    """Send to every subscription; drop endpoints the push service rejects."""
    from pywebpush import WebPushException, webpush

    data = keys()
    sent, failed = 0, 0
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM push_subscriptions").fetchall()
    for row in rows:
        subscription = {"endpoint": row["endpoint"],
                        "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}}
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps({"title": title, "body": body, "tag": tag}, ensure_ascii=False),
                vapid_private_key=data["private_pem"],
                vapid_claims={"sub": "mailto:health-agent@localhost"},
                timeout=10,
            )
            sent += 1
        except WebPushException as error:
            failed += 1
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status in (404, 410):
                unsubscribe(row["endpoint"])
        except Exception:
            failed += 1
    return {"sent": sent, "failed": failed, "subscriptions": len(rows)}
