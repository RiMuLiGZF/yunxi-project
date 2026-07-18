"""M1 Agent Hub - 核心源代码包

M1 多Agent集群调度 - 核心调度中枢
采用联邦调度架构，管理 8 个功能各异的子 Agent。

子模块:
- agents: Agent注册管理
- api: API层
- arbiter/budget/bus/discovery/lifecycle/security/snapshot/voice: 8个子Agent
- orchestration: 编排引擎
- core: 核心调度引擎
- resilience: 弹性与容错
- memory: 记忆系统
- observability: 可观测性
- tools: 工具集成
- config: 配置管理
- models: 数据模型
- federation: 联邦调度
- pool: 分身池
"""

__version__ = "1.2.0"
