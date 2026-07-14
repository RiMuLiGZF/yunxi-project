# ============================================================
# 云汐系统 M5 潮汐记忆系统 - Docker 容器配置
# 模块说明: 潮汐记忆系统 FastAPI 服务
# 启动方式: python server.py (默认端口 8005)
# ============================================================
FROM python:3.10-slim AS base

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends gcc curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 阶段1: 安装共享依赖
COPY shared/ /app/shared/
COPY config/ /app/config/
RUN pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic pydantic-settings \
    structlog python-dotenv psutil sqlalchemy aiosqlite

# 阶段2: 安装模块依赖
COPY M5-tide-memory/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# 阶段3: 复制模块代码
COPY M5-tide-memory/ /app/M5-tide-memory/

ENV PYTHONPATH=/app
EXPOSE 8005

WORKDIR /app/M5-tide-memory
CMD ["python", "server.py"]
