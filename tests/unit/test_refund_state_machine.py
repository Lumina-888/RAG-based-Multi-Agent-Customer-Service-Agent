"""SP-REF-006 状态机：T-REF-601 ~ 604。

- T-REF-601 合法链：CREATED→APPROVING→APPROVED→REFUNDING→REFUNDED（+REJECTED/FAILED 分支）
- T-REF-602 非法迁移抛 4091
- T-REF-603 终态（REJECTED/REFUNDED/FAILED）不可再转
- T-REF-604 每次迁移写审计日志（记录 from/to/operator/action/ts）
"""
from __future__ import annotations

import pytest

from app.refund.state_machine import (
    RefundStateMachineError,
    all_transitions,
    can_transition,
    is_terminal,
    transition,
)

#: 带审计内存库的迁移执行器（验证 T-REF-604）
from app.refund.repo import MemoryTicketRepo


@pytest.mark.spec("SP-REF-006")
class TestRefundStateMachine:
    def test_ref_601_legal_chain(self) -> None:
        chain = ["CREATED", "APPROVING", "APPROVED", "REFUNDING", "REFUNDED"]
        for frm, to in zip(chain, chain[1:]):
            assert can_transition(frm, to) is True
        assert can_transition("APPROVING", "REJECTED") is True
        assert can_transition("REFUNDING", "FAILED") is True

    async def test_ref_602_illegal_transition_4091(self) -> None:
        repo = MemoryTicketRepo()
        ticket = await repo.create_ticket(
            user_id="u1", order_id="ORD-1", refund_type="only_refund",
            reason="r", amount=10.0, created_by="u1",
        )
        with pytest.raises(RefundStateMachineError) as exc:
            await transition(repo, ticket, "REFUNDED", operator="u1", reason="跳过审核")
        assert exc.value.code == 4091  # CREATED→REFUNDED 非法（不得绕过审核）

    def test_ref_603_terminal_states_frozen(self) -> None:
        for terminal in ("REJECTED", "REFUNDED", "FAILED"):
            assert is_terminal(terminal) is True
            assert can_transition(terminal, "CREATED") is False
            assert can_transition(terminal, "APPROVING") is False

    async def test_ref_604_audit_written(self) -> None:
        repo = MemoryTicketRepo()
        ticket = await repo.create_ticket(
            user_id="u1", order_id="ORD-1", refund_type="only_refund",
            reason="r", amount=10.0, created_by="u1",
        )
        # 建单审计（服务层 create_request 会记录；此处镜像该行为）
        await repo.record_audit(
            ticket_id=ticket.ticket_id, operator="u1", action="create",
            from_status=None, to_status="CREATED", reason="r",
        )
        await transition(repo, ticket, "APPROVING", operator="system_auto", reason="自动审核开始")
        await transition(repo, ticket, "APPROVED", operator="system_auto", reason="审核通过")
        await transition(repo, ticket, "REFUNDING", operator="agent-01", reason="打款")

        logs = await repo.list_audit(ticket.ticket_id)
        # 建单（create）+ 3 次迁移
        assert len(logs) == 4
        assert logs[0].action == "create" and logs[0].to_status == "CREATED"
        assert (logs[1].from_status, logs[1].to_status) == ("CREATED", "APPROVING")
        assert logs[2].to_status == "APPROVED" and logs[2].operator == "system_auto"
        assert logs[3].to_status == "REFUNDING" and logs[3].operator == "agent-01"
        assert all(log.ts for log in logs)

    def test_ref_601_all_transitions_table(self) -> None:
        assert all_transitions() == {
            "CREATED": {"APPROVING"},
            "APPROVING": {"APPROVED", "REJECTED"},
            "APPROVED": {"REFUNDING"},
            "REFUNDING": {"REFUNDED", "FAILED"},
        }
