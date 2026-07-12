# M12 安全盾 (Security Shield)

**模块代号**：M12
**模块名称**：安全盾
**版本**：v1.0.0
**端口**：8012
**技术栈**：FastAPI + SQLAlchemy + JWT + WAF

---

## 一、模块概述

M12 安全盾是云汐系统的安全防护核心模块，负责全系统的 Web 应用防火墙（WAF）、API 密钥管理、IP 黑白名单控制、速率限制、安全审计和威胁检测。它像一道坚固的安全屏障，7x24 小时守护云汐系统的网络安全。

### 核心能力

| 能力 | 说明 |
|------|------|
| **WAF 防护墙** | SQL注入、XSS、CSRF、命令注入等常见攻击检测与拦截 |
| **API 密钥管理** | API Key 生成、吊销、权限分配、使用统计 |
| **IP 访问控制** | 黑白名单管理、自动封禁、IP 段支持 |
| **速率限制** | 令牌桶算法，按 IP / API Key 粒度限流 |
| **安全审计** | 全量安全事件记录、查询、统计、导出 |
| **JWT 认证** | 基于角色的访问控制（RBAC） |
| **安全仪表盘** | 实时安全态势展示、攻击趋势、威胁分布 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、目录结构

```
M12-security-shield/
├── server.py              # 服务启动入口
├── requirements.txt       # 依赖列表
├── README.md              # 本文件
├── __init__.py            # 包初始化
├── backend/               # 后端核心代码
│   ├── __init__.py
│   ├── main.py            # FastAPI 应用入口 create_app()
│   ├── config.py          # 配置管理（Settings 类）
│   ├── database.py        # 数据库连接（SQLAlchemy + SQLite）
│   ├── models.py          # 数据库 ORM 模型（5 张核心表）
│   ├── auth.py            # 认证逻辑（API Key + JWT + 角色权限）
│   ├── routers/           # API 路由层
│   │   ├── __init__.py    # 统一导出
│   │   ├── status.py      # 健康检查/状态接口
│   │   ├── waf.py         # WAF 防护墙接口
│   │   ├── auth_api.py    # 鉴权管理接口
│   │   ├── ip_control.py  # IP 访问控制接口
│   │   ├── audit.py       # 安全审计接口
│   │   └── dashboard.py   # 安全仪表盘接口
│   ├── services/          # 业务服务层
│   │   ├── __init__.py
│   │   ├── waf_engine.py  # WAF 检测引擎
│   │   ├── rate_limiter.py # 速率限制服务（令牌桶）
│   │   ├── ip_filter.py   # IP 过滤服务
│   │   └── audit_service.py # 审计日志服务
│   └── schemas/           # Pydantic 数据模型
│       ├── __init__.py
│       ├── common.py      # 通用响应模型
│       ├── waf.py         # WAF 相关模型
│       ├── auth.py        # 鉴权相关模型
│       ├── ip.py          # IP 控制相关模型
│       └── audit.py       # 审计相关模型
└── data/                  # 数据目录
    ├── .gitkeep
    └── m12.db             # SQLite 数据库（运行时生成）
```

---

## 三、数据库表结构

### 3.1 安全事件表 (security_events)
记录所有安全相关事件，包括攻击拦截、登录失败、权限异常等。

### 3.2 API 密钥表 (api_keys)
管理 API 密钥，支持权限分配、过期时间、使用统计。

### 3.3 IP 黑名单表 (ip_blacklist)
IP 黑名单管理，支持 IP 段、自动解封时间、封禁原因。

### 3.4 WAF 规则表 (waf_rules)
WAF 防护规则管理，支持规则类型、匹配模式、严重级别。

### 3.5 审计日志表 (audit_logs)
全量操作审计日志，支持按用户、模块、操作类型查询。

---

