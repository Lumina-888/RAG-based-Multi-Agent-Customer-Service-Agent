"""SP-SSE-001 SSE 事件协议（E2E：全栈应用 + Fake 外部依赖，离线可跑）。

- T-SSE-101 事件顺序断言（正常/澄清/转人工/图片 四路径，E2E 总用例 ≥ 10 条）
- T-SSE-102 每条事件 data 为合法 JSON；message delta 语义正确
- T-SSE-103 错误路径必有 done（含 error.code）；参数校验失败为非 SSE 统一 JSON
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.core.config import Settings
from app.intent.classifier import FakeIntentClassifier
from app.memory.repo import MemoryMessageRepo
from app.memory.store import FakeSessionStore
from app.services.llm import FakeLLM, LLMRouter

SID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class MiniES:
    def __init__(self, hits: list[dict] | None = None) -> None:
        self.hits = hits or [
            {"chunk_id": "c1", "doc_id": "d1", "title": "售后政策", "heading_path": "h",
             "content": "退款将在 3~5 个工作日原路退回。", "score": 0.8}
        ]

    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        return self.hits[:size]

    async def search_knn(self, q_vector, size=10, num_candidates=200) -> list[dict]:
        return self.hits[:size]

    async def search_rrf(self, q, q_vector, size=10, k=60, num_candidates=200) -> list[dict]:
        return self.hits[:size]


def _deps(
    intent: str = "pre_sales", conf: float = 0.95, replies: list[str] | None = None,
    main_fail: int = 0, fallback_fail: int = 0, hits: list[dict] | None = None,
) -> chat_api.ChatDeps:
    return chat_api.ChatDeps(
        store=FakeSessionStore(),
        repo=MemoryMessageRepo(),
        classifier=FakeIntentClassifier(intent=intent, conf=conf),
        llm=LLMRouter(
            Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
            FakeLLM("deepseek-v4-flash", replies=replies, fail_times=main_fail),
            FakeLLM("mimo-v2.5", fail_times=fallback_fail),
            FakeLLM("mimo-v2.5", replies=["发票信息已确认"]),
            backoff=0,
        ),
        es=MiniES(hits=hits),
        embedding=None,
        retrieval_top_k=5,
    )


@pytest.fixture
def client() -> TestClient:
    """全栈应用（chat + sessions 路由）+ 依赖覆盖。"""
    from app.main import app  # 延迟导入：避免收集期触发 setup_logging

    app.dependency_overrides[chat_api.get_chat_deps] = lambda: _deps()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _post(client: TestClient, payload: dict) -> list[tuple[str, dict, int]]:
    """POST 并解析 SSE 行 → [(event, data, id)]；断言 JSON 合法（T-SSE-102）。"""
    with client.stream("POST", "/api/v1/chat", json=payload) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = list(resp.iter_lines())
    events: list[tuple[str, dict, int]] = []
    current: str | None = None
    event_id: int | None = None
    for line in lines:
        if line.startswith("id:"):
            event_id = int(line.split(":", 1)[1].strip())
        elif line.startswith("event:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = json.loads(line.split(":", 1)[1].strip())  # T-SSE-102 JSON 合法性
            events.append((current or "", data, event_id or 0))
    return events


def _names(events: list[tuple[str, dict, int]]) -> list[str]:
    return [e for e, _, _ in events]


BASE = {"session_id": SID, "message": "这个保温杯多少钱"}


@pytest.mark.spec("SP-SSE-001")
class TestSseE2E:
    def test_sse_101_normal_flow_order(self, client: TestClient) -> None:
        events = _post(client, {**BASE, "message": "保温杯多少钱"})
        assert _names(events) == ["intent", "route", "retrieval", "message", "message", "done"]

    def test_sse_101_clarify_flow_order(self, client: TestClient) -> None:
        client.app.dependency_overrides[chat_api.get_chat_deps] = lambda: _deps(
            intent="after_sales", conf=0.5, replies=["无法确认"]
        )
        events = _post(client, {**BASE, "message": "随便聊聊"})
        assert _names(events) == ["intent", "route", "message", "message", "done"]
        assert events[3][1]["delta"] is False

    def test_sse_101_transfer_flow_order(self, client: TestClient) -> None:
        client.app.dependency_overrides[chat_api.get_chat_deps] = lambda: _deps(intent="human")
        events = _post(client, {**BASE, "message": "转人工"})
        assert _names(events) == ["intent", "route", "message", "message", "done"]
        assert events[-1][1]["transfer"] is True

    def test_sse_101_abuse_transfer(self, client: TestClient) -> None:
        events = _post(client, {**BASE, "message": "你这个垃圾"})
        assert _names(events)[-1] == "done"
        assert events[-1][1]["transfer"] is True

    def test_sse_101_vision_flow_order(self, client: TestClient) -> None:
        events = _post(client, {**BASE, "attachments": [{"type": "image", "url": "https://x/i.png"}]})
        names = _names(events)
        assert names[-1] == "done"
        assert names.index("vision") > names.index("route")
        assert names.index("vision") < names.index("retrieval")

    def test_sse_101_refund_qa(self, client: TestClient) -> None:
        client.app.dependency_overrides[chat_api.get_chat_deps] = lambda: _deps(
            intent="refund", replies=["已提交退款申请"]
        )
        events = _post(client, {**BASE, "message": "我要退款"})
        assert _names(events) == ["intent", "route", "retrieval", "message", "message", "done"]
        assert events[1][1]["intent"] == "refund"  # route 携带最终 intent

    def test_sse_101_order_query_qa(self, client: TestClient) -> None:
        client.app.dependency_overrides[chat_api.get_chat_deps] = lambda: _deps(
            intent="order_query", replies=["订单查询结果"]
        )
        events = _post(client, {**BASE, "message": "我的订单到哪了"})
        assert _names(events)[-1] == "done"

    def test_sse_101_reject_low_similarity(self, client: TestClient) -> None:
        client.app.dependency_overrides[chat_api.get_chat_deps] = lambda: _deps(
            hits=[{"chunk_id": "c1", "doc_id": "d1", "title": "t", "heading_path": "h",
                   "content": "无关", "score": 0.2}]
        )
        events = _post(client, BASE)
        assert "retrieval" in _names(events)
        msg = next(d for e, d, _ in events if e == "message")
        assert "抱歉" in msg["content"]  # 拒答模板

    def test_sse_102_all_events_valid_json_and_id(self, client: TestClient) -> None:
        events = _post(client, BASE)
        for i, (name, data, event_id) in enumerate(events):
            assert name and isinstance(data, dict)
            assert event_id == i + 1  # id 从 1 递增（重放依据）
        # message delta 语义
        deltas = [d["delta"] for e, d, _ in events if e == "message"]
        assert deltas == [True, False]

    def test_sse_103_error_path_done_with_code(self, client: TestClient) -> None:
        client.app.dependency_overrides[chat_api.get_chat_deps] = lambda: _deps(
            main_fail=99, fallback_fail=99
        )
        events = _post(client, BASE)
        assert events[-1][0] == "done"
        assert events[-1][1]["error"]["code"] == 5001

    def test_sse_103_validation_failure_non_sse(self, client: TestClient) -> None:
        """流开始前校验失败：统一 JSON（非 SSE），无任何事件。"""
        resp = client.post("/api/v1/chat", json={"session_id": SID})
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["code"] == 4001

    def test_sse_101_replay_last_event_id(self, client: TestClient) -> None:
        events = _post(client, BASE)
        last_id = events[-1][2]
        # 重放：Last-Event-ID = 全部已发 → 无新事件
        with client.stream(
            "POST", "/api/v1/chat", json=BASE, headers={"Last-Event-ID": str(last_id)}
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert body.strip() == ""
