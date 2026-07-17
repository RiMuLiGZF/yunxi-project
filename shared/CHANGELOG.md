# Changelog

所有 `shared` 模块的重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范。

## [1.0.0] - 2026-07-17

### 新增
- 三层架构目录结构：`core/`、`data/`、`business/`
- `shared.__version__` 版本号（从 v1.0.0 开始）
- 各层 `__init__.py` 统一 re-export，支持 `from shared.core import ...` 用法
- DeprecationWarning 弃用警告，提示旧路径迁移

### 变更
- **架构重构**：将 shared 从单一扁平目录重构为三层结构
  - `shared/core/` — 基础工具层（无业务依赖）
    - config, logger, errors, responses, auth, security, cors_utils, utils, version
    - waf_middleware, logger_redis
    - middleware/（tracing）
    - observability/（unified_logger, tracing, metrics, fastapi_middleware）
  - `shared/data/` — 数据基础设施层
    - cache（内存 TTL+LRU 缓存）
    - data_layer/（database_manager, backup_manager, migration, migration_tools）
    - data_governance/（sovereignty, deduplication_plans）
  - `shared/business/` — 业务能力层（过渡期保留）
    - agent_engine, voice_engine, personality_engine, agent_team, multi_agent, reasoning_engine
    - cosyvoice_client/server/service, voice_preset_manager, prosody_controller, reminder_voice
    - user_profile, roles, context_aware, autonomous_learning, skill_evolution
    - rag_knowledge, long_term_memory, multimodal
    - a2a_client, llm_client, model_router
    - builtin_tools, tool_system
    - module_client, process_manager, startup_orchestrator
    - distributed/（node_config, node_registry, cluster_bus, api）

### 向后兼容
- 所有旧的 import 路径仍然可用（通过存根模块转发）
- 旧路径导入时会发出 `DeprecationWarning`，提示迁移到新路径
- 示例：
  ```python
  # 旧路径（仍可用，有警告）
  from shared.config import get_config
  
  # 新路径（推荐）
  from shared.core.config import get_config
  ```

### 弃用
- `shared.config`、`shared.logger` 等根级单文件模块 → 迁移至 `shared.core.*`
- `shared.cache` → 迁移至 `shared.data.cache`
- `shared.middleware` → 迁移至 `shared.core.middleware`
- `shared.data_layer` → 迁移至 `shared.data.data_layer`
- `shared.data_governance` → 迁移至 `shared.data.data_governance`
- `shared.observability` → 迁移至 `shared.core.observability`
- `shared.distributed` → 迁移至 `shared.business.distributed`
- 所有业务引擎模块（agent_engine, voice_engine 等）→ 迁移至 `shared.business.*`

---

## [0.5.0] - 2026-07-14

### 备注
- 重构前的历史版本，所有模块均在 shared 根目录下扁平组织
