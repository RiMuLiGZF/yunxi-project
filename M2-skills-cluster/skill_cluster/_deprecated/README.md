# 废弃代码归档目录

本目录存放 M2 技能集群（skill_cluster）中已废弃但尚未删除的历史代码。

## 归档原则

1. **归档而非删除**：所有废弃代码先归档，保留历史记录，待确认完全无引用后再考虑删除
2. **禁止引用**：生产代码和新代码禁止引用本目录下的任何模块
3. **记录迁移路径**：每个归档项都要说明功能迁移到了哪里

## 归档列表

### stubs/ - 向后兼容存根目录

- **归档日期**：2026-07-19
- **归档原因**：stubs 目录下 47 个存根文件均为纯重定向 + DeprecationWarning，无实际业务实现
- **原路径**：`skill_cluster/stubs/`
- **新路径**：兼容逻辑已整合到 `skill_cluster/__init__.py` 中的 `_DEPRECATED_MODULE_MAP` 动态模块机制
- **文件数量**：48 个（含 `__init__.py`）
- **代码行数**：约 1176 行（含 `__init__.py`）
- **回滚锚点**：`a03050e0b5af573768fd7840dfc376c34440cbbf`

#### 存根文件与新路径对应表

| 存根文件 | 新路径 |
|---------|--------|
| a2a_bus.py | skill_cluster.extensions.a2a.bus |
| a2a_protocol.py | skill_cluster.models.a2a |
| adaptive_router.py | skill_cluster.discovery.routers.adaptive |
| agent_memory.py | skill_cluster.agent.memory |
| agent_runtime.py | skill_cluster.agent.runtime |
| api_v2.py | skill_cluster.api.v2 |
| ast_scanner.py | skill_cluster.security.ast_scanner |
| circuit_breaker.py | skill_cluster.resilience.circuit_breaker |
| code_execution_bridge.py | skill_cluster.security.code_exec.bridge |
| config_center.py | skill_cluster.infrastructure.config_center |
| edge_cloud_orchestrator.py | skill_cluster.discovery.routers.edge_cloud |
| event_bus.py | skill_cluster.infrastructure.event_bus |
| function_schema.py | skill_cluster.core.function_schema |
| health_checker.py | skill_cluster.infrastructure.health.checker |
| hooks.py | skill_cluster.infrastructure.hooks |
| http_api.py | skill_cluster.api.http |
| idempotency.py | skill_cluster.resilience.idempotency |
| m8_auth_middleware.py | skill_cluster.api.middleware.m8_auth |
| mcp_bridge.py | skill_cluster.extensions.mcp.bridge |
| memory_skill_bridge.py | skill_cluster.agent.experience.memory_bridge |
| metrics.py | skill_cluster.infrastructure.metrics |
| middleware.py | skill_cluster.core.middleware |
| permissions.py | skill_cluster.security.permissions |
| pipeline_store.py | skill_cluster.core.pipeline.store |
| plugin_loader.py | skill_cluster.extensions.plugins.loader |
| rate_limiter.py | skill_cluster.resilience.rate_limiter |
| result_renderer.py | skill_cluster.security.code_exec.renderer |
| sandbox.py | skill_cluster.security.sandbox |
| skill_bandit_router.py | skill_cluster.discovery.routers.bandit |
| skill_cache.py | skill_cluster.core.cache |
| skill_discovery.py | skill_cluster.discovery.engine |
| skill_experience.py | skill_cluster.agent.experience.bank |
| skill_graph.py | skill_cluster.agent.experience.graph |
| skill_handbook.py | skill_cluster.agent.experience.handbook |
| skill_health.py | skill_cluster.infrastructure.health.skill_health |
| skill_pipeline.py | skill_cluster.core.pipeline |
| skill_recommender.py | skill_cluster.discovery.recommender |
| skill_registry.py | skill_cluster.core.registry |
| skill_router.py | skill_cluster.core.router |
| skill_selection.py | skill_cluster.discovery.selection |
| streaming.py | skill_cluster.infrastructure.streaming |
| test_endpoints.py | skill_cluster.api.test_endpoints |
| token_budget.py | skill_cluster.agent.token_budget |
| tool_lazy_discoverer.py | skill_cluster.discovery.lazy_discoverer |
| trace_aggregator.py | skill_cluster.infrastructure.tracing.aggregator |
| upgrade_endpoints.py | skill_cluster.api.upgrade |
| voice_polish.py | skill_cluster.extensions.voice_polish |

#### 向后兼容说明

旧路径 `skill_cluster.xxx`（如 `skill_cluster.skill_router`、`skill_cluster.circuit_breaker`）
仍然可用，但会发出 `DeprecationWarning`。兼容机制通过 `skill_cluster/__init__.py` 中的
`_DEPRECATED_MODULE_MAP` 和 `_create_deprecated_module()` 动态代理实现。

建议尽快将代码中的旧 import 路径更新为上表中的新路径。
