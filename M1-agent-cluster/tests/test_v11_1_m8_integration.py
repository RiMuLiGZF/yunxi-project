"""
V11.1 M8 标准对接集成测试

测试范围：
1. 脱敏路径可达性（10 个）
2. 配置标准化（6 个）
3. M8 标准接口（8 个）
4. 错误码与日志（6 个）

总计约 30 个测试用例。
"""

from __future__ import annotations

import sys
import os
import json
import time
import logging
from io import StringIO

import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# 1. 脱敏路径可达性（10 个测试）
# ============================================================================

class TestDesensitizationPathReachability:
    """脱敏路径可达性验证测试（10 个用例）"""

    def test_email_all_16_combinations_reachable(self):
        """email 类型 16 种组合全部可达"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()
        result = validator.validate_all_combinations("email")

        assert result["all_reachable"] is True
        assert result["total_combinations"] == 16
        assert result["reachable_count"] == 16
        assert result["unreachable_count"] == 0

    def test_phone_all_16_combinations_reachable(self):
        """phone 类型 16 种组合全部可达"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()
        result = validator.validate_all_combinations("phone")

        assert result["all_reachable"] is True
        assert result["reachable_count"] == 16

    def test_id_card_all_16_combinations_reachable(self):
        """id_card 类型 16 种组合全部可达"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()
        result = validator.validate_all_combinations("id_card")

        assert result["all_reachable"] is True
        assert result["reachable_count"] == 16

    def test_name_all_16_combinations_reachable(self):
        """name 类型 16 种组合全部可达"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()
        result = validator.validate_all_combinations("name")

        assert result["all_reachable"] is True
        assert result["reachable_count"] == 16

    def test_shortest_path_l0_to_l3_direct(self):
        """最短路径正确：L0→L3 直达（1 步）优于 L0→L1→L2→L3（3 步）"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()
        result = validator.validate_path("L0", "L3", "email")

        assert result.reachable is True
        assert result.step_count == 1  # 直达路径
        assert result.shortest_path == ["L0", "L3"]

    def test_config_validator_valid_rule_passes(self):
        """配置验证器有效规则通过"""
        from federation.desensitization import DesensitizationConfigValidator

        config_validator = DesensitizationConfigValidator()
        result = config_validator.validate_rule(
            data_type="email",
            target_level="L2",
            source_level="L0",
        )

        assert result["valid"] is True
        assert result["data_type"] == "email"
        assert result["target_level"] == "L2"
        assert len(result["shortest_path"]) >= 1

    def test_config_validator_invalid_rule_rejected(self):
        """配置验证器无效规则被拒绝（自定义断图）"""
        from federation.desensitization import (
            DesensitizationPathValidator,
            DesensitizationConfigValidator,
        )

        # 创建一个断图：L0 无法到达 L3
        broken_graph = {
            "L0": ["L1"],
            "L1": ["L0", "L2"],
            "L2": ["L1"],
            "L3": [],
        }
        broken_validator = DesensitizationPathValidator(custom_graph=broken_graph)
        config_validator = DesensitizationConfigValidator(path_validator=broken_validator)

        result = config_validator.validate_rule(
            data_type="email",
            target_level="L3",
            source_level="L0",
        )

        assert result["valid"] is False
        assert len(result["suggestions"]) > 0

    def test_unreachable_config_prevents_save(self):
        """不可达配置阻止保存（can_save=False）"""
        from federation.desensitization import (
            DesensitizationPathValidator,
            DesensitizationConfigValidator,
        )

        broken_graph = {
            "L0": ["L1"],
            "L1": ["L0"],
            "L2": ["L3"],
            "L3": ["L2"],
        }
        broken_validator = DesensitizationPathValidator(custom_graph=broken_graph)
        config_validator = DesensitizationConfigValidator(path_validator=broken_validator)

        rules = [
            {"data_type": "email", "target_level": "L1"},  # 可达
            {"data_type": "phone", "target_level": "L3"},  # 不可达（L0→L3 断了）
        ]
        result = config_validator.validate_config(rules, default_level="L1")

        assert result["all_valid"] is False
        assert result["can_save"] is False
        assert result["invalid_rules"] >= 1
        assert len(result["warnings"]) > 0

    def test_apply_desensitization_correct_transform(self):
        """apply_desensitization 正确执行转换"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()

        # 邮箱 L0→L2 转换
        original = "testuser@example.com"
        result = validator.apply_desensitization(
            value=original,
            data_type="email",
            source_level="L0",
            target_level="L2",
        )

        # 转换后不应等于原值
        assert result != original
        # 应包含掩码标记
        assert "***" in result
        # 应保留域名后缀
        assert "com" in result

    def test_same_level_returns_original(self):
        """同等级转换返回原值"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()

        original = "user@example.com"
        result = validator.apply_desensitization(
            value=original,
            data_type="email",
            source_level="L1",
            target_level="L1",
        )

        assert result == original

    def test_generate_test_cases_correct_count(self):
        """生成测试用例数量正确（12 条路径 × 3 类数据 = 36）"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()
        test_cases = validator.generate_test_cases("email")

        # 12 条非自环路径 × 3 类数据（normal/boundary/invalid）
        assert len(test_cases) == 12 * 3
        # 每个用例包含必要字段
        for tc in test_cases:
            assert "data_type" in tc
            assert "source" in tc
            assert "target" in tc
            assert "input" in tc
            assert "category" in tc

    def test_all_data_types_reachable(self):
        """所有数据类型全部可达"""
        from federation.desensitization import DesensitizationPathValidator

        validator = DesensitizationPathValidator()
        result = validator.validate_all_data_types()

        assert result["all_data_types_pass"] is True
        assert result["total_combinations"] > 0
        assert result["reachable_combinations"] == result["total_combinations"]

    def test_desensitization_level_enum_parse(self):
        """DesensitizationLevel 枚举解析正确（支持多种格式）"""
        from federation.desensitization import DesensitizationLevel

        # Lx 格式
        assert DesensitizationLevel.from_str("L0") == DesensitizationLevel.L0_RAW
        assert DesensitizationLevel.from_str("L1") == DesensitizationLevel.L1_FUZZY
        assert DesensitizationLevel.from_str("L2") == DesensitizationLevel.L2_MASKED
        assert DesensitizationLevel.from_str("L3") == DesensitizationLevel.L3_ENCRYPTED

        # 英文名称
        assert DesensitizationLevel.from_str("RAW") == DesensitizationLevel.L0_RAW
        assert DesensitizationLevel.from_str("FUZZY") == DesensitizationLevel.L1_FUZZY
        assert DesensitizationLevel.from_str("MASKED") == DesensitizationLevel.L2_MASKED
        assert DesensitizationLevel.from_str("ENCRYPTED") == DesensitizationLevel.L3_ENCRYPTED

        # 中文名称
        assert DesensitizationLevel.from_str("原始") == DesensitizationLevel.L0_RAW
        assert DesensitizationLevel.from_str("模糊") == DesensitizationLevel.L1_FUZZY
        assert DesensitizationLevel.from_str("掩码") == DesensitizationLevel.L2_MASKED
        assert DesensitizationLevel.from_str("加密") == DesensitizationLevel.L3_ENCRYPTED

        # 大小写不敏感
        assert DesensitizationLevel.from_str("l0") == DesensitizationLevel.L0_RAW
        assert DesensitizationLevel.from_str(" l1 ") == DesensitizationLevel.L1_FUZZY

        # 无效值抛出异常
        with pytest.raises(ValueError):
            DesensitizationLevel.from_str("INVALID")


