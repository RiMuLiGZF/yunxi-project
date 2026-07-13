"""M2 技能集群 - API 层.

提供 HTTP API、v2 标准接口、鉴权中间件、升级管理、测试管理等。
"""

from __future__ import annotations

from skill_cluster.api.http import (
    HealthResponse,
    InvokeRequest,
    SearchResponse,
    SkillInfo,
    create_http_app,
    manifest_to_skill_info,
    result_to_dict,
)
from skill_cluster.api.middleware.m8_auth import (
    M8TokenAuthMiddleware,
    check_production_requirements,
    get_admin_token_from_env,
)
from skill_cluster.api.test_endpoints import (
    TestManager,
    TestResultData,
    TestRunRequest,
    TestTaskResponse,
    register_test_routes,
)
from skill_cluster.api.upgrade import (
    CodeSnapshotData,
    UpgradeApplyRequest,
    UpgradeManager,
    UpgradePreviewRequest,
    UpgradeTaskResponse,
    register_upgrade_routes,
)
from skill_cluster.api.v2 import create_v2_app

__all__ = [
    # HTTP API
    "create_http_app",
    "InvokeRequest",
    "SkillInfo",
    "SearchResponse",
    "HealthResponse",
    "manifest_to_skill_info",
    "result_to_dict",
    # v2 API
    "create_v2_app",
    # 中间件
    "M8TokenAuthMiddleware",
    "get_admin_token_from_env",
    "check_production_requirements",
    # 升级管理
    "UpgradeManager",
    "UpgradePreviewRequest",
    "UpgradeApplyRequest",
    "UpgradeTaskResponse",
    "CodeSnapshotData",
    "register_upgrade_routes",
    # 测试管理
    "TestManager",
    "TestRunRequest",
    "TestTaskResponse",
    "TestResultData",
    "register_test_routes",
]
