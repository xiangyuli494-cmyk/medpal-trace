"""KooSearch 适配层：两种方言、锚点映射、401 刷新、IAM token 缓存。"""

from __future__ import annotations

import pytest

from medpal_core.providers.huawei import iam
from medpal_core.providers.huawei.config import HuaweiConfig, ProviderNotConfigured
from medpal_core.providers.huawei.koosearch import KooSearchRetriever


class FakeResp:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("unexpected status " + str(self.status_code))


class FakeClient:
    """按顺序返回预置响应，并记录每次请求的 url / json / headers。"""

    def __init__(self, *resps):
        self._resps = list(resps)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        return self._resps.pop(0) if self._resps else FakeResp({"doc_list": []})


def _search_cfg(**kw):
    base = dict(
        region="cn-north-4",
        project_id="pid-1",
        koosearch_endpoint="https://koo.example.com",
        koosearch_app_id="app-1",
        koosearch_repo_id="repo-1",
        koosearch_token="tok-fixed",
    )
    base.update(kw)
    return HuaweiConfig(**base)


def test_unconfigured_returns_empty():
    r = KooSearchRetriever(cfg=HuaweiConfig(), client=FakeClient())
    assert r.search("消化性溃疡") == []


def test_searchtext_dialect_url_body_headers():
    client = FakeClient(FakeResp({"doc_list": [{
        "file_id": "f1", "content": "胃镜是首选检查", "score": 0.82,
        "additional_fields": {"asset_id": "AST-1", "anchor_id": "a3"},
    }], "total": 1}))
    r = KooSearchRetriever(cfg=_search_cfg(), client=client)
    hits = r.search("消化性溃疡 检查", top_k=3)

    call = client.calls[0]
    assert call["url"] == ("https://koo.example.com/v1/pid-1/applications/app-1"
                           "/uni-search/experience/searchtext")
    assert call["json"] == {"repo_id": "repo-1", "content": "消化性溃疡 检查",
                            "page_num": 1, "page_size": 3}
    assert call["headers"] == {"X-Auth-Token": "tok-fixed"}
    assert len(hits) == 1
    assert hits[0].asset_id == "AST-1"
    assert hits[0].anchor_id == "AST-1#a3"
    assert hits[0].text == "胃镜是首选检查"
    assert hits[0].score == 0.82


def test_meta_from_tags_and_no_meta_keeps_anchor_empty():
    client = FakeClient(FakeResp({"doc_list": [
        {"file_id": "f1", "content": "甲", "tags": ["asset_id=AST-9", "anchor_id=a7"]},
        {"file_id": "f2", "content": "乙"},
    ]}))
    hits = KooSearchRetriever(cfg=_search_cfg(), client=client).search("q", top_k=2)
    assert hits[0].anchor_id == "AST-9#a7"
    # 没元数据就不编锚点：空串，pipeline 会把它过滤掉，不进 evidence
    assert hits[1].anchor_id == ""
    assert hits[1].asset_id == "KOO-f2"


def test_refresh_token_once_on_401(monkeypatch):
    seq = iter(["stale", "fresh"])
    monkeypatch.setattr(iam, "token", lambda cfg=None, force=False: next(seq))
    client = FakeClient(FakeResp({"doc_list": []}, status=401),
                        FakeResp({"doc_list": [{"file_id": "f1", "content": "x"}]}))
    hits = KooSearchRetriever(cfg=_search_cfg(), client=client).search("q", top_k=1)
    assert len(client.calls) == 2
    assert client.calls[1]["headers"] == {"X-Auth-Token": "fresh"}
    assert len(hits) == 1


def test_raw_dialect_keeps_old_contract():
    cfg = HuaweiConfig(koosearch_endpoint="http://127.0.0.1:9000/search")
    client = FakeClient(FakeResp({"hits": [{"asset_id": "AST-2", "anchor_id": "a1",
                                            "text": "旧口径", "score": 1.5}]}))
    r = KooSearchRetriever(cfg=cfg, client=client)
    hits = r.search("q", top_k=2)
    assert r.dialect == "raw"
    assert client.calls[0]["json"] == {"query": "q", "top_k": 2}
    assert client.calls[0]["headers"] == {}
    assert hits[0].anchor_id == "AST-2#a1"


