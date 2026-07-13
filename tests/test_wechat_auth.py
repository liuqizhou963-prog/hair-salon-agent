from unittest.mock import AsyncMock

import backend.api.routers as routers
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_wechat_login_creates_and_reuses_customer(monkeypatch):
    exchange = AsyncMock(return_value="openid-test-customer")
    monkeypatch.setattr(routers, "_fetch_wechat_openid", exchange)

    first = client.post("/api/auth/wechat", json={"code": "wx-code-1"})
    assert first.status_code == 200, first.text

    first_token = first.json()["access_token"]
    profile = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {first_token}"}
    )
    assert profile.status_code == 200
    assert profile.json()["name"] == "微信用户"
    assert profile.json()["phone"] is None

    second = client.post("/api/auth/wechat", json={"code": "wx-code-2"})
    assert second.status_code == 200, second.text
    assert exchange.await_count == 2


def test_wechat_login_requires_code():
    response = client.post("/api/auth/wechat", json={})
    assert response.status_code == 422
