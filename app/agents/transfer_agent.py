"""SP-AGENT-005 转人工 Agent：会话摘要生成 + Redis 落库。

- 摘要内容：问题（最后一条用户消息）、已提供信息、订单号（正则提取 + 工具结果）
- 摘要写入 Redis `session:{id}:transfer`（前端展示"已转接人工坐席 1001"）
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("app.agents.transfer_agent")

_ORDER_NO_RE = re.compile(r"\bORD-\d{6,}-\d{3,}\b|\b\d{8,}\b")


def generate_summary(
    messages: list[dict],
    intent: str,
    tool_results: list[dict] | None = None,
) -> str:
    """生成人工会话摘要：问题、已提供信息、订单号（SP-AGENT-005）。"""
    user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
    question = user_messages[-1] if user_messages else ""
    order_ids = sorted(set(_ORDER_NO_RE.findall(" ".join(user_messages))))
    details = []
    if order_ids:
        details.append(f"订单号：{'、'.join(order_ids)}")
    for tool_result in tool_results or []:
        order_id = tool_result.get("order_id")
        if order_id and order_id not in order_ids:
            details.append(f"订单号：{order_id}")
        status = tool_result.get("status")
        if status:
            details.append(f"订单状态：{status}")
    provided = "；".join(details) if details else "暂无额外信息"
    return (
        f"【会话摘要】意图：{intent}；问题：{question}；"
        f"已提供信息：{provided}"
    )


async def mark_transfer(store: Any, session_id: str, summary: str) -> None:
    """摘要写入 Redis（session:{id}:transfer）。"""
    await store.set_transfer_summary(session_id, summary)
    logger.info("转人工摘要已落库 session_id=%s", session_id)
