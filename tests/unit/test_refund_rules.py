"""SP-REF-003 订单状态与时效预审（规则引擎，非 LLM）：T-REF-301 ~ 305。

- T-REF-301 未发货：only_refund 通过；return_refund → 4220 + 引导
- T-REF-302 已发货未签收：直接退款拒绝（4220，仅可拦截/拒收）
- T-REF-303 已签收 ≤ 7 天：无理由退货 / 质量问题均可（return_refund 通过）
- T-REF-304 7 < 签收 ≤ 15 天：仅质量问题（附凭证），普通原因 → 4220
- T-REF-305 签收 > 15 天：4220 + 转人工
- 断言错误码（4220）与 rule 字段（data 内）
"""
from __future__ import annotations

import pytest

from app.refund.rules import precheck

#: 各档订单（状态 + 签收天数）


@pytest.mark.spec("SP-REF-003")
class TestPrecheckRules:
    def test_ref_301_not_shipped_only_refund(self) -> None:
        r = precheck(status="pending_shipment", received_days=None,
                     refund_type="only_refund", amount=299.0, order_amount=299.0)
        assert r.passed is True

        r2 = precheck(status="pending_shipment", received_days=None,
                      refund_type="return_refund", amount=299.0, order_amount=299.0)
        assert r2.passed is False
        assert r2.code == 4220 and r2.rule == "not_shipped_only_refund"  # 引导改仅退款

    def test_ref_302_shipped_reject(self) -> None:
        r = precheck(status="shipped", received_days=None,
                     refund_type="only_refund", amount=59.0, order_amount=59.0)
        assert r.passed is False
        assert r.code == 4220 and r.rule == "shipped_intercept_only"  # 仅可拦截/拒收

    def test_ref_303_received_within_7d(self) -> None:
        r = precheck(status="received", received_days=3,
                     refund_type="return_refund", amount=199.0, order_amount=199.0)
        assert r.passed is True
        assert r.rule == "received_within_7d"  # 无理由退货/质量问题

    def test_ref_304_received_7_15d_quality_only(self) -> None:
        # 普通原因 → 4220
        r = precheck(status="received", received_days=10,
                     refund_type="return_refund", amount=199.0, order_amount=199.0,
                     reason="不想要了")
        assert r.passed is False
        assert r.code == 4220 and r.rule == "received_7_15d_quality_only"
        # 质量问题（附凭证）→ 通过
        r2 = precheck(status="received", received_days=10,
                      refund_type="return_refund", amount=199.0, order_amount=199.0,
                      reason="质量问题，杯盖损坏")
        assert r2.passed is True

    def test_ref_305_received_over_15d(self) -> None:
        r = precheck(status="received", received_days=16,
                     refund_type="return_refund", amount=199.0, order_amount=199.0)
        assert r.passed is False
        assert r.code == 4220 and r.rule == "received_over_15d_transfer"  # 转人工
        assert r.transfer is True

    def test_ref_305_unknown_status(self) -> None:
        r = precheck(status="unknown_status", received_days=None,
                     refund_type="only_refund", amount=1.0, order_amount=1.0)
        assert r.passed is False
        assert r.code == 4220
