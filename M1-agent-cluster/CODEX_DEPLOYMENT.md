# Codex Agent 部署文档

## 概述

Codex Agent 是云汐系统接入的**代码专家智能体**，支持双模式运行：

- **途径一：本地模式** — 7B 大模型指挥（qwen2.5:7b，零成本，本地推理）
- **途径二：API 模式** — 云端 API 调用（OpenAI/Anthropic/DeepSeek 等，更强能力）

**放置位置**：M1 联邦调度层（外部 Agent 注册）
**工具调用**：通过 MCP 协议对接 M2 Skills 集群
**密钥管理**：Fernet 对称加密存储在 `~/.yunxi/codex_keys.enc`

---

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    云汐 M1 调度中心                          │
│  (master_scheduler + 联邦调度 + 8基础设施 + 8模块管家)        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
          ┌─────────────────┐   ┌─────────────────┐
          │  Hermes Agent   │   │   Codex Agent   │
          │  (通用智能体)    │   │  (代码专家)      │
          └─────────────────┘   └────────┬────────┘
                                          │
                           ┌──────────────┴──────────────┐
                           ▼                             ▼
                    本地模式 (local)              API 模式 (api)
                           │                             │
                           ▼                             ▼
                 Ollama qwen2.5:7b          OpenAI / Anthropic / ...
                 (本地GPU，零成本)           (云端API，按调用计费)
                           │                             │
                           └──────────────┬──────────────┘
                                          │
                                          ▼
                                MCP 协议 (JSON-RPC 2.0)
                                          │
                                          ▼
                                M2 Skills 集群
                           (代码搜索/文档处理/翻译等)
```

---

## 文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| 核心适配器 | `federation/adapters/codex_agent.py` | Codex Agent 双模式适配器 |
| 注册工具 | `codex_register.py` | 联邦注册 + 密钥管理 CLI |
| 配置模板 | `codex_agent_config.yaml` | YAML 配置模板 |
| 部署文档 | `CODEX_DEPLOYMENT.md` | 本文档 |
| 密钥存储 | `~/.yunxi/codex_keys.enc` | 加密后的 API 密钥 |

---

## 快速开始

### 途径一：本地模式（7B 大模型指挥）

**适用场景**：日常代码辅助、学习、简单开发、隐私敏感场景

```bash
cd M1-agent-cluster

# 1. 测试基本功能
python codex_register.py --test --mode local

# 2. 注册到联邦调度系统
python codex_register.py --register --mode local

# 3. 查看所有 Codex Agent
python codex_register.py --list
```

**前置条件**：
- ✅ Ollama 服务运行中（默认 `http://localhost:11434`）
- ✅ qwen2.5:7b 模型已拉取
- ✅ Python 依赖：httpx, structlog, pydantic

### 途径二：API 模式（云端 API 调用）

**适用场景**：复杂架构设计、深度代码审查、高性能代码生成

```bash
cd M1-agent-cluster

# 1. 添加 API 密钥（交互式输入）
python codex_register.py --keys add --provider openai

# 或从环境变量读取
set OPENAI_API_KEY=sk-xxxxxxxx
python codex_register.py --keys add --provider openai --env-key OPENAI_API_KEY

# 2. 注册到联邦调度系统
python codex_register.py --register --mode api --provider openai

# 3. 测试 API 模式
python codex_register.py --test --mode api --provider openai

# 4. 查看已存储的密钥
python codex_register.py --keys list
```

**支持的 API 服务商**：

| 服务商 | provider 值 | 默认模型 | 默认端点 |
|--------|------------|---------|---------|
| OpenAI | `openai` | gpt-4o | https://api.openai.com/v1 |
| Anthropic | `anthropic` | claude-3-5-sonnet | https://api.anthropic.com |
| DeepSeek | `deepseek` | deepseek-coder | https://api.deepseek.com/v1 |
| Moonshot | `moonshot` | moonshot-v1-8k | https://api.moonshot.cn/v1 |
| 通义千问 | `qwen` | qwen-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| 自定义 | `custom` | 自定义 | 自定义 |

---

## API 密钥安全管理

### 存储机制

