"""SP-INT-001 意图体系：6 类意图 + 非法输入（空串/超长）→ invalid。"""
from __future__ import annotations

#: 分类器输出空间（6 类，SP-INT-001）
INTENT_LABELS: tuple[str, ...] = (
    "pre_sales",  # 售前咨询
    "after_sales",  # 售后咨询
    "order_query",  # 订单查询
    "refund",  # 退款退货
    "complaint",  # 投诉
    "human",  # 转人工
)
INVALID_INTENT = "invalid"

#: 输入长度上限（字符）；超过视为非法输入
MAX_INPUT_LEN = 200


def is_valid_input(text: str) -> bool:
    """非法输入判定：空串 / 纯空白 / 超长（>200 字符）。"""
    return bool(text) and bool(text.strip()) and len(text) <= MAX_INPUT_LEN
