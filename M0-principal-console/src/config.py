"""
M0 主理人管控台 - 配置管理

从 config.yaml 读取配置，支持环境变量覆盖。
与 M8 配置风格保持一致。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# 路径定义
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent
SRC_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"
CONFIG_PATH: Path = BASE_DIR / "config.yaml"

# 确保 data 目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 配置模型
# ---------------------------------------------------------------------------

class ServerConfig(BaseModel):
    """服务配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    env: str = "development"


class AppConfig(BaseModel):
    """应用信息配置"""
    name: str = "M0 主理人管控台"
    version: str = "0.1.0"
    description: str = "云汐系统舰长室 - 主理人专属工作台"


class M8Config(BaseModel):
    """M8 控制塔连接配置"""
    base_url: str = "http://localhost:8000"
    timeout: int = 10
    api_prefix: str = "/api"


class JWTConfig(BaseModel):
    """JWT 认证配置（与 M8 保持一致）"""
    secret: str = "m0-principal-console-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440


class PrincipalConfig(BaseModel):
    """主理人账号配置"""
    username: str = "owner"
    password: str = "owner123456"


class CORSConfig(BaseModel):
    """CORS 配置"""
    origins: List[str] = Field(default_factory=lambda: [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ])


class DataConfig(BaseModel):
    """数据目录配置"""
    data_path: str = "./data"


class Settings(BaseSettings):
    """M0 全局配置"""

    server: ServerConfig = Field(default_factory=ServerConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    m8: M8Config = Field(default_factory=M8Config)
    jwt: JWTConfig = Field(default_factory=JWTConfig)
    principal: PrincipalConfig = Field(default_factory=PrincipalConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    data: DataConfig = Field(default_factory=DataConfig)

    model_config = SettingsConfigDict(
        env_prefix="M0_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # 便捷属性
    @property
    def app_name(self) -> str:
        """应用名称"""
        return self.app.name

    @property
    def version(self) -> str:
        """版本号"""
        return self.app.version

    @property
    def host(self) -> str:
        """监听地址"""
        return self.server.host

    @property
    def port(self) -> int:
        """监听端口"""
        return self.server.port

    @property
    def jwt_secret(self) -> str:
        """JWT 密钥"""
        return self.jwt.secret

    @property
    def jwt_algorithm(self) -> str:
        """JWT 算法"""
        return self.jwt.algorithm

    @property
    def access_token_expire_minutes(self) -> int:
        """Token 过期时间（分钟）"""
        return self.jwt.access_token_expire_minutes

    @property
    def m8_base_url(self) -> str:
        """M8 基础地址"""
        return self.m8.base_url

    @property
    def data_dir(self) -> Path:
        """数据目录路径"""
        p = Path(self.data.data_path)
        return p.resolve() if p.is_absolute() else (BASE_DIR / self.data.data_path).resolve()


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

def _load_yaml_config(config_path: Path) -> dict:
    """从 YAML 文件加载配置"""
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def create_settings() -> Settings:
    """
    创建设置实例，优先级：环境变量 > YAML 配置 > 默认值

    Returns:
        Settings: 全局配置实例
    """
    yaml_config = _load_yaml_config(CONFIG_PATH)

    # 将 YAML 配置映射到 Settings 的子模型字段
    return Settings(**yaml_config)


# 全局单例
settings: Settings = create_settings()
