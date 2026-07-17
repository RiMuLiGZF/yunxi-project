"""
预算管控子Agent（Budget-Agent）

封装 BudgetManager，提供预算检查、使用记录、成本感知模型选择、
超预算熔断及成本预警等能力。
"""

from src.budget.agent import BudgetAgent

__all__ = ["BudgetAgent"]
