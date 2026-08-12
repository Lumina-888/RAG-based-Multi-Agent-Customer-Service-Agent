"""SP-REF-001 建单入参契约：`refund_type` 枚举、`amount` 必填且 > 0 且 ≤ 订单实付。

结构校验为纯函数（不依赖订单数据）；`≤ 订单实付金额` 需订单，由服务层传入
`order_amount`（SP-REF-001：amount 由前端/Agent 从订单实付金额取值）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

REFUND_TYPES = ("only_refund", "return_refund")


class RefundRequest(BaseModel):
    """建单入参（SP-REF-001）。

    `amount` 用 Any 兜底：类型非法统一由 `validate_refund_request` 返回 4001
    （避免 Pydantic 提前 422，保证错误码契约一致）。
    """

    order_id: str = ""
    refund_type: str = ""
    reason: str = ""
    amount: Any = None


@dataclass
class ValidationIssue:
    """参数校验失败（统一错误码 4001）。"""

    code: int = 4001
    message: str = ""


def validate_refund_request(
    req: RefundRequest, order_amount: float | None = None
) -> ValidationIssue | None:
    """入参校验：合法返回 None，否则返回 4001 问题。"""
    if not req.order_id.strip():
        return ValidationIssue(message="order_id 不能为空")
    if req.refund_type not in REFUND_TYPES:
        return ValidationIssue(
            message=f"refund_type 非法: {req.refund_type!r}（仅支持 {REFUND_TYPES}）"
        )
    if not req.reason.strip():
        return ValidationIssue(message="reason 不能为空")
    amount = req.amount
    if amount is None or not isinstance(amount, (int, float)):
        return ValidationIssue(message="amount 必填且必须为数字")
    if amount <= 0:
        return ValidationIssue(message=f"amount 必须 > 0（当前 {amount}）")
    if order_amount is not None and amount > order_amount:
        return ValidationIssue(
            message=f"amount 不能超过订单实付金额（{order_amount}）"
        )
    return None
