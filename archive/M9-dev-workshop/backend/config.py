"""
云汐 M9 开发者工坊 - 配置管理模块
负责管理系统全局配置，包括 VS Code 路径、工作区目录、MCP 服务、数据库等
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


def _get_base_dir() -> Path:
    """获取项目基础目录（兼容直接运行和作为模块导入）"""
    if "__file__" in globals():
        return Path(__file__).resolve().parent.parent
    return Path.cwd()


@dataclass
class Settings:
    """系统配置类"""

    # ===== 基础路径配置 =====
    # 项目根目录
    base_dir: Path = field(default_factory=_get_base_dir)
    # 数据目录
    data_dir: Path = field(init=False)
    # 数据库路径（SQLite）
    db_path: Path = field(init=False)

    # ===== VS Code 配置 =====
    # VS Code 可执行文件路径（自动检测后填充）
    vscode_path: Optional[str] = None
    # VS Code 常见安装路径列表（Windows）
    vscode_candidate_paths: List[str] = field(default_factory=lambda: [
        r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
        r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code Insiders\Code - Insiders.exe",
    ])

    # ===== 工作区配置 =====
    # 工作区根目录
    workspace_root: str = field(default_factory=lambda: os.path.expanduser("~\\yunxi-workspace"))
    # 自动扫描的项目目录列表
    scan_dirs: List[str] = field(default_factory=lambda: [
        os.path.expanduser("~\\Desktop"),
        os.path.expanduser("~\\Documents"),
        os.path.expanduser("~\\Projects"),
        os.path.expanduser("~\\workspace"),
    ])

    # ===== MCP 服务配置 =====
    # MCP 服务是否启用
    mcp_enabled: bool = True
    # MCP 服务端口
    mcp_port: int = 8765
    # 云汐内部服务 API 地址
    m8_control_tower_api: str = "http://localhost:8001/api"  # M8 控制塔
    m5_memory_api: str = "http://localhost:8002/api"         # M5 潮汐记忆
    m4_scene_api: str = "http://localhost:8003/api"          # M4 场景引擎
    m8_inspection_api: str = "http://localhost:8004/api"     # M8 巡检

    # ===== 服务配置 =====
    # 服务主机
    host: str = "0.0.0.0"
    # 服务端口
    port: int = 8009
    # 调试模式
    debug: bool = True
    # CORS 允许的源
    cors_origins: List[str] = field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ])

    # ===== 安全认证配置 =====
    # 管理员 Token
    admin_token: str = ""

    # ===== 代码执行配置 =====
    # 代码执行超时时间（秒）
    code_exec_timeout: int = 30
    # 是否启用沙箱安全检测
    code_exec_sandbox_enabled: bool = True

    def __post_init__(self):
        """初始化后处理：计算派生路径"""
        self.data_dir = self.base_dir / "data"
        self.db_path = self.data_dir / "yunxi_m9.db"
        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # P2-5: 环境变量覆盖（优先级高于默认值）
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
                    pass  # 转换失败则忽略，使用默认值

    def reload_config(self) -> dict:
        """重新加载环境变量覆盖，返回变更项"""
        old_values = {}
        changes = {}

        # 记录当前关键配置
        tracked_attrs = ["host", "port", "debug", "mcp_enabled", "mcp_port",
                         "admin_token", "code_exec_timeout", "code_exec_sandbox_enabled",
                         "workspace_root"]
        for attr in tracked_attrs:
            old_values[attr] = getattr(self, attr)

        # 重新应用环境变量
        self._apply_env_overrides()

        # 检测变更
        for attr in tracked_attrs:
            new_val = getattr(self, attr)
            if old_values[attr] != new_val:
                changes[attr] = {"old": old_values[attr], "new": new_val}

        return changes

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
        return f"sqlite:///{self.db_path.as_posix()}"


# 全局配置单例
_settings: Optional[Settings] = None


def get_settings(force_reload: bool = False) -> Settings:
    """获取全局配置实例（单例模式）"""
    global _settings
    if _settings is None or force_reload:
        old_settings = _settings
        _settings = Settings()
        _settings.detect_vscode()
        if old_settings is not None:
            _settings._apply_env_overrides()
    return _settings


# 兼容直接运行测试
if __name__ == "__main__":
    settings = get_settings()
    print(f"项目根目录: {settings.base_dir}")
    print(f"数据目录: {settings.data_dir}")
    print(f"数据库路径: {settings.db_path}")
    print(f"VS Code 路径: {settings.vscode_path}")
    print(f"工作区根目录: {settings.workspace_root}")
    print(f"MCP 服务端口: {settings.mcp_port}")