## 四、配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M12_PORT` | `8012` | 服务监听端口 |
| `M12_HOST` | `0.0.0.0` | 监听地址 |
| `M12_ENV` | `development` | 运行环境 |
| `M12_DEBUG` | `true` | 调试模式 |
| `M12_WAF_ENABLED` | `true` | WAF 防护开关 |
| `M12_RATE_LIMIT_ENABLED` | `true` | 速率限制开关 |
| `M12_DEFAULT_RATE` | `60` | 默认每分钟请求限制 |
| `M12_JWT_SECRET` | `yunxi-m12-secret` | JWT 签名密钥 |
| `M12_JWT_EXPIRE_MINUTES` | `1440` | Token 过期时间（分钟） |
| `M12_ADMIN_TOKEN` | `""` | M8 对接管理 Token |
| `M12_AUDIT_RETENTION_DAYS` | `90` | 审计日志保留天数 |

---

## 五、API 接口

### 5.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 5.2 状态接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/m12/status/health` | GET | 健康检查 |
| `/api/m12/status/info` | GET | 模块信息 |

### 5.3 WAF 防护墙

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/m12/waf/status` | GET | WAF 状态查询 |
| `/api/m12/waf/rules` | GET | 规则列表 |
| `/api/m12/waf/rules` | POST | 新增规则 |
| `/api/m12/waf/rules/{id}` | PUT | 更新规则 |
| `/api/m12/waf/rules/{id}` | DELETE | 删除规则 |
| `/api/m12/waf/toggle` | POST | 启用/禁用 WAF |

### 5.4 鉴权管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/m12/auth/login` | POST | 登录获取 Token |
| `/api/m12/auth/keys` | GET | API 密钥列表 |
| `/api/m12/auth/keys` | POST | 创建 API 密钥 |
| `/api/m12/auth/keys/{id}` | DELETE | 吊销 API 密钥 |
| `/api/m12/auth/keys/{id}/rotate` | POST | 轮换 API 密钥 |

### 5.5 IP 访问控制

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/m12/ip/blacklist` | GET | 黑名单列表 |
| `/api/m12/ip/blacklist` | POST | 添加黑名单 |
| `/api/m12/ip/blacklist/{id}` | DELETE | 移除黑名单 |
| `/api/m12/ip/whitelist` | GET | 白名单列表 |
| `/api/m12/ip/whitelist` | POST | 添加白名单 |
| `/api/m12/ip/whitelist/{id}` | DELETE | 移除白名单 |

### 5.6 安全审计

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/m12/audit/events` | GET | 安全事件查询 |
| `/api/m12/audit/events/{id}` | GET | 事件详情 |
| `/api/m12/audit/stats` | GET | 审计统计 |
| `/api/m12/audit/logs` | GET | 操作日志查询 |

### 5.7 安全仪表盘

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/m12/dashboard/summary` | GET | 安全概览 |
| `/api/m12/dashboard/attack-trend` | GET | 攻击趋势 |
| `/api/m12/dashboard/threat-distribution` | GET | 威胁分布 |

---

## 六、快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py

# 健康检查
curl http://localhost:8012/health

# M8 标准健康检查（带 Token）
curl -H "X-M8-Token: yunxi-m12-admin-token-2026" http://localhost:8012/m8/health

# API 文档
http://localhost:8012/docs
```

---

## 七、与其他模块关系

```
                    ┌─────────────┐
                    │   M8 管理台  │
                    └──────┬──────┘
                           │ 纳管/监控
                    ┌──────▼──────┐
                    │ M12 安全盾   │
                    └──────┬──────┘
         ┌─────────────────┼─────────────────┐
    ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
    │ M1-M11  │       │  WAF引擎  │       │ 审计日志 │
    │ 各模块   │       │ /速率限制 │       │ (存储)   │
    └─────────┘       └─────────┘       └─────────┘
```

- **上游**：M8 管理台通过 M8 标准接口调用 M12 获取安全状态
- **下游**：M12 为 M1-M11 所有模块提供安全防护和认证服务
