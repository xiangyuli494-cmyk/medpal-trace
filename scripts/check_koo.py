#!/usr/bin/env python3
"""check_koo.py — KooSearch 云端检索自检（C5 交付物）。

四步：环境变量 -> provider 就绪 -> 真发一次检索 -> 命中结构合规。
和 check_pg.py / check_obs.py 同风格：全绿打印 KOO READY 退出 0，失败退出 1。

两种方言（由有没有 HUAWEI_KOOSEARCH_APP_ID + _REPO_ID 决定）：
    searchtext  华为云真实接口 /v1/{project_id}/applications/{app_id}/uni-search/experience/searchtext
    raw         老口径，{"query","top_k"} 直接 POST 到 endpoint
searchtext 下必须能拿到 X-Auth-Token：给 HUAWEI_KOOSEARCH_TOKEN，
或用 HUAWEI_IAM_USER / HUAWEI_IAM_PASSWORD（/ _DOMAIN）现换。

锚点（asset_id#anchor_id）来自文档的 additional_fields 或 tags。
拿不到不算失败，只算「溯源断链」——自检里按 WARN 报锚点率，别把没锚点当检索坏了。

用法（仓库根目录）：
    PYTHONPATH=packages/core:apps/api HUAWEI_KOOSEARCH_ENDPOINT=https://... \
      python scripts/check_koo.py
    python scripts/check_koo.py --strict     # 未配置、零召回、零锚点均失败（C5 验收）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "core"))
sys.path.insert(0, str(ROOT / "apps" / "api"))

QUERY = "消化性溃疡 上腹痛 该做什么检查"


def _auth_mode(cfg) -> str:
    if cfg.koosearch_token:
        return "HUAWEI_KOOSEARCH_TOKEN"
    if cfg.iam_user and cfg.iam_password:
        return "IAM 用户密码换 token（" + cfg.iam_user + "）"
    return "(无)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KooSearch 检索自检")
    ap.add_argument("--strict", action="store_true", help="未配置、零召回或零锚点均判失败")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args(argv)

    from medpal_core.providers.huawei.config import load_config
    from medpal_core.providers.huawei.koosearch import KooSearchRetriever

    cfg = load_config()
    ready = cfg.readiness()
    print("endpoint =", cfg.koosearch_endpoint or "(空)")
    print("region   =", cfg.region)
    print("dialect  =", cfg.koosearch_dialect)
    if cfg.koosearch_dialect == "searchtext":
        print("project  =", cfg.project_id or "(空，URL 拼不出来)")
        print("app_id   =", cfg.koosearch_app_id)
        print("repo_id  =", cfg.koosearch_repo_id)
        print("auth     =", _auth_mode(cfg))

    if not ready["koosearch"]:
        msg = ("SKIP  HUAWEI_KOOSEARCH_ENDPOINT 未配置"
               if not cfg.koosearch_endpoint else
               "SKIP  searchtext 配置不全：检查 PROJECT_ID / APP_ID / REPO_ID 与鉴权信息")
        if args.strict:
            print("FAIL  " + msg + "，--strict 下按失败处理")
            return 1
        print(msg)
        return 0

    r = KooSearchRetriever(cfg)
    if not r.available():
        print("FAIL  provider 说未就绪，但环境变量看似齐全 —— 检查 load_config 的判定")
        return 1
    print("STEP1 [OK] provider 就绪，URL =", _safe_url(r))
    print("STEP2 [OK] 方言 =", r.dialect)

    try:
        hits = r.search(QUERY, top_k=args.top_k)
    except Exception as exc:
        print("FAIL  检索调用失败:", type(exc).__name__, str(exc)[:300])
        if cfg.koosearch_dialect == "searchtext":
            print("      排查顺序：project_id / app_id / repo_id 是否正确；"
                  "KooSearch 的 API 是否已在 APIG 发布到环境；token 是否过期")
        return 1
    print("STEP3 [OK] 检索返回", len(hits), "条")

    if not hits:
        print("WARN  0 命中：端点通但索引里没有这批文档")
        if cfg.koosearch_dialect == "searchtext":
            print("      检查 repo_id 下是否已上传文档并完成解析（知识库 -> 文档管理）")
        if args.strict:
            print("FAIL  --strict 要求非空召回，不能以 0 hits 验收 C5")
            return 1
        print("KOO READY (0 hits)")
        return 0

    bad = [i for i, h in enumerate(hits) if not getattr(h, "text", "")]
    if bad:
        print("FAIL  命中缺正文，索引下标:", json.dumps(bad))
        return 1
    anchored = [h for h in hits if getattr(h, "anchor_id", "")]
    if args.strict and not anchored:
        print("FAIL  --strict 要求至少一条带锚点的命中")
        return 1
    rate = round(len(anchored) / len(hits), 2)
    print("STEP4 [OK] 命中结构合规；锚点率", str(int(rate * 100)) + "%")
    if rate < 1:
        print("WARN  有命中没有锚点：这些条目进不了 evidence（不进溯源链，也不扣完整率）")
        print("      解决：上传文档时把 asset_id / anchor_id 写进 additional_fields，"
              "或标签写成 asset_id=AST-xxx / anchor_id=a3")
    print("sample =", json.dumps({"asset_id": hits[0].asset_id,
                                  "anchor_id": hits[0].anchor_id,
                                  "score": hits[0].score,
                                  "text": (hits[0].text or "")[:60]},
                                 ensure_ascii=False))
    print("KOO READY")
    return 0


def _safe_url(retriever) -> str:
    try:
        return retriever.url()
    except Exception as exc:  # 缺 project_id 之类，如实说出来
        return "(URL 拼不出：" + str(exc)[:80] + ")"


if __name__ == "__main__":
    raise SystemExit(main())
