"""
数据管理 API（Data Access API）
=============================

M8 控制塔 - 统一数据访问层管理接口。

提供以下能力：
- 数据模型管理（查询/列表）
- 统一查询接口
- 数据同步管理
- 数据质量检查
- 数据视图管理
- 数据迁移管理

API 前缀: /api/data
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

# 将项目根目录加入 path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.data_access import (
    BaseModel as DalBaseModel,
    get_model_registry,
    get_migration_manager,
)
from shared.data_access.backends import BackendType, create_backend
from shared.data_access.aggregation import (
    QueryService,
    AggregationQuery,
    AggregateFunc,
    JoinQuery,
    JoinType,
    get_view_manager,
    ViewCache,
)
from shared.data_access.quality import (
    QualityChecker,
    QualityRule,
    QualityRuleType,
    QualitySeverity,
    get_data_governance,
)
from shared.data_access.sync import (
    SyncEngine,
    SyncMode,
    SyncDirection,
    ConflictResolution,
    EventSyncManager,
)

router = APIRouter()


# ============================================================
# 请求/响应模型
# ============================================================

class QueryRequest(BaseModel):
    """高级查询请求"""
    model: str
    filters: List[Dict[str, Any]] = Field(default_factory=list, description="过滤条件列表 [{field, operator, value}]")
    order_by: List[Dict[str, Any]] = Field(default_factory=list, description="排序 [{field, ascending}]")
    page: int = 1
    page_size: int = 20


class AggregationRequest(BaseModel):
    """聚合查询请求"""
    model: str
    group_by: List[str] = Field(default_factory=list)
    aggregations: Dict[str, Dict[str, str]] = Field(
        default_factory=dict,
        description='聚合定义 {alias: {func: "count/sum/avg/min/max", field: "字段名"}}',
    )
    filters: List[Dict[str, Any]] = Field(default_factory=list)


class SyncTriggerRequest(BaseModel):
    """同步触发请求"""
    source: str = "local"
    target: str = "remote"
    mode: str = "incremental"
    direction: str = "bidirectional"
    conflict_resolution: str = "last_write_wins"
    models: Optional[List[str]] = None


class QualityCheckRequest(BaseModel):
    """质量检查请求"""
    models: List[str] = Field(default_factory=list, description="要检查的模型列表，空表示所有")
    rule_types: List[str] = Field(default_factory=list, description="检查类型过滤")


class MigrationUpgradeRequest(BaseModel):
    """迁移升级请求"""
    target_version: Optional[str] = None


class MigrationRollbackRequest(BaseModel):
    """迁移回滚请求"""
    target_version: Optional[str] = None


# ============================================================
# 服务实例
# ============================================================

# 使用内存后端作为默认演示实现
_backend = create_backend(BackendType.MEMORY)
_query_service = QueryService()
_quality_checker = QualityChecker()
_event_sync = EventSyncManager()


def _get_query_service() -> QueryService:
    return _query_service


def _get_quality_checker() -> QualityChecker:
    return _quality_checker


def _get_event_sync() -> EventSyncManager:
    return _event_sync


# ============================================================
# 1. 数据模型接口
# ============================================================

@router.get("/models", summary="数据模型列表")
async def list_models(
    module: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取所有注册的数据模型列表。

    - **module**: 按模块筛选（如 m8, m4, m5）
    - **category**: 按分类筛选（user, content, system, business, analytics）
    """
    registry = get_model_registry()

    cat_filter = None
    if category:
        from shared.data_access.registry import ModelCategory
        try:
            cat_filter = ModelCategory(category)
        except ValueError:
            pass

    models = registry.list_models(module=module, category=cat_filter)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "models": [
                {
                    "name": m.name,
                    "table_name": m.table_name,
                    "module": m.module,
                    "category": m.category.value,
                    "sensitivity": m.sensitivity.value,
                    "version": m.version,
                    "description": m.description,
                    "fields_count": len(m.fields),
                    "primary_key": m.primary_key,
                }
                for m in models
            ],
            "total": len(models),
            "stats": registry.get_stats(),
        },
    }


@router.get("/models/{name}", summary="模型详情")
async def get_model_detail(name: str) -> Dict[str, Any]:
    """获取指定数据模型的详细信息，包括字段定义、索引等。"""
    registry = get_model_registry()
    model_info = registry.get_model(name)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    relations = registry.get_relations(name)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "name": model_info.name,
            "table_name": model_info.table_name,
            "module": model_info.module,
            "category": model_info.category.value,
            "sensitivity": model_info.sensitivity.value,
            "version": model_info.version,
            "description": model_info.description,
            "fields": model_info.fields,
            "primary_key": model_info.primary_key,
            "indexes": model_info.indexes,
            "created_at": model_info.created_at,
            "relations": [
                {
                    "target_model": r.target_model if r.source_model == name else r.source_model,
                    "relation_type": r.relation_type.value,
                    "direction": "outgoing" if r.source_model == name else "incoming",
                }
                for r in relations
            ],
        },
    }


