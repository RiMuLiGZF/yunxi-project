"""P2-7: 统一错误码测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from errors import ErrorCode, M4Error, error_response, get_error_message, ERROR_MESSAGES


class TestErrorCodeEnum:
    """测试错误码枚举值"""

    def test_success_is_zero(self):
        assert ErrorCode.SUCCESS == 0

    def test_client_error_range(self):
        """4xxxx 应该是客户端错误"""
        assert 40000 <= ErrorCode.BAD_REQUEST < 50000
        assert 40000 <= ErrorCode.SCENE_NOT_FOUND < 50000
        assert 40000 <= ErrorCode.CONTEXT_NOT_FOUND < 50000
        assert 40000 <= ErrorCode.TOKEN_INVALID < 50000

    def test_server_error_range(self):
        """5xxxx 应该是服务端错误"""
        assert 50000 <= ErrorCode.INTERNAL_ERROR < 60000
        assert 50000 <= ErrorCode.SERVICE_UNAVAILABLE < 60000
        assert 50000 <= ErrorCode.TIMEOUT < 60000

    def test_scene_module_codes(self):
        """场景相关应该是 410xx"""
        assert 41000 <= ErrorCode.SCENE_NOT_FOUND < 42000
        assert 41000 <= ErrorCode.SCENE_SWITCH_FAILED < 42000

    def test_context_module_codes(self):
        """上下文相关应该是 420xx"""
        assert 42000 <= ErrorCode.CONTEXT_NOT_FOUND < 43000

    def test_auth_module_codes(self):
        """鉴权相关应该是 440xx"""
        assert 44000 <= ErrorCode.TOKEN_MISSING < 45000
        assert 44000 <= ErrorCode.PERMISSION_DENIED < 45000


class TestErrorMessages:
    """测试错误消息映射"""

    def test_all_codes_have_messages(self):
        """每个错误码都应该有对应的消息"""
        for code in ErrorCode:
            assert code in ERROR_MESSAGES, f"{code.name} 没有错误消息"
            msg = get_error_message(code)
            assert isinstance(msg, str)
            assert len(msg) > 0

    def test_get_error_message_default(self):
        """未知错误码应该返回默认消息"""
        msg = get_error_message(99999)
        assert isinstance(msg, str)


class TestM4Error:
    """测试 M4Error 异常类"""

    def test_create_with_code(self):
        err = M4Error(ErrorCode.SCENE_NOT_FOUND)
        assert err.code == 41001
        assert isinstance(err.message, str)
        assert len(err.message) > 0

    def test_create_with_custom_message(self):
        err = M4Error(ErrorCode.SCENE_NOT_FOUND, "自定义消息")
        assert err.message == "自定义消息"

    def test_to_response(self):
        err = M4Error(ErrorCode.BAD_REQUEST, "参数错了")
        resp = err.to_response()
        assert resp["code"] == 40000
        assert resp["message"] == "参数错了"
        assert "request_id" in resp

    def test_exception_inheritance(self):
        err = M4Error(ErrorCode.INTERNAL_ERROR)
        assert isinstance(err, Exception)
        assert str(err) == err.message


class TestErrorResponse:
    """测试 error_response 工具函数"""

    def test_error_response_structure(self):
        resp = error_response(ErrorCode.BAD_REQUEST, "参数错误")
        assert "code" in resp
        assert "message" in resp
        assert "data" in resp
        assert "request_id" in resp
        assert resp["code"] == 40000

    def test_error_response_default_message(self):
        resp = error_response(ErrorCode.SCENE_NOT_FOUND)
        assert resp["message"] == get_error_message(ErrorCode.SCENE_NOT_FOUND)

    def test_error_response_with_data(self):
        resp = error_response(ErrorCode.BAD_REQUEST, "字段错误", {"field": "name"})
        assert resp["data"] == {"field": "name"}
