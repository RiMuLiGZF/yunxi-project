# ============================================================
# 云汐系统 - 共享基础镜像（多阶段构建）
# 用途: 为所有业务模块提供统一的 Python 运行时和共享依赖
# 优化点:
#   - 多阶段构建: builder -> runtime
#   - 非 root 用户运行
#   - 健康检查工具预装
#   - 共享代码预安装
# ============================================================

# ---- 阶段 1: 构建依赖 ----
FROM python:3.10-slim AS builder

WORKDIR /build

# 系统构建依赖（仅构建阶段需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖到 /build/deps
COPY shared/requirements.txt /build/shared-requirements.txt
RUN pip install --prefix=/build/deps --no-cache-dir -r /build/shared-requirements.txt 2>/dev/null || \
    pip install --prefix=/build/deps --no-cache-dir \
        fastapi uvicorn httpx pydantic pydantic-settings \
        structlog python-dotenv psutil sqlalchemy aiosqlite \
        python-jose[cryptography] passlib[bcrypt] redis

# ---- 阶段 2: 运行时 ----
FROM python:3.10-slim AS runtime

# 元数据
LABEL org.opencontainers.image.title="yunxi-shared-base" \
      org.opencontainers.image.description="云汐系统共享基础镜像" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.vendor="yunxi"

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai

# 运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

# 创建非 root 用户
RUN groupadd -r yunxi && useradd -r -g yunxi -d /app -s /sbin/nologin yunxi

# 工作目录
WORKDIR /app

# 从构建阶段复制依赖
COPY --from=builder /build/deps /usr/local

# 复制共享代码
COPY shared/ /app/shared/
COPY config/ /app/config/

# 设置权限
RUN mkdir -p /app/data /app/logs /app/backups /app/tmp && \
    chown -R yunxi:yunxi /app

# 健康检查脚本
COPY <<EOF /app/healthcheck.sh
#!/bin/bash
# 通用健康检查脚本 - 各模块通过环境变量 HEALTH_PORT 和 HEALTH_PATH 配置
PORT=${HEALTH_PORT:-8000}
PATH=${HEALTH_PATH:-/health/live}
curl -fsS "http://localhost:${PORT}${PATH}" || exit 1
EOF
RUN chmod +x /app/healthcheck.sh

# 切换到非 root 用户
USER yunxi

# 默认健康检查（可被子镜像覆盖）
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=30s \
    CMD /app/healthcheck.sh
