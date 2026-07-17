"""
云汐 M9 开发者工坊 - 配置管理模块

统一配置框架迁移版：
- 新接口：M9ModuleConfig（继承 BaseConfig，基于 pydantic-settings）
- 旧接口：Settings dataclass（保留，内部委托给 M9ModuleConfig，向后兼容）

负责管理系统全局配置，包括 VS Code 路径、工作区目录、MCP 服务、数据库等
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict


# ============================================================
# 尝试从统一配置基类导入，失败则降级到本地实现
# ============================================================

try:
    # 查找项目根目录并加入 sys.path
    _current = Path(__file__).resolve()
    for _ in range(10):
        _current = _current.parent
        if (_current / "shared" / "core" / "config.py").exists():
            if str(_current) not in sys.path:
                sys.path.insert(0, str(_current))
            break
    from shared.core.config import BaseConfig, EnvType
    _USE_UNIFIED_CONFIG = True
except ImportError:
    _USE_UNIFIED_CONFIG = False


# ============================================================
# 基础路径工具
# ============================================================

def _get_base_dir() -> Path:
    """获取项目基础目录（兼容直接运行和作为模块导入）"""
    if "__file__" in globals():
        return Path(__file__).resolve().parent.parent
    return Path.cwd()


# ============================================================
# M9 模块统一配置类（新接口）
# ============================================================

if _USE_UNIFIED_CONFIG:

    class M9ModuleConfig(BaseConfig):
        """
        M9 开发者工坊模块配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载
        - 环境变量覆盖
        - 生产环境敏感字段校验
        - 敏感字段脱敏
        - 配置热更新

        环境变量前缀：M9_
        旧环境变量名（YUNXI_M9_ 前缀）通过 alias 保持兼容。
        """

        # ---- 模块基础信息 ----
        module_name: str = Field(default="m9-dev-workshop", description="模块名称")
        port: int = Field(default=8009, ge=1, le=65535, description="服务监听端口")

        # ---- 基础路径配置 ----
        base_dir: str = Field(default_factory=lambda: str(_get_base_dir()), description="项目根目录")
        data_dir: str = Field(default="", description="数据目录（留空则自动计算）")
        db_path: str = Field(default="", description="数据库路径（留空则自动计算）")

        # ---- VS Code 配置 ----
        vscode_path: Optional[str] = Field(default=None, description="VS Code 可执行文件路径")
        vscode_candidate_paths: List[str] = Field(
            default_factory=lambda: [
                r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
                r"C:\Program Files\Microsoft VS Code\Code.exe",
                r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
                r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code Insiders\Code - Insiders.exe",
            ],
            description="VS Code 常见安装路径列表（Windows）",
        )

        # ---- 工作区配置 ----
        workspace_root: str = Field(
            default_factory=lambda: os.path.expanduser("~\\yunxi-workspace"),
            description="工作区根目录",
        )
        scan_dirs: List[str] = Field(
            default_factory=lambda: [
                os.path.expanduser("~\\Desktop"),
                os.path.expanduser("~\\Documents"),
                os.path.expanduser("~\\Projects"),
                os.path.expanduser("~\\workspace"),
            ],
            description="自动扫描的项目目录列表",
        )

        # ---- MCP 服务配置 ----
        mcp_enabled: bool = Field(default=True, description="MCP 服务是否启用")
        mcp_port: int = Field(default=8765, ge=1, le=65535, description="MCP 服务端口")

        # ---- 模块间调用配置 ----
        m8_control_tower_api: str = Field(
            default="http://localhost:8008/api",
            description="M8 控制塔 API 地址",
        )
        m5_memory_api: str = Field(
            default="http://localhost:8005/api",
            description="M5 潮汐记忆 API 地址",
        )
        m4_scene_api: str = Field(
            default="http://localhost:8004/api",
            description="M4 场景引擎 API 地址",
        )
        m8_inspection_api: str = Field(
            default="http://localhost:8003/api",
            description="M8 巡检 API 地址",
        )

        # ---- 服务配置 ----
        debug: bool = Field(default=True, description="调试模式")

        # ---- 代码执行配置 ----
        code_exec_timeout: int = Field(default=30, ge=1, description="代码执行超时时间（秒）")
        code_exec_sandbox_enabled: bool = Field(default=True, description="是否启用沙箱安全检测")

        model_config = SettingsConfigDict(
            env_prefix="M9_",
            env_file=".env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
            # 支持旧的 YUNXI_M9_ 前缀作为 alias
            alias_generator=None,
        )

        @field_validator("data_dir", mode="before")
        @classmethod
        def _default_data_dir(cls, v: str) -> str:
            """data_dir 为空时自动计算"""
            if not v:
                return str(_get_base_dir() / "data")
            return v

        @field_validator("db_path", mode="before")
        @classmethod
        def _default_db_path(cls, v: str) -> str:
            """db_path 为空时自动计算"""
            if not v:
                return str(_get_base_dir() / "data" / "yunxi_m9.db")
            return v

        # ---- VS Code 检测（保留原有方法） ----

        def detect_vscode(self) -> Optional[str]:
            """
            自动检测 VS Code 安装路径
            返回检测到的路径，未找到则返回 None
            """
            # 遍历候选路径
            for candidate in self.vscode_candidate_paths:
                # 展开环境变量
                expanded = os.path.expandvars(candidate)
                if os.path.isfile(expanded):
                    self.vscode_path = expanded
                    return expanded

            # 尝试从 PATH 环境变量查找 code 命令
            import shutil
            code_cmd = shutil.which("code")
            if code_cmd:
                # code 命令通常是 cmd 包装器，需要找到实际的 Code.exe
                code_dir = os.path.dirname(code_cmd)
                # 向上查找 bin 目录的父级
                parent = os.path.dirname(code_dir)
                code_exe = os.path.join(parent, "Code.exe")
                if os.path.isfile(code_exe):
                    self.vscode_path = code_exe
                    return code_exe
                # 直接返回 code 命令路径（可能是 .cmd）
                self.vscode_path = code_cmd
                return code_cmd

            return None

        def get_db_url(self) -> str:
            """获取 SQLAlchemy 数据库连接 URL"""
            return f"sqlite:///{Path(self.db_path).as_posix()}"

        def ensure_data_dir(self) -> None:
            """确保数据目录存在"""
            Path(self.data_dir).mkdir(parents=True, exist_ok=True)


    # ============================================================
    # 全局配置单例（新接口）
    # ============================================================

    _m9_config: Optional[M9ModuleConfig] = None

    def get_m9_config() -> M9ModuleConfig:
        """获取 M9 模块配置实例（单例模式，统一配置框架）"""
        global _m9_config
        if _m9_config is None:
            _m9_config = M9ModuleConfig()
            _m9_config.ensure_data_dir()
            _m9_config.detect_vscode()
        return _m9_config

else:
    # 降级：无法导入统一配置基类时的占位
    M9ModuleConfig = None  # type: ignore
    get_m9_config = None  # type: ignore


# ============================================================
# 向后兼容：旧的 Settings dataclass
# ============================================================
# 内部委托给 M9ModuleConfig，对外保持完全相同的接口
# ============================================================

from dataclasses import dataclass, field  # noqa: E402


@dataclass
class Settings:
    """
    系统配置类（向后兼容层）

    .. deprecated:: 2.0.0
        请使用 M9ModuleConfig 替代。
        旧的 Settings dataclass 内部已委托给 M9ModuleConfig，
        接口保持不变，可继续使用。
    """

    # 内部实际配置实例
    _inner: object = field(default=None, repr=False)

    def __init__(self, **kwargs):
        if _USE_UNIFIED_CONFIG and M9ModuleConfig is not None:
            self._inner = M9ModuleConfig(**kwargs)
            self._inner.ensure_data_dir()
        else:
            # 完全降级模式：使用旧的实现
            self._fallback_init(**kwargs)

    def _fallback_init(self, **kwargs):
        """降级模式下的初始化（旧 dataclass 逻辑）"""
        # 基础路径
        self.base_dir = kwargs.get("base_dir", _get_base_dir())
        self.data_dir = self.base_dir / "data"
        self.db_path = self.data_dir / "yunxi_m9.db"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # VS Code
        self.vscode_path = kwargs.get("vscode_path", None)
        self.vscode_candidate_paths = kwargs.get("vscode_candidate_paths", [
            r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
            r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code Insiders\Code - Insiders.exe",
        ])

        # 工作区
        self.workspace_root = kwargs.get("workspace_root", os.path.expanduser("~\\yunxi-workspace"))
        self.scan_dirs = kwargs.get("scan_dirs", [
            os.path.expanduser("~\\Desktop"),
            os.path.expanduser("~\\Documents"),
            os.path.expanduser("~\\Projects"),
            os.path.expanduser("~\\workspace"),
        ])

        # MCP
        self.mcp_enabled = kwargs.get("mcp_enabled", True)
        self.mcp_port = kwargs.get("mcp_port", 8765)
        self.m8_control_tower_api = kwargs.get("m8_control_tower_api", "http://localhost:8008/api")
        self.m5_memory_api = kwargs.get("m5_memory_api", "http://localhost:8005/api")
        self.m4_scene_api = kwargs.get("m4_scene_api", "http://localhost:8004/api")
        self.m8_inspection_api = kwargs.get("m8_inspection_api", "http://localhost:8003/api")

        # 服务
        self.host = kwargs.get("host", "0.0.0.0")
        self.port = kwargs.get("port", 8009)
        self.debug = kwargs.get("debug", True)
        self.cors_origins = kwargs.get("cors_origins", [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ])

        # 安全
        self.admin_token = kwargs.get("admin_token", "")

        # 代码执行
        self.code_exec_timeout = kwargs.get("code_exec_timeout", 30)
        self.code_exec_sandbox_enabled = kwargs.get("code_exec_sandbox_enabled", True)

        # 环境变量覆盖
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """从环境变量加载配置覆盖（YUNXI_M9_ 前缀）"""
        env_map = {
            "YUNXI_M9_HOST": ("host", str),
            "YUNXI_M9_PORT": ("port", int),
            "YUNXI_M9_DEBUG": ("debug", lambda v: v.lower() in ("true", "1", "yes")),
            "YUNXI_M9_WORKSPACE_ROOT": ("workspace_root", str),
            "YUNXI_M9_MCP_ENABLED": ("mcp_enabled", lambda v: v.lower() in ("true", "1", "yes")),
            "YUNXI_M9_MCP_PORT": ("mcp_port", int),
            "YUNXI_M9_ADMIN_TOKEN": ("admin_token", str),
            "YUNXI_M9_CODE_EXEC_TIMEOUT": ("code_exec_timeout", int),
            "YUNXI_M9_CODE_EXEC_SANDBOX": ("code_exec_sandbox_enabled", lambda v: v.lower() in ("true", "1", "yes")),
            "YUNXI_M9_M8_API": ("m8_control_tower_api", str),
            "YUNXI_M5_API": ("m5_memory_api", str),
            "YUNXI_M4_API": ("m4_scene_api", str),
            "YUNXI_M8_INSPECTION_API": ("m8_inspection_api", str),
        }
        for env_key, (attr_name, converter) in env_map.items():
            value = os.environ.get(env_key)
            if value is not None:
                try:
                    setattr(self, attr_name, converter(value))
                except (ValueError, TypeError):
                    pass

    # ---- 属性访问委托 ----

    def __getattr__(self, name):
        if name.startswith("_") or not _USE_UNIFIED_CONFIG or self._inner is None:
            raise AttributeError(f"'Settings' object has no attribute '{name}'")
        # 委托给内部 M9ModuleConfig
        try:
            return getattr(self._inner, name)
        except AttributeError:
            raise AttributeError(f"'Settings' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name.startswith("_") or not _USE_UNIFIED_CONFIG:
            super().__setattr__(name, value)
        else:
            if hasattr(self._inner, name):
                setattr(self._inner, name, value)
            else:
                super().__setattr__(name, value)

    # ---- 保留旧方法 ----

    def reload_config(self) -> dict:
        """重新加载环境变量覆盖，返回变更项"""
        if _USE_UNIFIED_CONFIG and hasattr(self._inner, 'reload'):
            return self._inner.reload()
        # 降级模式
        old_values = {}
        changes = {}
        tracked_attrs = ["host", "port", "debug", "mcp_enabled", "mcp_port",
                         "admin_token", "code_exec_timeout", "code_exec_sandbox_enabled",
                         "workspace_root"]
        for attr in tracked_attrs:
            old_values[attr] = getattr(self, attr)
        self._apply_env_overrides()
        for attr in tracked_attrs:
            new_val = getattr(self, attr)
            if old_values[attr] != new_val:
                changes[attr] = {"old": old_values[attr], "new": new_val}
        return changes

    def detect_vscode(self) -> Optional[str]:
        """自动检测 VS Code 安装路径"""
        if _USE_UNIFIED_CONFIG and hasattr(self._inner, 'detect_vscode'):
            return self._inner.detect_vscode()
        # 降级模式
        for candidate in self.vscode_candidate_paths:
            expanded = os.path.expandvars(candidate)
            if os.path.isfile(expanded):
                self.vscode_path = expanded
                return expanded
        import shutil
        code_cmd = shutil.which("code")
        if code_cmd:
            self.vscode_path = code_cmd
            return code_cmd
        return None

    def get_db_url(self) -> str:
        """获取 SQLAlchemy 数据库连接 URL"""
        if _USE_UNIFIED_CONFIG and hasattr(self._inner, 'get_db_url'):
            return self._inner.get_db_url()
        return f"sqlite:///{self.db_path.as_posix()}"


# ============================================================
# 全局配置单例（旧接口，向后兼容）
# ============================================================

_settings: Optional[Settings] = None


def get_settings(force_reload: bool = False) -> Settings:
    """获取全局配置实例（单例模式，向后兼容旧接口）"""
    global _settings
    if _settings is None or force_reload:
        old_settings = _settings
        _settings = Settings()
        _settings.detect_vscode()
        if old_settings is not None and not _USE_UNIFIED_CONFIG:
            _settings._apply_env_overrides()
    return _settings


# ============================================================
# 兼容直接运行测试
# ============================================================

if __name__ == "__main__":
    settings = get_settings()
    print(f"项目根目录: {settings.base_dir}")
    print(f"数据目录: {settings.data_dir}")
    print(f"数据库路径: {settings.db_path}")
    print(f"VS Code 路径: {settings.vscode_path}")
    print(f"工作区根目录: {settings.workspace_root}")
    print(f"MCP 服务端口: {settings.mcp_port}")
    if _USE_UNIFIED_CONFIG:
        print("使用统一配置框架: 是")
    else:
        print("使用统一配置框架: 否（降级模式）")
