"""SP-EVAL-003 消融跑批（离线，FakeES/FakeEmbedding 注入，零外部服务）。

- T-EVAL-302：E1~E5 五组策略均可执行，输出结构稳定、指标数值正确
  （手工样本：bm25 行 recall@5=1.0, mrr=0.75, ndcg@5≈0.8155）
- T-EVAL-303：重排服务不可用（RerankUnavailableError）→ rrf_rerank 行
  `skipped=true` 且指标为 None，**不阻塞**其余策略
- T-EVAL-304：注入 FakeReranker → rrf_rerank 正常出数；repo 注入 → eval_runs 落库
"""
from __future__ import annotations

import json

import pytest

from app.eval.ablation import STRATEGIES, run_ablation
from app.eval.case_loader import RetrievalCase
from app.eval.runs import MemoryEvalRunRepo
from app.retrieval.rerank import RerankUnavailableError
from app.services.embedding import FakeEmbeddingClient

#: 确定性检索命中（doc 级：kb-ret-01 在 rank1/3，kb-ret-02 在 rank2）
FAKE_HITS = [
    {"chunk_id": "kb-ret-01-0", "doc_id": "kb-ret-01", "title": "售后政策",
     "content": "退款将在 3~5 个工作日内原路退回。", "score": 1.0},
    {"chunk_id": "kb-ret-02-0", "doc_id": "kb-ret-02", "title": "商品手册",
     "content": "保温杯容量 500ml。", "score": 0.9},
    {"chunk_id": "kb-ret-01-1", "doc_id": "kb-ret-01", "title": "售后政策",
     "content": "已签收 7 天内可无理由退货。", "score": 0.8},
]

CASES = [
    RetrievalCase(query="退款多久到账", gold_docs=["kb-ret-01"]),
    RetrievalCase(query="保温杯容量多大", gold_docs=["kb-ret-02"]),
]


class FakeES:
    """Fake 检索：三条固定命中（与查询无关，deterministic）。"""

    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        return FAKE_HITS[:size]

    async def search_knn(self, q_vector: list[float], size: int = 10) -> list[dict]:
        return FAKE_HITS[:size]

    async def search_rrf(self, q: str, q_vector: list[float], size: int = 10) -> list[dict]:
        return FAKE_HITS[:size]


class FakeRerankerOk:
    """可用的 Fake 重排：按候选原顺序返回。"""

    model = "fake-reranker"

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[dict]:
        return [
            {"index": i, "relevance_score": 1.0 - i * 0.01} for i in range(min(top_n, len(documents)))
        ]


class FakeRerankerDown:
    """不可用的重排（模拟无 RERANKER_API_KEY）。"""

    model = "fake-reranker"

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[dict]:
        raise RerankUnavailableError("未配置 RERANKER_API_KEY")


@pytest.fixture
def es() -> FakeES:
    return FakeES()


@pytest.mark.spec("SP-EVAL-003")
class TestAblationUnit:
    async def test_ev_302_five_strategies_with_correct_values(self, es: FakeES) -> None:
        # 显式注入 Fake 重排：避免依赖环境是否有 RERANKER_API_KEY（零网络）
        rows = await run_ablation(es, FakeEmbeddingClient(dim=1024), CASES,
                                  rerank_client=FakeRerankerOk())
        assert [r["strategy"] for r in rows] == list(STRATEGIES)  # E1~E5 顺序稳定
        for row in rows:
            assert row["cases"] == 2 and row["skipped"] is False
        # 手工样本：case1 命中 rank1（recall 1 / MRR 1 / NDCG 1），
        # case2 命中 rank2（recall 1 / MRR 0.5 / NDCG 1/log2(3)≈0.6309）
        bm25 = rows[0]
        assert bm25["recall@5"] == pytest.approx(1.0)
        assert bm25["mrr"] == pytest.approx(0.75)
        # 输出契约为 4 位小数（round(…, 4)）
        assert bm25["ndcg@5"] == pytest.approx(round((1.0 + 1 / 1.5849625007211563) / 2, 4))

    async def test_ev_303_rerank_unavailable_marks_skipped_only(self, es: FakeES) -> None:
        rows = await run_ablation(es, FakeEmbeddingClient(dim=1024), CASES,
                                  rerank_client=FakeRerankerDown())
        rerank_row = next(r for r in rows if r["strategy"] == "rrf_rerank")
        assert rerank_row["skipped"] is True
        assert rerank_row["recall@5"] is None and rerank_row["mrr"] is None
        # 其余 4 组不受影响
        others = [r for r in rows if r["strategy"] != "rrf_rerank"]
        assert all(r["skipped"] is False and r["recall@5"] is not None for r in others)

    async def test_ev_304_rerank_ok_and_repo_record(self, es: FakeES) -> None:
        repo = MemoryEvalRunRepo()
        rows = await run_ablation(es, FakeEmbeddingClient(dim=1024), CASES,
                                  rerank_client=FakeRerankerOk(), repo=repo)
        rerank_row = next(r for r in rows if r["strategy"] == "rrf_rerank")
        assert rerank_row["skipped"] is False
        assert rerank_row["recall@5"] == pytest.approx(1.0)
        # 结果已写入 eval_runs（消融表结构供看板渲染）
        runs = await repo.list_runs(run_type="ablation")
        assert len(runs) == 1
        assert len(runs[0].metrics["strategies"]) == 5
        assert runs[0].metrics["strategies"][0]["strategy"] == "bm25"

    async def test_ev_305_accepts_file_path(self, es: FakeES, tmp_path) -> None:
        path = tmp_path / "retrieval.jsonl"
        path.write_text(
            "\n".join(
                json.dumps({"query": c.query, "gold_docs": c.gold_docs}) for c in CASES
            ),
            encoding="utf-8",
        )
        rows = await run_ablation(es, FakeEmbeddingClient(dim=1024), str(path),
                                  rerank_client=FakeRerankerOk())
        assert len(rows) == 5 and rows[0]["recall@5"] == pytest.approx(1.0)
