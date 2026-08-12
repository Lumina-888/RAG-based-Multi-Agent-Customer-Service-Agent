"""SP-CHAT-002 / SP-SSE-001 对话编排（离线单元层，全 Fake 注入，零外部服务）。

覆盖：四路径事件序列（正常/澄清/转人工/图片）、参数校验 4001（非 SSE）、
JSON 合法性、错误路径必发 done、事件持久化与重放（Last-Event-ID）。
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.intent.classifier import FakeIntentClassifier
from app.memory.repo import MemoryMessageRepo
from app.memory.store import FakeSessionStore
from app.services.llm import FakeLLM, LLMRouter
from app.core.config import Settings


def _router(replies: list[str] | None = None, main_fail: int = 0, fallback_fail: int = 0) -> LLMRouter:
    return LLMRouter(
        Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
        FakeLLM("deepseek-v4-flash", replies=replies, fail_times=main_fail),
        FakeLLM("mimo-v2.5", fail_times=fallback_fail),
        FakeLLM("mimo-v2.5", replies=["图片描述内容"]),
        backoff=0,
    )


class MiniES:
    """内存 ES：检索返回给定命中（chat 流程只需非空/空两种行为）。"""

    def __init__(self, hits: list[dict] | None = None) -> None:
        self.hits = hits or [
            {"chunk_id": "c1", "doc_id": "d1", "title": "售后政策", "heading_path": "售后政策 / 退款",
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
        llm=_router(replies=replies, main_fail=main_fail, fallback_fail=fallback_fail),
        es=MiniES(hits=hits),
        embedding=None,  # rrf 会降级 bm25（MiniES.search_match）
        retrieval_top_k=5,
    )


def _client(deps: chat_api.ChatDeps) -> TestClient:
    app = FastAPI()
    app.include_router(chat_api.router)
    app.dependency_overrides[chat_api.get_chat_deps] = lambda: deps
    return TestClient(app)


def _post_sse(client: TestClient, payload: dict, headers: dict | None = None):
    """POST /api/v1/chat 并解析 SSE 事件 → [(event, data_dict)]。"""
    with client.stream("POST", "/api/v1/chat", json=payload, headers=headers or {}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = list(resp.iter_lines())
    events: list[tuple[str, dict]] = []
    current: str | None = None
    for line in lines:
        if line.startswith("event:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = json.loads(line.split(":", 1)[1].strip())  # T-SSE-102 JSON 合法性
            events.append((current or "", data))
    return events


PAYLOAD = {"session_id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", "message": "这个保温杯多少钱"}


@pytest.mark.spec("SP-SSE-001")
class TestChatFlow:
    async def test_sse_101_normal_qa_flow(self) -> None:
        """正常问答：intent → route → retrieval → message(delta) → done。"""
        deps = _deps(intent="pre_sales", conf=0.95, replies=["这款保温杯 59 元。"])
        events = _post_sse(_client(deps), PAYLOAD)

        assert [e for e, _ in events] == ["intent", "route", "retrieval", "message", "message", "done"]
        intent_event = events[0][1]
        assert intent_event["intent"] == "pre_sales" and intent_event["conf"] == 0.95
        route = events[1][1]
        assert route["agent"] == "qa_agent"  # 携带 LLM 修正后的最终 intent/conf
        assert route["intent"] == "pre_sales"
        assert events[2][1]["strategy"] in ("rrf", "bm25-fallback")
        # message delta 语义：delta=true 在前，delta=false 结尾
        assert events[3][1]["delta"] is True and "保温杯" in events[3][1]["content"]
        assert events[4][1]["delta"] is False
        assert events[5][1] == {"ticket_id": None, "transfer": False}

    async def test_sse_101_clarify_flow(self) -> None:
        """澄清路径：intent → route → message(delta) → done（无 retrieval）。"""
        deps = _deps(intent="after_sales", conf=0.5, replies=["无法确认意图"])
        events = _post_sse(_client(deps), {"session_id": PAYLOAD["session_id"], "message": "随便聊聊"})

        assert [e for e, _ in events] == ["intent", "route", "message", "message", "done"]
        assert events[1][1]["agent"] == "clarify"
        assert "说明" in events[2][1]["content"]
        assert events[4][1] == {"ticket_id": None, "transfer": False}

    async def test_sse_101_transfer_flow(self) -> None:
        """转人工路径（human/complaint）：done.transfer=true 标记。"""
        deps = _deps(intent="human", conf=0.95)
        events = _post_sse(_client(deps), {"session_id": PAYLOAD["session_id"], "message": "转人工"})

        assert [e for e, _ in events] == ["intent", "route", "message", "message", "done"]
        assert events[1][1]["agent"] == "transfer_agent"
        assert events[4][1]["transfer"] is True

    async def test_sse_101_transfer_by_abuse_guard(self) -> None:
        """辱骂触发情绪升级 → 转人工（done.transfer=true）。"""
        deps = _deps(intent="after_sales", conf=0.95)
        events = _post_sse(_client(deps), {"session_id": PAYLOAD["session_id"], "message": "你这个垃圾"})

        assert events[-1][1]["transfer"] is True

    async def test_sse_101_vision_flow(self) -> None:
        """图片路径：intent → route → vision → retrieval → message → done。"""
        deps = _deps(intent="after_sales", conf=0.95, replies=["发票已确认。"])
        events = _post_sse(
            _client(deps),
            {**PAYLOAD, "attachments": [{"type": "image", "url": "https://x.com/invoice.png"}]},
        )

        names = [e for e, _ in events]
        assert names.index("vision") > names.index("route")  # vision 在 route 后
        assert names.index("vision") < names.index("retrieval")
        vision = events[names.index("vision")][1]
        assert vision["description"] == "图片描述内容"
        assert vision["model"] == "mimo-v2.5"

    async def test_sse_103_error_path_has_done(self) -> None:
        """LLM 主备均不可用 → 仍发送 done 且带 error{code:5001}。"""
        deps = _deps(intent="pre_sales", conf=0.95, main_fail=99, fallback_fail=99)
        events = _post_sse(_client(deps), PAYLOAD)

        assert events[-1][0] == "done"
        assert events[-1][1]["error"]["code"] == 5001

    async def test_sse_102_all_data_valid_json(self) -> None:
        """每条事件 data 均为合法 JSON（_post_sse 内 json.loads 已强制）。"""
        deps = _deps(intent="refund", conf=0.9, replies=["已为您提交退款申请。"])
        events = _post_sse(_client(deps), PAYLOAD)
        assert len(events) >= 5

    async def test_sse_101_reject_low_similarity(self) -> None:
        """低相似度（top-1 < 0.45）→ 拒答模板，不编造。"""
        deps = _deps(
            intent="pre_sales", conf=0.95, replies=["不会走到这里"],
            hits=[{"chunk_id": "c1", "doc_id": "d1", "title": "t", "heading_path": "h",
                   "content": "无关内容", "score": 0.2}],
        )
        events = _post_sse(_client(deps), PAYLOAD)
        names = [e for e, _ in events]
        assert "retrieval" in names
        assert "抱歉" in events[names.index("message")][1]["content"]  # 拒答模板
        assert events[-1][1]["error"] is None if "error" in events[-1][1] else True

    # ---------- SP-CHAT-002 参数校验（4001，流前统一 JSON 非 SSE） ----------

    def test_chat_201_missing_fields(self) -> None:
        client = _client(_deps())
        resp = client.post("/api/v1/chat", json={"message": "你好"})
        assert resp.status_code == 400 and resp.json()["code"] == 4001
        resp2 = client.post("/api/v1/chat", json={"session_id": "x"})
        assert resp2.status_code == 400 and resp2.json()["code"] == 4001

    def test_chat_202_oversize_message(self) -> None:
        client = _client(_deps())
        resp = client.post(
            "/api/v1/chat", json={"session_id": "x", "message": "长" * 501}
        )
        assert resp.status_code == 400 and resp.json()["code"] == 4001

    def test_chat_201_invalid_attachment(self) -> None:
        client = _client(_deps())
        resp = client.post(
            "/api/v1/chat",
            json={"session_id": "x", "message": "hi",
                  "attachments": [{"type": "video", "url": "https://x/v.mp4"}]},
        )
        assert resp.status_code == 400 and resp.json()["code"] == 4001

    # ---------- 事件持久化与重放 ----------

    async def test_sse_104_events_persisted_and_replayed(self) -> None:
        deps = _deps(intent="pre_sales", conf=0.95, replies=["回复甲"])
        sid = PAYLOAD["session_id"]
        events1 = _post_sse(_client(deps), PAYLOAD)
        stored = await deps.store.get_events(sid)
        assert len(stored) == len(events1)  # 事件序列持久化至 session:{id}:events

        # 带 Last-Event-ID 重放：只回放 id > last 的事件（此处无新事件）
        deps2 = _deps(intent="pre_sales", conf=0.95, replies=["回复乙"])
        client2 = _client(deps2)
        with client2.stream(
            "POST", "/api/v1/chat", json=PAYLOAD, headers={"Last-Event-ID": str(len(events1))}
        ) as resp:
            body = "".join(resp.iter_text())
        assert body.strip() == ""  # 无新事件可重放
