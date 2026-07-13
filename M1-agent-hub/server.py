"""
M1 多Agent调度中心 - 启动入口

使用方式：
    python server.py
    python server.py --port 8001
    python server.py --host 0.0.0.0 --port 8001

配置加载优先级：
    1. 命令行参数
    2. 环境变量（M1_PORT、M1_HOST 等）
    3. 项目根目录 config/yunxi.env
    4. config.yaml
    5. 默认值
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 确保当前目录在 sys.path 中，以便模块导入
_current_dir = Path(__file__).resolve().parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

import structlog

from app_bootstrap import YunxiApplication

logger = structlog.get_logger(__name__)


def get_default_port() -> int:
    """获取默认端口：优先环境变量 M1_PORT，否则 8001"""
    port_str = os.environ.get("M1_PORT", "8001")
    try:
        return int(port_str)
    except (ValueError, TypeError):
        return 8001


def get_default_host() -> str:
    """获取默认监听地址：优先环境变量 M1_HOST，否则 0.0.0.0"""
    return os.environ.get("M1_HOST", "0.0.0.0")


async def main_async(
    host: str,
    port: int,
    config_path: str | None = None,
) -> None:
    """异步主函数"""
    logger.info(
        "m1_scheduler_starting",
        host=host,
        port=port,
        config=config_path or "default+env",
    )

    # 构建应用
    app = YunxiApplication(config_path=config_path)
    await app.build()
    await app.lifecycle.startup()
    app.lifecycle.setup_signal_handlers()

    # 启动 API 服务
    await app.start_api(host=host, port=port)

    logger.info(
        "m1_scheduler_started",
        host=host,
        port=port,
        version=app.config.get_str("basic.version", "11.1.0"),
    )
    print(f"\n  M1 多Agent调度中心已启动")
    print(f"  地址: http://{host}:{port}")
    print(f"  健康检查: http://{host}:{port}/health")
    print(f"  API 文档: http://{host}:{port}/docs\n")

    # 阻塞等待关闭信号
    await app.lifecycle.wait_for_shutdown()


def main() -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="M1 多Agent调度中心 - 云汐系统联邦调度引擎",
    )
    parser.add_argument(
        "--host",
        default=get_default_host(),
        help="API 服务监听地址（默认: 0.0.0.0，可通过 M1_HOST 环境变量设置）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=get_default_port(),
        help="API 服务监听端口（默认: 8001，可通过 M1_PORT 环境变量设置）",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="配置文件路径（可选，默认从 yunxi.env 和环境变量加载）",
    )
    args = parser.parse_args()

    asyncio.run(main_async(
        host=args.host,
        port=args.port,
        config_path=args.config,
    ))


if __name__ == "__main__":
    main()
