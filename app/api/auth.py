"""SP-SEC-003 认证与鉴权 API：登录 + 统一身份解析。

- `POST /api/v1/auth/login`：一键登录（user_id）或账号密码，返回 `user_id + token`
- `get_current_user`（FastAPI 依赖）：`Authorization: Bearer <token>` 优先；
  内部演示兼容 `X-User-Id` 简化头；未认证返回 None（端点映射 4010）
- 受保护接口（退款建单 / 会话历史 / 订单查询归属）统一经此解析身份
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth.token_store import RedisTokenStore, TokenStore
from app.core.config import get_settings
from app.core.responses import err, ok
from app.seed.users import DEMO_USERS

logger = logging.getLogger("app.api.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """一键登录：user_id；或账号密码：username + password。"""

    user_id: str = ""
    username: str = ""
    password: str = ""


@lru_cache(maxsize=1)
def _build_token_store() -> TokenStore:
    return RedisTokenStore(get_settings().redis_url)


def get_token_store() -> TokenStore:
    """Token 存储依赖（测试可 dependency_overrides 注入内存实现）。"""
    return _build_token_store()


@router.post("/login")
async def login(
    req: LoginRequest,
    store: TokenStore = Depends(get_token_store),
) -> dict:
    """登录：一键 / 账号密码 → `{user_id, token}`；凭证错误 → 4010。"""
    if req.user_id.strip():
        if req.user_id not in DEMO_USERS:
            return err(4010, 401, "用户不存在")
        user_id = req.user_id
    else:
        matched = [
            uid for uid, user in DEMO_USERS.items()
            if user["username"] == req.username and user["password"] == req.password
        ]
        if not matched:
            return err(4010, 401, "账号或密码错误")
        user_id = matched[0]
    token = await store.issue(user_id)
    logger.info("登录成功 user_id=%s", user_id)
    return ok({"user_id": user_id, "token": token})


async def get_current_user(
    request: Request,
    store: TokenStore = Depends(get_token_store),
) -> str | None:
    """统一身份解析：Bearer token 优先；内部演示兼容 X-User-Id 简化头。

    返回 None 表示未认证（端点映射 4010）。
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):].strip()
        if not token:
            return None
        user_id = await store.resolve(token)  # 无效/过期 → None
        if user_id is None:
            return None
        return user_id
    user_id = request.headers.get("X-User-Id")
    if user_id and user_id.strip():
        return user_id.strip()
    return None
