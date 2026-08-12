#!/usr/bin/env bash
# SP-DEP-001 应用容器入口：
# 1) 意图模型缺失时启动训练（fasttext.bin 不入库，模型文件由容器首启生成）
# 2) 启动 FastAPI（uvicorn，0.0.0.0:8000）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f models/intent/fasttext.bin ]; then
  echo "[entrypoint] fasttext.bin 缺失，启动前训练意图模型..."
  python scripts/train_intent_model.py
else
  echo "[entrypoint] 意图模型已存在，跳过训练"
fi

echo "[entrypoint] 启动 uvicorn: app.main:app :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
