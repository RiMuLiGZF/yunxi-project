# 云汐系统配置参考手册

> **文档版本**：v1.0
> **更新日期**：2026-07-18
> **适用范围**：云汐系统全模块配置
> **对应问题**：DOC-002（配置项缺少统一参考手册）

---

## 目录

- [1. 配置总览](#1-配置总览)
- [2. 全局基础配置](#2-全局基础配置)
- [3. 安全配置](#3-安全配置)
- [4. API 网关配置](#4-api-网关配置)
- [5. M8 控制塔配置](#5-m8-控制塔配置)
- [6. 各模块通用配置](#6-各模块通用配置)
- [7. 大模型配置](#7-大模型配置)
- [8. WAF 安全防护配置](#8-waf-安全防护配置)
- [9. 备份调度配置](#9-备份调度配置)
- [10. 数据库配置](#10-数据库配置)
- [11. 快速配置指南（最小必要配置）](#11-快速配置指南最小必要配置)
- [12. 生产环境检查清单](#12-生产环境检查清单)
- [13. 配置加载优先级](#13-配置加载优先级)

---

## 1. 配置总览

### 1.1 配置分类

| 分类 | 配置文件位置 | 环境变量前缀 | 说明 |
|------|------------|-------------|------|
| 全局基础配置 | `shared/core/config.py` | `YUNXI_` | 系统级基础配置，所有模块共用 |
| 安全配置 | `shared/core/config.py` | `YUNXI_SECURITY_` | JWT、CORS、WAF 等安全相关配置 |
| 网关配置 | `API-Gateway/src/config.py` | `GATEWAY_` | API 网关专属配置 |
| M8 配置 | `M8-control-tower/backend/config.py` | `M8_` | M8 管理控制塔专属配置 |
| 模块配置 | 各模块 `config.py` | `M{1..12}_` | 各业务模块独立配置 |
| 环境变量示例 | `config/.env.example` | - | 所有环境变量的参考模板 |

### 1.2 配置文件层次

```
config/yunxi.env          # 全局环境变量（主配置文件，不提交到 Git）
config/.env.example       # 环境变量模板（提交到 Git，作为参考）
config/yunxi.yaml         # 可选：YAML 格式配置文件
各模块/.env               # 模块级覆盖（可选）
各模块/config.py          # 模块配置类定义
```

---

## 2. 全局基础配置

> 配置类：`YunxiGlobalConfig` / `BaseConfig`
> 环境变量前缀：`YUNXI_`
> 源码位置：`shared/core/config.py`

### 2.1 基础配置项

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `env` | `YUNXI_ENV` | `development` | string | 是 | 运行环境：`development` / `staging` / `production` / `testing` |
| `module_name` | `YUNXI_MODULE_NAME` | `unknown` | string | 否 | 模块名称 |
| `log_level` | `YUNXI_LOG_LEVEL` | `info` | string | 否 | 日志级别：`debug` / `info` / `warning` / `error` / `critical` |
| `host` | `YUNXI_HOST` | `0.0.0.0` | string | 否 | 服务监听地址 |
| `port` | `YUNXI_PORT` | `8000` | int | 否 | 服务监听端口（1-65535） |
| `version` | `YUNXI_VERSION` | `1.0.0` | string | 否 | 系统版本号 |

### 2.2 全局模块端点配置

> 配置类：`GlobalModuleConfig`
> 环境变量格式：`YUNXI_MODULES_{MODULE}_FIELD`

所有 13 个模块统一管理，每个模块包含以下字段：

| 配置项 | 环境变量格式 | 默认值 | 类型 | 必填 | 说明 |
|-------|------------|--------|------|------|------|
| `host` | `YUNXI_MODULES_M{X}_HOST` | `0.0.0.0` | string | 否 | 模块监听地址 |
| `port` | `YUNXI_MODULES_M{X}_PORT` | 8000 + 模块号 | int | 否 | 模块监听端口 |
| `token` | `YUNXI_MODULES_M{X}_TOKEN` | `""` | string | 生产环境必填 | 模块间调用认证令牌 |
| `base_url` | `YUNXI_MODULES_M{X}_BASE_URL` | `http://localhost:{port}` | string | 否 | 模块 Base URL |
| `python_executable` | `YUNXI_MODULES_M{X}_PYTHON_EXECUTABLE` | `python` | string | 否 | Python 可执行文件路径 |
| `health_check_path` | `YUNXI_MODULES_M{X}_HEALTH_CHECK_PATH` | `/health` | string | 否 | 健康检查路径 |
| `enabled` | `YUNXI_MODULES_M{X}_ENABLED` | `true` | bool | 否 | 模块是否启用 |

### 2.3 模块端口一览

| 模块 | 编号 | 默认端口 | 环境变量 |
|------|------|---------|---------|
| M0 主理人管控台 | 0 | 8000 | `M0_PORT` |
| M1 多Agent集群 | 1 | 8001 | `M1_PORT` |
| M2 技能集群 | 2 | 8002 | `M2_PORT` |
| M3 端云协同 | 3 | 8003 | `M3_PORT` |
| M4 场景引擎 | 4 | 8004 | `M4_PORT` |
| M5 潮汐记忆 | 5 | 8005 | `M5_PORT` |
| M6 硬件外设 | 6 | 8006 | `M6_PORT` |
| M7 积木平台 | 7 | 8007 | `M7_PORT` |
| M8 管理控制塔 | 8 | 8008 | `M8_PORT` |
| M9 开发者工坊 | 9 | 8009 | `M9_PORT` |
| M10 系统卫士 | 10 | 8010 | `M10_PORT` |
| M11 MCP总线 | 11 | 8011 | `M11_PORT` |
| M12 安全盾 | 12 | 8012 | `M12_PORT` |
| API 网关 | GW | 8080 | `GATEWAY_PORT` |

---

## 3. 安全配置

> 配置类：`GlobalSecurityConfig`
> 环境变量前缀：`YUNXI_SECURITY_`
> 源码位置：`shared/core/config.py`

### 3.1 JWT 配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `jwt_secret` | `YUNXI_SECURITY_JWT_SECRET` | `""` | string | 生产环境必填 | JWT 签名密钥（HS256 使用，至少 32 字符） |
| `jwt_algorithm` | `YUNXI_SECURITY_JWT_ALGORITHM` | `RS256` | string | 否 | JWT 签名算法：`HS256` / `RS256` / `RS384` / `RS512` |
| `access_token_expire_minutes` | `YUNXI_SECURITY_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | int | 否 | 访问令牌有效期（分钟），默认 24 小时 |
| `jwt_private_key_path` | `YUNXI_SECURITY_JWT_PRIVATE_KEY_PATH` | `config/keys/jwt_private.pem` | string | 否 | JWT RSA 私钥文件路径 |
| `jwt_public_key_path` | `YUNXI_SECURITY_JWT_PUBLIC_KEY_PATH` | `config/keys/jwt_public.pem` | string | 否 | JWT RSA 公钥文件路径 |
| `jwt_key_size` | `YUNXI_SECURITY_JWT_KEY_SIZE` | `2048` | int | 否 | RSA 密钥位数：`2048` / `4096` |
| `jwt_auto_generate_keys` | `YUNXI_SECURITY_JWT_AUTO_GENERATE_KEYS` | `true` | bool | 否 | 首次启动是否自动生成 RSA 密钥对 |
| `jwt_key_rotation_days` | `YUNXI_SECURITY_JWT_KEY_ROTATION_DAYS` | `0` | int | 否 | 密钥轮换周期（天），0 表示不自动轮换 |
| `jwt_old_key_retention_days` | `YUNXI_SECURITY_JWT_OLD_KEY_RETENTION_DAYS` | `30` | int | 否 | 旧密钥保留天数 |

### 3.2 CORS 配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `cors_origins` | `YUNXI_SECURITY_CORS_ORIGINS` / `CORS_ORIGINS` | `*` | string | 生产环境必填 | CORS 允许的来源（逗号分隔）。生产环境禁止使用 `*` |

### 3.3 WAF 配置（全局默认）

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `waf_enabled` | `YUNXI_SECURITY_WAF_ENABLED` / `WAF_ENABLED` | `true` | bool | 生产环境必填 | 是否启用 WAF Web 应用防火墙 |
| `waf_mode` | `YUNXI_SECURITY_WAF_MODE` / `WAF_MODE` | `block` | string | 生产环境必填 | WAF 工作模式：`monitor` / `block`。生产环境必须为 `block` |

### 3.4 密钥最小长度要求

| 密钥类型 | 最小长度（字符） | 推荐长度（字符） |
|---------|----------------|----------------|
| JWT Secret | 32 | 64 |
| Encryption Key | 32 | 32（AES-256 精确要求） |
| Admin Token | 16 | 32 |
| API Key | 16 | 32 |
| Password | 8 | 12+（含大小写数字特殊字符） |
| Master Key | 32 | 64 |
| Internal Secret | 32 | 64 |

---

## 4. API 网关配置

> 配置类：`GatewayModuleConfig`
> 环境变量前缀：`GATEWAY_`
> 源码位置：`API-Gateway/src/config.py`

### 4.1 基础配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `module_name` | `GATEWAY_MODULE_NAME` | `api-gateway` | string | 否 | 模块名称 |
| `port` | `GATEWAY_PORT` | `8080` | int | 否 | 网关监听端口（1-65535） |
| `host` | `GATEWAY_HOST` | `0.0.0.0` | string | 否 | 网关监听地址 |
| `log_level` | `GATEWAY_LOG_LEVEL` | `info` | string | 否 | 日志级别 |

### 4.2 CORS 配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `cors_origins` | `GATEWAY_CORS_ORIGINS` | `*` | string | 生产环境必填 | 网关 CORS 来源（逗号分隔，优先级高于全局 CORS_ORIGINS） |

### 4.3 认证配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `api_key_header` | `GATEWAY_API_KEY_HEADER` | `X-API-Key` | string | 否 | API Key 头字段名 |
| `jwt_header` | `GATEWAY_JWT_HEADER` | `Authorization` | string | 否 | JWT 头字段名 |
| `jwt_secret` | `GATEWAY_JWT_SECRET` | `""` | string | 生产环境必填 | 网关 JWT 签名密钥（至少 32 字节） |
| `jwt_algorithm` | `GATEWAY_JWT_ALGORITHM` | `HS256` | string | 否 | 网关 JWT 算法 |
| `jwt_issuer` | `GATEWAY_JWT_ISSUER` | `yunxi` | string | 否 | JWT 签发者 |

### 4.4 API Key 配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `api_key_1` ~ `api_key_20` | `GATEWAY_API_KEY_1` ~ `GATEWAY_API_KEY_20` | `""` | string | 生产环境必填 | 服务间调用 API Key，可配置多个 |
| `enable_dev_key` | `GATEWAY_ENABLE_DEV_KEY` | `true` | bool | 否 | 是否启用开发环境专用 Key |
| `dev_api_key` | `GATEWAY_DEV_API_KEY` | `""` | string | 否 | 开发环境专用 Key（生产环境请禁用） |

### 4.5 限流配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `rate_limit_per_minute` | `GATEWAY_RATE_LIMIT_TOTAL` | `600` | int | 否 | 全局每分钟限流次数 |
| `rate_limit_per_ip` | `GATEWAY_RATE_LIMIT_PER_IP` | `100` | int | 否 | 每 IP 每分钟限流次数 |

### 4.6 熔断配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `circuit_breaker_threshold` | `GATEWAY_CB_THRESHOLD` | `5` | int | 否 | 连续失败次数阈值（触发熔断） |
| `circuit_breaker_recovery_time` | `GATEWAY_CB_RECOVERY` | `30` | int | 否 | 熔断恢复时间（秒） |

### 4.7 模块路由表

网关路由表在代码中定义（`build_default_routes()`），包含 12 个模块的路由配置。每个路由包含：目标地址、超时、健康检查、认证要求、限流阈值、熔断配置、协议支持等。

路由配置修改需通过代码变更，不通过环境变量配置。

---

## 5. M8 控制塔配置

> 配置类：`Settings`
> 环境变量前缀：`M8_`
> 源码位置：`M8-control-tower/backend/config.py`

### 5.1 服务配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `app_name` | `M8_APP_NAME` | `云汐管理工作台 M8` | string | 否 | 应用名称 |
| `version` | `M8_VERSION` | `1.0.0` | string | 否 | 版本号 |
| `host` | `M8_HOST` | `0.0.0.0` | string | 否 | 监听地址 |
| `port` | `M8_PORT` / `M8_BACKEND_PORT` | `8008` | int | 否 | 后端监听端口 |
| `frontend_port` | `M8_FRONTEND_PORT` | `5174` | int | 否 | 前端端口 |
| `env` | `M8_ENV` | `development` | string | 否 | 运行环境 |
| `log_level` | `M8_LOG_LEVEL` | `info` | string | 否 | 日志级别 |

### 5.2 安全配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `admin_username` | `M8_ADMIN_USERNAME` | `admin` | string | 否 | 默认管理员用户名 |
| `admin_password` | `M8_ADMIN_PASSWORD` | `""` | string | 生产环境必填 | 默认管理员密码（首次登录后请立即修改） |
| `jwt_secret` | `M8_JWT_SECRET` | `""` | string | 生产环境必填 | JWT 签名密钥（至少 32 字节） |
| `jwt_algorithm` | `M8_JWT_ALGORITHM` | `HS256` | string | 否 | JWT 签名算法 |
| `access_token_expire_minutes` | `M8_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | int | 否 | 访问令牌有效期（分钟） |
| `m8_admin_token` | `M8_ADMIN_TOKEN` | `""` | string | 生产环境必填 | M8 模块管理令牌 |

### 5.3 CORS 配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `cors_origins` | `M8_CORS_ORIGINS` | `*` | string | 生产环境必填 | CORS 允许来源 |

### 5.4 数据库配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `database_url` | `M8_DATABASE_URL` / `M8_DATABASE_PATH` | `sqlite:///data/m8.db` | string | 否 | 数据库连接 URL |

### 5.5 密码强度要求

M8 管理员密码需满足以下要求（`PASSWORD_MIN_LENGTH = 12`）：
- 至少 12 位
- 包含大写字母
- 包含小写字母
- 包含数字
- 包含特殊字符（`!@#$%^&*()-_=+` 等）

---

## 6. 各模块通用配置

以下配置适用于 M1~M12 各模块（环境变量前缀替换为对应模块编号）。

### 6.1 模块基础配置

| 配置项 | 环境变量格式 | 默认值 | 类型 | 必填 | 说明 |
|-------|------------|--------|------|------|------|
| `name` | `M{X}_NAME` | `m{X}-{module}` | string | 否 | 模块名称 |
| `port` | `M{X}_PORT` | 8000 + 模块号 | int | 否 | 监听端口 |
| `host` | `M{X}_HOST` | `0.0.0.0` | string | 否 | 监听地址 |
| `env` | `M{X}_ENV` | `development` | string | 否 | 运行环境 |

### 6.2 模块安全配置

| 配置项 | 环境变量格式 | 默认值 | 类型 | 必填 | 说明 |
|-------|------------|--------|------|------|------|
| `admin_token` | `M{X}_ADMIN_TOKEN` | `""` | string | 生产环境必填 | 管理员令牌（模块间调用鉴权） |
| `encryption_key` | `M{X}_ENCRYPTION_KEY` | `""` | string | 生产环境必填 | AES-256 加密密钥（恰好 32 字节） |
| `jwt_secret` | `M{X}_JWT_SECRET` | `""` | string | 生产环境必填 | JWT 签名密钥（至少 32 字节） |

### 6.3 模块数据库配置

| 配置项 | 环境变量格式 | 默认值 | 类型 | 必填 | 说明 |
|-------|------------|--------|------|------|------|
| `database_url` | `M{X}_DATABASE_URL` | - | string | 否 | 数据库连接 URL |
| `database_path` | `M{X}_DATABASE_PATH` | `../data/m{x}.db` | string | 否 | SQLite 数据库文件路径 |
| `vector_db_path` | `M{X}_VECTOR_DB_PATH` | - | string | 否 | 向量数据库路径（M5 等模块） |

### 6.4 联邦调度密钥（M1）

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `federation_master_key` | `FEDERATION_MASTER_KEY` | `""` | string | 生产环境必填 | 联邦调度主密钥 |
| `federation_admin_key` | `FEDERATION_ADMIN_KEY` | `""` | string | 生产环境必填 | 联邦调度管理员密钥 |
| `federation_internal_secret` | `FEDERATION_INTERNAL_SECRET` | `""` | string | 生产环境必填 | 联邦内部通信密钥 |

---

## 7. 大模型配置

> 环境变量：无统一前缀
> 参考文件：`config/.env.example`

### 7.1 LLM 通用配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `provider` | `LLM_PROVIDER` | `ollama` | string | 是 | LLM 提供商：`deepseek` / `openai` / `ollama` / `azure` |
| `api_key` | `LLM_API_KEY` | `""` | string | 外部服务必填 | LLM API 密钥（本地 Ollama 可留空） |
| `base_url` | `LLM_BASE_URL` | `http://localhost:11434/v1` | string | 否 | API 基础地址 |
| `model` | `LLM_MODEL` | `qwen2.5:7b` | string | 否 | 默认模型 |
| `timeout` | `LLM_TIMEOUT` | `60` | int | 否 | 请求超时时间（秒） |

### 7.2 嵌入模型配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `embedding_model` | `EMBEDDING_MODEL` | `nomic-embed-text` | string | 否 | 嵌入模型名称 |
| `embedding_dimensions` | `EMBEDDING_DIMENSIONS` | `768` | int | 否 | 嵌入向量维度 |

### 7.3 Ollama 配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `ollama_base_url` | `OLLAMA_BASE_URL` | `http://localhost:11434` | string | 否 | Ollama 服务地址 |
| `ollama_model` | `OLLAMA_MODEL` | `qwen2.5:7b` | string | 否 | 默认 Ollama 模型 |
| `ollama_timeout` | `OLLAMA_TIMEOUT` | `120` | int | 否 | 请求超时（秒） |
| `ollama_keep_alive` | `OLLAMA_KEEP_ALIVE` | `5m` | string | 否 | 模型保持加载时间 |
| `ollama_embedding_model` | `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | string | 否 | 嵌入模型 |
| `ollama_available_models` | `OLLAMA_AVAILABLE_MODELS` | `qwen2.5:7b,qwen2.5:14b,qwen2.5:1.5b` | string | 否 | 可用模型列表（逗号分隔） |

### 7.4 代码生成配置（M4）

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `m4_enable_llm` | `M4_ENABLE_LLM` | `true` | bool | 否 | 是否启用 LLM 代码生成 |
| `llm_codegen_url` | `LLM_CODEGEN_URL` | `http://localhost:11434/v1/chat/completions` | string | 否 | 代码生成 API 端点 |
| `llm_codegen_model` | `LLM_CODEGEN_MODEL` | `qwen2.5:7b` | string | 否 | 代码生成专用模型 |

---

## 8. WAF 安全防护配置

> 环境变量前缀：`WAF_`
> 源码位置：`shared/core/waf_middleware.py`

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `enabled` | `WAF_ENABLED` | `true` | bool | 生产环境必填 | 是否启用 WAF |
| `mode` | `WAF_MODE` | `monitor` | string | 生产环境必填 | 工作模式：`monitor`（仅日志） / `block`（拦截） |
| `rule_types` | `WAF_RULE_TYPES` | `""`（全部启用） | string | 否 | 启用的规则类型，逗号分隔：`sql_injection,xss,command_injection,path_traversal,csrf` |
| `exclude_paths` | `WAF_EXCLUDE_PATHS` | `/health,/m8/health,/m8/metrics,/m8/config` | string | 否 | 排除的路径（逗号分隔） |
| `body_limit_kb` | `WAF_BODY_LIMIT_KB` | `10` | int | 否 | 请求体检测大小限制（KB） |

---

## 9. 备份调度配置

> 环境变量前缀：`BACKUP_`
> 源码位置：`shared/data/data_layer/backup_scheduler.py`

### 9.1 全局备份配置

| 配置项 | 环境变量名 | 默认值 | 类型 | 必填 | 说明 |
|-------|-----------|--------|------|------|------|
| `enabled` | `BACKUP_ENABLED` | `true` | bool | 否 | 是否启用统一备份调度 |
| `root` | `BACKUP_ROOT` | `backups` | string | 否 | 备份根目录（相对于项目根目录） |
| `default_type` | `BACKUP_DEFAULT_TYPE` | `full` | string | 否 | 默认备份类型：`full` / `incremental` / `differential` |
| `compression` | `BACKUP_COMPRESSION` | `gzip` | string | 否 | 压缩类型：`gzip` / `none` |
| `encryption` | `BACKUP_ENCRYPTION` | `none` | string | 否 | 加密类型：`aes-256-gcm` / `none` |
| `encryption_key` | `BACKUP_ENCRYPTION_KEY` | `""` | string | 启用加密时必填 | 加密密钥（base64 编码的 32 字节密钥） |
| `retention_strategy` | `BACKUP_RETENTION_STRATEGY` | `hybrid` | string | 否 | 保留策略：`count` / `age` / `size` / `hybrid` |
| `max_backups` | `BACKUP_MAX_BACKUPS` | `30` | int | 否 | 最大保留备份数 |
| `max_age_days` | `BACKUP_MAX_AGE_DAYS` | `30` | int | 否 | 最大保留天数 |
| `max_size_gb` | `BACKUP_MAX_SIZE_GB` | `50` | int | 否 | 最大存储空间（GB） |
| `alert_failure_threshold` | `BACKUP_ALERT_FAILURE_THRESHOLD` | `3` | int | 否 | 备份失败告警阈值（连续失败次数） |
| `disk_warn_percent` | `BACKUP_DISK_WARN_PERCENT` | `20` | int | 否 | 磁盘空间告警阈值（%） |
| `disk_critical_percent` | `BACKUP_DISK_CRITICAL_PERCENT` | `10` | int | 否 | 磁盘空间严重告警阈值（%） |
| `storage_monitor_interval` | `BACKUP_STORAGE_MONITOR_INTERVAL` | `3600` | int | 否 | 存储监控间隔（秒） |

### 9.2 各模块备份策略覆盖

| 模块 | 启用 | 计划 | 时间 | 最大保留数 |
|------|------|------|------|----------|
| M4 | `BACKUP_M4_ENABLED=true` | `daily` | `03:00` | 30 |
| M5 | `BACKUP_M5_ENABLED=true` | `daily` | `03:30` | 30 |
| M6 | `BACKUP_M6_ENABLED=true` | `daily` | `04:00` | 20 |
| M8 | `BACKUP_M8_ENABLED=true` | `daily` | `02:00` | 50 |
| M9 | `BACKUP_M9_ENABLED=true` | `daily` | `03:00` | 30 |
| M10 | `BACKUP_M10_ENABLED=true` | `daily` | `04:30` | 30 |
| M12 | `BACKUP_M12_ENABLED=true` | `daily` | `05:00` | 30 |

---

## 10. 数据库配置

### 10.1 SQLite 默认数据库

各模块默认使用 SQLite 数据库，数据库文件位于各模块 `data/` 目录下：

| 模块 | 默认数据库路径 | 环境变量 |
|------|--------------|---------|
| M1 | `../data/m1.db` | `M1_DATABASE_URL` |
| M2 | `../data/m2.db` | `M2_DATABASE_PATH` |
| M3 | `../data/m3.db` | `M3_DATABASE_PATH` |
| M4 | `../data/m4.db` | `M4_DATABASE_PATH` |
| M5 | `../data/m5.db` | `M5_DATABASE_PATH` |
| M6 | `../data/m6.db` | `M6_DATABASE_PATH` |
| M7 | `../data/m7.db` | `M7_DATABASE_PATH` |
| M8 | `data/m8.db` | `M8_DATABASE_URL` |
| M12 | - | `M12_DATABASE_URL` |

### 10.2 向量数据库

| 模块 | 默认路径 | 环境变量 |
|------|---------|---------|
| M5 | `../data/m5-vector` | `M5_VECTOR_DB_PATH` |

---

## 11. 快速配置指南（最小必要配置）

### 11.1 开发环境最小配置

开发环境下，大部分配置使用默认值即可。以下是最小必要配置：

```env
# 1. 运行环境
YUNXI_ENV=development

# 2. LLM 配置（根据实际使用的提供商填写）
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# 3. 日志级别
YUNXI_LOG_LEVEL=info
```

> **注意**：开发环境下，JWT 密钥、模块 Token 等敏感字段为空时会自动生成随机值并在日志中显示，重启后失效。

### 11.2 生产环境最小配置

生产环境必须配置以下核心项：

```env
# ===== 基础 =====
YUNXI_ENV=production
YUNXI_LOG_LEVEL=warning

# ===== 安全（必须全部配置强随机值） =====
YUNXI_SECURITY_JWT_SECRET=<至少32字符的强随机密钥>
YUNXI_SECURITY_CORS_ORIGINS=https://your-domain.com,https://app.your-domain.com
YUNXI_SECURITY_WAF_ENABLED=true
YUNXI_SECURITY_WAF_MODE=block

# ===== 网关 =====
GATEWAY_JWT_SECRET=<至少32字符的强随机密钥>
GATEWAY_API_KEY_1=<服务间调用API Key>
GATEWAY_ENABLE_DEV_KEY=false
GATEWAY_CORS_ORIGINS=https://your-domain.com

# ===== M8 管理员 =====
M8_ADMIN_PASSWORD=<符合强度要求的强密码>
M8_JWT_SECRET=<至少32字符的强随机密钥>
M8_ADMIN_TOKEN=<至少32字符的强随机密钥>

# ===== 模块令牌（所有模块都需要） =====
M1_ADMIN_TOKEN=<强随机值>
M2_ADMIN_TOKEN=<强随机值>
# ... M3 ~ M12 同样需要配置
```

### 11.3 生成安全密钥的方法

```bash
# 方法一：使用 Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 方法二：使用 openssl
openssl rand -hex 32

# 方法三：PowerShell
-join ((1..32) | % { '{0:x2}' -f (Get-Random -Max 256) })
```

---

## 12. 生产环境检查清单

### 12.1 安全检查

- [ ] `YUNXI_ENV=production` 已设置
- [ ] JWT 密钥已配置且长度 >= 32 字符
- [ ] JWT 密钥不是默认值/弱密钥（不以 `changeme_`、`yunxi-`、`test` 等开头）
- [ ] 所有模块的 `ADMIN_TOKEN` 已配置为强随机值
- [ ] `CORS_ORIGINS` 不包含 `*`，已配置具体域名
- [ ] `WAF_ENABLED=true` 且 `WAF_MODE=block`
- [ ] 网关 `GATEWAY_ENABLE_DEV_KEY=false`
- [ ] M8 管理员密码符合强度要求（12位+，含大小写数字特殊字符）
- [ ] 各模块 `ENCRYPTION_KEY` 已配置为 32 字节密钥
- [ ] `.env` 文件权限已设置（仅服务账户可读取）
- [ ] 未在代码仓库中提交任何真实密钥

### 12.2 配置完整性检查

- [ ] 所有模块的端口号已规划且不冲突
- [ ] 所有模块的 base_url 已正确配置
- [ ] 数据库路径已正确设置
- [ ] 备份目录已配置且有足够磁盘空间
- [ ] LLM API 密钥已正确配置

### 12.3 性能与可靠性检查

- [ ] 限流阈值已根据业务量调整
- [ ] 熔断参数已合理配置
- [ ] 数据库连接池大小已调整
- [ ] 日志级别设置为 `warning` 或 `error`
- [ ] 健康检查路径已配置

---

## 13. 配置加载优先级

云汐系统采用多源配置加载，优先级从高到低：

1. **初始化参数**（代码中显式传入的参数）
2. **环境变量**（操作系统环境变量，优先级最高）
3. **.env 文件**（`config/yunxi.env` 或各模块 `.env`）
4. **YAML 配置文件**（`config/yunxi.yaml`，可选）
5. **默认值**（代码中定义的默认值）

### 13.1 配置文件查找顺序

系统会按以下顺序查找配置文件：

1. 项目根目录下的 `config/yunxi.env`
2. 项目根目录下的 `config/yunxi.yaml` / `config/yunxi.yml`
3. 当前工作目录下的 `.env`
4. 当前工作目录下的 `config.yaml` / `config.yml`

### 13.2 敏感字段说明

以下字段名包含敏感关键词，会被自动脱敏处理（`to_dict(sanitize=True)`）：

- `token`、`secret`、`password`、`api_key`
- `encryption_key`、`private_key`、`access_key`
- `admin_token`、`jwt_secret`、`db_password`
- `redis_password`、`mongo_password`

---

## 相关文档

- [配置指南](../shared/core/CONFIG_GUIDE.md) - shared 核心配置使用指南
- [安全文档](SECURITY.md) - 安全架构与防护措施
- [运维手册](OPS.md) - 日常运维操作指南
- [部署手册](DEPLOYMENT.md) - 生产环境部署指南
- [环境变量模板](../config/.env.example) - 完整的环境变量示例文件
