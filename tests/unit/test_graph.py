"""SP-AGENT-004 状态机编排（LangGraph，离线单元层）：T-AGENT-401/402 + 补充。

- T-AGENT-401 全流程一次通过（pre_sales → qa_agent 回答；事件序 _sse）
- T-AGENT-402 中途异常走兜底（LLM 全挂 → 兜底回复，链不中断）
- T-AGENT-403 敏感操作（建单）CONFIRM 挂起：未确认不建单；确认后建单返回单号
- T-AGENT-404 挂起期间非确认/取消消息 → 拒绝处理
"""
from __future__ import annotations

import pytest

from app.agents.graph import execute_graph
from app.api.chat import ChatDeps
from app.core.config import Settings
from app.intent.classifier import FakeIntentClassifier
from app.memory.repo import MemoryMessageRepo
from app.memory.store import FakeSessionStore
from app.services.llm import FakeLLM, LLMRouter


class MiniES:
    def __init__(self, hits: list[dict] | None = None) -> None:
        self.hits = hits or [
            {"chunk_id": "c1", "doc_id": "d1", "title": "售后政策", "heading_path": "h",
             "content": "已签收 7 天内支持无理由退货，退款 3~5 个工作日到账。", "score": 0.8}
        ]

    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        return self.hits[:size]

    async def search_knn(self, q_vector, size=10, num_candidates=200) -> list[dict]:
        return self.hits[:size]

    async def search_rrf(self, q, q_vector, size=10, k=60, num_candidates=200) -> list[dict]:
        return self.hits[:size]


def _deps(
    intent: str = "pre_sales", conf: float = 0.95, replies: list[str] | None = None,
    main_fail: int = 0, fallback_fail: int = 0,
) -> ChatDeps:
    return ChatDeps(
        store=FakeSessionStore(),
        repo=MemoryMessageRepo(),
        classifier=FakeIntentClassifier(intent=intent, conf=conf),
        llm=LLMRouter(
            Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
            FakeLLM("deepseek-v4-flash", replies=replies, fail_times=main_fail),
            FakeLLM("mimo-v2.5", fail_times=fallback_fail),
            FakeLLM("mimo-v2.5"),
            backoff=0,
        ),
        es=MiniES(),
        embedding=None,
        retrieval_top_k=5,
    )


@pytest.mark.spec("SP-AGENT-004")
class TestGraph:
    async def test_agent_401_full_flow(self) -> None:
        deps = _deps(intent="pre_sales", conf=0.95, replies=["支持 7 天无理由退货[1]。"])
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="退货政策是什么"
        )

        assert state["intent"] == "pre_sales" and state["conf"] == 0.95
        assert state["route"] == "qa_agent"
        assert state["reply"] and "退货" in state["reply"]
        events = [e["event"] for e in state["_sse"]]
        assert events == ["intent", "route", "retrieval", "message", "message"]

    async def test_agent_402_node_exception_fallback(self) -> None:
        """中途异常不中断整条链：LLM 全挂 → 兜底回复 + error_code=5001。"""
        deps = _deps(intent="pre_sales", conf=0.95, main_fail=99, fallback_fail=99)
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="退货政策"
        )

        assert state["reply"]  # 兜底回复非空
        assert state["error_code"] == 5001
        assert state["_sse"][-1]["event"] == "message"  # 链正常收尾（不中断）

    async def test_agent_403_confirm_gate_before_refund(self) -> None:
        """建单前必须 CONFIRM：未确认不建单；确认后建单返回单号。"""
        deps = _deps(intent="refund", conf=0.95)
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1",
            message="我要退款 订单号 ORD-20260811-001",
        )

        assert state["pending_confirm"] is True  # 挂起等待确认
        assert state.get("ticket_id") is None  # 未确认 → 未建单
        assert deps.refund_gateway.tickets == []  # 真实服务零调用
        assert "确认" in state["reply"]  # 引导确认话术

        # 用户确认 → 建单
        state2 = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="确认",
            pending=state["pending_args"],
        )
        assert state2["pending_confirm"] is False
        assert state2["ticket_id"]  # 返回单号
        assert len(deps.refund_gateway.tickets) == 1

    async def test_agent_403_cancel_aborts(self) -> None:
        deps = _deps(intent="refund", conf=0.95)
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1",
            message="我要退款 订单号 ORD-20260811-001",
        )
        state2 = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="取消",
            pending=state["pending_args"],
        )
        assert state2.get("ticket_id") is None
        assert deps.refund_gateway.tickets == []  # 取消 → 不建单

    async def test_agent_404_pending_deny_other_messages(self) -> None:
        deps = _deps(intent="refund", conf=0.95)
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1",
            message="我要退款 订单号 ORD-20260811-001",
        )
        state2 = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="帮我查物流",
            pending=state["pending_args"],
        )
        assert "确认" in state2["reply"] or "取消" in state2["reply"]  # 挂起期间仅接受确认/取消
        assert state2.get("ticket_id") is None

    async def test_agent_401_transfer_flow(self) -> None:
        deps = _deps(intent="human", conf=0.95)
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="转人工",
        )
        assert state["route"] == "transfer_agent"
        assert state["transfer_needed"] is True
        assert "人工" in state["reply"]
        # 摘要已落库（SP-AGENT-005）
        assert await deps.store.get_transfer_summary("s1")
