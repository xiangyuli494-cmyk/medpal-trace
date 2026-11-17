"""IAM 取 Token：KooSearch 这类服务用 X-Auth-Token，不是 AK/SK 签名。

单独一个模块的理由：AK/SK 签名（obs 用）与 token 认证是两套体系，
混在一起会让后续接 APIG / 盘古时又写一遍。谁需要 token 就 import 这里。

有效期按 IAM 的 24 小时算，缓存 22 小时；401/403 时由调用方 force=True 刷一次。
"""

from __future__ import annotations

import time

import httpx

from .config import HuaweiConfig, ProviderNotConfigured, load_config

_CACHE: dict = {}
_TTL_SECONDS = 22 * 3600


def iam_endpoint(region: str) -> str:
    return "https://iam." + region + ".myhuaweicloud.com/v3/auth/tokens"


def _cache_key(cfg: HuaweiConfig) -> tuple:
    return (cfg.iam_user, cfg.iam_domain or cfg.iam_user, cfg.region, cfg.project_id)


def reset_cache() -> None:
    """测试和「换了账号」时清缓存用。"""
    _CACHE.clear()


def token(cfg: HuaweiConfig | None = None, force: bool = False) -> str:
    """取 X-Auth-Token。优先用现成的 HUAWEI_KOOSEARCH_TOKEN，其次用 IAM 用户密码换。"""
    cfg = cfg or load_config()
    if cfg.koosearch_token:
        return cfg.koosearch_token
    if not (cfg.iam_user and cfg.iam_password):
        raise ProviderNotConfigured(
            "缺少 HUAWEI_IAM_USER / HUAWEI_IAM_PASSWORD（X-Auth-Token 要用 IAM 用户密码换，"
            "或直接给 HUAWEI_KOOSEARCH_TOKEN）"
        )

    key = _cache_key(cfg)
    now = time.time()
    if not force:
        cached = _CACHE.get(key)
        if cached and cached[1] > now:
            return cached[0]

    scope = {"project": {"id": cfg.project_id}} if cfg.project_id else {"project": {"name": cfg.region}}
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": cfg.iam_user,
                        "password": cfg.iam_password,
                        "domain": {"name": cfg.iam_domain or cfg.iam_user},
                    }
                },
            },
            "scope": scope,
        }
    }
    resp = httpx.post(iam_endpoint(cfg.region), json=body, timeout=20.0)
    if resp.status_code >= 400:
        raise ProviderNotConfigured(
            "IAM 换 token 失败：" + str(resp.status_code) + " " + (resp.text or "")[:300]
        )
    got = resp.headers.get("X-Subject-Token") or resp.headers.get("x-subject-token") or ""
    if not got:
        raise ProviderNotConfigured("IAM 响应里没有 X-Subject-Token 头")
    _CACHE[key] = (got, now + _TTL_SECONDS)
    return got
