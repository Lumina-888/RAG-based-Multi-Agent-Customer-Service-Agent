"""SP-EVAL-003 消融实验跑批：一键跑 E1~E5，输出对比表（可被前端看板渲染）。

策略（顺序稳定，SP-EVAL-003）：
- E1 `bm25`：仅 BM25（SP-RET-001）
- E2 `vector`：仅向量（SP-RET-002）
- E3 `rrf`：RRF 静态融合（SP-RET-005）
- E4 `rrf_rerank`：RRF + 重排（SP-RET-004）；无 `RERANKER_API_KEY` →
  该行标记 `skipped=true` 且指标为 None，**不阻塞**其余策略
- E5 `dynamic`：动态权重（SP-RET-007）

- `run_ablation(es, embedding, cases, rerank_client=None, top_k=5, candidate_k=20)`：
  基于 retrieval 用例（path 或 `list[RetrievalCase]`）对 5 种策略分别计算
  Recall@5 / MRR / NDCG@5（按用例平均；gold 为 doc 级 id，与检索结果 `doc_id` 对齐）
- `repo` 提供时把整表写入 eval_runs（run_type="ablation"），供 `GET /api/v1/eval/runs`
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from app.eval.case_loader import RetrievalCase, load_retrieval_cases
from app.eval.metrics import mrr, ndcg_at_k, recall_at_k
from app.retrieval.hybrid_search import bm25_search, hybrid_search, vector_search
from app.retrieval.rerank import RerankClient, RerankUnavailableError, rerank

logger = logging.getLogger("app.eval.ablation")

#: 消融策略顺序（E1~E5，稳定输出）
STRATEGIES = ("bm25", "vector", "rrf", "rrf_rerank", "dynamic")


class ESWriter(Protocol):
    async def search_match(self, q: str, size: int = 10) -> list[dict]: ...

    async def search_knn(self, q_vector: list[float], size: int = 10) -> list[dict]: ...

    async def search_rrf(self, q: str, q_vector: list[float], size: int = 10) -> list[dict]: ...


class EmbeddingClient(Protocol):
    model: str
    dim: int

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]: ...


async def _retrieve(
    strategy: str,
    q: str,
    es: ESWriter,
    embedding: EmbeddingClient,
    top_k: int,
    candidate_k: int,
    rerank_client: RerankClient | None,
) -> list[dict]:
    """按策略检索 top_k 候选（rrf_rerank 先取 candidate_k 再重排）。"""
    if strategy == "bm25":
        return await bm25_search(q, es, top_k=top_k)
    if strategy == "vector":
        return await vector_search(q, es, embedding, top_k=top_k)
    if strategy == "rrf":
        return (await hybrid_search(q, es, embedding, strategy="rrf", top_k=top_k))["docs"]
    if strategy == "rrf_rerank":
        docs = (await hybrid_search(q, es, embedding, strategy="rrf", top_k=candidate_k))["docs"]
        if not docs:
            return []
        return await rerank(q, docs, top_k=top_k, client=rerank_client)
    if strategy == "dynamic":
        return (await hybrid_search(q, es, embedding, strategy="dynamic", top_k=top_k))["docs"]
    raise ValueError(f"未知消融策略: {strategy}")


def _empty_row(strategy: str, cases: int, skipped: bool) -> dict:
    return {
        "strategy": strategy,
        "recall@5": None,
        "mrr": None,
        "ndcg@5": None,
        "cases": cases,
        "skipped": skipped,
    }


async def run_ablation(
    es: ESWriter,
    embedding: EmbeddingClient,
    cases: str | Path | list[RetrievalCase],
    rerank_client: RerankClient | None = None,
    top_k: int = 5,
    candidate_k: int = 20,
    repo=None,
) -> list[dict]:
    """消融跑批：返回 `[{strategy, recall@5, mrr, ndcg@5, cases, skipped}]`。"""
    case_list = cases if isinstance(cases, list) else load_retrieval_cases(cases)[0]
    rows: list[dict] = []
    for strategy in STRATEGIES:
        recall_sum = mrr_sum = ndcg_sum = 0.0
        skipped = False
        for case in case_list:
            try:
                docs = await _retrieve(
                    strategy, case.query, es, embedding, top_k, candidate_k, rerank_client
                )
            except (RerankUnavailableError, ValueError) as exc:
                if strategy == "rrf_rerank" and isinstance(exc, RerankUnavailableError):
                    skipped = True  # 无 key 不阻塞其余策略
                    logger.warning("rrf_rerank 跳过（重排服务不可用）: %s", exc)
                    break
                raise
            retrieved = [d.get("doc_id") or d["chunk_id"].rsplit("-", 1)[0] for d in docs]
            relevant = case.gold_docs
            recall_sum += recall_at_k(relevant, retrieved, k=top_k)
            mrr_sum += mrr(relevant, retrieved)
            ndcg_sum += ndcg_at_k(relevant, retrieved, k=top_k)
        n = len(case_list)
        if skipped:
            rows.append(_empty_row(strategy, n, skipped=True))
            continue
        rows.append(
            {
                "strategy": strategy,
                "recall@5": round(recall_sum / n, 4),
                "mrr": round(mrr_sum / n, 4),
                "ndcg@5": round(ndcg_sum / n, 4),
                "cases": n,
                "skipped": False,
            }
        )
    if repo is not None:
        await repo.record_run(
            run_type="ablation", name="ablation",
            metrics={"strategies": rows, "cases": len(case_list), "top_k": top_k},
        )
    logger.info("消融跑批完成 策略=%d 用例=%d", len(rows), len(case_list))
    return rows