```
API Key 明文
    │
    ▼  Fernet 对称加密
加密后的 Key
    │
    ▼  JSON 封装
{ "openai": "encrypted_key", "anthropic": "encrypted_key", ... }
    │
    ▼  再次 Fernet 加密
密文文件 → ~/.yunxi/codex_keys.enc
```

### 主密钥管理

- 默认从环境变量 `FEDERATION_MASTER_KEY` 读取
- 未设置时自动生成（仅内存有效，进程重启后失效）
- **生产环境必须设置**：
  ```bash
  set FEDERATION_MASTER_KEY=your-32-byte-base64-key
  ```

### 密钥操作

```bash
# 列出所有密钥（掩码显示）
python codex_register.py --keys list

# 添加密钥
python codex_register.py --keys add --provider openai

# 移除密钥
python codex_register.py --keys remove --provider openai
```

---

## 云汐系统调用方式

云汐调度中心通过以下方式向 Codex 发指令：

### 1. 通过联邦调度器调用

```python
from federation.registry import ExternalAgentRegistry
from federation.adapters.codex_agent import CodexAgentAdapter

registry = ExternalAgentRegistry()

# 获取可用的 Codex Agent
codex_agents = [a for a in registry.list_agents() if a.provider == "Codex"]

# 创建适配器并调用
adapter = CodexAgentAdapter(
    agent_id=codex_agents[0].agent_id,
    display_name=codex_agents[0].display_name,
    config=codex_agents[0].config,
)

result = await adapter.invoke(
    prompt="帮我写一个用户认证的 FastAPI 路由",
    system_prompt="使用 Python 3.10+ 语法，包含类型注解和错误处理。",
    temperature=0.2,
    max_tokens=2048,
)

print(result["output"])
```

### 2. 任务分配场景

| 场景 | 推荐模式 | 说明 |
|------|---------|------|
| 代码补全、简单函数生成 | 本地模式 | 快速响应，零成本 |
| 代码审查、Bug 修复 | 本地模式 | 隐私敏感，本地处理 |
| 架构设计、技术选型 | API 模式 | 需要更强推理能力 |
| 复杂算法实现 | API 模式 | 更高质量的输出 |
| 学习辅助、代码解释 | 本地模式 | 足够用，低成本 |

---

## 功能能力对比

| 能力 | 本地模式 (7B) | API 模式 (GPT-4o 级) |
|------|-------------|---------------------|
| 代码生成 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 代码审查 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Bug 修复 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 代码解释 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 重构建议 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 架构设计 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 测试生成 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 多语言支持 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 响应速度 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 成本 | 免费 | 按调用计费 |
| 隐私安全 | 完全本地 | 数据上传 |

---

## 性能指标（本地模式）

### 测试数据（qwen2.5:7b, RTX 3070 8G）

| 测试项 | 结果 |
|--------|------|
| 代码生成（快速排序） | ~12 秒 / 446 tokens |
| 代码解释（斐波那契） | ~5.5 秒 / 347 tokens |
| 健康检查 | ~600 ms |
| 平均 token 输出速度 | ~40-50 token/s |

### 资源占用

- **GPU 显存**：约 5-6 GB
- **系统内存**：约 200-300 MB
- **磁盘**：4.7 GB（模型文件）

---

## MCP 工具调用配置

Codex Agent 可以通过 MCP 协议调用 M2 Skills 集群的技能。

### 启用 MCP 工具

```python
adapter = CodexAgentAdapter(
    config={
        "mode": "local",
        "enable_tools": True,  # 启用工具
        "mcp_server_url": "http://localhost:8002/mcp/v1",
        "max_iterations": 5,
    }
)
```

### M8 鉴权配置

M2 Skills 需要 M8 管理令牌才能调用。配置方式：

**方式一：配置到适配器**
```python
adapter = CodexAgentAdapter(config={
    "mcp_server_url": "http://localhost:8002/mcp/v1",
    "m8_token": "your-m8-token",
})
```

**方式二：在请求头中携带**（修改 `_ensure_http_client` 方法）

### 可用的代码相关技能

