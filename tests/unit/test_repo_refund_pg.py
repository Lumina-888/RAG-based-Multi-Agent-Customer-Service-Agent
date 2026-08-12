"""SP-REF 仓储层（SQLite 替身跑 SQLAlchemy 代码路径，零外部服务）。

覆盖 PostgresTicketRepo 的建单/查询/流转/审计/频次统计；
部分唯一索引的并发冲突兜底（SP-REF-005）需真实 PG（集成测试）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.refund.repo import (
    ACTIVE_STATUSES,
    PostgresTicketRepo,
    TicketRecord,
)
from app.refund.state_machine import transition


@pytest.fixture
def repo(tmp_path) -> PostgresTicketRepo:
    return PostgresTicketRepo(f"sqlite+aiosqlite:///{tmp_path / 'refund.db'}")


@pytest.mark.spec("SP-REF-005")
@pytest.mark.spec("SP-REF-006")
class TestPostgresTicketRepo:
    async def test_create_and_get(self, repo: PostgresTicketRepo) -> None:
        ticket = await repo.create_ticket(
            user_id="u1", order_id="ORD-1", refund_type="only_refund",
            reason="r", amount=10.0, created_by="u1",
        )
        assert ticket.status == "CREATED" and ticket.ticket_id
        got = await repo.get_ticket(ticket.ticket_id)
        assert got is not None and got.amount == 10.0 and got.user_id == "u1"
        assert await repo.get_ticket("TK-NOPE") is None

    async def test_list_by_status(self, repo: PostgresTicketRepo) -> None:
        t1 = await repo.create_ticket(
            user_id="u1", order_id="ORD-1", refund_type="only_refund",
            reason="r", amount=10.0, created_by="u1",
        )
        t2 = await repo.create_ticket(
            user_id="u1", order_id="ORD-2", refund_type="only_refund",
            reason="r", amount=10.0, created_by="u1",
        )
        await transition(repo, t2, "APPROVING", operator="system_auto", reason="审核")

        created = await repo.list_tickets(status="CREATED")
        assert [t.ticket_id for t in created] == [t1.ticket_id]
        assert len(await repo.list_tickets()) == 2

    async def test_update_status_and_count_refunds(self, repo: PostgresTicketRepo) -> None:
        ticket = await repo.create_ticket(
            user_id="u1", order_id="ORD-1", refund_type="only_refund",
            reason="r", amount=10.0, created_by="u1",
        )
        updated = await transition(repo, ticket, "APPROVING", operator="system_auto", reason="审核")
        updated = await transition(repo, updated, "APPROVED", operator="system_auto", reason="通过")
        updated = await transition(repo, updated, "REFUNDING", operator="system_auto", reason="打款")
        updated = await transition(repo, updated, "REFUNDED", operator="system_auto", reason="完成")
        assert updated.status == "REFUNDED"

        since = datetime.now(timezone.utc) - timedelta(days=30)
        assert await repo.count_refunds_since("u1", since) == 1  # 30 天内退款次数
        assert await repo.count_refunds_since("u2", since) == 0

    async def test_audit_roundtrip(self, repo: PostgresTicketRepo) -> None:
        ticket = await repo.create_ticket(
            user_id="u1", order_id="ORD-1", refund_type="only_refund",
            reason="r", amount=10.0, created_by="u1",
        )
        await repo.record_audit(
            ticket_id=ticket.ticket_id, operator="u1", action="create",
            from_status=None, to_status="CREATED", reason="r",
        )
        logs = await repo.list_audit(ticket.ticket_id)
        assert len(logs) == 1
        assert logs[0].action == "create" and logs[0].to_status == "CREATED"
        assert logs[0].ts is not None
        assert await repo.list_audit("TK-OTHER") == []
