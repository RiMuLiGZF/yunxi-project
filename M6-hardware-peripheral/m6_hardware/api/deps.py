"""
M6 硬件外设 - API 依赖注入
从 request.app.state 获取各服务实例，替代全局单例模式

FastAPI lifespan 启动时将服务实例存入 app.state，
API 路由通过 Depends() 从请求上下文中获取，确保线程安全。
"""

from fastapi import Request

from ..config import M6Config
from ..services.device_manager import DeviceManager
from ..services.data_collector import DataCollector
from ..services.notification import NotificationService
from ..realtime.sse_manager import SSEManager


def get_config(request: Request) -> M6Config:
    """获取配置实例（从 app.state 中获取）

    Returns:
        M6Config 配置实例
    """
    return request.app.state.config


def get_device_manager(request: Request) -> DeviceManager:
    """获取设备管理器实例（从 app.state 中获取）

    Returns:
        DeviceManager 设备管理器实例
    """
    return request.app.state.device_manager


def get_data_collector(request: Request) -> DataCollector:
    """获取数据采集服务实例（从 app.state 中获取）

    Returns:
        DataCollector 数据采集服务实例
    """
    return request.app.state.data_collector


def get_sse_manager(request: Request) -> SSEManager:
    """获取 SSE 管理器实例（从 app.state 中获取）

    Returns:
        SSEManager SSE 推送管理器实例
    """
    return request.app.state.sse_manager


def get_notification_service(request: Request) -> NotificationService:
    """获取通知服务实例（从 app.state 中获取）

    Returns:
        NotificationService 通知推送服务实例
    """
    return request.app.state.notification_service
