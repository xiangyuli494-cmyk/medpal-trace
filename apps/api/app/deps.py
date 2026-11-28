"""FastAPI 依赖：一条请求一个连接。后端由 MEDPAL_DB_BACKEND 决定，不再写死 sqlite。

- 默认（或 MEDPAL_DB_BACKEND=sqlite）-> 本地 sqlite，零依赖可跑；
- MEDPAL_DB_BACKEND=gaussdb（或只设了 HUAWEI_GAUSSDB_DSN）-> providers/huawei/gaussdb。

两条路对端点完全一样：连接都支持 execute/commit/close，行都能按列名取。
差别（? 与 %s、tuple 与 dict）在 providers 层抹平，业务代码零改动。
"""

from __future__ import annotations

import os

from medpal_core.config import settings
from medpal_core.storage import connect

GAUSS_ALIASES = {"gaussdb", "postgres", "postgresql"}
_prepared = False


def want_gaussdb() -> bool:
    explicit = os.environ.get("MEDPAL_DB_BACKEND", "").strip().lower()
    if explicit in GAUSS_ALIASES:
        return True
    if explicit and explicit != "auto":
        return False
    return bool(os.environ.get("MEDPAL_DB_DSN") or os.environ.get("HUAWEI_GAUSSDB_DSN"))


def open_conn():
    global _prepared

    if not want_gaussdb():
        return connect()

    from medpal_core.providers.huawei import gaussdb

    conn = gaussdb.connect()
    if not _prepared:
        # prepare 内部提交 DDL；成功返回后才标记，读请求关闭连接不会回滚建表。
        gaussdb.prepare(conn)
        _prepared = True
    return conn


def get_conn():
    conn = open_conn()
    try:
        yield conn
    finally:
        conn.close()


_report_store = None


def get_report_store():
    """报告仓库单例：一个进程一个 OBS 客户端；测试用 dependency_overrides 换掉。"""
    global _report_store
    if _report_store is None:
        from .report_store import ReportStore

        _report_store = ReportStore()
    return _report_store


def get_settings():
    return settings()
