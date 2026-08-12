"""会话记忆存储（SP-CHAT-001 / 设计文档 §6.4）：

- 短期上下文：`session:{id}:ctx`（Redis，TTL 30 分钟）——TTL 只影响"上下文注入"，
  不影响消息历史查询（历史在 PostgreSQL，SP-CHAT-001）
- 事件序列：`session:{id}:events`（Redis List，SSE 断线重连重放，SP-SSE-001）
- `FakeSessionStore`：CI 单测注入（同 SP-CFG-004 FakeLLM 模式）
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import redis.asyncio as aioredis

logger = logging.getLogger("app.memory.store")

#: 短期上下文 TTL：30 分钟（SP-CHAT-001）
CONTEXT_TTL_SECONDS = 30 * 60


class SessionStore(Protocol):
    """会话存储协议：Redis 与 Fake 实现同一接口。"""

    ctx_ttl: int

    async def get_context(self, session_id: str) -> list[dict[str, Any]]: ...

    async def set_context(self, session_id: str, messages: list[dict[str, Any]]) -> None: ...

    async def append_event(self, session_id: str, event: dict[str, Any]) -> int: ...

    async def get_events(self, session_id: str, after_id: int = 0) -> list[dict[str, Any]]: ...

    async def clear(self, session_id: str) -> None: ...


class RedisSessionStore:
    """Redis 实现：上下文 JSON + TTL；事件序列按序号（RPUSH 位置）重放。

    `client` 可注入（fakeredis 等替身）供单测，默认按 `redis_url` 建真实客户端。
    """

    def __init__(
        self,
        redis_url: str,
        ttl: int = CONTEXT_TTL_SECONDS,
        client: Any | None = None,
    ) -> None:
        self.ctx_ttl = ttl
        self._redis = client if client is not None else aioredis.from_url(
            redis_url, decode_responses=True
        )

    @staticmethod
    def _ctx_key(session_id: str) -> str:
        return f"session:{session_id}:ctx"

    @staticmethod
    def _events_key(session_id: str) -> str:
        return f"session:{session_id}:events"

    async def get_context(self, session_id: str) -> list[dict[str, Any]]:
        raw = await self._redis.get(self._ctx_key(session_id))
        return json.loads(raw) if raw else []

    async def set_context(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        await self._redis.set(
            self._ctx_key(session_id),
            json.dumps(messages, ensure_ascii=False),
            ex=self.ctx_ttl,  # TTL 30 分钟：过期后不再注入旧上下文
        )

    async def append_event(self, session_id: str, event: dict[str, Any]) -> int:
        """RPUSH 返回列表长度 = 该事件的序号（1 起，作为 SSE id / Last-Event-ID）。"""
        return await self._redis.rpush(
            self._events_key(session_id), json.dumps(event, ensure_ascii=False)
        )

    async def get_events(self, session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        raw = await self._redis.lrange(self._events_key(session_id), after_id, -1)
        return [
            {**json.loads(item), "id": idx + after_id + 1} for idx, item in enumerate(raw)
        ]

    async def clear(self, session_id: str) -> None:
        await self._redis.delete(self._ctx_key(session_id), self._events_key(session_id))

    async def aclose(self) -> None:
        await self._redis.aclose()


class FakeSessionStore:
    """内存实现（CI 单测）：`expire_context` 模拟 TTL 过期。"""

    def __init__(self, ttl: int = CONTEXT_TTL_SECONDS) -> None:
        self.ctx_ttl = ttl
        self.contexts: dict[str, list[dict[str, Any]]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}

    async def get_context(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.contexts.get(session_id, []))

    async def set_context(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        self.contexts[session_id] = list(messages)

    def expire_context(self, session_id: str) -> None:
        """模拟 TTL 过期（测试用）。"""
        self.contexts.pop(session_id, None)

    async def append_event(self, session_id: str, event: dict[str, Any]) -> int:
        seq = self.events.setdefault(session_id, [])
        seq.append(dict(event))
        return len(seq)

    async def get_events(self, session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        seq = self.events.get(session_id, [])
        return [
            {**event, "id": idx + 1}
            for idx, event in enumerate(seq)
            if idx + 1 > after_id
        ]

    async def clear(self, session_id: str) -> None:
        self.contexts.pop(session_id, None)
        self.events.pop(session_id, None)
