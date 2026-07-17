# 云汐系统统一配置指南

> 版本：v2.0.0
> 更新日期：2026-07-17

## 目录

1. [概述](#概述)
2. [统一配置基类 BaseConfig](#统一配置基类-baseconfig)
3. [全局配置 YunxiGlobalConfig](#全局配置-yunxiglobalconfig)
4. [环境变量规范](#环境变量规范)
5. [配置加载优先级](#配置加载优先级)
6. [生产环境校验](#生产环境校验)
7. [敏感字段脱敏](#敏感字段脱敏)
8. [配置热更新](#配置热更新)
9. [各模块配置详情](#各模块配置详情)
10. [向后兼容](#向后兼容)
11. [迁移指南](#迁移指南)

---

## 概述

云汐系统使用基于 `pydantic-settings` 的统一配置框架，所有模块的配置类均继承自 `BaseConfig` 基类，实现配置管理的标准化。

### 核心特性

- **多源配置加载**：支持环境变量、.env 文件、YAML 配置文件
- **类型安全**：基于 Pydantic 的强类型校验
- **生产环境校验**：敏感字段在生产环境强制配置，禁止使用默认值
- **敏感字段脱敏**：输出时自动脱敏密钥、令牌等敏感信息
- **配置热更新**：运行时重新加载配置并触发回调
- **向后兼容**：旧环境变量名通过 alias 机制保持可用

---

## 统一配置基类 BaseConfig

所有模块配置类的基类，继承自 `pydantic_settings.BaseSettings`。

### 导入方式

```python
from shared.core.config import BaseConfig, EnvType
from pydantic_settings import SettingsConfigDict
from pydantic import Field
```

### 内置字段

| 字段名 | 类型 | 默认值 | 环境变量 | 说明 |
|--------|------|--------|----------|------|
| `module_name` | `str` | `"unknown"` | `{PREFIX}MODULE_NAME` | 模块名称 |
| `env` | `EnvType` | `EnvType.DEVELOPMENT` | `{PREFIX}ENV` | 运行环境 |
| `log_level` | `str` | `"info"` | `{PREFIX}LOG_LEVEL` | 日志级别 |
| `host` | `str` | `"0.0.0.0"` | `{PREFIX}HOST` | 服务监听地址 |
| `port` | `int` | `8000` | `{PREFIX}PORT` | 服务监听端口 |
| `cors_origins` | `str` | `"*"` | `{PREFIX}CORS_ORIGINS` | CORS 允许来源 |
| `admin_token` | `str` | `""` | `{PREFIX}ADMIN_TOKEN` | 管理员令牌（敏感） |

### 环境类型 EnvType

| 值 | 说明 |
|----|------|
| `development` | 开发环境 |
| `staging` | 预发布环境 |
| `production` | 生产环境 |
| `testing` | 测试环境 |

### 使用示例

```python
class MyModuleConfig(BaseConfig):
    # 自定义字段
    database_url: str = Field(default="sqlite:///./app.db", description="数据库连接URL")
    max_connections: int = Field(default=100, ge=1, description="最大连接数")
    api_key: str = Field(default="", description="API密钥（敏感字段）")

    model_config = SettingsConfigDict(
        env_prefix="MY_MODULE_",  # 环境变量前缀
        env_file=".env",          # .env 文件路径
        extra="allow",            # 允许额外字段
    )
```

---

## 全局配置 YunxiGlobalConfig

集中管理所有模块的端点配置和全局安全配置。

### 获取全局配置

```python
from shared.core.config import get_global_config, YunxiGlobalConfig

config = get_global_config()  # 单例模式
```

### 全局安全配置 (security)

| 字段名 | 类型 | 默认值 | 环境变量 | 说明 |
|--------|------|--------|----------|------|
| `jwt_secret` | `str` | `"yunxi-jwt-secret-key-2026"` | `YUNXI_JWT_SECRET` | JWT 签名密钥（敏感） |
| `jwt_algorithm` | `str` | `"HS256"` | `YUNXI_JWT_ALGORITHM` | JWT 签名算法 |
| `access_token_expire_minutes` | `int` | `1440` | `YUNXI_ACCESS_TOKEN_EXPIRE_MINUTES` | 令牌有效期（分钟） |
| `cors_origins` | `str` | `"*"` | `YUNXI_CORS_ORIGINS` | 全局 CORS 来源 |

### 模块端点配置 (modules)

每个模块包含以下字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `host` | `str` | 监听地址 |
| `port` | `int` | 监听端口 |
| `token` | `str` | 管理令牌（敏感） |
| `base_url` | `str` | Base URL |
| `python_executable` | `str` | Python 可执行文件路径 |
| `health_check_path` | `str` | 健康检查路径 |
| `enabled` | `bool` | 是否启用 |

### 模块端口分配

| 模块 | Key | 默认端口 | 环境变量 |
|------|-----|----------|----------|
| API 网关 | `gateway` | 8080 | `GATEWAY_PORT` |
| M0 主控台 | `m0` | 8000 | `M0_PORT` |
| M1 多Agent集群 | `m1` | 8001 | `M1_PORT` |
| M2 技能集群 | `m2` | 8002 | `M2_PORT` |
| M3 端云协同 | `m3` | 8003 | `M3_PORT` |
| M4 场景引擎 | `m4` | 8004 | `M4_PORT` |
| M5 潮汐记忆 | `m5` | 8005 | `M5_PORT` |
| M6 硬件外设 | `m6` | 8006 | `M6_PORT` |
| M7 工作流编排 | `m7` | 8007 | `M7_PORT` |
| M8 控制塔 | `m8` | 8008 | `M8_PORT` |
| M9 开发者工坊 | `m9` | 8009 | `M9_PORT` |
| M10 系统卫士 | `m10` | 8010 | `M10_PORT` |
| M11 MCP总线 | `m11` | 8011 | `M11_PORT` |
| M12 安全盾 | `m12` | 8012 | `M12_PORT` |

### 便捷方法

```python
# 获取指定模块的端口
config.get_module_port("m5")  # 8005

# 获取指定模块的 Base URL
config.get_module_base_url("m6")  # "http://localhost:8006"

# 获取指定模块的管理令牌
config.get_module_token("m9")  # "yunxi-m9-admin-token-2026"

# 获取所有模块 key
config.get_all_module_keys()  # ["gateway", "m0", "m1", ...]
```

---

## 环境变量规范

### 命名规则

- 全局配置：`YUNXI_` 前缀
- 模块配置：`{MODULE_CODE}_` 前缀（如 `M5_`、`M10_`、`GATEWAY_`）
- 旧环境变量名通过 alias 机制保持兼容
- 全部使用大写字母和下划线

### .env 文件

系统会自动从以下位置加载 `.env` 文件：

1. 项目根目录 `config/yunxi.env`（全局）
2. 模块目录下的 `.env`（模块私有）
3. 当前工作目录的 `.env`

### YAML 配置文件

支持从 YAML 文件加载配置，默认查找路径：

1. `config/yunxi.yaml`（项目根目录）
2. `config/yunxi.yml`
3. `config.yaml`（当前工作目录）
4. `config.yml`

YAML 文件格式示例：

```yaml
env: production
log_level: info
cors_origins: "https://yunxi.example.com"

m5:
  port: 8005
  database_url: "postgresql://user:pass@localhost/m5"

m6:
  simulation_mode: false
  collection_interval: 2
```

---

## 配置加载优先级

从高到低：

1. **初始化参数**（代码中显式传入）
2. **环境变量**（优先级最高的外部配置）
3. **.env 文件**（项目级/模块级）
4. **YAML 配置文件**
5. **默认值**（代码中定义的字段默认值）

---

## 生产环境校验

当 `env` 设置为 `production` 时，系统会自动进行安全校验：

### 校验规则

1. **敏感字段不得为空**：所有包含 `token`、`secret`、`password`、`api_key` 等关键词的字段
2. **不得使用默认占位值**：以 `yunxi-` 开头且包含 `default` 的值会被拒绝
3. **校验失败抛出异常**：启动时立即失败，避免使用不安全的默认配置

### 示例

```python
# 生产环境下，如果 admin_token 为空或使用默认值，会抛出 ValueError
config = MyModuleConfig(env="production", admin_token="")
# ValueError: 生产环境必须配置 'admin_token'，禁止使用空默认值。
```

### 敏感字段关键词

系统自动识别以下关键词的字段为敏感字段：

`token`, `secret`, `password`, `api_key`, `apikey`, `encryption_key`, `private_key`, `access_key`, `admin_token`, `jwt_secret`, `db_password`, `redis_password`, `mongo_password`

---

## 敏感字段脱敏

所有配置对象在输出（`to_dict()`、`__repr__`）时会自动脱敏敏感字段。

### 使用方式

```python
config = MyModuleConfig(admin_token="secret123", api_key="key-abc")

# 脱敏输出（默认）
data = config.to_dict()  # {"admin_token": "***MASKED***", "api_key": "***MASKED***"}

# 不脱敏（谨慎使用）
raw_data = config.to_dict(sanitize=False)  # {"admin_token": "secret123", ...}

# repr 也会脱敏
print(config)  # <MyModuleConfig env=development port=8000>
```

---

## 配置热更新

支持运行时重新加载配置，并通过钩子函数通知变更。

### 重新加载配置

```python
changes = config.reload()
# changes = {
#   "port": {"old": 8000, "new": 8001},
#   "log_level": {"old": "info", "new": "debug"}
# }
```

### 注册热更新钩子

```python
def on_config_change(new_config: BaseConfig):
    print(f"配置已变更，新端口: {new_config.port}")

config.register_hot_reload_hook(on_config_change)
```

---

## 各模块配置详情

### M5 潮汐记忆 (M5-tide-memory)

**配置类**：`M5ModuleConfig` / `TideConfig` / `TideConfigSchema`

**环境变量前缀**：`M5_`

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 端口 | `M5_PORT` | 8005 | 服务监听端口 |
| 环境 | `M5_ENV` | development | 运行环境 |
| 日志级别 | `M5_LOG_LEVEL` | info | 日志级别 |
| 加密密钥 | `M5_ENCRYPTION_KEY` | - | 主加密密钥（敏感） |
| 管理员令牌 | `M5_ADMIN_TOKEN` | - | 管理员令牌（敏感） |
| JWT 密钥 | `M5_JWT_SECRET` | - | JWT 签名密钥（敏感） |
| 嵌入 API Key | `M5_EMBEDDING_API_KEY` | - | 向量嵌入 API 密钥（敏感） |
| 嵌入 Base URL | `M5_EMBEDDING_BASE_URL` | - | 向量嵌入 API 基础 URL |
| 向量后端 | `M5_VECTOR_BACKEND` | chroma | 向量数据库类型 |
| 存储路径 | `M5_STORAGE_PATH` | ./data/memory | 本地存储路径 |
| 审计启用 | `M5_AUDIT_ENABLED` | true | 是否启用审计日志 |
| 审计日志路径 | `M5_AUDIT_LOG_PATH` | ./logs/m5-audit.log | 审计日志文件路径 |

**新接口使用方式**：
```python
from tide_memory.core.config import get_m5_config, M5ModuleConfig

config = get_m5_config()
schema = config.schema  # 详细配置 schema
```

### M6 硬件外设 (M6-hardware-peripheral)

**配置类**：`M6ModuleConfig` / `M6Config`

**环境变量前缀**：`M6_`

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 模块名 | `M6_NAME` | m6-hardware | 模块名称 |
| 地址 | `M6_HOST` | 0.0.0.0 | 监听地址 |
| 端口 | `M6_PORT` | 8006 | 监听端口 |
| 环境 | `M6_ENV` | development | 运行环境 |
| 管理员令牌 | `M6_ADMIN_TOKEN` | - | 管理令牌（敏感，生产必填） |
| 模拟模式 | `M6_SIMULATION_MODE` | true | 是否使用模拟数据 |
| 数据库路径 | `M6_DATABASE_PATH` | data/m6_sensors.db | SQLite 数据库路径 |
| 采集间隔 | `M6_COLLECTION_INTERVAL` | 5 | 数据采集间隔（秒） |
| 数据保留天数 | `M6_DATA_RETENTION_DAYS` | 30 | 数据保留天数 |
| SSE 令牌有效期 | `M6_SSE_TOKEN_TTL` | 300 | SSE 令牌有效期（秒） |
| SSE 最大连接数 | `M6_SSE_MAX_CONNECTIONS` | 100 | SSE 最大连接数 |
| SSE 推送间隔 | `M6_SSE_INTERVAL` | 5 | SSE 推送间隔（秒） |
| SSE 心跳间隔 | `M6_SSE_HEARTBEAT_INTERVAL` | 30 | SSE 心跳间隔（秒） |
| 低电量阈值 | `M6_BATTERY_LOW_THRESHOLD` | 20 | 低电量告警阈值（%） |
| 基础耗电速率 | `M6_BATTERY_DRAIN_BASE` | 0.1 | 基础电量消耗速率 |
| 默认设备路径 | `M6_DEFAULT_DEVICES_PATH` | "" | 默认设备配置文件路径 |

**新接口使用方式**：
```python
from m6_hardware.config import get_m6_config, M6ModuleConfig

config = get_m6_config()
print(config.simulation_mode)  # True/False
```

### M9 开发者工坊 (M9-dev-workshop)

**配置类**：`M9ModuleConfig` / `Settings`

**环境变量前缀**：`M9_`（新）/ `YUNXI_M9_`（旧，兼容）

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 端口 | `M9_PORT` | 8009 | 服务监听端口 |
| 工作区根目录 | `M9_WORKSPACE_ROOT` | ~/yunxi-workspace | 工作区根目录 |
| MCP 启用 | `M9_MCP_ENABLED` | true | MCP 服务是否启用 |
| MCP 端口 | `M9_MCP_PORT` | 8765 | MCP 服务端口 |
| 管理员令牌 | `M9_ADMIN_TOKEN` | "" | 管理员令牌（敏感） |
| 调试模式 | `M9_DEBUG` | true | 是否启用调试模式 |
| 代码执行超时 | `M9_CODE_EXEC_TIMEOUT` | 30 | 代码执行超时（秒） |
| 沙箱启用 | `M9_CODE_EXEC_SANDBOX` | true | 是否启用沙箱安全检测 |
| M8 API | `M9_M8_API` | http://localhost:8008/api | M8 控制塔 API 地址 |
| M5 API | `M5_API` | http://localhost:8005/api | M5 潮汐记忆 API 地址 |
| M4 API | `M4_API` | http://localhost:8004/api | M4 场景引擎 API 地址 |
| M8 巡检 API | `M8_INSPECTION_API` | http://localhost:8003/api | M8 巡检 API 地址 |

**新接口使用方式**：
```python
from backend.config import get_m9_config, M9ModuleConfig

config = get_m9_config()
print(config.workspace_root)
```

### M10 系统卫士 (M10-system-guard)

**配置类**：`M10ModuleConfig` / `M10Config`

**环境变量前缀**：`M10_`

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 端口 | `M10_PORT` | 8010 | 服务监听端口 |
| 地址 | `M10_HOST` | 0.0.0.0 | 监听地址 |
| 日志级别 | `M10_LOG_LEVEL` | info | 日志级别 |
| 环境 | `M10_ENV` | development | 运行环境 |
| 沙盒模式 | `M10_SANDBOX_ENABLED` | false | 是否启用沙盒模式 |
| CORS 来源 | `M10_CORS_ORIGINS` | (多地址) | CORS 允许来源 |

**子配置模块**：
- `basic` - 基础配置
- `sandbox` - 沙盒模式配置
- `guard_threshold` - 防护阈值配置（CPU/内存/温度/磁盘四级告警）
- `process` - 进程管理配置
- `startup_check` - 启动安全检查配置
- `sandbox_scheduler` - 沙箱任务调度配置
- `audit` - 审计日志配置
- `report` - 报告生成配置
- `data_aggregation` - 数据聚合配置

**新接口使用方式**：
```python
from m10_system_guard.config import get_m10_config, M10ModuleConfig

config = get_m10_config()
print(config.sandbox.enabled)  # 沙盒模式是否启用
print(config.guard_threshold.cpu_warning)  # CPU 告警阈值
```

### API 网关 (API-Gateway)

**配置类**：`GatewayModuleConfig` / `GatewaySettings`

**环境变量前缀**：`GATEWAY_`

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 地址 | `GATEWAY_HOST` | 0.0.0.0 | 监听地址 |
| 端口 | `GATEWAY_PORT` | 8080 | 监听端口 |
| 日志级别 | `GATEWAY_LOG_LEVEL` | info | 日志级别 |
| CORS 来源 | `GATEWAY_CORS_ORIGINS` | * | 允许的来源 |
| API Key 头 | `GATEWAY_API_KEY_HEADER` | X-API-Key | API Key 头字段名 |
| JWT 头 | `GATEWAY_JWT_HEADER` | Authorization | JWT 头字段名 |
| 全局限流 | `GATEWAY_RATE_LIMIT_TOTAL` | 600 | 全局每分钟限流次数 |
| 单 IP 限流 | `GATEWAY_RATE_LIMIT_PER_IP` | 100 | 每 IP 每分钟限流次数 |
| 熔断阈值 | `GATEWAY_CB_THRESHOLD` | 5 | 连续失败次数阈值 |
| 熔断恢复 | `GATEWAY_CB_RECOVERY` | 30 | 熔断恢复时间（秒） |

**新接口使用方式**：
```python
from src.config import get_gateway_config, GatewayModuleConfig

config = get_gateway_config()
routes = config.get_enabled_routes()  # 所有启用的路由
m5_route = config.get_route("m5")    # M5 模块路由配置
```

---

## 向后兼容

### 旧接口可用性

所有模块的旧配置类和函数均保留，现有代码无需修改即可继续运行。

| 模块 | 旧接口 | 状态 |
|------|--------|------|
| 全局配置 | `YunxiConfig` / `get_config()` | 保留，委托给新实现 |
| M5 | `TideConfig` / `TideConfigSchema` | 完全保留，无修改 |
| M6 | `M6Config` / `get_config()` | 保留，内部委托给新类 |
| M9 | `Settings` / `get_settings()` | 保留，内部委托给新类 |
| M10 | `M10Config` / `load_config()` / `get_config()` | 完全保留 |
| API Gateway | `GatewaySettings` / `settings` / `ModuleRoute` | 完全保留 |

### shared/config.py 兼容

`shared/config.py` 作为旧路径的兼容存根，从 `shared.core.config` 重新导出所有内容，并发出 `DeprecationWarning`。

### 降级模式

每个模块的配置模块都包含降级逻辑：当无法导入 `shared.core.config` 时，自动回退到本地实现，确保模块独立可用。

---

## 迁移指南

### 将自定义配置类迁移到统一框架

**步骤 1**：继承 BaseConfig

```python
# 旧代码
class MyConfig:
    def __init__(self):
        self.port = int(os.getenv("MY_PORT", "8000"))
        self.host = os.getenv("MY_HOST", "0.0.0.0")
```

```python
# 新代码
from shared.core.config import BaseConfig
from pydantic_settings import SettingsConfigDict
from pydantic import Field

class MyConfig(BaseConfig):
    port: int = Field(default=8000, ge=1, le=65535)
    host: str = "0.0.0.0"

    model_config = SettingsConfigDict(
        env_prefix="MY_",
        env_file=".env",
        extra="allow",
    )
```

**步骤 2**：保留旧接口（可选）

为了向后兼容，可以保留旧的配置类作为包装层：

```python
class OldConfigClass:
    def __init__(self):
        self._inner = MyConfig()

    def __getattr__(self, name):
        return getattr(self._inner, name)
```

**步骤 3**：验证生产环境校验

设置 `env=production` 并验证敏感字段是否正确配置：

```bash
# 测试生产环境校验
YUNXI_ENV=production python -c "from my_module.config import get_config; get_config()"
```

---

## 附录：文件结构

```
shared/
├── core/
│   ├── config.py           # 统一配置基类 + 全局配置（核心文件）
│   └── CONFIG_GUIDE.md     # 本文档
└── config.py               # 旧路径兼容存根（re-export）

各模块配置：
├── M5-tide-memory/src/tide_memory/core/
│   ├── config.py           # 新增 M5ModuleConfig + 旧 TideConfig
│   └── config_schema.py    # TideConfigSchema（不变）
├── M6-hardware-peripheral/m6_hardware/
│   └── config.py           # 新增 M6ModuleConfig + 旧 M6Config
├── M9-dev-workshop/backend/
│   └── config.py           # 新增 M9ModuleConfig + 旧 Settings
├── M10-system-guard/m10_system_guard/
│   └── config.py           # 新增 M10ModuleConfig + 旧 M10Config
└── API-Gateway/src/
    └── config.py           # 新增 GatewayModuleConfig + 旧 GatewaySettings
```
