"""
pytest 配置 - 测试路径统一注入 (ARC-006 修复)

统一管理 sys.path 注入，避免每个测试文件重复 sys.path.insert。

如需新增路径依赖，请在此处添加，不要在单个测试文件中使用 sys.path.insert。
"""
import sys
from pathlib import Path

# 项目根目录（用于导入 shared 等公共包）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 模块源码目录（用于导入本模块源码）
_MODULE_SRC = Path(__file__).resolve().parents[1] / "src"

# 统一注入路径（模块源码优先，然后项目根目录）
for _p in (str(_MODULE_SRC), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
