"""SP-AGENT-003 工具调用契约（集成层）：T-AGENT-301 ~ 304。

- T-AGENT-301 合法参数 → 调用模拟 ERP 返回结构化结果
- T-AGENT-302 非法参数 → 不调用真实服务，返回澄清
- T-AGENT-303 他人订单 → 4030 且不返回任何订单数据
- T-AGENT-304 建单敏感操作：未确认不建单（CONFIRM 节点前置）
"""
from __future__ import annotations

import pytest

from app.agents.graph import execute_graph
from app.agents.tool_agent import execute_query_order, validate_tool_args
from app.api.chat import ChatDeps
from app.core.config import Settings
from app.intent.classifier import FakeIntentClassifier
from app.memory.repo import MemoryMessageRepo
from app.memory.store import FakeSessionStore
from app.services.erp_sim import query_order
from app.services.llm import FakeLLM, LLMRouter


def _deps(intent: str = "order_query", conf: float = 0.95) -> ChatDeps:
    return ChatDeps(
        store=FakeSessionStore(),
        repo=MemoryMessageRepo(),
        classifier=FakeIntentClassifier(intent=intent, conf=conf),
        llm=LLMRouter(
            Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
            FakeLLM("deepseek-v4-flash"),
            FakeLLM("mimo-v2.5"),
            FakeLLM("mimo-v2.5"),
            backoff=0,
        ),
        es=None,
        embedding=None,
        retrieval_top_k=5,
    )


@pytest.mark.spec("SP-AGENT-003")
@pytest.mark.integration
class TestToolsIntegration:
    def test_agent_301_valid_args_calls_service(self) -> None:
        assert validate_tool_args("query_order", {"order_id": "ORD-20260811-001"}) is None
        result = execute_query_order("ORD-20260811-001", user_id="user-1")

        assert result["code"] == 0
        assert result["data"]["status"]  # 结构化结果
        assert query_order("ORD-20260811-001")["code"] == 0  # 真实调用路径一致

    async def test_agent_302_invalid_args_no_call_clarify(self) -> None:
        """缺订单号 → 参数非法 → 不调用真实服务（工具层零调用）→ 澄清。"""
        deps = _deps(intent="order_query")
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="帮我查一下订单"
        )

        assert state.get("tool_calls", []) == []  # 未发生任何工具调用
        assert "订单号" in state["reply"]  # 澄清追问
        assert state["route"] == "tool_agent"

    def test_agent_303_others_order_4030(self) -> None:
        result = execute_query_order("ORD-20260811-001", user_id="user-2")

        assert result["code"] == 4030  # 归属校验
        assert result["data"] is None  # 不返回任何订单数据（零泄露）

    async def test_agent_304_unconfirmed_no_ticket(self) -> None:
        """建单前必须 CONFIRM：未确认不得建单。"""
        deps = _deps(intent="refund")
        state = await execute_graph(
            deps, session_id="s1", user_id="user-1",
            message="我要退款 订单号 ORD-20260811-001",
        )

        assert state["pending_confirm"] is True
        assert deps.refund_gateway.tickets == []  # 未确认 → 真实服务零建单
        assert state.get("ticket_id") is None

        # 确认后建单（CONFIRM 节点放行）
        state2 = await execute_graph(
            deps, session_id="s1", user_id="user-1", message="确认",
            pending=state["pending_args"],
        )
        assert state2["ticket_id"]
        assert len(deps.refund_gateway.tickets) == 1
