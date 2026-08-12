"""Token 存储（SP-SEC-003）：签发 / 解析 / 撤销。

- `RedisTokenStore`：`auth:{token} → user_id`（TTL 2 小时）
- `MemoryTokenStore`：内存实现（CI 单测 / 演示）
"""
from __future__ import annotations

import uuid
from typing import Protocol

import redis.asyncio as aioredis

#: 登录态有效期（秒）
TOKEN_TTL_SECONDS = 2 * 3600


class TokenStore(Protocol):
    """Token 存储协议：Redis 与内存实现同一接口。"""

    async def issue(self, user_id: str, ttl: int = TOKEN_TTL_SECONDS) -> str: ...

    async def resolve(self, token: str) -> str | None: ...

    async def revoke(self, token: str) -> None: ...


class RedisTokenStore:
    """Redis 实现：`auth:{token}` → user_id。"""

    def __init__(self, redis_url: str, client=None) -> None:
        self._redis = client if client is not None else aioredis.from_url(
            redis_url, decode_responses=True
        )

    @staticmethod
    def _key(token: str) -> str:
        return f"auth:{token}"

    async def issue(self, user_id: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
        token = f"tk_{uuid.uuid4().hex[:24]}"
        await self._redis.set(self._key(token), user_id, ex=ttl)
        return token

    async def resolve(self, token: str) -> str | None:
        return await self._redis.get(self._key(token))

    async def revoke(self, token: str) -> None:
        await self._redis.delete(self._key(token))

    async def aclose(self) -> None:
        await self._redis.aclose()


class MemoryTokenStore:
    """内存实现（CI 单测 / 演示）。"""

    def __init__(self, ttl: int = TOKEN_TTL_SECONDS) -> None:
        self._tokens: dict[str, tuple[str, float]] = {}
        self.ttl = ttl

    async def issue(self, user_id: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
        import time

        token = f"tk_{uuid.uuid4().hex[:24]}"
        self._tokens[token] = (user_id, time.monotonic() + ttl)
        return token

    async def resolve(self, token: str) -> str | None:
        import time

        record = self._tokens.get(token)
        if record is None:
            return None
        user_id, expires = record
        if time.monotonic() > expires:  # 过期即失效
            self._tokens.pop(token, None)
            return None
        return user_id

    async def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)
