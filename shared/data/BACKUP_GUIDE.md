# 云汐系统备份指南（第二阶段统一治理）

## 概述

本文档介绍云汐系统的统一备份机制，包括备份策略、恢复流程、最佳实践等内容。

**第二阶段统一治理目标**：所有有独立数据库的模块都接入 M8 统一备份调度中心，实现全系统备份能力的标准化、自动化和可观测。

---

## 目录

- [架构概览](#架构概览)
- [备份类型](#备份类型)
- [存储后端](#存储后端)
- [备份安全](#备份安全)
- [保留策略](#保留策略)
- [模块接入情况](#模块接入情况)
- [备份调度配置](#备份调度配置)
- [CLI 工具使用](#cli-工具使用)
- [恢复流程](#恢复流程)
- [API 接口](#api-接口)
- [最佳实践](#最佳实践)
- [故障排查](#故障排查)

---

## 架构概览

### 核心组件

```
┌─────────────────────────────────────────────────────────┐
│                    M8 控制塔（调度中心）                   │
│  ┌───────────────────────────────────────────────────┐  │
│  │           BackupOrchestratorService               │  │
│  │  - 模块配置管理（持久化到数据库）                    │  │
│  │  - 定时调度（daily / interval / cron）             │  │
│  │  - 备份任务状态追踪                                 │  │
│  │  - 失败告警 / 存储监控                              │  │
│  │  - 历史记录查询                                     │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │ 调用 / 回退
                       ▼
┌─────────────────────────────────────────────────────────┐
│            shared/data/data_layer/backup_manager.py      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ BackupManager│  │BackupOrchestra│  │ ModuleBackup │  │
│  │  - 全量备份   │  │  tor         │  │ Registry     │  │
│  │  - 增量备份   │  │  - 模块调度   │  │  - 模块配置   │  │
│  │  - 差异备份   │  │  - 统一管理   │  │  - 自动发现   │  │
│  │  - 加密压缩   │  └──────────────┘  └──────────────┘  │
│  │  - 校验恢复   │                                       │
│  └──────────────┘                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  存储后端    │  │  加密工具    │  │  压缩工具    │  │
│  │  (本地/远程) │  │ (AES-256-GCM)│  │   (gzip)     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 备份文件目录结构

```
backups/
├── module_backups/
│   ├── m4/
│   │   ├── m4_full_20250101_030000/
│   │   │   ├── m4.db.gz
│   │   │   ├── m4.db.gz.meta.json
│   │   │   └── backup_manifest.json
│   │   └── m4_full_20250102_030000/
│   ├── m5/
│   │   ├── m5_full_20250101_033000/
│   │   │   ├── l1_shallow.db.gz
│   │   │   ├── l2_deep.db.gz
│   │   │   ├── growth.db.gz
│   │   │   └── backup_manifest.json
│   │   └── ...
│   ├── m6/
│   ├── m8/
│   ├── m9/
│   ├── m10/
│   └── m12/
└── m8_backups/          # M8 调度中心自身备份
```

---

## 备份类型

### 全量备份（Full Backup）

备份模块的所有数据库文件。

- **特点**：恢复简单，备份完整
- **适用场景**：日常备份、重大变更前
- **默认策略**：所有模块每日一次全量备份

### 增量备份（Incremental Backup）

基于上一次备份（全量或增量）的差异备份。

- **特点**：节省空间，但恢复需要完整链
- **适用场景**：数据量大、需要频繁备份的模块
- **使用方式**：`backup --module m5 --type incremental`

### 差异备份（Differential Backup）

基于最近一次全量备份的差异备份。

- **特点**：介于全量和增量之间，恢复只需要全量+最近一次差异
- **适用场景**：平衡备份空间和恢复速度
- **使用方式**：`backup --module m5 --type differential`

---

## 存储后端

### 本地文件系统（默认）

备份文件存储在项目根目录下的 `backups/` 目录。

- **优点**：配置简单，恢复速度快
- **缺点**：本地故障时可能丢失
- **适用**：开发环境、快速验证

### 远程存储（预留接口）

预留了远程存储后端接口，未来可扩展支持：

- **S3 / OSS / COS**：对象存储
- **SFTP / FTP**：文件传输协议
- **NFS / SMB**：网络文件系统

---

## 备份安全

### 压缩（gzip）

默认启用 gzip 压缩，减少存储空间占用。

- **压缩级别**：6（平衡速度和压缩率）
- **文件后缀**：`.db.gz`
- **节省空间**：通常可节省 50%-80%

### 加密（AES-256-GCM）

可选的 AES-256-GCM 加密，保护敏感数据。

- **算法**：AES-256-GCM（认证加密）
- **密钥长度**：256 位（32 字节）
- **文件后缀**：`.enc`
- **生成密钥**：

```python
from shared.data.data_layer.backup_manager import BackupEncryptor
key = BackupEncryptor.generate_key()
print(key)  # base64 编码的密钥
```

**注意**：请妥善保管加密密钥，丢失密钥将无法恢复备份数据。

### 校验（SHA-256）

每个备份文件都计算 SHA-256 校验和，确保数据完整性。

- **校验和存储**：备份目录的 `backup_manifest.json`
- **验证方式**：`backup.py verify --backup-path /path/to/backup.db`

---

## 保留策略

支持四种保留策略，可按模块独立配置：

### 按数量（count）

保留最近 N 个备份，超出删除最旧的。

```python
RetentionPolicy(strategy="count", max_count=30)
```

### 按时间（age）

保留最近 N 天的备份，超出删除。

```python
RetentionPolicy(strategy="age", max_age_days=30)
```

### 按大小（size）

限制最大存储空间，超出时删除最旧的备份。

```python
RetentionPolicy(strategy="size", max_size_gb=10.0)
```

### 混合策略（hybrid，推荐）

同时满足数量和时间条件才删除，提供双重保障。

```python
RetentionPolicy(
    strategy="hybrid",
    max_count=30,
    max_age_days=30,
    max_size_gb=10.0,
)
```

---

## 模块接入情况

### 已接入模块（第二阶段统一治理）

| 模块 | 名称 | 数据库数量 | 备份时间 | 保留策略 | 保留数量 |
|------|------|-----------|----------|----------|----------|
| M4 | 场景引擎 | 1+ | 每日 03:00 | hybrid | 30份/30天/5GB |
| M5 | 潮汐记忆 | 4+ | 每日 03:30 | hybrid | 30份/45天/10GB |
| M6 | 硬件外设 | 1+ | 每日 04:00 | count | 20份/20天 |
| M8 | 控制塔 | 1+ | 每日 02:00 | hybrid | 50份/60天/5GB |
| M9 | 开发工坊 | 1+ | 每日 03:00 | hybrid | 30份/30天/5GB |
| M10 | 系统卫士 | 1+ | 每日 04:30 | hybrid | 30份/30天/3GB |
| M12 | 安全盾 | 1+ | 每日 05:00 | hybrid | 30份/90天/2GB |

### 配置文件位置

模块备份配置集中管理在：
`shared/data/data_layer/module_backup_registry.py`

---

## 备份调度配置

### 配置文件

全局备份配置在 `config/yunxi.env` 中：

```env
# 全局开关
BACKUP_ENABLED=true
BACKUP_ROOT=backups
BACKUP_DEFAULT_TYPE=full
BACKUP_COMPRESSION=gzip
BACKUP_ENCRYPTION=none
BACKUP_ENCRYPTION_KEY=

# 保留策略
BACKUP_RETENTION_STRATEGY=hybrid
BACKUP_MAX_BACKUPS=30
BACKUP_MAX_AGE_DAYS=30
BACKUP_MAX_SIZE_GB=50

# 告警配置
BACKUP_ALERT_FAILURE_THRESHOLD=3
BACKUP_DISK_WARN_PERCENT=20
BACKUP_DISK_CRITICAL_PERCENT=10

# 模块级配置（覆盖全局）
BACKUP_M4_ENABLED=true
BACKUP_M4_SCHEDULE=daily
BACKUP_M4_TIME=03:00
BACKUP_M4_MAX_BACKUPS=30
```

### 调度方式

#### 1. 每日定时（daily）

```python
schedule = {"type": "daily", "time": "03:00"}
```

#### 2. 间隔调度（interval）

```python
schedule = {"type": "interval", "hours": 6}
# 或
schedule = {"type": "interval", "minutes": 30}
```

#### 3. Cron 表达式（cron）

```python
schedule = {"type": "cron", "expression": "0 3 * * 1-5"}  # 工作日凌晨3点
```

Cron 表达式格式：`分 时 日 月 周`

支持的语法：
- `*`：任意值
- `*/n`：每隔 n
- `n`：具体值
- `n-m`：范围
- `n,m,k`：列表

---

## CLI 工具使用

CLI 工具位置：`shared/data/data_layer/backup.py`

### 基本用法

```bash
# 查看帮助
python shared/data/data_layer/backup.py --help

# 查看子命令帮助
python shared/data/data_layer/backup.py backup --help
```

### 备份操作

```bash
# 备份所有模块
python shared/data/data_layer/backup.py backup --all

# 备份指定模块
python shared/data/data_layer/backup.py backup --module m5

# 增量备份
python shared/data/data_layer/backup.py backup --module m5 --type incremental

# 差异备份
python shared/data/data_layer/backup.py backup --module m5 --type differential
```

### 恢复操作

```bash
# 恢复指定模块的备份（带安全网）
python shared/data/data_layer/backup.py restore --module m5 --backup-dir /path/to/backup_dir

# 不使用安全网（谨慎操作）
python shared/data/data_layer/backup.py restore --module m5 --backup-dir /path --no-safety-net

# 跳过确认提示
python shared/data/data_layer/backup.py restore --module m5 --backup-dir /path -y
```

### 列出备份

```bash
# 列出所有备份
python shared/data/data_layer/backup.py list

# 列出指定模块的备份
python shared/data/data_layer/backup.py list --module m4
```

### 校验备份

```bash
# 校验备份文件
python shared/data/data_layer/backup.py verify --backup-path /path/to/backup.db.gz

# 校验并对比校验和
python shared/data/data_layer/backup.py verify --backup-path /path/to/backup.db.gz --expected-checksum <sha256>
```

### 清理备份

```bash
# 按时间清理（删除30天前的备份）
python shared/data/data_layer/backup.py clean --max-age 30

# 按数量清理（保留最近10个）
python shared/data/data_layer/backup.py clean --max-count 10

# 按大小清理（限制5GB）
python shared/data/data_layer/backup.py clean --max-size-gb 5

# 清理指定模块
python shared/data/data_layer/backup.py clean --module m5 --max-age 30
```

### 状态查看

```bash
# 查看备份系统整体状态
python shared/data/data_layer/backup.py status
```

---

## 恢复流程

### 安全网恢复机制（推荐）

恢复前自动创建当前数据库的安全网备份，如果恢复失败则自动回滚。

```
1. 检查目标数据库是否存在
2. 如果存在，创建安全网备份（.safety_net_时间戳.db）
3. 执行恢复操作
4. 如果恢复成功 → 完成
5. 如果恢复失败 → 自动从安全网回滚 → 返回失败信息
```

### 全系统恢复步骤

**重要**：全系统恢复是高风险操作，请谨慎执行。

```bash
# 1. 先查看备份列表，确定要恢复的版本
python shared/data/data_layer/backup.py list

# 2. 逐模块恢复（建议先测试一个模块）
python shared/data/data_layer/backup.py restore --module m4 --backup-dir /path/to/m4_backup

# 3. 验证恢复结果
python shared/data/data_layer/backup.py verify --backup-path /path/to/restored.db

# 4. 依次恢复其他模块
python shared/data/data_layer/backup.py restore --module m5 --backup-dir /path/to/m5_backup
```

---

## API 接口

M8 备份调度中心提供 RESTful API，接口前缀：`/api/v1/backup`（实际路径以路由注册为准）。

### 模块管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /backup/modules | 列出所有备份模块 |
| POST | /backup/modules | 注册新模块 |
| GET | /backup/modules/{id} | 获取模块详情 |
| PUT | /backup/modules/{id} | 更新模块配置 |
| DELETE | /backup/modules/{id} | 删除模块 |

### 备份执行

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /backup/backup/all | 触发全系统备份 |
| POST | /backup/backup/{module_id} | 触发指定模块备份 |

### 历史与统计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /backup/history | 备份历史记录 |
| GET | /backup/stats | 备份统计信息 |
| GET | /backup/status | 调度器状态 |

### 监控与告警

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /backup/storage | 存储空间使用情况 |
| GET | /backup/alerts | 告警列表 |
| POST | /backup/alerts/{id}/acknowledge | 确认告警 |

---

## 最佳实践

### 1. 定期验证备份

**只备份不验证等于没备份。** 建议每月至少验证一次备份的可恢复性。

```bash
# 校验备份完整性
python shared/data/data_layer/backup.py verify --backup-path /path/to/backup

# 实际恢复测试（使用临时目录）
python shared/data/data_layer/backup.py restore --module m5 --backup-dir /path -y
```

### 2. 错开备份时间

避免所有模块在同一时间备份，减少 IO 峰值。

推荐错开方案：
- M8: 02:00（最先备份调度中心自身）
- M4: 03:00
- M5: 03:30
- M6: 04:00
- M10: 04:30
- M12: 05:00

### 3. 关键数据加密

对于包含敏感数据的模块（如用户信息、安全策略），启用加密备份。

```env
BACKUP_ENCRYPTION=aes-256-gcm
BACKUP_ENCRYPTION_KEY=your_base64_encoded_key
```

### 4. 监控告警

定期检查备份告警，及时处理备份失败。

- 连续失败 3 次：告警
- 磁盘剩余 < 20%：警告
- 磁盘剩余 < 10%：严重告警

### 5. 变更前备份

在进行以下操作前，手动执行一次备份：

- 数据库迁移
- 大版本升级
- 数据批量操作
- 配置重大变更

```bash
python shared/data/data_layer/backup.py backup --module m8
```

### 6. 异地备份（推荐）

重要数据建议同时保留异地备份，防止本地灾难。

可通过以下方式实现：
- 将 `backups/` 目录同步到云存储（rclone / ossutil）
- 使用 NAS / 外部硬盘定期复制
- 接入远程存储后端（待实现）

---

## 故障排查

### 备份失败

**常见原因：**

1. **数据库文件锁定**
   - 症状：备份时提示 database is locked
   - 解决：等待业务低峰期再备份，或使用 SQLite WAL 模式

2. **磁盘空间不足**
   - 症状：No space left on device
   - 解决：清理旧备份或扩大磁盘空间
   - 查看：`backup.py status`

3. **权限不足**
   - 症状：Permission denied
   - 解决：检查备份目录权限

4. **加密密钥错误**
   - 症状：解密失败、校验失败
   - 解决：确认使用正确的加密密钥

### 恢复失败

**常见原因：**

1. **备份文件损坏**
   - 症状：integrity_check 失败
   - 解决：尝试更早的备份版本

2. **版本不兼容**
   - 症状：表结构不匹配
   - 解决：确认备份版本与当前版本兼容

3. **磁盘空间不足**
   - 症状：恢复过程中磁盘写满
   - 解决：清理空间后重试

### 调度不执行

**常见原因：**

1. **服务未启动**
   - 确认 M8 服务正常运行
   - 检查 `orchestrator.initialize()` 是否已调用

2. **配置错误**
   - 检查 `schedule_type` 是否正确
   - 检查 cron 表达式格式

3. **进程退出**
   - 调度器使用守护线程，主线程退出会导致调度停止
   - 确保服务进程持续运行

---

## 附录

### 相关文件

| 文件 | 说明 |
|------|------|
| `shared/data/data_layer/backup_manager.py` | 备份管理器核心实现 |
| `shared/data/data_layer/module_backup_registry.py` | 模块备份配置注册表 |
| `shared/data/data_layer/backup.py` | CLI 工具 |
| `M8-control-tower/backend/services/backup_scheduler.py` | M8 调度中心服务 |
| `M8-control-tower/backend/models/backup_scheduler.py` | M8 调度中心数据模型 |
| `M8-control-tower/backend/routers/backup_scheduler.py` | M8 调度中心 API |
| `config/yunxi.env` | 全局配置文件 |

### 数据类说明

#### ModuleBackupConfig

模块备份配置，定义模块的备份策略。

#### BackupReport

备份执行结果报告，包含成功/失败状态、大小、耗时等信息。

#### VerifyReport

备份校验报告，包含完整性检查结果。

#### RetentionPolicy

保留策略配置，支持 count/age/size/hybrid 四种策略。

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 2.0 | 第二阶段统一治理 | 统一备份机制，全模块接入，加密压缩、cron调度、告警监控 |
| 1.0 | 第一阶段 | 基础备份能力，M8 调度中心雏形 |

---

**如有问题，请参考代码注释和日志信息进行排查。**
