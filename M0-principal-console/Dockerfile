# ============================================================
# 云汐系统 M0 主理人管控台 - Docker 容器配置
# 模块说明: 主理人管控台，系统总入口
# 启动方式: python server.py (默认端口 8000)
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
COPY M0-principal-console/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# 阶段3: 复制模块代码
COPY M0-principal-console/ /app/M0-principal-console/

ENV PYTHONPATH=/app
EXPOSE 8000

# 工作目录切换到模块目录，确保 server.py 的路径解析正确
WORKDIR /app/M0-principal-console
CMD ["python", "server.py"]
