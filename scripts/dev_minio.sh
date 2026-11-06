#!/usr/bin/env bash
# dev_minio.sh — 一键起本地 MinIO（顶替 OBS）+ 跑对象存储自检（B2 交付物）。
#
# 用法：
#   bash scripts/dev_minio.sh                  起容器 + 建桶 + 自检
#   bash scripts/dev_minio.sh --down           停并删容器
#   MINIO_PORT=9100 bash scripts/dev_minio.sh  换端口
#
# 验收标准（B2）：上传返回可下载地址；原件与下载件 sha256 一致；桶内能 ls 到对象。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTAINER="medpal-minio"
MINIO_PORT="${MINIO_PORT:-9000}"
CONSOLE_PORT="${CONSOLE_PORT:-9001}"
MINIO_USER="${MINIO_USER:-minioadmin}"
MINIO_PASS="${MINIO_PASS:-minioadmin}"
BUCKET="${HUAWEI_OBS_BUCKET:-medpal-trace-cn4}"
# MinIO 默认 region 是 us-east-1；OBS SDK 的 v4 签名要跟它一致，否则 403。
MINIO_REGION="${MINIO_REGION:-us-east-1}"
IMAGE="minio/minio:latest"

PY="${PY:-python}"
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$ROOT/packages/core:$ROOT/apps/api"

# ---- --down：停容器 ----
if [ "${1:-}" = "--down" ]; then
  echo "停容器 $CONTAINER ..."
  docker rm -f "$CONTAINER" 2>/dev/null || true
  echo "done"
  exit 0
fi

# ---- 前置检查 ----
if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL: docker 不在 PATH，先装 Docker 或用 Podman" >&2
  exit 1
fi

# ---- 起容器（已存在就复用）----
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "复用已运行的容器 $CONTAINER"
else
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker rm -f "$CONTAINER" >/dev/null
  fi
  echo "起 $IMAGE（端口 $MINIO_PORT -> 9000, $CONSOLE_PORT -> 9001）..."
  docker run -d --name "$CONTAINER" \
    -e MINIO_ROOT_USER="$MINIO_USER" \
    -e MINIO_ROOT_PASSWORD="$MINIO_PASS" \
    -e MINIO_REGION="$MINIO_REGION" \
    -p "$MINIO_PORT:9000" \
    -p "$CONSOLE_PORT:9001" \
    "$IMAGE" server /data --console-address ":9001" >/dev/null
fi

# ---- 等 MinIO 就绪（健康检查端点）----
echo -n "等 MinIO 就绪"
ready=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$MINIO_PORT/minio/health/live" >/dev/null 2>&1; then
    echo " ok"
    ready=1
    break
  fi
  echo -n "."
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo " 超时"
  echo "FAIL: MinIO 30 秒内没就绪" >&2
  exit 1
fi

# ---- 装 esdk-obs-python（如果没装）----
if ! "$PY" -c "import obs" 2>/dev/null; then
  echo "装 esdk-obs-python ..."
  "$PY" -m pip install -q esdk-obs-python || {
    echo "FAIL: esdk-obs-python 装不上" >&2; exit 1; }
fi

# ---- 设环境变量 + 跑自检 ----
export HUAWEI_OBS_ENDPOINT="http://127.0.0.1:$MINIO_PORT"
export HUAWEI_AK="$MINIO_USER"
export HUAWEI_SK="$MINIO_PASS"
export HUAWEI_OBS_BUCKET="$BUCKET"
export HUAWEI_REGION="$MINIO_REGION"

echo "endpoint=http://127.0.0.1:$MINIO_PORT, bucket=$BUCKET, region=$MINIO_REGION"
echo "== check_obs.py"
echo

if "$PY" scripts/check_obs.py; then
  echo
  echo "PASS: B2 验收通过（MinIO 顶替 OBS：上传/下载 sha256 一致/ls 可见）"
  exit 0
else
  echo
  echo "FAIL: check_obs.py 未通过" >&2
  exit 1
fi