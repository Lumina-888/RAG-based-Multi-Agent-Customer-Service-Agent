"""SP-AGENT-003 工具调用契约：参数解析 → 校验 → 归属校验 → 调用。

- 工具 Schema（JSON）：query_order / create_refund_request（设计文档 §6.3）
- 参数由 LLM Function Calling 解析（`OpenAICompatToolParser`）；参数非法时
  **不得**调用真实服务，返回澄清原因
- `execute_query_order`：调用前校验 `order.user_id == 当前用户`，不符返回 4030
  且不返回任何订单数据
- `create_refund_request` 为敏感操作：编排层 CONFIRM 节点前置（见 graph.py），
  本模块只提供参数校验，不直接建单
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from app.services.erp_sim import get_order

logger = logging.getLogger("app.agents.tool_agent")

#: 工具定义（与设计文档 §6.3 对齐）
TOOLS: dict[str, dict] = {
    "query_order": {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "按订单号查询订单状态与物流信息",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "订单号（必填）"}},
                "required": ["order_id"],
            },
        },
    },
    "create_refund_request": {
        "type": "function",
        "function": {
            "name": "create_refund_request",
            "description": (
                "发起退款/售后申请。仅创建申请单，服务端会强制校验订单归属/状态/时效，"
                "资金操作需人工审核"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号（必填）"},
                    "refund_type": {
                        "type": "string", "enum": ["only_refund", "return_refund"],
                    },
                    "reason": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["order_id", "refund_type", "reason", "amount"],
            },
        },
    },
}

#: 订单号形态：ORD-20260811-001 / 纯数字 8+ 位
_ORDER_NO_RE = re.compile(r"\b(?:ORD-)?[A-Z]{0,4}-?\d{8,}(?:-\d{3,})?\b|\bORD-\d{6,}-\d{3,}\b")


def extract_order_id(text: str) -> str | None:
    """从用户消息中提取订单号（无则返回 None，工具层转澄清）。"""
    match = _ORDER_NO_RE.search(text)
    return match.group(0) if match else None


def validate_tool_args(tool_name: str, args: dict | None) -> str | None:
    """参数校验：合法返回 None；非法返回澄清原因（不得调用真实服务）。"""
    if not args:
        return "缺少工具参数，无法执行"
    if tool_name == "query_order":
        if not str(args.get("order_id", "")).strip():
            return "缺少订单号（order_id），请先提供订单号"
        return None
    if tool_name == "create_refund_request":
        if not str(args.get("order_id", "")).strip():
            return "缺少订单号（order_id），请先提供订单号"
        refund_type = args.get("refund_type")
        if refund_type not in ("only_refund", "return_refund"):
            return f"退款类型非法: {refund_type}（仅支持 only_refund / return_refund）"
        if not str(args.get("reason", "")).strip():
            return "缺少退款原因（reason）"
        amount = args.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            return f"退款金额非法: {amount}（必须 > 0）"
        return None
    return f"未知工具: {tool_name}"


class ToolArgsParser(Protocol):
    """工具参数解析协议：真实（OpenAI Function Calling）与 Fake 同接口。"""

    async def parse(self, tool_name: str, message: str) -> dict | None: ...


class OpenAICompatToolParser:
    """OpenAI 兼容 Function Calling 解析（SP-CFG-004 客户端 chat_tools 直通）。"""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def parse(self, tool_name: str, message: str) -> dict | None:
        schema = TOOLS.get(tool_name)
        if schema is None:
            return None
        result = await self._llm.chat_tools(
            [{"role": "user", "content": message}], tools=[schema], tool_choice="auto"
        )
        # 兼容 ChatResult（LLMRouter 路由）与 (content, tool_calls) 元组（直连客户端）
        if isinstance(result, tuple):
            _, tool_calls = result
        else:
            tool_calls = getattr(result, "tool_calls", None)
        if not tool_calls:
            return None  # LLM 未产生工具调用（如澄清回复）→ 不调用真实服务
        try:
            return json.loads(tool_calls[0]["function"]["arguments"])
        except (KeyError, json.JSONDecodeError):
            logger.warning("工具参数解析失败: %s", tool_calls)
            return None


class FakeToolParser:
    """测试注入：固定返回参数或 None（模拟解析失败）。"""

    def __init__(self, args: dict | None = None) -> None:
        self.args = args
        self.calls: list[tuple[str, str]] = []

    async def parse(self, tool_name: str, message: str) -> dict | None:
        self.calls.append((tool_name, message))
        return self.args


def execute_query_order(order_id: str, user_id: str) -> dict:
    """归属校验后调用模拟 ERP：他人订单 → 4030 且不返回任何订单数据。"""
    order = get_order(order_id)
    if order is None:
        return {"code": 4041, "data": None, "msg": "订单不存在"}
    if order.user_id != user_id:
        return {"code": 4030, "data": None, "msg": "无权访问该订单"}  # 零数据泄露
    return {"code": 0, "data": {
        "order_id": order.order_id,
        "status": order.status,
        "amount": order.amount,
        "item_title": order.item_title,
        "logistics": order.logistics,
    }, "msg": "ok"}
