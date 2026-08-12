"""SP-AGENT-003 工具调用前置：模拟 ERP（SP-AGENT-003 依赖）。

- T-AGENT-111 订单查询契约 {code, data, msg}：存在返回 0，不存在 4041
- T-AGENT-112 归属字段：查询结果携带 user_id（供工具层 4030 校验）
"""
from __future__ import annotations

import pytest

from app.services.erp_sim import SEED_ORDERS, get_order, query_order


@pytest.mark.spec("SP-AGENT-003")
class TestERPSim:
    def test_agent_111_query_contract(self) -> None:
        result = query_order("ORD-20260811-001")
        assert result["code"] == 0
        assert result["data"]["order_id"] == "ORD-20260811-001"
        assert result["data"]["status"] in ("pending_shipment", "shipped", "received")

        missing = query_order("ORD-99999999-999")
        assert missing["code"] == 4041  # 订单不存在
        assert missing["data"] is None

    def test_agent_112_owner_field(self) -> None:
        assert get_order("ORD-20260811-001").user_id == "user-1"  # type: ignore[union-attr]
        assert SEED_ORDERS  # 演示种子订单非空
        assert all(o.user_id for o in SEED_ORDERS.values())
