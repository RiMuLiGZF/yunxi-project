# M8 管理控制塔 (Control Tower)

云汐系统的统一管理中枢，提供用户认证、模块纳管、系统监控、配置中心、算力调度等核心管理能力。

## 模块定位

M8 是云汐系统 10 大模块中的管理枢纽，承担以下核心角色：

- **统一入口**：用户通过 M8 管理台访问所有模块功能
- **模块纳管**：通过标准 `/m8/*` 协议管理 M1-M10 所有模块的健康、指标、配置、启停
- **权限控制**：用户认证、角色权限、JWT Token 管理
- **配置中心**：统一管理系统配置和各模块 API 密钥
- **监控运维**：系统状态监控、审计日志、告警管理

## 目录结构

```
M8-control-tower/
├── backend/                  # 后端服务
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置管理
│   ├── auth.py              # 认证与权限（JWT + bcrypt）
│   ├── models.py            # SQLAlchemy 数据模型 + 数据库初始化
│   ├── schemas.py           # Pydantic 响应模型
│   ├── crypto.py            # Fernet 加密工具（API Key 加密存储）
│   ├── repositories/        # 数据访问层（Repository 模式）
│   │   ├── settings_repository.py
│   │   ├── audit_repository.py
│   │   └── user_repository.py
│   ├── routers/             # API 路由（34 个子模块）
│   │   ├── auth.py          # 认证（登录/登出/改密）
│   │   ├── users.py         # 用户管理
│   │   ├── system.py        # 系统设置 + API 密钥管理
│   │   ├── audit.py         # 审计日志
│   │   ├── monitor.py       # 监控中心
│   │   ├── modules.py       # 模块管理
│   │   ├── workflow.py      # 工作流管理
│   │   ├── growth.py        # 成长中心
│   │   ├── review.py        # 复盘总结
│   │   ├── study_plan.py    # 学业规划
│   │   ├── life_management.py  # 生活管理
│   │   ├── emotion_comfort.py  # 情绪陪伴
│   │   ├── social_relation.py  # 人际关系
│   │   ├── appearance.py    # 形象工坊
│   │   ├── compute_*.py     # 算力调度（8个路由模块）
│   │   ├── evolution_*.py   # 自进化引擎（3个路由模块）
│   │   └── ...              # 其他业务路由
│   ├── data/                # 数据文件
│   │   ├── m8.db           # SQLite 数据库
│   │   └── compute_master.key  # Fernet 主密钥
│   └── tests/               # 测试文件
├── frontend/                # （前端页面存放在项目根目录 frontend/m8/）
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量示例
└── README.md                # 本文件
```

## 核心功能

### 1. 用户与认证
- JWT Bearer Token 认证
- bcrypt 密码哈希
- 角色权限体系（owner > admin > editor > viewer）
- 首次启动自动生成管理员密码
- 密码修改功能

### 2. 系统设置
- 主题、语言、通知等基础配置
- **大模型配置**：AI Provider、模型、温度、Token 限制
- **API 密钥管理**：LLM API Key 加密存储（Fernet AES-128-CBC + HMAC）
- 模块对接 Token 管理
- 加密状态信息展示

### 3. 模块纳管
- 10 个模块统一健康检查
- 实时性能指标采集
- 模块配置管理
- 模块启停控制（通过 M10）

### 4. 算力调度
- 多算力源管理（API Key 加密存储）
- 算力分组与路由策略
- 模型管理与负载均衡
- 算力监控与统计
- 技能调度

### 5. 审计与安全
- 操作审计日志
- 登录日志追踪
- 安全事件记录
- API 速率限制（部分模块）

### 6. 业务功能
- 成长中心（积分、成就、等级）
- 复盘总结
- 学业规划
- 生活管理
- 情绪陪伴
- 人际关系
- 形象工坊
- 自进化引擎

## 数据库表

