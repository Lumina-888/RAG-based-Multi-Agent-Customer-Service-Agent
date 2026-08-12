"""SP-AGENT-001 路由规则：T-AGENT-101/102。

- T-AGENT-101 全映射正确：order_query→tool_agent、refund→refund_agent、
  complaint/human→transfer_agent、pre_sales/after_sales→qa_agent
- T-AGENT-102 未知意图不路由（None → 澄清）
"""
from __future__ import annotations

import pytest

from app.agents.router import ROUTE_TABLE, route


@pytest.mark.spec("SP-AGENT-001")
class TestRouter:
    def test_agent_101_full_mapping(self) -> None:
        assert route("order_query") == "tool_agent"
        assert route("refund") == "refund_agent"
        assert route("complaint") == "transfer_agent"
        assert route("human") == "transfer_agent"
        assert route("pre_sales") == "qa_agent"
        assert route("after_sales") == "qa_agent"
        # 路由表与意图体系一致（6 类全覆盖）
        assert set(ROUTE_TABLE) == {
            "pre_sales", "after_sales", "order_query", "refund", "complaint", "human",
        }

    def test_agent_102_unknown_intent_clarify(self) -> None:
        assert route("invalid") is None
        assert route("") is None
        assert route("whatever") is None
