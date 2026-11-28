#!/usr/bin/env python3
"""check_pg.py — Postgres/GaussDB 方言层九步自检（B1 交付物）。

在目标 PG 上跑 prepare → seed 8 条三元组 → kg_query，
同时用 SQLite 跑同一套数据做基线，对比两者路径数与结构是否一致。

用法：
    export MEDPAL_DB_DSN="postgresql://user:pass@localhost:5432/medpal"
    python scripts/check_pg.py

九步全绿打印 PG READY 且退出码 0；任一步失败打印原因且退出码 1。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "core"))
sys.path.insert(0, str(ROOT / "apps" / "api"))

SEED_FILE = ROOT / "data" / "ontology" / "seed.jsonl"
SAMPLE = ROOT / "data" / "samples" / "peptic_ulcer_pathway.md"
QUERY_SEED = "消化性溃疡"
MAX_HOPS = 2
EXPECT_PATHS = 8

_steps: list[tuple[str, bool, str]] = []


def _ok(step: str, detail: str = "") -> None:
    _steps.append((step, True, detail))
    print(f"{step:<4s} [OK] {detail}")


def _fail(step: str, detail: str) -> None:
    _steps.append((step, False, detail))
    print(f"{step:<4s} [FAIL] {detail}")


def _dsn() -> str:
    return os.environ.get("MEDPAL_DB_DSN") or os.environ.get("HUAWEI_GAUSSDB_DSN") or ""


def _mask_dsn(dsn: str) -> str:
    """掩码 DSN 里的密码，其余保留（urlsplit 重组，不做全局替换）。"""
    parts = urlsplit(dsn)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    userinfo = ""
    if parts.username:
        userinfo = f"{parts.username}:***@" if parts.password else f"{parts.username}@"
    netloc = f"{userinfo}{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _seed_triples(conn, card, version="v0.9"):
    """灌 8 条三元组，返回 (added_count, triple_ids)。"""
    from medpal_core.ontology import store

    anchors = card["anchors"]
    added, tids = 0, []
    for line in SEED_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        term = t.pop("anchor_term", "")
        anchor = next((a for a in anchors if term and term in (a.get("text") or "")), None)
        if not anchor and anchors:
            anchor = anchors[0]
        t["provenance"] = {"asset_id": card["asset_id"],
                           "anchor_id": anchor["anchor_id"] if anchor else ""}
        tid = store.add_triple(conn, t, version=version)
        if tid:
            added += 1
            tids.append(tid)
    return added, tids


def _path_signature(paths):
    """把 kg_query 的 paths 压成可对比的签名（去掉随机 UUID）。"""
    sig = []
    for p in paths:
        steps_sig = [(s["rel"], s["head_label"], s["tail_label"]) for s in p["steps"]]
        sig.append((p["hops"], p["score"], tuple(p["nodes"]), tuple(steps_sig)))
    return sig


def _run_sqlite_baseline():
    """在临时 SQLite 上跑同一套 seed + kg_query，返回 (paths, triple_count)。"""
    from medpal_core.assets.card import ingest_file
    from medpal_core.assets.entity import default_lexicon
    from medpal_core.ontology import store
    from medpal_core.storage import connect

    tmp = tempfile.mktemp(suffix=".db")
    os.environ["MEDPAL_DB"] = tmp
    try:
        conn = connect()
        card = ingest_file(conn, str(SAMPLE), title="SQLite 基线",
                           source_type="public_standard", ingested_by="check_pg",
                           lexicon=default_lexicon())
        added, _ = _seed_triples(conn, card)
        result = store.kg_query(conn, [QUERY_SEED], max_hops=MAX_HOPS)
        conn.close()
        return result["paths"], added
    finally:
        os.environ.pop("MEDPAL_DB", None)
        Path(tmp).unlink(missing_ok=True)


_TABLES = ("trace", "triple", "version", "asset", "alias", "pending_diff")


def _drop_tables(conn) -> None:
    for t in _TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    # PostgreSQL 的 DROP 也在事务内；close() 会回滚未提交的清理。
    conn.commit()


def main() -> int:
    from medpal_core.assets.card import ingest_file
    from medpal_core.assets.entity import default_lexicon
    from medpal_core.ontology import store
    from medpal_core.ontology import version as onto_version
    from medpal_core.providers.huawei import gaussdb

    print(f"== check_pg.py  ({QUERY_SEED}, max_hops={MAX_HOPS})")
    n = 1

    # 1) 环境变量
    dsn = _dsn()
    if dsn:
        _ok(f"{n})", f"DSN={_mask_dsn(dsn)}")
    else:
        _fail(f"{n})", "缺少 MEDPAL_DB_DSN 或 HUAWEI_GAUSSDB_DSN")
        return 1
    n += 1

    # 2) 驱动
    try:
        import psycopg
        _ok(f"{n})", f"psycopg {psycopg.__version__}")
    except ImportError:
        _fail(f"{n})", "未安装驱动：pip install psycopg[binary]")
        return 1
    n += 1

    # 3) 连接
    try:
        conn = gaussdb.connect(dsn)
        info = conn.execute("SELECT version()").fetchone()
        _ok(f"{n})", info["version"] if info else "connected")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 4) 建表（--reset 先清空上次跑剩的表，否则重跑第 6 步会因去重返回 0 条）
    try:
        if "--reset" in sys.argv:
            host = (urlsplit(dsn).hostname or "").lower()
            if host not in ("127.0.0.1", "localhost", "::1", "") and \
                    "--allow-remote-drop" not in sys.argv:
                _fail(f"{n})", f"拒绝 DROP 重建：host={host} 不是本地，加 --allow-remote-drop")
                return 1
            _drop_tables(conn)
        gaussdb.prepare(conn)
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename"
        ).fetchall()
        tables = [r["tablename"] for r in rows]
        _ok(f"{n})", "schema={} 表：{}".format(
            conn.execute("SELECT current_schema() AS s").fetchone()["s"], ", ".join(tables)))
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 5) 写资产
    try:
        card = ingest_file(conn, str(SAMPLE), title="PG 自检资产",
                           source_type="public_standard", ingested_by="check_pg",
                           lexicon=default_lexicon())
        if not card.get("ok"):
            raise RuntimeError(str(card))
        card2 = ingest_file(conn, str(SAMPLE), title="PG 自检资产 v2",
                            source_type="public_standard", ingested_by="check_pg",
                            lexicon=default_lexicon())
        _ok(f"{n})", f"覆盖后 asset_id = {card2['asset_id']}, blocks = {card2['blocks']}")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 6) 写三元组
    try:
        added, tids = _seed_triples(conn, card2)
        if added != EXPECT_PATHS:
            _fail(f"{n})", f"期望 {EXPECT_PATHS} 条，实际 {added} 条")
            return 1
        _ok(f"{n})", f"{added} 条 added, 首条 triple_id = {tids[0]}")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 7) 版本快照
    try:
        snap = onto_version.snapshot(conn, "v-pgtest", note="check_pg 自检快照")
        _ok(f"{n})", f"v-pgtest triple_count={snap['triple_count']} hash={snap['manifest_hash']}")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 8) kg_query 对比 SQLite
    try:
        pg_result = store.kg_query(conn, [QUERY_SEED], max_hops=MAX_HOPS)
        pg_paths = pg_result["paths"]
        sqlite_paths, sqlite_added = _run_sqlite_baseline()

        pg_sig = _path_signature(pg_paths)
        sqlite_sig = _path_signature(sqlite_paths)

        if len(pg_paths) != EXPECT_PATHS:
            _fail(f"{n})", f"PG 路径数 {len(pg_paths)} != 期望 {EXPECT_PATHS}")
            return 1
        if pg_sig != sqlite_sig:
            _fail(f"{n})", f"PG 与 SQLite 路径结构不一致\n  PG={pg_sig}\n  SQLite={sqlite_sig}")
            return 1
        _ok(f"{n})", f"PG 路径数={len(pg_paths)}, SQLite 路径数={len(sqlite_paths)}, 结构一致")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 9) 清理（--keep 时保留表，供随后 seed + api 步复用同一批数据）
    try:
        if "--keep" in sys.argv:
            conn.close()
            _ok(f"{n})", "保留测试表（--keep），供 api 步继续验证")
            print("\nPG READY: " + (dsn.split("@")[-1] if "@" in dsn else dsn))
            return 0
        host = (urlsplit(dsn).hostname or "").lower()
        allow_remote = "--allow-remote-drop" in sys.argv
        if host not in ("127.0.0.1", "localhost", "::1", "") and not allow_remote:
            _fail(f"{n})", f"拒绝 DROP：host={host} 不是本地，加 --allow-remote-drop 强制")
            return 1
        _drop_tables(conn)
        conn.close()
        _ok(f"{n})", "已 DROP 全部测试表并关闭连接")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1

    # 汇总
    host = dsn.split("@")[-1] if "@" in dsn else dsn
    print(f"\nPG READY: {host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
