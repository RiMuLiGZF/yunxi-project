# Hermes Agent 部署文档

## 概述

Hermes Agent 是云汐系统接入的第一个外部智能代理，采用 **方案一：M1 联邦调度 + MCP 协议层** 架构。

- **位置**：M1 联邦调度层（外部 Agent）
- **推理引擎**：本地 Ollama + qwen2.5:7b 模型
- **工具调用**：通过 MCP 协议调用 M2 Skills 集群
- **隐私等级**：LOCAL_ONLY（数据完全本地处理）
- **许可证**：MIT

## 架构图

```
┌─────────────────────────────────────────────────────────┐
│                   云汐 M1 调度中心                       │
│  (master_scheduler + 8基础设施Agent + 8模块管家Agent)    │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
    ┌──────────────────┐     ┌──────────────────┐
    │  联邦调度层       │     │  内置子 Agent     │
    │  (External       │     │  (代码/情感/      │
    │   Agent 注册表)   │     │   笔记/审查等)    │
    └─────────┬────────┘     └──────────────────┘
              │
    ┌─────────▼────────┐
    │  Hermes Agent    │  ◄── 本文件部署的 Agent
    │  (外部超级Agent)  │
    └─────────┬────────┘
              │ MCP 协议 (JSON-RPC 2.0)
              ▼
    ┌──────────────────┐
    │  M2 Skills 集群   │
    │  (14+ 内置技能)   │
    └──────────────────┘
```

## 文件清单

| 文件 | 位置 | 说明 |
|------|------|------|
| `hermes_agent.py` | `federation/adapters/` | Hermes Agent 适配器核心代码 |
| `hermes_register.py` | `M1-agent-cluster/` | 联邦注册与测试工具 |
| `hermes_agent_config.yaml` | `M1-agent-cluster/` | 配置模板 |
| `HERMES_DEPLOYMENT.md` | `M1-agent-cluster/` | 本文档 |
| `hermes-agent/` | `models/` | Hermes Agent 官方源码（参考用） |

## 快速开始

### 1. 环境前置条件

- ✅ Python 3.10+
- ✅ Ollama 服务运行中（默认 `http://localhost:11434`）
- ✅ qwen2.5:7b 模型已拉取
- ✅ M2 Skills 服务运行中（默认 `http://localhost:8002`）
- ✅ M8 管理令牌（用于 MCP 鉴权）

### 2. 安装依赖

```bash
pip install httpx pyyaml structlog pydantic
```

### 3. 运行测试

```bash
cd M1-agent-cluster

# 测试 Hermes Agent 基本功能（纯推理，不依赖 M2）
python hermes_register.py --test

# 使用自定义模型测试
python hermes_register.py --test --model qwen2.5:7b
```

### 4. 注册到联邦调度系统

```bash
# 注册 Hermes Agent
python hermes_register.py --register

# 注册并立即测试
python hermes_register.py --register --test

# 查看所有已注册 Agent
python hermes_register.py --list
```

## 配置说明

### 核心配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ollama_base_url` | `http://localhost:11434` | Ollama 服务地址 |
| `model_name` | `qwen2.5:7b` | 使用的模型名称 |
| `mcp_server_url` | `http://localhost:8002/mcp/v1` | MCP 服务器地址 |
| `max_iterations` | `8` | 最大 ReAct 迭代次数 |
| `temperature` | `0.7` | 生成温度 |
| `timeout` | `120.0` | 单次调用超时（秒） |

### 配置文件加载

```python
import yaml
from federation.adapters.hermes_agent import HermesAgentAdapter

with open("hermes_agent_config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

adapter = HermesAgentAdapter(
    agent_id="hermes_01",
    display_name="Hermes 智能助手",
    config={
        "ollama_base_url": config["ollama"]["base_url"],
        "model_name": config["ollama"]["model_name"],
        "mcp_server_url": config["mcp"]["server_url"],
        "max_iterations": config["performance"]["max_iterations"],
        "temperature": config["performance"]["temperature"],
    },
)
```

## 功能能力

### 已验证功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 本地 Ollama 连接 | ✅ | qwen2.5:7b 正常推理 |
| ReAct 多步推理 | ✅ | 思考→行动→观察→回答 循环 |
| 数学计算 | ✅ | 1234*5678=7006652 正确 |
| 健康检查 | ✅ | 支持 Ollama + MCP 双端检测 |
| MCP 工具调用 | ⚠️ | 需配置 M8 鉴权令牌 |
| 联邦注册 | ✅ | 已接入 ExternalAgentRegistry |

### 待启用功能（需 M2 配合）

- 代码搜索与生成（需 code_search skill）
- 文档处理（需 doc_proc skill）
- 网页抓取（需 web_fetch skill）
- 数据分析（需 data_analysis skill）
- 翻译（需 translate skill）

## MCP 接入配置

### 鉴权方式

Hermes Agent 调用 M2 技能需要 M8 管理令牌。有两种配置方式：

**方式一：在请求头中携带（推荐）**

