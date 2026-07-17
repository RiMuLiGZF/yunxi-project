# 云汐 API 网关 Dockerfile
FROM python:3.10-slim

WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 安装依赖
COPY API-Gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && \
    pip install --no-cache-dir python-jose[cryptography]

# 复制网关代码
COPY API-Gateway/ /app/

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# 启动命令
CMD ["python", "server.py"]
