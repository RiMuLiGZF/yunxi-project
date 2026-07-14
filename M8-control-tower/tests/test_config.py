# -*- coding: utf-8 -*-
"""
M8 控制塔 - 配置加载测试

验证 Settings 类可以正常加载，且关键字段（端口等）具有正确的默认值。
"""

from backend.config import Settings, settings


def test_settings_load():
    """验证 Settings 可以正常加载。"""
    s = Settings()
    assert s is not None
    # 应用名称不应为空
    assert s.app_name is not None
    assert len(s.app_name) > 0
    # 版本号不应为空
    assert s.version is not None
    assert len(s.version) > 0
    # 数据库 URL 应为 SQLite 协议
    assert s.database_url.startswith("sqlite:///")


def test_port_default():
    """验证端口默认值为 8008。"""
    # 全局单例也应为 8008
    assert settings.port == 8008
    # 新建实例同样应为 8008
    s = Settings()
    assert s.port == 8008
