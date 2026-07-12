"""
shared.responses 模块单元测试

测试内容：
- ApiResponse.success()：结构正确性、data 为 None、request_id 自动生成
- ApiResponse.error()：错误结构、details 为 None
- ApiResponse.to_dict()：字典格式
- ApiResponse.is_success 属性：成功/错误判断
- 错误码常量：值验证
"""

import pytest

from shared.responses import (
    ApiResponse,
    SUCCESS,
    ERROR_INVALID_PARAMS,
    ERROR_UNAUTHORIZED,
    ERROR_FORBIDDEN,
    ERROR_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_MODULE_UNAVAILABLE,
)


# ============================================================
# 错误码常量测试
# ============================================================

class TestErrorCodeConstants:
    """错误码常量测试"""

    def test_SUCCESS值为0(self):
        """SUCCESS 常量值为 0"""
        assert SUCCESS == 0

    def test_ERROR_INVALID_PARAMS值(self):
        """参数错误码为 40001"""
        assert ERROR_INVALID_PARAMS == 40001

    def test_ERROR_UNAUTHORIZED值(self):
        """未认证错误码为 40101"""
        assert ERROR_UNAUTHORIZED == 40101

    def test_ERROR_FORBIDDEN值(self):
        """无权限错误码为 40301"""
        assert ERROR_FORBIDDEN == 40301

    def test_ERROR_NOT_FOUND值(self):
        """资源不存在错误码为 40401"""
        assert ERROR_NOT_FOUND == 40401

    def test_ERROR_INTERNAL值(self):
        """内部错误码为 50001"""
        assert ERROR_INTERNAL == 50001

    def test_ERROR_MODULE_UNAVAILABLE值(self):
        """模块不可用错误码为 50301"""
        assert ERROR_MODULE_UNAVAILABLE == 50301

    def test_所有错误码非0(self):
        """所有错误码常量均不为 0"""
        error_codes = [
            ERROR_INVALID_PARAMS,
            ERROR_UNAUTHORIZED,
            ERROR_FORBIDDEN,
            ERROR_NOT_FOUND,
            ERROR_INTERNAL,
            ERROR_MODULE_UNAVAILABLE,
        ]
        for code in error_codes:
            assert code != 0


# ============================================================
# ApiResponse.success() 测试
# ============================================================

class TestApiResponseSuccess:
    """ApiResponse.success() 方法测试"""

    def test_默认成功响应结构(self):
        """默认参数创建成功响应，结构正确"""
        resp = ApiResponse.success()
        assert resp.code == SUCCESS
        assert resp.code == 0
        assert resp.message == "操作成功"
        assert resp.data is None
        assert resp.details == {}
        assert resp.request_id is None

    def test_带data的成功响应(self):
        """带 data 的成功响应"""
        data = {"user": "alice", "id": 1}
        resp = ApiResponse.success(data=data)
        assert resp.data == data
        assert resp.code == 0

    def test_data为None时正常(self):
        """data 为 None 时正常工作"""
        resp = ApiResponse.success(data=None)
        assert resp.data is None
        assert resp.code == 0

    def test_自定义message(self):
        """自定义成功消息"""
        resp = ApiResponse.success(message="获取用户信息成功")
        assert resp.message == "获取用户信息成功"

    def test_带request_id(self):
        """指定 request_id"""
        resp = ApiResponse.success(request_id="req-123456")
        assert resp.request_id == "req-123456"

    def test_完整参数成功响应(self):
        """所有参数都指定的成功响应"""
        data = {"items": [1, 2, 3]}
        resp = ApiResponse.success(
            data=data,
            message="查询成功",
            request_id="req-abc",
        )
        assert resp.code == 0
        assert resp.message == "查询成功"
        assert resp.data == data
        assert resp.request_id == "req-abc"


# ============================================================
# ApiResponse.error() 测试
# ============================================================

class TestApiResponseError:
    """ApiResponse.error() 方法测试"""

    def test_默认错误响应结构(self):
        """默认参数创建错误响应，结构正确"""
        resp = ApiResponse.error()
        assert resp.code == ERROR_INTERNAL
        assert resp.code != 0
        assert resp.message == "操作失败"
        assert resp.details == {}
        assert resp.data is None
        assert resp.request_id is None

    def test_自定义错误码和消息(self):
        """自定义错误码和消息"""
        resp = ApiResponse.error(code=40001, message="参数错误")
        assert resp.code == 40001
        assert resp.message == "参数错误"

    def test_带details的错误响应(self):
        """带 details 的错误响应"""
        details = {"field": "name", "reason": "不能为空"}
        resp = ApiResponse.error(
            code=40001,
            message="参数验证失败",
            details=details,
        )
        assert resp.details == details

    def test_details为None时默认为空字典(self):
        """details 为 None 时默认为空字典"""
        resp = ApiResponse.error(details=None)
        assert resp.details == {}

    def test_带request_id的错误响应(self):
        """指定 request_id 的错误响应"""
        resp = ApiResponse.error(request_id="err-789")
        assert resp.request_id == "err-789"

    def test_完整参数错误响应(self):
        """所有参数都指定的错误响应"""
        details = {"missing_fields": ["email", "password"]}
        resp = ApiResponse.error(
            code=ERROR_INVALID_PARAMS,
            message="缺少必填字段",
            details=details,
            request_id="req-err-001",
        )
        assert resp.code == ERROR_INVALID_PARAMS
        assert resp.message == "缺少必填字段"
        assert resp.details == details
        assert resp.request_id == "req-err-001"


