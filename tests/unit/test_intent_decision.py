"""SP-INT-003 置信度分级决策：T-INT-301 ~ 304。

- T-INT-301 conf ≥ 0.85 → 直路由（不依赖 LLM，零调用）
- T-INT-302 0.6 ≤ conf < 0.85 → LLM 二次确认（主模型）；LLM 不可用/解析失败 → clarify
- T-INT-303 conf < 0.6 → LLM 兜底分类（主→备降级由 SP-CFG-004 路由负责）；
  解析失败 → clarify
- T-INT-304 主备均不可用（5001）→ 统一降级 clarify
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.intent.decision import Decision, decide, parse_llm_intent
from app.services.llm import FakeLLM, LLMRouter


def _settings() -> Settings:
    return Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m")


def _router(
    replies: list[str] | None = None, main_fail: int = 0, fallback_fail: int = 0
) -> LLMRouter:
    return LLMRouter(
        _settings(),
        FakeLLM("deepseek-v4-flash", replies=replies, fail_times=main_fail),
        FakeLLM("mimo-v2.5", fail_times=fallback_fail),
        FakeLLM("mimo-v2.5"),
        backoff=0,
    )


@pytest.mark.spec("SP-INT-003")
class TestDecision:
    async def test_int_301_high_conf_routes_directly(self) -> None:
        router = _router(replies=["refund"])  # 即使 LLM 有回复也不该被调用
        decision = await decide("refund", 0.92, llm=router, text="我想退款")

        assert decision.action == "route"
        assert decision.intent == "refund"
        assert decision.conf == 0.92
        assert router._main.calls == []  # 高置信不依赖 LLM

    async def test_int_302_mid_conf_llm_confirm(self) -> None:
        router = _router(replies=["refund"])
        decision = await decide("after_sales", 0.7, llm=router, text="我想退款")

        assert decision.action == "route"
        assert decision.intent == "refund"  # 以 LLM 二次确认结果为准
        assert len(router._main.calls) == 1  # 主模型确认一次
        assert "after_sales" in router._main.calls[0]["messages"][-1]["content"]
        assert "我想退款" in router._main.calls[0]["messages"][-1]["content"]  # 原文透传

    async def test_int_302_mid_conf_llm_unparseable_clarify(self) -> None:
        router = _router(replies=["随便聊聊"])
        decision = await decide("after_sales", 0.7, llm=router, text="嗨")
        assert decision.action == "clarify"
        assert decision.intent is None

    async def test_int_302_mid_conf_llm_unavailable_clarify(self) -> None:
        router = _router(main_fail=2, fallback_fail=99)  # 主重试 2 次失败 → 备也失败 → 5001
        decision = await decide("after_sales", 0.7, llm=router, text="嗨")
        assert decision.action == "clarify"

    async def test_int_303_low_conf_llm_fallback(self) -> None:
        router = _router(replies=["complaint"])
        decision = await decide("human", 0.3, llm=router, text="我要投诉")

        assert decision.action == "route"
        assert decision.intent == "complaint"  # 以 LLM 兜底分类为准
        assert router._main.calls and len(router._main.calls) >= 1

    async def test_int_303_low_conf_unparseable_clarify(self) -> None:
        router = _router(replies=["不知道"])
        decision = await decide("human", 0.3, llm=router, text="随便")
        assert decision.action == "clarify"

    async def test_int_304_both_unavailable_clarify(self) -> None:
        """主备均不可用（5001）→ 中/低置信统一降级 clarify。"""
        router = _router(main_fail=99, fallback_fail=99)
        assert (await decide("refund", 0.7, llm=router)).action == "clarify"
        assert (await decide("refund", 0.4, llm=router)).action == "clarify"

    async def test_int_304_no_llm_clarify(self) -> None:
        """llm 未注入（如主备均不可用的部署态）→ 需要 LLM 的档位降级 clarify。"""
        assert (await decide("refund", 0.7, llm=None)).action == "clarify"
        assert (await decide("refund", 0.4, llm=None)).action == "clarify"
        assert (await decide("refund", 0.9, llm=None)).action == "route"  # 高置信仍可路由

    def test_parse_llm_intent(self) -> None:
        assert parse_llm_intent("refund") == "refund"
        assert parse_llm_intent("意图是 refund，建议退款") == "refund"
        assert parse_llm_intent("PRE_SALES") == "pre_sales"  # 大小写不敏感
        assert parse_llm_intent("order_query") == "order_query"
        assert parse_llm_intent("没有明确意图") is None
        assert parse_llm_intent("") is None
        assert parse_llm_intent(None) is None  # type: ignore[arg-type]

    async def test_decision_dataclass(self) -> None:
        d = Decision(action="route", intent="refund", conf=0.9)
        assert d.as_dict() == {"action": "route", "intent": "refund", "conf": 0.9}
