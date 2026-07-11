"""M11 MCP Bus - 服务启动入口.

使用 Uvicorn 启动 FastAPI 服务。
端口通过环境变量 M11_PORT 配置，默认 8011。

用法:
    python server.py
    M11_PORT=8011 python server.py
"""

from __future__ import annotations

import os
import sys

# 将项目根目录加入路径，以便以包的形式导入 src
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import uvicorn
from dotenv import load_dotenv


def main():
    """启动 M11 服务."""
    # 先加载全局配置（优先级低，可被模块自身配置覆盖）
    project_root = os.path.dirname(os.path.dirname(__file__))
    global_env = os.path.join(project_root, "config", "yunxi.env")
    if os.path.exists(global_env):
        load_dotenv(global_env, override=False)

    # 再加载模块自身的 .env（优先级高，可覆盖全局）
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)

    host = os.environ.get("M11_HOST", "0.0.0.0")
    port = int(os.environ.get("M11_PORT", "8011"))
    env = os.environ.get("M11_ENV", "development")
    workers = int(os.environ.get("M11_WORKERS", "1"))
    log_level = os.environ.get("M11_LOG_LEVEL", "info")

    print("=" * 60)
    print("  M11 MCP Bus - MCP总线服务")
    print("=" * 60)
    print(f"  Host:      {host}")
    print(f"  Port:      {port}")
    print(f"  Env:       {env}")
    print(f"  Log Level: {log_level}")
    print(f"  Workers:   {workers}")
    print(f"  API Docs:  http://localhost:{port}/docs")
    print(f"  Health:    http://localhost:{port}/api/v1/health")
    print("=" * 60)

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=(env == "development"),
        reload_dirs=[os.path.join(BASE_DIR, "src")] if env == "development" else None,
        workers=workers if env == "production" else None,
        log_level=log_level if env == "production" else "debug",
    )


if __name__ == "__main__":
    main()
