"""SP-AGENT-001 路由规则（纯函数）。

路由表：`order_query→tool_agent`、`refund→refund_agent(工单)`、
`complaint/human→transfer_agent`、`pre_sales/after_sales→qa_agent`；
未知意图不路由（返回 None → 编排层走澄清）。
"""
from __future__ import annotations

#: 意图 → Agent 路由表（与 SP-INT-001 六类意图一一对应）
ROUTE_TABLE: dict[str, str] = {
    "pre_sales": "qa_agent",
    "after_sales": "qa_agent",
    "order_query": "tool_agent",
    "refund": "refund_agent",
    "complaint": "transfer_agent",
    "human": "transfer_agent",
}


def route(intent: str) -> str | None:
    """返回该意图对应的 Agent 名；未知意图返回 None（走澄清）。"""
    return ROUTE_TABLE.get(intent)
