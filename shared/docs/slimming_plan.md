# shared 库瘦身计划

> 版本: v1.3.0 (瘦身第一步)
> 日期: 2026-07-19
> 级别: P2 质量优化
> 状态: 进行中

---

## 一、shared 库现状分析

### 1.1 总体概况

| 指标 | 数值 |
|------|------|
| 总模块数 | 243 个 .py 文件 |
| 总代码行数 | 89,526 行（不含空行/注释） |
| 总行数 | 117,359 行 |
| 核心基础模块 (5+引用) | 7 个 |
| 业务通用模块 (2-4引用) | 16 个 |
| 边缘模块 (1引用) | 51 个 |
| 无人引用模块 | 169 个 |
| 测试文件数 | 38 个 |

### 1.2 三层架构

```
shared/
├── core/          # 基础工具层 (222 行 __init__, 约 30+ 子模块)
│   ├── config, errors, logger, responses, auth, security
│   ├── utils, version, cors_utils, waf_middleware
│   ├── middleware/, observability/, audit_framework
│   ├── auth/, chaos/, ha/
│   └── bounded_collections, module_registry
├── data/          # 数据基础设施层 (87 行 __init__, 约 20+ 子模块)
│   ├── cache, multi_level_cache, index_optimizer
│   ├── data_layer/ (数据库/备份/迁移)
│   └── data_governance/
├── business/      # 业务能力层 (65 行 __init__, 约 30+ 子模块)
│   ├── module_client, process_manager, a2a_client
│   ├── agent_engine, voice_engine, personality_engine
│   ├── llm_client, model_router, rag_knowledge
│   ├── multi_agent, agent_team, reasoning_engine
│   ├── tool_system, builtin_tools, skill_evolution
│   ├── cosyvoice_* (5个语音相关模块)
│   ├── rag_services/ (RAG 服务子模块)
│   └── distributed/ (分布式基础设施)
├── config_sdk/    # 配置 SDK
├── module_sdk/    # 模块 SDK
├── data_access/   # 数据访问层 (另一套实现)
├── perf/          # 性能工具
├── i18n/          # 国际化
├── health/        # 健康检查
└── tests/         # 测试
```

### 1.3 引用分布（外部生产代码）

**核心基础 (5+ 引用) - 7 个模块:**
- `shared.core.observability` (27 引用) - 最核心
- `shared.core.config` (20 引用)
- `shared.core.errors` (17 引用)
- `shared.core.responses` (11 引用)
- `shared.business.module_client` (11 引用)
- `shared.core.version` (7 引用)
- `shared.module_client` (5 引用) - 顶层存根

**业务通用 (2-4 引用) - 16 个模块:**
- `shared.logger` (4)
- `shared.data.cache` (4)
- `shared.version` (4)
- `shared.user_profile` (3)
- `shared.llm_client` (3)
- `shared.data.data_layer.backup_manager` (3)
- `shared.core.auth.jwt` (2)
- `shared.core.audit_framework` (2)
- `shared.core.logger` (2)
- `shared.module_sdk.models` (2)
- `shared.business.process_manager` (2)
- `shared.data_layer` (2)
- `shared.business.startup_orchestrator` (2)
- `shared.i18n.core` (2)
- `shared.core.middleware.security_headers` (2)
- `shared.core.auth` (2)

### 1.4 主要问题

1. **顶层存根泛滥**: 顶层有 40+ 个 .py 文件，大部分是仅做 re-export 的弃用存根
2. **重复模块多**: 顶层 vs core vs business 有大量同名模块（如 config 出现在 3 个地方）
3. **死代码多**: 169 个模块（约 70%）没有任何外部引用
4. **导出过度**: `shared/__init__.py` 导出 110+ 个符号，远超实际需要
5. **大模块多**: 65 个模块超过 500 行代码，最大的 `backup_manager` 达 2313 行

---

## 二、第一步瘦身成果 (v1.3.0)

### 2.1 归档无人引用的顶层存根模块（A类）

将 24 个无人引用的顶层存根模块归档到 `shared/_deprecated/`，原位置保留兼容存根 + 弃用警告。

**归档文件列表 (24 个):**

