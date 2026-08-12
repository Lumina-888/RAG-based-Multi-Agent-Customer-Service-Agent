"""SP-AGENT-003 工具调用契约（离线单元层，Fake 注入）。

- T-AGENT-311 参数校验：非法参数返回原因（不得调用真实服务 → 澄清）
- T-AGENT-312 归属校验：他人订单 → 4030 且不返回任何订单数据
- T-AGENT-313 OpenAI 兼容 Function Calling 解析（MockTransport，零网络）
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.agents.tool_agent import (
    OpenAICompatToolParser,
    execute_query_order,
    extract_order_id,
    validate_tool_args,
)
from app.services.llm import OpenAIClient


@pytest.mark.spec("SP-AGENT-003")
class TestToolAgent:
    def test_agent_311_validate_args(self) -> None:
        assert validate_tool_args("query_order", {"order_id": "ORD-1"}) is None
        assert validate_tool_args("query_order", None) is not None  # 缺参
        assert validate_tool_args("query_order", {}) is not None
        # create_refund_request 必填与枚举
        assert validate_tool_args(
            "create_refund_request",
            {"order_id": "ORD-1", "refund_type": "only_refund", "reason": "不想要了", "amount": 99.0},
        ) is None
        assert validate_tool_args(
            "create_refund_request", {"order_id": "ORD-1", "refund_type": "refund_now", "amount": 99.0}
        ) is not None  # 非法枚举
        assert validate_tool_args("create_refund_request", {"order_id": "ORD-1", "amount": 99.0}) is not None
        # 分支补齐：缺 order_id / 缺 reason / 金额非法 / 未知工具
        assert "订单号" in validate_tool_args("create_refund_request", {"refund_type": "only_refund"})
        assert "reason" in validate_tool_args(
            "create_refund_request", {"order_id": "ORD-1", "refund_type": "only_refund", "amount": 1.0}
        )
        assert "金额" in validate_tool_args(
            "create_refund_request",
            {"order_id": "ORD-1", "refund_type": "only_refund", "reason": "r", "amount": 0},
        )
        assert "未知工具" in validate_tool_args("magic_tool", {"a": 1})

    def test_agent_311_extract_order_id(self) -> None:
        assert extract_order_id("订单 ORD-20260811-001 到哪了") == "ORD-20260811-001"
        assert extract_order_id("没有订单号") is None

    def test_agent_312_ownership_4030(self) -> None:
        # 本人订单 → 正常返回数据
        mine = execute_query_order("ORD-20260811-001", user_id="user-1")
        assert mine["code"] == 0 and mine["data"]["status"]

        # 他人订单 → 4030 且零订单数据
        others = execute_query_order("ORD-20260811-001", user_id="user-2")
        assert others["code"] == 4030
        assert others["data"] is None  # 不泄露任何订单数据
        assert "status" not in str(others["data"])

        # 订单不存在 → 4041
        assert execute_query_order("ORD-00000000-000", user_id="user-1")["code"] == 4041

    async def test_agent_313_openai_function_calling(self) -> None:
        """真实解析路径：OpenAI 兼容 tools 参数 + tool_calls 解析。"""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/chat/completions"):
                captured["body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "choices": [{
                            "message": {
                                "content": None,
                                "tool_calls": [{
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "query_order",
                                        "arguments": '{"order_id": "ORD-20260811-001"}',
                                    },
                                }],
                            }
                        }]
                    },
                )
            return httpx.Response(404)

        client = OpenAIClient(
            "deepseek-v4-flash", "k", "https://api.deepseek.com", timeout=10,
            transport=httpx.MockTransport(handler),
        )
        parser = OpenAICompatToolParser(client)
        args = await parser.parse("query_order", "我的订单到哪了")

        assert args == {"order_id": "ORD-20260811-001"}
        assert captured["body"]["tools"][0]["function"]["name"] == "query_order"
        assert captured["body"]["tool_choice"] == "auto"

    async def test_agent_313_unparseable_returns_none(self) -> None:
        """LLM 未产生 tool_calls（如澄清回复）→ None（不调用真实服务）。"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "请提供订单号"}}]})

        client = OpenAIClient(
            "deepseek-v4-flash", "k", "https://api.deepseek.com", timeout=10,
            transport=httpx.MockTransport(handler),
        )
        parser = OpenAICompatToolParser(client)
        assert await parser.parse("query_order", "请问") is None

    async def test_agent_313_chatresult_and_malformed_args(self) -> None:
        """ChatResult（LLMRouter 路由）分支；参数 JSON 损坏 → None。"""

        class _StubResult:
            tool_calls = [{"function": {"arguments": "{bad json"}}]

        class _StubLLM:
            async def chat_tools(self, messages, tools, tool_choice="auto"):
                return _StubResult()

        assert await OpenAICompatToolParser(_StubLLM()).parse("query_order", "x") is None

        class _StubNone:
            tool_calls = None

        class _StubLLM2:
            async def chat_tools(self, messages, tools, tool_choice="auto"):
                return _StubNone()

        assert await OpenAICompatToolParser(_StubLLM2()).parse("query_order", "x") is None

        # 未知工具 → None
        assert await OpenAICompatToolParser(_StubLLM()).parse("magic_tool", "x") is None

    async def test_agent_313_fake_parser_records(self) -> None:
        from app.agents.tool_agent import FakeToolParser

        parser = FakeToolParser(args={"order_id": "ORD-1"})
        assert await parser.parse("query_order", "查订单") == {"order_id": "ORD-1"}
        assert parser.calls == [("query_order", "查订单")]
