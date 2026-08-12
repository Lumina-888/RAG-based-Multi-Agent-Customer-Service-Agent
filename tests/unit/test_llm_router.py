"""SP-CFG-004 统一 LLM 封装与模型路由：T-CFG-401 ~ 405。

- T-CFG-401 主模型正常：chat() 默认走 MODEL_MAIN（deepseek-v4-flash）
- T-CFG-402 主模型连续失败 2 次 → 自动降级 MODEL_FALLBACK（mimo-v2.5）
- T-CFG-403 主备均失败 → 错误码 5001
- T-CFG-404 vision 路由固定 MODEL_VISION（mimo-v2.5）
- T-CFG-405 FakeLLM 注入生效（CI 单测不依赖真实 API）
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.llm import FakeLLM, LLMRouter, LLMUnavailableError


def _settings() -> Settings:
    return Settings(_env_file=None, deepseek_api_key="deepseek-test", mimo_api_key="mimo-test")


@pytest.mark.spec("SP-CFG-004")
class TestLLMRouter:
    async def test_cfg_401_main_model_normal(self) -> None:
        main = FakeLLM("deepseek-v4-flash", replies=["你好，请问有什么可以帮您？"])
        fallback = FakeLLM("mimo-v2.5")
        vision = FakeLLM("mimo-v2.5")
        router = LLMRouter(_settings(), main, fallback, vision, backoff=0)

        result = await router.chat([{"role": "user", "content": "hi"}])

        assert result.content == "你好，请问有什么可以帮您？"
        assert result.model == "deepseek-v4-flash"  # 默认走主模型
        assert result.fallback_used is False
        assert len(main.calls) == 1
        assert fallback.calls == []  # 备模型未被调用

    async def test_cfg_402_fallback_after_two_main_failures(self) -> None:
        """主模型连续失败 2 次后自动降级备模型。"""
        main = FakeLLM("deepseek-v4-flash", fail_times=2)
        fallback = FakeLLM("mimo-v2.5", replies=["备模型兜底回复"])
        vision = FakeLLM("mimo-v2.5")
        router = LLMRouter(_settings(), main, fallback, vision, backoff=0)

        result = await router.chat([{"role": "user", "content": "hi"}])

        assert result.content == "备模型兜底回复"
        assert result.model == "mimo-v2.5"
        assert result.fallback_used is True
        assert len(main.calls) == 2  # 主模型重试 2 次后放弃
        assert len(fallback.calls) == 1

    async def test_cfg_403_both_fail_raises_5001(self) -> None:
        main = FakeLLM("deepseek-v4-flash", fail_times=99)
        fallback = FakeLLM("mimo-v2.5", fail_times=99)
        vision = FakeLLM("mimo-v2.5")
        router = LLMRouter(_settings(), main, fallback, vision, backoff=0)

        with pytest.raises(LLMUnavailableError) as exc:
            await router.chat([{"role": "user", "content": "hi"}])
        assert exc.value.code == 5001

    async def test_cfg_404_vision_routes_to_vision_model(self) -> None:
        main = FakeLLM("deepseek-v4-flash")
        fallback = FakeLLM("mimo-v2.5")
        vision = FakeLLM("mimo-v2.5", replies=["图中是一张发票，金额 299 元"])
        router = LLMRouter(_settings(), main, fallback, vision, backoff=0)

        result = await router.vision("https://example.com/img/1.png", "请描述这张图片")

        assert result.content == "图中是一张发票，金额 299 元"
        assert result.model == "mimo-v2.5"  # vision 固定走 MODEL_VISION
        assert vision.calls and vision.calls[0]["method"] == "vision"
        assert vision.calls[0]["image_url"] == "https://example.com/img/1.png"

    async def test_cfg_405_fake_llm_injection(self) -> None:
        """FakeLLM 注入生效：全程零真实网络请求，调用历史可断言。"""
        main = FakeLLM("deepseek-v4-flash", replies=["ok"])
        fallback = FakeLLM("mimo-v2.5")
        vision = FakeLLM("mimo-v2.5")
        router = LLMRouter(_settings(), main, fallback, vision, backoff=0)

        result = await router.chat([{"role": "user", "content": "ping"}])

        assert result.content == "ok"
        assert main.calls[0]["messages"][0]["content"] == "ping"
        assert main.calls[0]["model"] == "deepseek-v4-flash"