| 模块 | 类型 | 目标路径 | 行数 |
|------|------|----------|------|
| `shared.a2a_client` | 存根 | `shared.business.a2a_client` | 22 |
| `shared.auth` | 存根 | `shared.core.auth` | 22 |
| `shared.builtin_tools` | 存根 | `shared.business.builtin_tools` | 22 |
| `shared.cache` | 存根 | `shared.data.cache` | 22 |
| `shared.config` | 存根 | `shared.core.config` | 22 |
| `shared.cors_utils` | 存根 | `shared.core.cors_utils` | 22 |
| `shared.cosyvoice_client` | 存根 | `shared.business.cosyvoice_client` | 22 |
| `shared.cosyvoice_server` | 存根 | `shared.business.cosyvoice_server` | 22 |
| `shared.cosyvoice_service` | 存根 | `shared.business.cosyvoice_service` | 22 |
| `shared.errors` | 存根 | `shared.core.errors` | 22 |
| `shared.logger_redis` | 存根 | `shared.core.logger_redis` | 22 |
| `shared.model_router` | 存根 | `shared.business.model_router` | 22 |
| `shared.process_manager` | 存根 | `shared.business.process_manager` | 22 |
| `shared.prosody_controller` | 存根 | `shared.business.prosody_controller` | 22 |
| `shared.reminder_voice` | 存根 | `shared.business.reminder_voice` | 22 |
| `shared.responses` | 存根 | `shared.core.responses` | 22 |
| `shared.roles` | 存根 | `shared.business.roles` | 22 |
| `shared.security` | 存根 | `shared.core.security` | 22 |
| `shared.startup_orchestrator` | 存根 | `shared.business.startup_orchestrator` | 22 |
| `shared.tool_system` | 存根 | `shared.business.tool_system` | 22 |
| `shared.utils` | 存根 | `shared.core.utils` | 22 |
| `shared.voice_engine` | 存根 | `shared.business.voice_engine` | 22 |
| `shared.voice_preset_manager` | 存根 | `shared.business.voice_preset_manager` | 22 |
| `shared.waf_middleware` | 存根 | `shared.core.waf_middleware` | 22 |

**归档存根包 (3 个):**

| 包 | 目标路径 |
|----|----------|
| `shared.data_governance` | `shared.data.data_governance` |
| `shared.distributed` | `shared.business.distributed` |
| `shared.middleware` | `shared.core.middleware` |

**瘦身效果:** 顶层 .py 文件从 42 个减少到 18 个（保留仍被引用的 + 新增 `_deprecated/` 目录）。

### 2.2 修复内部过时引用

修复了 2 处内部代码仍使用弃用路径的问题：

| 文件 | 修改前 | 修改后 |
|------|--------|--------|
| `business/module_client.py:23` | `from shared.config import get_config` | `from shared.core.config import get_config` |
| `business/module_client.py:24` | `from shared.cache import ...` | `from shared.data.cache import ...` |
| `business/voice_engine.py:492` | `from shared.cosyvoice_client import ...` | `from shared.business.cosyvoice_client import ...` |

### 2.3 精简 `shared/__init__.py` 导出

- `__all__` 从 **110+** 个符号精简到 **39** 个核心符号
- 所有符号仍可导入（保持向后兼容），但不推荐的符号不在 `__all__` 中
- 分为"推荐导入"和"兼容导入"两部分，清晰标注推荐路径

**推荐导入 (39 个符号):**
- 错误与异常: `YunxiError`, `ConfigError`, `ModuleNotFoundError`, `ModuleCallError`, `ValidationError`, `AuthenticationError`, `AuthorizationError`, `error_to_dict`
- 配置: `YunxiConfig`, `get_config`
- 日志: `get_logger`, `UnifiedLogger`
- API 响应: `ApiResponse`, `SUCCESS`, `ERROR_*` (7个错误码)
- 版本信息: `SYSTEM_VERSION`, `BUILD_DATE`, `VERSION_CODE`
- 模块客户端: `ModuleKey`, `ModuleCategory`, `ModuleInfo`, `ModuleClient`, `ModuleRegistry`, `ModuleStatus`, `get_registry`, `get_module_registry`, `DEFAULT_MODULE_CONFIGS`
- 通用工具: `generate_id`, `now_timestamp`, `now_iso`, `safe_get`, `truncate_text`, `format_file_size`

### 2.4 新增文件

| 文件 | 用途 |
|------|------|
| `shared/_deprecated/__init__.py` | 归档目录说明 |
| `shared/docs/slimming_plan.md` | 本文档 |
| `shared/pytest.ini` | shared 专用测试配置 |

---

## 三、四类可瘦身项清单

### A 类：无人引用的死模块（候选删除/归档）

**已处理 (第一步):** 24 个顶层存根 + 3 个存根包

**待处理 (后续步骤):** 约 142 个更多无人引用模块，包括：
- `shared.core.chaos.*` (3 个模块，混沌工程)
- `shared.core.ha.*` (4 个模块，高可用)
- `shared.core.auth.*` 子模块 (大部分 0 引用)
- `shared.core.observability.*` 子模块 (部分 0 引用)
- `shared.data.data_layer.*` 子模块 (大部分 0 引用)
- `shared.data_access.*` (整套数据访问层)
- `shared.config_sdk.*` (配置 SDK)
- `shared.module_sdk.*` (模块 SDK)
- `shared.perf.*` (性能工具)
- `shared.i18n.*` 子模块 (部分 0 引用)
- `shared.business.*` 子模块 (大量 0 引用)

