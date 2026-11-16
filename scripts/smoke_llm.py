"""云端模型冒烟 + B8 联调：单次连通、连续 N 次 P95、断网 llm_error。

用法（仓库根目录）：
    PYTHONPATH=packages/core:apps/api python scripts/smoke_llm.py
    MEDPAL_LLM=modelarts MEDPAL_LLM_BASE_URL=https://api.modelarts-maas.com/v1 \
      MEDPAL_LLM_MODEL=deepseek-v3 MEDPAL_LLM_API_KEY=sk-xxx \
      python scripts/smoke_llm.py --strict --soak 10

三种模式：
    默认           —— 没配模型时打印 SKIP 并退出 0（本地 verify 不该因为没买模型而红）
    --strict       —— 没配模型也算失败（答辩前「模型到底通没通」用它）
    --soak N       —— 连续调用 N 次，统计 P50/P95；B8 要求 10 次 P95 < 8s
    --offline-sim  —— 断网模拟（坏 base_url 走 pipeline），验证接口仍 200 且带 llm_error

它能证明三件事，正是 B8 答辩要说清的：
    1) base_url 是活的 —— 401/403 说明域名和鉴权层正常，只差有效 key；
    2) 有 key 时 narrative 真的来自云上模型，而不是 FakeLLM 的 [offline] 前缀；
    3) 模型挂了（断网/超时）整条链不崩，接口 200 且 conclusion.llm_error 有值。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from medpal_core.config import settings
from medpal_core.llm import FakeLLM, build_llm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_SYSTEM = "你只回答一个词。"
PROBE_USER = "回复：ok"


def _offline_sim() -> int:
    """用 TestClient 打 POST /v1/ask，断网时验 HTTP 200 + conclusion.llm_error + trace 落库。

    注意：不能直接调 pipeline.answer() 来判断「接口仍 200」——那绕过了路由层，
    即使 answer() 抛异常也测不出来。这里走 FastAPI 的 TestClient，验的是真实端点。
    """
    sys.path.insert(0, os.path.join(ROOT, "apps", "api"))

    # 断网：模型端点指到没人监听的端口；同时确保用默认 SQLite，不受外部 DSN 影响
    for k in ("MEDPAL_DB_DSN", "MEDPAL_DB_BACKEND"):
        os.environ.pop(k, None)
    os.environ["MEDPAL_LLM"] = "openai"
    os.environ["MEDPAL_LLM_BASE_URL"] = "http://127.0.0.1:59999/v1"
    os.environ["MEDPAL_LLM_MODEL"] = "fake"
    os.environ["MEDPAL_LLM_API_KEY"] = "sk-fake"

    from fastapi.testclient import TestClient  # noqa: E402

    from app.main import app  # noqa: E402

    with TestClient(app) as client:
        r = client.post("/v1/ask", json={"question": "消化性溃疡怎么治？"})
        if r.status_code != 200:
            print(f"FAIL  断网时 /v1/ask 返回 {r.status_code}（应 200）")
            return 1
        out = r.json()
        tid = out.get("trace_id")
        if not tid:
            print("FAIL  断网时没有返回 trace_id")
            return 1
        back = client.get(f"/v1/traces/{tid}")
        if back.status_code != 200:
            print(f"FAIL  trace 未落库：GET /v1/traces/{tid} -> {back.status_code}")
            return 1

    conclusion = out.get("conclusion") or {}
    err = conclusion.get("llm_error")
    narrative = conclusion.get("narrative")
    if not err:
        print("FAIL  断网时 conclusion.llm_error 未写入")
        return 1
    if narrative:
        print("FAIL  断网时不该有 conclusion.narrative:", str(narrative)[:80])
        return 1
    print("OK    /v1/ask 200 + trace 落库，llm_error =", str(err)[:120])
    return 0


def _soak(llm, n: int) -> int:
    times = []
    for i in range(n):
        t0 = time.perf_counter()
        try:
            out = llm.complete(PROBE_SYSTEM, PROBE_USER)
        except Exception as exc:
            print(f"FAIL  第 {i + 1}/{n} 次调用失败:", type(exc).__name__, str(exc)[:160])
            return 1
        times.append(time.perf_counter() - t0)
        if not out.strip():
            print(f"FAIL  第 {i + 1}/{n} 次返回空内容")
            return 1
    times.sort()
    n_ok = len(times)
    p50 = times[n_ok // 2]
    p95 = times[max(0, min(n_ok - 1, int(n_ok * 0.95)))]
    print(f"OK    {n_ok} 次调用  P50={p50:.2f}s  P95={p95:.2f}s  max={times[-1]:.2f}s")
    if p95 >= 8.0:
        print("FAIL  P95 >= 8s（B8 门槛 8s）")
        return 1
    print("       P95 < 8s，B8 延迟门槛通过")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="云端模型连通性冒烟")
    ap.add_argument("--strict", action="store_true", help="没配模型也判失败")
    ap.add_argument("--timeout", type=float, default=30.0, help="单次调用超时秒数")
    ap.add_argument("--soak", type=int, default=0, help="连续调用 N 次并统计 P50/P95")
    ap.add_argument("--offline-sim", action="store_true",
                    help="断网模拟：坏 base_url 走 pipeline，验证 llm_error")
    args = ap.parse_args(argv)

    # 断网模拟不需要模型配置，先于 SKIP 判断。
    if args.offline_sim:
        return _offline_sim()

    cfg = settings()
    print("provider =", cfg.llm_provider)
    print("base_url =", cfg.llm_base_url or "(空)")
    print("model    =", cfg.llm_model or "(空)")
    print("api_key  =", "已配置" if cfg.llm_api_key else "(空)")

    if cfg.llm_provider == "offline" or not cfg.llm_base_url or not cfg.llm_model:
        msg = "SKIP  模型未配置（MEDPAL_LLM / MEDPAL_LLM_BASE_URL / MEDPAL_LLM_MODEL）"
        if args.strict:
            print("FAIL  " + msg + "，--strict 下按失败处理")
            return 1
        print(msg)
        return 0

    try:
        llm = build_llm()
    except Exception as exc:
        print("FAIL  构建模型客户端失败:", type(exc).__name__, str(exc)[:200])
        return 1
    if isinstance(llm, FakeLLM):
        print("FAIL  provider 说是云端，实际拿到 FakeLLM —— 配置没生效")
        return 1

    llm.timeout = args.timeout
    try:
        out = llm.complete(PROBE_SYSTEM, PROBE_USER)
    except Exception as exc:
        text = str(exc)
        print("FAIL  调用失败:", type(exc).__name__, text[:300])
        hint = ""
        if "401" in text or "403" in text:
            hint = "鉴权被拒：域名是通的，换一个有效 MEDPAL_LLM_API_KEY 即可"
        elif "400" in text:
            hint = "请求被拒：多半是 MEDPAL_LLM_MODEL 不在该端点的可用模型列表里"
        elif "Timeout" in text or "timed out" in text.lower():
            host = cfg.llm_base_url.split("//", 1)[-1].split("/", 1)[0]
            hint = "超时：本机到 " + host + " 可能要走出口代理（HTTPS_PROXY / 本机 http.proxy 配置）"
        if hint:
            print("      " + hint)
        return 1

    if not out.strip():
        print("FAIL  模型返回空内容")
        return 1
    print("OK    云端模型可用；返回片段:", out.strip().replace(chr(10), " ")[:120])

    if args.soak > 0:
        return _soak(llm, args.soak)
    return 0


if __name__ == "__main__":
    sys.exit(main())