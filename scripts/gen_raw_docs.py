"""生成演示知识库文档（W1 目标：100 份），确定性种子可复现。

产物：data/raw_docs/ 下
- 售后政策类 30 份：`售后政策-{n:02d}.md`（H1 + H2 层级，含退款/退货/运费/质保/发票/物流时效等）
- 商品手册类 50 份：`商品手册-{n:02d}.md`（含规格参数表，H1/H2 层级 + 表格）
- FAQ 类 20 份：`FAQ-{n:02d}.md`（H2 问答对，一条 FAQ 完整不拆块）

格式对齐解析器（SP-ING-001）：
- 部分文档掺入页眉/页脚噪声样本（页码行 `第 N 页` / `Page N`、重复品牌水印行），
  验证 `clean_markdown` 噪声去除
- 全 Markdown 可被 parse_markdown 直接解析（表格保留为 Markdown 表格）

用法：python scripts/gen_raw_docs.py [--out data/raw_docs] [--seed 42]
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 各分类文档数（W1 目标：售后政策 30 / 商品手册 50 / FAQ 20）
AFTER_SALES_COUNT = 30
PRODUCT_COUNT = 50
FAQ_COUNT = 20
#: 掺入噪声样本的文档比例（页眉/页脚/页码/水印，SP-ING-001 噪声去除验证）
NOISE_RATIO = 0.2

BRAND = "智能优选商城"

#: 50 款商品（名称 + 价格 + 规格参数表）
PRODUCTS: list[dict] = [
    {"name": "智能保温杯 500ml", "price": 129, "specs": {"容量": "500ml", "保温时长": "12 小时", "材质": "316 不锈钢", "充电方式": "Type-C", "重量": "320g"}},
    {"name": "无线蓝牙耳机 Pro", "price": 299, "specs": {"续航": "单次 8 小时", "充电接口": "Type-C", "防水等级": "IPX5", "蓝牙版本": "5.3", "重量": "单耳 4.2g"}},
    {"name": "便携充电宝 20000mAh", "price": 159, "specs": {"容量": "20000mAh", "输出功率": "22.5W", "接口": "USB-A ×2 / USB-C", "重量": "380g", "民航可带": "是"}},
    {"name": "LED 护眼台灯", "price": 89, "specs": {"亮度": "三档可调", "色温": "3000K-5000K", "功率": "12W", "供电": "USB 供电", "灯珠": "72 颗"}},
    {"name": "机械键盘 87 键", "price": 199, "specs": {"轴体": "青轴", "连接": "有线/蓝牙双模", "键数": "87", "背光": "RGB", "重量": "850g"}},
    {"name": "人体工学鼠标", "price": 79, "specs": {"DPI": "800-3200 可调", "连接": "2.4G/蓝牙", "按键数": "6", "电池": "AA 一节", "重量": "95g"}},
    {"name": "便携榨汁杯", "price": 109, "specs": {"容量": "400ml", "功率": "70W", "电池": "2000mAh", "材质": "Tritan", "清洗": "可水洗"}},
    {"name": "智能手环 8 代", "price": 249, "specs": {"屏幕": "1.62 英寸 AMOLED", "续航": "14 天", "防水": "5ATM", "传感器": "心率/血氧/睡眠", "重量": "24g"}},
    {"name": "挂脖风扇", "price": 69, "specs": {"风力": "三档", "续航": "6 小时", "电池": "3000mAh", "噪音": "<45dB", "重量": "280g"}},
    {"name": "折叠晴雨伞", "price": 45, "specs": {"伞面": "防晒 UPF50+", "直径": "105cm", "伞骨": "8 骨铝合金", "重量": "320g", "收合": "三折"}},
    {"name": "电热烧水杯", "price": 139, "specs": {"容量": "450ml", "功率": "300W", "材质": "304 内胆", "档位": "40/55/100℃", "重量": "540g"}},
    {"name": "智能门锁指纹版", "price": 899, "specs": {"开锁方式": "指纹/密码/钥匙", "指纹容量": "100 枚", "供电": "4 节 AA", "防盗等级": "C 级锁芯", "适用门厚": "40-120mm"}},
    {"name": "扫地机器人 L10", "price": 1499, "specs": {"吸力": "4000Pa", "续航": "180 分钟", "尘盒": "600ml", "导航": "激光雷达", "拖地": "电控水箱"}},
    {"name": "空气炸锅 5L", "price": 349, "specs": {"容量": "5L", "功率": "1500W", "温控": "80-200℃", "炸篮": "不粘涂层", "定时": "0-60 分钟"}},
    {"name": "破壁机", "price": 499, "specs": {"容量": "1.75L", "功率": "1200W", "转速": "35000rpm", "杯体": "高硼硅玻璃", "功能": "豆浆/果汁/辅食"}},
    {"name": "智能音箱 Mini", "price": 99, "specs": {"扬声器": "3W", "麦克风": "双麦阵列", "连接": "WiFi/蓝牙", "尺寸": "98×45mm", "语音": "全场景"}},
    {"name": "电动牙刷 S5", "price": 199, "specs": {"震动频率": "38000 次/分钟", "模式": "5 种", "续航": "30 天", "充电": "Type-C", "刷头": "杜邦软毛"}},
    {"name": "蒸汽挂烫机", "price": 259, "specs": {"水箱": "1.5L", "蒸汽量": "32g/min", "功率": "1500W", "预热": "30 秒", "适用": "干烫湿烫"}},
    {"name": "儿童学习桌", "price": 799, "specs": {"尺寸": "100×60cm", "高度": "52-76cm 可调", "材质": "环保板材", "收纳": "抽屉+书架", "承重": "80kg"}},
    {"name": "瑜伽垫加厚", "price": 59, "specs": {"厚度": "8mm", "材质": "TPE", "尺寸": "183×61cm", "防滑": "双面纹理", "重量": "1.2kg"}},
    {"name": "跑步机家用款", "price": 1999, "specs": {"跑带": "120×42cm", "速度": "1-12km/h", "坡度": "0-15%", "承重": "120kg", "折叠": "支持"}},
    {"name": "电动剃须刀", "price": 219, "specs": {"刀头": "三刀头", "充电": "1 小时快充", "续航": "60 天", "防水": "IPX7 全身水洗", "显示": "LED 电量"}},
    {"name": "车载手机支架", "price": 39, "specs": {"类型": "出风口式", "材质": "铝合金", "适配": "4.7-7 英寸", "旋转": "360°", "安装": "免工具"}},
    {"name": "玻璃保鲜盒 3 件套", "price": 79, "specs": {"容量": "650ml×2+1000ml", "材质": "高硼硅玻璃", "密封": "硅胶圈", "耐温": "-20~400℃", "适用": "微波炉/烤箱"}},
    {"name": "不锈钢炒锅 32cm", "price": 169, "specs": {"直径": "32cm", "材质": "316 不锈钢", "锅底": "三层复合", "重量": "1.8kg", "适用": "燃气/电磁炉"}},
    {"name": "羽绒被冬被", "price": 599, "specs": {"尺寸": "200×230cm", "填充": "95% 白鹅绒 1.2kg", "面料": "全棉防羽布", "蓬松度": "700+", "等级": "A 类"}},
    {"name": "记忆棉枕头", "price": 129, "specs": {"尺寸": "60×40cm", "高度": "10/12cm 高低款", "内芯": "慢回弹记忆棉", "枕套": "可拆洗", "认证": "SGS 检测"}},
    {"name": "加湿器 4L", "price": 119, "specs": {"容量": "4L", "雾量": "280ml/h", "噪音": "<32dB", "水位": "可视窗口", "保护": "缺水断电"}},
    {"name": "电蚊拍充电款", "price": 49, "specs": {"电压": "2600V", "电池": "1200mAh", "网面": "三层", "照明": "LED 诱蚊灯", "充电": "USB"}},
    {"name": "筋膜枪 mini", "price": 269, "specs": {"档位": "5 档", "振幅": "8mm", "续航": "4 小时", "噪音": "<40dB", "按摩头": "4 个"}},
    {"name": "智能体脂秤", "price": 79, "specs": {"称重": "5-180kg", "精度": "100g", "测量项": "14 项身体数据", "连接": "蓝牙 5.0", "供电": "3 节 AAA"}},
    {"name": "不锈钢保温饭盒", "price": 139, "specs": {"容量": "1.2L 三层", "内胆": "316 不锈钢", "保温": "6 小时 ≥60℃", "密封": "硅胶圈", "提手": "折叠"}},
    {"name": "儿童滑板车", "price": 299, "specs": {"适用年龄": "3-8 岁", "踏板": "加宽防滑", "高度": "可调三档", "承重": "50kg", "材质": "航空铝"}},
    {"name": "厨房电子秤", "price": 49, "specs": {"量程": "5kg", "精度": "1g", "单位": "g/kg/oz", "显示": "LCD 背光", "供电": "2 节 AAA"}},
    {"name": "落地晾衣架", "price": 89, "specs": {"展开": "210×60×140cm", "承重": "30kg", "材质": "不锈钢", "结构": "X 型折叠", "收纳": "可折叠"}},
    {"name": "宠物自动喂食器", "price": 229, "specs": {"容量": "3L", "出粮": "定时 4 餐", "电源": "USB/电池双供", "适用": "猫狗通用", "防卡粮": "螺旋出粮"}},
    {"name": "旅行收纳六件套", "price": 69, "specs": {"件数": "6 件", "材质": "防水尼龙", "重量": "450g", "分类": "衣物/鞋/洗漱", "折叠": "压缩设计"}},
    {"name": "无线充电器 15W", "price": 99, "specs": {"功率": "15W", "协议": "Qi 认证", "感应距离": "8mm", "线圈": "双线圈", "保护": "过温/过压"}},
    {"name": "智能摄像头 2K", "price": 199, "specs": {"清晰度": "2K 超清", "视角": "360° 云台", "夜视": "红外/全彩", "存储": "SD/云存储", "语音": "双向对讲"}},
    {"name": "电水壶 1.7L", "price": 109, "specs": {"容量": "1.7L", "功率": "1800W", "材质": "304 不锈钢", "烧开": "约 4 分钟", "保温": "24 小时恒温"}},
    {"name": "电动滑板车 E2", "price": 1899, "specs": {"续航": "30km", "速度": "25km/h", "电机": "350W", "轮胎": "10 英寸", "承重": "120kg"}},
    {"name": "遮光窗帘 2 片", "price": 159, "specs": {"尺寸": "140×245cm×2", "遮光率": "99%", "材质": "高精密涤纶", "工艺": "高温定型", "安装": "打孔/挂钩"}},
    {"name": "男士运动背包", "price": 129, "specs": {"容量": "28L", "材质": "防泼水牛津布", "分区": "电脑仓+鞋仓", "背负": "透气减压", "重量": "680g"}},
    {"name": "桌面绿植盆栽", "price": 35, "specs": {"植物": "绿萝/发财树", "花盆": "陶瓷 12cm", "养护": "喜阴耐旱", "配送": "带土发货", "尺寸": "25-35cm"}},
    {"name": "香薰加湿器", "price": 89, "specs": {"容量": "500ml", "雾化": "超声波", "定时": "2/4/8 小时", "灯光": "七彩氛围灯", "静音": "<30dB"}},
    {"name": "行李箱 24 寸", "price": 399, "specs": {"尺寸": "24 寸", "材质": "PC 硬箱", "轮子": "万向静音轮", "锁具": "TSA 海关锁", "承重": "35kg"}},
    {"name": "家用工具箱 88 件", "price": 159, "specs": {"件数": "88 件", "工具箱": "ABS 双层", "常用": "螺丝刀/扳手/钳", "材质": "铬钒钢", "重量": "4.5kg"}},
    {"name": "电动打蛋器", "price": 69, "specs": {"功率": "350W", "档位": "5 档", "附件": "搅拌棒/打蛋棒", "材质": "食品级不锈钢", "收纳": "立式"}},
    {"name": "婴儿恒温调奶器", "price": 259, "specs": {"容量": "1.2L", "温控": "40-100℃", "恒温": "24 小时", "材质": "高硼硅玻璃", "显示": "LED 数显"}},
    {"name": "户外露营帐篷", "price": 299, "specs": {"尺寸": "2-3 人", "防水": "3000mm", "搭建": "自动速开", "重量": "2.8kg", "材质": "牛津布"}},
]

#: 售后政策模板段（H2 小节，{...} 为变体槽位）
AFTER_SALES_SECTIONS: list[tuple[str, str]] = [
    ("退款政策", "退款申请审核通过后，款项将在 {refund_days} 个工作日内原路退回至支付账户。"),
    ("退货政策", "自签收之日起 {return_days} 天内支持无理由退货（未使用、不影响二次销售），运费由{ship_cost}承担。"),
    ("运费政策", "单笔订单实付满 {free_ship_amount} 元包邮，未满则收取运费 {ship_fee} 元。"),
    ("质保政策", "本店商品提供 {warranty} 免费质保，非人为损坏支持免费维修或换新。"),
    ("发票政策", "支持开具增值税普通发票与专用发票，下单时选择开票信息即可。"),
    ("物流时效", "现货商品 {delivery_days} 小时内发出，偏远地区（{remote_regions}）时效顺延 1-2 天。"),
    ("售后联系方式", "售后热线 400-{hotline}，服务时间 {service_hours}，在线客服 7×24 小时。"),
    ("价格保护", "签收后 {price_protect_days} 天内同款降价，可申请差价退还。"),
]

#: FAQ 主题池（每份 FAQ 选一个主题，生成 10 条问答）
FAQ_TOPICS = ("商品咨询", "订单配送", "售后服务", "支付与发票", "会员与优惠")

#: 页眉/页脚噪声池（SP-ING-001 噪声去除验证；重复短行作为水印）
NOISE_LINES = (
    "智能优选电商",  # 品牌水印（≤20 字符，重复 ≥3 次 → 去除）
    "版权所有 © 2026 智能优选商城",
    "内部资料 请勿外传",
)


def _render_product(idx: int, rng: random.Random) -> str:
    p = PRODUCTS[idx]
    spec_rows = "\n".join(f"| {k} | {v} |" for k, v in p["specs"].items())
    return (
        f"# {p['name']} 商品手册\n\n"
        f"## 商品简介\n{p['name']}，售价 {p['price']} 元，适用于日常使用场景。\n\n"
        f"## 规格参数\n\n| 参数 | 数值 |\n|---|---|\n{spec_rows}\n\n"
        f"## 使用说明\n"
        f"1. 首次使用前请阅读本手册并检查配件是否齐全。\n"
        f"2. 按照图示完成组装/配对，长按电源键开机。\n"
        f"3. 使用完毕后妥善收纳，避免潮湿环境。\n\n"
        f"## 保养与维护\n"
        f"请使用干布清洁表面，切勿使用腐蚀性清洁剂。长期不使用时，建议取出电池并存放于干燥处。\n\n"
        f"## 常见问题\n"
        f"**Q：{p['name']} 如何保修？**\n"
        f"A：整机提供 1 年免费质保，凭购买记录联系客服即可。\n"
        f"**Q：{p['name']} 支持退换货吗？**\n"
        f"A：支持，签收后 7 天内无理由退换货。\n"
    )


def _render_aftersales(idx: int, rng: random.Random) -> str:
    options = {
        "refund_days": ("1-3", "3-5", "5-7"),
        "return_days": ("7", "15"),
        "ship_cost": ("平台", "买家"),
        "free_ship_amount": ("99", "199"),
        "ship_fee": ("8", "10", "12"),
        "warranty": ("1 年", "2 年", "3 年"),
        "delivery_days": ("24", "48", "72"),
        "remote_regions": ("新疆、西藏、内蒙古", "海南、甘肃、宁夏", "青海、新疆"),
        "hotline": ("800-1234", "800-5678"),
        "service_hours": ("9:00-21:00", "8:30-22:00"),
        "price_protect_days": ("7", "15", "30"),
    }
    sections = []
    for title, template in AFTER_SALES_SECTIONS:
        if rng.random() < 0.85:  # 每份保留 6~8 个小节
            filled = template.format(**{k: rng.choice(v) for k, v in options.items()})
            sections.append(f"## {title}\n{filled}")
    # 部分文档带时效表格（表格保留验证）
    if rng.random() < 0.5:
        sections.append(
            "## 时效明细\n\n| 场景 | 时效 |\n|---|---|\n"
            "| 退款到账 | 3~5 个工作日 |\n| 退货退款 | 2~3 个工作日 |\n"
            "| 换货发出 | 48 小时内 |\n"
        )
    return f"# {BRAND} 售后政策（第 {idx:02d} 版）\n\n" + "\n\n".join(sections) + "\n"


def _render_faq(idx: int, rng: random.Random) -> str:
    topic = FAQ_TOPICS[idx % len(FAQ_TOPICS)]
    qa = (
        ("下单后多久发货？", "现货商品 48 小时内发出，预售商品以页面提示时间为准。"),
        ("如何查看物流信息？", "可在「我的订单」中点击查看物流，或联系在线客服查询。"),
        ("支持哪些支付方式？", "支持微信、支付宝、银行卡及平台余额支付。"),
        ("可以开发票吗？", "可以，下单时填写开票信息即可，电子发票 1~3 个工作日推送。"),
        ("运费怎么计算？", "满 99 元包邮，未满收取 8 元运费，偏远地区另计。"),
        ("签收后可以退吗？", "签收后 7 天内支持无理由退货，质量问题 15 天内可退。"),
        ("退款多久到账？", "审核通过后 3~5 个工作日原路退回。"),
        ("如何联系人工客服？", "在对话页输入「转人工」即可接入人工坐席，或拨打 400-800-1234。"),
        ("商品保修多久？", "整机保修 1 年，部分商品 2 年，以商品详情页为准。"),
        ("质量问题如何举证？", "请提供订单号与问题照片，客服会在 24 小时内处理。"),
    )
    lines = [f"# {BRAND} 常见问题（{topic}）", ""]
    for i, (q, a) in enumerate(qa, start=1):
        lines.append(f"## Q{i}：{q}")
        lines.append(a)
        lines.append("")
    return "\n".join(lines)


def _inject_noise(md: str, rng: random.Random) -> str:
    """掺入页眉/页脚噪声：页码行 + 品牌水印（同一短行重复 ≥3 次，SP-ING-001 噪声去除验证）。"""
    page_line = rng.choice(["第 1 页", "Page 1 of 8", "页码：1"])
    watermark = rng.choice(NOISE_LINES)  # 同一行重复 3 次 → 命中去重规则（≤20 字符非结构行）
    footer = "\n".join([watermark] * 3)
    return f"{page_line}\n{md}\n{footer}\n"


def generate_docs(out_dir: str | Path, seed: int = 42) -> list[Path]:
    """生成 100 份文档到 out_dir，返回生成的文件路径列表（确定性种子）。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    written: list[Path] = []

    for i in range(1, AFTER_SALES_COUNT + 1):
        md = _render_aftersales(i, rng)
        if rng.random() < NOISE_RATIO:
            md = _inject_noise(md, rng)
        path = out / f"售后政策-{i:02d}.md"
        path.write_text(md, encoding="utf-8")
        written.append(path)

    for i in range(PRODUCT_COUNT):
        md = _render_product(i, rng)
        if rng.random() < NOISE_RATIO:
            md = _inject_noise(md, rng)
        path = out / f"商品手册-{i + 1:02d}.md"
        path.write_text(md, encoding="utf-8")
        written.append(path)

    for i in range(1, FAQ_COUNT + 1):
        md = _render_faq(i, rng)
        if rng.random() < NOISE_RATIO:
            md = _inject_noise(md, rng)
        path = out / f"FAQ-{i:02d}.md"
        path.write_text(md, encoding="utf-8")
        written.append(path)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 100 份演示知识库文档（W1 目标）")
    parser.add_argument("--out", default=str(ROOT / "data" / "raw_docs"), help="输出目录")
    parser.add_argument("--seed", type=int, default=42, help="确定性种子")
    args = parser.parse_args()
    written = generate_docs(args.out, seed=args.seed)
    print(f"已生成 {len(written)} 份文档 → {args.out}（售后政策 {AFTER_SALES_COUNT} / 商品手册 {PRODUCT_COUNT} / FAQ {FAQ_COUNT}）")


if __name__ == "__main__":
    main()
