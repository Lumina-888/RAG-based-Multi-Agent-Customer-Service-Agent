"""SP-INT-004 拒答与情绪升级（规则，非 LLM）：

- 辱骂词表或高强度重复标点 → `should_transfer(text)` 为 True（转人工）
- 知识库 top-1 相似度 < `RETRIEVAL_REJECT_THRESHOLD`（默认 0.45）→
  `should_reject(top1_score)` 为 True（问答 Agent 输出拒答模板，不编造）
"""
from __future__ import annotations

import re

from app.core.config import Settings, get_settings

#: 辱骂词表（演示数据，可扩展）
ABUSE_WORDS: tuple[str, ...] = (
    "傻逼", "煞笔", "垃圾", "废物", "滚", "去死", "白痴", "智障", "脑残",
    "贱人", "妈的", "操", "婊", "畜牲", "nmd", "cnm", "fuck",
)

#: 高强度标点：同一标点连续出现 ≥ 3 个视为情绪升级（混合标点如 ？!？ 不算）
_INTENSE_PUNCT_RE = re.compile(r"([!！?？~～])\1{2,}")


def detect_abuse(text: str) -> bool:
    """辱骂词表命中。"""
    lowered = text.lower()
    return any(word in lowered for word in ABUSE_WORDS)


def detect_intense_punctuation(text: str) -> bool:
    """高强度重复标点：连续 3+ 个 !？~ 等。"""
    return bool(_INTENSE_PUNCT_RE.search(text))


def should_transfer(text: str) -> bool:
    """情绪升级判定：辱骂或高强度重复标点 → 转人工。"""
    return detect_abuse(text) or detect_intense_punctuation(text)


def should_reject(top1_score: float, threshold: float | None = None) -> bool:
    """低相似度拒答判定：top-1 < RETRIEVAL_REJECT_THRESHOLD（默认 0.45）。"""
    if threshold is None:
        settings: Settings = get_settings()
        threshold = settings.retrieval_reject_threshold
    return top1_score < threshold
