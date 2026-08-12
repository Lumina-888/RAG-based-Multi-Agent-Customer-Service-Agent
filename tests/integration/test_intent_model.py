"""SP-INT-002 轻量分类器（fastText 训练与评测）：T-INT-201/202。

- T-INT-201 测试集 Accuracy ≥ 85%
- T-INT-202 order_query 与 refund 混淆可控（F1 ≥ 0.8，混淆矩阵断言）
- 产物：训练后落盘 `models/intent/fasttext.bin`（启动时加载，SP-INT-002）
- 依赖：fasttext（fasttext-wheel）与 data/train、data/test_cases 数据文件
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.intent.classifier import FastTextIntentClassifier, train_fasttext
from app.intent.labels import INVALID_INTENT, INTENT_LABELS

ROOT = Path(__file__).resolve().parents[2]
TRAIN_CSV = ROOT / "data" / "train" / "intent_train.csv"
TEST_CSV = ROOT / "data" / "test_cases" / "intent.csv"
MODEL_PATH = ROOT / "models" / "intent" / "fasttext.bin"


def _load_rows(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(row["label"], row["text"]) for row in reader]


def _to_fasttext_txt(rows: list[tuple[str, str]]) -> str:
    return "\n".join(f"__label__{label} {text}" for label, text in rows)


def _binary_f1(confusion: dict[tuple[str, str], int], label: str) -> float:
    """二分类 F1：混淆矩阵 {（真实, 预测）: 计数}。"""
    tp = confusion.get((label, label), 0)
    fp = sum(c for (_, pred), c in confusion.items() if pred == label and c) - tp
    fn = sum(c for (real, _), c in confusion.items() if real == label and c) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


@pytest.fixture(scope="module")
def model(tmp_path_factory: pytest.TempPathFactory) -> FastTextIntentClassifier:
    """训练 fastText 并落盘 models/intent/fasttext.bin（模块级一次）。"""
    pytest.importorskip("fasttext", reason="需 fasttext（pip install fasttext-wheel）")
    if not TRAIN_CSV.exists() or not TEST_CSV.exists():
        pytest.skip("缺少意图数据文件（先运行 scripts/gen_intent_data.py）")
    train_txt = tmp_path_factory.mktemp("intent") / "intent_train.txt"
    train_txt.write_text(_to_fasttext_txt(_load_rows(TRAIN_CSV)), encoding="utf-8")
    return train_fasttext(train_txt, MODEL_PATH, epoch=30, lr=0.8, dim=50, word_ngrams=2)


@pytest.mark.spec("SP-INT-002")
@pytest.mark.integration
class TestIntentModel:
    async def test_int_201_accuracy_gate(self, model: FastTextIntentClassifier) -> None:
        rows = _load_rows(TEST_CSV)
        assert len(rows) >= 300  # 每类 ≥ 50

        correct = 0
        for label, text in rows:
            if (await model.predict(text)).intent == label:
                correct += 1
        accuracy = correct / len(rows)
        assert accuracy >= 0.85, f"Accuracy={accuracy:.3f} 低于门槛 0.85（SP-INT-002）"

    async def test_int_202_confusion_f1(self, model: FastTextIntentClassifier) -> None:
        rows = _load_rows(TEST_CSV)
        confusion: dict[tuple[str, str], int] = {}
        for label, text in rows:
            pred = (await model.predict(text)).intent
            confusion[(label, pred)] = confusion.get((label, pred), 0) + 1

        # order_query 与 refund 混淆可控
        for label in ("order_query", "refund"):
            f1 = _binary_f1(confusion, label)
            assert f1 >= 0.8, f"{label} F1={f1:.3f} 低于 0.8（SP-INT-002）"

    async def test_int_202_invalid_input(self, model: FastTextIntentClassifier) -> None:
        assert (await model.predict("")).intent == INVALID_INTENT
        assert (await model.predict("长" * 500)).intent == INVALID_INTENT

    async def test_int_202_labels_in_output_space(self, model: FastTextIntentClassifier) -> None:
        rows = _load_rows(TEST_CSV)
        for label, text in rows[:60]:
            assert (await model.predict(text)).intent in INTENT_LABELS

    async def test_int_202_load_artifact(self) -> None:
        """训练产物可加载（启动时加载路径，SP-INT-002）。"""
        if not MODEL_PATH.exists():
            pytest.skip("缺少训练产物 fasttext.bin（先跑训练用例）")
        loaded = FastTextIntentClassifier.load(MODEL_PATH)
        result = await loaded.predict("我要申请退款")
        assert result.intent in INTENT_LABELS
        assert 0.0 <= result.conf <= 1.0
        assert loaded.model_name == "fasttext.bin"

    def test_int_202_load_missing_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="不存在"):
            FastTextIntentClassifier.load(ROOT / "models" / "intent" / "nonexistent.bin")
