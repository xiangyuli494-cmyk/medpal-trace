"""华为云配置：一处读环境变量，readiness() 给出「哪块云服务已就绪」。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None or v == "" else v


@dataclass
class HuaweiConfig:
    ak: str = ""
    sk: str = ""
    region: str = "cn-north-4"
    project_id: str = ""
    obs_bucket: str = ""
    obs_endpoint: str = ""
    gaussdb_dsn: str = ""
    model_endpoint: str = ""
    model_name: str = ""
    model_api_key: str = ""
    koosearch_endpoint: str = ""
    koosearch_app_id: str = ""
    koosearch_repo_id: str = ""
    koosearch_token: str = ""
    iam_user: str = ""
    iam_password: str = ""
    iam_domain: str = ""
    extras: dict = field(default_factory=dict)

    @property
    def koosearch_dialect(self) -> str:
        """配置任一云端 ID 就按 searchtext 检查，避免漏填时误发 raw 请求。"""
        return "searchtext" if (self.koosearch_app_id or self.koosearch_repo_id) else "raw"

    def koosearch_auth_ready(self) -> bool:
        return bool(self.koosearch_token or (self.iam_user and self.iam_password))

    def readiness(self) -> dict:
        ready = bool(self.koosearch_endpoint)
        if ready and self.koosearch_dialect == "searchtext":
            # 真实接口必须带 X-Auth-Token，没凭据就当没配，别让 /health 说假话
            ready = bool(self.project_id and self.koosearch_app_id
                         and self.koosearch_repo_id and self.koosearch_auth_ready())
        return {
            "obs": bool(self.ak and self.sk and self.obs_bucket),
            "gaussdb": bool(self.gaussdb_dsn),
            "modelarts": bool(self.model_endpoint and self.model_name),
            "koosearch": ready,
        }


def load_config() -> HuaweiConfig:
    return HuaweiConfig(
        ak=_env("HUAWEI_AK"),
        sk=_env("HUAWEI_SK"),
        region=_env("HUAWEI_REGION", "cn-north-4"),
        project_id=_env("HUAWEI_PROJECT_ID"),
        obs_bucket=_env("HUAWEI_OBS_BUCKET"),
        obs_endpoint=_env("HUAWEI_OBS_ENDPOINT"),
        gaussdb_dsn=_env("MEDPAL_DB_DSN") or _env("HUAWEI_GAUSSDB_DSN"),
        # MEDPAL_LLM_* 是唯一入口，HUAWEI_MODEL_* 保留兼容；两处口径必须一致，
        # 否则 /health 说就绪、/v1/cloud 说缺变量（2026-11-08 修过的假阴性）。
        model_endpoint=_env("MEDPAL_LLM_BASE_URL") or _env("HUAWEI_MODEL_ENDPOINT"),
        model_name=_env("MEDPAL_LLM_MODEL") or _env("HUAWEI_MODEL_NAME"),
        model_api_key=_env("MEDPAL_LLM_API_KEY") or _env("HUAWEI_MODEL_API_KEY"),
        koosearch_endpoint=_env("HUAWEI_KOOSEARCH_ENDPOINT"),
        koosearch_app_id=_env("HUAWEI_KOOSEARCH_APP_ID"),
        koosearch_repo_id=_env("HUAWEI_KOOSEARCH_REPO_ID"),
        koosearch_token=_env("HUAWEI_KOOSEARCH_TOKEN"),
        iam_user=_env("HUAWEI_IAM_USER"),
        iam_password=_env("HUAWEI_IAM_PASSWORD"),
        iam_domain=_env("HUAWEI_IAM_DOMAIN"),
    )


class ProviderNotConfigured(RuntimeError):
    """没配云服务时的统一异常，消息里直接给缺的环境变量名。"""
