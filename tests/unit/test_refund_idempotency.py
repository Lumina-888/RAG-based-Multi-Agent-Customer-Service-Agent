"""SP-REF-005 幂等防重：T-REF-501 ~ 503。

- T-REF-501 存在进行中申请单（CREATED/APPROVING/APPROVED/REFUNDING）→ 4090 + existing_ticket_id
- T-REF-502 并发双请求只建一单（asyncio 并发 + 内存唯一约束兜底）
- T-REF-503 终态（REJECTED/REFUNDED/FAILED）后同键允许重新申请
"""
from __future__ import annotations

import asyncio

import pytest

from app.refund.repo import MemoryTicketRepo
from app.refund.service import RefundService
from app.refund.state_machine import RefundStateMachineError, transition

ORD = "ORD-20260811-001"


@pytest.fixture
def repo() -> MemoryTicketRepo:
    return MemoryTicketRepo()


@pytest.fixture
def service(repo: MemoryTicketRepo) -> RefundService:
    return RefundService(repo=repo)


@pytest.mark.spec("SP-REF-005")
class TestRefundIdempotency:
    async def test_ref_501_duplicate_rejected(self, service: RefundService) -> None:
        t1 = await service.create_request(
            user_id="user-1", order_id=ORD, refund_type="only_refund",
            reason="不想要了", amount=199.0,
        )
        assert t1.status == "CREATED"

        with pytest.raises(Exception) as exc:
            await service.create_request(
                user_id="user-1", order_id=ORD, refund_type="only_refund",
                reason="再来一次", amount=199.0,
            )
        from app.refund.service import RefundConflictError

        assert isinstance(exc.value, RefundConflictError)
        assert exc.value.code == 4090
        assert exc.value.existing_ticket_id == t1.ticket_id  # 携带已存在单号

    async def test_ref_502_concurrent_only_one_ticket(self, service: RefundService) -> None:
        """并发双请求只建一单（内存唯一约束模拟 DB 部分唯一索引兜底）。"""
        results = await asyncio.gather(
            *[
                service.create_request(
                    user_id="user-1", order_id=ORD, refund_type="only_refund",
                    reason="并发", amount=199.0,
                )
                for _ in range(2)
            ],
            return_exceptions=True,
        )
        ok = [r for r in results if not isinstance(r, Exception)]
        conflicts = [r for r in results if isinstance(r, Exception)]
        assert len(ok) == 1  # 只建一单
        assert len(conflicts) == 1
        assert getattr(conflicts[0], "code", None) == 4090  # 唯一冲突 → 4090 而非 5000

    async def test_ref_503_reapply_after_terminal(self, service: RefundService, repo: MemoryTicketRepo) -> None:
        t1 = await service.create_request(
            user_id="user-1", order_id=ORD, refund_type="only_refund",
            reason="第一次", amount=199.0,
        )
        # 驳回（终态 REJECTED）
        await transition(repo, t1, "APPROVING", operator="system_auto", reason="审核")
        await transition(repo, t1, "REJECTED", operator="agent-01", reason="不符合政策")

        # 终态后同键允许重新申请
        t2 = await service.create_request(
            user_id="user-1", order_id=ORD, refund_type="only_refund",
            reason="重新申请", amount=199.0,
        )
        assert t2.status == "CREATED"
        assert t2.ticket_id != t1.ticket_id

    async def test_ref_501_active_blocks_different_type(self, service: RefundService) -> None:
        """进行中（不同 refund_type）不冲突：幂等键含 refund_type。"""
        await service.create_request(
            user_id="user-1", order_id=ORD, refund_type="only_refund",
            reason="r", amount=199.0,
        )
        t2 = await service.create_request(
            user_id="user-1", order_id=ORD, refund_type="return_refund",
            reason="质量问题", amount=199.0,
        )
        assert t2.status == "CREATED"
