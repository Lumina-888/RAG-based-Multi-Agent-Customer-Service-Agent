"""SP-INT-002 轻量分类器（fastText，可插拔）。

- `FastTextIntentClassifier`：加载 `models/intent/fasttext.bin`（启动时加载），
  `predict(text)` → `IntentResult{intent, conf}`；非法输入直接返回 invalid
- `train_fasttext(train_txt, output_path, ...)`：训练并落盘（产物 models/intent/fasttext.bin）
- `FakeIntentClassifier`：CI 单测注入，不依赖真实模型
- 注意：fastText softmax 概率未校准，0.85/0.6 决策阈值在验证集校准后写入配置
  （SP-INT-002 产物约定）
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.intent.labels import INVALID_INTENT, is_valid_input

logger = logging.getLogger("app.intent.classifier")


@dataclass
class IntentResult:
    """分类结果：意图 + 置信度（0~1）。"""

    intent: str
    conf: float


class IntentClassifier(Protocol):
    """分类器协议：Fake 与 fastText 实现同一接口（SP-CFG-004 同模式）。"""

    model_name: str

    async def predict(self, text: str) -> IntentResult: ...


def parse_fasttext_label(label: str) -> str:
    """fastText 标签 `__label__refund` → `refund`。"""
    return label.removeprefix("__label__")


class FastTextIntentClassifier:
    """fastText 监督分类器（加载训练产物，预测为同步快操作）。"""

    def __init__(self, model: Any, model_name: str = "fasttext.bin") -> None:
        self._model = model
        self.model_name = model_name

    @classmethod
    def load(cls, model_path: str | Path) -> "FastTextIntentClassifier":
        import fasttext  # 延迟导入：模型缺失时模块可导入

        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"意图模型不存在: {path}（先运行训练，见 SP-INT-002）")
        logger.info("加载意图模型 %s", path)
        return cls(fasttext.load_model(str(path)), model_name=path.name)

    async def predict(self, text: str) -> IntentResult:
        if not is_valid_input(text):
            return IntentResult(intent=INVALID_INTENT, conf=0.0)
        labels, probs = await asyncio.to_thread(self._model.predict, text.strip(), k=1)
        # fastText softmax 概率浮点误差可能略超 1.0，钳制到 [0,1]（SP-INT-003 阈值稳定）
        conf = min(max(float(probs[0]), 0.0), 1.0)
        return IntentResult(intent=parse_fasttext_label(labels[0]), conf=conf)


class FakeIntentClassifier:
    """测试注入的假分类器：可配置返回意图/置信度，记录调用历史。

    与真实分类器协议一致：非法输入（空串/超长）同样返回 invalid。
    """

    def __init__(self, intent: str = "after_sales", conf: float = 0.9) -> None:
        self.intent = intent
        self.conf = conf
        self.model_name = "fake"
        self.calls: list[str] = []

    def predict_sync(self, text: str) -> IntentResult:
        if not is_valid_input(text):
            return IntentResult(intent=INVALID_INTENT, conf=0.0)
        return IntentResult(intent=self.intent, conf=self.conf)

    async def predict(self, text: str) -> IntentResult:
        self.calls.append(text)
        return self.predict_sync(text)


def train_fasttext(
    train_txt: str | Path,
    output_path: str | Path,
    epoch: int = 30,
    lr: float = 0.8,
    dim: int = 50,
    word_ngrams: int = 2,
    seed: int = 42,
    bucket: int = 10000,
) -> FastTextIntentClassifier:
    """训练 fastText 监督模型并落盘（SP-INT-002 产物 models/intent/fasttext.bin）。

    返回可加载的分类器；训练参数以确定性种子保证可复现。
    注：`bucket` 哈希桶数需显式调小（默认 200 万桶 → 模型数百 MB，本项目语料
    词汇量小，1 万桶足够且模型 < 1MB）。
    """
    import fasttext

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    model = fasttext.train_supervised(
        str(train_txt),
        epoch=epoch,
        lr=lr,
        dim=dim,
        wordNgrams=word_ngrams,
        seed=seed,
        bucket=bucket,
        loss="softmax",
    )
    model.save_model(str(output))
    logger.info("意图模型训练完成 → %s", output)
    return FastTextIntentClassifier(model, model_name=output.name)
