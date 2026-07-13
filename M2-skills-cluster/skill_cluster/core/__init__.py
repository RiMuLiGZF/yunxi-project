"""M2 技能集群 - 核心层.

核心层包含技能集群的核心组件：
    - registry: 技能注册中心
    - middleware: 中间件管道
    - router: 技能路由器
    - cache: 多级缓存系统
    - function_schema: Function Schema 生成器
    - pipeline: 流水线编排引擎
"""

from __future__ import annotations

from skill_cluster.core.cache import SkillCache
from skill_cluster.core.function_schema import (
    ActionSignature,
    FunctionParameter,
    FunctionSchema,
    SkillSchemaRegistry,
    build_signatures_from_function,
)
from skill_cluster.core.middleware import (
    Middleware,
    MiddlewarePipeline,
    cache_middleware,
    event_middleware,
    idempotent_middleware,
    logging_middleware,
    metrics_middleware,
    resilient_middleware,
)
from skill_cluster.core.registry import (
    DependencyNotFoundError,
    SkillAlreadyExistsError,
    SkillDependencyOccupiedError,
    SkillRegistry,
    SkillRegistryError,
)
from skill_cluster.core.router import SkillRouter

__all__ = [
    # 注册中心
    "SkillRegistry",
    "SkillRegistryError",
    "SkillAlreadyExistsError",
    "DependencyNotFoundError",
    "SkillDependencyOccupiedError",
    # 缓存
    "SkillCache",
    # 中间件
    "MiddlewarePipeline",
    "Middleware",
    "cache_middleware",
    "event_middleware",
    "resilient_middleware",
    "metrics_middleware",
    "logging_middleware",
    "idempotent_middleware",
    # 路由器
    "SkillRouter",
    # Function Schema
    "SkillSchemaRegistry",
    "FunctionSchema",
    "FunctionParameter",
    "ActionSignature",
    "build_signatures_from_function",
]
