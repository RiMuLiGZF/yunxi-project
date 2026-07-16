# 云汐 API 网关 (API-Gateway)

> 版本：v1.0.0 · 状态：开发中
> 端口：8080

## 一、模块定位

云汐系统的统一接入层，负责所有外部请求的路由转发、认证鉴权、速率限制、熔断降级。

从 M8 控制塔中拆分出代理职责，解决 M8 单点故障问题。

## 二、核心功能

### 2.1 路由转发
- 基于路径前缀的模块路由（/m1, /m2, /m8 ...）
- 12个模块统一接入
- 自动请求头转发（X-Forwarded-For等）
- 响应头注入（网关延迟、模块标识）

### 2.2 认证鉴权
- API Key 认证（X-API-Key）
- JWT Bearer Token 认证
- 路径白名单机制
- 模块级白名单

### 2.3 速率限制
- 全局限速（默认600请求/分钟）
- 单IP限速（默认100请求/分钟）
- 令牌桶算法
- 响应头返回限速信息

### 2.4 熔断降级
- 熔断器模式（Closed → Open → Half-Open）
- 连续失败次数阈值可配置
- 自动恢复机制
- 半开状态探测

### 2.5 M8标准接口
- `GET /m8/health` - 健康检查（含各模块状态）
- `GET /m8/metrics` - 运行指标
- 符合 M8 纳管标准

## 三、架构设计

```
客户端请求
    ↓
[CORS 中间件]
    ↓
[速率限制中间件] ← 令牌桶算法
    ↓
[认证中间件] ← API Key / JWT
    ↓
[代理转发] ← 路由匹配 + HTTP客户端
    ↓
[熔断器] ← 失败计数 + 状态机
    ↓
目标模块服务
```

## 四、目录结构

```
API-Gateway/
├── server.py              # 启动入口
├── requirements.txt       # 依赖
├── src/
│   ├── main.py           # 主应用（FastAPI + 路由）
│   ├── config.py         # 配置管理
│   ├── middleware/
│   │   ├── auth.py       # 认证中间件
│   │   └── rate_limit.py # 速率限制中间件
│   └── services/
│       ├── proxy_service.py    # 代理转发服务
│       ├── circuit_breaker.py  # 熔断器
│       └── rate_limiter.py     # 速率限制器
└── tests/
    └── ...
```

## 五、快速开始

### 5.1 安装依赖
```bash
pip install -r requirements.txt
```

### 5.2 配置环境变量
```bash
# 网关配置
GATEWAY_PORT=8080
GATEWAY_LOG_LEVEL=info

# 各模块地址
M8_BASE_URL=http://localhost:8008
M1_BASE_URL=http://localhost:8001
# ... 其他模块
```

### 5.3 启动
```bash
python server.py
```

### 5.4 验证
```bash
# 网关健康检查
curl http://localhost:8080/health

# 查看路由表
curl http://localhost:8080/routes

# 代理转发到M8
curl http://localhost:8080/m8/health \
  -H "X-API-Key: yunxi-gateway-dev-key"
```

## 六、路由规则

| 前缀 | 目标模块 | 目标地址 |
|------|---------|---------|
| /m1 | M1 多Agent集群 | http://localhost:8001 |
| /m2 | M2 技能集群 | http://localhost:8002 |
| /m3 | M3 端云协同 | http://localhost:8003 |
| /m4 | M4 场景引擎 | http://localhost:8004 |
| /m5 | M5 潮汐记忆 | http://localhost:8005 |
| /m6 | M6 硬件外设 | http://localhost:8006 |
| /m7 | M7 工作流编排 | http://localhost:8007 |
| /m8 | M8 管理控制塔 | http://localhost:8008 |
| /m9 | M9 开发者工坊 | http://localhost:8009 |
| /m10 | M10 系统卫士 | http://localhost:8010 |
| /m11 | M11 MCP总线 | http://localhost:8011 |
| /m12 | M12 安全盾 | http://localhost:8012 |

## 七、与 M8 的关系

| 职责 | M8（管理控制塔） | API Gateway（网关） |
|------|-----------------|-------------------|
| 用户认证 | ✅ 核心 | ✅ 透传验证 |
| 模块纳管 | ✅ 核心 | ✅ 健康检查 |
| 业务代理 | ❌ 移除 | ✅ 核心职责 |
| 速率限制 | ⚠️ 部分 | ✅ 统一入口 |
| 熔断降级 | ❌ 无 | ✅ 统一入口 |
| 管理后台UI | ✅ 核心 | ❌ 无 |

迁移策略：
1. 网关上线初期，M8保留代理能力作为后备
2. 逐步将外部流量切换到网关
3. 稳定后移除M8中的代理路由