```python
# 在 hermes_agent.py 的 _ensure_http_client 中添加
self._http_client = httpx.AsyncClient(
    headers={"X-M8-Token": "your-m8-token-here"},
    timeout=self._timeout,
    follow_redirects=True,
)
```

**方式二：在 URL 中携带参数**

```python
mcp_url = f"{mcp_base}?token={m8_token}"
```

### 支持的 MCP 工具

M2 Skills 集群目前提供以下技能（通过 MCP 暴露）：

| 技能 ID | 说明 | 状态 |
|---------|------|------|
| `code_search` | 代码搜索 | 待验证 |
| `code_skills` | 代码技能 | 待验证 |
| `doc_proc` | 文档处理 | 待验证 |
| `web_fetch` | 网页抓取 | 待验证 |
| `data_analysis` | 数据分析 | 待验证 |
| `translate` | 翻译 | 待验证 |
| `calendar` | 日历 | 待验证 |
| `notify` | 通知 | 待验证 |
| `fulltext_search` | 全文搜索 | 待验证 |

## 性能指标

### 本地 qwen2.5:7b 测试数据

| 测试项 | 结果 |
|--------|------|
| 简单对话延迟 | 3-6 秒 |
| 数学推理延迟 | 3-4 秒 |
| 单次推理 Token 消耗 | 300-700 input + 80-200 output |
| ReAct 单轮迭代 | 约 3 秒 |
| 最大迭代次数 | 8 次（约 24 秒内完成） |

### 资源占用

- **GPU 显存**：约 5-6 GB（qwen2.5:7b）
- **系统内存**：约 200-500 MB（Python 进程）
- **磁盘空间**：4.7 GB（模型） + 50 MB（代码）

## 安全与隐私

### 数据安全

- ✅ 所有推理在本地完成，数据不上传
- ✅ 无 API Key 泄露风险（本地模型）
- ✅ MIT 许可证，无版权传染性
- ⚠️ MCP 工具调用需经过 M8 鉴权

### 安全建议

1. 设置 `FEDERATION_MASTER_KEY` 环境变量以加密存储配置
2. MCP 调用使用内网地址，避免暴露到公网
3. 限制 Hermes Agent 可调用的技能范围
4. 定期审查 Agent 的工具调用日志

## 扩展与升级

### 接入更多外部 Agent

按照相同模式，可以快速接入其他外部 Agent：

1. 在 `federation/adapters/` 下创建新的适配器（继承 `AgentAdapterBase`）
2. 实现 `_invoke_impl` 和 `_health_check_impl` 方法
3. 使用 `ExternalAgentRegistry.register_agent()` 注册
4. 在联邦调度器中配置路由策略

### 升级 Hermes 官方版本

Hermes Agent 官方源码保存在 `models/hermes-agent/`，可定期同步：

```bash
cd models/hermes-agent
git pull origin main
```

注意：官方版本需要 Python 3.11+，当前适配器是基于 ReAct 模式的轻量实现，
不依赖官方源码，可以独立运行。后续如需官方完整功能，可升级 Python 版本后直接使用。

## 故障排查

### 常见问题

**Q: Ollama 连接失败？**
A: 检查 Ollama 服务是否启动：`ollama serve`，确认端口 11434 可访问。

**Q: 模型未找到？**
A: 执行 `ollama list` 查看已安装模型，用 `ollama pull qwen2.5:7b` 拉取。

**Q: MCP 工具调用返回 401？**
A: 需要配置 M8 管理令牌，参考上方"MCP 接入配置"章节。

**Q: 推理速度慢？**
A: 检查 GPU 是否被使用（NVIDIA：`nvidia-smi`），确认 Ollama 使用 GPU 加速。

**Q: 联邦注册后找不到 Agent？**
A: 注册表默认是内存存储，进程重启后会丢失。生产环境需配置持久化存储。

## 测试操作清单

部署完成后，按以下清单验证功能：

- [ ] **环境检查**
  - [ ] Ollama 服务运行中
  - [ ] qwen2.5:7b 模型已安装
  - [ ] Python 依赖已安装
  - [ ] M2 Skills 服务运行中

- [ ] **基本功能测试**
  - [ ] 健康检查通过（Ollama + MCP）
  - [ ] 简单对话正常
  - [ ] 数学推理正确
  - [ ] ReAct 循环正常工作

- [ ] **联邦注册测试**
  - [ ] Agent 注册成功
  - [ ] Agent 列表可查询
  - [ ] 适配器实例化正常

- [ ] **MCP 工具调用测试**（需 M2 配合）
  - [ ] 工具列表获取成功
  - [ ] 单技能调用正常
  - [ ] 多轮工具调用正常
  - [ ] 错误处理正常

- [ ] **性能测试**
  - [ ] 单次响应 < 10 秒
  - [ ] 内存占用稳定
  - [ ] 并发调用正常

## 版本信息

| 项目 | 版本 |
|------|------|
| Hermes 适配器 | v1.0.0 |
| 底层模型 | qwen2.5:7b |
| Ollama | 最新稳定版 |
| 协议 | MCP JSON-RPC 2.0 |
| 部署日期 | 2026-07-07 |
