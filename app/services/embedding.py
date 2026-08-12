"""统一 Embedding 封装（硅基流动 bge-m3 云端 API，SP-ING-003 / SP-RET-002 前置）。

- OpenAI 兼容接口：`POST {base_url}/embeddings`，模型 bge-m3，dim=1024
- 返回维度与配置不一致 → `EmbeddingError`（防静默错配，对齐"维度与模型一致"）
- 支持 FakeEmbedding 注入，CI 单测不依赖真实 API（同 SP-CFG-004 模式）
- 错误码约定：`code=5002`（检索链路不可用，SP-API-GEN），M2 检索模块统一映射
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger("app.services.embedding")


class EmbeddingError(Exception):
    """Embedding 服务不可用 / 返回异常（统一错误码 5002 前置）。"""

    code = 5002


class EmbeddingClient(Protocol):
    """Embedding 客户端协议：Fake 与真实 API 客户端实现同一接口。"""

    model: str
    dim: int

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]: ...


class OpenAIEmbeddingClient:
    """OpenAI 兼容的 /embeddings 客户端（硅基流动等平台通用）。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        dim: int,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dim = dim
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,  # 测试可注入 MockTransport
        )

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        resp = await self._http.post(
            "/embeddings", json={"model": self.model, "input": texts, **kwargs}
        )
        resp.raise_for_status()
        # OpenAI 兼容约定：data 按 index 对应 input 顺序，显式排序防乱序
        items = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
        vectors = [item["embedding"] for item in items]
        self._check_dim(vectors)
        return vectors

    def _check_dim(self, vectors: list[list[float]]) -> None:
        for v in vectors:
            if len(v) != self.dim:
                raise EmbeddingError(
                    f"向量维度 {len(v)} 与配置 {self.dim} 不一致（模型 {self.model}）"
                )

    async def aclose(self) -> None:
        await self._http.aclose()


class FakeEmbeddingClient:
    """测试注入的假客户端：可配置失败次数，记录调用历史。

    生成确定性伪向量（文本内容 + 维度索引 → 0~1 浮点），便于断言与复现。
    """

    def __init__(self, model: str = "bge-m3", dim: int = 1024, fail_times: int = 0) -> None:
        self.model = model
        self.dim = dim
        self.fail_times = fail_times
        self.calls: list[dict[str, Any]] = []

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append({"texts": list(texts), "kwargs": kwargs})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise EmbeddingError(f"fake {self.model} unavailable")
        return [
            [float((sum(ord(c) for c in text) + i) % 1000) / 1000.0 for i in range(self.dim)]
            for text in texts
        ]


def build_embedding_client(config: Settings) -> EmbeddingClient:
    """按配置构建真实 embedding 客户端（硅基流动 bge-m3）。"""
    return OpenAIEmbeddingClient(
        model=config.embedding_model,
        api_key=config.embedding_api_key,
        base_url=config.embedding_base_url,
        dim=config.embedding_dim,
        timeout=config.llm_timeout,
    )
