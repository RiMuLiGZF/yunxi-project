"""
pytest 配置 - 测试路径统一注入 (ARC-006 修复)

统一管理 sys.path 注入，避免每个测试文件重复 sys.path.insert。

如需新增路径依赖，请在此处添加，不要在单个测试文件中使用 sys.path.insert。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 项目根目录（用于导入 shared 等公共包）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 模块源码目录（用于导入本模块源码）
_MODULE_SRC = Path(__file__).resolve().parents[1] / "src"

# 统一注入路径（模块源码优先，然后项目根目录）
for _p in (str(_MODULE_SRC), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _mock_httpx_post(monkeypatch):
    """全局 mock httpx.post，避免测试时调用外部服务（M2/M5 等）.

    所有测试默认 mock 掉跨模块 HTTP 调用，确保测试快速且不依赖外部服务。
    """
    try:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"success": True}}

        mock_post = MagicMock(return_value=mock_response)
        monkeypatch.setattr(httpx, "post", mock_post)
        monkeypatch.setattr(httpx, "get", mock_post)
    except (ImportError, AttributeError):
        pass
