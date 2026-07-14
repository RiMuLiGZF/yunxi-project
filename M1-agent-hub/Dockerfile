# ============================================================
# 云汐系统 M1 多Agent调度中心 - Docker 容器配置
# 模块说明: 多 Agent 调度中心，HTTP API 服务网关
# 启动方式: python server.py (默认端口 8001)
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
COPY M1-agent-hub/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# 阶段3: 复制模块代码
COPY M1-agent-hub/ /app/M1-agent-hub/

ENV PYTHONPATH=/app
EXPOSE 8001

WORKDIR /app/M1-agent-hub
CMD ["python", "server.py"]
