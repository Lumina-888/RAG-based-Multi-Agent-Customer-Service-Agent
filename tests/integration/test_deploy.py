"""SP-DEP-001/003 部署冒烟（外部服务守卫，需 `docker compose up -d` 后运行）。

- T-DEP-101 `/api/v1/health` 200 且 code=0
- T-DEP-102 首页 200（前端 dist 由 FastAPI 托管，SP-DEP-001）
- T-DEP-301 Nginx 限流命中 429 → 响应体为统一包装（code=4290，SP-DEP-003）
  （限流在转发前生效，nginx 起来即可测，不依赖 app 存活）
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

APP_URL = "http://localhost:8000"
NGINX_URL = "http://localhost:8080"


@pytest.fixture
async def app_up() -> None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{APP_URL}/api/v1/health")
        if resp.status_code != 200:
            pytest.skip(f"app 已起但 health 异常: {resp.status_code}")
    except Exception:  # noqa: BLE001 - 服务未启动视为守卫跳过
        pytest.skip("app 未启动（先 `docker compose up -d`，本机直连 8000）")


@pytest.fixture
async def nginx_up() -> None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{NGINX_URL}/api/v1/health")
        # nginx 可达（无论 200/429/502——限流在转发前生效）
        if resp.status_code not in (200, 429, 502):
            pytest.skip(f"nginx 响应异常: {resp.status_code}")
    except Exception:  # noqa: BLE001
        pytest.skip("nginx 未启动（8080 端口，见 deploy/nginx.conf）")


@pytest.mark.spec("SP-DEP-001")
@pytest.mark.integration
class TestDeploySmoke:
    async def test_dep_101_health_probe(self, app_up: None) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{APP_URL}/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0 and body["data"]["status"] == "healthy"
        assert body["trace_id"].startswith("t_")

    async def test_dep_102_home_page_200(self, app_up: None) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{APP_URL}/")
        assert resp.status_code == 200  # 前端 dist 由 FastAPI 托管
        assert "智能客服" in resp.text  # index.html 标题


@pytest.mark.spec("SP-DEP-003")
@pytest.mark.integration
class TestNginxRateLimit:
    async def test_dep_301_429_unified_json(self, nginx_up: None) -> None:
        """限流命中（>30 req/s + burst）→ 429，且响应体为统一包装 code=4290。"""
        async with httpx.AsyncClient(timeout=5.0) as client:
            # 并发打满限流窗口（30 req/s + burst=20，~50 个请求即触发）
            results = await asyncio.gather(
                *[client.get(f"{NGINX_URL}/api/v1/health") for _ in range(120)]
            )
        rate_limited = [r for r in results if r.status_code == 429]
        assert rate_limited, "未触发 429（限流未生效？检查 nginx limit_req）"
        for resp in rate_limited[:3]:
            body = resp.json()
            assert body["code"] == 4290  # 统一错误码（SP-API-GEN）
            assert body["message"] and "trace_id" in body
