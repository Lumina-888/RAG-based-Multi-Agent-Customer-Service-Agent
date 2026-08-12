"""演示账号（SP-SEC-003 / 设计文档 §3：模拟用户，无真实个人信息）。"""
from __future__ import annotations

#: 演示账号表：user_id → {username, password, display_name}
DEMO_USERS: dict[str, dict[str, str]] = {
    "user-1": {"username": "alice", "password": "demo123", "display_name": "演示用户·艾丽"},
    "user-2": {"username": "bob", "password": "demo123", "display_name": "演示用户·鲍勃"},
}
