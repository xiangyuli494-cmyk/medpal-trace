"""B8 断网模拟的回归：有云库 DSN（含旧名）时也必须走 SQLite，不连云库。

对应 PR #93 的 [P2] 意见：只清 MEDPAL_DB_DSN 不够，HUAWEI_GAUSSDB_DSN
也会被 deps.want_gaussdb() 识别，所以脚本要显式固定 sqlite 并全程隔离。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _restore_env():
    """_offline_sim 会改 os.environ（设坏模型端点、清 DSN），测完必须还原，
    否则后续 test_default_llm_is_offline 之类的用例会被污染。"""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _load_smoke():
    sys.path.insert(0, str(REPO / "packages" / "core"))
    sys.path.insert(0, str(REPO / "apps" / "api"))
    spec = importlib.util.spec_from_file_location("smoke_llm", REPO / "scripts" / "smoke_llm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_offline_sim_clean_env():
    mod = _load_smoke()
    assert mod._offline_sim() == 0


def test_offline_sim_with_legacy_gauss_dsn(monkeypatch):
    """同时给两个 DSN 坏值，脚本应清掉它们走 SQLite，仍能跑通。"""
    monkeypatch.setenv("HUAWEI_GAUSSDB_DSN", "postgresql://x:x@127.0.0.1:59999/x")
    monkeypatch.setenv("MEDPAL_DB_DSN", "postgresql://x:x@127.0.0.1:59999/x")
    mod = _load_smoke()
    assert mod._offline_sim() == 0