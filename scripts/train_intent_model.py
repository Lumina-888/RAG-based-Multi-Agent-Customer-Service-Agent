"""训练意图模型（SP-DEP-001 启动时训练 / 本地复现）：CSV → fastText txt → bin。

- 输入：data/train/intent_train.csv（label,text，M3 生成）
- 输出：models/intent/fasttext.bin（gitignore，不入库；Docker 启动时缺失则训练）
- 参数与 SP-INT-002 测试一致（epoch=30/lr=0.8/dim=50/word_ngrams=2/seed=42）
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 直接运行 scripts/x.py 时 sys.path[0] 为 scripts/，需显式加入仓库根以导入 app
sys.path.insert(0, str(ROOT))

TRAIN_CSV = ROOT / "data" / "train" / "intent_train.csv"
MODEL_PATH = ROOT / "models" / "intent" / "fasttext.bin"


def _load_rows(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(row["label"], row["text"]) for row in reader]


def main() -> None:
    from app.intent.classifier import train_fasttext

    if not TRAIN_CSV.exists():
        raise SystemExit(f"缺少训练数据 {TRAIN_CSV}（先运行 scripts/gen_intent_data.py）")
    rows = _load_rows(TRAIN_CSV)
    # fasttext 中间格式（__label__ 前缀）写入临时目录，不污染仓库
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as f:
        f.write("\n".join(f"__label__{label} {text}" for label, text in rows))
        train_txt = Path(f.name)
    try:
        train_fasttext(train_txt, MODEL_PATH, epoch=30, lr=0.8, dim=50, word_ngrams=2)
    finally:
        train_txt.unlink(missing_ok=True)
    print(f"[train] 意图模型训练完成: {MODEL_PATH}（{len(rows)} 条样本）")


if __name__ == "__main__":
    sys.exit(main())
