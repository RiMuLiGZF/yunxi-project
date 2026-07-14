"""M11 MCP Bus - 模块入口.

支持从目录启动: python M11-mcp-bus
"""
import sys
from pathlib import Path

# 确保模块根目录和 src 目录在 sys.path 中
_BASE_DIR = Path(__file__).resolve().parent
_SRC_DIR = _BASE_DIR / "src"
_PROJECT_ROOT = _BASE_DIR.parent

for p in (_PROJECT_ROOT, _BASE_DIR, _SRC_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.main import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011)