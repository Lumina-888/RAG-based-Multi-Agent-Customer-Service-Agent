"""SP-SEC-003 认证与鉴权（离线单元层，内存 TokenStore）。

- 登录：一键登录（user_id）/ 账号密码；错误凭证 → 4010
- token：签发 / 解析 / 撤销（Bearer 头）
- 4010：未认证访问受保护接口（退款建单/会话历史）；4030：越权（他人数据）
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
from app.seed.users import DEMO_USERS

SID = "55555555-6666-4777-8888-999999999999"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(refund_api.router)
    app.include_router(sessions_api.router)
    store = MemoryTokenStore()
    app.dependency_overrides[auth_api.get_token_store] = lambda: store
    app.dependency_overrides[refund_api.get_refund_service] = lambda: RefundService(
        repo=MemoryTicketRepo()
    )
    return TestClient(app)


def _login(client: TestClient, **body) -> dict:
    resp = client.post("/api/v1/auth/login", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _headers(token: str | None = None, user_id: str | None = None) -> dict:
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {"X-User-Id": user_id} if user_id else {}


@pytest.mark.spec("SP-SEC-003")
class TestAuth:
    def test_login_one_click(self, client: TestClient) -> None:
        data = _login(client, user_id="user-1")
        assert data["user_id"] == "user-1" and data["token"].startswith("tk_")

    def test_login_username_password(self, client: TestClient) -> None:
        alice = DEMO_USERS["user-1"]
        data = _login(client, username=alice["username"], password=alice["password"])
        assert data["user_id"] == "user-1"

    def test_login_wrong_password_4010(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": "wrong"}
        )
        assert resp.status_code == 401 and resp.json()["code"] == 4010

    def test_login_unknown_user_4010(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "x"}
        )
        assert resp.status_code == 401 and resp.json()["code"] == 4010

    async def test_token_issue_resolve_revoke(self) -> None:
        store = MemoryTokenStore()
        token = await store.issue("user-1")
        assert token.startswith("tk_")
        assert await store.resolve(token) == "user-1"
        assert await store.resolve("tk_bogus") is None
        await store.revoke(token)
        assert await store.resolve(token) is None

    async def test_token_expiry(self) -> None:
        """TTL 过期 → 解析失败（登录态失效）。"""
        import time

        store = MemoryTokenStore()
        token = await store.issue("user-1", ttl=1)
        time.sleep(1.1)
        assert await store.resolve(token) is None  # 过期即失效

    async def test_redis_token_store(self) -> None:
        """RedisTokenStore（fakeredis 替身）：签发/解析/撤销。"""
        import fakeredis.aioredis

        from app.auth.token_store import RedisTokenStore

        store = RedisTokenStore("redis://x",
                                client=fakeredis.aioredis.FakeRedis(decode_responses=True))
        token = await store.issue("user-1")
        assert await store.resolve(token) == "user-1"
        assert await store.resolve("tk_bogus") is None
        await store.revoke(token)
        assert await store.resolve(token) is None
        await store.aclose()

    def test_security_301_unauthenticated_4010(self, client: TestClient) -> None:
        """未认证访问受保护接口 → 4010。"""
        # 退款建单
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": "ORD-20260811-001", "refund_type": "only_refund",
                  "reason": "r", "amount": 1.0},
        )
        assert resp.status_code == 401 and resp.json()["code"] == 4010
        # 会话历史
        resp2 = client.get(f"/api/v1/sessions/{SID}/messages")
        assert resp2.status_code == 401 and resp2.json()["code"] == 4010

    def test_security_301_invalid_bearer_4010(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": "ORD-20260811-001", "refund_type": "only_refund",
                  "reason": "r", "amount": 1.0},
            headers=_headers(token="tk_bogus"),
        )
        assert resp.status_code == 401 and resp.json()["code"] == 4010

    def test_security_303_login_then_access(self, client: TestClient) -> None:
        """登录后带 Bearer token 正常访问受保护接口。"""
        data = _login(client, user_id="user-1")
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": "ORD-20260811-001", "refund_type": "only_refund",
                  "reason": "不想要了", "amount": 199.0},
            headers=_headers(token=data["token"]),
        )
        assert resp.status_code == 200 and resp.json()["data"]["ticket"]["status"] == "CREATED"

    def test_security_302_cross_user_4030(self, client: TestClient) -> None:
        """已认证用户访问他人订单 → 4030 且不泄露数据。"""
        data = _login(client, user_id="user-2")  # user-2 的订单是 ORD-20260811-003
        resp = client.post(
            "/api/v1/refund-requests",
            json={"order_id": "ORD-20260811-001", "refund_type": "only_refund",
                  "reason": "r", "amount": 1.0},  # 该订单属于 user-1
            headers=_headers(token=data["token"]),
        )
        assert resp.status_code == 403 and resp.json()["code"] == 4030
        assert resp.json()["data"] is None  # 不泄露订单数据

    def test_security_302_sessions_ownership(self, client: TestClient) -> None:
        """会话归属：他人会话 → 4030。"""
        # user-1 建立会话（chat 端点匿名用 X-User-Id 标记归属）
        app = client.app
        from app.api import chat as chat_api
        from app.intent.classifier import FakeIntentClassifier
        from app.memory.repo import MemoryMessageRepo
        from app.memory.store import FakeSessionStore
        from app.services.llm import FakeLLM, LLMRouter
        from app.core.config import Settings

        chat_deps = chat_api.ChatDeps(
            store=FakeSessionStore(), repo=MemoryMessageRepo(),
            classifier=FakeIntentClassifier(intent="pre_sales", conf=0.95),
            llm=LLMRouter(Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
                          FakeLLM("deepseek-v4-flash", replies=["ok"]),
                          FakeLLM("mimo-v2.5"), FakeLLM("mimo-v2.5"), backoff=0),
            es=None, embedding=None, retrieval_top_k=5,
        )
        app.include_router(chat_api.router)
        app.dependency_overrides[chat_api.get_chat_deps] = lambda: chat_deps

        client.post("/api/v1/chat", json={"session_id": SID, "message": "hi"},
                    headers={"X-User-Id": "user-1"})
        # user-2 访问 user-1 的会话 → 4030
        data = _login(client, user_id="user-2")
        resp = client.get(f"/api/v1/sessions/{SID}/messages", headers=_headers(token=data["token"]))
        assert resp.status_code == 403 and resp.json()["code"] == 4030
        # 会话 owner 本人（Bearer token）→ 200
        data1 = _login(client, user_id="user-1")
        resp2 = client.get(f"/api/v1/sessions/{SID}/messages", headers=_headers(token=data1["token"]))
        assert resp2.status_code == 200
