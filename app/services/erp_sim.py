"""模拟 ERP 服务（SP-AGENT-003 / 设计文档 §6.3）。

契约：`query_order(order_id) -> {code, data, msg}`（code: 0 成功 / 4041 订单不存在）。
种子订单含 `user_id` 字段——工具层调用前做归属校验（4030，SP-AGENT-003）。
M6 退款预审使用的状态/时效字段（status / received_days）一并提供。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Order:
    order_id: str
    user_id: str
    status: str  # pending_shipment 未发货 / shipped 已发货 / received 已签收
    amount: float
    item_title: str
    logistics: str = ""
    received_days: int | None = None  # 签收天数（M6 时效预审用）


#: 演示种子订单（虚构数据）
SEED_ORDERS: dict[str, Order] = {
    "ORD-20260811-001": Order(
        order_id="ORD-20260811-001", user_id="user-1", status="received",
        amount=199.0, item_title="智能保温杯 Pro", logistics="已签收",
        received_days=3,
    ),
    "ORD-20260811-002": Order(
        order_id="ORD-20260811-002", user_id="user-1", status="shipped",
        amount=59.0, item_title="蓝牙耳机", logistics="运输中：广州→杭州",
    ),
    "ORD-20260811-003": Order(
        order_id="ORD-20260811-003", user_id="user-2", status="pending_shipment",
        amount=299.0, item_title="智能手表", logistics="待发货",
    ),
}


def get_order(order_id: str) -> Order | None:
    return SEED_ORDERS.get(order_id)


def query_order(order_id: str) -> dict:
    """模拟 ERP 订单查询（返回统一契约，归属校验由工具层负责）。"""
    order = get_order(order_id)
    if order is None:
        return {"code": 4041, "data": None, "msg": "订单不存在"}
    return {
        "code": 0,
        "data": {
            "order_id": order.order_id,
            "user_id": order.user_id,
            "status": order.status,
            "amount": order.amount,
            "item_title": order.item_title,
            "logistics": order.logistics,
        },
        "msg": "ok",
    }
