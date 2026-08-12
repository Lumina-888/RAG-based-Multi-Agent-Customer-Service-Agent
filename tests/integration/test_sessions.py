"""SP-CHAT-001 会话管理（需真实 Redis + PostgreSQL）：T-CHAT-101~103。

- T-CHAT-101 不存在的 session_id 发消息 → 自动创建会话（PG sessions 表）
- T-CHAT-102 短期上下文 TTL 失效（Redis 过期）但消息历史仍可查（PG 不受 TTL 影响）
- T-CHAT-103 历史查询：时间升序，含 intent / conf / agent_route；归属校验 4030
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.api import sessions as sessions_api
from app.core.config import get_settings
from app.intent.classifier import FakeIntentClassifier
from app.memory.repo import PostgresMessageRepo
from app.memory.store import RedisSessionStore
from app.services.llm import FakeLLM, LLMRouter

SID = "33333333-4444-4555-8666-777777777777"


class MiniES:
    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        return [{"chunk_id": "c1", "doc_id": "d1", "title": "售后政策", "heading_path": "h",
                 "content": "退款将在 3~5 个工作日原路退回。", "score": 0.8}]

    async def search_knn(self, q_vector, size=10, num_candidates=200) -> list[dict]:
        return await self.search_match("", size)

    async def search_rrf(self, q, q_vector, size=10, k=60, num_candidates=200) -> list[dict]:
        return await self.search_match(q, size)


@pytest.fixture
async def redis_ok() -> bool:
    settings = get_settings()
    store = RedisSessionStore(settings.redis_url, ttl=1)  # TTL=1s 便于测过期
    ok = False
    try:
        await store.set_context("__probe__", [{"role": "user", "content": "x"}])
        ok = await store.get_context("__probe__") != []
    except Exception:  # noqa: BLE001 - 连接失败视为不可用
        ok = False
    try:
        await store.clear("__probe__")
        await store.aclose()
    except Exception:  # noqa: BLE001 - 清理失败不掩盖探测结果
        pass
    if not ok:
        pytest.skip("本机 Redis 不可用（需 Redis 7，docker compose 见 M9）")
    return ok


@pytest.fixture
async def pg_ok() -> bool:
    settings = get_settings()
    repo = PostgresMessageRepo(settings.postgres_dsn)
    ok = False
    try:
        await repo.ensure_session("__probe__", "tester")
        ok = await repo.get_session_owner("__probe__") == "tester"
        await repo.delete_session("__probe__")
    except Exception:  # noqa: BLE001 - 连接失败视为不可用
        ok = False
    try:
        await repo.aclose()
    except Exception:  # noqa: BLE001
        pass
    if not ok:
        pytest.skip("本机 PostgreSQL 不可用（需 PostgreSQL 16，docker compose 见 M9）")
    return ok


@pytest.fixture
async def client(redis_ok: bool, pg_ok: bool) -> TestClient:
    """全真实 Redis/PG 存储 + Fake LLM/分类器/检索。"""
    settings = get_settings()
    router = LLMRouter(
        settings,
        FakeLLM("deepseek-v4-flash", replies=["回复内容"] * 4),
        FakeLLM("mimo-v2.5"),
        FakeLLM("mimo-v2.5"),
        backoff=0,
    )
    deps = chat_api.ChatDeps(
        store=RedisSessionStore(settings.redis_url, ttl=1),
        repo=PostgresMessageRepo(settings.postgres_dsn),
        classifier=FakeIntentClassifier(intent="pre_sales", conf=0.95),
        llm=router,
        es=MiniES(),
        embedding=None,
        retrieval_top_k=5,
    )
    app = FastAPI()
    app.include_router(chat_api.router)
    app.include_router(sessions_api.router)
    app.dependency_overrides[chat_api.get_chat_deps] = lambda: deps
    yield TestClient(app)
    await deps.repo.delete_session(SID)
    await deps.store.clear(SID)
    await deps.store.aclose()
    await deps.repo.aclose()


def _post(client: TestClient, message: str) -> None:
    client.post(
        "/api/v1/chat", json={"session_id": SID, "message": message},
        headers={"X-User-Id": "user-1"},
    )


@pytest.mark.spec("SP-CHAT-001")
@pytest.mark.integration
class TestSessionsIntegration:
    def test_chat_101_auto_create_session(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/chat", json={"session_id": SID, "message": "这个保温杯多少钱"},
            headers={"X-User-Id": "user-1"},
        )
        assert resp.status_code == 200
        # 会话已自动创建 + 消息落 PG
        resp2 = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-1"})
        assert resp2.status_code == 200
        messages = resp2.json()["data"]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]

    def test_chat_102_ttl_expiry_history_survives(self, client: TestClient) -> None:
        _post(client, "第一条")
        import time

        time.sleep(1.2)  # TTL=1s → 短期上下文过期

        # 上下文失效但历史可查
        resp = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-1"})
        assert resp.status_code == 200
        assert len(resp.json()["data"]["messages"]) >= 1  # PG 历史不受 TTL 影响

    def test_chat_103_history_ordered_with_meta(self, client: TestClient) -> None:
        _post(client, "第一问")
        _post(client, "第二问")
        resp = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-1"})

        messages = resp.json()["data"]["messages"]
        assert [m["content"] for m in messages] == ["第一问", "回复内容", "第二问", "回复内容"]
        user_msg = messages[0]
        for key in ("intent", "conf", "agent_route"):
            assert key in user_msg

    def test_chat_101_ownership_4030(self, client: TestClient) -> None:
        _post(client, "hi")
        resp = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-2"})
        assert resp.status_code == 403 and resp.json()["code"] == 4030

    def test_chat_101_delete_clears_session(self, client: TestClient) -> None:
        _post(client, "hi")
        resp = client.delete(f"/api/v1/sessions/{SID}", headers={"X-User-Id": "user-1"})
        assert resp.status_code == 200
        resp2 = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-1"})
        assert resp2.status_code == 404 and resp2.json()["code"] == 4040  # 会话已清空
