# ============================================================
# 云汐系统 - API 网关 Dockerfile
# 模块: API-Gateway
# 端口: 8080
# 功能: 统一接入层（路由转发、认证鉴权、限流熔断）
# ============================================================

# ---- 阶段 1: 构建依赖 ----
FROM python:3.10-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

# 安装共享依赖
COPY shared/ /build/shared/
COPY config/ /build/config/
RUN pip install --prefix=/build/deps --no-cache-dir \
    fastapi uvicorn httpx pydantic pydantic-settings \
    structlog python-dotenv psutil python-jose[cryptography] \
    passlib[bcrypt] redis

# 安装网关专属依赖
COPY API-Gateway/requirements.txt /build/gateway-requirements.txt
RUN pip install --prefix=/build/deps --no-cache-dir -r /build/gateway-requirements.txt || true

# ---- 阶段 2: 运行时 ----
FROM python:3.10-slim AS runtime

LABEL org.opencontainers.image.title="yunxi-gateway" \
      org.opencontainers.image.description="云汐API网关" \
      org.opencontainers.image.version="2.0.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai \
    HEALTH_PORT=8080 \
    HEALTH_PATH=/health/live

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

# 创建非 root 用户
RUN groupadd -r yunxi && useradd -r -g yunxi -d /app -s /sbin/nologin yunxi

WORKDIR /app

# 从构建阶段复制依赖
COPY --from=builder /build/deps /usr/local

# 复制共享代码和配置
COPY shared/ /app/shared/
COPY config/ /app/config/

# 复制网关代码
COPY API-Gateway/ /app/API-Gateway/

# 数据目录
RUN mkdir -p /app/data /app/logs && \
    chown -R yunxi:yunxi /app

# 健康检查脚本
COPY <<EOF /app/healthcheck.sh
#!/bin/bash
curl -fsS "http://localhost:${HEALTH_PORT:-8080}${HEALTH_PATH:-/health/live}" || exit 1
EOF
RUN chmod +x /app/healthcheck.sh

USER yunxi

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=20s \
    CMD /app/healthcheck.sh

WORKDIR /app/API-Gateway
CMD ["python", "server.py"]
