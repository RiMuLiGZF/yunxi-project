# 云汐系统 - 生产环境部署与运维手册

## 目录

1. [系统要求](#1-系统要求)
2. [裸机部署指南](#2-裸机部署指南)
3. [Docker 部署指南](#3-docker-部署指南)
4. [升级与回滚](#4-升级与回滚)
5. [日常运维](#5-日常运维)
6. [监控与告警](#6-监控与告警)
7. [常见问题排查](#7-常见问题排查)
8. [安全加固建议](#8-安全加固建议)

---

## 1. 系统要求

### 1.1 硬件要求

| 配置等级 | CPU | 内存 | 磁盘 | 适用场景 |
|---------|-----|------|------|---------|
| 最低配置 | 4 核 | 8 GB | 50 GB SSD | 开发测试、单用户 |
| 推荐配置 | 8 核 | 16 GB | 100 GB SSD | 小型团队、生产环境 |
| 高性能 | 16 核 | 32 GB+ | 500 GB SSD | 多用户、高并发 |

> **注意**：如果使用本地大模型（Ollama），需要额外增加 GPU 显存（建议 8GB+）。

### 1.2 软件要求

| 组件 | 最低版本 | 推荐版本 | 说明 |
|-----|---------|---------|------|
| Python | 3.10 | 3.11 / 3.12 | 运行各模块服务 |
| Node.js | 18.x | 20.x LTS | 前端构建（可选） |
| Redis | 6.0 | 7.x | 缓存和消息队列 |
| Git | 2.30 | 最新 | 版本管理和升级 |
| Docker | 20.10 | 24.x+ | Docker 部署（可选） |
| Nginx | 1.20 | 1.24+ | 反向代理（生产推荐） |

### 1.3 网络要求

- 入站端口：8080（API Gateway）、可选 80/443（Nginx）
- 内部端口：8000-8012（各模块服务）、6379（Redis）、8100（ChromaDB）
- 出站：大模型 API 访问（如使用云端模型）

> **生产环境建议**：仅暴露 80/443 端口，内部服务通过内网访问。

---

## 2. 裸机部署指南

### 2.1 部署前准备

```powershell
# 1. 克隆代码仓库
git clone <repository-url> yunxi-project
cd yunxi-project

# 2. 检查环境
python --version
git --version

# 3. 试运行部署检查
.\deploy-prod.ps1 -DryRun
```

### 2.2 首次部署

```powershell
# 1. 生成生产配置文件
# 脚本会自动从模板生成 yunxi.env.prod
.\deploy-prod.ps1

# 2. 修改配置文件
# 编辑 config/yunxi.env.prod，替换所有 CHANGEME_ 开头的配置
notepad config\yunxi.env.prod

# 3. 重新执行部署
.\deploy-prod.ps1

# 4. 验证部署
.\scripts\health-check-prod.ps1
```

### 2.3 部署参数说明

| 参数 | 说明 | 默认值 |
|-----|------|-------|
| `-ConfigFile` | 指定配置文件路径 | `config\yunxi.env.prod` |
| `-SkipEnvCheck` | 跳过环境检查 | false |
| `-SkipDependencyInstall` | 跳过依赖安装 | false |
| `-SkipDbMigration` | 跳过数据库迁移 | false |
| `-SkipFrontendBuild` | 跳过前端构建 | false |
| `-Force` | 强制部署（忽略检查失败） | false |
| `-DryRun` | 试运行模式 | false |

### 2.4 服务管理

```powershell
# 启动所有服务
.\start-all.ps1

# 启动并等待健康检查
.\start-all.ps1 -WaitForHealth

# 停止所有服务
.\stop-all.ps1

# 健康检查
.\scripts\health-check-prod.ps1

# 查看指定模块日志
.\scripts\logs.ps1 -Module M1

# 实时跟踪日志
.\scripts\logs.ps1 -Module Gateway -Follow
```

---

## 3. Docker 部署指南

### 3.1 环境准备

```bash
# 安装 Docker 和 Docker Compose
# 参考: https://docs.docker.com/engine/install/

# 验证安装
docker --version
docker compose version
```

### 3.2 快速部署

```bash
# 1. 克隆代码
git clone <repository-url> yunxi-project
cd yunxi-project

# 2. 复制生产配置
cp config/yunxi.env.prod.template config/yunxi.env.prod
# 编辑配置文件，替换所有 CHANGEME_ 配置

# 3. 创建必要的目录
mkdir -p data logs/nginx

# 4. 启动核心服务
docker compose -f docker-compose.prod.yml up -d

# 5. （可选）启动监控服务
docker compose -f docker-compose.prod.yml --profile monitoring up -d

# 6. （可选）启动 Nginx 反向代理
docker compose -f docker-compose.prod.yml --profile nginx up -d

# 7. 检查服务状态
docker compose -f docker-compose.prod.yml ps
```

### 3.3 生产配置说明

`docker-compose.prod.yml` 相比开发版本有以下增强：

- **资源限制**：每个服务都配置了 CPU 和内存限制
- **日志管理**：JSON 文件日志，单文件 100MB，保留 5 个
- **健康检查**：所有服务配置健康检查，自动重启不健康的容器
- **安全加固**：内部服务仅绑定 127.0.0.1，不对外暴露
- **环境隔离**：使用独立的 `yunxi.env.prod` 配置文件
- **Profile 支持**：监控和 Nginx 通过 profile 可选启用

### 3.4 常用命令

```bash
# 查看所有服务状态
docker compose -f docker-compose.prod.yml ps

# 查看服务日志
docker compose -f docker-compose.prod.yml logs -f yunxi-gateway

# 重启单个服务
docker compose -f docker-compose.prod.yml restart yunxi-m1

# 查看资源使用
docker stats

# 停止所有服务
docker compose -f docker-compose.prod.yml down

# 更新镜像并重启
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

---

## 4. 升级与回滚

### 4.1 升级流程

```powershell
# 1. 查看当前版本
git log --oneline -5

# 2. 试运行升级（推荐先执行）
.\upgrade.ps1 -DryRun

# 3. 执行升级
.\upgrade.ps1

# 4. 验证升级结果
.\scripts\health-check-prod.ps1
```

升级脚本自动执行以下步骤：
1. 升级前环境检查
2. 全量备份（代码、配置、数据）
3. Git 拉取最新代码
4. 依赖更新
5. 数据库迁移
6. 滚动重启服务
7. 健康检查验证
8. 失败自动回滚

### 4.2 升级参数

| 参数 | 说明 |
|-----|------|
| `-TargetCommit` | 升级到指定 commit |
| `-Branch` | 指定分支 |
| `-BackupDir` | 自定义备份目录 |
| `-SkipBackup` | 跳过备份（不推荐） |
| `-SkipRollback` | 失败时不自动回滚 |
| `-DryRun` | 试运行模式 |

### 4.3 回滚流程

```powershell
# 1. 查看可用备份
.\rollback.ps1 -ListBackups

# 2. 从指定备份回滚
.\rollback.ps1 -BackupPath .\backup\yunxi_backup_20240101_120000

# 3. 回滚到指定 commit
.\rollback.ps1 -TargetCommit abc1234

# 4. 自动选择最近的备份回滚
.\rollback.ps1
```

### 4.4 手动回滚

如果自动回滚失败，可以按以下步骤手动回滚：

```powershell
# 1. 停止服务
.\stop-all.ps1

# 2. 恢复代码版本
git checkout <previous-commit>

# 3. 恢复配置
Copy-Item .\backup\yunxi_backup_xxx\config\* .\config\ -Recurse -Force

# 4. 恢复数据
Copy-Item .\backup\yunxi_backup_xxx\data\* .\data\ -Recurse -Force

# 5. 重新启动
.\start-all.ps1

# 6. 验证
.\scripts\health-check-prod.ps1
```

---

## 5. 日常运维

### 5.1 健康检查

```powershell
# 完整健康检查
.\scripts\health-check-prod.ps1

# 简洁输出（适合脚本调用）
.\scripts\health-check-prod.ps1 -OutputFormat brief

# JSON 格式输出（便于集成）
.\scripts\health-check-prod.ps1 -OutputFormat json

# 检查指定模块
.\scripts\health-check-prod.ps1 -Module M1
```

**退出码说明**：
- `0`：全部健康
- `1`：有警告
- `2`：有严重错误

### 5.2 日志管理

```powershell
# 查看所有模块最近 100 行日志
.\scripts\logs.ps1

# 查看指定模块日志
.\scripts\logs.ps1 -Module M5

# 实时跟踪日志
.\scripts\logs.ps1 -Module Gateway -Follow

# 按级别过滤
.\scripts\logs.ps1 -Level error

# 关键词搜索
.\scripts\logs.ps1 -Module all -Keyword "timeout"

# 按时间范围
.\scripts\logs.ps1 -Since "1h" -Level error

# 列出可用的日志文件
.\scripts\logs.ps1 -ListModules
```

### 5.3 性能监控

```powershell
# 实时监控所有模块
.\scripts\monitor.ps1

# 只监控一次（适合定时任务）
.\scripts\monitor.ps1 -Once

# 简洁输出
.\scripts\monitor.ps1 -Once -Brief

# 监控指定模块
.\scripts\monitor.ps1 -Module M1

# 监控 5 分钟并导出报告
.\scripts\monitor.ps1 -Duration 300 -OutputFile report.csv
```

### 5.4 日常巡检清单

**每日检查**：
- [ ] 健康检查：`.\scripts\health-check-prod.ps1`
- [ ] 错误日志：`.\scripts\logs.ps1 -Level error -Since "24h"`
- [ ] 磁盘空间：确保剩余空间 > 20%
- [ ] 内存使用：确保使用率 < 80%

**每周检查**：
- [ ] 备份验证：检查备份是否正常生成
- [ ] 性能趋势：查看一周性能数据
- [ ] 安全更新：检查依赖是否有安全更新

**每月检查**：
- [ ] 清理旧日志和临时文件
- [ ] 数据库完整性检查
- [ ] 安全审计：检查访问日志

---

## 6. 监控与告警

### 6.1 Prometheus + Grafana

Docker 部署时可以通过 profile 启用监控：

```bash
docker compose -f docker-compose.prod.yml --profile monitoring up -d
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 （默认账号 admin/admin）

### 6.2 告警阈值

| 指标 | 警告阈值 | 严重阈值 | 建议处理 |
|-----|---------|---------|---------|
| CPU 使用率 | >= 80% | >= 95% | 扩容或优化代码 |
| 内存使用率 | >= 80% | >= 90% | 扩容或排查内存泄漏 |
| 磁盘使用率 | >= 80% | >= 90% | 清理空间或扩容 |
| 响应时间 | >= 1s | >= 3s | 排查性能瓶颈 |
| 错误率 | >= 5% | >= 20% | 排查错误原因 |

### 6.3 集成外部告警

可以将健康检查脚本接入监控系统：

```powershell
# 示例：通过退出码判断状态
.\scripts\health-check-prod.ps1 -OutputFormat brief
if ($LASTEXITCODE -eq 2) {
    # 发送严重告警
    Send-Alert -Level critical -Message "系统严重异常"
}
elseif ($LASTEXITCODE -eq 1) {
    # 发送警告
    Send-Alert -Level warning -Message "系统有警告"
}
```

---

## 7. 常见问题排查

### 7.1 服务无法启动

**症状**：模块启动后立即退出

**排查步骤**：
```powershell
# 1. 查看错误日志
.\scripts\logs.ps1 -Module M1 -Level error

# 2. 检查端口是否被占用
Get-NetTCPConnection -LocalPort 8001 -State Listen

# 3. 检查配置文件
# 确认 config/yunxi.env.prod 中相关配置正确

# 4. 手动启动查看详细错误
cd M1-agent-hub
python server.py
```

**常见原因**：
- 端口被占用：更换端口或停止占用进程
- 依赖缺失：重新执行 `pip install -r requirements.txt`
- 配置错误：检查配置文件格式和值
- 权限不足：以管理员身份运行

### 7.2 数据库错误

**症状**：数据库相关报错

**排查步骤**：
```powershell
# 1. 检查数据目录是否存在
Test-Path .\data

# 2. 检查数据库文件
Get-ChildItem .\data -Filter *.db

# 3. 检查磁盘空间
Get-PSDrive C
```

**常见原因**：
- 数据目录不存在：手动创建 `data` 目录
- 权限问题：确保服务账户有读写权限
- 数据库损坏：从备份恢复

### 7.3 Redis 连接失败

**症状**：提示 Redis 连接错误

**排查步骤**：
```powershell
# 1. 检查 Redis 是否运行
# Docker:
docker ps | grep redis

# 裸机:
Get-NetTCPConnection -LocalPort 6379 -State Listen

# 2. 测试连接
python -c "import redis; r = redis.Redis(); r.ping(); print('OK')"
```

**常见原因**：
- Redis 未启动：启动 Redis 服务
- 密码错误：检查 REDIS_PASSWORD 配置
- 网络问题：检查防火墙和网络配置

### 7.4 性能问题

**症状**：系统响应慢

**排查步骤**：
```powershell
# 1. 查看系统资源
.\scripts\monitor.ps1 -Once

# 2. 查看错误和警告日志
.\scripts\logs.ps1 -Level warning -Since "1h"

# 3. 查看慢请求日志
.\scripts\logs.ps1 -Keyword "slow"
```

**常见原因**：
- CPU/内存不足：升级硬件或优化代码
- 数据库慢查询：添加索引、优化查询
- 大模型响应慢：检查模型配置和网络

### 7.5 升级失败

**症状**：升级后服务无法启动

**处理方法**：
1. 升级脚本会自动回滚，等待回滚完成
2. 如果自动回滚失败，手动执行回滚：`.\rollback.ps1`
3. 查看升级日志，定位失败原因
4. 修复问题后重新尝试升级

---

## 8. 安全加固建议

### 8.1 配置安全

- [ ] 所有 `CHANGEME_` 开头的配置必须替换
- [ ] JWT 密钥使用随机字符串（至少 32 字节）
- [ ] 管理员密码使用强密码（至少 12 位，包含大小写字母、数字、特殊字符）
- [ ] Redis 设置密码认证
- [ ] 配置文件权限设置为仅服务账户可读

### 8.2 网络安全

- [ ] 使用 Nginx 反向代理，仅暴露 80/443 端口
- [ ] 配置 HTTPS（使用 Let's Encrypt 或商业证书）
- [ ] 启用 WAF（Web 应用防火墙）
- [ ] 配置 CORS 限制访问来源
- [ ] 内部服务绑定内网地址，不对外暴露

### 8.3 数据安全

- [ ] 定期备份（至少每日一次）
- [ ] 备份加密存储
- [ ] 定期测试恢复流程
- [ ] 敏感数据加密存储
- [ ] 数据库访问日志审计

### 8.4 系统安全

- [ ] 定期更新系统和依赖
- [ ] 启用防火墙
- [ ] 使用专用服务账户运行
- [ ] 禁止服务账户登录权限
- [ ] 定期安全审计

---

## 附录

### A. 脚本速查

| 脚本 | 位置 | 用途 |
|-----|------|------|
| `deploy-prod.ps1` | 项目根目录 | 生产环境部署 |
| `upgrade.ps1` | 项目根目录 | 系统升级 |
| `rollback.ps1` | 项目根目录 | 版本回滚 |
| `start-all.ps1` | 项目根目录 | 启动所有服务 |
| `stop-all.ps1` | 项目根目录 | 停止所有服务 |
| `health-check-prod.ps1` | scripts/ | 生产环境健康检查 |
| `logs.ps1` | scripts/ | 日志查看 |
| `monitor.ps1` | scripts/ | 性能监控 |

### B. 端口分配

| 端口 | 服务 | 说明 |
|-----|------|------|
| 8080 | API Gateway | 统一接入层 |
| 8000 | M0 主理人控制台 | 前端入口 |
| 8001 | M1 Agent 调度中心 | 多 Agent 调度 |
| 8002 | M2 技能集群 | 技能服务 |
| 8003 | M3 端云协同 | 端云同步 |
| 8004 | M4 场景引擎 | 场景编排 |
| 8005 | M5 潮汐记忆 | 记忆系统 |
| 8006 | M6 硬件外设 | 硬件接口 |
| 8007 | M7 积木平台 | 工作流构建 |
| 8008 | M8 管理工作台 | 管理后台 |
| 8009 | M9 编程开发 | 代码生成 |
| 8010 | M10 系统卫士 | 系统监控 |
| 8011 | M11 MCP 总线 | MCP 服务 |
| 8012 | M12 安全盾 | 安全防护 |
| 6379 | Redis | 缓存服务 |
| 8100 | ChromaDB | 向量数据库 |

### C. 目录结构

```
yunxi-project/
├── config/                    # 配置文件
│   ├── yunxi.env              # 当前使用配置
│   ├── yunxi.env.example      # 开发环境示例
│   └── yunxi.env.prod.template # 生产环境模板
├── data/                      # 数据文件（各模块数据库）
├── logs/                      # 日志文件
├── backup/                    # 备份文件
├── scripts/                   # 运维脚本
│   ├── health-check-prod.ps1  # 生产健康检查
│   ├── logs.ps1               # 日志查看
│   └── monitor.ps1            # 性能监控
├── docs/                      # 文档
│   └── DEPLOYMENT.md          # 本文档
├── deploy-prod.ps1            # 生产部署脚本
├── upgrade.ps1                # 升级脚本
├── rollback.ps1               # 回滚脚本
├── start-all.ps1              # 启动脚本
├── stop-all.ps1               # 停止脚本
├── docker-compose.yml         # 开发环境编排
└── docker-compose.prod.yml    # 生产环境编排
```
