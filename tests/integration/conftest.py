"""集成测试共享夹具：ES 不可达时整体 skip（本地起 ES 见 M9 docker compose）。"""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services.es import ESClient


@pytest.fixture
async def es_client() -> ESClient:
    client = ESClient(get_settings().es_host, timeout=3.0)
    try:
        ok = await client.ping()
    except Exception:  # noqa: BLE001 - 连接失败视为不可用
        ok = False
    if not ok:
        await client.aclose()
        pytest.skip("本机 ES 不可用（需 ES 8.x，docker compose 见 M9）")
    yield client
    await client.aclose()
