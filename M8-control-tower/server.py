"""
M8 管理工作台启动入口

运行方式:
    python server.py

默认端口: 8008
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"
PROJECT_ROOT = BASE_DIR.parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 加载环境变量
# ---------------------------------------------------------------------------
def _load_env() -> None:
    """加载 .env 文件中的环境变量."""
    # 优先加载全局配置
    env_paths = [
        PROJECT_ROOT / "config" / "yunxi.env",
        BASE_DIR / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path, override=False)
            except ImportError:
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key and key not in os.environ:
                                os.environ[key] = value
                except Exception:
                    pass

_load_env()

# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    """启动 FastAPI 服务."""
    from backend.main import app

    port = int(os.environ.get("M8_PORT", "8008"))
    host = os.environ.get("M8_HOST", "0.0.0.0")

    print("=" * 60)
    print("  M8 管理工作台")
    print("  Control Tower Server")
    print("=" * 60)
    print(f"  地址:      http://{host}:{port}")
    print(f"  前端入口:  http://localhost:{port}/startup/index.html")
    print(f"  管理台:    http://localhost:{port}/m8/login.html")
    print(f"  文档地址:  http://localhost:{port}/docs")
    print(f"  健康检查:  http://localhost:{port}/health")
    print("=" * 60)
    print()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
