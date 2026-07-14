"""M8 管理工作台 - 模块入口.

支持从目录启动: python M8-control-tower
"""
import sys
from pathlib import Path

# 确保模块根目录、backend 目录和项目根目录在 sys.path 中
_BASE_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _BASE_DIR / "backend"
_PROJECT_ROOT = _BASE_DIR.parent

for p in (_PROJECT_ROOT, _BASE_DIR, _BACKEND_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backend.main import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)