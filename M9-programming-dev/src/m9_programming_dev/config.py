"""M9 Programming Dev - 配置管理"""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """M9配置"""
    
    # 服务配置
    app_name: str = "M9 Programming Dev"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8009
    
    # VSCode配置
    vscode_code_command: str = "code"
    vscode_default_workspace: str = os.path.expanduser("~/projects")
    vscode_port_range_start: int = 8080
    
    # 代码执行配置
    code_exec_timeout: int = 30
    code_exec_max_memory: int = 512  # MB
    code_exec_sandbox_enabled: bool = True
    
    # 项目配置
    projects_root_dir: str = os.path.expanduser("~/yunxi-projects")
    
    # M8 集成
    m8_api_url: str = "http://localhost:8008"
    m8_api_key: str = ""
    
    class Config:
        env_prefix = "M9_"
        env_file = ".env"


settings = Settings()
