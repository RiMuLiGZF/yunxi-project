"""M2 Skill技能集群 - 配置管理模块.

统一管理所有配置，支持 YAML 文件 + 环境变量覆盖。
所有敏感配置必须通过环境变量注入，禁止硬编码。
"""

import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 配置子模型
# ============================================================

class BasicConfig(BaseModel):
    """基础配置."""
    name: str = "m2-skills"
    version: str = "3.10.0"
    port: int = 8002
    host: str = "0.0.0.0"
    log_level: str = "info"
    env: str = "production"
    worker_count: int = 2

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"debug", "info", "warn", "error"}
        if v.lower() not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return v.lower()


class SecurityConfig(BaseModel):
    """安全配置."""
    encryption_key: str = ""
    admin_token: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    jwt_secret: str = ""
    jwt_expire_hours: int = 24
    rate_limit_per_minute: int = 60
    max_file_size_mb: int = 10


class LLMModelConfig(BaseModel):
    """单个LLM模型配置."""
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 30
    max_retries: int = 3


class LLMConfig(BaseModel):
    """LLM配置."""
    primary: LLMModelConfig = Field(default_factory=LLMModelConfig)
    lightweight: LLMModelConfig = Field(default_factory=lambda: LLMModelConfig(
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=512,
        timeout=15,
        max_retries=2,
    ))
    embedding: LLMModelConfig = Field(default_factory=lambda: LLMModelConfig(
        model="text-embedding-3-small",
        temperature=0.0,
        max_tokens=8191,
        timeout=10,
        max_retries=2,
    ))


class RecommendationConfig(BaseModel):
    """推荐引擎配置."""
    weights: dict[str, float] = Field(default_factory=lambda: {
        "keyword": 0.25,
        "ngram": 0.25,
        "scene": 0.20,
        "history": 0.15,
        "preference": 0.10,
        "timeliness": 0.05,
    })
    top_k: int = 5
    min_confidence: float = 0.3
    max_candidates: int = 50
    cache_ttl_seconds: int = 300

    fuzzy_match_enabled: bool = True
    fuzzy_match_threshold: float = 0.6
    fuzzy_match_max_distance: int = 2


class SkillsExecutionConfig(BaseModel):
    """技能执行配置."""
    default_timeout: int = 30
    max_retries: int = 2
    max_concurrent: int = 10


class SkillsConfig(BaseModel):
    """技能配置."""
    enabled: list[str] = Field(default_factory=list)
    config_dir: str = "./skills"
    hot_reload: bool = False
    hot_reload_interval: int = 60
    execution: SkillsExecutionConfig = Field(default_factory=SkillsExecutionConfig)


class VoicePolishConfig(BaseModel):
    """VoicePolish配置."""
    enabled: bool = True
    pipeline: list[str] = Field(default_factory=lambda: [
        "denoise", "asr_correction", "term_protection",
        "style_adaptation", "fluency_enhancement",
    ])
    term_dictionary: str = "./data/terms.json"
    default_style: str = "natural"


class CodeExecSecurityConfig(BaseModel):
    """代码执行安全配置."""
    allow_network: bool = False
    allow_file_write: bool = False
    max_memory_mb: int = 512
    max_cpu_percent: int = 50


class CodeExecReplConfig(BaseModel):
    """REPL配置."""
    max_sessions_per_user: int = 3
    idle_timeout_minutes: int = 30
    max_history: int = 100


class CodeExecAutoFixConfig(BaseModel):
    """自动修复配置."""
    enabled: bool = True
    max_attempts: int = 3


class CodeExecutionConfig(BaseModel):
    """代码执行配置."""
    enabled: bool = True
    default_backend: str = "m7"
    default_timeout: int = 30
    max_retries: int = 3
    auto_fix: CodeExecAutoFixConfig = Field(default_factory=CodeExecAutoFixConfig)
    repl: CodeExecReplConfig = Field(default_factory=CodeExecReplConfig)
    security: CodeExecSecurityConfig = Field(default_factory=CodeExecSecurityConfig)


class DatabaseConfig(BaseModel):
    """数据库配置."""
    type: str = "sqlite"
    path: str = "./data/m2.db"
    host: str = ""
    port: int = 5432
    name: str = "m2_skills"
    user: str = ""
    password: str = ""


class McpA2AConfig(BaseModel):
    """MCP A2A桥接配置."""
    enabled: bool = True
    bus_agent_endpoint: str = ""
    callback_endpoint: str = ""


class McpConfig(BaseModel):
    """MCP配置."""
    enabled: bool = True
    servers: list[dict] = Field(default_factory=list)
    connect_timeout: int = 10
    request_timeout: int = 30
    a2a: McpA2AConfig = Field(default_factory=McpA2AConfig)


