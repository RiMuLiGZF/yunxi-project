"""端云协同调度内核 (Edge-Cloud Collaborative Dispatch Kernel).

云汐项目模块三 v2.1.0：提供端云数据同步、通信网关、资源监控与硬件桥接能力。
M3 职责边界：sync（数据同步）+ gateway（通信网关）+ resource（资源监控）+ local_data（本地数据）
推理调度相关组件（路由决策、任务编排、推理执行、LLM Provider）归板块1（多Agent集群）管理。
"""

from __future__ import annotations

__version__: str = "1.2.0"
__author__: str = "Yunxi Team"
