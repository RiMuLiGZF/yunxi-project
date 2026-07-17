# 云汐系统运维手册

> **版本**：v1.0（第四阶段 · 生产就绪）
> **更新时间**：2026-07-17
> **文档类型**：运维手册 · 适用范围：全系统运维

---

## 目录

- [1. 系统要求](#1-系统要求)
- [2. 日常运维清单](#2-日常运维清单)
- [3. 监控指标说明](#3-监控指标说明)
- [4. 备份策略与操作](#4-备份策略与操作)
- [5. 升级流程](#5-升级流程)
- [6. 回滚流程](#6-回滚流程)
- [7. 常见故障排查](#7-常见故障排查)
- [8. 性能调优指南](#8-性能调优指南)
- [9. 服务管理](#9-服务管理)
  - [9.1 启动服务](#91-启动服务)
  - [9.2 停止服务](#92-停止服务)
  - [9.3 服务状态检查](#93-服务状态检查)
  - [9.4 日志管理](#94-日志管理)
    - [9.4.1 日志轮转机制（OP-006）](#941-日志轮转机制op-006)
    - [9.4.2 日志清理工具](#942-日志清理工具)
    - [9.4.3 各模块日志接入](#943-各模块日志接入)
  - [9.5 进程管理](#95-进程管理)
- [10. 安全运维](#10-安全运维)

---

## 1. 系统要求

### 1.1 硬件要求

| 配置等级 | CPU | 内存 | 磁盘 | GPU | 适用场景 |
|---------|-----|------|------|-----|---------|
| 最低配置 | 4 核 | 8 GB | 50 GB SSD | - | 开发测试、单用户轻量使用 |
| 推荐配置 | 8 核 | 16 GB | 100 GB SSD | - | 个人生产使用、常规 AI 任务 |
| 高性能 | 16 核 | 32 GB+ | 500 GB SSD | 8GB+ 显存 | 本地大模型、高并发、多用户 |

> **注意**：使用本地大模型（Ollama）时，GPU 显存需满足模型大小要求（7B 模型约需 8GB，13B 约需 16GB）。

### 1.2 软件要求

| 组件 | 最低版本 | 推荐版本 | 说明 |
|-----|---------|---------|------|
| Python | 3.10 | 3.11 / 3.12 | 运行各模块服务 |
| Git | 2.30 | 最新 | 版本管理和升级 |
| Node.js | 18.x | 20.x LTS | 前端构建（可选） |
| Docker | 20.10 | 24.x+ | Docker 部署（可选） |
| Ollama | 0.1.0 | 最新 | 本地 LLM 推理（可选） |

### 1.3 端口分配

| 端口 | 服务 | 对外暴露 | 说明 |
|-----|------|---------|------|
| 8080 | API Gateway | 是 | 统一接入层 |
| 8000 | M0 主理人管控台 | 可选 | 最高权限管控台 |
| 8001 | M1 Agent 集群 | 否 | 多 Agent 调度 |
| 8002 | M2 技能集群 | 否 | 技能服务 |
| 8003 | M3 端云协同 | 否 | 端云同步 |
| 8004 | M4 场景引擎 | 否 | 场景编排 |
| 8005 | M5 潮汐记忆 | 否 | 记忆系统（私有） |
| 8006 | M6 硬件外设 | 否 | 硬件接口 |
| 8007 | M7 积木平台 | 否 | 工作流构建 |
| 8008 | M8 控制塔 | 可选 | 管理后台 |
| 8009 | M9 开发工坊 | 否 | 代码生成 |
| 8010 | M10 系统卫士 | 否 | 系统监控 |
| 8011 | M11 MCP 总线 | 否 | MCP 服务 |
| 8012 | M12 安全盾 | 否 | 安全防护 |

> **生产环境建议**：仅暴露 8080（API Gateway），内部服务通过内网访问。

---

## 2. 日常运维清单

### 2.1 每日检查

| 序号 | 检查项 | 操作命令 | 判定标准 | 频率 |
|------|--------|---------|---------|------|
| 1 | 系统健康检查 | `.\scripts\health-check.ps1` | 退出码 = 0 | 每日 |
| 2 | 错误日志检查 | `.\scripts\logs.ps1 -Level error -Since "24h"` | 无新增 ERROR | 每日 |
| 3 | 磁盘空间 | `Get-PSDrive C` (Windows) / `df -h` (Linux) | 剩余 > 20% | 每日 |
| 4 | 内存使用 | M10 系统卫士 / `.\scripts\monitor.ps1 -Once` | 使用率 < 80% | 每日 |
| 5 | CPU 使用 | M10 系统卫士 / `.\scripts\monitor.ps1 -Once` | 使用率 < 80% | 每日 |
| 6 | 备份状态 | M8 备份管理页面 / `.\scripts\verify-backup.ps1 -All` | 备份成功 | 每日 |
| 7 | 安全审计 | M12 安全盾审计日志 | 无异常告警 | 每日 |

**操作命令汇总**：
```powershell
# 一键执行每日检查
.\scripts\health-check.ps1
.\scripts\logs.ps1 -Level error -Since "24h"
.\scripts\monitor.ps1 -Once -Brief
```

### 2.2 每周检查

| 序号 | 检查项 | 操作 | 判定标准 | 频率 |
|------|--------|------|---------|------|
| 1 | 备份验证 | `.\scripts\verify-backup.ps1 -All -TestRestore` | 验证通过率 100% | 每周 |
| 2 | 性能趋势分析 | 查看 M8 监控中心一周数据 | 无持续性能下降 | 每周 |
| 3 | 安全更新 | 检查依赖安全公告 | 无高危漏洞 | 每周 |
| 4 | 日志清理 | 清理超过 30 天的旧日志 | 磁盘空间正常 | 每周 |
| 5 | 告警回顾 | 回顾本周所有告警 | 均已处理 | 每周 |

### 2.3 每月检查

| 序号 | 检查项 | 操作 | 判定标准 | 频率 |
|------|--------|------|---------|------|
| 1 | 数据库完整性 | SQLite `PRAGMA integrity_check` | 全部通过 | 每月 |
| 2 | 安全审计 | 全面安全审计 | 无 P1/P0 漏洞 | 每月 |
| 3 | 恢复演练 | 单模块恢复演练 | RTO 达标 | 每月 |
| 4 | 容量规划 | 分析资源使用趋势 | 无容量风险 | 每月 |
| 5 | 文档更新 | 更新运维文档 | 与实际一致 | 每月 |

### 2.4 巡检自动化

可将日常检查脚本加入定时任务（Windows 任务计划 / Linux cron）：

```powershell
# Windows 任务计划示例：每日凌晨 6 点执行健康检查
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-File C:\yunxi-project\scripts\health-check.ps1 -OutputFormat brief"
$trigger = New-ScheduledTaskTrigger -Daily -At 6am
Register-ScheduledTask -TaskName "YunxiDailyCheck" -Action $action -Trigger $trigger
```

---

## 3. 监控指标说明

### 3.1 系统级指标

| 指标 | 警告阈值 | 严重阈值 | 告警级别 | 建议处理 |
|------|---------|---------|---------|---------|
| CPU 使用率 | >= 80% | >= 95% | 警告/严重 | 扩容或优化代码 |
| 内存使用率 | >= 80% | >= 90% | 警告/严重 | 扩容或排查内存泄漏 |
| 磁盘使用率 | >= 80% | >= 90% | 警告/严重 | 清理空间或扩容 |
| 磁盘 IO 等待 | >= 20% | >= 50% | 警告/严重 | 排查 IO 瓶颈 |
| 网络带宽 | >= 70% | >= 90% | 警告/严重 | 扩容或限流 |
| GPU 利用率 | >= 90% | >= 99% | 警告/严重 | 优化或增加 GPU |
| GPU 显存 | >= 85% | >= 95% | 警告/严重 | 释放显存或换大模型 |

### 3.2 服务级指标

| 指标 | 警告阈值 | 严重阈值 | 告警级别 | 说明 |
|------|---------|---------|---------|------|
| 响应时间（P95） | >= 1s | >= 3s | 警告/严重 | 接口响应耗时 |
| 错误率 | >= 5% | >= 20% | 警告/严重 | 5xx 错误占比 |
| QPS | > 容量 80% | > 容量 95% | 警告/严重 | 请求量接近上限 |
| 服务可用性 | < 99.9% | < 99% | 警告/严重 | 服务正常运行时间比例 |
| 活跃连接数 | > 上限 80% | > 上限 95% | 警告/严重 | 并发连接数 |

### 3.3 模块级指标

各模块通过 `/m8/metrics` 接口暴露运行指标：

| 指标 | 说明 |
|------|------|
| `qps` | 每秒请求数 |
| `avg_latency_ms` | 平均响应延迟（毫秒） |
| `p99_latency_ms` | P99 响应延迟（毫秒） |
| `error_rate` | 错误率 |
| `requests_total` | 总请求数 |
| `active_connections` | 活跃连接数 |

### 3.4 业务指标

| 指标 | 说明 | 监控方式 |
|------|------|---------|
| 日活用户数 | 每日活跃用户 | M8 统计中心 |
| 消息量 | 每日聊天消息数 | M8 统计中心 |
| 技能调用量 | 每日技能调用次数 | M2 统计 |
| 工作流执行量 | 每日工作流执行次数 | M7 统计 |
| API 调用量 | 每日 API 总调用数 | 网关统计 |
| 平均响应时间 | 全局平均响应时间 | 网关统计 |

### 3.5 告警级别定义

| 级别 | 响应时间 | 通知方式 | 示例 |
|------|---------|---------|------|
| P0 紧急 | 立即（15 分钟内） | 电话 + 短信 + 邮件 | 全系统不可用、数据丢失 |
| P1 严重 | 1 小时内 | 短信 + 邮件 | 核心模块故障、安全漏洞 |
| P2 警告 | 4 小时内 | 邮件 + 控制台 | 资源使用率高、非核心模块故障 |
| P3 通知 | 24 小时内 | 控制台 | 备份成功、例行通知 |

---

## 4. 备份策略与操作

### 4.1 备份策略

#### 4.1.1 备份类型

| 类型 | 定义 | 频率 | 保留周期 | 适用模块 |
|------|------|------|---------|---------|
| 全量备份 | 备份所有数据的完整副本 | 每日 02:00-05:00 | 30 天 | 所有模块 |
| 增量备份 | 备份自上次备份以来的变化 | 每 6 小时 | 7 天 | M5 潮汐记忆 |
| 差异备份 | 备份自上次全量备份以来的变化 | 每日中午 12:00 | 7 天 | M5、M8 |

#### 4.1.2 备份时间表

| 模块 | 全量备份时间 | 增量备份 | 压缩 | 加密 | 保留策略 |
|------|-------------|---------|------|------|---------|
| M8 控制塔 | 每日 02:00 | 不启用 | gzip | 可选 | 50 个 / 60 天 / 5GB |
| M5 潮汐记忆 | 每日 03:30 | 每 6 小时 | gzip | 可选 | 30 个 / 45 天 / 10GB |
| M12 安全盾 | 每日 05:00 | 不启用 | gzip | 启用 | 30 个 / 90 天 / 2GB |
| M4 场景引擎 | 每日 03:00 | 不启用 | gzip | 可选 | 30 个 / 30 天 / 5GB |
| M9 开发工坊 | 每日 03:00 | 不启用 | gzip | 可选 | 30 个 / 30 天 / 5GB |
| M10 系统卫士 | 每日 04:30 | 不启用 | gzip | 可选 | 30 个 / 30 天 / 3GB |
| M6 硬件外设 | 每日 04:00 | 不启用 | gzip | 可选 | 20 个 / 20 天 |

### 4.2 备份操作

#### 4.2.1 手动备份

```powershell
# 备份所有模块
python shared/data/data_layer/backup.py backup --all

# 备份指定模块
python shared/data/data_layer/backup.py backup --module m8

# 增量备份（仅 M5）
python shared/data/data_layer/backup.py backup --module m5 --type incremental

# 查看备份列表
python shared/data/data_layer/backup.py list --module m8

# 查看备份状态
python shared/data/data_layer/backup.py status
```

#### 4.2.2 备份验证

```powershell
# 验证指定模块的最新备份
.\scripts\verify-backup.ps1 -Module m8

# 验证所有模块
.\scripts\verify-backup.ps1 -All

# 验证并测试恢复（更全面）
.\scripts\verify-backup.ps1 -All -TestRestore

# 自动验证模式（适合定时任务）
.\scripts\verify-backup.ps1 -All -AutoVerify -ReportPath .\backup_report.json
```

#### 4.2.3 备份清理

```powershell
# 清理超过 30 天的旧备份
python shared/data/data_layer/backup.py clean --max-age 30

# 清理超过最大数量的备份
python shared/data/data_layer/backup.py clean --max-count 50
```

### 4.3 备份存储

- **存储位置**：`backups/module_backups/{module_id}/`
- **命名格式**：`{module_id}_{backup_type}_{timestamp}/`
- **元数据文件**：`backup_manifest.json`、`*.meta.json`
- **校验算法**：SHA-256
- **压缩算法**：gzip level 6
- **加密算法**：AES-256-GCM（可选）

### 4.4 备份监控

| 监控项 | 告警阈值 | 告警级别 |
|--------|---------|---------|
| 备份失败 | 连续 1 次失败 | 严重 |
| 备份空间使用率 | > 80% | 警告 |
| 备份空间使用率 | > 90% | 严重 |
| 备份过期 | 超过 RPO 时间未备份 | 警告 |
| 备份文件损坏 | 验证失败 | 严重 |

---

## 5. 升级流程

### 5.1 升级前检查清单

升级前必须确认以下事项：

- [ ] 查看当前版本：`git log --oneline -5`
- [ ] 查看版本更新说明（CHANGELOG）
- [ ] 确认有可用的备份
- [ ] 确认磁盘空间充足（至少剩余 5GB）
- [ ] 通知相关用户预计停机时间
- [ ] 试运行升级：`.\upgrade.ps1 -DryRun`

### 5.2 标准升级流程

```powershell
# 第 1 步：试运行升级（推荐）
.\upgrade.ps1 -DryRun

# 第 2 步：执行升级
.\upgrade.ps1

# 第 3 步：验证升级结果
.\scripts\health-check.ps1

# 第 4 步：验证核心功能
# - 登录测试
# - 聊天功能测试
# - 各模块健康检查
```

### 5.3 升级脚本自动执行步骤

`upgrade.ps1` 脚本自动执行以下步骤：

1. **升级前环境检查** — 验证 Python 版本、依赖、磁盘空间
2. **全量备份** — 备份代码、配置、数据（升级安全网）
3. **Git 拉取最新代码** — 拉取目标版本
4. **依赖更新** — 更新 Python 包依赖
5. **数据库迁移** — 执行数据库 schema 迁移
6. **滚动重启服务** — 按顺序重启各模块
7. **健康检查验证** — 验证所有模块正常运行
8. **失败自动回滚** — 升级失败自动恢复到升级前状态

### 5.4 升级参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-TargetCommit` | 升级到指定 commit | 最新 commit |
| `-Branch` | 指定分支 | 当前分支 |
| `-BackupDir` | 自定义备份目录 | `backup/` |
| `-SkipBackup` | 跳过备份（不推荐） | false |
| `-SkipRollback` | 失败时不自动回滚 | false |
| `-DryRun` | 试运行模式 | false |

### 5.5 大版本升级注意事项

- 主版本升级（如 v0.9.x → v1.0.0）可能包含破坏性变更
- 升级前务必阅读版本更新说明
- 建议在测试环境先验证
- 数据量大的模块升级时预留足够时间
- 升级期间建议暂停非关键业务

---

## 6. 回滚流程

### 6.1 回滚触发条件

以下情况需要执行回滚：

- 升级后核心功能不可用
- 数据异常或数据丢失
- 安全漏洞或安全风险
- 性能严重下降
- 升级脚本报错且无法自动修复

### 6.2 自动回滚

升级脚本内置自动回滚机制：

- 升级失败时自动触发回滚
- 回滚到升级前的备份状态
- 回滚完成后自动健康检查
- 回滚结果通过日志输出

### 6.3 手动回滚

自动回滚失败时，使用以下命令手动回滚：

```powershell
# 查看可用备份
.\rollback.ps1 -ListBackups

# 从指定备份回滚
.\rollback.ps1 -BackupPath .\backup\yunxi_backup_20260717_020000

# 回滚到指定 commit
.\rollback.ps1 -TargetCommit abc1234

# 自动选择最近的备份回滚
.\rollback.ps1
```

### 6.4 手动回滚详细步骤

如果回滚脚本也失败，按以下步骤手动操作：

```powershell
# 第 1 步：停止所有服务
.\scripts\stop-all.ps1

# 第 2 步：恢复代码版本
git checkout <previous-commit-hash>

# 第 3 步：恢复配置文件
Copy-Item .\backup\yunxi_backup_xxx\config\* .\config\ -Recurse -Force

# 第 4 步：恢复数据
Copy-Item .\backup\yunxi_backup_xxx\data\* .\data\ -Recurse -Force

# 第 5 步：恢复依赖（如版本有变化）
pip install -r requirements.txt

# 第 6 步：重新启动
.\scripts\start-all.ps1

# 第 7 步：验证
.\scripts\health-check.ps1
```

### 6.5 回滚验证

回滚完成后必须验证：

- [ ] 所有模块健康检查通过
- [ ] 核心功能正常（登录、聊天、数据查询）
- [ ] 数据完整性验证
- [ ] 无新增错误日志
- [ ] 用户数据完整无损

---

## 7. 常见故障排查

### 7.1 服务无法启动

**症状**：模块启动后立即退出或健康检查失败

**排查步骤**：

```powershell
# 1. 查看错误日志
.\scripts\logs.ps1 -Module M1 -Level error

# 2. 检查端口是否被占用
Get-NetTCPConnection -LocalPort 8001 -State Listen  # Windows
# ss -tlnp | grep 8001  # Linux

# 3. 检查配置文件
# 确认 config/yunxi.env 中相关配置正确

# 4. 手动启动查看详细错误
cd M1-agent-hub
python server.py
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| 端口被占用 | 更换端口或停止占用进程 |
| 依赖缺失 | `pip install -r requirements.txt` |
| 配置错误 | 检查配置文件格式和值 |
| 权限不足 | 以管理员身份运行 |
| Python 版本不对 | 使用 Python 3.10+ |

---

### 7.2 数据库错误

**症状**：数据库相关报错，如 "database disk image is malformed"

**排查步骤**：

```powershell
# 1. 检查数据目录是否存在
Test-Path .\data

# 2. 检查数据库文件
Get-ChildItem .\data -Filter *.db

# 3. 检查磁盘空间
Get-PSDrive C

# 4. 验证数据库完整性
python -c "import sqlite3; conn = sqlite3.connect('data/m8.db'); print(conn.execute('PRAGMA integrity_check').fetchone())"
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| 数据目录不存在 | 手动创建 `data` 目录 |
| 权限问题 | 确保服务账户有读写权限 |
| 数据库损坏 | 从备份恢复 |
| 磁盘满 | 清理磁盘空间 |

---

### 7.3 认证失败

**症状**：登录失败、API 调用返回 401

**排查步骤**：

```powershell
# 1. 检查 Token 是否过期
# 查看 JWT Token 的 exp 字段

# 2. 检查用户是否存在
# 通过 M8 管理后台查看用户状态

# 3. 检查 JWT 密钥配置
# 确认 JWT_SECRET 配置正确

# 4. 检查时间同步
# JWT 验证依赖系统时间，确保时间准确
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| Token 过期 | 使用 refresh_token 刷新 |
| 用户名或密码错误 | 重置密码 |
| JWT 密钥不匹配 | 检查并统一 JWT_SECRET 配置 |
| 系统时间不同步 | 同步系统时间 |
| 账号被锁定 | 等待解锁或管理员解锁 |

---

### 7.4 性能问题（响应慢）

**症状**：系统响应缓慢，接口超时

**排查步骤**：

```powershell
# 1. 查看系统资源
.\scripts\monitor.ps1 -Once

# 2. 查看慢请求日志
.\scripts\logs.ps1 -Keyword "slow"

# 3. 查看错误和警告日志
.\scripts\logs.ps1 -Level warning -Since "1h"

# 4. 检查大模型响应时间
# 查看 LLM 调用耗时
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| CPU/内存不足 | 升级硬件或优化代码 |
| 数据库慢查询 | 添加索引、优化查询 |
| 大模型响应慢 | 检查模型配置和网络 |
| 网络延迟 | 检查网络连接 |
| 并发量过高 | 限流或扩容 |

---

### 7.5 模块间调用失败

**症状**：模块间 HTTP 调用失败、超时

**排查步骤**：

```powershell
# 1. 检查目标模块是否运行
.\scripts\health-check.ps1 -Module M5

# 2. 检查网络连通性
Test-NetConnection localhost -Port 8005  # Windows

# 3. 检查 Module Token 配置
# 确认模块间的 Token 配置正确

# 4. 检查防火墙
# 确认内部端口未被防火墙拦截
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| 目标模块未启动 | 启动目标模块 |
| 网络不通 | 检查防火墙和网络配置 |
| Token 无效 | 检查并更新 Module Token |
| 超时时间过短 | 调整超时配置 |
| 目标模块过载 | 等待或扩容 |

---

### 7.6 备份失败

**症状**：备份任务执行失败

**排查步骤**：

```powershell
# 1. 查看备份日志
Get-Content .\logs\backup.log -Tail 50

# 2. 检查磁盘空间
Get-PSDrive C

# 3. 检查备份目录权限
# 确认服务账户对备份目录有写入权限

# 4. 手动测试备份
python shared/data/data_layer/backup.py backup --module m8
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| 磁盘空间不足 | 清理空间或扩容 |
| 权限不足 | 设置正确的目录权限 |
| 数据库被锁定 | 等待或使用热备份模式 |
| 备份目录不存在 | 创建备份目录 |

---

### 7.7 升级失败

**症状**：升级过程中报错，升级后服务异常

**处理方法**：

1. 升级脚本会自动回滚，等待回滚完成
2. 如果自动回滚失败，手动执行回滚：`.\rollback.ps1`
3. 查看升级日志，定位失败原因
4. 修复问题后重新尝试升级

**常见失败原因**：

| 原因 | 解决方案 |
|------|---------|
| 网络问题导致代码拉取失败 | 检查网络，重试 |
| 依赖安装失败 | 手动安装依赖后重试 |
| 数据库迁移失败 | 查看迁移日志，修复数据 |
| 磁盘空间不足 | 清理空间后重试 |
| 配置文件冲突 | 手动合并配置 |

---

### 7.8 安全告警

**症状**：M12 安全盾触发告警

**排查步骤**：

```powershell
# 1. 查看安全审计日志
# M12 安全盾管理界面 → 审计日志

# 2. 查看 WAF 拦截统计
# M12 安全盾管理界面 → WAF 统计

# 3. 检查 IP 黑名单
# M12 安全盾管理界面 → IP 管理
```

**常见告警及处理**：

| 告警类型 | 处理方式 |
|---------|---------|
| SQL 注入尝试 | 拦截并加入 IP 黑名单 |
| XSS 攻击尝试 | 拦截并记录 |
| 暴力破解登录 | 自动锁定账号和 IP |
| 速率超限 | 自动限流，检查是否正常业务 |
| 异常 API Key 使用 | 吊销异常 Key 并调查 |

---

### 7.9 内存泄漏

**症状**：内存使用持续增长，不释放

**排查步骤**：

```powershell
# 1. 监控内存趋势
.\scripts\monitor.ps1 -Duration 300 -OutputFile memory_report.csv

# 2. 查看各进程内存占用
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10

# 3. 重启可疑模块
# 观察重启后内存是否恢复正常
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| Python 内存泄漏 | 重启模块，定位泄漏代码 |
| 缓存未清理 | 限制缓存大小，设置过期时间 |
| 大模型加载 | 卸载不用的模型 |
| 连接未释放 | 检查数据库连接和 HTTP 连接池 |

---

### 7.10 磁盘空间不足

**症状**：磁盘使用率超过 90%

**清理步骤**：

```powershell
# 1. 查看磁盘使用情况
Get-PSDrive C

# 2. 清理旧日志
# 保留最近 30 天日志
Get-ChildItem .\logs -Recurse | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item

# 3. 清理旧备份
python shared/data/data_layer/backup.py clean --max-age 30

# 4. 清理临时文件
Remove-Item .\temp\* -Recurse -Force -ErrorAction SilentlyContinue

# 5. 清理 Python 缓存
Get-ChildItem -Path . -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force
```

---

### 7.11 大模型调用失败

**症状**：AI 功能不可用，LLM 调用报错

**排查步骤**：

```powershell
# 1. 检查 LLM Provider 配置
# 查看 config/yunxi.env 中的 LLM 配置

# 2. 检查网络连接（云端模型）
Test-NetConnection api.deepseek.com -Port 443

# 3. 检查 Ollama 状态（本地模型）
ollama list

# 4. 测试 LLM 调用
python -c "from shared.core.llm_client import get_llm_client; print(get_llm_client().chat('你好'))"
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| API Key 无效 | 更新 API Key |
| 网络不通 | 检查网络或切换到本地模型 |
| 本地模型未下载 | `ollama pull <model-name>` |
| 模型服务未启动 | 启动 Ollama 服务 |
| 配额不足 | 升级套餐或切换模型 |

---

### 7.12 GPU 相关问题

**症状**：GPU 使用率异常、显存不足

**排查步骤**：

```powershell
# 1. 检查 GPU 状态
nvidia-smi

# 2. 查看 M10 系统卫士 GPU 监控
# M10 监控页面 → GPU 状态

# 3. 检查显存占用
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
```

**常见原因及解决**：

| 原因 | 解决方案 |
|------|---------|
| 显存不足 | 卸载不用的模型、使用更小的模型 |
| GPU 利用率低 | 检查任务是否正常调度 |
| 驱动问题 | 更新 NVIDIA 驱动 |
| 模型加载失败 | 检查模型文件完整性 |

---

## 8. 性能调优指南

### 8.1 系统级调优

| 调优项 | 建议值 | 说明 |
|--------|-------|------|
| 文件描述符 | 65535 | Linux 系统调优 |
| TCP 连接数 | 65535 | 高并发场景 |
| 内存分配 | 按需 | 避免 OOM |
| 磁盘调度 | noop / deadline | SSD 优化 |

### 8.2 应用级调优

#### 8.2.1 数据库调优

```python
# SQLite 调优建议
# 1. 使用 WAL 模式（写入性能提升）
PRAGMA journal_mode = WAL;

# 2. 调整缓存大小
PRAGMA cache_size = -20000;  # 20MB 缓存

# 3. 同步模式（性能优先，可接受少量数据丢失风险）
PRAGMA synchronous = NORMAL;
```

#### 8.2.2 缓存策略

| 缓存层级 | 位置 | 用途 | 建议大小 |
|---------|------|------|---------|
| L1 内存缓存 | 进程内 | 热点数据 | 100-500 MB |
| L2 本地缓存 | SQLite/文件 | 会话数据 | 1-5 GB |
| L3 向量缓存 | FAISS | 向量检索 | 视数据量而定 |

#### 8.2.3 LLM 调用优化

- **批处理**：将多个小请求合并批量处理
- **缓存结果**：相同问题直接返回缓存结果
- **流式输出**：使用 SSE 流式输出，减少首字延迟
- **模型路由**：简单问题用小模型，复杂问题用大模型
- **并发控制**：限制同时进行的 LLM 调用数

### 8.3 模块级调优

#### M1 Agent 集群
- 调整 Agent 池大小，避免过多并发
- 设置合理的超时时间
- 启用结果缓存

#### M5 潮汐记忆
- 控制记忆总量，定期清理
- 向量检索使用合适的索引类型
- 记忆巩固在低峰期执行

#### M11 MCP 总线
- 复用 MCP 连接，避免频繁建连
- 设置工具调用超时
- 启用工具结果缓存

### 8.4 性能监控与分析

```powershell
# 监控 5 分钟并生成报告
.\scripts\monitor.ps1 -Duration 300 -OutputFile performance_report.csv

# 分析慢查询
# 开启数据库慢查询日志
```

### 8.5 性能基准

建议定期执行性能基准测试，跟踪性能变化：

| 指标 | 基准值 | 测试方法 |
|------|-------|---------|
| 登录接口响应 | < 100ms | 压测工具 |
| 健康检查响应 | < 50ms | 压测工具 |
| 聊天首字延迟 | < 2s | 实际测试 |
| 记忆查询响应 | < 200ms | 压测工具 |
| 单模块 QPS | > 100 | 压测工具 |

---

## 9. 服务管理

### 9.1 启动服务

```powershell
# 启动所有服务
.\scripts\start-all.ps1

# 启动并等待健康检查通过
.\scripts\start-all.ps1 -WaitForHealth

# 启动指定模块
# 进入模块目录手动启动
cd M8-control-tower\backend
python server.py
```

**启动顺序**（4 个批次）：
1. **基础设施**：M12 → M11 → M10
2. **核心服务**：M5 → M1 → M4 → M8
3. **业务模块**：M2 → M3 → M6 → M7 → M9
4. **管控台**：M0 → API Gateway

### 9.2 停止服务

```powershell
# 停止所有服务
.\scripts\stop-all.ps1

# 优雅停止（等待请求完成）
.\scripts\stop-all.ps1 -Graceful
```

### 9.3 服务状态检查

```powershell
# 健康检查（所有模块）
.\scripts\health-check.ps1

# 健康检查（指定模块）
.\scripts\health-check.ps1 -Module M1

# 简洁输出（适合脚本调用）
.\scripts\health-check.ps1 -OutputFormat brief

# JSON 格式输出（便于集成）
.\scripts\health-check.ps1 -OutputFormat json
```

**健康检查退出码**：
- `0`：全部健康
- `1`：有警告
- `2`：有严重错误

### 9.4 日志管理

```powershell
# 查看所有模块最近 100 行日志
.\scripts\logs.ps1

# 查看指定模块日志
.\scripts\logs.ps1 -Module M8

# 实时跟踪日志
.\scripts\logs.ps1 -Module Gateway -Follow

# 按级别过滤
.\scripts\logs.ps1 -Level error

# 关键词搜索
.\scripts\logs.ps1 -Module all -Keyword "timeout"

# 按时间范围
.\scripts\logs.ps1 -Since "1h" -Level error

# 列出可用的日志模块
.\scripts\logs.ps1 -ListModules
```

#### 9.4.1 日志轮转机制（OP-006）

云汐系统内置了完善的日志轮转机制，防止日志文件无限增长导致磁盘空间耗尽。

**默认配置**：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 轮转方式 | 按天轮转（midnight） | 每天零点自动切分日志 |
| 保留天数 | 30 天 | 自动清理 30 天前的日志 |
| 单文件大小上限 | 100 MB | 防止单日日志过大 |
| 自动压缩 | 启用（gzip） | 旧日志自动压缩为 .gz 格式 |
| 错误日志 | 独立文件 | ERROR 及以上级别单独存储 |

**日志文件结构**：

```
logs/
├── yunxi.m8.log              # 当前主日志
├── yunxi.m8-error.log        # 当前错误日志
├── yunxi.m8.log.2026-07-16   # 历史日志（未压缩）
├── yunxi.m8.log.2026-07-15.gz  # 历史日志（已压缩）
├── yunxi.m8-error.log.2026-07-16.gz
└── ...
```

**环境变量配置**：

| 环境变量 | 类型 | 默认值 | 说明 |
|---------|------|--------|------|
| `LOG_ROTATION_ENABLED` | bool | `true` | 是否启用日志轮转 |
| `LOG_ROTATION_WHEN` | string | `midnight` | 轮转时机：`midnight`/`hourly`/`weekly`/`daily` |
| `LOG_ROTATION_BACKUP_COUNT` | int | `30` | 保留的备份文件数（天数） |
| `LOG_ROTATION_MAX_BYTES` | int | `104857600` | 单文件最大字节数（size 模式） |
| `LOG_ROTATION_COMPRESS` | bool | `true` | 是否自动 gzip 压缩旧日志 |
| `LOG_ROTATION_INTERVAL` | int | `1` | 轮转间隔 |
| `LOG_DIR` | string | `./logs` | 日志目录 |

**配置示例**：

```bash
# 生产环境：保留 60 天，按周轮转
LOG_ROTATION_WHEN=weekly
LOG_ROTATION_BACKUP_COUNT=60
LOG_ROTATION_COMPRESS=true

# 开发环境：禁用压缩，保留 7 天
LOG_ROTATION_BACKUP_COUNT=7
LOG_ROTATION_COMPRESS=false

# 高频日志场景：按小时轮转
LOG_ROTATION_WHEN=hourly
LOG_ROTATION_BACKUP_COUNT=168  # 7天 * 24小时
```

#### 9.4.2 日志清理工具

系统提供了内置的日志清理 Python API，可用于自动化运维脚本：

```python
from shared.core.observability import get_log_dir_size, clean_expired_logs, archive_logs

# 1. 统计日志目录大小
total_bytes, file_count = get_log_dir_size("./logs")
print(f"日志目录: {total_bytes / 1024 / 1024:.2f} MB, {file_count} 个文件")

# 2. 清理过期日志（保留 30 天）
result = clean_expired_logs("./logs", max_age_days=30)
print(f"删除 {result['deleted']} 个文件, 释放 {result['freed_mb']} MB")

# 3. 试运行清理（不实际删除）
result = clean_expired_logs("./logs", max_age_days=30, dry_run=True)

# 4. 归档指定时间段日志
result = archive_logs(
    log_dir="./logs",
    output_dir="./log_archive/2026-07",
    start_date="2026-07-01",
    end_date="2026-07-15",
)
print(f"归档了 {result['archived']} 个文件")
```

**PowerShell 一键清理**：

```powershell
# 清理超过 30 天的旧日志（保留最近 30 天）
Get-ChildItem .\logs -Recurse -File | 
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | 
  Remove-Item -Force

# 查看各模块日志大小
Get-ChildItem .\logs -File | 
  Sort-Object Length -Descending | 
  Select-Object Name, @{Name="SizeMB";Expression={[math]::Round($_.Length/1MB,2)}} |
  Format-Table -AutoSize
```

#### 9.4.3 各模块日志接入

以下模块已自动接入统一日志轮转：

| 模块 | 日志文件 | 说明 |
|------|---------|------|
| M8 控制塔 | `logs/yunxi.m8.log` | 主控制塔日志 |
| M9 开发工坊 | `logs/yunxi.m9.log` | 代码开发日志 |
| M10 系统卫士 | `logs/yunxi.m10.log` | 系统监控日志 |
| M11 MCP 总线 | `logs/yunxi.m11.log` | MCP 服务日志 |
| M12 安全盾 | `logs/yunxi.m12.log` | 安全防护日志 |
| API Gateway | `logs/yunxi.gateway.log` | 网关访问日志 |

所有模块均使用相同的轮转配置（通过环境变量统一控制），确保运维一致性。

### 9.5 进程管理

```powershell
# 查看所有云汐进程
Get-Process | Where-Object { $_.ProcessName -like "*python*" } | Format-Table Id, ProcessName, CPU, WorkingSet64

# 终止指定模块（不推荐，优先用健康的停止方式）
Stop-Process -Id <pid>
```

---

## 10. 安全运维

### 10.1 安全配置清单

生产环境必须完成以下安全配置：

- [ ] JWT 密钥更换为强随机值（至少 32 字节）
- [ ] 管理员密码使用强密码（至少 12 位，混合字符）
- [ ] 所有 `CHANGEME_` 开头的配置已替换
- [ ] DEBUG 模式已关闭
- [ ] CORS 已配置具体来源（非通配符）
- [ ] HTTPS 已启用
- [ ] WAF 已启用 block 模式
- [ ] 速率限制已配置
- [ ] 日志脱敏已启用
- [ ] 错误堆栈已关闭
- [ ] 文件上传大小限制已配置
- [ ] 备份加密已配置

### 10.2 定期安全检查

| 检查项 | 频率 | 工具/方法 |
|--------|------|-----------|
| 依赖安全扫描 | 每月 | pip-audit / safety |
| 漏洞扫描 | 每月 | 安全扫描工具 |
| 权限审计 | 每月 | M8 管理后台 |
| 日志审计 | 每周 | M12 安全盾 |
| 渗透测试 | 每季度 | 内部或第三方 |

### 10.3 应急响应流程

```
发现安全事件
    ↓
1. 评估影响范围和严重程度
    ↓
2. 遏制：隔离受影响系统、封禁恶意 IP
    ↓
3. 取证：保存日志、记录时间线
    ↓
4. 修复：修复漏洞、清理恶意代码
    ↓
5. 恢复：恢复服务正常运行
    ↓
6. 复盘：分析原因、改进措施
    ↓
7. 文档更新
```

### 10.4 安全联系人

| 角色 | 职责 | 响应时间 |
|------|------|---------|
| 安全负责人 | 安全事件决策、协调 | 24 小时 |
| 运维负责人 | 系统操作、应急响应 | 工作时间 30 分钟 |
| 模块负责人 | 模块级安全问题修复 | 工作时间 1 小时 |

---

## 附录

### A. 运维脚本速查

| 脚本 | 位置 | 用途 |
|------|------|------|
| `start-all.ps1` | `scripts/` | 启动所有服务 |
| `stop-all.ps1` | `scripts/` | 停止所有服务 |
| `health-check.ps1` | `scripts/` | 健康检查 |
| `logs.ps1` | `scripts/` | 日志查看 |
| `monitor.ps1` | `scripts/` | 性能监控 |
| `verify-backup.ps1` | `scripts/` | 备份验证 |
| `disaster-recovery.ps1` | `scripts/` | 灾难恢复 |
| `backup-monitor.ps1` | `scripts/` | 备份监控 |

### B. 相关文档

- [架构文档](ARCHITECTURE.md) — 系统架构与模块说明
- [API 文档](API.md) — API 接口参考
- [部署手册](DEPLOYMENT.md) — 生产环境部署指南
- [安全文档](SECURITY.md) — 安全架构与防护措施
- [灾难恢复](DISASTER_RECOVERY.md) — 容灾与恢复详细指南
- [开发者指南](DEVELOPMENT.md) — 开发规范与调试技巧

---

**文档维护**：每次运维流程变更时更新本文档
**最后更新**：2026-07-17
**版本**：v1.0
