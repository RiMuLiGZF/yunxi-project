# M3 端云协同内核 (Edge-Cloud Kernel)

**模块代号**：M3
**模块名称**：端云协同内核
**版本**：v3.0
**端口**：8003
**技术栈**：FastAPI + 云端执行器 + 本地执行器 + 同步引擎

---

## 一、模块概述

M3 端云协同内核是云汐系统的混合调度层，负责在端侧（本地）和云侧（远程）之间智能分配计算任务，实现"端侧隐私保护 + 云端算力增强"的协同计算模式。

### 核心能力

| 能力 | 说明 |
|------|------|
| **双执行器** | 本地执行器 + 云端执行器，自动选择最优执行位置 |
| **智能路由** | 基于数据敏感度、算力需求、网络状况的路由决策 |
| **数据同步** | 端云数据双向同步、冲突检测与自动解决 |
| **离线模式** | 断网时本地降级运行，联网后自动同步 |
| **VRAM 监控** | GPU 显存监控与调度，避免 OOM |
| **熔断器/限流器** | 云端调用失败自动降级，保护系统稳定性 |
| **设备管理** | 多设备注册、健康检查、设备注册表 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、核心模块

| 模块 | 目录 | 说明 |
|------|------|------|
| **执行层** | `execution/` | cloud_executor + local_executor + route_engine |
| **网关层** | `gateway/` | cloud_gateway + circuit_breaker + rate_limiter |
| **数据层** | `local_data/` | local_data_manager + conflict_resolver + sync_client |
| **同步层** | `sync/` | sync_api + context_sync + tide_memory_bridge + offline_shadow |
| **资源层** | `resource/` | cache_manager + vram_monitor |
| **M8 API** | `m8_api/` | 健康/配置/升级/测试 + 设备注册 + 鉴权中间件 |
| **模型层** | `models/` | sync_models + call_log + exceptions + vram_report |

---

## 三、配置说明

### 配置文件

- `config/config.yaml` — 主配置文件
- `config/config.example.yaml` — 配置示例
- `config/hardware_bridge.yaml` — 硬件桥接配置
- `config/vram_policy.yaml` — VRAM 策略配置
- `config/sync_api_openapi.yaml` — OpenAPI 规范

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M3_HOST` | `0.0.0.0` | 监听地址 |
| `M3_PORT` | `8003` | 监听端口 |
| `M3_ENV` | `development` | 运行环境 |
| `M3_ADMIN_TOKEN` | `""` | M8 对接管理 Token |

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py

# 健康检查
curl http://localhost:8003/health

# API 文档
http://localhost:8003/docs
```

---

## 四、API 接口

### 4.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 4.2 同步管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v3/sync/status` | GET | 同步状态 |
| `POST /api/v3/sync/trigger` | POST | 触发同步 |
| `GET /api/v3/sync/conflicts` | GET | 冲突列表 |
| `POST /api/v3/sync/conflicts/{id}/resolve` | POST | 解决冲突 |

### 4.3 设备管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v3/devices` | GET | 设备列表 |
| `POST /api/v3/devices/{id}/remove` | POST | 移除设备 |

### 4.4 配置管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v3/config` | GET | 获取配置 |
| `POST /api/v3/config/update` | POST | 更新配置 |

### 4.5 V1 兼容接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v1/health` | GET | V1 健康检查 |
| `GET /api/v1/metrics` | GET | V1 指标 |
| `GET /api/v1/config` | GET | V1 配置 |

---

## 五、测试

```bash
# 运行所有测试
pytest edge_cloud_kernel/tests/ -v

# 运行同步 API 测试
pytest edge_cloud_kernel/tests/test_sync_api.py -v

# 运行 M8 集成测试
pytest edge_cloud_kernel/tests/test_m8_auth_health.py -v
```

---

## 六、协同模式

### 模式对比

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **纯本地** | 所有计算在端侧执行 | 高隐私数据、无网络 |
| **纯云端** | 所有计算在云侧执行 | 大算力需求、数据不敏感 |
| **混合模式** | 智能路由，按需分配 | 常规场景（默认） |
| **离线模式** | 断网降级，本地全量运行 | 网络不可用 |

### 冲突解决策略

1. **时间戳优先**：较新的修改胜出
2. **版本号校验**：基于版本向量的冲突检测
3. **人工仲裁**：无法自动解决时标记待人工处理

---

## 七、与其他模块关系

```
┌──────────┐          ┌──────────┐
│  端侧设备  │ ◀─────▶ │  云端服务  │
│ (Edge)   │   同步    │ (Cloud)  │
└────┬─────┘          └────┬─────┘
     │                     │
     └──────────┬──────────┘
                │
         M3 端云协同内核
                │
         ┌──────▼──────┐
         │  M8 管理台   │
         └─────────────┘
```

- **上游**：M1 调度中心通过 M3 实现端云协同调度
- **下游**：对接 M5 潮汐记忆实现数据同步
- **管理**：M8 管理台通过 M8 标准接口纳管 M3
