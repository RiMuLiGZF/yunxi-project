"""
M4 场景引擎 - 统一配置管理

集中管理所有环境变量配置，替代分散在各文件中的 os.environ.get 调用。

使用方式：
    from src.config import get_settings
    settings = get_settings()
    print(settings.port, settings.default_scene)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List
from functools import lru_cache


# ---------------------------------------------------------------------------
# 路径工具
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    """向上查找项目根目录（含 config/yunxi.env 的目录）"""
    current = Path(__file__).resolve().parent.parent.parent
    for _ in range(10):
        if (current / "config" / "yunxi.env").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return current.parent


def _load_env_files() -> None:
    """加载环境变量文件（全局 + 模块级）"""
    project_root = _find_project_root()

    # 1. 全局配置（优先级低）
    global_env = project_root / "config" / "yunxi.env"
    if global_env.exists():
        _load_dotenv(str(global_env), override=False)

    # 2. 模块级 .env（优先级高）
    module_env = Path(__file__).resolve().parent.parent / ".env"
    if module_env.exists():
        _load_dotenv(str(module_env), override=True)


def _load_dotenv(filepath: str, override: bool = False) -> None:
    """手动加载 .env 文件（兼容无 python-dotenv 的环境）"""
    try:
        from dotenv import load_dotenv
        load_dotenv(filepath, override=override)
        return
    except ImportError:
        pass

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("\'")
                if key and (override or key not in os.environ):
                    os.environ[key] = value
    except Exception:
        pass


# 启动时加载环境变量
_load_env_files()


# ---------------------------------------------------------------------------
# 配置类
# ---------------------------------------------------------------------------

class Settings:
    """M4 场景引擎配置"""

    def __init__(self) -> None:
        # ---- 基础服务 ----
        self.port = int(os.environ.get("M4_PORT", "8004"))
        self.host = os.environ.get("M4_HOST", "0.0.0.0")
        self.env = os.environ.get("M4_ENV", "development")

        # ---- CORS ----
        self.cors_origins = os.environ.get("CORS_ORIGINS", "*")

        # ---- 场景引擎 ----
        self.default_scene = os.environ.get("M4_DEFAULT_SCENE", "emotional")
        self.auto_switch = os.environ.get("M4_AUTO_SWITCH", "true").lower() == "true"
        self.switch_threshold = float(os.environ.get("M4_SWITCH_THRESHOLD", "0.7"))
        self.keyword_threshold = float(os.environ.get("M4_KEYWORD_THRESHOLD", "0.7"))
        self.max_history = int(os.environ.get("M4_MAX_HISTORY", "100"))

        # ---- LLM ----
        self.enable_llm = os.environ.get("M4_ENABLE_LLM", "false").lower() == "true"
        self.llm_base_url = os.environ.get("M4_LLM_BASE_URL", "")
        self.llm_model = os.environ.get("M4_LLM_MODEL", "")

        # ---- 数据 ----
        self.data_path = os.environ.get("M4_DATA_PATH", "")

        # ---- 安全 ----
        self.admin_token = os.environ.get("M4_ADMIN_TOKEN", "")

    @property
    def cors_origin_list(self) -> list:
        """CORS 允许源列表"""
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        """是否开发环境"""
        return self.env.lower() in ("dev", "development")

    @property
    def is_production(self) -> bool:
        """是否生产环境"""
        return self.env.lower() in ("prod", "production")


# ---------------------------------------------------------------------------
# 单例获取
# ---------------------------------------------------------------------------

_settings_instance = None

def get_settings() -> Settings:
    """获取配置单例"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


# 系统版本号（统一从 shared.version 导入）
# from shared.version import SYSTEM_VERSION
SYSTEM_VERSION = "0.4.0"  # 与 shared/version.py 保持同步
