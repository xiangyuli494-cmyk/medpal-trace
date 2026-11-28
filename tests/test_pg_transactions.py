"""真实 PostgreSQL 事务回归；仅使用 MEDPAL_TEST_PG_DSN 指定的本机测试库。"""
from __future__ import annotations

import os
import uuid

import pytest


@pytest.fixture
def pg_dsn(monkeypatch, tmp_path):
    dsn = os.environ.get("MEDPAL_TEST_PG_DSN")
    if not dsn:
        pytest.skip("需要本机 MEDPAL_TEST_PG_DSN")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    if conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("事务回归仅允许本机 PostgreSQL，不访问云库")
    schema = "medpal_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        isolated = make_conninfo(dsn, options=f"-csearch_path={schema}")
        monkeypatch.setenv("MEDPAL_DB_BACKEND", "gaussdb")
        monkeypatch.setenv("MEDPAL_DB_DSN", isolated)
        monkeypatch.setenv("MEDPAL_DATA_DIR", str(tmp_path))
        from app import deps

        monkeypatch.setattr(deps, "_prepared", False)
        try:
            yield isolated
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_read_first_schema_survives_connection_close(pg_dsn):
    import psycopg
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        with psycopg.connect(pg_dsn) as conn:
            assert conn.execute("SELECT to_regclass('asset')").fetchone()[0] == "asset"
        assert client.get("/health").status_code == 200


def test_drop_tables_persists_on_repeated_runs(pg_dsn):
    import psycopg
    from scripts.check_pg import _drop_tables

    from medpal_core.providers.huawei import gaussdb

    for _ in range(2):
        conn = gaussdb.connect(pg_dsn)
        try:
            gaussdb.prepare(conn)
            _drop_tables(conn)
        finally:
            conn.close()
        with psycopg.connect(pg_dsn) as check:
            assert check.execute("SELECT count(*) FROM pg_tables WHERE schemaname=current_schema()").fetchone()[0] == 0