# ============================================================
# ApiResponse.to_dict() 测试
# ============================================================

class TestApiResponseToDict:
    """ApiResponse.to_dict() 方法测试"""

    def test_成功响应转字典(self):
        """成功响应转换为字典格式正确"""
        resp = ApiResponse.success(data={"id": 1}, request_id="req-1")
        d = resp.to_dict()
        assert isinstance(d, dict)
        assert d["code"] == 0
        assert d["message"] == "操作成功"
        assert d["data"] == {"id": 1}
        assert d["request_id"] == "req-1"

    def test_错误响应转字典包含details(self):
        """错误响应转换为字典包含 details 字段"""
        details = {"field": "name"}
        resp = ApiResponse.error(code=40001, message="参数错误", details=details)
        d = resp.to_dict()
        assert d["code"] == 40001
        assert d["message"] == "参数错误"
        assert d["details"] == details

    def test_无details时不包含details字段(self):
        """details 为空时，to_dict 不包含 details 键"""
        resp = ApiResponse.success(data={"a": 1})
        d = resp.to_dict()
        assert "details" not in d

    def test_无request_id时不包含request_id字段(self):
        """request_id 为 None 时，to_dict 不包含 request_id 键"""
        resp = ApiResponse.success(data={"a": 1})
        d = resp.to_dict()
        assert "request_id" not in d

    def test_data为None时仍包含data字段(self):
        """data 为 None 时，to_dict 仍包含 data 键"""
        resp = ApiResponse.success()
        d = resp.to_dict()
        assert "data" in d
        assert d["data"] is None

    def test_错误响应也包含data字段且为None(self):
        """错误响应 to_dict 也包含 data 字段，值为 None"""
        resp = ApiResponse.error(code=50001, message="服务器错误")
        d = resp.to_dict()
        assert "data" in d
        assert d["data"] is None


# ============================================================
# ApiResponse.is_success 属性测试
# ============================================================

class TestApiResponseIsSuccess:
    """ApiResponse.is_success 属性测试"""

    def test_成功响应返回True(self):
        """成功响应 is_success 为 True"""
        resp = ApiResponse.success()
        assert resp.is_success is True

    def test_错误响应返回False(self):
        """错误响应 is_success 为 False"""
        resp = ApiResponse.error()
        assert resp.is_success is False

    def test_code为0时为成功(self):
        """code 为 0 时 is_success 为 True"""
        resp = ApiResponse(code=0)
        assert resp.is_success is True

    def test_code非0时为失败(self):
        """code 非 0 时 is_success 为 False"""
        for code in [-1, 1, 40001, 50001, 99999]:
            resp = ApiResponse(code=code)
            assert resp.is_success is False, f"code={code} 时 is_success 应为 False"


# ============================================================
# ApiResponse 其他方法测试
# ============================================================

class TestApiResponseMisc:
    """ApiResponse 字符串表示等杂项测试"""

    def test_str表示格式正确(self):
        """__str__ 返回格式正确"""
        resp = ApiResponse.success(message="测试成功")
        s = str(resp)
        assert "ApiResponse" in s
        assert "code=0" in s
        assert "'测试成功'" in s

    def test_repr表示包含完整信息(self):
        """__repr__ 包含完整属性信息"""
        resp = ApiResponse.success(data={"k": "v"}, request_id="req-1")
        r = repr(resp)
        assert "ApiResponse" in r
        assert "code=0" in r
        assert "request_id=" in r

    def test_直接构造函数实例化(self):
        """直接通过构造函数创建实例"""
        resp = ApiResponse(
            code=200,
            message="自定义",
            data={"key": "value"},
            details={"extra": "info"},
            request_id="custom-1",
        )
        assert resp.code == 200
        assert resp.message == "自定义"
        assert resp.data == {"key": "value"}
        assert resp.details == {"extra": "info"}
        assert resp.request_id == "custom-1"
