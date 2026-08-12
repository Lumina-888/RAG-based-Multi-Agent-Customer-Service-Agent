"""消息历史仓储（SP-CHAT-001）：PostgreSQL 持久保留，不受短期上下文 TTL 影响。

- `PostgresMessageRepo`：SQLAlchemy 异步实现（sessions / messages 表）
- `MemoryMessageRepo`：内存实现（CI 单测 / 无 PG 演示模式）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import delete, insert, select, update

from app.models.db import ChatMessageRow, SessionRow, make_sessionmaker


@dataclass
class MessageRecord:
    """历史消息记录（时间升序查询，含意图/置信度/路由元数据）。"""

    id: int
    session_id: str
    role: str
    content: str
    intent: str | None
    conf: float | None
    agent_route: str | None
    created_at: datetime

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "intent": self.intent,
            "conf": self.conf,
            "agent_route": self.agent_route,
            "created_at": self.created_at.isoformat(),
        }


class MessageRepo(Protocol):
    """消息仓储协议：PG 与内存实现同一接口。"""

    async def ensure_session(self, session_id: str, user_id: str) -> None: ...

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        intent: str | None = None,
        conf: float | None = None,
        agent_route: str | None = None,
    ) -> MessageRecord: ...

    async def list_messages(self, session_id: str) -> list[MessageRecord]: ...

    async def get_session_owner(self, session_id: str) -> str | None: ...

    async def delete_session(self, session_id: str) -> None: ...


class PostgresMessageRepo:
    """PostgreSQL 实现（sessions/messages 表，设计文档 §7.4）。"""

    def __init__(self, dsn: str) -> None:
        self._engine = None
        self._dsn = dsn

    async def _sessionmaker(self):
        from app.models.db import init_db  # 延迟导入：避免建表副作用

        if self._engine is None:
            self._engine = await init_db(self._dsn)
        return make_sessionmaker(self._engine)

    async def ensure_session(self, session_id: str, user_id: str) -> None:
        sm = await self._sessionmaker()
        async with sm() as session:
            if await session.get(SessionRow, session_id) is None:  # 已存在则跳过（幂等）
                session.add(SessionRow(id=session_id, user_id=user_id))
                await session.commit()

    async def add_message(
        self, session_id: str, role: str, content: str,
        intent: str | None = None, conf: float | None = None, agent_route: str | None = None,
    ) -> MessageRecord:
        sm = await self._sessionmaker()
        async with sm() as session:
            row = await session.execute(
                insert(ChatMessageRow)
                .values(
                    session_id=session_id, role=role, content=content,
                    intent=intent, conf=conf, agent_route=agent_route,
                )
                .returning(
                    ChatMessageRow.id, ChatMessageRow.session_id, ChatMessageRow.role,
                    ChatMessageRow.content, ChatMessageRow.intent, ChatMessageRow.conf,
                    ChatMessageRow.agent_route, ChatMessageRow.created_at,
                )
            )
            await session.commit()
            return MessageRecord(*row.one())

    async def list_messages(self, session_id: str) -> list[MessageRecord]:
        sm = await self._sessionmaker()
        async with sm() as session:
            rows = await session.execute(
                select(
                    ChatMessageRow.id, ChatMessageRow.session_id, ChatMessageRow.role,
                    ChatMessageRow.content, ChatMessageRow.intent, ChatMessageRow.conf,
                    ChatMessageRow.agent_route, ChatMessageRow.created_at,
                )
                .where(ChatMessageRow.session_id == session_id)
                .order_by(ChatMessageRow.created_at.asc(), ChatMessageRow.id.asc())
            )
            return [MessageRecord(*row) for row in rows]

    async def get_session_owner(self, session_id: str) -> str | None:
        sm = await self._sessionmaker()
        async with sm() as session:
            row = await session.execute(
                select(SessionRow.user_id).where(SessionRow.id == session_id)
            )
            return row.scalar_one_or_none()

    async def delete_session(self, session_id: str) -> None:
        sm = await self._sessionmaker()
        async with sm() as session:
            await session.execute(delete(ChatMessageRow).where(ChatMessageRow.session_id == session_id))
            await session.execute(delete(SessionRow).where(SessionRow.id == session_id))
            await session.commit()

    async def aclose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


class MemoryMessageRepo:
    """内存实现（CI 单测 / 无 PG 演示模式）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
        self._messages: dict[str, list[MessageRecord]] = {}
        self._seq = 0

    async def ensure_session(self, session_id: str, user_id: str) -> None:
        self._sessions.setdefault(session_id, user_id)

    async def add_message(
        self, session_id: str, role: str, content: str,
        intent: str | None = None, conf: float | None = None, agent_route: str | None = None,
    ) -> MessageRecord:
        self._seq += 1
        record = MessageRecord(
            id=self._seq, session_id=session_id, role=role, content=content,
            intent=intent, conf=conf, agent_route=agent_route,
            created_at=datetime.now(timezone.utc),
        )
        self._messages.setdefault(session_id, []).append(record)
        return record

    async def list_messages(self, session_id: str) -> list[MessageRecord]:
        return list(self._messages.get(session_id, []))

    async def get_session_owner(self, session_id: str) -> str | None:
        return self._sessions.get(session_id)

    async def delete_session(self, session_id: str) -> None:
        self._messages.pop(session_id, None)
        self._sessions.pop(session_id, None)
