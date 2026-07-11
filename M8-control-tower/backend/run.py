"""
M8 管理工作台 - 启动入口
直接运行这个文件启动服务
"""

import sys
import os
from pathlib import Path

# 将项目根目录加入 path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
