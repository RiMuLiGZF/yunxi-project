"""M9 Programming Dev - 服务启动入口"""

import sys
import os

# 确保 src 目录在 Python 路径中
_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from m9_programming_dev.main import app
from m9_programming_dev.config import settings
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "m9_programming_dev.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
