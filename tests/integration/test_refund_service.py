"""SP-REF-002 身份与归属校验（需真实 PostgreSQL）：T-REF-201 ~ 203。

- T-REF-201 归属不符（他人订单）→ 4030，不泄露数据
- T-REF-202 订单不存在 → 4041
- T-REF-203 正常通过（建单 CREATED + 审计留痕）
"""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.refund.repo import PostgresTicketRepo
from app.refund.service import (
    RefundForbiddenError,
    RefundService,
    RefundUnavailableError,
)

ORD_OWNED = "ORD-20260811-001"  # user-1，received 3 天，199 元


@pytest.fixture
async def pg_ok() -> bool:
    settings = get_settings()
    repo = PostgresTicketRepo(settings.postgres_dsn)
    try:
        await repo.get_ticket("__probe__")
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    try:
        await repo.aclose()
    except Exception:  # noqa: BLE001
        pass
    if not ok:
        pytest.skip("本机 PostgreSQL 不可用（需 PostgreSQL 16，docker compose 见 M9）")
    return ok


@pytest.fixture
async def service(pg_ok: bool) -> RefundService:
    settings = get_settings()
    repo = PostgresTicketRepo(settings.postgres_dsn)
    yield RefundService(repo=repo)
    # 清理测试工单（订单级联删除审计）
    from app.models.db import Base, create_async_engine

    engine = create_async_engine(settings.postgres_dsn)
    from sqlalchemy import delete, text as sa_text

    async with engine.begin() as conn:
        await conn.execute(sa_text("DELETE FROM tickets WHERE user_id = 'user-1' AND order_id = 'ORD-20260811-001'"))
    await engine.dispose()
    await repo.aclose()


@pytest.mark.spec("SP-REF-002")
@pytest.mark.integration
class TestRefundServicePG:
    async def test_ref_203_normal_create(self, service: RefundService) -> None:
        ticket = await service.create_request(
            user_id="user-1", order_id=ORD_OWNED, refund_type="only_refund",
            reason="不想要了", amount=199.0,
        )
        assert ticket.status == "CREATED"
        assert ticket.amount == 199.0
        # 审计留痕（SP-REF-008）
        logs = await service.repo.list_audit(ticket.ticket_id)
        assert len(logs) == 1 and logs[0].action == "create"

    async def test_ref_201_ownership_rejected(self, service: RefundService) -> None:
        with pytest.raises(RefundForbiddenError) as exc:
            await service.create_request(
                user_id="user-2", order_id=ORD_OWNED, refund_type="only_refund",
                reason="r", amount=199.0,
            )
        assert exc.value.code == 4030

    async def test_ref_202_order_not_found(self, service: RefundService) -> None:
        with pytest.raises(RefundUnavailableError) as exc:
            await service.create_request(
                user_id="user-1", order_id="ORD-NOPE-000", refund_type="only_refund",
                reason="r", amount=1.0,
            )
        assert exc.value.code == 4041