| 技能 | 说明 | 状态 |
|------|------|------|
| `code_search` | 代码搜索 | 待验证 |
| `code_skills` | 代码技能集合 | 待验证 |
| `doc_proc` | 文档处理 | 待验证 |
| `data_analysis` | 数据分析 | 待验证 |
| `translate` | 翻译 | 待验证 |
| `web_fetch` | 网页抓取 | 待验证 |
| `fulltext_search` | 全文搜索 | 待验证 |

---

## 故障排查

### 常见问题

**Q: 本地模式报错 "Ollama API 调用失败"**
A: 检查 Ollama 服务是否启动：`ollama serve`，确认端口 11434 可访问。

**Q: 模型未找到**
A: 执行 `ollama list` 查看已安装模型，用 `ollama pull qwen2.5:7b` 拉取。

**Q: API 模式返回 401/403**
A: 检查 API Key 是否正确配置，运行 `python codex_register.py --keys list` 确认。

**Q: 密钥文件损坏/解密失败**
A: 删除 `~/.yunxi/codex_keys.enc` 重新添加密钥。注意：如果使用了自定义 `FEDERATION_MASTER_KEY`，需要确保环境变量一致。

**Q: 响应速度太慢**
A:
- 本地模式：检查 GPU 利用率（`nvidia-smi`），确认 Ollama 使用 GPU
- API 模式：检查网络延迟，考虑切换更近的 API 端点

**Q: 代码质量不够好**
A:
- 本地模式：属于 7B 模型的能力上限，可考虑切换到 API 模式
- API 模式：调整 temperature 或更换更强的模型

---

## 扩展与升级

### 接入更多 API 服务商

在 `codex_register.py` 的 `default_urls` 和 `default_models` 字典中添加新的服务商：

```python
default_urls = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    # 添加新的服务商
    "new_provider": "https://api.new-provider.com/v1",
}
```

### 接入更多 Agent

按照 Codex 的模式，可以快速添加新的 Agent 类型：

1. 在 `federation/adapters/` 下创建新适配器（继承 `AgentAdapterBase`）
2. 实现 `_invoke_impl` 和 `_health_check_impl`
3. 用 `ExternalAgentRegistry.register_agent()` 注册
4. 在调度器中配置路由策略

---

## 测试操作清单

部署完成后，按以下清单验证：

- [ ] **环境检查**
  - [ ] Ollama 服务运行中（本地模式）
  - [ ] qwen2.5:7b 模型已安装（本地模式）
  - [ ] API Key 已配置（API 模式）
  - [ ] Python 依赖已安装
  - [ ] M2 Skills 服务运行中（MCP 模式）

- [ ] **本地模式测试**
  - [ ] 健康检查通过
  - [ ] 代码生成正常（Python 函数）
  - [ ] 代码解释正确
  - [ ] 多语言支持（JS/Go 等）
  - [ ] 响应延迟 < 15 秒

- [ ] **API 模式测试**
  - [ ] 健康检查通过（API 可达）
  - [ ] 代码生成正常
  - [ ] 复杂任务质量达标
  - [ ] Token 计数准确
  - [ ] 成本计算正确

- [ ] **联邦注册测试**
  - [ ] Agent 注册成功
  - [ ] Agent 列表可查询
  - [ ] 适配器实例化正常
  - [ ] 类型为 CODE

- [ ] **密钥管理测试**
  - [ ] 密钥添加成功
  - [ ] 密钥列表显示正确（掩码）
  - [ ] 密钥删除正常
  - [ ] 加密存储验证

- [ ] **MCP 工具调用测试**（需 M2 配合）
  - [ ] 工具列表获取成功
  - [ ] 单技能调用正常
  - [ ] 多轮工具调用正常
  - [ ] 错误处理正常

---

## 版本信息

| 项目 | 版本 |
|------|------|
| Codex 适配器 | v1.0.0 |
| 本地模型 | qwen2.5:7b |
| 支持 API 格式 | OpenAI 兼容 / Anthropic |
| 协议 | MCP JSON-RPC 2.0 |
| 加密算法 | Fernet (AES-128-CBC + HMAC-SHA256) |
| 部署日期 | 2026-07-07 |
