"""M3 端云协同内核 FastAPI 服务启动入口.

运行方式: python server.py
默认端口: 8003 (通过环境变量 M3_PORT 配置)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

# 路径配置
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from edge_cloud_kernel.core.app_factory import create_app, get_kernel_manager

# 创建应用（含组件初始化、环境加载、配置初始化）
app = create_app(base_dir=BASE_DIR)


def main() -> None:
    """启动 FastAPI 服务."""
    kernel = get_kernel_manager()
    port = int(os.environ.get("M3_PORT", "8003"))
    host = os.environ.get("M3_HOST", "0.0.0.0")

    # 从配置管理器读取端口
    if kernel is not None:
        config_mgr = kernel.get_component("config_manager")
        if config_mgr is not None and not kernel.is_mock("config_manager"):
            try:
                config_port = config_mgr.get("basic.port")
                if config_port:
                    port = int(config_port)
            except Exception:
                pass

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
