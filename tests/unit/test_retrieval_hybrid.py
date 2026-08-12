"""SP-RET-005/007 混合检索入口（离线单元层，Fake ES + FakeEmbedding，零网络）。

- T-RET-507 查询粗分类规则（实体库 / 关键词密度 / 长度）
- T-RET-508 bm25_search 返回按分数降序且含必含字段
- T-RET-509 vector_search 走 embedding 客户端且按相似度降序
- T-RET-510 hybrid_search 默认 rrf 通路（ES 原生 RRF 行为对标）
- T-RET-511 hybrid_search dynamic 通路（加权 RRF + 权重随查询类型）
- T-RET-512 embedding 不可用 → 自动降级 bm25（strategy=bm25-fallback）
- T-RET-513 非法 strategy → ValueError
- T-RET-514 无结果 → docs=[]（空输入不报错）
"""
from __future__ import annotations

import pytest

from app.retrieval.hybrid_search import (
    bm25_search,
    classify_query,
    hybrid_search,
    vector_search,
)
from app.services.embedding import FakeEmbeddingClient


class FakeES:
    """内存 ES：按配置返回预先给定的命中（模拟 bm25/knn/rrf 三路）。"""

    def __init__(self, bm25_hits: list[dict] | None = None, vec_hits: list[dict] | None = None):
        self.bm25_hits = list(bm25_hits or [])
        self.vec_hits = list(vec_hits or [])

    def _hit(self, chunk_id: str, content: str, score: float) -> dict:
        return {
            "chunk_id": chunk_id,
            "doc_id": f"doc-{chunk_id}",
            "title": "手册",
            "heading_path": "甲 / 子",
            "content": content,
            "score": score,
        }

    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        return sorted(self.bm25_hits, key=lambda h: -h["score"])[:size]

    async def search_knn(self, q_vector: list[float], size: int = 10, num_candidates: int = 200) -> list[dict]:
        return sorted(self.vec_hits, key=lambda h: -h["score"])[:size]

    async def search_rrf(
        self, q: str, q_vector: list[float], size: int = 10, k: int = 60, num_candidates: int = 200
    ) -> list[dict]:
        # 融合：两路各取前 2 的并集，按 bm25 分 + 向量分粗略排序（测试只需非空/排序）
        ids = {h["chunk_id"] for h in self.bm25_hits[:2]} | {h["chunk_id"] for h in self.vec_hits[:2]}
        return [
            h for h in self.bm25_hits + self.vec_hits if h["chunk_id"] in ids
        ][:size]


def _bm25_hits() -> list[dict]:
    return [
        {"chunk_id": "c1", "doc_id": "d1", "title": "售后政策", "heading_path": "售后政策 / 退货规则",
         "content": "退货规则说明：未发货仅退款。", "score": 3.2},
        {"chunk_id": "c2", "doc_id": "d1", "title": "售后政策", "heading_path": "售后政策 / 退款流程",
         "content": "退款流程说明。", "score": 1.1},
    ]


@pytest.mark.spec("SP-RET-007")
class TestQueryClassifier:
    def test_ret_507_entity_hint(self) -> None:
        """实体库命中（订单/退款/退货/发票/物流…）→ 关键词权重。"""
        for q in ("我的订单怎么还没发货", "申请退货", "发票怎么开", "退款要多久"):
            r = classify_query(q)
            assert r["type"] in ("entity", "keyword")
            assert (r["w_bm25"], r["w_vec"]) == (1.5, 1.0)

    def test_ret_507_order_number_pattern(self) -> None:
        r = classify_query("ORD-20260811-001 查询")
        assert (r["w_bm25"], r["w_vec"]) == (1.5, 1.0)
        r2 = classify_query("订单号 88392014 状态")
        assert (r2["w_bm25"], r2["w_vec"]) == (1.5, 1.0)

    def test_ret_507_keyword_density(self) -> None:
        """短名词短语（高关键词密度）→ 关键词权重。"""
        r = classify_query("保温杯 保温时长")
        assert r["type"] == "keyword"
        assert (r["w_bm25"], r["w_vec"]) == (1.5, 1.0)

    def test_ret_507_semantic_query(self) -> None:
        """疑问/观点类查询 → 语义权重（向量更高）。"""
        for q in ("这个杯子好用吗", "怎么选择适合自己的杯子", "为什么推荐这款"):
            r = classify_query(q)
            assert r["type"] == "semantic"
            assert (r["w_bm25"], r["w_vec"]) == (1.0, 1.5)

    def test_ret_507_empty_query(self) -> None:
        r = classify_query("  ")
        assert r["type"] == "semantic"
        assert (r["w_bm25"], r["w_vec"]) == (1.0, 1.5)


