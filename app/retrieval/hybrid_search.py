"""SP-RET-001/002/005/007 检索路径与混合检索入口（app/retrieval）。

- `bm25_search(q, es, top_k)`：BM25 检索（标题权重为内容 2 倍，SP-RET-001）
- `vector_search(q, es, embedding, top_k)`：向量检索（bge-m3 dim=1024，SP-RET-002）
- `hybrid_search(q, es, embedding, strategy, top_k)`：
  - `rrf`（默认，SP-RET-005）：ES 原生 `rank:{rrf:{}}` 静态融合（需 ES ≥ 8.8），
    与 `fusion.rrf_fuse` 行为对标
  - `dynamic`（SP-RET-007）：查询粗分类 → 加权 RRF（自研纯函数，ES 原生不支持按路加权）
  - embedding 不可用 → 自动降级纯 BM25（strategy=`bm25-fallback`）
- `classify_query(q)`：查询粗分类（实体库 / 关键词密度 / 长度规则；fastText 兜底
  待 M3 意图模型集成）
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.retrieval.fusion import weighted_rrf_fuse
from app.services.embedding import EmbeddingClient

logger = logging.getLogger("app.retrieval.hybrid_search")

#: SP-RET-007 实体库提示词（命中 → 实体/关键词查询，w_bm25=1.5）
_ENTITY_HINTS = (
    "订单", "退款", "退货", "换货", "发票", "物流", "快递", "发货", "收货", "签收",
    "金额", "价格", "优惠", "券", "保修", "质保", "库存", "规格", "参数", "型号",
    "颜色", "尺寸", "地址", "电话", "商品", "产品", "售后", "运费",
)
#: 疑问/观点标记（命中 → 语义查询，w_vec=1.5）
_INTERROGATIVE_HINTS = ("怎么", "如何", "为什么", "什么", "吗", "呢", "怎么样")
#: 订单号 / 长数字串（订单查询形态）
_ORDER_NO_RE = re.compile(r"\b(?:ORD|NO)[-_]?\d{4,}\b|\b\d{8,}\b")

_KEYWORD_DENSITY_THRESHOLD = 0.6
_KEYWORD_MAX_LEN = 8

_WEIGHTS_KEYWORD = {"w_bm25": 1.5, "w_vec": 1.0}
_WEIGHTS_SEMANTIC = {"w_bm25": 1.0, "w_vec": 1.5}


def classify_query(q: str) -> dict:
    """查询粗分类（SP-RET-007 规则，确定性可测）：

    实体库命中 / 订单号形态 / 短名词短语（高关键词密度）→ 关键词权重 (1.5, 1.0)；
    疑问/观点查询 → 语义权重 (1.0, 1.5)。空查询兜底语义。
    """
    q = q.strip()
    if not q:
        return {"type": "semantic", **_WEIGHTS_SEMANTIC}
    if any(hint in q for hint in _ENTITY_HINTS):
        return {"type": "entity", **_WEIGHTS_KEYWORD}
    if _ORDER_NO_RE.search(q):
        return {"type": "entity", **_WEIGHTS_KEYWORD}
    if any(marker in q for marker in _INTERROGATIVE_HINTS):
        return {"type": "semantic", **_WEIGHTS_SEMANTIC}
    non_stop = [c for c in q if c not in "的了吗呢怎么如何为什么什么可以请问一下"]
    density = len(non_stop) / max(len(q), 1)
    if density >= _KEYWORD_DENSITY_THRESHOLD and len(q) <= _KEYWORD_MAX_LEN:
        return {"type": "keyword", **_WEIGHTS_KEYWORD}
    return {"type": "semantic", **_WEIGHTS_SEMANTIC}


async def bm25_search(q: str, es: Any, top_k: int = 10) -> list[dict]:
    """BM25 检索（标题字段权重为内容 2 倍），按相关度降序。"""
    return await es.search_match(q, size=top_k)


async def vector_search(
    q: str, es: Any, embedding: EmbeddingClient, top_k: int = 10
) -> list[dict]:
    """向量检索（bge-m3，dim 与 embedding 客户端一致），按相似度降序。"""
    vector = (await embedding.embed([q]))[0]
    return await es.search_knn(vector, size=top_k)


def _with_sources(hits: list[dict], sources: list[str]) -> list[dict]:
    return [{**h, "sources": list(sources)} for h in hits]


async def hybrid_search(
    q: str,
    es: Any,
    embedding: EmbeddingClient | None = None,
    strategy: str = "rrf",
    top_k: int = 10,
    weights: dict | None = None,
) -> dict:
    """混合检索入口 → `{docs, strategy, weights, elapsed_ms}`。

    - docs 每条含 `chunk_id/title/content/heading_path/score/sources`，按分数降序
    - 默认 `rrf`（ES 原生）；`dynamic` 走自研加权融合；embedding 缺失/失败降级 BM25
    """
    if strategy not in ("rrf", "dynamic"):
        raise ValueError(f"不支持的 strategy: {strategy}（可选 rrf / dynamic）")
    started = time.monotonic()
    docs: list[dict] = []
    result_strategy = strategy
    used_weights: dict | None = None

    async def _fallback_bm25() -> list[dict]:
        nonlocal result_strategy
        result_strategy = "bm25-fallback"
        return _with_sources(await es.search_match(q, size=top_k), ["bm25"])

    if strategy == "rrf":
        try:
            vector = (await embedding.embed([q]))[0]
            hits = await es.search_rrf(q, vector, size=top_k)
            docs = _with_sources(hits, ["bm25", "vector"])
        except Exception as exc:  # noqa: BLE001 - embedding/ES 任一不可用即降级
            logger.warning("RRF 融合不可用，降级 BM25: %s", exc)
            docs = await _fallback_bm25()
    else:  # dynamic：两路检索 → 查询粗分类 → 加权 RRF
        try:
            bm25_hits = await bm25_search(q, es, top_k)
            vec_hits = await vector_search(q, es, embedding, top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dynamic 检索不可用，降级 BM25: %s", exc)
            docs = await _fallback_bm25()
        else:
            used_weights = dict(weights) if weights else classify_query(q)
            fused = weighted_rrf_fuse(
                [(h["chunk_id"], i + 1) for i, h in enumerate(bm25_hits)],
                [(h["chunk_id"], i + 1) for i, h in enumerate(vec_hits)],
                k=60,
                w_bm25=used_weights["w_bm25"],
                w_vec=used_weights["w_vec"],
            )
            bm25_ids = {h["chunk_id"] for h in bm25_hits}
            vec_ids = {h["chunk_id"] for h in vec_hits}
            by_id = {h["chunk_id"]: h for h in bm25_hits + vec_hits}
            for chunk_id, score in fused:
                sources = [s for s, ids in (("bm25", bm25_ids), ("vector", vec_ids)) if chunk_id in ids]
                docs.append({**by_id[chunk_id], "score": score, "sources": sources})

    return {
        "docs": docs,
        "strategy": result_strategy,
        "weights": used_weights,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
    }
