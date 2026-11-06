"""OBS：原件与报告落对象存储。SDK 缺失或未配 AK/SK 时明确报缺什么。

endpoint 优先读 HUAWEI_OBS_ENDPOINT（本地 MinIO 顶替 OBS 时指到 127.0.0.1:9000），
否则按 region 拼华为云 OBS 域名——同一份代码，本地和云上只换环境变量。
"""

from __future__ import annotations

from pathlib import Path

from .config import ProviderNotConfigured, load_config


def _is_local_endpoint(server: str) -> bool:
    """endpoint 指向本机（MinIO）时返回 True。"""
    from urllib.parse import urlparse

    host = (urlparse(server).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def _read_body(resp) -> bytes:
    """从 getObject 响应取字节。

    坑2（cloud-resources.md §4.3）：esdk-obs-python 的 getObject 不传
    loadStreamInMemory=True 时，resp.body 是 buffer=None 的 ObjectStream，
    read 属性也是 None，直接 .buffer 会得到空内容。所以：
    1) 调 getObject 时显式传 loadStreamInMemory=True；
    2) 这里再兜底：先认 buffer，再试 read()，最后按可迭代对象拼。
    """
    body = getattr(resp, "body", None)
    if body is None:
        return b""
    buf = getattr(body, "buffer", None)
    if isinstance(buf, (bytes, bytearray)):
        return bytes(buf)
    reader = getattr(body, "read", None)
    if callable(reader):
        data = reader()
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
    if hasattr(body, "__iter__"):
        return b"".join(body)
    return b""


class OBSStore:
    name = "huawei-obs"

    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self._client = None

    def available(self) -> bool:
        return self.cfg.readiness()["obs"]

    def _c(self):
        if self._client is None:
            if not self.available():
                raise ProviderNotConfigured("缺少 HUAWEI_AK / HUAWEI_SK / HUAWEI_OBS_BUCKET")
            try:
                from obs import ObsClient  # type: ignore
            except ImportError as exc:
                raise ProviderNotConfigured("未安装华为云 OBS SDK：pip install esdk-obs-python") from exc
            server = self.cfg.obs_endpoint or (
                "https://obs." + self.cfg.region + ".myhuaweicloud.com"
            )
            kwargs = dict(
                access_key_id=self.cfg.ak,
                secret_access_key=self.cfg.sk,
                server=server,
                region=self.cfg.region,
            )
            # 本地 MinIO 走 S3 兼容模式：path-style + v4 签名；
            # 云端 OBS 用默认的 obs 签名，两者共用同一份 provider 代码。
            if _is_local_endpoint(server):
                kwargs.update(path_style=True, signature="v4")
            self._client = ObsClient(**kwargs)
        return self._client

    def put(self, local_path: str | Path, key: str) -> str:
        client = self._c()
        resp = client.putFile(self.cfg.obs_bucket, key, str(local_path))
        if getattr(resp, "status", 0) >= 300:
            raise ProviderNotConfigured("OBS 上传失败: {}".format(getattr(resp, "reason", resp)))
        return "obs://" + self.cfg.obs_bucket + "/" + key

    def ensure_bucket(self) -> None:
        """桶不存在就建；已存在视为成功（OBS / MinIO 的 409 文案不同，都放过）。"""
        client = self._c()
        resp = client.createBucket(self.cfg.obs_bucket)
        status = getattr(resp, "status", 0)
        reason = str(getattr(resp, "reason", "")).lower()
        if status >= 300 and not any(k in reason for k in ("exist", "already", "owned")):
            raise ProviderNotConfigured(
                "OBS 建桶失败: {}".format(getattr(resp, "reason", resp))
            )

    def get(self, key: str) -> bytes:
        client = self._c()
        resp = client.getObject(self.cfg.obs_bucket, key, loadStreamInMemory=True)
        if getattr(resp, "status", 0) >= 300:
            raise ProviderNotConfigured("OBS 下载失败: {}".format(getattr(resp, "reason", resp)))
        return _read_body(resp)

    def delete(self, key: str) -> bool:
        client = self._c()
        resp = client.deleteObject(self.cfg.obs_bucket, key)
        if getattr(resp, "status", 0) >= 300:
            raise ProviderNotConfigured("OBS 删除失败: {}".format(getattr(resp, "reason", resp)))
        return True

    def list(self, prefix: str = "") -> list:
        client = self._c()
        resp = client.listObjects(self.cfg.obs_bucket, prefix=prefix)
        if getattr(resp, "status", 0) >= 300:
            raise ProviderNotConfigured("OBS 列举失败: {}".format(getattr(resp, "reason", resp)))
        body = getattr(resp, "body", None)
        items = getattr(body, "contents", None) or []
        return [getattr(obj, "key", "") for obj in items]