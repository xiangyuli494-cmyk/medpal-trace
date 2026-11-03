"""本体版本：快照、当前版本、两版差分。

「可进化」的可观测证据就是这里：同一批问题在 v0.9 / v1.0 下答案会变，且变化能 diff 出来。
"""

from __future__ import annotations

import hashlib
import json

from ..storage.db import data_dir, now


def snapshot(conn, version, note=""):
    rows = conn.execute(
        "SELECT triple_id,head_id,rel,tail_id,confidence,asset_id,anchor_id FROM triple "
        "WHERE status='active' ORDER BY triple_id"
    ).fetchall()
    payload = "\n".join(
        r["triple_id"]
        + "|"
        + r["head_id"]
        + "|"
        + r["rel"]
        + "|"
        + r["tail_id"]
        + "|"
        + "{:.3f}".format(r["confidence"])
        for r in rows
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    conn.execute("UPDATE version SET is_current = 0")
    conn.execute(
        "INSERT INTO version "
        "(version,created_at,triple_count,manifest_hash,note,is_current) "
        "VALUES (?,?,?,?,?,1) "
        "ON CONFLICT(version) DO UPDATE SET "
        "created_at=excluded.created_at,triple_count=excluded.triple_count,"
        "manifest_hash=excluded.manifest_hash,note=excluded.note,"
        "is_current=excluded.is_current",
        (version, now(), len(rows), digest, note),
    )
    conn.commit()
    path = data_dir() / ("ontology_" + version + ".jsonl")
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    return {
        "version": version,
        "triple_count": len(rows),
        "manifest_hash": digest,
        "snapshot_path": str(path),
        "created_at": now(),
    }


def current_version(conn):
    row = conn.execute("SELECT * FROM version WHERE is_current = 1").fetchone()
    return dict(row) if row else None


def diff_versions(conn, old, new):
    def load(v):
        p = data_dir() / ("ontology_" + v + ".jsonl")
        if not p.exists():
            return {}
        out = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["triple_id"]] = (d["head_id"], d["rel"], d["tail_id"], d["confidence"])
        return out

    a, b = load(old), load(new)
    added = [{"triple_id": k, "signature": list(b[k])} for k in sorted(b.keys() - a.keys())]
    removed = [{"triple_id": k, "signature": list(a[k])} for k in sorted(a.keys() - b.keys())]
    modified = [
        {"triple_id": k, "old": list(a[k]), "new": list(b[k])}
        for k in sorted(a.keys() & b.keys())
        if a[k][:3] != b[k][:3] or abs(a[k][3] - b[k][3]) > 1e-6
    ]
    return {
        "old": old,
        "new": new,
        "added": added,
        "removed": removed,
        "modified": modified,
        "counts": {"added": len(added), "removed": len(removed), "modified": len(modified)},
    }


def list_versions(conn, limit=50):
    """版本列表，新到旧。GET /v1/ontology/versions 用。"""
    rows = conn.execute(
        "SELECT version,created_at,triple_count,manifest_hash,note,is_current "
        "FROM version ORDER BY created_at DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]
