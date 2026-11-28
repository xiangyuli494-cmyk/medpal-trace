#!/usr/bin/env bash
# check_cce.sh — B10 验收：CCE pods 全 Running + 集群外 /health 200。
#
# 用法：
#   bash scripts/check_cce.sh                  # 用 kubectl 默认 context，ELB 地址自动从 svc 取
#   ELB=192.168.0.217 bash scripts/check_cce.sh # 手动指定内网 ELB（取不到 svc 时）
#   NS=medpal bash scripts/check_cce.sh
#
# 输出落到 docs/evidence/<timestamp>/：pods.txt / health.json / summary.md
# 两条验收不过即 exit 1；缺 kubectl 或 ELB 地址取不到时明确报错。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

NS="${NS:-medpal}"
SVC="${SVC:-medpal-api-lb}"
PORT="${PORT:-8000}"
ELB="${ELB:-}"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="docs/evidence/$TS"
mkdir -p "$OUT"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "FAIL: kubectl 不在 PATH，B10 必须在能连集群的机器跑" >&2
  exit 1
fi

echo "== 1) kubectl -n $NS get pods"
kubectl -n "$NS" get pods -o wide | tee "$OUT/pods.txt"

# 空 namespace 会假绿：先确认真的有 pod，再看是否全 Running。
n=$(kubectl -n "$NS" get pods --no-headers 2>/dev/null | wc -l)
[ "$n" -ge 1 ] || { echo "FAIL: namespace $NS 里没有 pod（deployment 没 apply？）" >&2; exit 1; }

# 所有 pod 必须 Running 且 READY 全满（本部署 replicas=1，即 1/1）。
bad=$(kubectl -n "$NS" get pods --no-headers 2>/dev/null | awk '$3 != "Running" || $2 != "1/1" {print}')
if [ -n "$bad" ]; then
  echo "FAIL: 有 pod 未就绪：$bad" >&2
  exit 1
fi
echo "   [OK] pods 全 Running"

# ---- 取 ELB 地址 ----
if [ -z "$ELB" ]; then
  ELB=$(kubectl -n "$NS" get svc "$SVC" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
fi
if [ -z "$ELB" ]; then
  echo "FAIL: 拿不到 $SVC 的 LoadBalancer IP。用 ELB=<ip> 手动指定，或先 apply 40-service-lb.yaml" >&2
  exit 1
fi
echo "== 2) 集群外 curl http://$ELB:$PORT/health"
if ! curl -fsS -m 10 "http://$ELB:$PORT/health" -o "$OUT/health.json"; then
  echo "FAIL: 集群外 /health 不通（APIG/ELB 未打通？）" >&2
  echo "  提示：若 Pod 日志出现 relation ... does not exist，先确认 gaussdb.prepare() 是否已补 conn.commit()（#96 的 P0）" >&2
  exit 1
fi
cat "$OUT/health.json"
echo

# 校验返回体 ok=true
if command -v python3 >/dev/null 2>&1; then
  python3 - "$OUT/health.json" <<'PY' || exit 1
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("ok") is True, d
assert d.get("storage") == "gaussdb", f"后端不是 gaussdb：{d.get('storage')}（pod 可能回落 sqlite）"
print("   [OK] /health ok=true, storage=gaussdb")
PY
fi

{
  echo "# B10 验收记录 $TS"
  echo
  echo "- pods 全 Running：是（见 pods.txt）"
  echo "- 集群外 /health 200：是（http://$ELB:$PORT/health，见 health.json）"
} > "$OUT/summary.md"

echo
echo "CCE READY: pods 全 Running + 集群外 /health 200。证据在 $OUT/"