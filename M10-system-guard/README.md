# M10 系统卫士 (System Guard)

**模块代号**：M10
**模块名称**：系统卫士
**版本**：v1.0.0
**端口**：8010
**技术栈**：FastAPI + psutil + APScheduler

---

## 一、模块概述

M10 系统卫士是云汐系统的基础设施守护模块，负责全系统的资源监控、进程管理、阈值防护、审计日志和启动健康检查。它像一个 7x24 小时值守的运维工程师，确保云汐系统稳定高效运行。

### 核心能力

| 能力 | 说明 |
|------|------|
| **系统资源监控** | CPU、内存、磁盘、网络、温度实时采集 |
| **进程管理** | 云汐各模块进程状态监控，自动拉起异常进程 |
| **阈值防护** | 四级防护策略（正常/关注/警告/紧急），自动降级 |
| **审计日志** | 全系统操作审计，支持查询和导出 |
| **启动检查** | 系统启动时的健康预检，确保依赖就绪 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、目录结构

```
M10-system-guard/
├── server.py              # 服务启动入口
├── requirements.txt       # 依赖列表
├── .env.example           # 配置示例
├── README.md              # 本文件
├── m10_system_guard/      # 核心代码包
│   ├── __init__.py
│   ├── config.py          # 配置管理（9个子配置类）
│   ├── models.py          # 数据模型
│   ├── guard_engine.py    # 防护引擎（4种策略+四级拦截）
│   ├── system_monitor.py  # 系统资源监控（7类指标）
│   ├── process_manager.py # 进程管理（全量快照+进程树）
│   ├── audit_logger.py    # 审计日志
│   ├── startup_check.py   # 启动健康检查
│   ├── report_generator.py # 报告生成器（日报/周报）
│   ├── sandbox_scheduler.py # 沙箱调度器（四级任务队列）
│   └── api/               # API 路由层
│       ├── __init__.py
│       ├── status.py      # 系统状态接口
│       ├── process.py     # 进程管理接口
│       ├── guard.py       # 防护策略接口
│       ├── audit.py       # 审计日志接口
│       ├── report.py      # 报告生成接口
│       └── startup_check.py # 启动检查接口
└── tests/                 # 单元测试（5个文件）
    ├── test_guard_engine.py
    ├── test_process_manager.py
    ├── test_sandbox_scheduler.py
    ├── test_startup_check.py
    └── test_system_monitor.py
```

---

## 三、配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_PORT` | `8010` | 服务监听端口 |
| `M10_HOST` | `0.0.0.0` | 监听地址 |
| `M10_ENV` | `development` | 运行环境 |
| `M10_SAMPLE_INTERVAL` | `5` | 采样间隔（秒） |
| `M10_ADMIN_TOKEN` | `""` | M8 对接管理 Token |
| `M10_CPU_WARNING` | `70` | CPU 警告阈值（%） |
| `M10_CPU_CRITICAL` | `90` | CPU 紧急阈值（%） |
| `M10_MEM_WARNING` | `75` | 内存警告阈值（%） |
| `M10_MEM_CRITICAL` | `90` | 内存紧急阈值（%） |
| `M10_AUDIT_RETENTION` | `30` | 审计日志保留天数 |

### 防护等级

| 等级 | 颜色 | 触发条件 | 动作 |
|------|------|----------|------|
| NORMAL | 绿色 | 所有指标正常 | 正常运行 |
| WATCH | 黄色 | 单指标超过关注阈值 | 记录日志，增加采样 |
| WARNING | 橙色 | 多指标警告或单指标警告持续 | 发送告警，准备降级 |
| CRITICAL | 红色 | 关键指标紧急 | 自动降级，关闭非核心服务 |

---

## 四、API 接口

### 4.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 4.2 监控接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/monitor/current` | GET | 获取当前系统指标 |
| `/api/v1/monitor/history` | GET | 获取历史监控数据 |
| `/api/v1/monitor/processes` | GET | 获取进程列表 |
| `/api/v1/monitor/guard-level` | GET | 获取当前防护等级 |

### 4.3 进程管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/processes` | GET | 列出所有云汐进程 |
| `/api/v1/processes/{module}` | GET | 获取指定模块进程状态 |
| `/api/v1/processes/{module}/start` | POST | 启动指定模块 |
| `/api/v1/processes/{module}/stop` | POST | 停止指定模块 |
| `/api/v1/processes/{module}/restart` | POST | 重启指定模块 |

### 4.4 审计日志

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/audit/logs` | GET | 查询审计日志 |
| `/api/v1/audit/logs/export` | GET | 导出审计日志 |
| `/api/v1/audit/logs/{id}` | GET | 获取单条审计详情 |

### 4.5 启动检查

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/startup/check` | POST | 执行启动健康检查 |
| `/api/v1/startup/report` | GET | 获取最近检查报告 |

---

## 五、快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py

# 健康检查
curl http://localhost:8010/health

# M8 标准健康检查（带 Token）
curl -H "X-M8-Token: yunxi-m10-admin-token-2026" http://localhost:8010/m8/health

# API 文档
http://localhost:8010/docs
```

---

## 六、测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行单个测试
pytest tests/test_monitor.py -v
```

---

## 七、与其他模块关系

```
                    ┌─────────────┐
                    │   M8 管理台  │
                    └──────┬──────┘
                           │ 纳管/监控
                    ┌──────▼──────┐
                    │ M10 系统卫士 │
                    └──────┬──────┘
         ┌─────────────────┼─────────────────┐
    ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
    │ M1-M9  │       │  操作系统  │       │  审计日志 │
    │ 各模块  │       │ (资源/进程)│       │  (存储)   │
    └─────────┘       └─────────┘       └─────────┘
```

- **上游**：M8 管理台通过 M8 标准接口调用 M10 获取系统状态
- **下游**：M10 监控 M1-M9 所有模块的进程和资源使用情况
