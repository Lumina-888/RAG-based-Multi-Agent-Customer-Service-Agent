"""SP-SEC-003 认证与鉴权（集成层，全离线可跑）：T-SEC-301 ~ 303。

- T-SEC-301 未认证访问受保护接口（退款建单/会话历史）→ 4010
- T-SEC-302 已认证用户访问他人订单/会话 → 4030 且不泄露数据
- T-SEC-303 登录（Bearer token）后正常访问
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api import refund as refund_api
from app.api import sessions as sessions_api
from app.auth.token_store import MemoryTokenStore
from app.refund.repo import MemoryTicketRepo
from app.refund.service import RefundService


@pytest.fixture
def client() -> TestClient:
    from app.main import app  # 延迟导入：避免收集期触发 setup_logging

    store = MemoryTokenStore()
    app.dependency_overrides[auth_api.get_token_store] = lambda: store
    app.dependency_overrides[refund_api.get_refund_service] = lambda: RefundService(
        repo=MemoryTicketRepo()
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(client: TestClient, user_id: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"user_id": user_id})
    assert resp.status_code == 200
    return resp.json()["data"]


def _bearer(data: dict) -> dict:
    return {"Authorization": f"Bearer {data['token']}"}


@pytest.mark.spec("SP-SEC-003")
@pytest.mark.integration
class TestAuthIntegration:
    def test_sec_301_unauthenticated_4010(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": "ORD-20260811-001", "refund_type": "only_refund",
                  "reason": "r", "amount": 199.0},
        )
        assert resp.status_code == 401 and resp.json()["code"] == 4010
        resp2 = client.get("/api/v1/sessions/abc/messages")
        assert resp2.status_code == 401 and resp2.json()["code"] == 4010

    def test_sec_302_cross_user_4030(self, client: TestClient) -> None:
        bob = _login(client, "user-2")
        # user-1 的订单 → user-2 访问 → 4030 且 data 为空（不泄露）
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": "ORD-20260811-001", "refund_type": "only_refund",
                  "reason": "r", "amount": 199.0},
            headers=_bearer(bob),
        )
        assert resp.status_code == 403 and resp.json()["code"] == 4030
        assert resp.json()["data"] is None

    def test_sec_303_login_then_normal_access(self, client: TestClient) -> None:
        alice = _login(client, "user-1")
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": "ORD-20260811-001", "refund_type": "only_refund",
                  "reason": "不想要了", "amount": 199.0},
            headers=_bearer(alice),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["ticket"]["status"] == "CREATED"
        assert resp.json()["data"]["ticket"]["user_id"] == "user-1"
