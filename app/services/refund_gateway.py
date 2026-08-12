"""退款建单网关（SP-AGENT-003 工具依赖）。

- `RefundGateway` 协议：`create_request(...)` 创建 CREATED 状态申请单
- `MemoryRefundGateway`：M5 演示实现（M6 交付 PostgreSQL 全量预审/幂等/状态机后替换）
- 注意：本接口只创建申请单，**不触发任何资金操作**（SP-REF-007 口径）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


@dataclass
class TicketRecord:
    """退款申请单（M6 交付后对齐 SP-REF-001~006 状态机）。"""

    ticket_id: str
    user_id: str
    order_id: str
    refund_type: str
    reason: str
    amount: float
    status: str = "CREATED"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RefundGateway(Protocol):
    """建单协议：M6 的 PostgreSQL 实现与 M5 内存实现同接口。"""

    async def create_request(
        self,
        *,
        user_id: str,
        order_id: str,
        refund_type: str,
        reason: str,
        amount: float,
    ) -> TicketRecord: ...


class MemoryRefundGateway:
    """内存实现（CI / 演示）：建单即 CREATED，不校验归属/时效（M6 交付完整预审）。"""

    def __init__(self) -> None:
        self.tickets: list[TicketRecord] = []
        self._seq = 0

    async def create_request(
        self,
        *,
        user_id: str,
        order_id: str,
        refund_type: str,
        reason: str,
        amount: float,
    ) -> TicketRecord:
        self._seq += 1
        ticket = TicketRecord(
            ticket_id=f"TK-{self._seq:06d}",
            user_id=user_id,
            order_id=order_id,
            refund_type=refund_type,
            reason=reason,
            amount=amount,
        )
        self.tickets.append(ticket)
        return ticket
