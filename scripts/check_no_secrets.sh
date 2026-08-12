#!/usr/bin/env bash
# SP-DEP-002 / T-DEP-201 CI 密钥扫描：
# 占位符（your_*_key_here）与疑似真实密钥（sk-* / AIza*）不得出现在
# docker-compose.yml / Dockerfile / deploy/ / app/ / scripts/ / frontend/src/
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SCOPE="docker-compose.yml Dockerfile deploy app scripts frontend/src"
bad=0

for f in $(find $SCOPE -type f 2>/dev/null); do
  if grep -nE 'your_[a-z_]+_key_here' "$f" 2>/dev/null; then
    echo "[FAIL] 占位符泄漏: $f"; bad=1
  fi
  if grep -nE 'sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}' "$f" 2>/dev/null; then
    echo "[FAIL] 疑似真实密钥: $f"; bad=1
  fi
done

if [ "$bad" -eq 0 ]; then
  echo "SECRET SCAN OK"
else
  echo "SECRET SCAN FAILED"
  exit 1
fi
