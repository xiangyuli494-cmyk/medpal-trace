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
    koosearch_endpoint: str = ""
    extras: dict = field(default_factory=dict)

    def readiness(self) -> dict:
        return {
            "obs": bool(self.ak and self.sk and self.obs_bucket),
            "gaussdb": bool(self.gaussdb_dsn),
            "modelarts": bool(self.model_endpoint and self.model_name),
            "koosearch": bool(self.koosearch_endpoint),
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
        model_endpoint=_env("HUAWEI_MODEL_ENDPOINT"),
        model_name=_env("HUAWEI_MODEL_NAME"),
        koosearch_endpoint=_env("HUAWEI_KOOSEARCH_ENDPOINT"),
    )


class ProviderNotConfigured(RuntimeError):
    """没配云服务时的统一异常，消息里直接给缺的环境变量名。"""
