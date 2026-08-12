"""SP-INT-001 意图体系：T-INT-101/102。

- T-INT-101 分类器输出为 6 类之一：pre_sales / after_sales / order_query /
  refund / complaint / human
- T-INT-102 非法输入（空串 / 超长 >200 字符）返回 invalid
"""
from __future__ import annotations

import pytest

from app.intent.classifier import FakeIntentClassifier, IntentResult
from app.intent.labels import INTENT_LABELS, INVALID_INTENT, MAX_INPUT_LEN, is_valid_input


@pytest.mark.spec("SP-INT-001")
class TestIntentLabels:
    def test_int_101_six_labels(self) -> None:
        assert len(INTENT_LABELS) == 6
        assert set(INTENT_LABELS) == {
            "pre_sales", "after_sales", "order_query", "refund", "complaint", "human",
        }

    def test_int_101_classifier_accepts_all_labels(self) -> None:
        for label in INTENT_LABELS:
            result = FakeIntentClassifier(intent=label).predict_sync("某消息")
            assert result.intent == label
            assert 0.0 <= result.conf <= 1.0

    def test_int_102_empty_or_whitespace_invalid(self) -> None:
        assert is_valid_input("") is False
        assert is_valid_input("   ") is False
        assert is_valid_input("\t\n") is False
        assert is_valid_input("你好") is True

    def test_int_102_oversize_invalid(self) -> None:
        assert is_valid_input("好" * MAX_INPUT_LEN) is True  # 恰好 200 合法
        assert is_valid_input("好" * (MAX_INPUT_LEN + 1)) is False  # 超长 201

    async def test_int_102_classifier_returns_invalid(self) -> None:
        """分类器对非法输入返回 invalid（不落入 6 类）。"""
        clf = FakeIntentClassifier(intent="refund")
        assert (await clf.predict("")).intent == INVALID_INTENT
        assert (await clf.predict("长" * 300)).intent == INVALID_INTENT
        assert (await clf.predict("   ")).intent == INVALID_INTENT
        result: IntentResult = await clf.predict("我想退款")
        assert result.intent == "refund"
