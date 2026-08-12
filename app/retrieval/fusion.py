"""SP-RET-003 RRF 融合（纯函数核心）+ SP-RET-007 加权 RRF。

- `rrf_fuse(bm25_results, vector_results, k=60)`：
  score = Σ 1/(k+rank)，按降序返回 `[(id, score)]`；只出现在一路的文档正常参与；
  空列表输入返回空；相同 id 只出现一次（同路重复取最优 rank）
- `weighted_rrf_fuse(..., w_bm25, w_vec)`：按路加权（ES 原生 RRF 不支持按路加权，
  动态权重必须走本函数，SP-RET-007）
- 输入为 `[(id, rank)]`（rank 从 1 起）；ES 原生 `rank:{rrf:{}}` 行为与本函数对标
"""
from __future__ import annotations

from collections import defaultdict
from typing import Hashable


def _best_rank(path: list[tuple[Hashable, int]]) -> dict[Hashable, int]:
    """同路归一化：相同 id 只保留最优（最小）rank。"""
    best: dict[Hashable, int] = {}
    for doc_id, rank in path:
        if doc_id not in best or rank < best[doc_id]:
            best[doc_id] = rank
    return best


def rrf_fuse(
    bm25_results: list[tuple[Hashable, int]],
    vector_results: list[tuple[Hashable, int]],
    k: int = 60,
) -> list[tuple[Hashable, float]]:
    """RRF 融合：`Σ 1/(k+rank)` 降序，去重，空输入返回空。"""
    return weighted_rrf_fuse(bm25_results, vector_results, k=k, w_bm25=1.0, w_vec=1.0)


def weighted_rrf_fuse(
    bm25_results: list[tuple[Hashable, int]],
    vector_results: list[tuple[Hashable, int]],
    k: int = 60,
    w_bm25: float = 1.0,
    w_vec: float = 1.0,
) -> list[tuple[Hashable, float]]:
    """加权 RRF（SP-RET-007）：score = w_bm25·Σ1/(k+r_b) + w_vec·Σ1/(k+r_v)。"""
    scores: dict[Hashable, float] = defaultdict(float)
    for doc_id, rank in _best_rank(bm25_results).items():
        scores[doc_id] += w_bm25 / (k + rank)
    for doc_id, rank in _best_rank(vector_results).items():
        scores[doc_id] += w_vec / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])
