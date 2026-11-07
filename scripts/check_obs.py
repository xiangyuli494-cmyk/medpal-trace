#!/usr/bin/env python3
"""check_obs.py — OBS/MinIO 对象存储自检（B2 交付物）。

六步：环境变量 → SDK → 建桶 → 上传 → 下载比 sha256 → ls 确认 → 清理。
全绿打印 OBS READY 且退出码 0；任一步失败打印原因且退出码 1。

本地用 MinIO 顶替 OBS：
    bash scripts/dev_minio.sh
云上用真 OBS：
    export HUAWEI_AK=... HUAWEI_SK=... HUAWEI_OBS_BUCKET=medpal-trace-cn4 \
           HUAWEI_REGION=cn-north-4
    python scripts/check_obs.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "apps", "api"))

KEY = "_selftest/hello.txt"
PAYLOAD = b"medpal-trace obs selftest\n"

_steps: list[tuple[str, bool, str]] = []


def _ok(step: str, detail: str = "") -> None:
    _steps.append((step, True, detail))
    print(f"{step:<4s} [OK] {detail}")


def _fail(step: str, detail: str) -> None:
    _steps.append((step, False, detail))
    print(f"{step:<4s} [FAIL] {detail}")


def _mask(v: str) -> str:
    if not v:
        return "(空)"
    return v[:4] + "***" if len(v) > 4 else "***"


def main() -> int:
    from medpal_core.providers.huawei.config import load_config
    from medpal_core.providers.huawei.obs import OBSStore

    print("== check_obs.py")
    n = 1

    # 1) 环境变量
    cfg = load_config()
    missing = [k for k, v in (("HUAWEI_AK", cfg.ak), ("HUAWEI_SK", cfg.sk),
                              ("HUAWEI_OBS_BUCKET", cfg.obs_bucket)) if not v]
    if missing:
        _fail(f"{n})", "缺 " + " / ".join(missing))
        return 1
    endpoint = cfg.obs_endpoint or ("https://obs." + cfg.region + ".myhuaweicloud.com")
    _ok(f"{n})", f"endpoint={endpoint}, bucket={cfg.obs_bucket}, ak={_mask(cfg.ak)}")
    n += 1

    # 2) SDK
    try:
        import obs as obs_sdk
        _ok(f"{n})", f"esdk-obs-python {getattr(obs_sdk, '__version__', 'ok')}")
    except ImportError:
        _fail(f"{n})", "未安装 SDK：pip install esdk-obs-python")
        return 1
    n += 1

    # 3) 建桶（已存在就跳过）
    store = OBSStore(cfg)
    try:
        store.ensure_bucket()
        _ok(f"{n})", f"桶 {cfg.obs_bucket} 就绪")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 4) 上传
    fd, tmp = tempfile.mkstemp(prefix="obs_selftest_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(PAYLOAD)
        uri = store.put(tmp, KEY)
        _ok(f"{n})", f"上传 {uri}")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    n += 1

    # 5) 下载 + sha256 对比
    try:
        got = store.get(KEY)
        want = hashlib.sha256(PAYLOAD).hexdigest()
        have = hashlib.sha256(got).hexdigest()
        if want != have:
            _fail(f"{n})", f"sha256 不一致 want={want[:16]} got={have[:16]} 长度={len(got)}")
            return 1
        _ok(f"{n})", f"下载内容一致 sha256={have[:16]}… 长度={len(got)}")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 6) ls 确认对象存在
    try:
        keys = store.list(prefix="_selftest/")
        if KEY not in keys:
            _fail(f"{n})", f"桶内未找到 {KEY}，实际={keys}")
            return 1
        _ok(f"{n})", f"桶内 ls 到 {len(keys)} 个对象，含 {KEY}")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1
    n += 1

    # 7) 清理
    try:
        store.delete(KEY)
        _ok(f"{n})", "已删除测试对象")
    except Exception as exc:
        _fail(f"{n})", str(exc))
        return 1

    print(f"\nOBS READY: obs://{cfg.obs_bucket}/{KEY} @ {endpoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())