### B 类：单模块专用的工具（候选迁移）

以下模块只被一个业务模块引用，可考虑迁移到该模块内部：

| 模块 | 引用者 | 建议 |
|------|--------|------|
| `shared.business.agent_engine` | M8-control-tower | 迁移到 M8 |
| `shared.business.agent_team` | M8-control-tower | 迁移到 M8 |
| `shared.business.autonomous_learning` | M8-control-tower | 迁移到 M8 |
| `shared.business.builtin_tools` | M8-control-tower | 迁移到 M8 |
| `shared.business.distributed` | M8-control-tower | 迁移到 M8 |
| `shared.business.llm_client` | M8-control-tower | 迁移到 M8 |
| `shared.business.long_term_memory` | M8-control-tower | 迁移到 M8 |
| `shared.business.multi_agent` | M8-control-tower | 迁移到 M8 |
| `shared.business.personality_engine` | M8-control-tower | 迁移到 M8 |
| `shared.business.rag_knowledge` | M8-control-tower | 迁移到 M8 |
| `shared.business.reminder_voice` | M8-control-tower | 迁移到 M8 |
| `shared.business.skill_evolution` | M8-control-tower | 迁移到 M8 |
| `shared.business.tool_system` | M8-control-tower | 迁移到 M8 |
| `shared.core.cors_utils` | M8-control-tower | 迁移到 M8 |
| `shared.core.module_registry` | M8-control-tower | 迁移到 M8 |
| `shared.core.waf_middleware` | M8-control-tower | 迁移到 M8 |
| `shared.data_access.*` | M8-control-tower | 迁移到 M8 |
| `shared.health.health_checker` | M8-control-tower | 迁移到 M8 |
| `shared.i18n.middleware` | M8-control-tower | 迁移到 M8 |
| `shared.perf.*` (8个模块) | M8-control-tower | 迁移到 M8 |
| `shared.business.model_router` | M1-agent-hub | 迁移到 M1 |
| `shared.business.distributed.cluster_bus` | M1-agent-hub | 迁移到 M1 |
| `shared.business.distributed.node_registry` | M1-agent-hub | 迁移到 M1 |
| `shared.core.observability.health` | M12-security-shield | 迁移到 M12 |
| `shared.i18n` | M10-system-guard | 迁移到 M10 |
| `shared.observability` | tools | 迁移到 tools |

> **注意**: 第一步只做标记，不实际迁移。需要第二步评估后逐步实施。

### C 类：重复/重叠功能（候选合并）

| 模块A | 模块B | 重叠说明 | 建议 |
|-------|-------|----------|------|
| `shared.data.cache` | `shared.data.multi_level_cache` | 缓存功能重叠 | 合并为统一缓存模块 |
| `shared.data.data_layer.migration` | `shared.data.data_layer.migration_enhanced` | 迁移引擎两套实现 | 合并到增强版 |
| `shared.data.data_layer.query_optimizer` | `shared.perf.query_optimizer` | 查询优化器重复 | 合并到 perf |
| `shared.core.middleware.tracing` | `shared.core.observability.tracing` | 链路追踪两套实现 | 合并到 observability |
| `shared.core.logger` | `shared.core.observability.unified_logger` | 日志系统两套 | 合并到 unified_logger |
| `shared.module_sdk.module_client` | `shared.business.module_client` | 模块客户端两套 | 评估后合并 |
| `shared.data_access.*` | `shared.data.data_layer.*` | 数据访问层两套 | 评估后合并 |
| `shared.business.rag_knowledge` | `shared.business.rag_services.*` | RAG 功能重叠 | 合并到 rag_services |
| `shared.core.module_registry` | `shared.module_sdk.registry` | 模块注册两套 | 评估后合并 |
| `shared.health.health_checker` | `shared.core.ha.health_checker_pro` | 健康检查两套 | 合并 |

### D 类：过大的模块（候选拆分）

Top 10 大模块:

