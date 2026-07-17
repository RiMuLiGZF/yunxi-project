"""
M3 端云协同 - 统一配置框架接入（第二阶段基础设施）

新增 M3ModuleConfig 继承 BaseConfig，获得：
- 全局 .env 文件自动加载
- 生产环境敏感字段校验
- 配置热更新
- 敏感字段自动脱敏

原有 config_manager 配置体系保持不变，确保向后兼容。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    _current_m3_cfg = Path(__file__).resolve()
    for _ in range(10):
        _current_m3_cfg = _current_m3_cfg.parent
        if (_current_m3_cfg / "shared" / "core" / "config.py").exists():
            if str(_current_m3_cfg) not in sys.path:
                sys.path.insert(0, str(_current_m3_cfg))
            break
    from shared.core.config import BaseConfig
    from pydantic import Field
    from pydantic_settings import SettingsConfigDict
    _USE_UNIFIED_CONFIG_M3 = True
except ImportError:
    _USE_UNIFIED_CONFIG_M3 = False
    BaseConfig = None  # type: ignore
    Field = None  # type: ignore
    SettingsConfigDict = None  # type: ignore


if _USE_UNIFIED_CONFIG_M3:

    class M3ModuleConfig(BaseConfig):
        """
        M3 端云协同模块配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载（config/yunxi.env）
        - 环境变量覆盖（优先级最高）
        - 生产环境敏感字段校验
        - 敏感字段脱敏输出
        - 配置热更新

        环境变量前缀：M3_
        """

        module_name: str = Field(default="m3-edge-cloud", description="模块名称")
        port: int = Field(default=8003, ge=1, le=65535, description="服务监听端口")
        host: str = Field(default="0.0.0.0", description="服务监听地址")
        rate_limit_enabled: bool = Field(default=True, description="是否启用限流")
        circuit_breaker_enabled: bool = Field(default=True, description="是否启用熔断")

        model_config = SettingsConfigDict(
            env_prefix="M3_",
            env_file="config/yunxi.env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
        )

    # 全局配置单例（新接口）
    _m3_unified_config: Optional[M3ModuleConfig] = None

    def get_m3_unified_config() -> M3ModuleConfig:
        """获取 M3 模块统一配置实例（单例模式）"""
        global _m3_unified_config
        if _m3_unified_config is None:
            _m3_unified_config = M3ModuleConfig()
        return _m3_unified_config

else:
    M3ModuleConfig = None  # type: ignore
    get_m3_unified_config = None  # type: ignore


__all__ = [
    "M3ModuleConfig",
    "get_m3_unified_config",
    "_USE_UNIFIED_CONFIG_M3",
]
