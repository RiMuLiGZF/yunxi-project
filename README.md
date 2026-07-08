# 云汐 M8 算力调度中台

云汐系统统一算力管理与智能调度平台，支持 Claude Code 等工具通过 OpenAI 兼容协议接入，自动路由到 DeepSeek/Anthropic/Qwen 等多厂商算力源。

## 核心功能### 1. OpenAI 兼容代理层

为 Claude Code 等工具提供统一的 OpenAI 兼容 API 入口，自动协议转换和智能路由。

**Claude Code 配置方式：

```bash
export ANTHROPIC_BASE_URL=http://localhost:8000/v1
export ANTHROPIC_API_KEY=yunxi-xxxxxxxxxxxxxx
```

Claude Code 会以为自己在和 Anthropic API 对话，实际上中台自动：
- 转换协议格式（Anthropic ↔ OpenAI ↔ DeepSeek ↔ Qwen）
- 智能路由到最优算力源
- 故障自动转移
- 统一配额和审计

### 2. 三层算力架构| 层级 | 说明 | 示例 |
|------|------|------|
| 边缘算力 | 本地设备/NPU | 笔记本本地模型 |
| 云端算力 | 第三方API | DeepSeek / Anthropic / Qwen |
| 私有化算力 | 自建服务器 | 私有部署大模型 |

### 3. 智能路由策略

- **auto**: 自动最优（综合延迟、成本、健康度加权）
- **fastest**: 最快响应优先
- **cheapest**: 最低成本优先
- **priority**: 按优先级调度
- 自动故障转移（2次重试

### 4. API密钥管理

- 统一代理密钥，下游算力源密钥加密存储
- 按密钥分组管理权限
- RPM/TPM/日配额/月配额
- 用量统计与审计

### 5. 巡检中心

- **快速巡检**: 8项核心检查，30秒内完成
- **全面巡检**: 15+项深度检查
- Sentinel-Lite: 轻量级巡检Agent（定时+启动自检）
- Sentinel-Pro: 深度巡检Agent（LLM智能分析+修复方案）

## 项目结构

```
yunxi-project/
├── M8-control-tower/          # M8 控制塔（算力调度中台）
│   └── backend/
│       ├── main.py              # 主应用入口
│       ├── models.py             # 数据模型
│       ├── crypto.py            # 加密工具
│       ├── key_manager.py       # API密钥管理
│       ├── compute_router.py   # 算力路由引擎
│       ├── protocol_adapter.py   # 多厂商协议适配器
│       ├── openai_proxy.py      # OpenAI兼容代理层
│       ├── audit_logger.py     # 审计日志
│       ├── inspection_tools.py # 巡检工具集（10+检查项）
│       ├── inspection_runner.py # 巡检运行器
│       ├── routers/             # API路由
│       │   ├── __init__.py
│       │   ├── compute_sources.py
│       │   ├── api_keys.py
│       │   ├── audit.py
│       │   ├── inspection.py
│       │   └── dashboard.py
│       ├── test_e2e.py        # 端到端测试
│       └── requirements.txt
├── M1-agent-cluster/
│   └── federation/agents/
│       ├── sentinel_lite.py     # Sentinel-Lite 快速巡检Agent
│       └── sentinel_pro.py     # Sentinel-Pro 全面巡检Agent
├── frontend/
│   └── m8/
│       └── inspection.html      # 巡检中心前端页面
└── shared/                      # 共享模块
```

## 快速开始

### 1. 安装依赖

```bash
cd M8-control-tower/backend
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python main.py
```

服务启动后：
- API 地址: `http://localhost:8000
- API 文档: `http://localhost:8000/docs`
- 巡检中心: `http://localhost:8000/static/inspection.html`

### 3. 运行测试

```bash
# 功能演示
python test_e2e.py --demo

# 单元测试
python test_e2e.py --test
```

### 4. Claude Code 接入

1. 启动中台服务
2. 创建API密钥（或使用首次启动自动生成的默认密钥）
3. 配置 Claude Code:

```bash
export ANTHROPIC_BASE_URL=http://localhost:8000/v1
export ANTHROPIC_API_KEY=yunxi-你的密钥
claude
```

## 支持的厂商

| 厂商 | 聊天 | 流式 | Tool Calling | 嵌入 |
|-----|------|------|-------------|------|
| DeepSeek | ✅ | ✅ | ✅ | ✅ |
| Anthropic | ✅ | ✅ | ✅ | - |
| OpenAI | ✅ | ✅ | ✅ | ✅ |
| 通义千问(Qwen) | ✅ | ✅ | ✅ | ✅ |
| 智谱(Zhipu) | ✅ | ✅ | ✅ | ✅ |
| 月之暗面(Moonshot) | ✅ | ✅ | ✅ | ✅ |
| Gemini | ✅ | ✅ | - | - |

## 巡检检查项

### 快速巡检（8项）
1. 系统资源检测（CPU、内存、进程）
2. 磁盘空间检测
3. 数据库连接检测
4. 算力源健康检测
5. 配置文件完整性
6. 日志目录检测
7. 基础网络检测
8. API密钥状态检测

### 全面巡检（额外7+项）
1. 告警统计检查
2. 网络连通性检测
3. 版本一致性检查
4. 安全扫描
5. 性能基线检查
6. 架构一致性检查
7. 备份状态检查
8. 审计日志检查

## 架构设计原则

1. **模块归属**: M8 控制塔（算力调度中台）
2. **设计理念**: 边缘-云端-私有化三层算力统一调度
3. **核心能力**: 协议透明转换 + 智能路由 + 故障自愈
4. **安全保障**: 密钥加密存储 + 统一鉴权 + 全链路审计

## License

云汐系统内部模块
