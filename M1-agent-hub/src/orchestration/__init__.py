"""M1 orchestration 子模块

编排器版本收敛说明（2026-07-19）：
- 保留版本：v8（稳定版）、v9（最新生产/开发版）
- 归档版本：v2、v3、v4、v5、v7（移至 _deprecated/ 目录）
- 向后兼容：归档版本仍可通过原路径 import，但会触发 DeprecationWarning

推荐使用：
- from src.orchestration.orchestrator_v9 import OrchestratorV9  # 生产版
- from src.orchestration.orchestrator_v8 import OrchestratorV8  # 稳定版（回滚备选）
"""

__all__ = [
    # 保留版本（稳定 + 最新）
    'orchestrator_v8',
    'orchestrator_v9',
    # 已归档版本（向后兼容，会触发 DeprecationWarning）
    'orchestrator_v2',
    'orchestrator_v3',
    'orchestrator_v4',
    'orchestrator_v5',
    'orchestrator_v7',
    # 其他编排模块
    'ensemble_engine',
    'group_chat',
    'swarm_and_innovation',
    'workflow_engine',
]
