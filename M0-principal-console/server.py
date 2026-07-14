"""
M0 主理人管控台 - 启动入口

运行方式:
    python server.py

默认端口: 8000
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
SRC_DIR = BASE_DIR / "src"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 尝试添加 yunxi-project 根目录（用于导入 shared 模块）
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 加载环境变量
# ---------------------------------------------------------------------------
def _load_env() -> None:
    """加载 .env 文件中的环境变量"""
    env_paths = [
        BASE_DIR / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path, override=False)
            except ImportError:
                # dotenv 不可用时手动加载
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, value = line.split("=", 1)
                                os.environ.setdefault(key.strip(), value.strip())
                except Exception:
                    pass


_load_env()

# ---------------------------------------------------------------------------
# 导入配置
# ---------------------------------------------------------------------------
from src.config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
def main() -> None:
    """启动 M0 主理人管控台"""
    print("=" * 60)
    print(f"  {settings.app_name} v{settings.version}")
    print(f"  {settings.app.description}")
    print("=" * 60)
    print(f"  监听地址: {settings.host}:{settings.port}")
    print(f"  运行环境: {settings.server.env}")
    print(f"  M8 地址: {settings.m8_base_url}")
    print(f"  API 文档: http://localhost:{settings.port}/api/docs")
    print("=" * 60)
    print()

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.server.env == "development",
        log_level="info",
    )


if __name__ == "__main__":
    main()