class LoggingConfig(BaseModel):
    """日志配置."""
    format: str = "json"
    level: str = "info"
    file: str = "./logs/m2.log"
    max_size: str = "100MB"
    max_files: int = 10
    console_output: bool = True
    sensitive_fields: list[str] = Field(default_factory=lambda: [
        "api_key", "password", "token", "secret", "authorization",
    ])
    trace_enabled: bool = True
    trace_id_header: str = "X-Trace-Id"


class CacheConfig(BaseModel):
    """缓存配置."""
    type: str = "memory"
    ttl_seconds: int = 300
    max_size: int = 1000
    redis_url: str = ""


class BudgetConfig(BaseModel):
    """预算配置."""
    enabled: bool = True
    default_skill_quota: int = 4000
    daily_budget: int = 100000
    low_watermark: int = 20


class HealthConfig(BaseModel):
    """健康检查配置."""
    check_interval: int = 30
    timeout: int = 5
    checks: list[str] = Field(default_factory=lambda: [
        "database", "llm_connection", "m7_connection", "skill_registry",
    ])


# ============================================================
# 主配置模型
# ============================================================

class AppConfig(BaseModel):
    """应用全局配置."""
    basic: BasicConfig = Field(default_factory=BasicConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    recommendation: RecommendationConfig = Field(default_factory=RecommendationConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    voice_polish: VoicePolishConfig = Field(default_factory=VoicePolishConfig)
    code_execution: CodeExecutionConfig = Field(default_factory=CodeExecutionConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)

    def validate_required(self) -> list[str]:
        """校验必填配置项，返回缺失的配置项列表."""
        missing: list[str] = []

        # 生产环境必须配置密钥
        if self.basic.env == "production":
            if not self.security.jwt_secret:
                missing.append("security.jwt_secret")
            if not self.security.encryption_key:
                missing.append("security.encryption_key")
            if not self.llm.primary.api_key:
                missing.append("llm.primary.api_key")

        return missing


# ============================================================
# 环境变量解析
# ============================================================

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _resolve_env_vars(value: Any) -> Any:
    """递归解析配置值中的 ${ENV_VAR} 占位符."""
    if isinstance(value, str):
        # 替换所有 ${VAR_NAME} 为环境变量值
        def replace(match: re.Match[str]) -> str:
            env_name = match.group(1)
            return os.environ.get(env_name, "")
        return _ENV_VAR_PATTERN.sub(replace, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    else:
        return value


# ============================================================
# 配置加载
# ============================================================

_config_instance: AppConfig | None = None


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """加载配置.

    优先级：
    1. 指定的配置文件
    2. 环境变量 M2_CONFIG_PATH 指定的路径
    3. 当前目录下的 config.yaml
    4. 默认配置

    Args:
        config_path: 配置文件路径

    Returns:
        AppConfig 配置实例
    """
    global _config_instance

    # 确定配置文件路径
    path = config_path or os.environ.get("M2_CONFIG_PATH") or "config.yaml"
    path = Path(path)

    config_dict: dict[str, Any] = {}

    if path.exists():
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                config_dict = yaml.safe_load(f) or {}
        except ImportError:
            # PyYAML 未安装，跳过文件加载
            pass
        except Exception:
            # 配置文件读取失败，使用默认
            pass

    # 解析环境变量占位符
    config_dict = _resolve_env_vars(config_dict)

    # 构建配置对象
    config = AppConfig(**config_dict)
    _config_instance = config
    return config


def get_config() -> AppConfig:
    """获取全局配置单例."""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance


def reload_config() -> AppConfig:
    """重新加载配置."""
    global _config_instance
    _config_instance = None
    return get_config()


# ============================================================
# ONNX Runtime 配置
# ============================================================

# ONNX 模型目录
ONNX_MODELS_DIR = os.getenv("ONNX_MODELS_DIR", os.path.expanduser("~/.yunxi/models/onnx"))

# 首选后端: auto / cpu / cuda / tensorrt
ONNX_PREFERRED_BACKEND = os.getenv("ONNX_PREFERRED_BACKEND", "auto")

# GPU 设备 ID
ONNX_GPU_DEVICE_ID = int(os.getenv("ONNX_GPU_DEVICE_ID", "0"))

# GPU 显存限制 (GB)
ONNX_GPU_MEMORY_LIMIT_GB = float(os.getenv("ONNX_GPU_MEMORY_LIMIT_GB", "4"))

# 是否自动加载注册的模型
ONNX_AUTO_LOAD = os.getenv("ONNX_AUTO_LOAD", "false").lower() == "true"

# 翻译技能是否启用 ONNX
ONNX_TRANSLATE_ENABLED = os.getenv("ONNX_TRANSLATE_ENABLED", "false").lower() == "true"

# 翻译 ONNX 模型名称
ONNX_TRANSLATE_MODEL = os.getenv("ONNX_TRANSLATE_MODEL", "")
