"""退款工单仓储（SP-REF）：内存实现（CI/演示）+ PostgreSQL 实现。

- 幂等（SP-REF-005）：进行中状态（CREATED/APPROVING/APPROVED/REFUNDING）同键唯一；
  PG 侧用**部分唯一索引**兜底并发（`uq_refund_active ... WHERE status 进行中`），
  唯一冲突 → `ActiveTicketConflict`（服务层映射 4090 而非 5000）
- 审计（SP-REF-008）：`refund_audit_log` 全生命周期留痕
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import delete, func, select, text
from sqlalchemy import Index as SAIndex

from app.models.db import make_sessionmaker

#: 进行中状态（幂等键生效范围，SP-REF-005）
ACTIVE_STATUSES = ("CREATED", "APPROVING", "APPROVED", "REFUNDING")
TERMINAL_STATUSES = ("REJECTED", "REFUNDED", "FAILED")


@dataclass
class TicketRecord:
    """退款申请单（SP-REF-001~006）。"""

    ticket_id: str
    user_id: str
    order_id: str
    refund_type: str
    reason: str
    amount: float
    status: str = "CREATED"
    created_by: str = ""
    reject_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "order_id": self.order_id,
            "refund_type": self.refund_type,
            "amount": self.amount,
            "reason": self.reason,
            "status": self.status,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class AuditRecord:
    """审计日志（SP-REF-008）：{ticket_id, operator, action, from, to, reason, ts}。"""

    id: int
    ticket_id: str
    operator: str
    action: str
    from_status: str | None
    to_status: str | None
    reason: str
    ts: datetime

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "operator": self.operator,
            "action": self.action,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "reason": self.reason,
            "ts": self.ts.isoformat(),
        }


class ActiveTicketConflict(Exception):
    """幂等冲突（进行中同键已存在）：携带已存在单号（→ 4090）。"""

    def __init__(self, existing_ticket_id: str) -> None:
        self.existing_ticket_id = existing_ticket_id
        super().__init__(f"存在进行中的退款申请: {existing_ticket_id}")


class TicketRepo(Protocol):
    """工单仓储协议：内存与 PG 实现同一接口。"""

    async def create_ticket(
        self, *, user_id: str, order_id: str, refund_type: str,
        reason: str, amount: float, created_by: str,
    ) -> TicketRecord: ...

    async def get_ticket(self, ticket_id: str) -> TicketRecord | None: ...

    async def list_tickets(self, status: str | None = None) -> list[TicketRecord]: ...

    async def count_refunds_since(self, user_id: str, since: datetime) -> int: ...

    async def update_status(
        self, ticket_id: str, status: str, reject_reason: str | None = None
    ) -> TicketRecord: ...

    async def record_audit(
        self, *, ticket_id: str, operator: str, action: str,
        from_status: str | None, to_status: str | None, reason: str,
    ) -> AuditRecord: ...

    async def list_audit(self, ticket_id: str) -> list[AuditRecord]: ...

    async def aclose(self) -> None: ...


class MemoryTicketRepo:
    """内存实现：`asyncio.Lock` 模拟 DB 部分唯一索引的并发安全（T-REF-502）。"""

    def __init__(self) -> None:
        self.tickets: dict[str, TicketRecord] = {}
        self.audit: list[AuditRecord] = []
        self._seq = 0
        self._lock = asyncio.Lock()

    def _ticket_id(self) -> str:
        self._seq += 1
        return f"TK-{self._seq:06d}"

    async def create_ticket(
        self, *, user_id: str, order_id: str, refund_type: str,
        reason: str, amount: float, created_by: str,
    ) -> TicketRecord:
        async with self._lock:  # 并发双请求只建一单（模拟部分唯一索引）
            existing = next(
                (t for t in self.tickets.values()
                 if t.user_id == user_id and t.order_id == order_id
                 and t.refund_type == refund_type and t.status in ACTIVE_STATUSES),
                None,
            )
            if existing is not None:
                raise ActiveTicketConflict(existing.ticket_id)
            now = datetime.now(timezone.utc)
            ticket = TicketRecord(
                ticket_id=self._ticket_id(), user_id=user_id, order_id=order_id,
                refund_type=refund_type, reason=reason, amount=amount,
                status="CREATED", created_by=created_by,
                created_at=now, updated_at=now,
            )
            self.tickets[ticket.ticket_id] = ticket
            return ticket

    async def get_ticket(self, ticket_id: str) -> TicketRecord | None:
        return self.tickets.get(ticket_id)

    async def list_tickets(self, status: str | None = None) -> list[TicketRecord]:
        items = list(self.tickets.values())
        if status:
            items = [t for t in items if t.status == status]
        return sorted(items, key=lambda t: t.created_at)

    async def count_refunds_since(self, user_id: str, since: datetime) -> int:
        return sum(
            1 for t in self.tickets.values()
            if t.user_id == user_id and t.status == "REFUNDED" and t.created_at >= since
        )

    async def update_status(
        self, ticket_id: str, status: str, reject_reason: str | None = None
    ) -> TicketRecord:
        ticket = self.tickets[ticket_id]
        ticket.status = status
        ticket.reject_reason = reject_reason
        ticket.updated_at = datetime.now(timezone.utc)
        return ticket

    async def record_audit(
        self, *, ticket_id: str, operator: str, action: str,
        from_status: str | None, to_status: str | None, reason: str,
    ) -> AuditRecord:
        self._seq += 1
        record = AuditRecord(
            id=self._seq, ticket_id=ticket_id, operator=operator, action=action,
            from_status=from_status, to_status=to_status, reason=reason,
            ts=datetime.now(timezone.utc),
        )
        self.audit.append(record)
        return record

    async def list_audit(self, ticket_id: str) -> list[AuditRecord]:
        return [r for r in self.audit if r.ticket_id == ticket_id]

    async def aclose(self) -> None:
        pass


class PostgresTicketRepo:
    """PostgreSQL 实现（tickets / refund_audit_log 表，设计文档 §7.4）。

    - 部分唯一索引 `uq_refund_active`：仅约束进行中状态（SP-REF-005），
      终态后同键允许重新申请
    - 并发唯一冲突（IntegrityError）→ ActiveTicketConflict（4090 而非 5000）
    """

    def __init__(self, dsn: str) -> None:
        self._engine = None
        self._dsn = dsn

    async def _sessionmaker(self):
        from app.models.db import init_db

        if self._engine is None:
            self._engine = await init_db(self._dsn)
        return make_sessionmaker(self._engine)

    async def create_ticket(
        self, *, user_id: str, order_id: str, refund_type: str,
        reason: str, amount: float, created_by: str,
    ) -> TicketRecord:
        from sqlalchemy.exc import IntegrityError

        from app.models.db import TicketRow

        sm = await self._sessionmaker()
        async with sm() as session:
            ticket_id = f"TK-{uuid.uuid4().hex[:12].upper()}"
            row = TicketRow(
                id=ticket_id, user_id=user_id, order_id=order_id,
                refund_type=refund_type, amount=amount, reason=reason,
                status="CREATED", created_by=created_by,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self._find_active(user_id, order_id, refund_type)
                raise ActiveTicketConflict(existing.ticket_id if existing else "unknown")
            return await self.get_ticket(ticket_id)  # type: ignore[return-value]

    async def _find_active(
        self, user_id: str, order_id: str, refund_type: str
    ) -> TicketRecord | None:
        from app.models.db import TicketRow

        sm = await self._sessionmaker()
        async with sm() as session:
            row = await session.execute(
                select(TicketRow).where(
                    TicketRow.user_id == user_id,
                    TicketRow.order_id == order_id,
                    TicketRow.refund_type == refund_type,
                    TicketRow.status.in_(ACTIVE_STATUSES),
                )
            )
            return _row_to_ticket(row.scalar_one_or_none())

    async def get_ticket(self, ticket_id: str) -> TicketRecord | None:
        from app.models.db import TicketRow

        sm = await self._sessionmaker()
        async with sm() as session:
            row = await session.get(TicketRow, ticket_id)
            return _row_to_ticket(row)

    async def list_tickets(self, status: str | None = None) -> list[TicketRecord]:
        from app.models.db import TicketRow

        sm = await self._sessionmaker()
        async with sm() as session:
            stmt = select(TicketRow).order_by(TicketRow.created_at.asc())
            if status:
                stmt = stmt.where(TicketRow.status == status)
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_ticket(r) for r in rows]

    async def count_refunds_since(self, user_id: str, since: datetime) -> int:
        from app.models.db import TicketRow

        sm = await self._sessionmaker()
        async with sm() as session:
            count = await session.execute(
                select(func.count())
                .select_from(TicketRow)
                .where(
                    TicketRow.user_id == user_id,
                    TicketRow.status == "REFUNDED",
                    TicketRow.created_at >= since,
                )
            )
            return int(count.scalar_one())

    async def update_status(
        self, ticket_id: str, status: str, reject_reason: str | None = None
    ) -> TicketRecord:
        from app.models.db import TicketRow

        sm = await self._sessionmaker()
        async with sm() as session:
            row = await session.get(TicketRow, ticket_id)
            if row is None:
                raise KeyError(f"工单不存在: {ticket_id}")
            row.status = status
            row.reject_reason = reject_reason
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return _row_to_ticket(row)

    async def record_audit(
        self, *, ticket_id: str, operator: str, action: str,
        from_status: str | None, to_status: str | None, reason: str,
    ) -> AuditRecord:
        from app.models.db import RefundAuditLogRow

        sm = await self._sessionmaker()
        async with sm() as session:
            row = RefundAuditLogRow(
                ticket_id=ticket_id, operator=operator, action=action,
                from_status=from_status, to_status=to_status, reason=reason,
            )
            session.add(row)
            await session.commit()
            return AuditRecord(
                id=row.id, ticket_id=ticket_id, operator=operator, action=action,
                from_status=from_status, to_status=to_status, reason=reason, ts=row.created_at,
            )

    async def list_audit(self, ticket_id: str) -> list[AuditRecord]:
        from app.models.db import RefundAuditLogRow

        sm = await self._sessionmaker()
        async with sm() as session:
            rows = (
                await session.execute(
                    select(RefundAuditLogRow)
                    .where(RefundAuditLogRow.ticket_id == ticket_id)
                    .order_by(RefundAuditLogRow.id.asc())
                )
            ).scalars().all()
            return [
                AuditRecord(
                    id=r.id, ticket_id=r.ticket_id, operator=r.operator, action=r.action,
                    from_status=r.from_status, to_status=r.to_status, reason=r.reason,
                    ts=r.created_at,
                )
                for r in rows
            ]

    async def aclose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _row_to_ticket(row: Any) -> TicketRecord | None:
    if row is None:
        return None
    return TicketRecord(
        ticket_id=row.id, user_id=row.user_id, order_id=row.order_id,
        refund_type=row.refund_type, reason=row.reason, amount=row.amount,
        status=row.status, created_by=row.created_by, reject_reason=row.reject_reason,
        created_at=row.created_at, updated_at=row.updated_at,
    )
