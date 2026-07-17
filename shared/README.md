# Shared 公共组件库

> **模块代号**：shared
> **版本**：v1.0.0
> **架构**：三层架构（core / data / business）
> **说明**：云汐系统全局共享组件库，被所有模块引用

---

## 目录

- [一、模块概述](#一模块概述)
- [二、三层架构](#二三层架构)
- [三、core 层 — 基础工具](#三core-层--基础工具)
- [四、data 层 — 数据基础设施](#四data-层--数据基础设施)
- [五、business 层 — 业务能力](#五business-层--业务能力)
- [六、配置文件](#六配置文件)
- [七、使用说明](#七使用说明)
- [八、版本变更](#八版本变更)

---

## 一、模块概述

shared 是云汐系统的公共基础组件库，提供全局配置、统一日志、模块调用客户端、进程管理器等通用能力，供所有模块复用，避免重复造轮子。

### 设计原则

- **分层清晰**：三层架构（core/data/business），依赖自上而下
- **无循环依赖**：core 层不依赖 data 和 business
- **向后兼容**：旧的导入路径仍然可用（有弃用警告）
- **统一规范**：所有模块使用统一的错误码、响应格式、日志格式

---

## 二、三层架构

```
┌─────────────────────────────────────────────┐
│              business 业务能力层              │
│  Agent引擎 / 语音引擎 / LLM客户端 / 分布式等    │
├─────────────────────────────────────────────┤
│               data 数据基础设施层             │
│       缓存 / 数据库管理 / 数据治理             │
├─────────────────────────────────────────────┤
│                core 基础工具层                │
│  配置 / 日志 / 错误码 / 安全 / 鉴权 / 工具函数  │
└─────────────────────────────────────────────┘
```

| 层级 | 目录 | 职责 | 依赖方向 |
|------|------|------|---------|
| core | `shared/core/` | 基础工具，无业务依赖 | 不依赖其他层 |
| data | `shared/data/` | 数据基础设施 | 可依赖 core |
| business | `shared/business/` | 业务能力（过渡期） | 可依赖 core + data |

### 导入方式对照

| 旧路径（仍可用） | 新路径（推荐） | 层级 |
|-----------------|---------------|------|
| `shared.config` | `shared.core.config` | core |
| `shared.logger` | `shared.core.logger` | core |
| `shared.errors` | `shared.core.errors` | core |
| `shared.responses` | `shared.core.responses` | core |
| `shared.auth` | `shared.core.auth` | core |
| `shared.utils` | `shared.core.utils` | core |
| `shared.security` | `shared.core.security` | core |
| `shared.cache` | `shared.data.cache` | data |
| `shared.data_layer` | `shared.data.data_layer` | data |
| `shared.data_governance` | `shared.data.data_governance` | data |
| `shared.llm_client` | `shared.business.llm_client` | business |
| `shared.module_client` | `shared.business.module_client` | business |
| `shared.process_manager` | `shared.business.process_manager` | business |
| `shared.distributed` | `shared.business.distributed` | business |
| `shared.agent_engine` | `shared.business.agent_engine` | business |
| `shared.voice_engine` | `shared.business.voice_engine` | business |

> **迁移建议**：新代码请使用新的三层路径，旧代码可逐步迁移。

---

## 三、core 层 — 基础工具

core 层是最底层的基础工具，不包含任何业务逻辑，不依赖其他层。

### 3.1 核心模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **全局配置** | `core/config.py` | 统一从 yunxi.env 加载，管理 13 模块的端口/Host/Token/BaseURL |
| **统一日志** | `core/logger.py` | 结构化日志，统一格式，避免重复 handler |
| **统一错误** | `core/errors.py` | 自定义异常体系，6 位统一错误码，异常转字典工具 |
| **统一响应** | `core/responses.py` | 标准化 API 响应格式，全局异常处理器 |
| **通用工具** | `core/utils.py` | 随机 ID、时间戳、安全取值、文本截断、文件大小格式化 |
| **鉴权工具** | `core/auth.py` | API Key 管理、路径白名单、令牌桶限流、FastAPI 适配 |
| **安全工具** | `core/security.py` | XSS过滤、路径安全、文件上传验证、密码强度检查、日志脱敏 |
| **版本信息** | `core/version.py` | shared 库版本号 |
| **WAF 中间件** | `core/waf_middleware.py` | SQL注入/XSS/命令注入/路径遍历检测 |

### 3.2 中间件

| 模块 | 文件 | 功能 |
|------|------|------|
| 链路追踪 | `core/middleware/tracing.py` | 请求链路追踪中间件 |
| 安全响应头 | `core/middleware/security_headers.py` | HTTP 安全响应头设置 |
| CORS 工具 | `core/cors_utils.py` | 跨域请求安全配置 |

### 3.3 可观测性

| 模块 | 文件 | 功能 |
|------|------|------|
| 统一日志 | `core/observability/unified_logger.py` | 结构化日志增强 |
| 链路追踪 | `core/observability/tracing.py` | 分布式追踪 |
| 指标采集 | `core/observability/metrics.py` | Prometheus 指标 |
| FastAPI 中间件 | `core/observability/fastapi_middleware.py` | FastAPI 可观测中间件 |

### 3.4 使用示例

```python
# 全局配置
from shared.core.config import get_config

config = get_config()
port = config.get_module_port("m8")

# 统一日志
from shared.core.logger import get_logger

logger = get_logger("m8.backend")
logger.info("服务启动成功")

# 统一错误处理
from shared.core.errors import ValidationError, NotFoundError
from shared.core.responses import ok, fail, ApiResponse

# 成功响应
return ok(data={"user": user}, message="获取成功")

# 抛出业务异常（由全局异常处理器统一处理）
raise NotFoundError(message="用户不存在")

# 鉴权工具
from shared.core.auth import (
    generate_api_key,
    verify_api_key,
    SimpleRateLimiter,
)

key = generate_api_key(prefix="yx_", length=32)
limiter = SimpleRateLimiter(default_limit=60, window_seconds=60)

# 安全工具
from shared.core.security import (
    xss_filter,
    safe_join_path,
    validate_file_upload,
    check_password_strength,
    mask_sensitive_data,
)
```

---

## 四、data 层 — 数据基础设施

data 层提供数据存储、缓存、治理等基础设施能力。

### 4.1 缓存模块

| 模块 | 目录 | 功能 |
|------|------|------|
| TTL+LRU 缓存 | `data/cache/` | 内存缓存，支持 TTL 过期和 LRU 淘汰 |

### 4.2 数据层

| 模块 | 目录 | 功能 |
|------|------|------|
| 数据库管理 | `data/data_layer/` | 数据库管理器、备份管理器、数据迁移 |
| 数据迁移工具 | `data/data_layer/migration.py` | Schema 迁移、版本管理 |
| 备份管理器 | `data/data_layer/backup_manager.py` | 数据备份与恢复 |

### 4.3 数据治理

| 模块 | 目录 | 功能 |
|------|------|------|
| 数据主权 | `data/data_governance/sovereignty.py` | 数据主权管理 |
| 去重计划 | `data/data_governance/deduplication_plans.py` | 数据去重策略 |

### 4.4 使用示例

```python
# 缓存使用
from shared.data.cache import TTLCache

cache = TTLCache(maxsize=1000, ttl=3600)
cache.set("key", "value")
value = cache.get("key")

# 数据备份
from shared.data.data_layer.backup_manager import BackupManager

bm = BackupManager(backup_dir="./backups")
bm.backup_database("m8", "./data/m8.db")
bm.restore_database("m8", "./backups/m8_latest/")
```

---

## 五、business 层 — 业务能力

business 层包含通用业务能力模块，处于过渡期，后续会逐步拆分为各模块的独立实现。

### 5.1 Agent 与智能

| 模块 | 文件 | 功能 |
|------|------|------|
| Agent 引擎 | `business/agent_engine.py` | 基础 Agent 框架 |
| 多 Agent | `business/multi_agent.py` | 多 Agent 协作 |
| Agent 团队 | `business/agent_team.py` | Agent 团队管理 |
| 推理引擎 | `business/reasoning_engine.py` | 推理与路由 |
| 模型路由 | `business/model_router.py` | 多模型智能路由 |

### 5.2 LLM 与工具

| 模块 | 文件 | 功能 |
|------|------|------|
| LLM 客户端 | `business/llm_client.py` | 多后端切换（DeepSeek/OpenAI/Ollama） |
| 工具系统 | `business/tool_system.py` | 工具注册与调用 |
| 内置工具 | `business/builtin_tools.py` | 内置工具集合 |
| A2A 客户端 | `business/a2a_client.py` | Agent-to-Agent 协议客户端 |

### 5.3 记忆与知识

| 模块 | 文件 | 功能 |
|------|------|------|
| 长期记忆 | `business/long_term_memory.py` | 长期记忆管理 |
| RAG 知识 | `business/rag_knowledge.py` | 检索增强生成 |
| 用户画像 | `business/user_profile.py` | 用户画像管理 |
| 上下文感知 | `business/context_aware.py` | 上下文管理 |

### 5.4 语音与交互

| 模块 | 文件 | 功能 |
|------|------|------|
| 语音引擎 | `business/voice_engine.py` | 语音合成与识别 |
| CosyVoice 客户端 | `business/cosyvoice_client.py` | CosyVoice TTS |
| 音色预设管理 | `business/voice_preset_manager.py` | 音色管理 |
| 韵律控制 | `business/prosody_controller.py` | 语音韵律调节 |
| 提醒语音 | `business/reminder_voice.py` | 语音提醒 |

### 5.5 系统管理

| 模块 | 文件 | 功能 |
|------|------|------|
| 模块调用客户端 | `business/module_client.py` | 模块间 HTTP 调用 |
| 进程管理器 | `business/process_manager.py` | 模块进程启动/停止/重启 |
| 启动编排器 | `business/startup_orchestrator.py` | 模块启动顺序编排 |

### 5.6 分布式

| 模块 | 目录 | 功能 |
|------|------|------|
| 节点配置 | `business/distributed/node_config.py` | 节点配置管理 |
| 节点注册 | `business/distributed/node_registry.py` | 节点注册发现 |
| 集群总线 | `business/distributed/cluster_bus.py` | 跨节点消息总线 |
| 分布式 API | `business/distributed/api.py` | 分布式接口 |

### 5.7 人格与进化

| 模块 | 文件 | 功能 |
|------|------|------|
| 人格引擎 | `business/personality_engine.py` | AI 人格系统 |
| 自主学习 | `business/autonomous_learning.py` | 自主学习能力 |
| 技能进化 | `business/skill_evolution.py` | 技能自动进化 |
| 角色系统 | `business/roles.py` | 角色与权限 |
| 多模态 | `business/multimodal.py` | 多模态处理 |

---

## 六、配置文件

全局配置文件路径：`config/yunxi.env`

包含以下配置块：

- 全局基础配置
- M0-M12 各模块配置（端口/Host/Token/BaseURL）
- 大模型配置（DeepSeek/OpenAI/Ollama）
- 安全配置（JWT密钥、CORS、超时、重试）
- 模块间调用配置

详细说明参见：[core/CONFIG_GUIDE.md](core/CONFIG_GUIDE.md)

---

## 七、使用说明

### 7.1 路径约定

所有模块的项目根目录为 `yunxi-project/`，shared 模块位于 `shared/` 目录下。

### 7.2 导入方式

```python
import sys
from pathlib import Path

# 将项目根目录加入 path
project_root = Path(__file__).parent.parent  # 根据实际层级调整
sys.path.insert(0, str(project_root))

# 导入 shared 组件（推荐使用三层路径）
from shared.core.config import get_config
from shared.core.logger import get_logger
from shared.core.errors import ValidationError

# 旧路径仍然可用（会有 DeprecationWarning）
from shared.config import get_config  # 兼容旧代码
```

---

## 八、版本变更

详细变更记录参见 [CHANGELOG.md](CHANGELOG.md)

### v1.0.0 (2026-07-17)

- 三层架构目录结构：`core/`、`data/`、`business/`
- 各层 `__init__.py` 统一 re-export
- 旧路径向后兼容（DeprecationWarning）

---

## 相关文档

- [错误码规范](core/ERROR_CODES.md) — 统一错误码体系
- [配置指南](core/CONFIG_GUIDE.md) — 全局配置说明
- [健康检查指南](core/HEALTH_GUIDE.md) — M8 标准健康检查接口
- [数据迁移指南](data/MIGRATION_GUIDE.md) — 数据库迁移
- [备份指南](data/BACKUP_GUIDE.md) — 数据备份与恢复
- [性能指南](data/PERFORMANCE_GUIDE.md) — 性能调优
- [数据治理](data/data_governance/README.md) — 数据治理说明

---

**最后更新**：2026-07-17
**版本**：v1.0.0
