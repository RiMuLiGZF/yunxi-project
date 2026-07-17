# M8 Router 迁移状态清单（ARC-002 第一阶段）

## 概述
本文件记录 M8-control-tower 中各业务 router 的迁移状态。
已迁移到其他模块（M4/M5/M9）的 router 在 M8 中保留为代理占位，
实际业务逻辑由目标模块处理。

## 迁移状态总览

| Router 文件 | 业务名称 | 目标模块 | 迁移状态 | 本地端点 | 代理方式 |
|------------|---------|---------|---------|---------|---------|
| `appearance.py` | 形象工坊 | M4 | ✅ 已完成迁移 | 2 (health + proxy-info) | m4_proxy_middleware |
| `emotion_comfort.py` | 情绪陪伴 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `social_relation.py` | 人际关系 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `life_management.py` | 生活管理 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `study_plan.py` | 学业规划 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `review.py` | 复盘总结 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `chat.py` | 聊天服务 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `watch.py` | 手表交互 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `voice.py` | 语音服务 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `voice_presets.py` | 音色管理 | M4 | ✅ 已完成迁移 | 1 (health) | m4_proxy_middleware |
| `work_dev.py` | 工作开发 | M9 | ✅ 已完成迁移 | 多（路由级代理） | 路由级 httpx 代理 |
| `growth_m5_proxy.py` | 成长中心 | M5 | ✅ 已完成迁移 | 多（路由级代理） | 路由级 httpx 代理 |
| `memory.py` | 潮汐记忆 | M5 | ✅ 已完成迁移 | 多（ModuleClient 代理） | ModuleClient 代理 |
| `m4_gateway.py` | M4代理网关 | M4 | - | 多 | 显式代理网关 |

## 正常业务 Router（未迁移）

以下 router 为 M8 核心业务，不迁移：

| Router 文件 | 业务名称 | 说明 |
|------------|---------|------|
| `auth.py` | 认证 | M8 自身认证 |
| `users.py` | 用户管理 | M8 用户管理 |
| `system.py` | 系统管理 | M8 系统配置 |
| `deploy.py` | 部署中心 | 模块部署管理 |
| `monitor.py` | 监控中心 | 系统监控 |
| `modules.py` | 模块管理 | 模块注册与管理 |
| `audit.py` | 审计日志 | 审计功能 |
| `security.py` | 安全管理 | 安全配置 |
| `modes.py` | 模式管理 | 业务模式切换 |
| `agents.py` | Agent管理 | Agent 联邦调度 |
| `task.py` | 汐舷-任务 | 任务管理 |
| `workflow.py` | 积木平台 | 工作流 |
| `brain.py` | 云汐大脑 | 知识库等 |
| `personalization.py` | 个性化设置 | 用户个性化 |
| `reminders.py` | 主动提醒 | 提醒服务 |
| `backup_scheduler.py` | 备份调度中心 | 备份管理 |
| `git_status.py` | Git状态看板 | Git 信息 |
| `m6_devices.py` | M6穿戴设备 | 设备管理 |
| `compute_*.py` (8个) | 算力调度中台 | M8-CS 算力管理 |
| `evolution_*.py` (3个) | 自进化 | 自进化系统 |
| `inspection_agents.py` | 巡检Agent | 巡检功能 |

## 代理方式说明

### 1. m4_proxy_middleware（中间件级代理）
- 适用：已迁移到 M4 的业务模式类 router
- 特点：在中间件层拦截请求并转发，router 文件仅保留健康检查端点
- 优点：代码最精简，无需每个 router 写代理逻辑
- 对应 router：appearance, emotion_comfort, social_relation, life_management,
  study_plan, review, chat, watch, voice, voice_presets

### 2. 路由级 httpx 代理
- 适用：迁移到 M5/M9 等非 M4 模块的业务
- 特点：router 文件中定义端点，内部用 httpx 转发到目标模块
- 优点：灵活，可定制请求/响应转换
- 对应 router：work_dev.py, growth_m5_proxy.py

### 3. ModuleClient 代理
- 适用：通过模块注册中心调用的业务
- 特点：使用 ModuleRegistry / ModuleClient 进行服务发现和调用
- 对应 router：memory.py

## 回滚方式

如需将某业务从代理模式回滚到 M8 本地实现：
1. 从 `_archive/m8_migrated/routers/` 目录恢复原 router 文件
2. 关闭对应模块的 m4_proxy_middleware 开关（如适用）
3. 重启 M8 服务

## 后续计划（第二阶段）

- [ ] 移除已迁移 router 的占位文件，完全由 m4_proxy_middleware 处理
- [ ] 统一所有代理方式为中间件级代理
- [ ] 清理 M8 中与已迁移业务相关的 model/repository 代码
