"""SP-REF-003/004 预审规则引擎（规则，非 LLM）。

SP-REF-003 订单状态与时效：
- 未发货：仅 only_refund（return_refund → 4220 + 引导）
- 已发货未签收：仅可"拦截/拒收"，直接退款拒绝（4220 + 引导）
- 已签收 ≤ 7 天：无理由退货 / 质量问题均可
- 已签收 7~15 天：仅质量问题（附凭证）
- 已签收 > 15 天：4220 + 转人工

SP-REF-004 风控：单笔 > ¥2000（review_required）——频次（30 天 > 3 次）在服务层
结合仓储统计判定（规则函数保持纯函数，频次数据由服务层注入）。
"""
from __future__ import annotations

from dataclasses import dataclass

#: 质量问题关键词（7~15 天档需附凭证）
QUALITY_REASON_HINTS = ("质量", "故障", "损坏", "坏", "瑕疵", "破损")

#: 单笔金额风控阈值（SP-REF-004）
AMOUNT_LIMIT = 2000.0
#: 30 天内退款次数阈值（SP-REF-004，服务层统计）
FREQUENCY_LIMIT = 3
#: 风控统计窗口（天）
RISK_WINDOW_DAYS = 30


@dataclass
class PrecheckResult:
    """预审结果：通过 / 拒绝（4220 + rule + 引导信息）。"""

    passed: bool
    code: int = 0
    rule: str = ""
    reason: str = ""
    review_required: bool = False
    transfer: bool = False


def precheck(
    *,
    status: str,
    received_days: int | None,
    refund_type: str,
    amount: float,
    order_amount: float,
    reason: str = "",
) -> PrecheckResult:
    """订单状态与时效预审（SP-REF-003）。"""
    if status == "pending_shipment":
        if refund_type != "only_refund":
            return PrecheckResult(
                passed=False, code=4220, rule="not_shipped_only_refund",
                reason="未发货订单仅支持仅退款（取消订单全额退），请切换为仅退款",
            )
        return PrecheckResult(passed=True, rule="not_shipped_ok")
    if status == "shipped":
        return PrecheckResult(
            passed=False, code=4220, rule="shipped_intercept_only",
            reason="订单已发货未签收，仅可拦截/拒收，暂不支持直接退款",
        )
    if status == "received":
        days = received_days or 0
        if days <= 7:
            return PrecheckResult(passed=True, rule="received_within_7d")
        if days <= 15:
            if any(hint in reason for hint in QUALITY_REASON_HINTS):
                return PrecheckResult(passed=True, rule="received_7_15d_quality_only")
            return PrecheckResult(
                passed=False, code=4220, rule="received_7_15d_quality_only",
                reason="签收超过 7 天仅支持质量问题退货（需附凭证）",
            )
        return PrecheckResult(
            passed=False, code=4220, rule="received_over_15d_transfer",
            reason="签收超过 15 天无法在线申请退款，请转人工客服处理",
            transfer=True,
        )
    return PrecheckResult(
        passed=False, code=4220, rule="unknown_status",
        reason=f"未知订单状态: {status}",
    )


def amount_risk(amount: float) -> PrecheckResult | None:
    """单笔金额风控（SP-REF-004）：> ¥2000 → 4220 + review_required。"""
    if amount > AMOUNT_LIMIT:
        return PrecheckResult(
            passed=False, code=4220, rule="amount_over_limit",
            reason=f"单笔退款金额超过 ¥{AMOUNT_LIMIT:.0f}，需人工审核",
            review_required=True,
        )
    return None


def frequency_risk(refund_count_30d: int) -> PrecheckResult | None:
    """频次风控（SP-REF-004）：30 天内退款 > 3 次 → 4220 + review_required。"""
    if refund_count_30d > FREQUENCY_LIMIT:
        return PrecheckResult(
            passed=False, code=4220, rule="frequency_over_limit",
            reason=f"30 天内退款次数超过 {FREQUENCY_LIMIT} 次，需人工审核",
            review_required=True,
        )
    return None
