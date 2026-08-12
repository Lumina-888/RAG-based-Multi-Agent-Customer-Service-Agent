"""SP-RET-003 RRF 融合（核心纯函数）：T-RET-301 ~ 304（规格）+ T-RET-505/506（SP-RET-007 加权）。

- T-RET-301 公式正确：score = Σ 1/(k+rank)，按降序
- T-RET-302 双路都在前列的排前
- T-RET-303 空列表输入返回空；单路输入正常参与
- T-RET-304 相同 id 只出现一次（同路重复取最优 rank）
- T-RET-505 加权 RRF 公式（w_bm25=1.5, w_vec=1.0）
- T-RET-506 权重可翻转排序（关键词查询 bm25 权重更高）
"""
from __future__ import annotations

import pytest

from app.retrieval.fusion import rrf_fuse, weighted_rrf_fuse


@pytest.mark.spec("SP-RET-003")
class TestRRFFusion:
    def test_ret_301_formula(self) -> None:
        """score = Σ 1/(k+rank)，k=60 默认；按降序返回。"""
        bm25 = [("a", 1), ("b", 2)]
        vec = [("b", 1), ("c", 2)]

        result = rrf_fuse(bm25, vec)

        assert result[0][0] == "b"  # 双路都命中 → 第一
        assert result[0][1] == pytest.approx(1 / 61 + 1 / 62)  # bm25 rank2 + vec rank1
        assert result[1][0] == "a"
        assert result[1][1] == pytest.approx(1 / 61)
        assert result[2][0] == "c"
        assert result[2][1] == pytest.approx(1 / 62)  # rank=2 → 1/(60+2)
        assert [s for _, s in result] == sorted((s for _, s in result), reverse=True)

    def test_ret_302_both_paths_first(self) -> None:
        """两路都排第 1 的文档分数最高，压过仅单路高排名的文档。"""
        bm25 = [("x", 1), ("y", 2)]
        vec = [("x", 1), ("z", 1)]

        result = rrf_fuse(bm25, vec)

        assert result[0][0] == "x"
        assert result[0][1] == pytest.approx(2 / 61)
        assert {doc for doc, _ in result} == {"x", "y", "z"}

    def test_ret_303_empty_inputs(self) -> None:
        assert rrf_fuse([], []) == []
        # 只出现在一路的文档正常参与
        assert rrf_fuse([("a", 1)], []) == [("a", pytest.approx(1 / 61))]
        assert rrf_fuse([], [("b", 3)]) == [("b", pytest.approx(1 / 63))]
        assert rrf_fuse([], [("b", 3), ("a", 1)])[0][0] == "a"  # 单路按 rank 降序

    def test_ret_304_dedupe(self) -> None:
        """相同 id 只出现一次；同路内重复出现取最优（最小）rank。"""
        bm25 = [("a", 1), ("a", 4)]  # 防御：同路重复 → 只计 rank=1
        vec = [("a", 2), ("b", 1)]

        result = rrf_fuse(bm25, vec)

        assert [doc for doc, _ in result].count("a") == 1
        a_score = dict(result)["a"]
        assert a_score == pytest.approx(1 / 61 + 1 / 62)  # rank 1 与 rank 2 各计一次

    def test_ret_304_k_parameter(self) -> None:
        result = rrf_fuse([("a", 1)], [], k=60)
        assert result[0][1] == pytest.approx(1 / 61)
        result2 = rrf_fuse([("a", 1)], [], k=100)
        assert result2[0][1] == pytest.approx(1 / 101)


@pytest.mark.spec("SP-RET-007")
class TestWeightedRRF:
    def test_ret_505_weighted_formula(self) -> None:
        """加权 RRF：score = w_bm25·Σ1/(k+r_b) + w_vec·Σ1/(k+r_v)。"""
        bm25 = [("a", 1)]
        vec = [("a", 1)]

        result = weighted_rrf_fuse(bm25, vec, k=60, w_bm25=1.5, w_vec=1.0)

        assert result[0][1] == pytest.approx(1.5 / 61 + 1.0 / 61)

    def test_ret_506_weights_flip_ordering(self) -> None:
        """仅 bm25 命中的文档 vs 仅向量命中的文档：权重决定先后。"""
        bm25_only = ("k", 1)
        vec_only = ("v", 1)

        # 关键词查询：w_bm25=1.5 → bm25 单路文档压过向量单路
        r1 = weighted_rrf_fuse([bm25_only], [vec_only], k=60, w_bm25=1.5, w_vec=1.0)
        assert r1[0][0] == "k"
        assert r1[0][1] == pytest.approx(1.5 / 61)
        assert r1[1][1] == pytest.approx(1.0 / 61)

        # 语义查询：w_vec=1.5 → 向量单路文档压过 bm25 单路
        r2 = weighted_rrf_fuse([bm25_only], [vec_only], k=60, w_bm25=1.0, w_vec=1.5)
        assert r2[0][0] == "v"
        assert r2[0][1] == pytest.approx(1.5 / 61)

    def test_ret_506_weighted_dedupe(self) -> None:
        result = weighted_rrf_fuse([("a", 1)], [("a", 2), ("a", 3)], k=60, w_bm25=1.5, w_vec=1.0)
        assert len(result) == 1
        assert result[0][1] == pytest.approx(1.5 / 61 + 1.0 / 62)  # 同路只取最优 rank
