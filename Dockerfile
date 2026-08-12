# SP-DEP-001 多阶段构建：stage1 前端（node）→ stage2 Python 应用 + 静态产物
# 产物：FastAPI 单镜像托管 API + 前端 dist（app/static）

# ---------- stage1: 前端构建 ----------
FROM node:20-alpine AS frontend
WORKDIR /build/frontend
# 先拷锁文件 → npm ci（利用层缓存）
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---------- stage2: Python 应用 ----------
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/
COPY data/ data/
COPY models/ models/
# 前端产物打进 FastAPI 静态目录（SP-DEP-001：单镜像托管）
COPY --from=frontend /build/frontend/dist/ app/static/

RUN chmod +x scripts/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
