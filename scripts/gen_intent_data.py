"""生成意图训练/测试集（SP-INT-002）：确定性种子，可复现。

产物：
- data/train/intent_train.csv    每类 200 条（共 1200），列：label,text
- data/test_cases/intent.csv     每类 50 条（共 300），列：label,text

设计：每类 12 条模板 × 中性后缀变体组合去重；训练/测试用不同后缀池与随机种子，
保证测试句与训练句不完全相同（同分布）。关键词分布刻意隔离（如 退款/退货 仅出现
在 refund 类），支撑 fastText 达到 85% 准确率门槛。
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 每类训练条数 / 测试条数（规格：训练每类 ≥ 200）
TRAIN_PER_CLASS = 200
TEST_PER_CLASS = 50

GOODS = ("保温杯", "智能手表", "蓝牙耳机", "充电宝", "台灯", "键盘", "鼠标", "水杯")
ORDER_IDS = tuple(f"ORD-20260811-{i:03d}" for i in range(1, 9))

INTENT_TEMPLATES: dict[str, list[str]] = {
    "pre_sales": [
        "这个{g}多少钱", "{g}有优惠活动吗", "你们卖{g}吗", "{g}是什么颜色",
        "{g}多大尺寸", "买{g}什么时候发货", "这款{g}怎么样", "{g}可以开发票吗",
        "有什么推荐的{g}", "{g}价格是多少", "现在下单有折扣吗", "想咨询一下{g}的参数",
    ],
    "after_sales": [
        "{g}坏了怎么维修", "{g}在保修期内吗", "怎么联系售后服务", "{g}出现故障了",
        "保修期是多久", "{g}可以免费维修吗", "售后电话是多少", "维修需要多久",
        "{g}充不进电了", "售后网点在哪里", "质量问题找谁处理", "{g}需要保养吗",
    ],
    "order_query": [
        "我的订单到哪了", "查询一下物流信息", "订单号{o}到哪里了", "我的包裹什么时候到",
        "帮我看看快递进度", "订单{o}发货了吗", "物流显示不动了", "快递多久能送到",
        "我的订单状态是什么", "查询订单{o}", "包裹到哪个城市了", "快递单号怎么查",
    ],
    "refund": [
        "我要申请退款", "怎么办理退货", "退款什么时候到账", "申请退款没到账",
        "想退货退款", "退款流程是什么", "退货地址是什么", "退款怎么还没到",
        "取消订单退款", "如何申请仅退款", "退款金额不对", "退货要几天",
    ],
    "complaint": [
        "我要投诉", "客服态度太差了", "商品太差我要举报", "对服务不满意",
        "投诉你们平台", "客服不理人", "体验太差了", "我要投诉发货太慢",
        "售后服务太敷衍", "投诉电话是多少", "这服务让人生气", "质量差到想投诉",
    ],
    "human": [
        "我要转人工客服", "人工客服在哪里", "请给我转人工", "找真人客服",
        "转人工服务", "人工客服电话是多少", "我要找人工处理", "请安排人工客服",
        "想和人工聊聊", "人工客服在吗", "请转接人工坐席", "有人工客服吗",
    ],
}

#: 中性后缀池（不携带类关键词；训练与测试用不同池）
TRAIN_JUNK = [
    "麻烦问一下", "谢谢", "在线等回复", "请问一下", "谢谢啦", "麻烦您了",
    "打扰了", "在吗", "想了解一下", "帮帮忙", "谢谢了", "麻烦帮忙看看",
    "感谢", "辛苦了", "谢谢回复", "麻烦尽快回复", "在线等", "感谢解答", "麻烦啦", "谢谢您",
]
TEST_JUNK = [
    "方便的话回复一下", "期待回复", "麻烦告知", "谢谢答复", "辛苦啦", "感谢您",
    "在吗在吗", "打扰您了", "盼回复", "谢谢您了", "麻烦您看看", "感谢帮忙",
    "期待答复", "谢谢关注", "麻烦回复", "感谢您了", "辛苦了您", "麻烦您了谢谢",
    "期待您的回复", "在线等您",
]


def _render(template: str, rng: random.Random) -> str:
    if "{g}" in template:
        return template.format(g=rng.choice(GOODS))
    if "{o}" in template:
        return template.format(o=rng.choice(tuple(ORDER_IDS)))
    return template


def _generate(label: str, templates: list[str], junk: list[str], n: int, rng: random.Random) -> list[tuple[str, str]]:
    """模板 × 中性后缀组合生成 n 条（类内去重）。"""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    while len(rows) < n:
        tpl = rng.choice(templates)
        sentence = f"{_render(tpl, rng)} {rng.choice(junk)}".strip()
        if sentence in seen:
            continue
        seen.add(sentence)
        rows.append((label, sentence))
    return rows


def main() -> None:
    train_path = ROOT / "data" / "train" / "intent_train.csv"
    test_path = ROOT / "data" / "test_cases" / "intent.csv"
    train_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.parent.mkdir(parents=True, exist_ok=True)

    train_rows: list[tuple[str, str]] = []
    test_rows: list[tuple[str, str]] = []
    for label, templates in INTENT_TEMPLATES.items():
        train_rows += _generate(label, templates, TRAIN_JUNK, TRAIN_PER_CLASS, random.Random(42))
        test_rows += _generate(label, templates, TEST_JUNK, TEST_PER_CLASS, random.Random(43))

    with train_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["label", "text"])
        writer.writerows(train_rows)
    with test_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["label", "text"])
        writer.writerows(test_rows)

    from collections import Counter

    print(f"训练集: {train_path} 共 {len(train_rows)} 条")
    print(f"测试集: {test_path} 共 {len(test_rows)} 条")
    print("训练集分布:", dict(Counter(label for label, _ in train_rows)))


if __name__ == "__main__":
    main()
