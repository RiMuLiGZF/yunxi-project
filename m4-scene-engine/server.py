"""M4 场景引擎服务启动入口.

运行方式:
    python server.py

默认端口: 8004 (通过环境变量 M4_PORT 配置)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import uvicorn

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ---------------------------------------------------------------------------
# 加载环境变量
# ---------------------------------------------------------------------------
def _load_env() -> None:
    """加载环境变量（先全局后模块，模块配置优先级高）."""
    # 先加载全局配置
    project_root = BASE_DIR.parent
    global_env = project_root / "config" / "yunxi.env"
    if global_env.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(global_env), override=False)
        except ImportError:
            # 手动解析
            try:
                with open(global_env, "r", encoding="utf-8") as f:
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

    # 再加载模块自身的 .env（可覆盖全局）
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path), override=True)
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
                        os.environ[key] = value
            except Exception:
                pass

_load_env()

# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    """启动 FastAPI 服务."""
    from src.main import app

    port = int(os.environ.get("M4_PORT", "8004"))
    host = os.environ.get("M4_HOST", "0.0.0.0")

    print("=" * 60)
    print("  M4 场景引擎服务")
    print("  Scene Engine Server")
    print("=" * 60)
    print(f"  版本:      1.0.0")
    print(f"  地址:      {host}:{port}")
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
