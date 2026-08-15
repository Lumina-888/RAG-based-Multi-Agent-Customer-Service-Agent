#!/usr/bin/env bash
# SP-DEP-001 冒烟测试（T-DEP-101/102）：health 探测 + 首页 200
# 用法：docker compose up -d --build 后执行 scripts/smoke_test.sh（可 BASE_URL=... 覆盖）
set -uo pipefail
BASE_URL="${BASE_URL:-http://localhost:8000}"
fail=0

echo "== health 探测 =="
health="$(curl -sf -m 5 "$BASE_URL/api/v1/health")" || { echo "[FAIL] /api/v1/health 不可达"; fail=1; }
if [ "$fail" -eq 0 ]; then
  # FastAPI JSONResponse 用紧凑分隔符（"code":0 无空格）；兼容两种格式做容错匹配
  echo "$health" | grep -Eq '"code"[[:space:]]*:[[:space:]]*0' || { echo "[FAIL] health 非 code=0: $health"; fail=1; }
  [ "$fail" -eq 0 ] && echo "[OK] /api/v1/health 200 code=0"
fi

echo "== 首页 200 =="
code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BASE_URL/")"
[ "$code" = "200" ] || { echo "[FAIL] 首页非 200: $code"; fail=1; }
[ "$code" = "200" ] && echo "[OK] 首页 200"

if [ "$fail" -eq 0 ]; then
  echo "SMOKE OK"
else
  echo "SMOKE FAILED"
  exit 1
fi
