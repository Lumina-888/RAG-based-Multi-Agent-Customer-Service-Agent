"""统一 LLM 封装与模型路由（SP-CFG-004）。

- `chat()`：默认主模型（MODEL_MAIN=deepseek-v4-flash）；连续失败达 `llm_max_retries`
  次（指数退避重试）后自动降级备模型（MODEL_FALLBACK=mimo-v2.5）；主备均失败
  → `LLMUnavailableError`（统一错误码 5001）
- `vision()`：固定走 MODEL_VISION（mimo-v2.5），不挤占文本主路径
- 全部调用支持 FakeLLM 注入，CI / 单测不依赖真实 API
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger("app.services.llm")


class LLMUnavailableError(Exception):
    """LLM 服务不可用（对应统一错误码 5001，SP-API-GEN）。"""

    code = 5001


class LLMClient(Protocol):
    """LLM 客户端协议：FakeLLM 与真实 API 客户端实现同一接口。"""

    model: str

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str: ...

    async def vision(self, image_url: str, prompt: str, **kwargs: Any) -> str: ...


@dataclass
class ChatResult:
    """统一调用结果：内容 + 实际使用的模型 + 是否发生降级。"""

    content: str
    model: str
    fallback_used: bool = False


class OpenAIClient:
    """OpenAI 兼容协议的云端 API 客户端（DeepSeek / mimo 均兼容）。"""

    def __init__(self, model: str, api_key: str, base_url: str, timeout: float = 30.0):
        self.model = model
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        resp = await self._http.post(
            "/chat/completions", json={"model": self.model, "messages": messages, **kwargs}
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def vision(self, image_url: str, prompt: str, **kwargs: Any) -> str:
        resp = await self._http.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
                **kwargs,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def aclose(self) -> None:
        await self._http.aclose()


class FakeLLM:
    """测试注入的假客户端：可配置回复内容 / 连续失败次数，并记录调用历史。"""

    def __init__(
        self,
        model: str,
        replies: list[str] | None = None,
        fail_times: int = 0,
    ) -> None:
        self.model = model
        self.replies: list[str] = list(replies or [])
        self.fail_times = fail_times
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        self.calls.append(
            {"method": "chat", "model": self.model, "messages": messages, "kwargs": kwargs}
        )
        return self._respond()

    async def vision(self, image_url: str, prompt: str, **kwargs: Any) -> str:
        self.calls.append(
            {
                "method": "vision",
                "model": self.model,
                "image_url": image_url,
                "prompt": prompt,
                "kwargs": kwargs,
            }
        )
        return self._respond()

    def _respond(self) -> str:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMUnavailableError(f"fake {self.model} unavailable")
        return self.replies.pop(0) if self.replies else f"[{self.model} reply]"


class LLMRouter:
    """模型路由：主模型 → 指数退避重试 → 备模型 → 主备均失败抛 5001。"""

    def __init__(
        self,
        config: Settings,
        main_client: LLMClient,
        fallback_client: LLMClient,
        vision_client: LLMClient,
        backoff: float = 0.1,
    ) -> None:
        self._config = config
        self._main = main_client
        self._fallback = fallback_client
        self._vision = vision_client
        self._backoff = backoff  # 指数退避基数（秒）；测试可置 0 加速

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        last_err: Exception | None = None
        for attempt in range(self._config.llm_max_retries):
            try:
                content = await self._main.chat(messages, **kwargs)
                return ChatResult(content=content, model=self._main.model)
            except Exception as exc:  # noqa: BLE001 - 统一降级，不区分具体错误类型
                last_err = exc
                logger.warning(
                    "主模型调用失败(第 %s/%s 次): %s",
                    attempt + 1,
                    self._config.llm_max_retries,
                    exc,
                )
                if attempt + 1 < self._config.llm_max_retries:
                    await asyncio.sleep(self._backoff * (2**attempt))
        # 主模型连续失败 → 自动降级备模型
        try:
            content = await self._fallback.chat(messages, **kwargs)
            logger.info("主模型不可用，已降级备模型 %s", self._fallback.model)
            return ChatResult(content=content, model=self._fallback.model, fallback_used=True)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        raise LLMUnavailableError(f"主备模型均不可用: {last_err}") from last_err

    async def vision(self, image_url: str, prompt: str, **kwargs: Any) -> ChatResult:
        try:
            content = await self._vision.vision(image_url, prompt, **kwargs)
            return ChatResult(content=content, model=self._vision.model)
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailableError(f"视觉模型不可用: {exc}") from exc


def build_llm(config: Settings) -> LLMRouter:
    """按配置构建真实客户端路由：DeepSeek 主 / mimo 备 + 视觉。"""
    main = OpenAIClient(
        config.model_main, config.deepseek_api_key, config.deepseek_base_url, config.llm_timeout
    )
    fallback = OpenAIClient(
        config.model_fallback, config.mimo_api_key, config.mimo_base_url, config.llm_timeout
    )
    vision = OpenAIClient(
        config.model_vision, config.mimo_api_key, config.mimo_base_url, config.llm_timeout
    )
    return LLMRouter(config, main, fallback, vision)
