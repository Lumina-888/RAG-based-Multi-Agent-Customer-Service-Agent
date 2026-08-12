"""退款建单网关（SP-AGENT-003 工具依赖 → M6 RefundService 全链路）。

- `RefundGateway` 协议：`create_request(...)` 创建 CREATED 状态申请单
- `ServiceRefundGateway`：M6 实现——走 `RefundService` 完整预审
  （归属 4030 / 状态时效 4220 / 风控 / 幂等 4090 / 审计），
  M5 编排层 CONFIRM 节点确认后经此建单
- 资金边界（SP-REF-007）：本网关只创建 CREATED，不触发任何资金操作
"""
from __future__ import annotations

from typing import Any, Protocol

from app.refund.repo import MemoryTicketRepo, TicketRecord, TicketRepo
from app.refund.service import RefundService


class RefundGateway(Protocol):
    """建单协议：M6 真实服务实现与 M5 编排层对接。"""

    async def create_request(
        self,
        *,
        user_id: str,
        order_id: str,
        refund_type: str,
        reason: str,
        amount: float,
    ) -> TicketRecord: ...


class ServiceRefundGateway:
    """RefundService 包装（预审全链路）；默认内存 repo（CI/演示）。"""

    def __init__(self, repo: TicketRepo | None = None, service: RefundService | None = None) -> None:
        self._service = service or RefundService(repo=repo or MemoryTicketRepo())

    @property
    def tickets(self) -> list[TicketRecord]:
        """当前工单列表（内存 repo 兼容视图，供编排层/测试断言）。"""
        repo = self._service.repo
        store = getattr(repo, "tickets", None)
        if isinstance(store, dict):
            return list(store.values())
        return []

    async def create_request(
        self,
        *,
        user_id: str,
        order_id: str,
        refund_type: str,
        reason: str,
        amount: float,
    ) -> TicketRecord:
        return await self._service.create_request(
            user_id=user_id, order_id=order_id, refund_type=refund_type,
            reason=reason, amount=amount,
        )
