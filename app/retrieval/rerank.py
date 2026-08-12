"""SP-RET-004 重排：硅基流动 bge-reranker-v2-m3 云端 API（P1）。

- `rerank(q, docs, top_k=5)`：top-20 候选 → top-5，按相关度降序，与问答 Agent
  输入顺序一致；无效输入（空查询/空候选/top_k≤0）抛 ValueError
- `SiliconFlowRerankClient`：OpenAI 兼容 `/rerank` 接口，支持 MockTransport 注入，
  单测零真实网络
- 性能不达标不作为验收阻塞（SP-RET-006 豁免口径）
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.retrieval.rerank")


class RerankUnavailableError(Exception):
    """重排服务不可用（未配置 RERANKER_API_KEY / 调用失败）。"""


class RerankClient(Protocol):
    """重排客户端协议：Fake 与真实 API 客户端实现同一接口。"""

    model: str

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[dict]: ...


class SiliconFlowRerankClient:
    """硅基流动 bge-reranker-v2-m3：`POST {base}/rerank`。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[dict]:
        resp = await self._http.post(
            "/rerank",
            json={"model": self.model, "query": query, "documents": documents, "top_n": top_n},
        )
        resp.raise_for_status()
        results = resp.json()["results"]  # [{"index": int, "relevance_score": float}]
        return sorted(results, key=lambda r: -r["relevance_score"])

    async def aclose(self) -> None:
        await self._http.aclose()


def build_reranker(config: Settings) -> SiliconFlowRerankClient:
    """按配置构建；缺 `RERANKER_API_KEY` 启动即失败（fail fast）。"""
    if not config.reranker_api_key:
        raise RerankUnavailableError("未配置 RERANKER_API_KEY，无法调用重排服务（见 .env.example）")
    return SiliconFlowRerankClient(
        model=config.reranker_model,
        api_key=config.reranker_api_key,
        base_url=config.reranker_base_url,
        timeout=config.llm_timeout,
    )


async def rerank(
    query: str, docs: list[dict], top_k: int = 5, client: RerankClient | None = None
) -> list[dict]:
    """重排入口：候选 docs（含 content）→ 按相关度降序返回 top_k。"""
    if not query or not query.strip():
        raise ValueError("查询不能为空")
    if not docs:
        raise ValueError("候选文档不能为空")
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    if client is None:
        client = build_reranker(get_settings())
    ranked = await client.rerank(query, [d["content"] for d in docs], top_n=top_k)
    ordered: list[dict] = []
    for item in ranked:  # 按相关度降序重排，与问答 Agent 输入顺序一致
        idx = item["index"]
        if 0 <= idx < len(docs):
            ordered.append(docs[idx])
    logger.info("rerank 完成 query=%r top_k=%d 候选=%d", query, top_k, len(docs))
    return ordered[:top_k]
