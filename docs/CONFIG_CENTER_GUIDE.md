# M8 配置中心使用指南

## 一、架构说明

### 1.1 整体架构

云汐系统配置中心采用「服务端 + 客户端 SDK」的两层架构：

```
┌─────────────────────────────────────────────────────────────┐
│                      M8 Config Center                        │
│  (M8-control-tower/backend/services/config_center.py)        │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │  CRUD 服务  │  │ 版本管理   │  │ 审计日志   │             │
│  └────────────┘  └────────────┘  └────────────┘             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │ 灰度发布   │  │ Schema校验 │  │ 导入导出   │             │
│  └────────────┘  └────────────┘  └────────────┘             │
│                                                              │
│  SQLite / PostgreSQL  ──  4 张核心表                         │
│  config_items / config_versions / config_audit / schemas    │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   ConfigClient SDK                           │
│              (shared/config_sdk/client.py)                   │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │ 内存缓存   │  │ 文件缓存   │  │ 长轮询监听 │             │
│  └────────────┘  └────────────┘  └────────────┘             │
│  ┌────────────┐  ┌────────────┐                             │
│  │ 变更回调   │  │ 故障降级   │                             │
│  └────────────┘  └────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 四层配置模型

配置采用「全局 → 模块 → 环境 → 实例」的四层分层模型：

```
全局配置 (global)
  └─ 模块配置 (module: M1/M2/M8...)
       └─ 环境配置 (env: dev/test/prod)
            └─ 实例配置 (instance: 特定实例ID)
```

**优先级规则**：实例 > 环境 > 模块 > 全局

获取配置时，从高优先级到低优先级依次查找，找到第一个匹配项即返回。

### 1.3 各层使用场景

| 层级 | 作用域 | 使用场景 | 示例 |
|------|--------|----------|------|
| global | 全局 | 全系统通用配置 | 系统版本、全局日志级别 |
| module | 模块 | 模块级默认配置 | M8 数据库连接池大小 |
| env | 环境 | 不同环境差异化配置 | 生产环境 JWT 密钥、开发环境调试开关 |
| instance | 实例 | 单实例特殊配置 | 特定节点的硬件参数、灰度发布 |

---

## 二、配置命名规范

### 2.1 命名格式

配置键采用 **小写字母 + 下划线 + 点分层** 的格式：

```
<域>.<子域>.<具体配置项>
```

### 2.2 命名示例

```
# 数据库相关
database.host
database.port
database.username
database.password

# LLM 相关
llm.provider
llm.model_name
llm.temperature
llm.max_tokens

# 日志相关
log.level
log.format
log.file_path

# 功能开关
feature.rag.enabled
feature.voice.enabled
feature.memory.enabled
```

### 2.3 命名约定

1. **全小写**：所有配置键使用小写字母
2. **下划线分词**：多个单词用下划线分隔
3. **点分层**：不同层级用点号分隔，从大到小
4. **动词后置**：`_enabled`、`_timeout`、`_path` 等后缀
5. **布尔配置用 is/has/enabled**：`feature.enabled`、`debug_mode`
6. **敏感配置加 secret 标记**：通过 `is_secret=True` 标记加密存储

---

## 三、SDK 使用指南

### 3.1 基本用法

```python
from shared.config_sdk import ConfigClient

# 创建客户端
client = ConfigClient(
    module_name="m8",
    config={
        "config_center_url": "http://localhost:8008/api/config",
        "env": "development",
        "auth_token": "your-token",
    },
    local_config={
        # 本地默认配置（兜底）
        "database.host": "localhost",
        "database.port": 5432,
    }
)

# 获取配置
host = client.get("database.host", default="localhost")
port = client.get("database.port", default=5432)

# 获取所有配置
all_configs = client.get_all()

# 获取指定前缀的配置
db_configs = client.get_all(prefix="database.")
```

### 3.2 配置监听

```python
# 监听单个配置变化
def on_db_host_change(key, old_val, new_val):
    print(f"数据库地址变更: {old_val} -> {new_val}")
    # 重新连接数据库...

listener_id = client.watch("database.host", on_db_host_change)

# 取消监听
client.unwatch(listener_id)
```

### 3.3 手动刷新

```python
# 强制刷新配置（绕过缓存）
success = client.refresh()
if success:
    print("配置已更新")
else:
    print("刷新失败，使用缓存")
```

### 3.4 本地合并器

```python
from shared.config_sdk import LocalConfigMerger

merger = LocalConfigMerger(
    local_config_path="config/config.yaml",
    override_path="config/override.yaml",
    env_prefix="M8_",
    defaults={"log_level": "info"},
)

