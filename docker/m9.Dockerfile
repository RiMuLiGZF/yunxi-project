# ============================================================
# 云汐系统 - M9 数据水晶 Dockerfile
# 模块: M9-data-crystal
# 端口: 8009
# 功能: 数据水晶、数据管道与连接器
# ============================================================

# ---- 阶段 1: 构建依赖 ----
FROM python:3.10-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY shared/ /build/shared/
COPY config/ /build/config/
RUN pip install --prefix=/build/deps --no-cache-dir \
    fastapi uvicorn httpx pydantic pydantic-settings \
    structlog python-dotenv psutil redis sqlalchemy pandas openpyxl

COPY M9-data-crystal/requirements.txt /build/m9-requirements.txt 2>/dev/null || true
RUN pip install --prefix=/build/deps --no-cache-dir -r /build/m9-requirements.txt 2>/dev/null || true

# ---- 阶段 2: 运行时 ----
FROM python:3.10-slim AS runtime

LABEL org.opencontainers.image.title="yunxi-m9" \
      org.opencontainers.image.description="云汐M9数据水晶" \
      org.opencontainers.image.version="2.0.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai \
    HEALTH_PORT=8009 \
    HEALTH_PATH=/health/live

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

RUN groupadd -r yunxi && useradd -r -g yunxi -d /app -s /sbin/nologin yunxi

WORKDIR /app

COPY --from=builder /build/deps /usr/local

COPY shared/ /app/shared/
COPY config/ /app/config/
COPY M9-data-crystal/ /app/M9-data-crystal/

RUN mkdir -p /app/data /app/logs && \
    chown -R yunxi:yunxi /app

COPY <<EOF /app/healthcheck.sh
#!/bin/bash
curl -fsS "http://localhost:${HEALTH_PORT:-8009}${HEALTH_PATH:-/health/live}" || exit 1
EOF
RUN chmod +x /app/healthcheck.sh

USER yunxi

EXPOSE 8009

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=20s \
    CMD /app/healthcheck.sh

WORKDIR /app/M9-data-crystal
CMD ["python", "-m", "backend.main"]
