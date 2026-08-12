"""生成评测数据（SP-EVAL-001）：确定性种子，可复现。

产物：
- data/test_cases/retrieval.jsonl  检索标注 50 条：{"query", "gold_docs": [doc_id]}
- data/test_cases/chat_e2e.jsonl   E2E 对话 20 条：{"id", "path", "turns"}

设计：
- retrieval：扫描 data/raw_docs/*.md，doc_id = 文件名 stem；按分类模板池
  （售后政策类 / 商品使用FAQ 类 / 兜底通用）生成查询，gold_docs 指向该 doc。
  总条数固定 50（多文档时每篇均分，≥1）；W4-3 知识库扩充（G）后重跑即可
  自动覆盖新文档（新文档按文件名关键词命中分类池）
- chat_e2e：20 条手写对话对，覆盖四条路径（正常/澄清/转人工/退款，各 5 条）
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 检索标注总量（SP-EVAL-001：retrieval 样例 50 条）
RETRIEVAL_TARGET = 50
#: 单篇文档查询数上限（多文档时均分，避免小库样例过密）
QUERIES_PER_DOC_CAP = 25

GOODS = ("保温杯", "智能手表", "蓝牙耳机", "充电宝", "台灯", "键盘", "鼠标", "水杯")
SUFFIXES = ("麻烦问一下", "谢谢", "在线等", "请问一下", "谢谢啦", "麻烦您了", "打扰了")

#: 分类查询模板池（doc_id 命中分类后使用；W4-3 新文档按 stem 关键词命中）
CATEGORY_TEMPLATES: dict[str, list[str]] = {
    "售后政策": [
        "退款多久到账", "退款流程是什么", "怎么申请退款", "退货规则是什么",
        "退货运费谁承担", "退货地址是什么", "七天无理由退货怎么操作",
        "质量问题怎么退货", "退款金额不对怎么办", "退款为什么还没到",
        "已签收还能退货吗", "退款要几天", "仅退款怎么申请",
        "退货需要提供凭证吗", "订单发货了吗", "物流信息怎么查",
        "快递什么时候到", "发货需要几天", "收货后多久能退",
        "保修期是多久", "怎么联系售后", "售后电话是多少",
        "发票怎么开", "可以开发票吗", "商品不想要了能退吗",
    ],
    "商品使用FAQ": [
        "{g}容量多大", "{g}怎么充电", "{g}续航多久", "{g}怎么连接手机",
        "{g}防水吗", "{g}怎么配对", "{g}怎么清洗", "{g}按键怎么用",
        "{g}支持快充吗", "{g}待机多久", "{g}有几种颜色", "{g}尺寸多大",
        "{g}重量多少", "{g}怎么开机", "{g}怎么重置", "{g}充电要多久",
        "{g}能连电脑吗", "{g}怎么换电池", "{g}灯珠是什么类型", "{g}支持蓝牙吗",
        "{g}怎么调音量", "{g}充电接口是什么", "{g}怎么升级固件", "{g}怎么绑定",
        "{g}第一次使用要注意什么",
    ],
}

#: 兜底通用池（未命中分类的文档）
GENERIC_TEMPLATES = [
    "介绍一下{g}", "{g}有什么功能", "{g}怎么使用", "{g}规格是什么", "{g}常见问题",
]


def _classify(doc_id: str) -> str:
    """按文件名关键词分类（W4-3 扩充后自动覆盖）。"""
    if "售后" in doc_id or "政策" in doc_id:
        return "售后政策"
    if "FAQ" in doc_id or "商品" in doc_id or "手册" in doc_id or "使用" in doc_id:
        return "商品使用FAQ"
    return "generic"


def _render(template: str, rng: random.Random) -> str:
    return template.format(g=rng.choice(GOODS)) if "{g}" in template else template


def _gen_queries(doc_id: str, n: int, rng: random.Random) -> list[dict]:
    """为单篇文档生成 n 条不重复查询（模板 × 中性后缀组合）。"""
    pool = CATEGORY_TEMPLATES.get(_classify(doc_id), GENERIC_TEMPLATES)
    rows: list[dict] = []
    seen: set[str] = set()
    while len(rows) < n:
        query = f"{_render(rng.choice(pool), rng)} {rng.choice(SUFFIXES)}".strip()
        if query in seen:
            continue
        seen.add(query)
        rows.append({"query": query, "gold_docs": [doc_id]})
    return rows


#: E2E 对话样例（20 条：正常/澄清/转人工/退款 各 5 条，路径对齐 SP-SSE-001）
CHAT_E2E_CASES: list[dict] = [
    # ---- 正常问答路径（intent → route → retrieval → message → done）----
    {"id": "ce-001", "path": "normal", "turns": [
        {"role": "user", "content": "这个保温杯容量多大？"},
        {"role": "assistant", "content": "容量 500ml，保温时长 12 小时[1]。"},
    ]},
    {"id": "ce-002", "path": "normal", "turns": [
        {"role": "user", "content": "蓝牙耳机怎么连接手机？"},
        {"role": "assistant", "content": "开机后进入配对模式，在手机蓝牙列表中选择设备即可[1]。"},
    ]},
    {"id": "ce-003", "path": "normal", "turns": [
        {"role": "user", "content": "台灯多少钱？"},
        {"role": "assistant", "content": "这款台灯售价 89 元，现在下单还有优惠[1]。"},
        {"role": "user", "content": "可以开发票吗？"},
        {"role": "assistant", "content": "可以的，下单时选择需要发票即可[1]。"},
    ]},
    {"id": "ce-004", "path": "normal", "turns": [
        {"role": "user", "content": "充电宝能带上飞机吗？"},
        {"role": "assistant", "content": "20000mAh 以内可以随身携带，需遵守航空公司规定[1]。"},
    ]},
    {"id": "ce-005", "path": "normal", "turns": [
        {"role": "user", "content": "键盘怎么清洗？"},
        {"role": "assistant", "content": "建议使用软毛刷和清洁胶，避免液体直接冲洗[1]。"},
    ]},
    # ---- 澄清路径（低置信度 → clarify，无 retrieval）----
    {"id": "ce-006", "path": "clarify", "turns": [
        {"role": "user", "content": "帮我看看那个"},
        {"role": "assistant", "content": "请问您想查询哪方面的内容？可以具体描述一下商品或问题。"},
    ]},
    {"id": "ce-007", "path": "clarify", "turns": [
        {"role": "user", "content": "退"},
        {"role": "assistant", "content": "您是想了解退货流程还是申请退款？请告诉我您的订单情况。"},
    ]},
    {"id": "ce-008", "path": "clarify", "turns": [
        {"role": "user", "content": "那个东西怎么样了"},
        {"role": "assistant", "content": "抱歉没理解您的意思，请提供商品名称或订单号，方便为您查询。"},
    ]},
    {"id": "ce-009", "path": "clarify", "turns": [
        {"role": "user", "content": "不是 我不是说这个"},
        {"role": "assistant", "content": "明白，请您重新描述一下问题，我会尽快帮您处理。"},
    ]},
    {"id": "ce-010", "path": "clarify", "turns": [
        {"role": "user", "content": "额 就是那个 你懂的"},
        {"role": "assistant", "content": "抱歉我没理解，您可以输入商品名称或具体问题，我来帮您查询。"},
    ]},
    # ---- 转人工路径（complaint/human → transfer，done.transfer 标记）----
    {"id": "ce-011", "path": "transfer", "turns": [
        {"role": "user", "content": "我要投诉！你们客服太敷衍了"},
        {"role": "assistant", "content": "非常抱歉给您带来不好的体验，已为您转接人工坐席 1001。"},
    ]},
    {"id": "ce-012", "path": "transfer", "turns": [
        {"role": "user", "content": "转人工客服"},
        {"role": "assistant", "content": "好的，已为您转接人工坐席 1001，请稍候。"},
    ]},
    {"id": "ce-013", "path": "transfer", "turns": [
        {"role": "user", "content": "我要找真人说话"},
        {"role": "assistant", "content": "已为您转接人工坐席 1001。"},
    ]},
    {"id": "ce-014", "path": "transfer", "turns": [
        {"role": "user", "content": "你们服务太差了我要举报"},
        {"role": "assistant", "content": "很抱歉给您带来困扰，已为您转接人工坐席 1001 处理。"},
    ]},
    {"id": "ce-015", "path": "transfer", "turns": [
        {"role": "user", "content": "人工客服在吗"},
        {"role": "assistant", "content": "在的，已为您转接人工坐席 1001。"},
    ]},
    # ---- 退款路径（refund → refund_agent 工单，含二次确认）----
    {"id": "ce-016", "path": "refund", "turns": [
        {"role": "user", "content": "我要申请退款"},
        {"role": "assistant", "content": "好的，请确认退款订单号 ORD-20260811-001，确认后将为您提交退款申请。"},
        {"role": "user", "content": "确认"},
        {"role": "assistant", "content": "退款申请已提交，工单号 TK-000001，审核通过后 3~5 个工作日原路退回。"},
    ]},
    {"id": "ce-017", "path": "refund", "turns": [
        {"role": "user", "content": "订单 ORD-20260811-002 想退货"},
        {"role": "assistant", "content": "该订单已签收 3 天，支持 7 天无理由退货，确认为您提交退货退款申请吗？"},
        {"role": "user", "content": "确认"},
        {"role": "assistant", "content": "退货退款申请已提交，请按提示寄回商品。"},
    ]},
    {"id": "ce-018", "path": "refund", "turns": [
        {"role": "user", "content": "退款什么时候到账"},
        {"role": "assistant", "content": "退款审核通过后 3~5 个工作日内原路退回，您的工单号 TK-000003。"},
    ]},
    {"id": "ce-019", "path": "refund", "turns": [
        {"role": "user", "content": "商品质量问题想退货"},
        {"role": "assistant", "content": "质量问题退货需提供凭证，确认提交退货申请吗？"},
        {"role": "user", "content": "确认"},
        {"role": "assistant", "content": "退货申请已提交，请附上问题照片凭证。"},
    ]},
    {"id": "ce-020", "path": "refund", "turns": [
        {"role": "user", "content": "仅退款怎么申请"},
        {"role": "assistant", "content": "未发货订单支持仅退款，确认提交申请吗？"},
        {"role": "user", "content": "确认"},
        {"role": "assistant", "content": "仅退款申请已提交，预计 1~2 个工作日处理。"},
    ]},
]


def main() -> None:
    out_dir = ROOT / "data" / "test_cases"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- retrieval.jsonl（扫描知识库，doc_id = 文件名 stem）----
    rng = random.Random(42)
    raw_dir = ROOT / "data" / "raw_docs"
    doc_ids = sorted(p.stem for p in raw_dir.glob("*.md"))
    if not doc_ids:
        raise SystemExit(f"data/raw_docs 无 md 文档，无法生成检索标注: {raw_dir}")
    per_doc = max(1, min(QUERIES_PER_DOC_CAP, -(-RETRIEVAL_TARGET // len(doc_ids))))  # 向上取整
    retrieval_rows: list[dict] = []
    for doc_id in doc_ids:
        retrieval_rows += _gen_queries(doc_id, per_doc, rng)
    retrieval_rows = retrieval_rows[:RETRIEVAL_TARGET]  # 超量截断，保总量

    ret_path = out_dir / "retrieval.jsonl"
    with ret_path.open("w", encoding="utf-8") as f:
        for row in retrieval_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ---- chat_e2e.jsonl（20 条固定手写对话对）----
    chat_path = out_dir / "chat_e2e.jsonl"
    with chat_path.open("w", encoding="utf-8") as f:
        for case in CHAT_E2E_CASES:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    from collections import Counter

    print(f"retrieval.jsonl: {ret_path} 共 {len(retrieval_rows)} 条")
    print("  按文档分布:", dict(Counter(r["gold_docs"][0] for r in retrieval_rows)))
    print(f"chat_e2e.jsonl: {chat_path} 共 {len(CHAT_E2E_CASES)} 条")
    print("  路径分布:", dict(Counter(c["path"] for c in CHAT_E2E_CASES)))


if __name__ == "__main__":
    main()