@pytest.mark.spec("SP-RET-005")
class TestRetrievalEntry:
    async def test_ret_508_bm25_search_sorted(self) -> None:
        es = FakeES(bm25_hits=_bm25_hits())
        hits = await bm25_search("退货", es, top_k=10)

        assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
        assert hits[0]["chunk_id"] == "c1"
        for key in ("chunk_id", "title", "content", "score"):
            assert key in hits[0]

    async def test_ret_509_vector_search_uses_embedding(self) -> None:
        es = FakeES(vec_hits=[h | {"score": 0.9} for h in _bm25_hits()])
        embedding = FakeEmbeddingClient(dim=1024)
        hits = await vector_search("退货", es, embedding, top_k=10)

        assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
        assert embedding.calls and embedding.calls[0]["texts"] == ["退货"]

    async def test_ret_510_hybrid_rrf_default(self) -> None:
        es = FakeES(bm25_hits=_bm25_hits(), vec_hits=[h | {"score": 0.8} for h in _bm25_hits()])
        result = await hybrid_search("退货", es, embedding=FakeEmbeddingClient(dim=1024))

        assert result["strategy"] == "rrf"
        assert result["docs"], "结果非空"
        assert "elapsed_ms" in result and result["elapsed_ms"] >= 0
        assert "sources" in result["docs"][0]  # 含来源标记
        scores = [d["score"] for d in result["docs"]]
        assert scores == sorted(scores, reverse=True)

    async def test_ret_511_hybrid_dynamic_weights(self) -> None:
        es = FakeES(bm25_hits=_bm25_hits(), vec_hits=[h | {"score": 0.7} for h in _bm25_hits()])
        result = await hybrid_search("退货 政策", es, embedding=FakeEmbeddingClient(dim=1024), strategy="dynamic")

        assert result["strategy"] == "dynamic"
        assert result["weights"] == classify_query("退货 政策")
        assert result["docs"]
        assert result["docs"][0]["chunk_id"] == "c1"  # bm25 高权 → 关键词命中靠前
        assert set(result["docs"][0]["sources"]) <= {"bm25", "vector"}

    async def test_ret_512_embedding_failure_fallback(self) -> None:
        es = FakeES(bm25_hits=_bm25_hits())
        broken = FakeEmbeddingClient(dim=1024, fail_times=99)  # embedding 持续失败
        result = await hybrid_search("退货", es, embedding=broken)

        assert result["strategy"] == "bm25-fallback"  # 自动降级 bm25
        assert result["docs"] and result["docs"][0]["chunk_id"] == "c1"
        assert result["docs"][0]["sources"] == ["bm25"]

    async def test_ret_512_no_embedding_client(self) -> None:
        es = FakeES(bm25_hits=_bm25_hits())
        result = await hybrid_search("退货", es, embedding=None)
        assert result["strategy"] == "bm25-fallback"

    async def test_ret_513_invalid_strategy(self) -> None:
        es = FakeES(bm25_hits=_bm25_hits())
        with pytest.raises(ValueError, match="strategy"):
            await hybrid_search("退货", es, strategy="magic")

    async def test_ret_514_empty_results(self) -> None:
        es = FakeES()
        result = await hybrid_search("不存在", es, embedding=FakeEmbeddingClient(dim=1024))
        assert result["docs"] == []
        assert result["strategy"] == "rrf"
