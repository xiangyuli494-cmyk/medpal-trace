# 云上形态：一个镜像同时承载 API 与演示页，环境变量决定后端实现。
# 构建：docker build -t medpal-trace:0.1.1 .
# 运行：docker run -p 8000:8000 -e MEDPAL_LLM=offline -v $PWD/data:/app/data medpal-trace:0.1.1
FROM python:3.12-slim AS wheels

# crcmod 需要编译；编译工具仅保留在构建阶段。
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip wheel --no-cache-dir --wheel-dir=/wheels \
    "psycopg[binary]>=3.1" "esdk-obs-python>=3.22"

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
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
    "psycopg[binary]>=3.1" "esdk-obs-python>=3.22" \
    && pip install --no-cache-dir -e . \
    && rm -rf /wheels

COPY data ./data

# 数据落在挂载卷上；容器重建不丢本体与决策链
ENV MEDPAL_DATA_DIR=/app/data
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/livez').status==200 else 1)"

# 默认单进程；上 CCE 时按副本数横向扩，状态都在 GaussDB / OBS 上
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
