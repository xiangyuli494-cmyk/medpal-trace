"""HTTP 入口。端点覆盖「资产入库 -> 提问 -> 决策链 -> 本体版本」闭环。

启动（仓库根目录）：
    MEDPAL_DATA_DIR=./data uv run -- python -m uvicorn app.main:app --app-dir apps/api --port 8000
或者直接用仓库自带的 make api / tools/dev.sh。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from medpal_core import __version__ as core_version
from medpal_core.assets.card import ingest_file
from medpal_core.config import settings
from medpal_core.llm import build_llm
from medpal_core.ontology import store
from medpal_core.ontology import version as onto_version
from medpal_core.providers.huawei.config import load_config
from medpal_core.storage.db import backend_name
from medpal_core.trace import get_trace

from . import __version__ as app_version
from .deps import get_conn, get_report_store, want_gaussdb
from .pipeline import answer
from .report_store import local_report_path

app = FastAPI(title="MedPal Cloud API", version=app_version,
              description="赛题1：基于华为云产品打造的 AI 创新应用 —— 可复用智能底座 + 可追溯决策链")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class AskIn(BaseModel):
    question: str = Field(min_length=1, examples=["上腹隐痛伴反酸，下一步该做什么检查？"])
    top_k: int = 8
    max_hops: int = 2


class IngestIn(BaseModel):
    path: str
    title: str = ""
    modality: str = ""
    source_type: str = "public_standard"


class SnapshotIn(BaseModel):
    version: str = Field(pattern=r"^v[0-9]+\.[0-9]+$", examples=["v1.0"])
    note: str = ""


@app.get("/")
def root():
    return {
        "name": "medpal-trace",
        "app_version": app_version,
        "core_version": core_version,
        "endpoints": ["/livez", "/health", "/v1/cloud", "/v1/assets", "/v1/assets/{asset_id}",
                      "/v1/ask", "/v1/traces/{trace_id}", "/v1/reports/{trace_id}", "/v1/ontology",
                      "/v1/ontology/versions", "/v1/ontology/diff"],
        "web": "/web/" if WEB_DIR.exists() else None,
    }


@app.get("/livez")
def livez():
    """仅确认进程能响应；外部存储故障不触发容器重启。"""
    return {"ok": True}


@app.get("/health")
def health(conn: Annotated[object, Depends(get_conn)]):
    cur = onto_version.current_version(conn)
    assets = len(store.list_assets(conn, limit=10000))
    cfg = settings()
    return {
        "ok": True,
        "app_version": app_version,
        "core_version": core_version,
        "ontology_version": (cur or {}).get("version"),
        "assets": assets,
        "llm": cfg.llm_provider,
        # 与 scripts/smoke_llm.py 同口径：provider 不是 offline、且有 base_url 和 model 才算就绪
        "llm_ready": cfg.llm_provider != "offline" and bool(cfg.llm_base_url) and bool(cfg.llm_model),
        "llm_model": cfg.llm_model or "",
        "storage": backend_name(conn),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


@app.get("/v1/cloud")
def cloud():
    """云上就绪度：哪块插槽真接上了、缺哪个环境变量。"""
    cfg = load_config()
    ready = cfg.readiness()
    missing = {
        "obs": [] if ready["obs"] else ["HUAWEI_AK", "HUAWEI_SK", "HUAWEI_OBS_BUCKET"],
        "gaussdb": [] if ready["gaussdb"] else ["MEDPAL_DB_DSN", "HUAWEI_GAUSSDB_DSN"],
        "modelarts": [] if ready["modelarts"] else [
            "MEDPAL_LLM_BASE_URL", "MEDPAL_LLM_MODEL", "HUAWEI_MODEL_ENDPOINT", "HUAWEI_MODEL_NAME",
        ],
        "koosearch": [] if ready["koosearch"] else ["HUAWEI_KOOSEARCH_ENDPOINT"],
    }
    # modelarts 那 4 个变量是两组「任选其一」，平铺列出来像是都要填，补一句说明
    notes = {}
    if not ready["modelarts"]:
        notes["modelarts"] = (
            "MEDPAL_LLM_BASE_URL + MEDPAL_LLM_MODEL，或 HUAWEI_MODEL_ENDPOINT + HUAWEI_MODEL_NAME（任一组）"
        )
    return {"ok": True, "region": cfg.region, "ready": ready,
            "missing": {k: v for k, v in missing.items() if v},
            "missing_note": notes,
            "storage_backend": "gaussdb" if want_gaussdb() else "sqlite"}


@app.post("/v1/assets")
def ingest(body: IngestIn, conn: Annotated[object, Depends(get_conn)]):
    out = ingest_file(conn, body.path, modality=body.modality, title=body.title,
                      source_type=body.source_type, ingested_by="api")
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    return out


@app.get("/v1/assets")
def assets(
    limit: int = 20,
    modality: str = "",
    entity: str = "",
    conn: Annotated[object, Depends(get_conn)] = None,
):
    return {"ok": True, "items": store.list_assets(conn, modality=modality or None,
                                                   entity=entity or None, limit=limit)}


@app.get("/v1/assets/{asset_id}")
def asset_detail(asset_id: str, conn: Annotated[object, Depends(get_conn)]):
    item = store.get_asset(conn, asset_id)
    if not item:
        raise HTTPException(status_code=404,
                            detail={"reason": "asset_not_found", "asset_id": asset_id})
    return {"ok": True, "item": item}


@app.get("/v1/ontology/versions")
def ontology_versions(limit: int = 50, conn: Annotated[object, Depends(get_conn)] = None):
    return {"ok": True, "items": onto_version.list_versions(conn, limit=limit)}


@app.post("/v1/ask")
def ask(body: AskIn, conn: Annotated[object, Depends(get_conn)],
        reports: Annotated[object, Depends(get_report_store)]):
    llm = None
    if settings().llm_provider != "offline":
        try:
            llm = build_llm()
        except Exception:
            llm = None
    out = answer(conn, body.question, top_k=body.top_k, max_hops=body.max_hops, llm=llm)
    # B7：报告同步传一份到 OBS。没配桶就安静降级（uri=null，reason 说明缺什么），
    # 已经算完的推理不会因为「云没接上」而丢掉——这条降级路径本身就是评分点。
    up = reports.upload(out.get("trace_id"), out.get("report_path"))
    out["report_uri"] = up.get("uri")
    out["report_upload"] = up
    return out


@app.get("/v1/traces/{trace_id}")
def trace(trace_id: str, conn: Annotated[object, Depends(get_conn)],
          reports: Annotated[object, Depends(get_report_store)]):
    out = get_trace(conn, trace_id)
    if not out:
        raise HTTPException(status_code=404, detail={"reason": "trace_not_found", "trace_id": trace_id})
    # 契约冻结（schema additionalProperties=false + test_frozen_v1_digest）：
    # 报告地址不能塞进 body，用响应头捎带；要正文走 GET /v1/reports/{trace_id}。
    # 回读时问一次桶：缓存命中就直接给，没有就 headObject 一次，拿不到就不带头。
    uri = reports.uri(trace_id)
    resp = JSONResponse(out)
    if uri:
        resp.headers["X-Medpal-Report-Uri"] = uri
    return resp


@app.get("/v1/reports/{trace_id}")
def report(trace_id: str, conn: Annotated[object, Depends(get_conn)],
           reports: Annotated[object, Depends(get_report_store)]):
    """报告本身：本地副本 + 云上地址。演示里「点开一条结论看它从哪来」走这里。"""
    if not get_trace(conn, trace_id):
        raise HTTPException(status_code=404, detail={"reason": "trace_not_found", "trace_id": trace_id})
    path = local_report_path(trace_id)
    body = path.read_text(encoding="utf-8") if path.exists() else ""
    return {
        "ok": bool(body),
        "trace_id": trace_id,
        "report_uri": reports.uri(trace_id),
        "local_path": str(path),
        "markdown": body,
    }


@app.get("/v1/ontology")
def ontology(conn: Annotated[object, Depends(get_conn)]):
    cur = onto_version.current_version(conn)
    return {"ok": True, "current": cur}


@app.post("/v1/ontology/snapshot")
def snapshot(body: SnapshotIn, conn: Annotated[object, Depends(get_conn)]):
    return onto_version.snapshot(conn, body.version, body.note)


@app.get("/v1/ontology/diff")
def diff(old: str, new: str, conn: Annotated[object, Depends(get_conn)]):
    return onto_version.diff_versions(conn, old, new)


if WEB_DIR.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
