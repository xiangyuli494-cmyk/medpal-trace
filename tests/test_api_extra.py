"""补两个看板承诺过、但端点一度缺席的查询：资产详情与版本列表。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from app.main import app

    return TestClient(app)


def test_asset_detail(seeded):
    c = _client()
    items = c.get("/v1/assets").json()["items"]
    aid = items[0]["asset_id"]
    r = c.get("/v1/assets/" + aid)
    assert r.status_code == 200
    assert r.json()["item"]["asset_id"] == aid


def test_asset_detail_404(seeded):
    r = _client().get("/v1/assets/AST-2026-doesnotexist")
    assert r.status_code == 404
    assert r.json()["detail"]["reason"] == "asset_not_found"


def test_versions_list(seeded):
    body = _client().get("/v1/ontology/versions").json()
    assert body["ok"]
    assert body["items"], "seed 之后至少要有一个版本"
    top = body["items"][0]
    assert top["version"] == "v1.0"
    assert top["is_current"] == 1


def test_schema_accepts_refusal():
    from jsonschema import Draft202012Validator

    from medpal_core.contracts.trace import load_schema

    schema = load_schema()
    trace = {
        "schema": "medpal-trace/1",
        "trace_id": "TR-20261101-ABCD",
        "question": "问句",
        "agent_version": "v1.0-cloud",
        "ontology_version": "v1.0",
        "steps": [{"i": 1, "op": "conclude", "evidence": []}],
        "gaps": ["没有可用证据"],
        "trace_completeness": 1.0,
        "refusal": True,
    }
    Draft202012Validator(schema).validate(trace)
