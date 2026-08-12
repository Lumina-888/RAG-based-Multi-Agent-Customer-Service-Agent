"""SP-CHAT-001 会话管理（离线单元层，内存 Store/Repo）：T-CHAT-101~103。

- T-CHAT-101 不存在的 session_id 发消息 → 自动创建会话
- T-CHAT-102 短期上下文 TTL 失效（记忆过期）但消息历史仍可查（PG 持久不受 TTL 影响）
- T-CHAT-103 历史查询：时间升序，含 intent / conf / agent_route；会话归属校验 4030
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.api import sessions as sessions_api
from app.intent.classifier import FakeIntentClassifier
from app.memory.repo import MemoryMessageRepo
from app.memory.store import FakeSessionStore
from app.services.llm import FakeLLM, LLMRouter
from app.core.config import Settings

SID = "11111111-2222-4333-8444-555555555555"


class MiniES:
    """内存 ES：chat 流程检索环节的最小替身。"""

    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        return [{"chunk_id": "c1", "doc_id": "d1", "title": "售后政策", "heading_path": "h",
                 "content": "退款将在 3~5 个工作日原路退回。", "score": 0.8}]

    async def search_knn(self, q_vector, size=10, num_candidates=200) -> list[dict]:
        return await self.search_match("", size)

    async def search_rrf(self, q, q_vector, size=10, k=60, num_candidates=200) -> list[dict]:
        return await self.search_match(q, size)


def _deps() -> chat_api.ChatDeps:
    router = LLMRouter(
        Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
        FakeLLM("deepseek-v4-flash", replies=["回复内容"] * 4),
        FakeLLM("mimo-v2.5"),
        FakeLLM("mimo-v2.5"),
        backoff=0,
    )
    return chat_api.ChatDeps(
        store=FakeSessionStore(),
        repo=MemoryMessageRepo(),
        classifier=FakeIntentClassifier(intent="pre_sales", conf=0.95),
        llm=router,
        es=MiniES(),
        embedding=None,
        retrieval_top_k=5,
    )


def _post(client: TestClient, message: str) -> None:
    """带归属头的对话请求（会话 owner = user-1）。"""
    client.post(
        "/api/v1/chat", json={"session_id": SID, "message": message},
        headers={"X-User-Id": "user-1"},
    )


@pytest.fixture
def client(deps: chat_api.ChatDeps) -> TestClient:
    app = FastAPI()
    app.include_router(chat_api.router)
    app.include_router(sessions_api.router)
    app.dependency_overrides[chat_api.get_chat_deps] = lambda: deps
    return TestClient(app)


@pytest.fixture
def deps() -> chat_api.ChatDeps:
    return _deps()


@pytest.mark.spec("SP-CHAT-001")
class TestSessions:
    async def test_chat_101_auto_create_session(self, client: TestClient, deps: chat_api.ChatDeps) -> None:
        resp = client.post(
            "/api/v1/chat",
            json={"session_id": SID, "message": "这个保温杯多少钱"},
            headers={"X-User-Id": "user-1"},
        )
        assert resp.status_code == 200

        assert await deps.repo.get_session_owner(SID) == "user-1"  # 会话已自动创建
        user_msgs = [m for m in await deps.repo.list_messages(SID) if m.role == "user"]
        assert len(user_msgs) == 1 and "保温杯" in user_msgs[0].content

    async def test_chat_102_ttl_expiry_history_survives(
        self, client: TestClient, deps: chat_api.ChatDeps
    ) -> None:
        _post(client, "第一条")
        # 短期上下文写入（TTL 30 分钟）
        await deps.store.set_context(SID, [{"role": "user", "content": "第一条"}])
        assert await deps.store.get_context(SID)  # TTL 内可注入

        deps.store.expire_context(SID)  # 模拟 30 分钟 TTL 过期
        assert await deps.store.get_context(SID) == []  # 记忆失效

        # 消息历史在 PostgreSQL 持久保留，不受 TTL 影响
        resp = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-1"})
        assert resp.status_code == 200
        messages = resp.json()["data"]["messages"]
        assert len(messages) >= 1  # 历史仍可查

    def test_chat_103_history_ordered_with_meta(
        self, client: TestClient, deps: chat_api.ChatDeps
    ) -> None:
        for msg in ("第一问", "第二问"):
            _post(client, msg)
        resp = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-1"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        messages = body["data"]["messages"]
        contents = [m["content"] for m in messages]
        assert contents == ["第一问", "回复内容", "第二问", "回复内容"]  # 时间升序
        user_msg = messages[0]
        assert user_msg["role"] == "user"
        for key in ("intent", "conf", "agent_route"):  # 含意图/置信度/路由元数据
            assert key in user_msg

    def test_chat_101_ownership_4030(self, client: TestClient) -> None:
        client.post(
            "/api/v1/chat", json={"session_id": SID, "message": "hi"},
            headers={"X-User-Id": "user-1"},
        )
        # 他人访问 → 4030 且不泄露数据
        resp = client.get(f"/api/v1/sessions/{SID}/messages", headers={"X-User-Id": "user-2"})
        assert resp.status_code == 403
        assert resp.json()["code"] == 4030

    def test_chat_101_session_not_found_4040(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/sessions/99999999-9999-4999-8999-999999999999/messages",
            headers={"X-User-Id": "user-1"},
        )
        assert resp.status_code == 404 and resp.json()["code"] == 4040

    async def test_chat_101_delete_clears_session(self, client: TestClient, deps: chat_api.ChatDeps) -> None:
        _post(client, "hi")
        resp = client.delete(f"/api/v1/sessions/{SID}", headers={"X-User-Id": "user-1"})
        assert resp.status_code == 200 and resp.json()["data"]["deleted"] is True

        assert await deps.repo.list_messages(SID) == []  # 历史清空
        assert await deps.store.get_events(SID) == []  # 事件序列清空
        assert await deps.store.get_context(SID) == []  # 短期上下文清空