| 表名 | 用途 | 迁移状态 |
|------|------|----------|
| users | 用户表 | DB 优先 + JSON 兼容 |
| audit_logs | 审计日志 | DB 优先 + JSON 兼容 |
| system_settings | 系统设置 | DB 优先 + JSON 兼容 |
| workflows | 工作流定义 | DB 优先 + JSON 兼容 |
| workflow_runs | 工作流运行记录 | DB 优先 + JSON 兼容 |
| compute_sources | 算力源（含加密 API Key） | DB |
| compute_groups | 算力分组 | DB |
| compute_models | 模型配置 | DB |
| alert_records | 告警记录 | DB |
| watch_devices | 手表设备 | DB |
| inspection_agents | 巡检 Agent | DB |
| growth_* | 成长体系相关表 | DB |

所有数据库表使用 SQLite + SQLAlchemy ORM。

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| M8_HOST | 服务监听地址 | 0.0.0.0 |
| M8_PORT | 服务端口 | 8008 |
| M8_ADMIN_USERNAME | 管理员用户名 | admin |
| M8_ADMIN_PASSWORD | 管理员密码 | *自动生成* |
| M8_JWT_SECRET | JWT 签名密钥 | *自动生成* |
| M8_ADMIN_TOKEN | M8 内部对接 Token | 空（需配置） |
| CORS_ORIGINS | CORS 允许来源 | * |
| DATABASE_URL | 数据库连接 | sqlite:///./data/m8.db |
| ACCESS_TOKEN_EXPIRE_MINUTES | Token 过期时间 | 1440 |

> **安全提示**：生产环境必须显式配置 `M8_ADMIN_PASSWORD` 和 `M8_JWT_SECRET`，不要依赖自动生成的值。

## API 概览

### 认证接口
- `POST /api/auth/login` — 用户登录
- `POST /api/auth/logout` — 用户登出
- `GET /api/auth/userinfo` — 获取当前用户信息
- `POST /api/auth/change-password` — 修改密码

### 系统管理
- `GET /api/system/settings` — 获取系统设置
- `PUT /api/system/settings` — 更新系统设置
- `GET /api/system/tokens` — 获取模块 Token 列表
- `POST /api/system/tokens/regenerate` — 批量重新生成 Token
- `GET /api/system/encryption/info` — 加密状态信息
- `GET /api/system/llm/test` — 测试 LLM 连接

### 审计日志
- `GET /api/audit/logs` — 审计日志列表
- `POST /api/audit/logs` — 记录审计日志

### 算力调度
- `GET /api/compute/sources` — 算力源列表
- `POST /api/compute/sources` — 新增算力源
- `PUT /api/compute/sources/{id}` — 更新算力源
- `DELETE /api/compute/sources/{id}` — 删除算力源

更多接口请访问 `/docs` 查看 OpenAPI 文档。

## 启动方式

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量（可选，未配置则自动生成密码和 JWT 密钥）
cp .env.example .env
# 编辑 .env 设置 M8_ADMIN_PASSWORD, M8_JWT_SECRET 等

# 启动服务
cd backend
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8008
```

首次启动时，如果未配置管理员密码，系统会自动生成一个 16 位随机密码并打印到控制台，请妥善保存。

## 安全特性

- **密码存储**：bcrypt 哈希，72 字节截断
- **JWT 认证**：HS256 签名，可配置过期时间
- **API Key 加密**：Fernet (AES-128-CBC + HMAC-SHA256)
- **主密钥**：独立密钥文件，权限 600
- **审计日志**：所有关键操作留痕
- **Token 比较**：hmac.compare_digest 防止时序攻击

## 与其他模块的关系

M8 通过标准 M8 协议（`/m8/health`, `/m8/metrics`, `/m8/config`）纳管所有模块：

```
M8 ──→ M1 多Agent集群  (/m8/* 接口)
   ──→ M2 技能集群
   ──→ M3 端云协同
   ──→ M4 场景引擎
   ──→ M5 潮汐记忆
   ──→ M6 硬件外设
   ──→ M7 工作流编排
   ──→ M9 开发者工坊
   └─→ M10 系统卫士
```

M8 还通过 API 直接调用各模块的业务接口，提供统一的前端体验。

## 版本信息

- 当前版本：v2.0.0
- 协议版本：M8 Standard v1
- 数据库版本：v3 (SQLite + SQLAlchemy)
