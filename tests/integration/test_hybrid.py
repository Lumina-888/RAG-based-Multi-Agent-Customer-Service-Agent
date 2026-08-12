"""SP-RET-005/007 混合检索入口（需 ES）：T-RET-501/502/503。

- T-RET-501 默认 RRF 通路（ES 原生 rank:{rrf:{}}）执行成功
- T-RET-502 结果非空且含来源标记（chunk_id/title/content/score/sources）
- T-RET-503 dynamic 通路：关键词查询走加权 RRF（机制冒烟；严格消融对比在 M7 E1~E5）
"""
from __future__ import annotations

import pytest

from app.retrieval.hybrid_search import classify_query, hybrid_search
from app.services.embedding import FakeEmbeddingClient
from app.services.es import ESClient


@pytest.mark.spec("SP-RET-005")
@pytest.mark.integration
class TestHybridSearch:
    async def test_ret_501_default_rrf(self, kb: ESClient) -> None:
        result = await hybrid_search("退货", kb, embedding=FakeEmbeddingClient(dim=1024))

        assert result["strategy"] == "rrf"  # 默认静态 RRF（ES 原生）
        assert result["docs"], "结果非空"
        assert "elapsed_ms" in result and result["elapsed_ms"] >= 0

    async def test_ret_502_results_with_source(self, kb: ESClient) -> None:
        result = await hybrid_search("退款", kb, embedding=FakeEmbeddingClient(dim=1024))

        assert result["docs"]
        first = result["docs"][0]
        for key in ("chunk_id", "title", "content", "score", "sources"):
            assert key in first  # 含来源标记（T-RET-502）
        scores = [d["score"] for d in result["docs"]]
        assert scores == sorted(scores, reverse=True)  # 按融合分数降序

    async def test_ret_503_dynamic_keyword_weights(self, kb: ESClient) -> None:
        q = "退货 政策"
        assert classify_query(q)["w_bm25"] == 1.5  # 关键词查询 → bm25 加权

        result = await hybrid_search(q, kb, embedding=FakeEmbeddingClient(dim=1024), strategy="dynamic")

        assert result["strategy"] == "dynamic"
        assert result["weights"] == classify_query(q)  # 权重随查询类型
        assert result["docs"]
        assert "退货" in result["docs"][0]["content"] or "退货" in result["docs"][0]["title"]
