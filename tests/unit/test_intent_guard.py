"""SP-INT-004 拒答与情绪升级：T-INT-401/402。

- T-INT-401 辱骂词表或高强度重复标点 → 转人工（transfer）
- T-INT-402 知识库 top-1 相似度 < RETRIEVAL_REJECT_THRESHOLD（默认 0.45）→ 拒答
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.intent.guard import detect_abuse, detect_intense_punctuation, should_reject, should_transfer


@pytest.mark.spec("SP-INT-004")
class TestGuard:
    def test_int_401_abuse_triggers_transfer(self) -> None:
        assert should_transfer("你这个垃圾") is True
        assert should_transfer("滚！") is True
        assert should_transfer("傻逼 去死吧") is True
        assert should_transfer("商品质量不错") is False  # 正常文本不误伤

    def test_int_401_intense_punctuation_triggers_transfer(self) -> None:
        assert should_transfer("？？？？？？") is True  # 高强度重复标点
        assert should_transfer("！！！") is True
        assert should_transfer("凭什么？？？") is True
        assert should_transfer("？") is False  # 单个标点不触发
        assert should_transfer("好的！！") is False  # 两个不触发
        assert should_transfer("？!？") is False  # 未连续重复不触发

    def test_int_401_detect_helpers(self) -> None:
        assert detect_abuse("垃圾") is True
        assert detect_abuse("感谢客服") is False
        assert detect_intense_punctuation("？？？") is True
        assert detect_intense_punctuation("正常问题？") is False

    def test_int_402_low_similarity_reject(self) -> None:
        assert should_reject(0.3, threshold=0.45) is True
        assert should_reject(0.44, threshold=0.45) is True
        assert should_reject(0.45, threshold=0.45) is False  # 边界：≥ 阈值不拒
        assert should_reject(0.6, threshold=0.45) is False

    def test_int_402_default_threshold_from_config(self) -> None:
        settings = Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m")
        assert settings.retrieval_reject_threshold == 0.45  # 默认阈值
        assert should_reject(0.3) is True  # 未传阈值时按默认 0.45
        assert should_reject(0.5) is False
