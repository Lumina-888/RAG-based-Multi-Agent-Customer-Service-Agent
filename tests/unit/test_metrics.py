"""SP-EVAL-002 指标计算（纯函数，手工样本验证）：T-EVAL-201 + MRR/NDCG。

所有指标均为纯函数，期望值用手工推导（0~1 浮点，pytest.approx 断言）：
- Recall@5：命中相关文档数 / 相关文档总数（k 截断生效）
- MRR：第一个相关文档排名的倒数（未命中 → 0）
- NDCG@5：DCG / IDCG（二值相关性，无相关文档 → 0）
- Accuracy / 宏 F1 / 混淆矩阵：分类侧指标
"""
from __future__ import annotations

import pytest

from app.eval.metrics import (
    accuracy,
    confusion_matrix,
    macro_f1,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


@pytest.mark.spec("SP-EVAL-002")
class TestRetrievalMetrics:
    def test_ev_201_recall_at_k(self) -> None:
        # 相关 {a}，top-5 命中 → 1.0
        assert recall_at_k({"a"}, ["x", "y", "a", "b", "c"], k=5) == pytest.approx(1.0)
        # 相关 {a, b}，全部命中（顺序无关）→ 1.0
        assert recall_at_k({"a", "b"}, ["a", "x", "b"], k=5) == pytest.approx(1.0)
        # 相关 {a, b}，只命中 1 个 → 0.5
        assert recall_at_k({"a", "b"}, ["x", "y", "a"], k=5) == pytest.approx(0.5)
        # k 截断：相关在第 2 位，k=1 不命中 → 0.0
        assert recall_at_k({"a"}, ["x", "a"], k=1) == pytest.approx(0.0)
        # 完全未命中 → 0.0；空检索 → 0.0；空相关 → 0.0（口径：无相关文档记 0）
        assert recall_at_k({"a", "b"}, ["x", "y", "z"], k=5) == pytest.approx(0.0)
        assert recall_at_k({"a"}, [], k=5) == pytest.approx(0.0)
        assert recall_at_k(set(), ["a", "b"], k=5) == pytest.approx(0.0)

    def test_mrr_hand_sample(self) -> None:
        # 第一个相关在第 2 位 → 1/2
        assert mrr({"a"}, ["x", "a", "b"]) == pytest.approx(0.5)
        # 第一个相关在第 1 位 → 1.0
        assert mrr({"a", "b"}, ["b", "x", "a"]) == pytest.approx(1.0)
        # 未命中 → 0.0
        assert mrr({"b"}, ["a", "c", "d"]) == pytest.approx(0.0)
        # 相关在第 3 位 → 1/3
        assert mrr({"c"}, ["x", "y", "c"]) == pytest.approx(1 / 3)

    def test_ndcg_at_k_hand_sample(self) -> None:
        # DCG = 1/log2(3) ≈ 0.6309；IDCG = 1/log2(2) = 1 → NDCG ≈ 0.6309
        assert ndcg_at_k({"a"}, ["x", "a", "y", "z", "w"], k=5) == pytest.approx(1 / 1.5849625007211563)
        # 相关 {a,b} 在 top-2 → DCG=IDCG → 1.0（二值相关性对置换不敏感）
        assert ndcg_at_k({"a", "b"}, ["a", "b", "x", "y", "z"], k=5) == pytest.approx(1.0)
        assert ndcg_at_k({"a", "b"}, ["b", "a", "x", "y", "z"], k=5) == pytest.approx(1.0)
        # 部分命中：相关 {a,b,c}，a 在 1 位、b 在 4 位 → DCG=1+1/log2(5)，IDCG=1+1/log2(3)+1/log2(4)
        dcg = 1.0 + 1.0 / 2.321928094887362  # log2(5)
        idcg = 1.0 + 1.0 / 1.5849625007211563 + 1.0 / 2.0  # log2(3), log2(4)
        assert ndcg_at_k({"a", "b", "c"}, ["a", "x", "y", "b", "z"], k=5) == pytest.approx(dcg / idcg)
        # 未命中 → 0.0
        assert ndcg_at_k({"a"}, ["x", "y", "z"], k=5) == pytest.approx(0.0)


@pytest.mark.spec("SP-EVAL-002")
class TestClassificationMetrics:
    def test_accuracy(self) -> None:
        assert accuracy(["a", "a", "b"], ["a", "b", "b"]) == pytest.approx(2 / 3)
        assert accuracy([], []) == pytest.approx(0.0)  # 空输入口径：0

    def test_macro_f1_hand_sample(self) -> None:
        # y_true=[a,a,b], y_pred=[a,b,b]：
        #   a: tp=1 fn=1 fp=0 → P=1 R=0.5 F1=2/3；b: tp=1 fp=1 fn=0 → F1=2/3
        #   → 宏 F1 = 2/3
        assert macro_f1(["a", "a", "b"], ["a", "b", "b"]) == pytest.approx(2 / 3)
        # 全对 → 1.0
        assert macro_f1(["a", "b", "c"], ["a", "b", "c"]) == pytest.approx(1.0)
        # 全错 → 0.0（无 tp）
        assert macro_f1(["a", "b"], ["b", "a"]) == pytest.approx(0.0)

    def test_confusion_matrix(self) -> None:
        cm = confusion_matrix(["a", "a", "b"], ["a", "b", "b"], labels=["a", "b"])
        assert cm["a"]["a"] == 1 and cm["a"]["b"] == 1
        assert cm["b"]["b"] == 1 and cm["b"]["a"] == 0
