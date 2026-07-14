# ============================================================
# 云汐系统 M11 MCP 总线 - Docker 容器配置
# 模块说明: MCP 协议总线，模块间通信枢纽
# 启动方式: python server.py (默认端口 8011)
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
COPY M11-mcp-bus/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# 阶段3: 复制模块代码
COPY M11-mcp-bus/ /app/M11-mcp-bus/

ENV PYTHONPATH=/app
EXPOSE 8011

WORKDIR /app/M11-mcp-bus
CMD ["python", "server.py"]
