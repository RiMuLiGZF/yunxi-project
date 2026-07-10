"""
云汐系统 - pytest 根配置
处理幽灵目录问题：某些目录在文件系统中可见但内容不可读
"""
import os
import sys

# 幽灵目录列表（目录项存在但内容不可读）
# 这些目录会导致 pytest 在收集阶段崩溃
GHOST_DIRS = [
    "M1-agent-cluster",
    "M2-skill-cluster",
    "M3-edge-cloud",
    "M4-scene-engine",
    "M5-tide-memory",
    "M6-hardware-hub",
    "M7-workflow",
    "M8-control-tower",
    "M9-dev-workshop",
    "M10-system-guard",
    "frontend",
]


def pytest_ignore_collect(collection_path, config):
    """pytest 收集钩子：忽略幽灵目录"""
    path_str = str(collection_path)
    basename = os.path.basename(path_str)

    # 忽略幽灵目录
    if basename in GHOST_DIRS and os.path.isdir(path_str):
        return True

    return None
