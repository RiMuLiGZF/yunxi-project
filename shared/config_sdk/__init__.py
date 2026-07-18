"""
云汐系统 - 配置中心客户端 SDK

提供配置中心的客户端访问能力，包括：
- 自动拉取模块配置
- 本地缓存（内存 + 文件）
- 配置热更新（长轮询）
- 层级继承合并
- 配置变更回调
- 故障降级

使用方式：
    from shared.config_sdk import ConfigClient

    client = ConfigClient(module_name="m8", config={
        "config_center_url": "http://localhost:8008/api/config",
        "env": "development",
    })

    # 获取配置
    value = client.get("database.host", default="localhost")

    # 监听变更
    def on_change(key, old_val, new_val):
        print(f"配置 {key} 已变更: {old_val} -> {new_val}")

    listener_id = client.watch("database.host", on_change)
"""

from .client import ConfigClient
from .local_merger import LocalConfigMerger

__all__ = [
    "ConfigClient",
    "LocalConfigMerger",
]
