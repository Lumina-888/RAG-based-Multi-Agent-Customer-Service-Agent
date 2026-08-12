"""SP-SEC-002 敏感信息脱敏：回复文本后处理（复用 M0 mask_sensitive）。

- 手机号：13812345678 → 138****5678
- 订单号：ORD-20260811-001 → ORD-****
- 应用位置：编排层 reply_node 统一后处理（SSE 下发与 PG/Redis 落库前），
  覆盖 qa/tool/transfer/confirm 等全部 agent 回复
"""
from __future__ import annotations

from app.core.logging import mask_sensitive


def mask_reply_text(text: str) -> str:
    """LLM 回复 / 编排层最终回复的脱敏后处理；无敏感信息时原样返回。"""
    return mask_sensitive(text)
