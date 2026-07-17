"""
M7 工作流构建器 - 统一配置框架接入（第二阶段基础设施）

新增 M7ModuleConfig 继承 BaseConfig，获得：
- 全局 .env 文件自动加载
- 生产环境敏感字段校验
- 配置热更新
- 敏感字段自动脱敏

原有 os.environ 读取方式保持不变，确保向后兼容。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    _current_m7_cfg = Path(__file__).resolve()
    for _ in range(10):
        _current_m7_cfg = _current_m7_cfg.parent
        if (_current_m7_cfg / "shared" / "core" / "config.py").exists():
            if str(_current_m7_cfg) not in sys.path:
                sys.path.insert(0, str(_current_m7_cfg))
            break
    from shared.core.config import BaseConfig
    from pydantic import Field
    from pydantic_settings import SettingsConfigDict
    _USE_UNIFIED_CONFIG_M7 = True
except ImportError:
    _USE_UNIFIED_CONFIG_M7 = False
    BaseConfig = None  # type: ignore
    Field = None  # type: ignore
    SettingsConfigDict = None  # type: ignore


if _USE_UNIFIED_CONFIG_M7:

    class M7ModuleConfig(BaseConfig):
        """
        M7 工作流构建器配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载（config/yunxi.env）
        - 环境变量覆盖（优先级最高）
        - 生产环境敏感字段校验
        - 敏感字段脱敏输出
        - 配置热更新

        环境变量前缀：M7_
        """

        module_name: str = Field(default="m7-workflow-builder", description="模块名称")
        port: int = Field(default=8007, ge=1, le=65535, description="服务监听端口")
        env: str = Field(default="development", description="运行环境")
        cors_origins: str = Field(default="*", description="CORS 允许来源")

        model_config = SettingsConfigDict(
            env_prefix="M7_",
            env_file="config/yunxi.env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
        )

    # 全局配置单例（新接口）
    _m7_unified_config: Optional[M7ModuleConfig] = None

    def get_m7_unified_config() -> M7ModuleConfig:
        """获取 M7 模块统一配置实例（单例模式）"""
        global _m7_unified_config
        if _m7_unified_config is None:
            _m7_unified_config = M7ModuleConfig()
        return _m7_unified_config

else:
    M7ModuleConfig = None  # type: ignore
    get_m7_unified_config = None  # type: ignore


__all__ = [
    "M7ModuleConfig",
    "get_m7_unified_config",
    "_USE_UNIFIED_CONFIG_M7",
]
