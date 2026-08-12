"""SP-REF 退款服务（企业规范核心）：入参 → 归属 → 预审 → 风控 → 幂等 → 建单 CREATED。

- SP-REF-002 身份与归属：未登录 4010（API 层）、他人订单 4030、订单不存在 4041
- SP-REF-003/004 预审与风控：规则引擎（rules.py，非 LLM）；4220 带 rule/review_required
- SP-REF-005 幂等：进行中同键 → 4090 + existing_ticket_id（DB 部分唯一索引兜底并发）
- SP-REF-007 资金边界：本服务只创建 CREATED；REFUNDING 仅内部审核（auto_review）触发，
  自动审核操作人记 system_auto
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.refund.repo import (
    ACTIVE_STATUSES,
    ActiveTicketConflict,
    TicketRepo,
)
from app.refund.rules import FREQUENCY_LIMIT, RISK_WINDOW_DAYS, amount_risk, frequency_risk, precheck
from app.refund.state_machine import transition
from app.refund.validate import RefundRequest, validate_refund_request
from app.services.erp_sim import get_order


class RefundError(Exception):
    """退款业务错误（统一错误码映射，SP-API-GEN）。"""

    def __init__(
        self,
        message: str,
        code: int,
        http_status: int = 400,
        *,
        data: dict | None = None,
    ) -> None:
        self.code = code
        self.http_status = http_status
        self.data = data
        super().__init__(message)


class RefundValidationError(RefundError):
    """参数校验失败（4001）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, 4001, 400)


class RefundForbiddenError(RefundError):
    """归属不符（4030，不泄露数据）。"""

    def __init__(self, message: str = "无权对该订单发起退款申请") -> None:
        super().__init__(message, 4030, 403)


class RefundUnavailableError(RefundError):
    """订单/工单不存在（4041）。"""

    def __init__(self, message: str = "订单不存在") -> None:
        super().__init__(message, 4041, 404)


class RefundPrecheckError(RefundError):
    """预审/风控不通过（4220，data 带 rule/reason/review_required）。"""

    def __init__(
        self,
        message: str,
        *,
        rule: str,
        review_required: bool = False,
        transfer: bool = False,
    ) -> None:
        super().__init__(
            message, 4220, 422,
            data={"rule": rule, "reason": message,
                  "review_required": review_required, "transfer": transfer},
        )
        self.rule = rule
        self.review_required = review_required
        self.transfer = transfer


class RefundConflictError(RefundError):
    """幂等冲突（4090 + existing_ticket_id）。"""

    def __init__(self, existing_ticket_id: str) -> None:
        super().__init__(
            "存在进行中的退款申请（幂等冲突）", 4090, 409,
            data={"existing_ticket_id": existing_ticket_id},
        )
        self.existing_ticket_id = existing_ticket_id


class RefundService:
    """退款服务：建单 / 内部审核（模拟人工）。"""

    def __init__(self, repo: TicketRepo) -> None:
        self.repo = repo

    async def create_request(
        self,
        *,
        user_id: str,
        order_id: str,
        refund_type: str,
        reason: str,
        amount: float,
    ):
        """建单全链路：校验 → 归属 → 预审 → 风控 → 幂等 → 建单 CREATED。"""
        # 1) 入参（SP-REF-001，4001）
        req = RefundRequest(order_id=order_id, refund_type=refund_type,
                            reason=reason, amount=amount)
        issue = validate_refund_request(req)
        if issue is not None:
            raise RefundValidationError(issue.message)

        # 2) 订单存在与归属（SP-REF-002）
        order = get_order(order_id)
        if order is None:
            raise RefundUnavailableError("订单不存在")
        if order.user_id != user_id:
            raise RefundForbiddenError()  # 4030，不泄露任何订单数据

        # 3) 金额契约（SP-REF-001：amount ≤ 订单实付金额）
        issue = validate_refund_request(req, order_amount=order.amount)
        if issue is not None:
            raise RefundValidationError(issue.message)

        # 4) 状态与时效预审（SP-REF-003，4220 + rule）
        result = precheck(
            status=order.status,
            received_days=order.received_days,
            refund_type=refund_type,
            amount=amount,
            order_amount=order.amount,
            reason=reason,
        )
        if not result.passed:
            raise RefundPrecheckError(
                result.reason, rule=result.rule, transfer=result.transfer
            )

        # 5) 风控（SP-REF-004，4220 + review_required）
        risk = amount_risk(amount)
        if risk is None:
            since = datetime.now(timezone.utc) - timedelta(days=RISK_WINDOW_DAYS)
            refund_count = await self.repo.count_refunds_since(user_id, since)
            risk = frequency_risk(refund_count)
        if risk is not None:
            raise RefundPrecheckError(risk.reason, rule=risk.rule, review_required=True)

        # 6) 幂等防重（SP-REF-005，4090；DB 部分唯一索引兜底并发）
        try:
            ticket = await self.repo.create_ticket(
                user_id=user_id, order_id=order_id, refund_type=refund_type,
                reason=reason, amount=amount, created_by=user_id,
            )
        except ActiveTicketConflict as exc:
            raise RefundConflictError(exc.existing_ticket_id) from exc

        # 7) 建单审计（SP-REF-008）
        await self.repo.record_audit(
            ticket_id=ticket.ticket_id, operator=user_id, action="create",
            from_status=None, to_status="CREATED", reason=reason,
        )
        return ticket

    async def auto_review(self, ticket_id: str, approve: bool):
        """内部审核服务（模拟人工，SP-REF-007）：操作人 system_auto。

        通过：CREATED→APPROVING→APPROVED（REFUNDING 打款为独立环节，仍由内部服务触发）。
        """
        ticket = await self.repo.get_ticket(ticket_id)
        if ticket is None:
            raise RefundUnavailableError("工单不存在")
        ticket = await transition(
            self.repo, ticket, "APPROVING", operator="system_auto", reason="自动审核开始"
        )
        if approve:
            return await transition(
                self.repo, ticket, "APPROVED", operator="system_auto", reason="自动审核通过"
            )
        return await transition(
            self.repo, ticket, "REJECTED", operator="system_auto", reason="自动审核驳回"
        )

    async def transition(self, ticket_id: str, to_status: str, *, operator: str, reason: str = ""):
        """受限迁移入口（模拟坐席/内部审核服务，SP-REF-008）。

        公开 API 仅允许受限迁移（APPROVING→APPROVED/REJECTED）；其余迁移
        仅内部服务方法可触发（SP-REF-007：无任何接口允许 AI 直接触发打款）。
        """
        ticket = await self.repo.get_ticket(ticket_id)
        if ticket is None:
            raise RefundUnavailableError("工单不存在")
        return await transition(self.repo, ticket, to_status, operator=operator, reason=reason)
