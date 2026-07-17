# Scripts 脚本目录

> 云汐系统运维与工具脚本集合。

---

## 目录结构

```
scripts/
├── start-all.ps1              # 启动所有模块
├── stop-all.ps1               # 停止所有模块
├── health-check.ps1           # 健康检查（开发环境）
├── health-check-prod.ps1      # 健康检查（生产环境）
├── logs.ps1                   # 日志查看工具
├── monitor.ps1                # 性能监控工具
├── verify-backup.ps1          # 备份验证脚本
├── disaster-recovery.ps1      # 灾难恢复脚本
├── backup-monitor.ps1         # 备份监控脚本
├── run_coverage.py            # 覆盖率测试脚本
├── system_health_check.py     # 系统健康检查 Python 版
├── start-m8.bat               # 仅启动 M8（Windows bat）
├── start-yunxi.bat            # 一键启动（Windows bat）
├── stop-yunxi.bat             # 一键停止（Windows bat）
├── health-check.bat           # 健康检查（Windows bat）
├── git/                       # Git Hooks 脚本
│   ├── install_hooks.ps1      # 安装 Git Hooks
│   ├── pre-commit.ps1         # 提交前检查
│   ├── commit-msg.ps1         # 提交信息检查
│   └── run_precommit.py       # Pre-commit 执行脚本
└── test/                      # 测试相关脚本
    ├── run_tests.py           # 测试运行脚本
    ├── generate_report.py     # 生成测试报告
    ├── backup_validation.py   # 备份验证测试
    └── __init__.py
```

---

## 核心脚本说明

### 启动与停止

| 脚本 | 用途 | 常用参数 |
|------|------|---------|
| `start-all.ps1` | 启动所有模块 | `-WaitForHealth` 等待健康检查通过 |
| `stop-all.ps1` | 停止所有模块 | `-Graceful` 优雅停止 |

**示例**：
```powershell
# 普通启动
.\scripts\start-all.ps1

# 启动并等待健康检查通过
.\scripts\start-all.ps1 -WaitForHealth

# 停止所有服务
.\scripts\stop-all.ps1
```

### 健康检查

| 脚本 | 用途 | 常用参数 |
|------|------|---------|
| `health-check.ps1` | 开发环境健康检查 | `-Module <模块名>` 指定模块 |
| `health-check-prod.ps1` | 生产环境健康检查 | `-OutputFormat brief/json` 输出格式 |

**输出格式**：
- 退出码 `0`：全部健康
- 退出码 `1`：有警告
- 退出码 `2`：有严重错误

**示例**：
```powershell
# 完整健康检查
.\scripts\health-check.ps1

# 检查指定模块
.\scripts\health-check.ps1 -Module M1

# 简洁输出（适合脚本调用）
.\scripts\health-check-prod.ps1 -OutputFormat brief

# JSON 格式输出（便于集成）
.\scripts\health-check-prod.ps1 -OutputFormat json
```

### 日志管理

| 脚本 | 用途 | 常用参数 |
|------|------|---------|
| `logs.ps1` | 查看各模块日志 | `-Module`, `-Follow`, `-Level`, `-Since`, `-Keyword` |

**示例**：
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

### 监控与性能

| 脚本 | 用途 | 常用参数 |
|------|------|---------|
| `monitor.ps1` | 性能监控 | `-Once`, `-Duration`, `-OutputFile`, `-Module` |

**示例**：
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

### 备份与恢复

| 脚本 | 用途 | 常用参数 |
|------|------|---------|
| `verify-backup.ps1` | 备份验证 | `-Module`, `-All`, `-TestRestore`, `-AutoVerify` |
| `disaster-recovery.ps1` | 灾难恢复 | `-Detect`, `-Module`, `-All`, `-DryRun` |
| `backup-monitor.ps1` | 备份监控 | 定时任务使用 |

**示例**：
```powershell
# 验证指定模块的备份
.\scripts\verify-backup.ps1 -Module m9

# 验证所有模块
.\scripts\verify-backup.ps1 -All

# 验证并测试恢复
.\scripts\verify-backup.ps1 -All -TestRestore

# 检测故障模块
.\scripts\disaster-recovery.ps1 -Detect

# 恢复指定模块
.\scripts\disaster-recovery.ps1 -Module m9

# 预览恢复计划
.\scripts\disaster-recovery.ps1 -Module m9 -DryRun
```

### 测试与覆盖率

| 脚本 | 用途 | 说明 |
|------|------|------|
| `run_coverage.py` | 运行覆盖率测试 | 生成 HTML 覆盖率报告 |
| `test/run_tests.py` | 运行测试 | 支持按模块、按标记筛选 |
| `test/generate_report.py` | 生成测试报告 | 生成 JUnit XML 格式报告 |

**示例**：
```powershell
# 运行覆盖率测试
python scripts/run_coverage.py

# 运行指定模块测试
python scripts/test/run_tests.py --module m8
```

### Git Hooks

| 脚本 | 用途 |
|------|------|
| `git/install_hooks.ps1` | 安装 Git Hooks |
| `git/pre-commit.ps1` | 提交前检查（代码格式、语法） |
| `git/commit-msg.ps1` | 提交信息格式检查（Conventional Commits） |

**安装**：
```powershell
.\scripts\git\install_hooks.ps1
```

安装后每次提交会自动检查：
- 提交信息格式是否符合 Conventional Commits
- Python 语法检查
- 基本代码格式检查

---

## 脚本编写规范

### 命名规范

- 使用动词 + 名词的命名方式
- 多个单词用连字符分隔：`health-check.ps1`
- PowerShell 脚本使用 `.ps1` 后缀
- Python 脚本使用 `.py` 后缀

### 参数规范

- 支持 `-Help` 参数显示帮助
- 重要操作支持 `-DryRun` 试运行模式
- 输出支持多种格式（human/json/brief）

### 日志规范

- 操作成功输出绿色提示
- 警告输出黄色提示
- 错误输出红色提示
- 重要操作记录到日志文件

---

## 相关文档

- [运维手册](../docs/OPS.md) — 详细运维操作指南
- [灾难恢复文档](../docs/DISASTER_RECOVERY.md) — 备份与恢复详细说明
- [开发者指南](../docs/DEVELOPMENT.md) — Git 提交规范

---

**最后更新**：2026-07-17
**版本**：v1.0
