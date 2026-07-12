"""
shared.errors 模块单元测试

测试内容：
- YunxiError 基类：实例化、属性访问、字符串表示
- 各子类异常：默认 message 和 code、自定义 message 和 details、继承关系
- error_to_dict() 函数：字典结构、字段完整性、details 为 None 的情况
"""

import pytest

from shared.errors import (
    YunxiError,
    ConfigError,
    ModuleNotFoundError,
    ModuleCallError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    error_to_dict,
)


# ============================================================
# YunxiError 基类测试
# ============================================================

class TestYunxiErrorBase:
    """YunxiError 基类测试"""

    def test_默认实例化属性正确(self):
        """默认参数实例化 YunxiError，属性值正确"""
        err = YunxiError()
        assert err.code == 50000
        assert err.message == "系统内部错误"
        assert err.details == {}

    def test_自定义参数实例化(self):
        """自定义 message、code、details 实例化"""
        details = {"field": "username", "reason": "不能为空"}
        err = YunxiError(message="测试错误", code=40000, details=details)
        assert err.code == 40000
        assert err.message == "测试错误"
        assert err.details == details

    def test_details为None时默认空字典(self):
        """details 传入 None 时，默认为空字典"""
        err = YunxiError(details=None)
        assert err.details == {}

    def test_可被捕获为Exception(self):
        """YunxiError 可被 except Exception 捕获"""
        try:
            raise YunxiError("测试")
        except Exception as e:
            assert isinstance(e, YunxiError)

    def test_str表示格式正确(self):
        """__str__ 返回 [code] message 格式"""
        err = YunxiError(message="测试错误", code=40000)
        assert str(err) == "[40000] 测试错误"

    def test_repr表示包含类名和属性(self):
        """__repr__ 包含类名、code、message、details"""
        err = YunxiError(message="测试", code=50000, details={"k": "v"})
        r = repr(err)
        assert "YunxiError" in r
        assert "code=50000" in r
        assert "'测试'" in r
        assert "{'k': 'v'}" in r

    def test_message作为异常参数(self):
        """Exception 基类的 args 包含 message"""
        err = YunxiError("测试消息")
        assert err.args[0] == "测试消息"


# ============================================================
# 各子类异常测试
# ============================================================

class TestConfigError:
    """ConfigError 配置错误测试"""

    def test_默认值正确(self):
        """默认 message 和 code 正确"""
        err = ConfigError()
        assert err.code == 40002
        assert err.message == "配置错误"
        assert err.details == {}

    def test_自定义参数(self):
        """支持自定义 message、code、details"""
        err = ConfigError(
            message="数据库配置缺失",
            code=40003,
            details={"missing_key": "db.host"},
        )
        assert err.code == 40003
        assert err.message == "数据库配置缺失"
        assert err.details == {"missing_key": "db.host"}

    def test_继承关系正确(self):
        """ConfigError 继承自 YunxiError 和 Exception"""
        err = ConfigError()
        assert isinstance(err, YunxiError)
        assert isinstance(err, Exception)
        assert issubclass(ConfigError, YunxiError)


class TestModuleNotFoundError:
    """ModuleNotFoundError 模块不存在错误测试"""

    def test_默认值正确(self):
        """默认 message 和 code 正确"""
        err = ModuleNotFoundError()
        assert err.code == 40402
        assert err.message == "模块不存在"
        assert err.details == {}

    def test_自定义参数(self):
        """支持自定义 message、code、details"""
        err = ModuleNotFoundError(
            message="技能模块未注册",
            details={"module_id": "skill.unknown"},
        )
        assert err.message == "技能模块未注册"
        assert err.details == {"module_id": "skill.unknown"}

    def test_继承关系正确(self):
        """ModuleNotFoundError 继承自 YunxiError"""
        err = ModuleNotFoundError()
        assert isinstance(err, YunxiError)
        assert issubclass(ModuleNotFoundError, YunxiError)


class TestModuleCallError:
    """ModuleCallError 模块调用失败错误测试"""

    def test_默认值正确(self):
        """默认 message 和 code 正确"""
        err = ModuleCallError()
        assert err.code == 50302
        assert err.message == "模块调用失败"
        assert err.details == {}

    def test_自定义参数(self):
        """支持自定义 message、code、details"""
        err = ModuleCallError(
            message="调用超时",
            details={"target": "m1.agent", "timeout": 30},
        )
        assert err.message == "调用超时"
        assert err.details == {"target": "m1.agent", "timeout": 30}

    def test_继承关系正确(self):
        """ModuleCallError 继承自 YunxiError"""
        err = ModuleCallError()
        assert isinstance(err, YunxiError)
        assert issubclass(ModuleCallError, YunxiError)


