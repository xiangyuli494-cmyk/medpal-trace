"""KooSearch：云端检索。两种方言，对上层都是同一个 Retriever 接口。

searchtext —— 华为云 KooSearch 真实接口（2026-11 文档：搜索知识库 SearchInKnowledgeRepo）：
    POST {endpoint}/v1/{project_id}/applications/{app_id}/uni-search/experience/searchtext
    头  X-Auth-Token: <IAM token>
    体  {"repo_id": ..., "content": 查询, "page_num": 1, "page_size": top_k}
    回  {"doc_list": [{"file_id","chunk_id","title","content","score", ...}], "total": n}

raw —— 老口径：把 {"query","top_k"} 原样 POST 到 endpoint，读 {"hits":[...]}。
    给自建网关 / 本地假服务用，也保证 C5 之前写的代码不破。

溯源能不能用，全看映射这一条：doc 的 additional_fields / tags 里带 asset_id + anchor_id，
才拼成 `<asset_id>#<anchor_id>` 填进 Hit.anchor_id；没有就留空 ——
空锚点不进 evidence，宁可少一条引用，也不编一个查不到的锚点出来。
"""

from __future__ import annotations

import httpx

from ...retrieval.base import Hit
from . import iam
from .config import ProviderNotConfigured, load_config


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def _meta(item: dict) -> dict:
    """把 additional_fields 与 tags 摊平成 key=value，用于取 asset_id / anchor_id。"""
    meta: dict = {}
    extra = item.get("additional_fields")
    if isinstance(extra, dict):
        for key, val in extra.items():
            if isinstance(key, str) and isinstance(val, str):
                meta.setdefault(key, val)
    for tag in item.get("tags") or []:
        if isinstance(tag, str) and "=" in tag:
            key, val = tag.split("=", 1)
            meta.setdefault(key.strip(), val.strip())
        elif isinstance(tag, dict):
            key, val = tag.get("key"), tag.get("value")
            if isinstance(key, str) and isinstance(val, str):
                meta.setdefault(key, val)
    return meta


class KooSearchRetriever:
    name = "koosearch"

    def __init__(self, cfg=None, top_k: int = 8, client=None):
        self.cfg = cfg or load_config()
        self.top_k = top_k
        self._client = client or httpx

    def available(self) -> bool:
        return self.cfg.readiness()["koosearch"]

    @property
    def dialect(self) -> str:
        return self.cfg.koosearch_dialect

    def url(self) -> str:
        cfg = self.cfg
        if self.dialect == "raw":
            return cfg.koosearch_endpoint
        if not cfg.project_id:
            raise ProviderNotConfigured(
                "searchtext 方言需要 HUAWEI_PROJECT_ID（接口路径里带 project_id）"
            )
        base = cfg.koosearch_endpoint.rstrip("/")
        return (base + "/v1/" + cfg.project_id + "/applications/" + cfg.koosearch_app_id
                + "/uni-search/experience/searchtext")

    def _body(self, query: str, top_k: int) -> dict:
        size = top_k or self.top_k
        if self.dialect == "raw":
            return {"query": query, "top_k": size}
        return {"repo_id": self.cfg.koosearch_repo_id, "content": query,
                "page_num": 1, "page_size": size}

    def _headers(self, force: bool = False) -> dict:
        if self.dialect == "raw":
            return {}
        return {"X-Auth-Token": iam.token(self.cfg, force=force)}

    def search(self, query: str, top_k: int = 8) -> list:
        if not self.available():
            # 未配置时诚实返回空召回：消融实验的四条命令都要能跑完，不抛异常
            return []
        url = self.url()
        body = self._body(query, top_k)
        resp = self._client.post(url, json=body, headers=self._headers(), timeout=20.0)
        if resp.status_code in (401, 403) and self.dialect != "raw":
            # token 过期是常态（IAM 24 小时），刷新一次再打；再失败才当错
            resp = self._client.post(url, json=body, headers=self._headers(force=True), timeout=20.0)
        resp.raise_for_status()
        return [self._hit(item, i, top_k or self.top_k)
                for i, item in enumerate(self._docs(resp.json()))]

    @staticmethod
    def _docs(payload) -> list:
        if isinstance(payload, dict):
            return list(payload.get("doc_list") or payload.get("hits") or [])
        return list(payload) if isinstance(payload, list) else []

    @staticmethod
    def _hit(item, i: int, size: int) -> Hit:
        doc = item if isinstance(item, dict) else {}
        meta = _meta(doc)
        # raw 方言的历史契约把 asset_id / anchor_id 放在命中项顶层，一并认
        asset = meta.get("asset_id") or _str(doc.get("asset_id"))
        anchor = meta.get("anchor_id") or _str(doc.get("anchor_id"))
        text = (doc.get("content") or doc.get("big_content")
                or doc.get("text") or doc.get("title") or "")
        try:
            score = float(doc.get("score"))
        except (TypeError, ValueError):
            score = float(max(size - i, 0))
        placeholder = "KOO-" + str(doc.get("file_id") or doc.get("chunk_id") or i)
        # raw 网关可能已经返回完整引用；其他资产的前缀不能静默拼接成伪引用。
        ref = ""
        if asset and anchor:
            if "#" not in anchor:
                ref = asset + "#" + anchor
            elif anchor.startswith(asset + "#"):
                ref = anchor
        return Hit(asset or placeholder, ref, text, score)
