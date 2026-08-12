"""SP-AGENT-005 转人工：T-AGENT-501/502。

- T-AGENT-501 会话摘要生成（问题、已提供信息、订单号）
- T-AGENT-502 摘要写入 Redis（session:{id}:transfer），前端显示"已转接人工坐席 1001"
"""
from __future__ import annotations

import pytest

from app.agents.transfer_agent import generate_summary, mark_transfer
from app.memory.store import FakeSessionStore


@pytest.mark.spec("SP-AGENT-005")
class TestTransferAgent:
    def test_agent_501_summary_content(self) -> None:
        messages = [
            {"role": "user", "content": "我的保温杯坏了"},
            {"role": "assistant", "content": "请问您的订单号是多少？"},
            {"role": "user", "content": "订单号 ORD-20260811-001，杯盖漏水"},
        ]
        summary = generate_summary(messages, intent="after_sales")

        assert "杯盖漏水" in summary  # 问题
        assert "ORD-20260811-001" in summary  # 订单号
        assert "after_sales" in summary  # 意图
        assert "已提供" in summary  # 已提供信息标记

    def test_agent_501_summary_with_tool_result(self) -> None:
        messages = [{"role": "user", "content": "帮我查一下订单"}]
        summary = generate_summary(
            messages, intent="order_query",
            tool_results=[{"order_id": "ORD-20260811-002", "status": "已发货"}],
        )
        assert "ORD-20260811-002" in summary
        assert "已发货" in summary

    async def test_agent_502_summary_persisted(self) -> None:
        store = FakeSessionStore()
        await mark_transfer(store, "s1", "【会话摘要】问题：杯盖漏水")

        assert await store.get_transfer_summary("s1") == "【会话摘要】问题：杯盖漏水"
