"""
A2A通信总线子Agent（Bus-Agent）

封装 MessageBus，提供优先级路由与DLQ管理能力。
支持A2A消息格式转换，对外暴露统一的消息发布/订阅/路由接口。
"""

from bus.agent import BusAgent

__all__ = ["BusAgent"]