# 合并远程配置
merged = merger.merge_layered(
    global_configs=global_configs,
    module_configs=module_configs,
    env_configs=env_configs,
    instance_configs=instance_configs,
)
```

### 3.5 故障降级

配置中心不可用时，SDK 自动降级：

1. **内存缓存**：优先使用内存中的配置
2. **文件缓存**：内存缓存失效时从文件缓存加载
3. **本地配置**：文件缓存也没有时使用本地默认配置
4. **自动重连**：长轮询失败后自动重试

---

## 四、服务端 API 清单

### 4.1 配置 CRUD

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/config/items` | 配置列表（支持过滤、分页） |
| GET | `/config/items/{key}` | 获取单个配置 |
| POST | `/config/items` | 新增配置 |
| PUT | `/config/items/{key}` | 更新配置 |
| DELETE | `/config/items/{key}` | 删除配置 |

### 4.2 批量操作

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/config/batch/get` | 批量获取配置 |
| POST | `/config/batch/set` | 批量设置配置 |

### 4.3 版本管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/config/versions` | 配置版本历史 |
| POST | `/config/rollback` | 配置回滚 |
| GET | `/config/versions/diff` | 版本对比 |

### 4.4 审计日志

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/config/audit` | 审计日志查询（支持过滤） |

### 4.5 Schema 管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/config/schemas` | Schema 列表 |
| POST | `/config/schemas` | 新增 Schema |

### 4.6 灰度发布

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/config/canary/start` | 启动灰度发布 |
| POST | `/config/canary/rollback` | 灰度回滚 |
| POST | `/config/canary/promote` | 灰度转正 |

### 4.7 导入导出

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/config/export` | 导出配置 |
| POST | `/config/import` | 导入配置 |

### 4.8 其他

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/config/health` | 配置中心健康检查 |
| GET | `/config/watch` | 长轮询监听变更 |

---

## 五、最佳实践

### 5.1 配置分层建议

1. **全局配置**：只放真正全系统通用的配置
2. **模块配置**：模块的默认配置，尽量全面
3. **环境配置**：仅放环境差异的配置（密钥、地址等）
4. **实例配置**：尽量少用，仅用于特殊场景

### 5.2 敏感配置

1. 所有密钥、密码、Token 必须标记 `is_secret=True`
2. 敏感配置在数据库中加密存储
3. API 返回时自动脱敏（显示为 `***SECRET***`）
4. 生产环境禁止在代码中硬编码敏感配置

### 5.3 配置变更流程

1. **开发环境**：直接修改，快速迭代
2. **测试环境**：通过配置中心管理，记录变更原因
3. **生产环境**：
   - 先在测试环境验证
   - 使用灰度发布逐步放量
   - 确认无误后全量发布
   - 保留审计记录和版本历史

### 5.4 灰度发布最佳实践

1. 先按 10% 比例灰度
2. 观察 10-30 分钟无异常再扩大
3. 异常时立即回滚（rollback_canary）
4. 全量发布使用 promote_canary

### 5.5 客户端使用建议

1. **启动时加载**：应用启动时创建 ConfigClient 并加载配置
2. **监听关键配置**：对影响运行时行为的配置注册 watcher
3. **设置合理 TTL**：缓存 TTL 根据配置敏感度调整
4. **本地兜底**：始终提供本地默认配置，确保断网可用

---

## 六、向后兼容

### 6.1 增量功能

配置中心是**纯增量功能**，不改变现有配置方式：

- 各模块原有的 `config.py` + pydantic-settings 方式不变
- 环境变量和 `.env` 文件继续有效
- 默认使用本地配置，可通过配置启用远程配置中心

### 6.2 启用方式

```python
# 方式一：仅使用本地配置（默认，向后兼容）
config = MyModuleConfig()

# 方式二：启用远程配置中心
from shared.config_sdk import ConfigClient

client = ConfigClient(
    module_name="m8",
    config={"enable_remote": True, ...},
    local_config=config.model_dump(),  # 本地配置作为兜底
)
```

### 6.3 迁移路径

1. 保持现有配置方式不变
2. 逐步将需要动态调整的配置迁移到配置中心
3. 通过 SDK 获取远程配置，本地配置作为 fallback
4. 完全迁移后可考虑移除本地硬编码配置

---

## 七、常见问题

### Q1: 配置中心不可用会不会影响服务启动？

不会。SDK 有完善的降级机制，配置中心不可用时使用本地缓存和默认配置。

### Q2: 配置变更后多久生效？

- 主动刷新：立即生效
- 长轮询监听：通常在 30 秒内（可配置）
- 缓存 TTL：默认 60 秒后自动刷新

### Q3: 多实例部署如何保证配置一致？

所有实例从同一个配置中心读取配置，配置中心是唯一数据源。

### Q4: 如何批量修改配置？

使用 `POST /config/batch/set` 接口，或通过导入导出功能。

### Q5: 配置修改后如何回滚？

通过版本历史找到目标版本，使用回滚接口恢复到指定版本。
所有变更都有审计记录，可追溯。

### Q6: 敏感配置安全吗？

敏感配置在数据库中使用 Fernet（AES-128-CBC + HMAC）加密存储，
API 返回时自动脱敏，只有有权限的调用者才能获取明文值。
