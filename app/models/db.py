"""SQLAlchemy 模型与引擎（sessions / messages，设计文档 §7.4）。

- `sessions`：会话元数据（归属 user_id 供 4030 校验）
- `messages`：消息历史持久保留（PG），不受 Redis 短期上下文 TTL 影响（SP-CHAT-001）
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class TicketRow(Base):
    """退款申请单（SP-REF）：部分唯一索引 uq_refund_active 兜底幂等（SP-REF-005）。"""

    __tablename__ = "tickets"
    __table_args__ = (
        Index(
            "uq_refund_active",
            "user_id", "order_id", "refund_type",
            unique=True,
            postgresql_where=text(
                "status IN ('CREATED', 'APPROVING', 'APPROVED', 'REFUNDING')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # ticket_id
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    refund_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EvalRunRow(Base):
    """评测运行记录（SP-EVAL-002）：eval_runs 表，评测看板数据源（SP-FE-003）。"""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(32), index=True)  # intent/retrieval/ragas/ablation
    name: Mapped[str] = mapped_column(String(128))  # 策略/批次名，如 E3_rrf
    metrics: Mapped[dict] = mapped_column(JSON)  # 指标字典（recall@5/mrr/... 或消融对比表）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefundAuditLogRow(Base):
    """退款审计日志（SP-REF-008）：全生命周期留痕。"""

    __tablename__ = "refund_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.id"), index=True)
    operator: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


async def init_db(dsn: str) -> AsyncEngine:
    """建引擎并建表（演示环境自动 create_all；生产可换 Alembic）。"""
    engine = create_async_engine(dsn, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session
