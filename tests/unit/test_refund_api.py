"""SP-REF-008 / SP-REF-001 API 层（离线，内存 repo 注入）：T-REF-801/802 + 补充。

- T-REF-801 全链路审计可查（GET /tickets/{id}/audit）
- T-REF-802 列表查询（GET /tickets?status=）与审计接口冒烟
- T-REF-701 API 层：transition 仅允许受限迁移（APPROVING→APPROVED/REJECTED），
  任何直达 REFUNDING 的尝试 → 4091（公开 API 无法绕过审核直接打款）
- T-REF-101/102 API 层：非法入参 → 4001 统一 JSON
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import refund as refund_api
from app.refund.repo import MemoryTicketRepo
from app.refund.service import RefundService

ORD = "ORD-20260811-001"


@pytest.fixture
def client() -> tuple[TestClient, RefundService]:
    app = FastAPI()
    app.include_router(refund_api.router)
    service = RefundService(repo=MemoryTicketRepo())
    app.dependency_overrides[refund_api.get_refund_service] = lambda: service
    return TestClient(app), service


def _create(client: TestClient, headers: dict | None = None) -> dict:
    resp = client.post(
        "/api/v1/refund-requests",
        json={"order_id": ORD, "refund_type": "only_refund",
              "reason": "不想要了", "amount": 199.0},
        headers=headers or {"X-User-Id": "user-1"},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["ticket"]


def _to_approving(client: TestClient, service: RefundService, ticket: dict) -> None:
    """内部审核服务进入 APPROVING（公开 API 无法直达，SP-REF-007）。"""
    import asyncio

    asyncio.run(service.transition(ticket["ticket_id"], "APPROVING",
                                   operator="system_auto", reason="审核开始"))


@pytest.mark.spec("SP-REF-008")
class TestTicketsApi:
    def test_ref_801_audit_chain(self, client: tuple[TestClient, RefundService]) -> None:
        client, service = client
        ticket = _create(client)
        _to_approving(client, service, ticket)  # 内部审核 → APPROVING
        # 模拟坐席受限迁移（APPROVING→APPROVED）
        resp = client.post(
            f"/api/v1/tickets/{ticket['ticket_id']}/transition",
            json={"status": "APPROVED", "operator": "agent-01", "reason": "通过"},
        )
        assert resp.status_code == 200, resp.text

        resp = client.get(f"/api/v1/tickets/{ticket['ticket_id']}/audit")
        assert resp.status_code == 200
        logs = resp.json()["data"]["audit_logs"]
        assert len(logs) == 3  # create + APPROVING + APPROVED
        assert logs[0]["action"] == "create"
        assert logs[-1]["to_status"] == "APPROVED"
        assert logs[-1]["operator"] == "agent-01"
        for log in logs:
            assert {"operator", "action", "from_status", "to_status", "ts"} <= set(log)

    def test_ref_802_list_by_status(self, client: tuple[TestClient, RefundService]) -> None:
        client, _ = client
        t1 = _create(client)
        resp = client.get("/api/v1/tickets", params={"status": "CREATED"})
        assert resp.status_code == 200
        items = resp.json()["data"]["tickets"]
        assert any(t["ticket_id"] == t1["ticket_id"] for t in items)

        resp2 = client.get("/api/v1/tickets", params={"status": "REFUNDED"})
        assert resp2.json()["data"]["tickets"] == []

    def test_ref_701_transition_cannot_reach_refunding(self, client: tuple[TestClient, RefundService]) -> None:
        """公开 API 无法绕过审核直接打款：直达 REFUNDING → 4091。"""
        client, _ = client
        ticket = _create(client)
        resp = client.post(
            f"/api/v1/tickets/{ticket['ticket_id']}/transition",
            json={"status": "REFUNDING", "operator": "user-1", "reason": "直接打款"},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == 4091

    def test_ref_701_transition_illegal_4091(self, client: tuple[TestClient, RefundService]) -> None:
        client, _ = client
        ticket = _create(client)
        resp = client.post(
            f"/api/v1/tickets/{ticket['ticket_id']}/transition",
            json={"status": "REFUNDED", "operator": "user-1", "reason": "跳过审核"},
        )
        assert resp.status_code == 409 and resp.json()["code"] == 4091

    def test_ref_101_api_4001(self, client: tuple[TestClient, RefundService]) -> None:
        client, _ = client
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": ORD, "refund_type": "refund_now", "reason": "r", "amount": 1.0},
            headers={"X-User-Id": "user-1"},
        )
        assert resp.status_code == 400 and resp.json()["code"] == 4001

    def test_ref_102_api_amount_over_order(self, client: tuple[TestClient, RefundService]) -> None:
        client, _ = client
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": ORD, "refund_type": "only_refund", "reason": "r", "amount": 99999.0},
            headers={"X-User-Id": "user-1"},
        )
        assert resp.status_code == 400 and resp.json()["code"] == 4001

    def test_ref_002_api_unauthenticated_4010(self, client: tuple[TestClient, RefundService]) -> None:
        client, _ = client
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": ORD, "refund_type": "only_refund", "reason": "r", "amount": 1.0},
        )
        assert resp.status_code == 401 and resp.json()["code"] == 4010  # 未登录

    def test_ref_201_api_ownership_4030(self, client: tuple[TestClient, RefundService]) -> None:
        client, _ = client
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": ORD, "refund_type": "only_refund", "reason": "r", "amount": 1.0},
            headers={"X-User-Id": "user-2"},
        )
        assert resp.status_code == 403 and resp.json()["code"] == 4030
