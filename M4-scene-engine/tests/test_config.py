"""P2-7: 配置管理测试"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestConfig:
    def test_config_singleton(self):
        from config import get_settings
        cfg1 = get_settings()
        cfg2 = get_settings()
        assert cfg1 is cfg2

    def test_default_port(self):
        from config import get_settings
        cfg = get_settings()
        assert cfg.port == 8004

    def test_security_config(self):
        from config import get_settings
        cfg = get_settings()
        assert hasattr(cfg, "admin_token")

    def test_cors_property(self):
        from config import get_settings
        cfg = get_settings()
        assert isinstance(cfg.cors_origin_list, list)

    def test_env_properties(self):
        from config import get_settings
        cfg = get_settings()
        assert isinstance(cfg.is_development, bool)
        assert isinstance(cfg.is_production, bool)

    def test_scene_config(self):
        from config import get_settings
        cfg = get_settings()
        assert hasattr(cfg, "default_scene")
        assert hasattr(cfg, "auto_switch")
        assert hasattr(cfg, "switch_threshold")