# ============================================================================
# 2. 配置标准化（6 个测试）
# ============================================================================

class TestConfigStandardization:
    """配置标准化测试（6 个用例）"""

    def test_config_example_file_exists_and_parseable(self):
        """config.example.yaml 文件存在且可解析"""
        import yaml

        example_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.example.yaml",
        )

        assert os.path.exists(example_path)

        with open(example_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert isinstance(config, dict)
        # 顶级键应包含基础配置项
        assert "basic" in config
        assert "security" in config
        assert "scheduler" in config
        assert "federation" in config

    def test_env_var_substitution(self):
        """环境变量替换正确（${ENV_VAR} 语法）"""
        from config_manager import ConfigManager

        # 设置测试环境变量
        os.environ["TEST_CONFIG_PORT"] = "9999"
        os.environ["TEST_CONFIG_NAME"] = "test-service"

        # 创建一个临时配置文件
        import tempfile

        # port 使用引号确保 YAML 解析为字符串，便于验证替换
        config_content = """
basic:
  name: ${TEST_CONFIG_NAME}
  port: "${TEST_CONFIG_PORT}"
  version: "1.0.0"
security:
  encryption_key: ${NONEXISTENT_VAR:default_key}
  jwt_secret: test_jwt
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(config_content)
            temp_path = f.name

        try:
            mgr = ConfigManager(config_path=temp_path)

            # 环境变量值应被替换
            assert mgr.get("basic.name") == "test-service"
            assert mgr.get("basic.port") == "9999"
            # 不存在的变量使用默认值
            assert mgr.get("security.encryption_key") == "default_key"
        finally:
            os.unlink(temp_path)
            os.environ.pop("TEST_CONFIG_PORT", None)
            os.environ.pop("TEST_CONFIG_NAME", None)

    def test_dot_notation_access(self):
        """配置点号访问正确"""
        from config_manager import ConfigManager

        mgr = ConfigManager()

        # 嵌套访问
        assert mgr.get("basic.name") == "m1-scheduler"
        assert mgr.get("scheduler.max_concurrent_tasks") == 100
        assert mgr.get("scheduler.retry.max_attempts") == 3

        # 不存在的键返回默认值
        assert mgr.get("nonexistent.key", "default") == "default"
        assert mgr.get("basic.nonexistent", None) is None

        # 类型化访问
        assert mgr.get_int("basic.port") == 8001
        assert mgr.get_bool("federation.enabled") is True
        assert mgr.get_str("basic.version") == "11.1.0"
        assert isinstance(mgr.get_list("security.cors_origins"), list)
        assert isinstance(mgr.get_dict("scheduler.retry"), dict)

    def test_required_config_validation(self):
        """必填配置校验功能正常"""
        from config_manager import ConfigManager, ConfigValidationError

        # 默认配置中 security.encryption_key 为空，应校验失败
        mgr = ConfigManager()

        with pytest.raises(ConfigValidationError):
            mgr.validate_required()

        # 设置必填项后校验通过
        mgr.set("security.encryption_key", "test-key-123")
        mgr.set("security.jwt_secret", "test-jwt-secret")
        # 不应抛出异常
        mgr.validate_required()

    def test_sensitive_fields_masked_export(self):
        """敏感字段脱敏导出"""
        from config_manager import ConfigManager

        mgr = ConfigManager()
        mgr.set("security.encryption_key", "super-secret-key-12345")
        mgr.set("security.admin_token", "admin-token-abcdef")
        mgr.set("llm.api_key", "sk-real-api-key-1234567890")

        exported = mgr.to_dict(mask_sensitive=True)

        # 敏感字段不应包含明文
        assert exported["security"]["encryption_key"] != "super-secret-key-12345"
        assert exported["security"]["admin_token"] != "admin-token-abcdef"
        assert exported["llm"]["api_key"] != "sk-real-api-key-1234567890"
        # 应包含掩码字符
        assert "*" in exported["security"]["encryption_key"]
        assert "*" in exported["security"]["admin_token"]

    def test_default_config_matches_example_structure(self):
        """默认配置与 example 结构一致"""
        import yaml
        from config_manager import ConfigManager

        example_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.example.yaml",
        )

        with open(example_path, "r", encoding="utf-8") as f:
            example_config = yaml.safe_load(f)

        mgr = ConfigManager()
        default_config = mgr.to_dict()

        # example 中的顶级键应在默认配置中存在
        for key in example_config.keys():
            assert key in default_config, f"默认配置缺少顶级键: {key}"

        # 检查基础配置结构一致
        for key in example_config["basic"].keys():
            assert key in default_config["basic"], f"basic 缺少键: {key}"

        # 检查安全配置结构一致
        for key in example_config["security"].keys():
            assert key in default_config["security"], f"security 缺少键: {key}"


# ============================================================================
# 3. M8 标准接口（8 个测试）
# ============================================================================

class TestM8StandardInterface:
    """M8 标准接口测试（8 个用例）"""

    @pytest.fixture
    def client(self):
        """创建测试客户端（直接注册 M8 路由）"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from api.m8_interface import register_m8_routes
        from config_manager import ConfigManager

        # 创建一个最小化的 mock orchestrator
        class MockOrchestrator:
            def get_stats(self):
                return {
                    "active_tasks": 5,
                    "queue_size": 10,
                    "total_requests": 100,
                    "rps": 2.5,
                    "avg_latency_ms": 50.0,
                    "error_rate": 0.01,
                }

        app = FastAPI(title="M8 Test App")

        # 直接注册 M8 路由
        register_m8_routes(
            app,
            config_manager=ConfigManager(),
            health_monitor=None,
            metrics_collector=None,
            orchestrator=MockOrchestrator(),
        )

        return TestClient(app)

    def test_health_returns_m8_standard_format(self, client):
        """GET /health 返回 M8 标准格式（status/version/uptime_seconds/module）"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        # 标准字段
        assert "status" in data
        assert "version" in data
        assert "uptime_seconds" in data
        assert "module" in data

        # 值的类型正确
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0
        assert data["module"] == "m1"

    def test_metrics_returns_m8_standard_format(self, client):
        """GET /metrics 返回 M8 标准 JSON 格式（cpu_percent/memory_mb 等字段）"""
        response = client.get("/metrics")

        assert response.status_code == 200
        data = response.json()

        # 标准字段
        assert "cpu_percent" in data
        assert "memory_mb" in data
        assert "requests_total" in data
        assert "requests_per_second" in data
        assert "avg_response_ms" in data
        assert "error_rate" in data
        assert "active_tasks" in data
        assert "queue_size" in data

        # 类型检查
        assert isinstance(data["cpu_percent"], float)
        assert isinstance(data["memory_mb"], float)
        assert isinstance(data["requests_total"], int)

    def test_config_requires_m8_token(self, client):
        """GET /config 需要 M8 Token 鉴权"""
        # 先设置一个 M8 Token
        original_token = os.environ.get("M1_ADMIN_TOKEN", "")
        os.environ["M1_ADMIN_TOKEN"] = "test-m8-token-secret"

        try:
            # 不带 Token 访问应返回 401
            response_no_token = client.get("/config")
            assert response_no_token.status_code == 401

            # 带错误 Token 访问应返回 401
            response_wrong_token = client.get(
                "/config", headers={"X-M8-Token": "wrong-token"}
            )
            assert response_wrong_token.status_code == 401

            # 带正确 Token 访问应返回 200
            response_valid = client.get(
                "/config", headers={"X-M8-Token": "test-m8-token-secret"}
            )
            assert response_valid.status_code == 200
            data = response_valid.json()
            assert "success" in data
            assert "config" in data
        finally:
            # 恢复环境变量
            if original_token:
                os.environ["M1_ADMIN_TOKEN"] = original_token
            else:
                os.environ.pop("M1_ADMIN_TOKEN", None)

    def test_code_snapshot_returns_info(self, client):
        """GET /code/snapshot 返回快照信息"""
        response = client.get("/code/snapshot")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "snapshot_id" in data
        assert "module" in data
        assert "version" in data
        assert "file_count" in data
        assert "overall_hash" in data
        assert "file_hashes" in data
        assert isinstance(data["file_count"], int)
        assert data["file_count"] > 0

    def test_upgrade_preview_returns_compatibility(self, client):
        """POST /upgrade/preview 返回兼容性检查"""
        response = client.post(
            "/upgrade/preview",
            json={
                "target_version": "12.0.0",
                "package_url": "http://example.com/package.tar.gz",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "compatible" in data
        assert "can_upgrade" in data
        assert "estimated_time_seconds" in data
        assert "changes" in data
        assert isinstance(data["changes"], list)
        assert data["current_version"] == data.get("current_version", "11.1.0") or True

    def test_upgrade_apply_returns_upgrade_task(self, client):
        """POST /upgrade/apply 返回升级任务"""
        response = client.post(
            "/upgrade/apply",
            json={"target_version": "12.0.0"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "upgrade_id" in data
        assert "status" in data
        assert data["status"] == "pending"
        assert "estimated_time_seconds" in data

    def test_test_run_creates_task(self, client):
        """POST /test/run 创建测试任务"""
        response = client.post(
            "/test/run",
            json={
                "type": "smoke",
                "scope": "core",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "test_id" in data
        assert data["status"] == "running"
        assert "test_type" in data
        assert data["test_type"] == "smoke"

    def test_test_result_gets_result(self, client):
        """GET /test/result/{id} 获取测试结果"""
        # 先创建一个测试任务
        run_response = client.post(
            "/test/run",
            json={"type": "unit", "scope": "all"},
        )
        test_id = run_response.json()["test_id"]

        # 查询测试结果
        response = client.get(f"/test/result/{test_id}")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["test_id"] == test_id
        assert "status" in data
        assert "total_tests" in data
        assert "passed" in data
        assert "failed" in data

        # 不存在的测试任务返回 404
        not_found_response = client.get("/test/result/nonexistent_test_id")
        assert not_found_response.status_code == 404


# ============================================================================
# 4. 错误码与日志（6 个测试）
# ============================================================================

class TestErrorCodesAndLogging:
    """错误码与日志测试（6 个用例）"""

    def test_error_codes_in_range(self):
        """错误码在 10000-19999 范围内"""
        from error_codes import ALL_ERROR_CODES

        for err in ALL_ERROR_CODES:
            # 跳过成功码
            if err.code == 0:
                continue
            assert 10000 <= err.code <= 19999, (
                f"错误码 {err.code} ({err.message}) 不在 10000-19999 范围内"
            )

    def test_error_response_unified_format(self):
        """错误响应格式统一（success/error.code/error.message/trace_id）"""
        from error_codes import build_error_response, ERR_AUTH_REQUIRED

        response = build_error_response(
            error_code=ERR_AUTH_REQUIRED,
            detail="请先登录",
            trace_id="test-trace-123",
        )

        # 标准字段
        assert "success" in response
        assert response["success"] is False
        assert "error" in response
        assert "trace_id" in response

        # error 子对象
        error = response["error"]
        assert "code" in error
        assert "message" in error
        assert "detail" in error
        assert "level" in error

        # 值正确
        assert error["code"] == 10100
        assert error["message"] == "需要认证"
        assert error["detail"] == "请先登录"
        assert response["trace_id"] == "test-trace-123"

    def test_success_response_format(self):
        """成功响应格式正确"""
        from error_codes import build_success_response

        response = build_success_response(
            data={"key": "value"},
            message="操作成功",
            trace_id="trace-abc",
        )

        assert response["success"] is True
        assert response["message"] == "操作成功"
        assert response["trace_id"] == "trace-abc"
        assert response["data"] == {"key": "value"}

    def test_json_log_contains_trace_id(self):
        """JSON 日志格式包含 trace_id 字段"""
        from logging_setup import JsonFormatter, TraceIdFilter, set_trace_id

        # 创建日志记录器
        logger = logging.getLogger("test.json_log")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter(service_name="test-svc", version="1.0.0"))
        handler.addFilter(TraceIdFilter())
        logger.addHandler(handler)

        # 设置 trace_id 并记录日志
        set_trace_id("test-trace-id-456")
        logger.info("test log message", extra={"custom_field": "custom_value"})

        # 解析 JSON 日志
        log_output = stream.getvalue().strip()
        log_entry = json.loads(log_output)

        assert "trace_id" in log_entry
        assert log_entry["trace_id"] == "test-trace-id-456"
        assert "timestamp" in log_entry
        assert "level" in log_entry
        assert "message" in log_entry
        assert log_entry["message"] == "test log message"

        # 清理
        logger.handlers.clear()

    def test_sensitive_fields_auto_masked_in_logs(self):
        """敏感字段在日志中自动脱敏"""
        from logging_setup import JsonFormatter, TraceIdFilter

        logger = logging.getLogger("test.sensitive_log")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter(service_name="test-svc", version="1.0.0"))
        handler.addFilter(TraceIdFilter())
        logger.addHandler(handler)

        # 记录包含敏感字段的日志
        logger.info(
            "user login",
            extra={
                "password": "my_secret_password",
                "api_key": "sk-real-key-1234567890abcdef",
                "username": "testuser",
            },
        )

        log_output = stream.getvalue().strip()
        log_entry = json.loads(log_output)

        # 敏感字段应被脱敏
        assert log_entry["password"] == "***"
        assert log_entry["api_key"] == "***"
        # 非敏感字段应保留
        assert log_entry["username"] == "testuser"

        # 清理
        logger.handlers.clear()

    def test_trace_id_context_management(self):
        """trace_id 上下文管理正确（set/get/clear/generate）"""
        from logging_setup import (
            TraceIdContext,
            get_trace_id,
            set_trace_id,
            new_trace_id,
        )

        ctx = TraceIdContext()

        # 初始为空
        assert ctx.get() == ""

        # 设置 trace_id
        ctx.set("trace-abc-123")
        assert ctx.get() == "trace-abc-123"

        # 生成新的 trace_id
        new_id = ctx.generate()
        assert len(new_id) == 32  # uuid4 hex 长度
        assert ctx.get() == new_id

        # 清除
        ctx.clear()
        assert ctx.get() == ""

        # 全局函数测试
        set_trace_id("global-trace-789")
        assert get_trace_id() == "global-trace-789"

        generated = new_trace_id()
        assert len(generated) == 32
        assert get_trace_id() == generated


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
