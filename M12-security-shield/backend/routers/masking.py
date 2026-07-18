"""
云汐 M12 安全盾 - 数据脱敏管理 API
提供脱敏规则查询、脱敏测试、脱敏配置等接口

所有接口均需鉴权保护。
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

# 兼容相对导入和直接运行
try:
    from ..schemas.common import make_response, make_error_response
    from ..services.masking import (
        mask_api_key,
        mask_password,
        mask_jwt_token,
        mask_ip_address,
        mask_email,
        mask_phone,
        mask_sensitive_data,
        mask_dict_with_rules,
    )
    from ..auth import get_current_user, require_role, require_scope
    from ..auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from schemas.common import make_response, make_error_response
    from services.masking import (
        mask_api_key,
        mask_password,
        mask_jwt_token,
        mask_ip_address,
        mask_email,
        mask_phone,
        mask_sensitive_data,
        mask_dict_with_rules,
    )
    from auth import get_current_user, require_role, require_scope
    from auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER

router = APIRouter(prefix="/api/m12/masking", tags=["M12-数据脱敏"])


# ===========================================================================
# 请求/响应模型
# ===========================================================================

class MaskTestRequest(BaseModel):
    """脱敏测试请求"""
    data_type: str = Field(..., description="数据类型：api_key/password/jwt/ip/email/phone/custom")
    value: str = Field(..., description="待脱敏的值")
    mask_char: Optional[str] = Field(default="*", description="脱敏字符")
    prefix_length: Optional[int] = Field(default=None, description="前缀保留长度（自定义模式）")
    suffix_length: Optional[int] = Field(default=None, description="后缀保留长度（自定义模式）")


class MaskBatchRequest(BaseModel):
    """批量脱敏请求"""
    data: Dict[str, Any] = Field(..., description="待脱敏的数据字典")
    rules: Dict[str, str] = Field(..., description="脱敏规则映射，key 为字段名，value 为脱敏类型")


# ===========================================================================
# 脱敏规则列表
# ===========================================================================

@router.get("/rules", summary="获取脱敏规则列表")
async def list_masking_rules(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取所有支持的脱敏规则列表（需鉴权）
    """
    rules = [
        {
            "id": "api_key",
            "name": "API Key 脱敏",
            "description": "只显示前 4 位和后 4 位，中间用 **** 代替",
            "example": "m12s****abcd",
            "category": "凭证类"
        },
        {
            "id": "password",
            "name": "密码脱敏",
            "description": "全部显示为 6 个星号",
            "example": "******",
            "category": "凭证类"
        },
        {
            "id": "jwt",
            "name": "JWT Token 脱敏",
            "description": "只显示前 10 位，后面用 **** 代替",
            "example": "eyJhbGciOi****",
            "category": "凭证类"
        },
        {
            "id": "ip",
            "name": "IP 地址脱敏",
            "description": "IPv4 最后一段替换为 ***，IPv6 最后一段替换为 ***",
            "example": "192.168.1.***",
            "category": "网络标识"
        },
        {
            "id": "email",
            "name": "邮箱脱敏",
            "description": "用户名部分只显示首字符，域名保留",
            "example": "a****@example.com",
            "category": "个人信息"
        },
        {
            "id": "phone",
            "name": "手机号脱敏",
            "description": "中间 4 位替换为 ****",
            "example": "138****5678",
            "category": "个人信息"
        },
        {
            "id": "custom",
            "name": "自定义脱敏",
            "description": "可自定义前缀保留长度、后缀保留长度和脱敏字符",
            "example": "前****后",
            "category": "自定义"
        }
    ]

    categories = ["凭证类", "网络标识", "个人信息", "自定义"]

    return make_response(data={
        "items": rules,
        "total": len(rules),
        "categories": categories
    })


# ===========================================================================
# 脱敏测试
# ===========================================================================

@router.post("/test", summary="脱敏功能测试")
async def test_masking(
    request: MaskTestRequest,
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    测试指定类型的脱敏效果（需鉴权）
    """
    try:
        value = request.value
        result = ""
        rule_name = ""

        if request.data_type == "api_key":
            result = mask_api_key(value)
            rule_name = "API Key 脱敏"
        elif request.data_type == "password":
            result = mask_password(value)
            rule_name = "密码脱敏"
        elif request.data_type == "jwt":
            result = mask_jwt_token(value)
            rule_name = "JWT Token 脱敏"
        elif request.data_type == "ip":
            result = mask_ip_address(value)
            rule_name = "IP 地址脱敏"
        elif request.data_type == "email":
            result = mask_email(value)
            rule_name = "邮箱脱敏"
        elif request.data_type == "phone":
            result = mask_phone(value)
            rule_name = "手机号脱敏"
        elif request.data_type == "custom":
            prefix_len = request.prefix_length or 3
            suffix_len = request.suffix_length or 2
            mask_char = request.mask_char or "*"
            if len(value) <= prefix_len + suffix_len:
                result = mask_char * len(value)
            else:
                mask_len = len(value) - prefix_len - suffix_len
                result = value[:prefix_len] + (mask_char * mask_len) + value[-suffix_len:]
            rule_name = "自定义脱敏"
        else:
            return make_error_response(f"不支持的数据类型: {request.data_type}", code=400)

        return make_response(data={
            "original": value,
            "masked": result,
            "data_type": request.data_type,
            "rule_name": rule_name,
            "original_length": len(value),
            "masked_length": len(result),
        })
    except Exception as e:
        return make_error_response(f"脱敏测试失败: {str(e)}")


# ===========================================================================
# 批量脱敏
# ===========================================================================

@router.post("/batch", summary="批量数据脱敏")
async def batch_masking(
    request: MaskBatchRequest,
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    对数据字典进行批量脱敏（需鉴权）

    根据 rules 中指定的字段和脱敏类型，对 data 中的对应字段进行脱敏处理。
    """
    try:
        result = mask_dict_with_rules(request.data, request.rules)
        return make_response(data={
            "original": request.data,
            "masked": result,
            "rules_applied": len(request.rules),
        })
    except Exception as e:
        return make_error_response(f"批量脱敏失败: {str(e)}")


# ===========================================================================
# 脱敏统计
# ===========================================================================

@router.get("/stats", summary="脱敏统计信息")
async def get_masking_stats(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取脱敏模块的统计信息（需鉴权）
    """
    stats = {
        "total_rules": 7,
        "enabled_rules": 7,
        "categories": [
            { name: "凭证类", count: 3 },
            { name: "网络标识", count: 1 },
            { name: "个人信息", count: 2 },
            { name: "自定义", count: 1 },
        ],
        "supported_types": ["api_key", "password", "jwt", "ip", "email", "phone", "custom"],
    }

    return make_response(data=stats)
