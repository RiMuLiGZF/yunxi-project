"""M2 技能集群 MCP 适配器启动脚本.

独立启动 M2 技能集群 MCP 适配器，注册到 M11 总线，
并提供 MCP 服务端点。

用法:
    python tools/start_m2_adapter.py

环境变量:
    M2_BASE_URL: M2 技能集群地址（默认 http://localhost:8002）
    M11_BUS_URL: M11 总线地址（默认 http://localhost:8011）
    M2_ADAPTER_HOST: 适配器监听地址（默认 0.0.0.0）
    M2_ADAPTER_PORT: 适配器监听端口（默认 8102）
    M2_ADAPTER_ENDPOINT: 适配器对外暴露的 MCP 端点地址
                         （总线通过此地址回调，默认自动拼接 host:port）
    M2_HEARTBEAT_INTERVAL: 心跳间隔（秒，默认 15）
    M2_USE_BRIDGE_MODE: 是否启用 M2 MCP 桥接模式（默认 true）
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from src.adapters.m2_adapter import M2SkillAdapter


def _get_env(key: str, default: str = "") -> str:
    """读取环境变量.

    Args:
        key: 环境变量名
        default: 默认值

    Returns:
        环境变量值
    """
    return os.environ.get(key, default)


def _get_env_bool(key: str, default: bool = True) -> bool:
    """读取布尔型环境变量.

    Args:
        key: 环境变量名
        default: 默认值

    Returns:
        布尔值
    """
    val = os.environ.get(key, "").lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off"):
        return False
    return default


def main() -> None:
    """启动 M2 技能集群 MCP 适配器."""
    # 读取配置
    m2_base_url = _get_env("M2_BASE_URL", "http://localhost:8002")
    bus_url = _get_env("M11_BUS_URL", "http://localhost:8011")
    host = _get_env("M2_ADAPTER_HOST", "0.0.0.0")
    port = int(_get_env("M2_ADAPTER_PORT", "8102"))
    heartbeat_interval = int(_get_env("M2_HEARTBEAT_INTERVAL", "15"))
    use_bridge_mode = _get_env_bool("M2_USE_BRIDGE_MODE", True)

    # 构建适配器端点地址（总线通过此地址回调本适配器）
    endpoint = _get_env("M2_ADAPTER_ENDPOINT", "")
    if not endpoint:
        # 如果没有显式指定，使用 host:port 拼接
        # 注意：0.0.0.0 需要替换为 localhost 或实际可访问地址
        if host == "0.0.0.0":
            endpoint = f"http://localhost:{port}/mcp"
        else:
            endpoint = f"http://{host}:{port}/mcp"

    print("=" * 60)
    print("M2 技能集群 MCP 适配器启动中...")
    print(f"  M2 技能集群地址: {m2_base_url}")
    print(f"  M11 总线地址:   {bus_url}")
    print(f"  适配器监听:     {host}:{port}")
    print(f"  MCP 端点:       {endpoint}")
    print(f"  桥接模式:       {'启用' if use_bridge_mode else '禁用'}")
    print(f"  心跳间隔:       {heartbeat_interval} 秒")
    print("=" * 60)

    # 创建适配器实例
    adapter = M2SkillAdapter(
        m2_base_url=m2_base_url,
        bus_url=bus_url,
        server_endpoint=endpoint,
        use_bridge_mode=use_bridge_mode,
    )

    # 注册到总线
    try:
        print("\n正在注册到 M11 总线...")
        result = adapter.register_to_bus()
        server_info = result.get("server", {})
        print(f"注册成功！server_id={server_info.get('id')}, name={server_info.get('name')}")
    except Exception as e:
        print(f"注册失败: {e}")
        print("将以未注册模式继续运行（仅本地 MCP 服务可用）")

    # 启动心跳
    try:
        adapter.start_heartbeat(interval=heartbeat_interval)
        print(f"心跳已启动（间隔 {heartbeat_interval} 秒）")
    except Exception as e:
        print(f"心跳启动失败: {e}")

    # 注册信号处理，优雅退出
    def _handle_signal(signum, frame):
        print("\n收到退出信号，正在停止适配器...")
        adapter.stop()
        print("适配器已停止，再见！")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # 启动 MCP 服务（阻塞式）
    print(f"\nMCP 服务已启动，监听端口 {port}")
    print("按 Ctrl+C 停止服务\n")

    try:
        adapter.run_server(port=port, host=host)
    except KeyboardInterrupt:
        print("\n正在停止适配器...")
        adapter.stop()
        print("适配器已停止，再见！")


if __name__ == "__main__":
    main()