class TestValidationError:
    """ValidationError 参数验证错误测试"""

    def test_默认值正确(self):
        """默认 message 和 code 正确"""
        err = ValidationError()
        assert err.code == 40001
        assert err.message == "参数验证失败"
        assert err.details == {}

    def test_自定义参数(self):
        """支持自定义 message、code、details"""
        err = ValidationError(
            message="邮箱格式不正确",
            details={"field": "email", "value": "not-an-email"},
        )
        assert err.message == "邮箱格式不正确"
        assert err.details == {"field": "email", "value": "not-an-email"}

    def test_继承关系正确(self):
        """ValidationError 继承自 YunxiError"""
        err = ValidationError()
        assert isinstance(err, YunxiError)
        assert issubclass(ValidationError, YunxiError)


class TestAuthenticationError:
    """AuthenticationError 认证错误测试"""

    def test_默认值正确(self):
        """默认 message 和 code 正确"""
        err = AuthenticationError()
        assert err.code == 40101
        assert err.message == "认证失败"
        assert err.details == {}

    def test_自定义参数(self):
        """支持自定义 message、code、details"""
        err = AuthenticationError(
            message="Token 已过期",
            details={"expired_at": "2026-01-01T00:00:00Z"},
        )
        assert err.message == "Token 已过期"
        assert err.details == {"expired_at": "2026-01-01T00:00:00Z"}

    def test_继承关系正确(self):
        """AuthenticationError 继承自 YunxiError"""
        err = AuthenticationError()
        assert isinstance(err, YunxiError)
        assert issubclass(AuthenticationError, YunxiError)


class TestAuthorizationError:
    """AuthorizationError 授权错误测试"""

    def test_默认值正确(self):
        """默认 message 和 code 正确"""
        err = AuthorizationError()
        assert err.code == 40301
        assert err.message == "无访问权限"
        assert err.details == {}

    def test_自定义参数(self):
        """支持自定义 message、code、details"""
        err = AuthorizationError(
            message="需要管理员权限",
            details={"required_role": "admin", "current_role": "user"},
        )
        assert err.message == "需要管理员权限"
        assert err.details == {"required_role": "admin", "current_role": "user"}

    def test_继承关系正确(self):
        """AuthorizationError 继承自 YunxiError"""
        err = AuthorizationError()
        assert isinstance(err, YunxiError)
        assert issubclass(AuthorizationError, YunxiError)


# ============================================================
# error_to_dict 函数测试
# ============================================================

class TestErrorToDict:
    """error_to_dict 函数测试"""

    def test_YunxiError转换结构正确(self):
        """YunxiError 转换后包含 code、message、details 字段"""
        err = YunxiError(message="测试错误", code=50000, details={"key": "value"})
        result = error_to_dict(err)
        assert isinstance(result, dict)
        assert result["code"] == 50000
        assert result["message"] == "测试错误"
        assert result["details"] == {"key": "value"}

    def test_包含code字段(self):
        """返回字典必须包含 code 字段"""
        err = ValidationError()
        result = error_to_dict(err)
        assert "code" in result

    def test_包含message字段(self):
        """返回字典必须包含 message 字段"""
        err = ValidationError()
        result = error_to_dict(err)
        assert "message" in result

    def test_包含details字段(self):
        """返回字典必须包含 details 字段"""
        err = ValidationError()
        result = error_to_dict(err)
        assert "details" in result

    def test_details为None时返回空字典(self):
        """details 为 None 时，转换后 details 为空字典"""
        # YunxiError 内部会将 None 转为 {}
        err = YunxiError(message="测试", details=None)
        result = error_to_dict(err)
        assert result["details"] == {}

    def test_普通Exception转换为通用错误(self):
        """普通 Exception 转换为通用内部错误格式"""
        err = ValueError("参数值非法")
        result = error_to_dict(err)
        assert result["code"] == 50000
        assert result["message"] == "参数值非法"
        assert result["details"] == {}

    def test_空消息Exception处理(self):
        """空消息的普通 Exception，message 使用默认值"""
        err = Exception("")
        result = error_to_dict(err)
        assert result["code"] == 50000
        assert result["message"] == "系统内部错误"
        assert result["details"] == {}

    def test_子类异常转换保留子类code(self):
        """各子类异常转换后保留各自的 code"""
        test_cases = [
            (ConfigError(), 40002),
            (ModuleNotFoundError(), 40402),
            (ModuleCallError(), 50302),
            (ValidationError(), 40001),
            (AuthenticationError(), 40101),
            (AuthorizationError(), 40301),
        ]
        for err, expected_code in test_cases:
            result = error_to_dict(err)
            assert result["code"] == expected_code, f"{type(err).__name__} code 不匹配"

    def test_可在异常捕获中使用(self):
        """在 try/except 中正常使用"""
        try:
            raise ValidationError("用户名不能为空", details={"field": "username"})
        except Exception as e:
            result = error_to_dict(e)
        assert result["code"] == 40001
        assert result["message"] == "用户名不能为空"
        assert result["details"] == {"field": "username"}
