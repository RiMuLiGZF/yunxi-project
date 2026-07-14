# ============================================================
# 云汐系统 M12 安全盾 - Docker 容器配置
# 模块说明: 安全盾，WAF防护墙、API密钥管理、IP黑白名单、速率限制
# 启动方式: python server.py (默认端口 8012)
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
COPY M12-security-shield/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# 阶段3: 复制模块代码
COPY M12-security-shield/ /app/M12-security-shield/

ENV PYTHONPATH=/app
EXPOSE 8012

WORKDIR /app/M12-security-shield
CMD ["python", "server.py"]
