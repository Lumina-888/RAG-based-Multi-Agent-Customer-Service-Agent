"""SP-REF-006 状态机（纯规则 + 迁移执行）。

合法迁移：`CREATED→APPROVING→APPROVED→REFUNDING→REFUNDED`、
`APPROVING→REJECTED`、`REFUNDING→FAILED`；其余迁移抛 4091；
`REJECTED/REFUNDED/FAILED` 为终态；每次迁移写审计日志（SP-REF-008）。
"""
from __future__ import annotations

from typing import Any

#: 合法迁移表
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"APPROVING"},
    "APPROVING": {"APPROVED", "REJECTED"},
    "APPROVED": {"REFUNDING"},
    "REFUNDING": {"REFUNDED", "FAILED"},
}
TERMINAL_STATES = ("REJECTED", "REFUNDED", "FAILED")


class RefundStateMachineError(Exception):
    """非法状态迁移（统一错误码 4091）。"""

    code = 4091


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES


def all_transitions() -> dict[str, set[str]]:
    return {k: set(v) for k, v in ALLOWED_TRANSITIONS.items()}


async def transition(
    repo: Any,
    ticket: Any,
    to_status: str,
    *,
    operator: str,
    reason: str = "",
) -> Any:
    """执行迁移（校验 + 落库 + 审计）。非法迁移抛 4091（SP-REF-006）。"""
    from_status = ticket.status
    if not can_transition(from_status, to_status):
        raise RefundStateMachineError(
            f"非法状态迁移: {from_status} → {to_status}"
        )
    updated = await repo.update_status(ticket.ticket_id, to_status, reject_reason=reason)
    await repo.record_audit(
        ticket_id=ticket.ticket_id,
        operator=operator,
        action="transition",
        from_status=from_status,
        to_status=to_status,
        reason=reason,
    )
    return updated
