# Agent 框架集成（预留）

本目录用于管理云汐系统的 Agent 框架集成。当前为预留目录，后续将逐步扩展。

## 规划中的 Agent 能力

### 1. 内置 Agent 框架
- 单 Agent 对话
- 多 Agent 协作（M1 调度）
- 工具调用（Function Calling）
- RAG 检索增强生成

### 2. 第三方框架集成
- **AutoGen** - 微软多 Agent 框架
- **MetaGPT** - 多角色协作框架
- **LangChain** - LLM 应用开发框架
- **CrewAI** - 角色扮演 Agent 框架

### 3. Agent 能力模块
- 代码生成与调试
- 文档阅读与总结
- 数据分析与可视化
- 网络搜索与信息整合
- 任务规划与执行

## 当前状态

- 基础 LLM 调用：✅ 已实现（`shared/llm_client.py`）
- M1 多 Agent 调度：✅ 模块存在
- 工具调用框架：⏳ 待开发
- 第三方框架集成：⏳ 待开发

## 扩展计划

### Phase 1: 基础 Agent 能力
- 实现 Function Calling 封装
- 内置常用工具集（搜索、计算、文件操作等）
- Agent 会话管理

### Phase 2: 多 Agent 协作
- 完善 M1 调度中心
- Agent 角色定义与分配
- 任务分解与协作协议

### Phase 3: 高级能力
- 长时记忆与学习
- 自我反思与优化
- 自定义 Agent 工作流（M7 积木集成）

## 相关模块

- `M1 模块` - 多Agent集群调度
- `M2 模块` - Skills技能集群
- `shared/llm_client.py` - 统一大模型客户端
- `models/ollama/` - 本地模型管理
