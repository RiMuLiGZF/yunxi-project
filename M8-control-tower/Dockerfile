# ============================================================
# 云汐系统 M8 管理工作台 - Docker 容器配置
# 模块说明: 管理工作台，后台管理界面
# 启动方式: python server.py (默认端口 8008)
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
COPY M8-control-tower/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# 阶段3: 复制模块代码
COPY M8-control-tower/ /app/M8-control-tower/

ENV PYTHONPATH=/app
EXPOSE 8008

WORKDIR /app/M8-control-tower
CMD ["python", "server.py"]