# ============================================================
# 2. 统一查询接口
# ============================================================

@router.get("/query", summary="统一查询接口（GET）")
async def simple_query(
    model: str = Query(..., description="模型名称"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """
    简单分页查询接口。

    - **model**: 模型名称
    - **page**: 页码
    - **page_size**: 每页大小
    """
    from shared.data_access.base import QueryFilter

    qs = _get_query_service()
    repo = qs.get_repository(model)

    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository for model '{model}' not found")

    result = qs.query(
        model_name=model,
        page=page,
        page_size=page_size,
    )

    return {
        "code": 0,
        "message": "success",
        "data": result.to_dict(),
    }


@router.post("/query", summary="高级查询接口")
async def advanced_query(request: QueryRequest) -> Dict[str, Any]:
    """
    高级查询接口，支持复杂过滤和排序。

    **filters 格式**:
    ```json
    [{"field": "name", "operator": "eq", "value": "test"}]
    ```

    **支持的操作符**: eq, ne, gt, gte, lt, lte, in, not_in, like, contains, between, is_null, is_not_null

    **order_by 格式**:
    ```json
    [{"field": "created_at", "ascending": false}]
    ```
    """
    from shared.data_access.base import QueryFilter, OrderBy

    qs = _get_query_service()
    repo = qs.get_repository(request.model)

    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository for model '{request.model}' not found")

    # 构建过滤条件
    filters = []
    for f in request.filters:
        filters.append(QueryFilter(
            field=f.get("field", ""),
            operator=f.get("operator", "eq"),
            value=f.get("value"),
        ))

    # 构建排序
    order_by = []
    for ob in request.order_by:
        order_by.append(OrderBy(
            field=ob.get("field", ""),
            ascending=ob.get("ascending", True),
        ))

    result = qs.query(
        model_name=request.model,
        filters=filters,
        order_by=order_by,
        page=request.page,
        page_size=request.page_size,
    )

    return {
        "code": 0,
        "message": "success",
        "data": result.to_dict(),
    }


# ============================================================
# 3. 数据同步接口
# ============================================================

@router.get("/sync/status", summary="同步状态")
async def get_sync_status() -> Dict[str, Any]:
    """获取数据同步引擎的当前状态。"""
    # 返回内存中的同步状态（演示用）
    return {
        "code": 0,
        "message": "success",
        "data": {
            "is_syncing": False,
            "active_sync": None,
            "history_count": 0,
            "supported_modes": ["incremental", "full"],
            "supported_directions": ["push", "pull", "bidirectional"],
            "conflict_resolution_options": [
                "last_write_wins",
                "first_write_wins",
                "merge",
                "manual",
            ],
            "last_sync_at": None,
        },
    }


@router.post("/sync/trigger", summary="触发同步")
async def trigger_sync(request: SyncTriggerRequest) -> Dict[str, Any]:
    """
    触发数据同步任务。

    - **mode**: incremental（增量）或 full（全量）
    - **direction**: push / pull / bidirectional
    - **conflict_resolution**: 冲突解决策略
    - **models**: 指定同步的模型列表
    """
    # 演示实现：返回同步任务信息
    sync_id = f"sync_{int(time.time())}"

    try:
        mode = SyncMode(request.mode)
        direction = SyncDirection(request.direction)
        resolution = ConflictResolution(request.conflict_resolution)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {e}")

    return {
        "code": 0,
        "message": "sync_triggered",
        "data": {
            "sync_id": sync_id,
            "status": "running",
            "mode": mode.value,
            "direction": direction.value,
            "conflict_resolution": resolution.value,
            "source": request.source,
            "target": request.target,
            "models": request.models,
            "started_at": time.time(),
            "progress": {
                "total": 0,
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "conflicts": 0,
                "percent": 0,
            },
        },
    }


@router.get("/sync/history", summary="同步历史")
async def get_sync_history(
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """获取同步历史记录。"""
    # 演示实现
    return {
        "code": 0,
        "message": "success",
        "data": {
            "history": [],
            "total": 0,
            "limit": limit,
        },
    }


# ============================================================
# 4. 数据质量接口
# ============================================================

@router.get("/quality/report", summary="质量报告")
async def get_quality_report() -> Dict[str, Any]:
    """获取最新的数据质量报告。"""
    governance = get_data_governance()
    latest = governance.get_latest_report()

    if latest:
        return {
            "code": 0,
            "message": "success",
            "data": latest.to_dict(),
        }

    # 返回空报告
    return {
        "code": 0,
        "message": "success",
        "data": {
            "report_id": None,
            "generated_at": time.time(),
            "summary": {
                "models_checked": 0,
                "total_records": 0,
                "total_issues": 0,
                "overall_score": 0,
                "grade": "N/A",
            },
            "models": {},
        },
    }


@router.post("/quality/check", summary="质量检查")
async def run_quality_check(request: QualityCheckRequest) -> Dict[str, Any]:
    """
    执行数据质量检查。

    - **models**: 要检查的模型列表，空表示检查所有已注册模型
    - **rule_types**: 检查类型过滤（completeness/consistency/accuracy/uniqueness/timeliness）
    """
    checker = _get_quality_checker()
    registry = get_model_registry()
    governance = get_data_governance()

    # 确定要检查的模型
    model_names = request.models if request.models else [m.name for m in registry.list_models()]

    # 收集各模型数据
    models_data: Dict[str, List[Dict[str, Any]]] = {}
    model_classes: Dict[str, type] = {}

    qs = _get_query_service()
    for name in model_names:
        repo = qs.get_repository(name)
        if repo:
            items = repo.list_all()
            models_data[name] = [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in items
            ]
        model_class = registry.get_model_class(name)
        if model_class:
            model_classes[name] = model_class

    # 执行检查
    results = checker.check_all(models_data, model_classes)

    # 生成报告
    report = governance.generate_report(results)

    return {
        "code": 0,
        "message": "success",
        "data": report.to_dict(),
    }


# ============================================================
# 5. 数据视图接口
# ============================================================

@router.get("/views", summary="数据视图列表")
async def list_views() -> Dict[str, Any]:
    """获取所有数据视图列表。"""
    view_manager = get_view_manager()
    views = view_manager.list_views()

    return {
        "code": 0,
        "message": "success",
        "data": {
            "views": views,
            "total": len(views),
        },
    }


@router.get("/views/{name}", summary="视图数据")
async def get_view_data(
    name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str = Query("", description="访问角色（用于权限检查）"),
) -> Dict[str, Any]:
    """
    查询指定视图的数据。

    - **name**: 视图名称
    - **page**: 页码
    - **page_size**: 每页大小
    - **role**: 访问角色
    """
    view_manager = get_view_manager()
    view = view_manager.get_view(name)

    if not view:
        raise HTTPException(status_code=404, detail=f"View '{name}' not found")

    try:
        # 设置查询服务（如果未设置）
        if not hasattr(view_manager, '_query_service') or view_manager._query_service is None:
            view_manager.set_query_service(_get_query_service())

        result = view_manager.query_view(
            name=name,
            page=page,
            page_size=page_size,
            role=role,
        )
        return {
            "code": 0,
            "message": "success",
            "data": result,
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ============================================================
# 6. 数据迁移接口
# ============================================================

@router.get("/migration/status", summary="迁移状态")
async def get_migration_status() -> Dict[str, Any]:
    """获取数据迁移状态。"""
    manager = get_migration_manager()
    status = manager.get_status()

    # 获取详细历史
    history = manager.get_history()

    return {
        "code": 0,
        "message": "success",
        "data": {
            **status,
            "history": [
                {
                    "version": r.version,
                    "description": r.description,
                    "status": r.status.value,
                    "applied_at": r.applied_at,
                    "duration_ms": r.duration_ms,
                    "checksum": r.checksum,
                    "error_message": r.error_message,
                }
                for r in history
            ],
        },
    }


@router.post("/migration/upgrade", summary="升级迁移")
async def upgrade_migration(request: MigrationUpgradeRequest) -> Dict[str, Any]:
    """
    执行数据库升级迁移。

    - **target_version**: 目标版本，None 表示升级到最新版本
    """
    manager = get_migration_manager()

    try:
        executed = manager.upgrade(target_version=request.target_version)
        status = manager.get_status()

        return {
            "code": 0,
            "message": "upgrade_completed",
            "data": {
                "executed_count": len(executed),
                "executed_versions": [r.version for r in executed],
                "current_version": status["current_version"],
                "latest_version": status["latest_version"],
                "is_up_to_date": status["is_up_to_date"],
                "details": [
                    {
                        "version": r.version,
                        "description": r.description,
                        "status": r.status.value,
                        "duration_ms": r.duration_ms,
                        "error": r.error_message,
                    }
                    for r in executed
                ],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Migration upgrade failed: {str(e)}")


@router.post("/migration/rollback", summary="回滚迁移")
async def rollback_migration(request: MigrationRollbackRequest) -> Dict[str, Any]:
    """
    执行数据库回滚。

    - **target_version**: 回滚到的目标版本，None 表示回滚上一个版本
    """
    manager = get_migration_manager()

    try:
        rolled_back = manager.rollback(target_version=request.target_version)
        status = manager.get_status()

        return {
            "code": 0,
            "message": "rollback_completed",
            "data": {
                "rolled_back_count": len(rolled_back),
                "rolled_back_versions": [r.version for r in rolled_back],
                "current_version": status["current_version"],
                "details": [
                    {
                        "version": r.version,
                        "description": r.description,
                        "status": r.status.value,
                        "duration_ms": r.duration_ms,
                        "error": r.error_message,
                    }
                    for r in rolled_back
                ],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Migration rollback failed: {str(e)}")


# ============================================================
# 注册数据模型（初始化时调用）
# ============================================================

def register_demo_models() -> None:
    """注册演示模型（开发/测试用）"""
    from shared.data_access.registry import ModelCategory, DataSensitivity

    registry = get_model_registry()

    # 如果已经注册过，跳过
    if registry.has_model("UserModel"):
        return

    class UserModel(DalBaseModel):
        __table_name__ = "users"
        __fields__ = {
            "id": {"type": int, "primary_key": True, "auto_increment": True},
            "username": {"type": str, "required": True, "unique": True},
            "email": {"type": str, "required": False},
            "role": {"type": str, "default": "viewer"},
            "status": {"type": str, "default": "active"},
            "created_at": {"type": float, "default": time.time},
            "updated_at": {"type": float, "default": time.time},
            "version": {"type": int, "default": 1},
        }

    class ProductModel(DalBaseModel):
        __table_name__ = "products"
        __fields__ = {
            "id": {"type": int, "primary_key": True, "auto_increment": True},
            "name": {"type": str, "required": True},
            "category": {"type": str, "default": "general"},
            "price": {"type": float, "default": 0.0},
            "stock": {"type": int, "default": 0},
            "created_at": {"type": float, "default": time.time},
            "updated_at": {"type": float, "default": time.time},
            "version": {"type": int, "default": 1},
        }

    class OrderModel(DalBaseModel):
        __table_name__ = "orders"
        __fields__ = {
            "id": {"type": int, "primary_key": True, "auto_increment": True},
            "user_id": {"type": int, "required": True},
            "product_id": {"type": int, "required": True},
            "quantity": {"type": int, "default": 1},
            "total_amount": {"type": float, "default": 0.0},
            "status": {"type": str, "default": "pending"},
            "created_at": {"type": float, "default": time.time},
            "updated_at": {"type": float, "default": time.time},
            "version": {"type": int, "default": 1},
        }

    # 注册模型
    registry.register_model(
        UserModel,
        module="m8",
        category=ModelCategory.USER,
        sensitivity=DataSensitivity.CONFIDENTIAL,
        description="用户账户模型",
    )

    registry.register_model(
        ProductModel,
        module="m8",
        category=ModelCategory.BUSINESS,
        sensitivity=DataSensitivity.INTERNAL,
        description="商品模型",
    )

    registry.register_model(
        OrderModel,
        module="m8",
        category=ModelCategory.BUSINESS,
        sensitivity=DataSensitivity.CONFIDENTIAL,
        description="订单模型",
    )

    # 创建仓库并注册到查询服务
    user_repo = _backend.create_repository(UserModel)
    product_repo = _backend.create_repository(ProductModel)
    order_repo = _backend.create_repository(OrderModel)

    _query_service.register_repository("UserModel", user_repo)
    _query_service.register_repository("ProductModel", product_repo)
    _query_service.register_repository("OrderModel", order_repo)

    # 注册关系
    from shared.data_access.registry import RelationType
    registry.add_relation(
        source_model="OrderModel",
        target_model="UserModel",
        relation_type=RelationType.MANY_TO_ONE,
        source_field="user_id",
        target_field="id",
    )
    registry.add_relation(
        source_model="OrderModel",
        target_model="ProductModel",
        relation_type=RelationType.MANY_TO_ONE,
        source_field="product_id",
        target_field="id",
    )

    # 注册质量规则
    from shared.data_access.quality.quality_checker import QualityRule, QualityRuleType, QualitySeverity
    _quality_checker.add_rule(QualityRule(
        name="UserModel.username.required",
        rule_type=QualityRuleType.COMPLETENESS,
        severity=QualitySeverity.ERROR,
        model_name="UserModel",
        field="username",
        description="用户名为必填字段",
    ))
    _quality_checker.add_rule(QualityRule(
        name="UserModel.username.unique",
        rule_type=QualityRuleType.UNIQUENESS,
        severity=QualitySeverity.ERROR,
        model_name="UserModel",
        field="username",
        description="用户名必须唯一",
    ))
    _quality_checker.add_rule(QualityRule(
        name="ProductModel.price.positive",
        rule_type=QualityRuleType.ACCURACY,
        severity=QualitySeverity.WARNING,
        model_name="ProductModel",
        field="price",
        description="价格应为正数",
    ))


# 初始化时注册演示模型
try:
    register_demo_models()
except Exception as e:
    print(f"Warning: Failed to register demo models: {e}")
