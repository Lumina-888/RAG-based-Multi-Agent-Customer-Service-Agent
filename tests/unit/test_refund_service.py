"""SP-REF-002/004/007 退款服务（离线单元层，内存 repo）。

- T-REF-401 风控：单笔 > ¥2000 / 30 天内退款 > 3 次 → 4220 + review_required=true
- T-REF-701 资金操作边界：公开服务入口只能建 CREATED；无任何路径直达 REFUNDING
- T-REF-203（离线版）正常建单全流程（归属/预审/金额校验通过）
"""
from __future__ import annotations

import pytest

from app.refund.repo import MemoryTicketRepo
from app.refund.service import (
    RefundForbiddenError,
    RefundPrecheckError,
    RefundService,
    RefundUnavailableError,
)

ORD_OWNED = "ORD-20260811-001"  # user-1，received 3 天，199 元
ORD_OTHER = "ORD-20260811-003"  # user-2，pending_shipment


@pytest.fixture
def service() -> RefundService:
    return RefundService(repo=MemoryTicketRepo())


@pytest.mark.spec("SP-REF-004")
class TestRiskControl:
    async def test_ref_401_amount_over_limit(self, service: RefundService) -> None:
        """单笔 > ¥2000 → 4220 + review_required。"""
        from app.services.erp_sim import SEED_ORDERS

        SEED_ORDERS["ORD-BIG-001"] = SEED_ORDERS[ORD_OWNED].__class__(
            order_id="ORD-BIG-001", user_id="user-1", status="received",
            amount=2999.0, item_title="大件", received_days=2,
        )
        try:
            with pytest.raises(RefundPrecheckError) as exc:
                await service.create_request(
                    user_id="user-1", order_id="ORD-BIG-001", refund_type="only_refund",
                    reason="不想要了", amount=2999.0,
                )
            assert exc.value.code == 4220
            assert exc.value.rule == "amount_over_limit"
            assert exc.value.review_required is True
        finally:
            del SEED_ORDERS["ORD-BIG-001"]

    async def test_ref_401_frequency_over_limit(self, service: RefundService) -> None:
        """30 天内退款 > 3 次 → 4220 + review_required（第 5 次触发，前 4 次已 REFUNDED）。"""
        from app.services.erp_sim import SEED_ORDERS

        # 造 5 个订单：前 4 单完成退款（终态 REFUNDED），第 5 单触发频次风控
        for i in range(5):
            oid = f"ORD-FREQ-{i}"
            SEED_ORDERS[oid] = SEED_ORDERS[ORD_OWNED].__class__(
                order_id=oid, user_id="user-1", status="received",
                amount=100.0, item_title="x", received_days=1,
            )
        try:
            from app.refund.state_machine import transition

            for i in range(4):
                t = await service.create_request(
                    user_id="user-1", order_id=f"ORD-FREQ-{i}", refund_type="only_refund",
                    reason="r", amount=100.0,
                )
                await transition(service.repo, t, "APPROVING", operator="system_auto", reason="auto")
                await transition(service.repo, t, "APPROVED", operator="system_auto", reason="auto")
                await transition(service.repo, t, "REFUNDING", operator="system_auto", reason="auto")
                await transition(service.repo, t, "REFUNDED", operator="system_auto", reason="auto")

            with pytest.raises(RefundPrecheckError) as exc:
                await service.create_request(
                    user_id="user-1", order_id="ORD-FREQ-4", refund_type="only_refund",
                    reason="r", amount=100.0,
                )
            assert exc.value.code == 4220
            assert exc.value.rule == "frequency_over_limit"
            assert exc.value.review_required is True
        finally:
            for i in range(5):
                SEED_ORDERS.pop(f"ORD-FREQ-{i}", None)


@pytest.mark.spec("SP-REF-007")
class TestMoneyBoundary:
    async def test_ref_701_create_only_created(self, service: RefundService) -> None:
        """Agent/API 只能创建 CREATED 状态申请单。"""
        ticket = await service.create_request(
            user_id="user-1", order_id=ORD_OWNED, refund_type="only_refund",
            reason="不想要了", amount=199.0,
        )
        assert ticket.status == "CREATED"
        # 服务内不存在直达 REFUNDING 的公开方法：所有迁移需逐级走状态机
        from app.refund.state_machine import can_transition

        assert can_transition("CREATED", "REFUNDING") is False

    async def test_ref_701_auto_review_marks_operator(self, service: RefundService) -> None:
        """自动审核通过时操作人记为 system_auto（SP-REF-007）。"""
        ticket = await service.create_request(
            user_id="user-1", order_id=ORD_OWNED, refund_type="only_refund",
            reason="不想要了", amount=199.0,
        )
        approved = await service.auto_review(ticket.ticket_id, approve=True)
        assert approved.status == "APPROVED"
        logs = await service.repo.list_audit(ticket.ticket_id)
        assert any(log.to_status == "APPROVED" and log.operator == "system_auto" for log in logs)


@pytest.mark.spec("SP-REF-002")
class TestServiceBasics:
    async def test_ref_203_normal_create(self, service: RefundService) -> None:
        ticket = await service.create_request(
            user_id="user-1", order_id=ORD_OWNED, refund_type="only_refund",
            reason="不想要了", amount=199.0,
        )
        assert ticket.status == "CREATED"
        assert ticket.user_id == "user-1"
        assert ticket.refund_type == "only_refund"
        assert ticket.amount == 199.0

    async def test_ref_202_order_not_found(self, service: RefundService) -> None:
        with pytest.raises(RefundUnavailableError) as exc:
            await service.create_request(
                user_id="user-1", order_id="ORD-NOPE-000", refund_type="only_refund",
                reason="r", amount=1.0,
            )
        assert exc.value.code == 4041

    async def test_ref_201_ownership_rejected(self, service: RefundService) -> None:
        """他人订单 → 4030 且不泄露数据。"""
        with pytest.raises(RefundForbiddenError) as exc:
            await service.create_request(
                user_id="user-2", order_id=ORD_OWNED, refund_type="only_refund",
                reason="r", amount=199.0,
            )
        assert exc.value.code == 4030