| 模块 | 代码行数 | 建议 |
|------|----------|------|
| `shared.data.data_layer.backup_manager` | 2,313 | 拆分为 backup_core, backup_strategy, backup_scheduler |
| `shared.core.observability.alerting` | 1,856 | 拆分为 alerting_core, alert_channels, alert_rules |
| `shared.business.voice_engine` | 1,659 | 拆分为 voice_core, voice_synthesis, voice_management |
| `shared.business.model_router` | 1,478 | 拆分为 router_core, routing_strategies, model_adapters |
| `shared.core.audit_framework` | 1,368 | 拆分为 audit_core, audit_storage, audit_middleware |
| `shared.core.config` | 1,364 | 拆分为 config_core, config_sources, config_validators |
| `shared.core.auth.api_key_manager` | 1,278 | 拆分为 api_key_core, api_key_storage, api_key_rotation |
| `shared.data.data_layer.migration_tools` | 1,252 | 拆分为 migration_tools 子包 |
| `shared.business.rag_knowledge` | 1,162 | 与 rag_services 整合 |
| `shared.data.data_layer.migration` | 1,101 | 与 migration_enhanced 合并后拆分 |

---

## 四、后续瘦身计划

### 第二步 (v1.4.0)：业务模块迁移

**目标**: 将单引用的业务模块迁移到对应业务模块中

**计划**:
1. 将 M8-control-tower 专用的 20+ 个模块迁移到 M8 内部
2. 将 M1-agent-hub 专用模块迁移到 M1 内部
3. 迁移后在 shared 中保留导入别名 + 弃用警告
4. 预计减少 30+ 个模块，约 15,000 行代码

**风险**: 中 - 需要确保迁移后所有功能正常，需要充分测试

### 第三步 (v1.5.0)：重复模块合并

**目标**: 合并功能重叠的模块

**计划**:
1. 合并两套数据访问层（data_access vs data.data_layer）
2. 合并两套模块客户端（module_sdk vs business.module_client）
3. 合并 RAG 相关模块（rag_knowledge + rag_services）
4. 合并缓存模块（cache + multi_level_cache）
5. 合并迁移引擎（migration + migration_enhanced）
6. 预计减少 20+ 个模块

**风险**: 高 - 涉及核心功能重构，需要充分的回归测试

### 第四步 (v2.0.0)：彻底清理

**目标**: 移除所有已弃用的存根模块和别名

**计划**:
1. 移除 `_deprecated/` 目录中所有模块
2. 移除 `shared/__init__.py` 中的兼容导入
3. 移除所有顶层存根文件
4. 最终 shared 库只保留 core/data/business 三层架构

**风险**: 高 - 破坏性变更，需要提前至少 2 个版本通知

---

## 五、模块迁移指南

### 5.1 何时迁移

满足以下条件的模块可以考虑从 shared 迁移到业务模块：

1. **引用单一**: 只被一个业务模块引用（或主要被一个模块引用）
2. **业务绑定强**: 模块功能与特定业务强相关，非通用能力
3. **变更频率高**: 模块经常随业务需求变更，不适合作为稳定的共享库
4. **依赖关系简单**: 模块不被其他 shared 模块依赖（或依赖可解除）

### 5.2 迁移步骤

1. **评估阶段**
   - 确认模块的所有引用方
   - 分析模块的内部依赖（import 了哪些 shared 子模块）
   - 评估迁移后的影响范围

2. **准备阶段**
   - 在目标业务模块中创建对应目录
   - 复制模块代码到目标位置
   - 调整 import 路径（从 shared.xxx 改为相对路径或模块内路径）
   - 确保测试通过

3. **过渡阶段**
   - 在 shared 原位置保留导入别名（从新位置 re-export）
   - 添加 DeprecationWarning
   - 更新所有内部引用到新路径
   - 运行完整测试套件

4. **验证阶段**
   - 确认所有引用方已迁移到新路径
   - 确认没有功能回归
   - 监控运行时的弃用警告

5. **清理阶段**（至少一个版本后）
   - 移除 shared 中的弃用别名
   - 移除 _deprecated 中的归档文件
   - 更新文档

### 5.3 迁移检查清单

- [ ] 模块引用方已全部识别
- [ ] 模块内部依赖已分析
- [ ] 目标模块已有对应目录结构
- [ ] 代码已复制并调整 import
- [ ] 单元测试已迁移并通过
- [ ] 集成测试已通过
- [ ] 原位置保留了导入别名 + 弃用警告
- [ ] shared 内部引用已更新到新路径
- [ ] 文档已更新
- [ ] CHANGELOG 已记录

### 5.4 示例：迁移 voice_engine 到 M8

```python
# 迁移前: from shared.business.voice_engine import VoiceEngine
# 迁移后: from m8_control_tower.voice_engine import VoiceEngine

# shared 中保留的兼容存根:
import warnings
warnings.warn(
    "shared.business.voice_engine 已迁移到 M8-control-tower",
    DeprecationWarning,
    stacklevel=2
)
from m8_control_tower.voice_engine import *  # noqa
```

---

## 六、版本历史

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.3.0 | 2026-07-19 | 瘦身第一步：归档24个顶层存根+3个存根包，精简__init__导出，修复内部引用 |
| v1.2.0 | - | 三层架构重构（core/data/business） |
