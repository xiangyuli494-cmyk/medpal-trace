# 云上形态：一个镜像同时承载 API 与演示页，环境变量决定后端实现。
# 构建：docker build -t medpal-trace:0.1.0 .
# 运行：docker run -p 8000:8000 -e MEDPAL_LLM=offline -v $PWD/data:/app/data medpal-trace:0.1.0
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# apps/api 提供 app 包、packages/core 提供 medpal_core；uvicorn 要按模块名导入 app.main
ENV PYTHONPATH=/app/apps/api:/app/packages/core

COPY pyproject.toml README.md ./
COPY packages/core ./packages/core
COPY apps ./apps
# GaussDB 走 psycopg[binary]（有 manylinux 轮子，slim 镜像不需要 gcc）。
# 这里显式装它而不是 -e ".[huawei]"：esdk-obs-python 依赖的 crcmod 只有 sdist、
# 无 Linux wheel，一起装会让镜像构建失败（真机联调 2026-11-15 踩过，见
# docs/evidence/2026-11-15-cce-apig.md）。此镜像尚未包含 OBS SDK；OBSStore 仍依赖
# esdk-obs-python，配置桶和 AK/SK 不代表上传可用，部署验收须单列这项缺口。
RUN pip install --no-cache-dir -e . "psycopg[binary]>=3.1"

COPY data ./data

# 数据落在挂载卷上；容器重建不丢本体与决策链
ENV MEDPAL_DATA_DIR=/app/data
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# 默认单进程；上 CCE 时按副本数横向扩，状态都在 GaussDB / OBS 上
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
