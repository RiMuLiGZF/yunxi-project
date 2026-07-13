"""
云汐内核 - 任务编排子Agent（Orchestrator-Agent）

负责将用户请求解析为 TaskDAG（有向无环任务图），
管理DAG生命周期，协调子Agent执行团队。
"""

from orchestrator.agent import OrchestratorAgent

__all__ = ["OrchestratorAgent"]
