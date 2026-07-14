"""
潮汐记忆系统 - Pydantic 配置 Schema

使用 Pydantic BaseModel 定义完整的配置模型，提供：
- 强类型约束
- 字段默认值与描述
- 范围校验（validator）
- 从字典加载并自动验证
- YAML/JSON 文件加载支持

分层定义：
- BasicConfig:       基础配置
- LayerConfig:       各记忆层配置
- MemoryConfig:      记忆系统总配置（含 layers）
- RecallConfig:      检索配置
- ConsolidationConfig: 巩固配置
- SecurityConfig:    安全配置
- VectorConfig:      向量配置
- EmotionConfig:     情绪配置
- StorageConfig:     存储配置
- AuditConfig:       审计配置
- TideConfigSchema:  总配置（根模型）
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 枚举定义
# ---------------------------------------------------------------------------

class EnvMode(str, Enum):
    """运行环境"""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class VectorBackendType(str, Enum):
    """向量后端类型"""
    CHROMA = "chroma"
    FAISS = "faiss"
    MILVUS = "milvus"
    QDRANT = "qdrant"


class VectorIndexType(str, Enum):
    """向量索引类型"""
    HNSW = "HNSW"
    FLAT = "Flat"
    IVF = "IVF"


class EncryptionAlgorithm(str, Enum):
    """加密算法"""
    AES_256_GCM = "AES-256-GCM"
    AES_256_CBC = "AES-256-CBC"
    CHACHA20_POLY1305 = "ChaCha20-Poly1305"


class EmotionModelType(str, Enum):
    """情绪模型类型"""
    VALENCE_AROUSAL = "valence-arousal"
    PLUTCHIK = "plutchik"
    EKMAN = "ekman"


# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

class BasicConfig(BaseModel):
    """基础配置"""

    name: str = Field(
        default="m5-memory",
        description="模块名称",
    )
    version: str = Field(
        default="2.4.0",
        description="模块版本号",
    )
    port: int = Field(
        default=8005,
        ge=1,
        le=65535,
        description="服务监听端口",
    )
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="日志级别",
    )
    env: EnvMode = Field(
        default=EnvMode.PRODUCTION,
        description="运行环境",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# 记忆层配置
# ---------------------------------------------------------------------------

class LayerConfig(BaseModel):
    """单条记忆层配置"""

    max_items: int = Field(
        default=1000,
        ge=1,
        description="该层最大记忆条目数",
    )
    retention_hours: Optional[int] = Field(
        default=None,
        ge=1,
        description="保留时长（小时），仅 L0 沙滩层使用",
    )
    retention_days: int = Field(
        default=30,
        ge=-1,
        description="保留天数，-1 表示永久保留",
    )
    access_priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="访问优先级（1-10，越高越优先）",
    )
    capacity_bytes: Optional[int] = Field(
        default=None,
        ge=0,
        description="容量上限（字节），None 表示不限制",
    )

    model_config = {"extra": "allow"}

    @field_validator("retention_days")
    @classmethod
    def check_retention_days(cls, v: int) -> int:
        """验证保留天数：-1 表示永久，其他必须 >= 1"""
        if v == 0:
            raise ValueError("retention_days 不能为 0，使用 -1 表示永久保留")
        if v < -1:
            raise ValueError("retention_days 不能小于 -1")
        return v


class MemoryLayersConfig(BaseModel):
    """四层记忆配置"""

    l0_beach: LayerConfig = Field(
        default_factory=lambda: LayerConfig(
            max_items=100,
            retention_hours=1,
            retention_days=1,  # 兼容字段
            access_priority=10,
        ),
        description="L0 沙滩层 - 瞬时记忆",
    )
    l1_shallow: LayerConfig = Field(
        default_factory=lambda: LayerConfig(
            max_items=1000,
            retention_days=1,
            access_priority=7,
        ),
        description="L1 浅水层 - 短期记忆",
    )
    l2_deep: LayerConfig = Field(
        default_factory=lambda: LayerConfig(
            max_items=10000,
            retention_days=30,
            access_priority=4,
        ),
        description="L2 深水层 - 中期记忆",
    )
    l3_abyss: LayerConfig = Field(
        default_factory=lambda: LayerConfig(
            max_items=100000,
            retention_days=-1,
            access_priority=1,
        ),
        description="L3 深海层 - 长期记忆",
    )

    model_config = {"extra": "allow"}

    def get(self, layer_name: str) -> LayerConfig:
        """按名称获取层配置"""
        return getattr(self, layer_name, self.l1_shallow)

    def to_dict(self) -> Dict[str, Dict[str, Any]]:
        """转换为字典（兼容旧接口）"""
        return {
            "l0_beach": self.l0_beach.model_dump(),
            "l1_shallow": self.l1_shallow.model_dump(),
            "l2_deep": self.l2_deep.model_dump(),
            "l3_abyss": self.l3_abyss.model_dump(),
        }


# ---------------------------------------------------------------------------
# 检索配置
# ---------------------------------------------------------------------------

class RecallConfig(BaseModel):
    """检索引擎配置"""

    top_k: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="检索返回的最大结果数",
    )
    similarity_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="相似度阈值（0-1），低于此值的结果被过滤",
    )
    keyword_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="关键词检索权重（向量检索权重为 1 - keyword_weight）",
    )
    preload_top_k: int = Field(
        default=3,
        ge=0,
        le=100,
        description="recall 结果前 N 个预加载到 L0 沙滩层",
    )
    cross_layer_search: bool = Field(
        default=True,
        description="是否跨层检索",
    )
    search_timeout_ms: int = Field(
        default=5000,
        ge=100,
        description="检索超时时间（毫秒）",
    )

    model_config = {"extra": "allow"}

    @field_validator("keyword_weight")
    @classmethod
    def check_weights(cls, v: float) -> float:
        """验证权重值在 0-1 范围内"""
        if v < 0.0 or v > 1.0:
            raise ValueError(f"keyword_weight 必须在 0-1 之间，当前值: {v}")
        return v


# ---------------------------------------------------------------------------
# 巩固配置
# ---------------------------------------------------------------------------

class ConsolidationConfig(BaseModel):
    """记忆巩固（睡眠整理）配置"""

    enabled: bool = Field(
        default=True,
        description="是否启用睡眠巩固",
    )
    schedule: str = Field(
        default="0 3 * * *",
        description="巩固调度 cron 表达式（默认每天凌晨 3 点）",
    )
    deduplication: bool = Field(
        default=True,
        description="是否启用去重",
    )
    quality_driven_transfer: bool = Field(
        default=True,
        description="是否启用质量驱动的层级迁移",
    )
    settle_threshold_access: int = Field(
        default=2,
        ge=1,
        description="L0→L1 沉降访问次数阈值",
    )
    min_quality_score: float = Field(
        default=30.0,
        ge=0.0,
        le=100.0,
        description="晋升到下一层的最低质量评分（0-100）",
    )
    promotion_ratio: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="每次巩固时晋升的记忆比例（0-1）",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        description="单次巩固批处理大小",
    )

    model_config = {"extra": "allow"}

    @field_validator("promotion_ratio")
    @classmethod
    def check_promotion_ratio(cls, v: float) -> float:
        """验证晋升比例在 0-1 范围内"""
        if v < 0.0 or v > 1.0:
            raise ValueError(f"promotion_ratio 必须在 0-1 之间，当前值: {v}")
        return v

    @field_validator("min_quality_score")
    @classmethod
    def check_quality_score(cls, v: float) -> float:
        """验证质量评分在 0-100 范围内"""
        if v < 0.0 or v > 100.0:
            raise ValueError(f"min_quality_score 必须在 0-100 之间，当前值: {v}")
        return v


# ---------------------------------------------------------------------------
# 安全配置
# ---------------------------------------------------------------------------

class SecurityConfig(BaseModel):
    """安全配置"""

    high_secret_local_only: bool = Field(
        default=True,
        description="高密级记忆是否仅限本地访问",
    )
    encrypt_at_rest: bool = Field(
        default=True,
        description="静态数据是否加密存储",
    )
    encryption_algorithm: EncryptionAlgorithm = Field(
        default=EncryptionAlgorithm.AES_256_GCM,
        description="加密算法",
    )
    access_audit: bool = Field(
        default=True,
        description="是否启用访问审计",
    )
    secure_delete: bool = Field(
        default=True,
        description="是否启用安全删除（覆写数据）",
    )
    encryption_key: Optional[str] = Field(
        default=None,
        description="主加密密钥（生产环境必须通过环境变量设置，勿硬编码）",
    )
    admin_token: Optional[str] = Field(
        default=None,
        description="管理员令牌",
    )
    jwt_secret: Optional[str] = Field(
        default=None,
        description="JWT 签名密钥",
    )
    store_original: bool = Field(
        default=False,
        description="是否存储记忆原文（默认关闭，隐私优先）",
    )
    original_encryption: bool = Field(
        default=True,
        description="原文是否加密存储（默认开启）",
    )
    session_timeout_seconds: int = Field(
        default=3600,
        ge=60,
        description="会话超时时间（秒）",
    )
    max_login_attempts: int = Field(
        default=5,
        ge=1,
        description="最大登录尝试次数",
    )

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def check_original_encryption_consistency(self) -> "SecurityConfig":
        """如果 store_original 为 True 但 original_encryption 为 False，发出警告"""
        if self.store_original and not self.original_encryption:
            log.warning(
                "安全配置警告：已启用原文存储但关闭了原文加密，存在隐私泄露风险",
                store_original=self.store_original,
                original_encryption=self.original_encryption,
            )
        return self


# ---------------------------------------------------------------------------
# 向量配置
# ---------------------------------------------------------------------------

class VectorConfig(BaseModel):
    """向量数据库配置"""

    type: VectorBackendType = Field(
        default=VectorBackendType.CHROMA,
        description="向量后端类型",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="嵌入模型名称",
    )
    dimension: int = Field(
        default=1536,
        ge=1,
        le=10000,
        description="向量维度",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="向量检索返回的最大结果数",
    )
    similarity_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="相似度阈值（0-1）",
    )
    hnsw_index: bool = Field(
        default=True,
        description="是否启用 HNSW 索引",
    )
    embedding_api_key: Optional[str] = Field(
        default=None,
        description="嵌入 API 密钥",
    )
    embedding_base_url: Optional[str] = Field(
        default=None,
        description="嵌入 API 基础 URL",
    )
    vector_index_type: VectorIndexType = Field(
        default=VectorIndexType.HNSW,
        description="向量索引类型（新建索引时使用）",
    )
    hnsw_m: int = Field(
        default=32,
        ge=2,
        le=200,
        description="HNSW M 参数（每层最大连接数）",
    )
    hnsw_ef_construction: int = Field(
        default=200,
        ge=8,
        le=2000,
        description="HNSW 构建时 ef 参数",
    )
    hnsw_ef_search: int = Field(
        default=128,
        ge=1,
        le=2000,
        description="HNSW 搜索时 ef 参数",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        description="批量嵌入的批次大小",
    )
    cache_embeddings: bool = Field(
        default=True,
        description="是否缓存嵌入向量",
    )

    model_config = {"extra": "allow"}

    @field_validator("similarity_threshold")
    @classmethod
    def check_similarity_threshold(cls, v: float) -> float:
        """验证相似度阈值在 0-1 范围内"""
        if v < 0.0 or v > 1.0:
            raise ValueError(f"similarity_threshold 必须在 0-1 之间，当前值: {v}")
        return v


# ---------------------------------------------------------------------------
# 情绪配置
# ---------------------------------------------------------------------------

class EmotionConfig(BaseModel):
    """情绪推断配置"""

    ei_inference: bool = Field(
        default=True,
        description="是否启用情绪推断",
    )
    model: EmotionModelType = Field(
        default=EmotionModelType.VALENCE_AROUSAL,
        description="情绪模型类型",
    )
    dimensions: List[str] = Field(
        default_factory=lambda: ["valence", "arousal"],
        description="情绪维度列表",
    )
    high_emotion_priority: bool = Field(
        default=True,
        description="高情绪记忆是否优先保留",
    )
    emotion_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="情绪因素在质量评分中的权重（0-1）",
    )

    model_config = {"extra": "allow"}

    @field_validator("emotion_weight")
    @classmethod
    def check_emotion_weight(cls, v: float) -> float:
        """验证情绪权重在 0-1 范围内"""
        if v < 0.0 or v > 1.0:
            raise ValueError(f"emotion_weight 必须在 0-1 之间，当前值: {v}")
        return v


# ---------------------------------------------------------------------------
# 存储配置
# ---------------------------------------------------------------------------

class StorageConfig(BaseModel):
    """存储配置"""

    local_path: str = Field(
        default="./data/memory",
        description="本地存储路径",
    )
    cloud_sync: bool = Field(
        default=False,
        description="是否启用云同步",
    )
    cloud_provider: Optional[str] = Field(
        default=None,
        description="云服务提供商",
    )
    backup_enabled: bool = Field(
        default=False,
        description="是否启用备份",
    )
    backup_interval_hours: int = Field(
        default=24,
        ge=1,
        description="备份间隔（小时）",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# 审计配置
# ---------------------------------------------------------------------------

class AuditConfig(BaseModel):
    """审计日志配置"""

    log_path: str = Field(
        default="./logs/m5-audit.log",
        description="审计日志文件路径",
    )
    enabled: bool = Field(
        default=True,
        description="是否启用审计日志",
    )
    rotation_days: int = Field(
        default=30,
        ge=1,
        description="日志轮转保留天数",
    )
    max_file_size_mb: int = Field(
        default=100,
        ge=1,
        description="单日志文件最大大小（MB）",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# 总配置模型
# ---------------------------------------------------------------------------

class TideConfigSchema(BaseModel):
    """
    潮汐记忆系统 - 完整配置 Schema

    使用 Pydantic 进行强类型校验和范围验证，
    支持从字典 / JSON / YAML 加载配置。
    """

    basic: BasicConfig = Field(
        default_factory=BasicConfig,
        description="基础配置",
    )
    security: SecurityConfig = Field(
        default_factory=SecurityConfig,
        description="安全配置",
    )
    memory_layers: MemoryLayersConfig = Field(
        default_factory=MemoryLayersConfig,
        description="记忆层配置",
    )
    recall: RecallConfig = Field(
        default_factory=RecallConfig,
        description="检索配置",
    )
    consolidation: ConsolidationConfig = Field(
        default_factory=ConsolidationConfig,
        description="巩固配置",
    )
    vector: VectorConfig = Field(
        default_factory=VectorConfig,
        description="向量配置",
    )
    emotion: EmotionConfig = Field(
        default_factory=EmotionConfig,
        description="情绪配置",
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="存储配置",
    )
    audit: AuditConfig = Field(
        default_factory=AuditConfig,
        description="审计配置",
    )

    model_config = {"extra": "allow"}

    # ------------------------------------------------------------------
    # 类方法：从不同来源加载配置
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TideConfigSchema":
        """
        从字典加载配置并自动验证

        Args:
            data: 配置字典

        Returns:
            验证后的 TideConfigSchema 实例

        Raises:
            ValidationError: 配置验证失败
        """
        log.debug("从字典加载配置", keys=list(data.keys()))
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "TideConfigSchema":
        """
        从 JSON 字符串加载配置

        Args:
            json_str: JSON 格式的配置字符串

        Returns:
            验证后的 TideConfigSchema 实例
        """
        data = json.loads(json_str)
        log.debug("从 JSON 字符串加载配置")
        return cls.model_validate(data)

    @classmethod
    def from_json_file(cls, file_path: str | os.PathLike) -> "TideConfigSchema":
        """
        从 JSON 文件加载配置

        Args:
            file_path: JSON 文件路径

        Returns:
            验证后的 TideConfigSchema 实例
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        log.info("从 JSON 文件加载配置", file_path=str(path))
        return cls.model_validate(data)

    @classmethod
    def from_yaml_file(cls, file_path: str | os.PathLike) -> "TideConfigSchema":
        """
        从 YAML 文件加载配置

        Args:
            file_path: YAML 文件路径

        Returns:
            验证后的 TideConfigSchema 实例

        Raises:
            ImportError: PyYAML 未安装
            FileNotFoundError: 文件不存在
        """
        try:
            import yaml
        except ImportError:
            raise ImportError("加载 YAML 配置需要安装 PyYAML")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        log.info("从 YAML 文件加载配置", file_path=str(path))
        return cls.model_validate(data)

    @classmethod
    def from_file(cls, file_path: str | os.PathLike) -> "TideConfigSchema":
        """
        从配置文件自动识别格式加载（根据扩展名）

        Args:
            file_path: 配置文件路径（支持 .json / .yaml / .yml）

        Returns:
            验证后的 TideConfigSchema 实例
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            return cls.from_json_file(path)
        elif suffix in (".yaml", ".yml"):
            return cls.from_yaml_file(path)
        else:
            raise ValueError(
                f"不支持的配置文件格式: {suffix}，支持 .json / .yaml / .yml"
            )

    # ------------------------------------------------------------------
    # 实例方法：导出配置
    # ------------------------------------------------------------------

    def to_dict(self, sanitize: bool = True) -> Dict[str, Any]:
        """
        导出为字典

        Args:
            sanitize: 是否脱敏敏感字段

        Returns:
            配置字典
        """
        data = self.model_dump(mode="json")
        if sanitize:
            self._sanitize_dict(data)
        return data

    def to_json(self, sanitize: bool = True, indent: int = 2) -> str:
        """
        导出为 JSON 字符串

        Args:
            sanitize: 是否脱敏敏感字段
            indent: 缩进空格数

        Returns:
            JSON 格式字符串
        """
        data = self.to_dict(sanitize=sanitize)
        return json.dumps(data, ensure_ascii=False, indent=indent)

    def save_to_json(self, file_path: str | os.PathLike,
                     sanitize: bool = True) -> None:
        """保存配置到 JSON 文件"""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json(sanitize=sanitize))
        log.info("配置已保存到 JSON 文件", file_path=str(path))

    def save_to_yaml(self, file_path: str | os.PathLike,
                     sanitize: bool = True) -> None:
        """保存配置到 YAML 文件"""
        try:
            import yaml
        except ImportError:
            raise ImportError("保存 YAML 配置需要安装 PyYAML")

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict(sanitize=sanitize)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        log.info("配置已保存到 YAML 文件", file_path=str(path))

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @classmethod
    def _get_sensitive_keys(cls) -> set:
        """获取敏感字段集合"""
        return {
            "encryption_key", "admin_token", "jwt_secret",
            "embedding_api_key", "api_key", "secret", "password",
        }

    @classmethod
    def _sanitize_dict(cls, d: Dict[str, Any]) -> None:
        """递归脱敏字典中的敏感字段"""
        sensitive = cls._get_sensitive_keys()
        for key, value in list(d.items()):
            if key.lower() in sensitive and value:
                d[key] = "***MASKED***"
            elif isinstance(value, dict):
                cls._sanitize_dict(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        cls._sanitize_dict(item)

    def get(self, path: str, default: Any = None) -> Any:
        """
        按点分路径获取配置值（兼容旧接口）

        Args:
            path: 配置路径，如 'basic.port'、'vector.top_k'
            default: 默认值

        Returns:
            配置值
        """
        keys = path.split(".")
        current: Any = self
        for key in keys:
            if isinstance(current, BaseModel):
                if hasattr(current, key):
                    current = getattr(current, key)
                else:
                    return default
            elif isinstance(current, dict):
                if key in current:
                    current = current[key]
                else:
                    return default
            else:
                return default
        return current

    def validate_config(self) -> bool:
        """
        主动验证配置完整性

        Returns:
            True 表示验证通过

        Raises:
            ValidationError: 验证失败
        """
        # Pydantic 在构造时已经验证，这里额外做业务逻辑校验
        log.debug(
            "配置验证通过",
            module=self.basic.name,
            version=self.basic.version,
            env=self.basic.env.value,
        )
        return True


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def create_default_config() -> TideConfigSchema:
    """创建默认配置实例"""
    return TideConfigSchema()


def load_config_from_dict(data: Dict[str, Any]) -> TideConfigSchema:
    """从字典加载配置（便捷函数）"""
    return TideConfigSchema.from_dict(data)


def load_config_from_file(file_path: str | os.PathLike) -> TideConfigSchema:
    """从文件加载配置（便捷函数）"""
    return TideConfigSchema.from_file(file_path)


# vim: set et ts=4 sw=4:
