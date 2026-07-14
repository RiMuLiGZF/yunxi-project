# Explore Agent 部署文档

## 概述

「小探」研究助理 — 基于 **qwen2.5:1.5b** 本地轻量大模型的信息检索专家。

**放置位置**：M1 联邦调度层（外部 Agent 注册）
**驱动模型**：qwen2.5:1.5b（约 1GB 显存）
**工具调用**：通过 MCP 协议调用 M2 Skills 集群
**核心定位**：网页检索、文档搜索、信息摘要、多源整合

---

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    云汐 M1 调度中心                          │
│  (master_scheduler + 联邦调度 + 8基础设施 + 8模块管家)        │
└──────────────────────────────┬──────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
      ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
      │ Hermes Agent │ │  Codex Agent │ │ Explore Agent│
      │  (通用智能体)  │ │  (代码专家)   │ │  (研究助理)   │
      │   7B 模型     │ │   7B 模型     │ │  1.5B 模型   │
      └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
             └─────────────────┼─────────────────┘
                               │
                       MCP 协议 (JSON-RPC 2.0)
                               │
                               ▼
                       M2 Skills 集群
              (web_fetch / fulltext_search / doc_proc / ...)
```

---

## 文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| 核心适配器 | `federation/adapters/explore_agent.py` | Explore Agent 适配器 |
| 注册工具 | `explore_register.py` | 联邦注册与管理 CLI |
| 配置模板 | `explore_agent_config.yaml` | YAML 配置模板 |
| 部署文档 | `EXPLORE_DEPLOYMENT.md` | 本文档 |

---

## 快速开始

### 1. 拉取模型

```bash
ollama pull qwen2.5:1.5b
```

### 2. 测试功能

```bash
cd M1-agent-hub
python explore_register.py --test
```

### 3. 注册到联邦系统

```bash
python explore_register.py --register
```

### 4. 查看所有 Explore Agent

```bash
python explore_register.py --list
```

---

## 人格设定

### 「小探」研究助理

- **性格**：细致、严谨、有条理
- **口头禅/风格**：喜欢用 📌📋📚 等 emoji 组织输出
- **专长**：信息检索、资料整理、要点提取
- **原则**：只提供信息和分析，不替用户做决策
- **输出结构**：核心结论 → 要点列表 → 参考来源

### 定制人格

可以通过修改系统提示词来改变人格：

```python
adapter = ExploreAgentAdapter(
    config={
        "personality": "小研",  # 人格标识
        # 自定义系统提示词在 _SYSTEM_PROMPT 中修改
    }
)
```

---

## 功能能力

### 核心能力

| 能力 | 说明 | 状态 |
|------|------|------|
| 信息摘要 | 长文本浓缩为要点列表 | ✅ 已验证 |
| 要点提取 | 提取关键信息点 | ✅ 已验证 |
| 概念解释 | 通俗解释专业概念 | ✅ 已验证 |
| 网页检索 | 抓取并提炼网页内容 | ⚠️ 需 M2 web_fetch |
| 文档搜索 | 本地文档全文检索 | ⚠️ 需 M2 fulltext_search |
| 多源整合 | 综合多个信息源 | ⚠️ 需工具配合 |
| 翻译辅助 | 外文资料翻译 | ⚠️ 需 M2 translate |
| 资料分类 | 内容分类与标签化 | ⚠️ 需工具配合 |

### MCP 可用工具（需 M2 配合）

| 工具 | 说明 | 优先级 |
|------|------|--------|
| `web_fetch` | 网页内容抓取 | 🔴 高 |
| `fulltext_search` | 全文搜索 | 🔴 高 |
| `doc_proc` | 文档处理 | 🟡 中 |
| `translate` | 翻译 | 🟡 中 |
| `code_search` | 代码搜索 | 🟡 中 |
| `data_analysis` | 数据分析 | 🟢 低 |
| `notify` | 通知推送 | 🟢 低 |
| `calendar` | 日历 | 🟢 低 |

---

## 性能指标

### 测试数据（qwen2.5:1.5b, RTX 3070 8G）

| 测试项 | 结果 | 对比 7B |
|--------|------|---------|
| 信息摘要（RESTful API） | **1.85 秒** / 62 tokens | 7B 约 5-6 秒（快 3x） |
| 要点提取（Python 学习） | **1.2 秒** / 209 tokens | 7B 约 4-5 秒（快 3-4x） |
| 概念解释（大语言模型） | **755ms** / 123 tokens | 7B 约 3-4 秒（快 4-5x） |
| 健康检查 | 631ms | 接近 |
| 平均输出速度 | ~80-100 token/s | 7B 约 40-50 token/s（快 2x） |

### 资源占用

- **GPU 显存**：约 **1-1.5 GB**（7B 约 5-6 GB，节省 75%）
- **系统内存**：约 100-200 MB
- **磁盘空间**：986 MB（模型文件）
- **功耗**：更低（GPU 负载更轻）

---

## 云汐系统调用方式

### 通过联邦调度器调用

```python
from federation.registry import ExternalAgentRegistry
from federation.adapters.explore_agent import ExploreAgentAdapter

registry = ExternalAgentRegistry()

# 获取 Explore Agent
explore_agents = [a for a in registry.list_agents() if a.provider == "Explore"]

# 创建适配器
adapter = ExploreAgentAdapter(
    agent_id=explore_agents[0].agent_id,
    display_name=explore_agents[0].display_name,
    config=explore_agents[0].config,
)

# 调用检索
result = await adapter.invoke(
    prompt="帮我总结一下微服务架构的优缺点",
    system_prompt="请用要点列表的形式输出。",
    temperature=0.5,
    max_tokens=500,
)

print(result["output"])
```

### 任务路由建议

| 任务类型 | 推荐 Agent | 原因 |
|---------|-----------|------|
| 通用问答、复杂推理 | Hermes (7B) | 推理能力强 |
| 代码开发、审查 | Codex (7B) | 代码专业 |
| 信息检索、摘要整理 | Explore (1.5B) | 快速轻量 |
| 简单对话、分类标签 | Explore (1.5B) | 响应快，省资源 |
| 先检索再深度分析 | Explore → Hermes | 1.5B 预处理 + 7B 深加工 |

### 典型协作模式：检索 + 深度分析

```
用户: "帮我调研一下 FastAPI 和 Flask 的对比"
  │
  ├─→ Explore Agent (1.5B)
  │    1. 调用 web_fetch 抓取相关文档
  │    2. 提取要点，整理成结构化摘要
  │    3. 返回：FastAPI 特点 + Flask 特点 + 对比表
  │
  └─→ Hermes Agent (7B)
       1. 接收 Explore 的检索结果
       2. 做深度分析和选型建议
       3. 返回：最终调研报告 + 选型建议
```

---

## 专属 Skills 扩展建议

### 第一批（高优先级）

| Skill | 功能 | 实现方式 |
|-------|------|---------|
| `web_fetch` | 网页抓取 | M2 已有，直接通过 MCP 调用 |
| `fulltext_search` | 全文搜索 | M2 已有，直接通过 MCP 调用 |
| `doc_proc` | 文档处理 | M2 已有，直接通过 MCP 调用 |

### 第二批（中优先级，需开发）

| Skill | 功能 | 说明 |
|-------|------|------|
| `rss_subscribe` | RSS 订阅 | 订阅技术博客/新闻，定期推送摘要 |
| `bookmark_manage` | 书签管理 | 收藏、分类、搜索网页书签 |
| `knowledge_card` | 知识卡片 | 将检索结果整理成知识卡片 |
| `multi_source_compare` | 多源对比 | 对多个信息源进行交叉验证和对比 |

### 第三批（低优先级，远期）

| Skill | 功能 | 说明 |
|-------|------|------|
| `paper_search` | 文献检索 | 接入 arXiv、知网等学术数据库 |
| `auto_summary` | 自动摘要 | 批量文档自动摘要，生成综述 |
| `mind_map` | 思维导图 | 将检索结果生成思维导图 |

---

## 配置说明

### 核心配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ollama_base_url` | `http://localhost:11434` | Ollama 服务地址 |
| `model_name` | `qwen2.5:1.5b` | 模型名称 |
| `mcp_server_url` | `http://localhost:8002/mcp/v1` | MCP 服务器地址 |
| `max_iterations` | `5` | 最大工具调用次数 |
| `temperature` | `0.5` | 生成温度 |
| `enable_tools` | `true` | 是否启用 MCP 工具 |
| `personality` | `"小探"` | 人格标识 |

