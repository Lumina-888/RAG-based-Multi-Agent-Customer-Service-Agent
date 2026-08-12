"""SP-EVAL-003 消融实验跑批（ES 守卫，kb fixture 已索引样例文档）：T-EVAL-301。

- T-EVAL-301：5 组策略（仅BM25 / 仅向量 / RRF / RRF+重排 / 动态权重）均可执行，
  输出结构 `[{strategy, recall@5, mrr, ndcg@5, cases, skipped}]` 稳定；
  重排策略无 `RERANKER_API_KEY` 时该行标记 `skipped=true`，不阻塞其余策略
- 补充：注入 FakeReranker 时 rrf_rerank 走真实重排路径（不标记 skipped）
"""
from __future__ import annotations

import json

import pytest

from app.eval.ablation import STRATEGIES, run_ablation
from app.retrieval.rerank import RerankClient
from app.services.embedding import FakeEmbeddingClient


@pytest.fixture
def retrieval_cases(tmp_path) -> str:
    """手写 retrieval.jsonl：gold_docs 对齐 conftest SAMPLE_DOCS（kb-ret-01/02）。"""
    lines = [
        {"query": "退款多久到账", "gold_docs": ["kb-ret-01"]},
        {"query": "退货规则是什么", "gold_docs": ["kb-ret-01"]},
        {"query": "保温杯容量多大", "gold_docs": ["kb-ret-02"]},
        {"query": "保温杯怎么充电", "gold_docs": ["kb-ret-02"]},
    ]
    path = tmp_path / "retrieval.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return str(path)


class FakeReranker:
    """确定性 Fake：按候选原顺序返回（分数递减），不依赖真实 API。"""

    model = "fake-reranker"

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[dict]:
        return [
            {"index": i, "relevance_score": 1.0 - i * 0.01} for i in range(min(top_n, len(documents)))
        ]


@pytest.mark.spec("SP-EVAL-003")
@pytest.mark.integration
class TestAblation:
    async def test_ev_301_five_strategies_run(self, kb, retrieval_cases: str) -> None:
        embedding = FakeEmbeddingClient(dim=1024)
        rows = await run_ablation(kb, embedding, retrieval_cases)
        assert [r["strategy"] for r in rows] == list(STRATEGIES)  # E1~E5 顺序稳定

        for row in rows:
            assert set(row) == {"strategy", "recall@5", "mrr", "ndcg@5", "cases", "skipped"}
            assert row["cases"] == 4
            if row["skipped"]:  # 仅 rrf_rerank 无 key 时允许
                assert row["strategy"] == "rrf_rerank"
                assert row["recall@5"] is None
            else:
                for key in ("recall@5", "mrr", "ndcg@5"):
                    assert 0.0 <= row[key] <= 1.0  # 指标数值合法（0~1）

    async def test_ev_301b_rerank_path_with_fake_client(self, kb, retrieval_cases: str) -> None:
        embedding = FakeEmbeddingClient(dim=1024)
        rows = await run_ablation(kb, embedding, retrieval_cases, rerank_client=FakeReranker())
        rerank_row = next(r for r in rows if r["strategy"] == "rrf_rerank")
        assert rerank_row["skipped"] is False
        assert 0.0 <= rerank_row["recall@5"] <= 1.0
