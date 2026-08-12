"""SP-REF-001 建单入参契约：T-REF-101/102。

- T-REF-101 refund_type 枚举（only_refund / return_refund），非法 → 4001
- T-REF-102 amount 边界：必填、> 0、≤ 订单实付金额（超界 → 4001）
"""
from __future__ import annotations

import pytest

from app.refund.validate import RefundRequest, validate_refund_request


def _req(**overrides) -> dict:
    base = {"order_id": "ORD-20260811-001", "refund_type": "only_refund",
            "reason": "不想要了", "amount": 199.0}
    base.update(overrides)
    return base


@pytest.mark.spec("SP-REF-001")
class TestRefundValidate:
    def test_ref_101_type_enum(self) -> None:
        assert validate_refund_request(RefundRequest(**_req())) is None
        assert validate_refund_request(RefundRequest(**_req(refund_type="return_refund"))) is None

        err = validate_refund_request(RefundRequest(**_req(refund_type="refund_now")))
        assert err is not None and err.code == 4001
        assert "refund_type" in err.message

        err2 = validate_refund_request(RefundRequest(**_req(refund_type="")))
        assert err2 is not None and err2.code == 4001

    def test_ref_102_amount_boundaries(self) -> None:
        # 缺失 / 非数字 / 0 / 负数 → 4001
        assert validate_refund_request(RefundRequest(**_req(amount=None))).code == 4001
        assert validate_refund_request(RefundRequest(**_req(amount="abc"))).code == 4001
        assert validate_refund_request(RefundRequest(**_req(amount=0))).code == 4001
        assert validate_refund_request(RefundRequest(**_req(amount=-5))).code == 4001
        # 超过订单实付金额 → 4001（order_amount 由服务层从订单取值传入）
        err = validate_refund_request(RefundRequest(**_req(amount=199.01)), order_amount=199.0)
        assert err.code == 4001 and "实付" in err.message
        # 恰好等于实付 → 通过；必填字段缺失 → 4001
        assert validate_refund_request(RefundRequest(**_req(amount=199.0)), order_amount=199.0) is None
        assert validate_refund_request(RefundRequest(**_req(order_id=""))).code == 4001
        assert validate_refund_request(RefundRequest(**_req(reason=""))).code == 4001
