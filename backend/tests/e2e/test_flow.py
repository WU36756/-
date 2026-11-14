"""End-to-end tests against a running panel (HTTP level).

Run with the service up:
    uv run pytest -q tests/e2e
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.error
import urllib.request
import uuid

import pytest

BASE = os.environ.get("HEALTH_E2E_URL", "http://127.0.0.1:8100")
ACCESS_CODE = os.environ.get("HEALTH_E2E_CODE", "health-demo-2026")


def _up() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/api/health", timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="panel is not running")


class Client:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._login()

    def _login(self) -> None:
        data = json.dumps({"code": ACCESS_CODE}).encode()
        request = urllib.request.Request(
            BASE + "/api/login", data=data, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            self.opener.open(request, timeout=10).read()
        except Exception:
            pass

    def text(self, path: str) -> str:
        with self.opener.open(BASE + path, timeout=10) as response:
            return response.read().decode()

    def call(self, path: str, method: str = "GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            BASE + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode() or "{}")


def _new_user() -> Client:
    return Client()


def test_full_user_flow_and_isolation():
    alice = _new_user()
    status, result = alice.call("/api/analyze", "POST",
                                {"symptoms": "发烧，头痛", "provider": "mock"})
    assert status == 200 and "tcm" in result

    # medication lifecycle
    status, created = alice.call("/api/medications", "POST", {
        "name": "E2E测试药", "dose": "1片", "method": "口服",
        "interval_hours": 8, "doses_per_day": 1, "start_time": "08:00",
        "total_doses": 2, "stock_total": 4, "stock_unit": "片"})
    assert status == 200
    med_id = created["item"]["id"]
    status, taken = alice.call(f"/api/medications/{med_id}/take", "POST")
    assert status == 200 and taken["item"]["taken"] == 1
    assert taken["item"]["stock_remaining"] == 3
    patched = alice.call(f"/api/medications/{med_id}", "PATCH", {"dose": "2片"})[1]
    assert patched["item"]["dose"] == "2片"

    # plan check-in with score
    alice.call("/api/plan/checkin", "POST",
               {"diet": True, "exercise": True, "meds": True, "score": 6})
    status, plan = alice.call("/api/plan")
    assert status == 200 and plan["plan"] is not None
    assert plan["plan"]["today"]["score"] == 6

    # notifications queue
    status, unread = alice.call("/api/notifications/unread")
    assert status == 200 and isinstance(unread["items"], list)

    # shared single-user mode: same account/data everywhere
    status, meds = alice.call("/api/medications")
    assert status == 200
    assert any(item["id"] == med_id for item in meds["items"])
    alice.call(f"/api/medications/{med_id}", "DELETE")


def test_frontend_is_split_into_assets():
    html = Client().text("/")
    assert 'href="/static/styles.css' in html
    assert 'src="/static/app.js' in html
    assert "<style>" not in html
    assert "<script>" not in html
    for asset in ("/static/app.js", "/static/styles.css"):
        with urllib.request.urlopen(BASE + asset, timeout=10) as response:
            assert response.status == 200
            assert len(response.read()) > 1000
