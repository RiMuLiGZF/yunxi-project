"""M9 Programming Dev - 服务启动入口"""

import sys
import os

# 将 src 目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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