### 配置文件加载

```python
import yaml
from federation.adapters.explore_agent import ExploreAgentAdapter

with open("explore_agent_config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

adapter = ExploreAgentAdapter(
    agent_id="explore_01",
    display_name=config["agent"]["display_name"],
    config={
        "ollama_base_url": config["ollama"]["base_url"],
        "model_name": config["ollama"]["model_name"],
        "temperature": config["ollama"]["temperature"],
        "mcp_server_url": config["mcp"]["server_url"],
        "enable_tools": config["mcp"]["enable_tools"],
        "max_iterations": config["performance"]["max_iterations"],
    },
)
```

---

## 故障排查

### 常见问题

**Q: 模型未找到？**
A: 执行 `ollama list` 确认已安装，用 `ollama pull qwen2.5:1.5b` 拉取。

**Q: Ollama 连接失败？**
A: 检查 Ollama 服务是否启动：`ollama serve`，确认端口 11434。

**Q: 回答质量不高？**
A: 1.5B 模型能力有限，适合简单检索和摘要。复杂任务建议交给 7B 模型。

**Q: MCP 工具调用失败（401）？**
A: 需要配置 M8 管理令牌，参考 Codex 部署文档的 MCP 接入配置。

**Q: 响应速度慢？**
A: 1.5B 应该很快。检查 GPU 利用率（`nvidia-smi`），确认 Ollama 使用 GPU。

**Q: 想换更快的模型？**
A: 可以用 `qwen2.5:0.5b`，速度更快，但能力更弱。适合极简单任务。

---

## 测试操作清单

部署完成后，按以下清单验证：

- [ ] **环境检查**
  - [ ] Ollama 服务运行中
  - [ ] qwen2.5:1.5b 模型已安装（986MB）
  - [ ] Python 依赖已安装
  - [ ] GPU 显存充足（至少 2GB 空闲）

- [ ] **基本功能测试**
  - [ ] 健康检查通过
  - [ ] 信息摘要正常（要点清晰）
  - [ ] 要点提取正常（结构化输出）
  - [ ] 概念解释正常（通俗易懂）
  - [ ] 响应速度 < 3 秒

- [ ] **联邦注册测试**
  - [ ] Agent 注册成功
  - [ ] Agent 列表可查询
  - [ ] 人格显示正确（小探）
  - [ ] 能力标签正确

- [ ] **MCP 工具调用测试**（需 M2 配合）
  - [ ] 工具列表获取成功
  - [ ] web_fetch 调用正常
  - [ ] fulltext_search 调用正常
  - [ ] 多轮工具调用正常

- [ ] **性能测试**
  - [ ] 单次响应 < 3 秒
  - [ ] GPU 显存占用 < 2 GB
  - [ ] 连续调用稳定
  - [ ] 内存占用稳定

---

## 三 Agent 协作总览

| Agent | 模型 | 定位 | 显存 | 速度 |
|-------|------|------|------|------|
| **Hermes** | qwen2.5:7b | 通用智能体、复杂推理 | ~5-6 GB | 3-6 秒 |
| **Codex** | qwen2.5:7b | 代码专家 | ~5-6 GB | 5-12 秒 |
| **Explore** | qwen2.5:1.5b | 研究助理、信息检索 | ~1-1.5 GB | 0.8-2 秒 |

**总显存占用**：约 7-8 GB（三个 Agent 共享 GPU，分时复用）
**适用配置**：8GB 显存 + 32GB 内存（完美匹配你的笔记本）

---

## 版本信息

| 项目 | 版本 |
|------|------|
| Explore 适配器 | v1.0.0 |
| 底层模型 | qwen2.5:1.5b (986MB) |
| 人格 | 小探 |
| 协议 | MCP JSON-RPC 2.0 |
| 部署日期 | 2026-07-07 |
