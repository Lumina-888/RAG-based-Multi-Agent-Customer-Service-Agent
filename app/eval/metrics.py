"""SP-EVAL-002 指标计算（纯函数，手工样本可验证）。

- 分类侧：`accuracy` / `macro_f1` / `confusion_matrix`
- 检索侧（相关为 doc 级 id 集合，检索为按相关度降序的 id 列表）：
  - `recall_at_k`：命中相关数 / 相关总数（k 截断生效）
  - `mrr`：第一个相关文档排名的倒数（未命中 → 0）
  - `ndcg_at_k`：DCG / IDCG（二值相关性；增益 1/log2(rank+1)）

口径约定（与测试一致）：空输入（空相关 / 空检索）记 0.0。
"""
from __future__ import annotations

import math
from collections import defaultdict


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    """分类准确率；空输入记 0.0。"""
    if not y_true or len(y_true) != len(y_pred):
        return 0.0
    return sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)


def _per_class_counts(
    y_true: list[str], y_pred: list[str], labels: list[str] | None = None
) -> tuple[list[str], dict[str, dict[str, int]]]:
    """统计每类 tp/fp/fn；labels 缺省取 y_true ∪ y_pred 的有序并集。"""
    classes = list(labels) if labels else sorted(set(y_true) | set(y_pred))
    counts = {c: {"tp": 0, "fp": 0, "fn": 0} for c in classes}
    for t, p in zip(y_true, y_pred):
        if t == p:
            counts[t]["tp"] += 1
        else:
            counts[t]["fn"] += 1
            counts[p]["fp"] += 1
    return classes, counts


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str] | None = None) -> float:
    """宏平均 F1：各类 P/R/F1 的算术平均（tp=0 的类记 0）。"""
    classes, counts = _per_class_counts(y_true, y_pred, labels)
    if not classes:
        return 0.0
    f1s = []
    for c in classes:
        tp, fp, fn = counts[c]["tp"], counts[c]["fp"], counts[c]["fn"]
        if tp == 0:
            f1s.append(0.0)
            continue
        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        f1s.append(2 * precision * recall / (precision + recall) if (precision + recall) else 0.0)
    return sum(f1s) / len(f1s)


def confusion_matrix(
    y_true: list[str], y_pred: list[str], labels: list[str] | None = None
) -> dict[str, dict[str, int]]:
    """混淆矩阵 `{真实类: {预测类: 计数}}`；labels 缺省取并集。"""
    classes = sorted(set(y_true) | set(y_pred)) if labels is None else list(labels)
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t, p in zip(y_true, y_pred):
        matrix[t][p] += 1
    return {c: {pc: matrix[c][pc] for pc in classes} for c in classes}


def recall_at_k(
    relevant: set[str] | list[str], retrieved: list[str], k: int = 5
) -> float:
    """Recall@k：top-k 中命中相关**去重**文档数 / 相关文档总数（口径：空相关记 0）。

    同一 doc 在检索结果中出现多次只计一次命中（防重复计数 > 1）。
    """
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    hits = len({doc for doc in retrieved[:k] if doc in relevant_set})
    return hits / len(relevant_set)


def mrr(relevant: set[str] | list[str], retrieved: list[str]) -> float:
    """MRR：第一个相关文档排名倒数；未命中 → 0。"""
    relevant_set = set(relevant)
    for rank, doc in enumerate(retrieved, start=1):
        if doc in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevant: set[str] | list[str], retrieved: list[str], k: int = 5) -> float:
    """NDCG@k（二值相关性）：DCG / IDCG；无相关文档 → 0。

    同一相关 doc 重复出现只计首次（防重复贡献增益）。
    """
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0

    def _dcg(ranking: list[str]) -> float:
        seen: set[str] = set()
        total = 0.0
        for rank, doc in enumerate(ranking[:k], start=1):
            if doc in relevant_set and doc not in seen:
                seen.add(doc)
                total += 1.0 / math.log2(rank + 1)
        return total

    ideal = list(relevant_set)  # 理想排序：相关在前
    idcg = _dcg(ideal)
    if idcg == 0.0:
        return 0.0
    return _dcg(retrieved) / idcg
