"""SP-REF 退款 API：建单 + 工单管理/审计/受限流转。

- `POST /api/v1/refund-requests`：建单（SP-REF-001/002，全量预审；4220 带 rule）
- `GET /api/v1/tickets?status=`：工单列表（SP-REF-008）
- `GET /api/v1/tickets/{id}/audit`：审计回溯（全生命周期）
- `POST /api/v1/tickets/{id}/transition`：仅模拟坐席/内部审核服务的**受限迁移**
  （APPROVING→APPROVED/REJECTED）；任何直达 REFUNDING 的尝试 → 4091
  （SP-REF-007：公开 API 无法绕过审核直接打款）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.responses import err, ok
from app.refund.repo import PostgresTicketRepo
from app.refund.service import RefundError, RefundService
from app.refund.state_machine import RefundStateMachineError
from app.refund.validate import RefundRequest as RefundRequestModel

logger = logging.getLogger("app.api.refund")

router = APIRouter(prefix="/api/v1", tags=["refund"])

#: 公开 API 允许的受限迁移（SP-REF-008：前端工单页状态流转）
LIMITED_TRANSITIONS = {("APPROVING", "APPROVED"), ("APPROVING", "REJECTED")}


class TransitionRequest(BaseModel):
    status: str
    operator: str = "agent"
    reason: str = ""


@lru_cache(maxsize=1)
def _build_service() -> RefundService:
    settings = get_settings()
    return RefundService(repo=PostgresTicketRepo(settings.postgres_dsn))


def get_refund_service() -> RefundService:
    """退款服务依赖（测试可 dependency_overrides 注入内存实现）。"""
    return _build_service()


def _user_id(request: Request) -> str | None:
    user_id = request.headers.get("X-User-Id")
    return user_id if user_id and user_id.strip() else None


def _refund_error(exc: RefundError):
    return err(exc.code, exc.http_status, str(exc), data=exc.data)


@router.post("/refund-requests")
async def create_refund_request(
    req: RefundRequestModel,
    request: Request,
    service: RefundService = Depends(get_refund_service),
) -> dict:
    user_id = _user_id(request)
    if user_id is None:
        return err(4010, 401, "未登录或会话无效")  # SP-REF-002
    try:
        ticket = await service.create_request(
            user_id=user_id,
            order_id=req.order_id,
            refund_type=req.refund_type,
            reason=req.reason,
            amount=req.amount or 0.0,
        )
    except RefundError as exc:
        return _refund_error(exc)
    return ok({"ticket": ticket.as_dict()})


@router.get("/tickets")
async def list_tickets(
    status: str | None = None,
    service: RefundService = Depends(get_refund_service),
) -> dict:
    tickets = await service.repo.list_tickets(status=status)
    return ok({"count": len(tickets), "tickets": [t.as_dict() for t in tickets]})


@router.get("/tickets/{ticket_id}/audit")
async def ticket_audit(
    ticket_id: str,
    service: RefundService = Depends(get_refund_service),
) -> dict:
    if await service.repo.get_ticket(ticket_id) is None:
        return err(4041, 404, "工单不存在")
    logs = await service.repo.list_audit(ticket_id)
    return ok({"ticket_id": ticket_id, "audit_logs": [log.as_dict() for log in logs]})


@router.post("/tickets/{ticket_id}/transition")
async def ticket_transition(
    ticket_id: str,
    req: TransitionRequest,
    service: RefundService = Depends(get_refund_service),
) -> dict:
    ticket = await service.repo.get_ticket(ticket_id)
    if ticket is None:
        return err(4041, 404, "工单不存在")
    # 受限迁移（SP-REF-007/008）：公开 API 无法绕过审核直达 REFUNDING
    if (ticket.status, req.status) not in LIMITED_TRANSITIONS:
        return err(4091, 409, f"受限迁移不允许: {ticket.status} → {req.status}（仅审核后可流转）")
    try:
        updated = await service.transition(
            ticket_id, req.status, operator=req.operator, reason=req.reason
        )
    except RefundStateMachineError as exc:
        return err(4091, 409, str(exc))
    return ok({"ticket": updated.as_dict()})
