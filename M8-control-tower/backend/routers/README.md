# M8 控制塔路由包

M8 控制塔的所有 API 路由按业务域拆分到子目录中。

## 目录结构

```
routers/
├── __init__.py          # 包入口，统一导出所有路由
├── README.md             # 本文档
│
├── core/                 # 核心控制（6 个路由）
│   ├── __init__.py
│   ├── modules.py        # 模块管理（63 个端点）
│   ├── system.py         # 系统管理
│   ├── deploy.py         # 部署中心
│   ├── modes.py          # 模式管理
│   ├── registry.py       # 服务注册中心
│   └── m4_gateway.py     # M4 代理网关
│
├── compute/              # 算力调度中台（8 个路由）
│   ├── __init__.py
│   ├── compute_sources.py   # 算力源管理
│   ├── compute_gpu.py      # GPU 算力管理
│   ├── compute_groups.py   # 密钥分组
│   ├── compute_models.py   # 模型绑定
│   ├── compute_routing.py  # 路由调度
│   ├── compute_monitor.py  # 监控大盘
│   ├── compute_config.py   # 配置管理
│   └── compute_skills.py   # 技能绑定
│
├── ops/                  # 运维监控（5 个路由）
│   ├── __init__.py
│   ├── monitor.py          # 监控中心
│   ├── ops_dashboard.py    # 运维仪表盘
│   ├── performance.py      # 性能监控
│   ├── inspection_agents.py # 巡检 Agent
│   └── git_status.py     # Git 状态看板
│
├── security/           # 安全管理（4 个路由）
│   ├── __init__.py
│   ├── auth.py           # 认证
│   ├── users.py          # 用户管理
│   ├── security.py       # 安全管理
│   └── audit.py          # 审计日志
│
├── config/             # 配置管理（2 个路由）
│   ├── __init__.py
│   ├── config_center.py  # 配置中心
│   └── i18n.py            # 国际化
│
├── data/               # 数据服务（2 个路由）
│   ├── __init__.py
│   ├── backup_scheduler.py # 备份调度中心
│   └── data_access.py    # 数据访问层
│
└── business/           # 业务服务（23 个路由）
    ├── __init__.py
    ├── growth_m5_proxy.py  # 成长中心（M5 代理）
    ├── work_dev.py      # 工作开发
    ├── review.py          # 复盘总结
    ├── study_plan.py      # 学业规划
    ├── life_management.py # 生活管理
    ├── emotion_comfort.py  # 情绪陪伴
    ├── social_relation.py  # 人际关系
    ├── appearance.py       # 形象工坊（M4 代理）
    ├── chat.py            # 云汐聊天（M4 代理）
    ├── memory.py       # 潮汐记忆（M5 代理）
    ├── brain.py           # 云汐大脑
    ├── personalization.py  # 个性化设置
    ├── reminders.py     # 主动提醒
    ├── agents.py       # Agent 管理
    ├── task.py            # 汐舷任务
    ├── workflow.py     # 积木平台
    ├── evolution_planner.py   # 自进化-规划器
    ├── evolution_deployer.py  # 自进化-部署治理
    ├── evolution_auditor.py   # 自进化-安全审计
    ├── voice.py           # 语音服务
    ├── voice_presets.py  # 音色管理
    ├── m6_devices.py    # M6 穿戴设备
    └── watch.py           # 手表交互
```

**路由总数：50 个

## 向后兼容

**阶段 0（当前阶段）**：顶层旧路径（`routers.xxx` 仍然有效，但会发出 `DeprecationWarning`。

### 保留的存根文件：

| 旧路径 | 新路径 | 状态 | 保留原因 |
|--------|--------|------|----------|
| `routers.audit` | `routers.security.audit` | 存根 | 已有存根，向后兼容 |
| `routers.compute_sources` | `routers.compute.compute_sources` | 存根 | 已有存根，向后兼容 |
| `routers.system` | `routers.core.system` | 存根 | 被 ops_status_aggregator 引用 |
| `routers.monitor` | `routers.ops.monitor` | 存根 | 被 health_service 和测试引用 |
| `routers.backup_scheduler` | `routers.data.backup_scheduler` | 存根 | 被测试引用 |

### 迁移指南

**模块开发时，请使用新的导入路径：**

```python
# 旧写法（已废弃，会发出 DeprecationWarning）
from routers.system import router, get_module_actions

# 新写法（推荐）
from routers.core.system import router, get_module_actions
```

**路由注册方式不变**：`router_config.py` 已切换为从子目录导入，应用启动时路由注册不受影响。

## 废弃时间表

| 阶段 | 时间 | 内容 |
|------|------|------|
| 阶段 0 | 当前 | 双重结构清理，顶层保留存根，发出 DeprecationWarning |
| 阶段 1 | 未来 | 逐步将所有外部引用迁移到新路径 |
| 阶段 2 | 远期 | 移除顶层存根文件 |

## 职责划分

### core（核心控制）
系统级别的核心功能，包括模块生命周期管理、系统配置、部署管理等。

### compute（算力调度中台）
M8-CS 算力调度系统，管理算力源、模型、路由等。

### ops（运维监控）
系统运维相关功能，包括监控、性能、巡检、Git 状态等。

### security（安全管理）
认证、授权、审计等安全相关功能。

### config（配置管理）
系统配置和国际化。

### data（数据服务）
数据访问层和备份调度。

### business（业务服务）
面向用户的业务功能，包括聊天、Agent、语音、设备、自进化等。

## 开发规范

1. 新增路由时，按业务域放入对应子目录
2. 在子目录的 `__init__.py` 中导出 `xxx_router`
3. 在顶层 `__init__.py` 中统一导出
4. 在 `router_config.py` 中注册路由
5. 如需跨子域调用，使用相对导入（`from ..other_subdir.module import ...`）