def test_searchtext_requires_project_id():
    cfg = _search_cfg(project_id="")
    with pytest.raises(ProviderNotConfigured):
        KooSearchRetriever(cfg=cfg, client=FakeClient()).url()


@pytest.mark.parametrize("field", ["project_id", "koosearch_app_id", "koosearch_repo_id"])
def test_partial_searchtext_config_is_not_ready(field):
    cfg = _search_cfg(**{field: ""})
    assert cfg.koosearch_dialect == "searchtext"
    assert not cfg.readiness()["koosearch"]


@pytest.mark.parametrize("dialect", ["raw", "searchtext"])
def test_full_anchor_survives_pipeline_trace(seeded, dialect):
    from app.pipeline import answer
    from medpal_core.retrieval.bm25 import BM25Retriever

    original = BM25Retriever(seeded).search("消化性溃疡")[0]
    doc = {"asset_id": original.asset_id, "anchor_id": original.anchor_id,
           "text": original.text, "score": original.score}
    cfg = (_search_cfg() if dialect == "searchtext" else
           HuaweiConfig(koosearch_endpoint="http://127.0.0.1:9000/search"))
    retriever = KooSearchRetriever(cfg=cfg, client=FakeClient(FakeResp({"hits": [doc]})))
    out = answer(seeded, "消化性溃疡", retriever=retriever)
    assert out["hits"][0]["anchor_id"] == original.anchor_id
    assert out["trace_completeness"] == 1.0
    assert not out["unresolved"]


def test_foreign_asset_anchor_is_not_fabricated():
    hit = KooSearchRetriever._hit({"asset_id": "AST-1", "anchor_id": "AST-2#a1"}, 0, 1)
    assert hit.anchor_id == ""


@pytest.mark.parametrize("docs", [[], [{"text": "正文，无锚点"}]])
def test_strict_probe_rejects_unusable_retrieval(monkeypatch, docs):
    from scripts import check_koo

    from medpal_core.providers.huawei import config, koosearch

    monkeypatch.setattr(config, "load_config", lambda: _search_cfg())
    monkeypatch.setattr(koosearch, "KooSearchRetriever", lambda cfg:
                        KooSearchRetriever(cfg=cfg, client=FakeClient(FakeResp({"hits": docs}))))
    assert check_koo.main(["--strict"]) == 1


def test_readiness_combinations():
    assert HuaweiConfig().readiness()["koosearch"] is False
    # 只有 endpoint 且没有 app/repo → raw 方言，算就绪（兼容自建网关）
    assert HuaweiConfig(koosearch_endpoint="http://x").readiness()["koosearch"] is True
    # 真实方言缺凭据 → 不就绪
    assert _search_cfg(koosearch_token="").readiness()["koosearch"] is False
    assert _search_cfg(koosearch_token="", iam_user="u", iam_password="p").readiness()["koosearch"] is True


def test_iam_token_cached(monkeypatch):
    calls = []

    class R:
        status_code = 201
        text = ""
        headers = {"X-Subject-Token": "iam-tok"}

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        return R()

    monkeypatch.setattr(iam.httpx, "post", fake_post)
    iam.reset_cache()
    cfg = HuaweiConfig(region="cn-north-4", project_id="pid", iam_user="u",
                       iam_password="p", iam_domain="d")
    assert iam.token(cfg) == "iam-tok"
    assert iam.token(cfg) == "iam-tok"
    assert calls == ["https://iam.cn-north-4.myhuaweicloud.com/v3/auth/tokens"]
    assert iam.token(cfg, force=True) == "iam-tok"
    assert len(calls) == 2
    iam.reset_cache()
