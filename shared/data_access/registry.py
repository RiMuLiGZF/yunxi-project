"""
数据模型注册中心（Model Registry）
==================================

集中管理所有模块的数据模型，支持：
- 模型注册与发现
- 模型关系定义
- 跨模块查询支持
- 模型版本管理
- 模型元数据查询

各模块可以在启动时注册自己的数据模型，
其他模块通过注册表查询和使用这些模型。
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Type
from enum import Enum

from .base import BaseModel


# ============================================================
# 模型分类
# ============================================================

class ModelCategory(str, Enum):
    """模型分类"""
    USER = "user"           # 用户相关
    CONTENT = "content"     # 内容相关
    SYSTEM = "system"       # 系统相关
    BUSINESS = "business"   # 业务相关
    ANALYTICS = "analytics"  # 分析相关


class DataSensitivity(str, Enum):
    """数据敏感度分级"""
    PUBLIC = "public"           # 公开数据
    INTERNAL = "internal"       # 内部数据
    CONFIDENTIAL = "confidential"  # 机密数据
    RESTRICTED = "restricted"   # 受限数据（最高级别）


# ============================================================
# 关系类型
# ============================================================

class RelationType(str, Enum):
    """关系类型"""
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


@dataclass
class RelationInfo:
    """
    模型关系定义。

    Attributes:
        source_model: 源模型名称
        target_model: 目标模型名称
        relation_type: 关系类型
        source_field: 源模型外键字段
        target_field: 目标模型关联字段
        through: 中间表模型（多对多时使用）
    """
    source_model: str
    target_model: str
    relation_type: RelationType
    source_field: str = ""
    target_field: str = ""
    through: Optional[str] = None


# ============================================================
# 模型信息
# ============================================================

@dataclass
class ModelInfo:
    """
    模型元信息。

    Attributes:
        name: 模型名称
        table_name: 表/集合名称
        module: 所属模块
        category: 模型分类
        sensitivity: 数据敏感度
        version: 模型版本
        description: 模型描述
        fields: 字段定义
        primary_key: 主键字段
        indexes: 索引字段列表
        created_at: 注册时间
        model_class: 模型类引用
    """
    name: str
    table_name: str
    module: str
    category: ModelCategory = ModelCategory.BUSINESS
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    version: str = "1.0.0"
    description: str = ""
    fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    primary_key: str = "id"
    indexes: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    model_class: Optional[Type[BaseModel]] = None


# ============================================================
# 模型注册表
# ============================================================

class ModelRegistry:
    """
    模型注册中心。

    集中管理所有模块的数据模型，支持：
    - 注册和查询模型
    - 定义模型间关系
    - 按模块/分类/敏感度查询模型
    - 模型版本管理

    使用方式：
        registry = get_model_registry()

        # 注册模型
        registry.register_model(UserModel, module="m8", category=ModelCategory.USER)

        # 查询模型
        model_info = registry.get_model("UserModel")

        # 定义关系
        registry.add_relation(
            source="UserModel",
            target="ProfileModel",
            relation_type=RelationType.ONE_TO_ONE,
            source_field="id",
            target_field="user_id",
        )
    """

    def __init__(self):
        self._models: Dict[str, ModelInfo] = {}
        self._relations: List[RelationInfo] = []
        self._model_classes: Dict[str, Type[BaseModel]] = {}
        self._lock = threading.RLock()

    # ---- 模型注册 ----

    def register_model(
        self,
        model_class: Type[BaseModel],
        module: str,
        category: ModelCategory = ModelCategory.BUSINESS,
        sensitivity: DataSensitivity = DataSensitivity.INTERNAL,
        version: str = "1.0.0",
        description: str = "",
        indexes: Optional[List[str]] = None,
    ) -> ModelInfo:
        """
        注册数据模型。

        Args:
            model_class: 模型类
            module: 所属模块 ID
            category: 模型分类
            sensitivity: 数据敏感度
            version: 模型版本
            description: 模型描述
            indexes: 索引字段列表

        Returns:
            模型信息对象
        """
        with self._lock:
            name = model_class.__name__
            table_name = model_class.get_table_name()

            # 确定主键
            pk_field = model_class.get_primary_key_field() or "id"

            info = ModelInfo(
                name=name,
                table_name=table_name,
                module=module,
                category=category,
                sensitivity=sensitivity,
                version=version,
                description=description,
                fields=dict(model_class.__fields__),
                primary_key=pk_field,
                indexes=indexes or [],
                model_class=model_class,
            )

            self._models[name] = info
            self._model_classes[name] = model_class

            return info

    def unregister_model(self, name: str) -> bool:
        """注销模型"""
        with self._lock:
            if name in self._models:
                del self._models[name]
                self._model_classes.pop(name, None)
                # 移除相关关系
                self._relations = [
                    r for r in self._relations
                    if r.source_model != name and r.target_model != name
                ]
                return True
            return False

    # ---- 模型查询 ----

    def get_model(self, name: str) -> Optional[ModelInfo]:
        """获取模型信息"""
        return self._models.get(name)

    def get_model_class(self, name: str) -> Optional[Type[BaseModel]]:
        """获取模型类"""
        return self._model_classes.get(name)

    def has_model(self, name: str) -> bool:
        """检查模型是否已注册"""
        return name in self._models

    def list_models(
        self,
        module: Optional[str] = None,
        category: Optional[ModelCategory] = None,
        sensitivity: Optional[DataSensitivity] = None,
    ) -> List[ModelInfo]:
        """
        列出模型（可筛选）。

        Args:
            module: 按模块筛选
            category: 按分类筛选
            sensitivity: 按敏感度筛选

        Returns:
            模型信息列表
        """
        with self._lock:
            result = list(self._models.values())

            if module:
                result = [m for m in result if m.module == module]
            if category:
                result = [m for m in result if m.category == category]
            if sensitivity:
                result = [m for m in result if m.sensitivity == sensitivity]

            return sorted(result, key=lambda m: m.name)

    def list_module_models(self, module: str) -> List[ModelInfo]:
        """列出指定模块的所有模型"""
        return self.list_models(module=module)

    def list_categories(self) -> List[str]:
        """列出所有模型分类"""
        return sorted(set(m.category.value for m in self._models.values()))

    def list_modules(self) -> List[str]:
        """列出所有注册了模型的模块"""
        return sorted(set(m.module for m in self._models.values()))

    # ---- 关系管理 ----

    def add_relation(
        self,
        source_model: str,
        target_model: str,
        relation_type: RelationType,
        source_field: str = "",
        target_field: str = "",
        through: Optional[str] = None,
    ) -> RelationInfo:
        """
        添加模型关系。

        Args:
            source_model: 源模型名称
            target_model: 目标模型名称
            relation_type: 关系类型
            source_field: 源模型外键字段
            target_field: 目标模型关联字段
            through: 中间表模型名（多对多时）

        Returns:
            关系信息对象
        """
        with self._lock:
            # 验证模型存在
            if source_model not in self._models:
                raise ValueError(f"Source model '{source_model}' not registered")
            if target_model not in self._models:
                raise ValueError(f"Target model '{target_model}' not registered")

            relation = RelationInfo(
                source_model=source_model,
                target_model=target_model,
                relation_type=relation_type,
                source_field=source_field,
                target_field=target_field,
                through=through,
            )
            self._relations.append(relation)
            return relation

    def get_relations(self, model_name: str) -> List[RelationInfo]:
        """获取指定模型的所有关系"""
        return [
            r for r in self._relations
            if r.source_model == model_name or r.target_model == model_name
        ]

    def get_outgoing_relations(self, model_name: str) -> List[RelationInfo]:
        """获取从指定模型出发的关系"""
        return [r for r in self._relations if r.source_model == model_name]

    def get_incoming_relations(self, model_name: str) -> List[RelationInfo]:
        """获取指向指定模型的关系"""
        return [r for r in self._relations if r.target_model == model_name]

    def get_all_relations(self) -> List[RelationInfo]:
        """获取所有关系"""
        return list(self._relations)

    # ---- 跨模块查询支持 ----

    def find_related_models(self, model_name: str, depth: int = 1) -> List[str]:
        """
        查找与指定模型相关联的模型（含关联深度）。

        Args:
            model_name: 起始模型名称
            depth: 关联深度

        Returns:
            相关模型名称列表
        """
        if depth <= 0:
            return []

        visited: Set[str] = set()
        current_level = {model_name}

        for _ in range(depth):
            next_level: Set[str] = set()
            for model in current_level:
                relations = self.get_relations(model)
                for rel in relations:
                    related = (
                        rel.target_model if rel.source_model == model
                        else rel.source_model
                    )
                    if related not in visited:
                        next_level.add(related)
            visited.update(next_level)
            current_level = next_level
            if not current_level:
                break

        visited.discard(model_name)
        return sorted(visited)

    # ---- 版本管理 ----

    def get_model_version(self, name: str) -> Optional[str]:
        """获取模型版本"""
        info = self.get_model(name)
        return info.version if info else None

    def check_compatibility(self, name: str, required_version: str) -> bool:
        """
        检查模型版本是否兼容。

        简单实现：主版本号一致则兼容。
        """
        info = self.get_model(name)
        if not info:
            return False

        current_major = info.version.split(".")[0]
        required_major = required_version.split(".")[0]
        return current_major == required_major

    # ---- 统计信息 ----

    def get_stats(self) -> Dict[str, Any]:
        """获取注册中心统计信息"""
        with self._lock:
            modules = {}
            categories = {}
            sensitivities = {}

            for info in self._models.values():
                modules[info.module] = modules.get(info.module, 0) + 1
                categories[info.category.value] = categories.get(
                    info.category.value, 0
                ) + 1
                sensitivities[info.sensitivity.value] = sensitivities.get(
                    info.sensitivity.value, 0
                ) + 1

            return {
                "total_models": len(self._models),
                "total_relations": len(self._relations),
                "modules": modules,
                "categories": categories,
                "sensitivities": sensitivities,
            }


# ============================================================
# 全局单例
# ============================================================

_registry: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()


def get_model_registry() -> ModelRegistry:
    """获取模型注册中心单例"""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ModelRegistry()
    return _registry


def reset_model_registry() -> None:
    """重置模型注册中心（测试用）"""
    global _registry
    _registry = None
