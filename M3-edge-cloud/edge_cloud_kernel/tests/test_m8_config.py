"""M8 管理接口测试 — 配置管理.

测试类别：配置管理接口(6) = 6个
"""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from edge_cloud_kernel.m8_api.config_endpoints import ConfigManager, SENSITIVE_KEYS


class TestConfigManager:
    """配置管理器测试."""

    def test_get_config_structure(self):
        """测试获取配置结构完整."""
        mgr = ConfigManager()
        config = mgr.get_config_sanitized()
        assert "basic" in config
        assert "security" in config
        assert "sync" in config
        assert "storage" in config
        assert "offline" in config
        assert "database" in config
        assert "logging" in config
        assert "devices" in config

    def test_sensitive_fields_masked(self):
        """测试敏感字段脱敏."""
        mgr = ConfigManager()
        # 先设置敏感值
        mgr._config["security"]["encryption_key"] = "super_secret_key"
        mgr._config["security"]["admin_token"] = "admin_token_123"
        config = mgr.get_config_sanitized()
        assert config["security"]["encryption_key"] == "***"
        assert config["security"]["admin_token"] == "***"

    def test_update_config_success(self):
        """测试成功更新配置."""
        mgr = ConfigManager()
        ok, result = mgr.update_config({
            "sync.mode": "manual",
            "sync.interval": 120,
        })
        assert ok is True
        assert "sync.mode" in result["updated_keys"]
        assert "sync.interval" in result["updated_keys"]
        assert result["restart_required"] is False
        assert mgr.get("sync.mode") == "manual"
        assert mgr.get("sync.interval") == 120

    def test_update_config_sensitive_rejected(self):
        """测试敏感字段不允许通过 API 更新."""
        mgr = ConfigManager()
        ok, result = mgr.update_config({
            "security.encryption_key": "new_key",
            "sync.mode": "manual",
        })
        assert ok is True  # 部分成功
        assert "security.encryption_key" in result["rejected_keys"]
        assert "sync.mode" in result["updated_keys"]
        # 敏感字段值未变
        assert mgr.get("security.encryption_key") != "new_key"

    def test_update_config_nonexistent_key(self):
        """测试更新不存在的 key 被拒绝."""
        mgr = ConfigManager()
        ok, result = mgr.update_config({
            "nonexistent.key": "value",
        })
        assert ok is True
        assert len(result["rejected_keys"]) == 1
        assert "nonexistent.key" in result["rejected_keys"][0]

    def test_update_config_restart_required(self):
        """测试需要重启的配置更新提示."""
        mgr = ConfigManager()
        ok, result = mgr.update_config({
            "basic.port": 9000,
        })
        assert ok is True
        assert result["restart_required"] is True
        assert mgr.get("basic.port") == 9000

    def test_config_load_from_yaml(self):
        """测试从 YAML 文件加载配置."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({
                "basic": {"port": 9001, "log_level": "debug"},
                "sync": {"interval": 30},
            }, f)
            config_path = f.name

        try:
            mgr = ConfigManager(config_path=config_path)
            assert mgr.get("basic.port") == 9001
            assert mgr.get("basic.log_level") == "debug"
            assert mgr.get("sync.interval") == 30
            # 未覆盖的字段使用默认值
            assert mgr.get("basic.name") == "m3-sync"
        finally:
            os.unlink(config_path)

    def test_audit_log(self):
        """测试审计日志记录."""
        mgr = ConfigManager()
        assert len(mgr.audit_log) == 0
        mgr.update_config({"sync.mode": "manual"}, request_id="audit-test-001")
        assert len(mgr.audit_log) == 1
        assert mgr.audit_log[0]["request_id"] == "audit-test-001"
        assert "sync.mode" in mgr.audit_log[0]["updated_keys"]

    def test_dot_key_nested(self):
        """测试嵌套点路径更新."""
        mgr = ConfigManager()
        ok, result = mgr.update_config({
            "security.e2ee.enabled": False,
        })
        assert ok is True
        assert mgr.get("security.e2ee.enabled") is False

    def test_get_default(self):
        """测试 get 方法默认值."""
        mgr = ConfigManager()
        assert mgr.get("nonexistent.path", "default") == "default"
        assert mgr.get("basic.name") == "m3-sync"
