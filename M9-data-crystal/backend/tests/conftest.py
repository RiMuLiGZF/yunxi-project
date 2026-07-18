"""
云汐 M9 数据水晶 - 测试配置
"""

import sys
from pathlib import Path

# 确保 backend 目录在 path 中
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
