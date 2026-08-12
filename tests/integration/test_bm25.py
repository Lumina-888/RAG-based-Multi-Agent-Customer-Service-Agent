"""SP-RET-001 BM25 检索（需 ES）：T-RET-101。

- T-RET-101 关键词精确命中排前：命中"退货"的块排第一，按相关度降序
"""
from __future__ import annotations

import pytest

from app.retrieval.hybrid_search import bm25_search
from app.services.es import ESClient


@pytest.mark.spec("SP-RET-001")
@pytest.mark.integration
class TestBM25Search:
    async def test_ret_101_exact_keyword_first(self, kb: ESClient) -> None:
        hits = await bm25_search("退货", kb, top_k=10)

        assert hits, "检索结果非空"
        assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
        assert "退货" in hits[0]["content"] or "退货" in hits[0]["title"]  # 精确命中排前
        for key in ("chunk_id", "title", "content", "score"):
            assert key in hits[0]

    async def test_ret_101_top_k_limit(self, kb: ESClient) -> None:
        hits = await bm25_search("商品", kb, top_k=2)
        assert len(hits) <= 2
