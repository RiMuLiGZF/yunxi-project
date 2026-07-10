"""
M1 错误码统一定义

错误码段：10000 - 19999
分段规划：
  10000-10099  通用错误
  10100-10199  认证/授权错误
  10200-10299  参数校验错误
  10300-10399  调度引擎错误
  10400-10499  Agent 管理错误
  10500-10599  联邦调度错误
  10600-10699  隐私/安全错误
  10700-10799  配置错误
  10800-10899  资源/成本错误
  10900-10999  M8 对接错误
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCode:
    """错误码定义"""
    code: int
    message: str
    http_status: int = 400
    level: str = "error"  # info / warning / error / critical


# ═══════════════════════════════════════════════════════
# 10000-10099 通用错误
# ═══════════════════════════════════════════════════════

SUCCESS = ErrorCode(0, "成功", 200, "info")

ERR_UNKNOWN = ErrorCode(10000, "未知错误", 500, "error")
ERR_INTERNAL = ErrorCode(10001, "服务器内部错误", 500, "error")
ERR_NOT_IMPLEMENTED = ErrorCode(10002, "功能未实现", 501, "warning")
ERR_SERVICE_UNAVAILABLE = ErrorCode(10003, "服务不可用", 503, "error")
ERR_TIMEOUT = ErrorCode(10004, "请求超时", 504, "warning")
ERR_TOO_MANY_REQUESTS = ErrorCode(10005, "请求过于频繁", 429, "warning")

# ═══════════════════════════════════════════════════════
# 10100-10199 认证/授权错误
# ═══════════════════════════════════════════════════════

ERR_AUTH_REQUIRED = ErrorCode(10100, "需要认证", 401, "warning")
ERR_AUTH_INVALID = ErrorCode(10101, "认证失败，无效的凭证", 401, "warning")
ERR_AUTH_EXPIRED = ErrorCode(10102, "Token 已过期", 401, "warning")
ERR_AUTH_SIGNATURE = ErrorCode(10103, "签名验证失败", 401, "warning")
ERR_PERMISSION_DENIED = ErrorCode(10104, "权限不足", 403, "warning")
ERR_ADMIN_KEY_REQUIRED = ErrorCode(10105, "需要管理员密钥", 403, "warning")
ERR_INTERNAL_CALL_REQUIRED = ErrorCode(10106, "仅限内部调用", 403, "warning")
ERR_M8_TOKEN_INVALID = ErrorCode(10107, "M8 管理令牌无效", 401, "warning")

# ═══════════════════════════════════════════════════════
# 10200-10299 参数校验错误
# ═══════════════════════════════════════════════════════

ERR_PARAM_MISSING = ErrorCode(10200, "缺少必要参数", 400, "warning")
ERR_PARAM_INVALID = ErrorCode(10201, "参数格式错误", 400, "warning")
ERR_PARAM_TYPE = ErrorCode(10202, "参数类型错误", 400, "warning")
ERR_PARAM_RANGE = ErrorCode(10203, "参数超出范围", 400, "warning")
ERR_PARAM_CONFLICT = ErrorCode(10204, "参数冲突", 409, "warning")
ERR_BODY_INVALID = ErrorCode(10205, "请求体格式错误", 400, "warning")

# ═══════════════════════════════════════════════════════
# 10300-10399 调度引擎错误
# ═══════════════════════════════════════════════════════

ERR_TASK_NOT_FOUND = ErrorCode(10300, "任务不存在", 404, "info")
ERR_TASK_ALREADY_EXISTS = ErrorCode(10301, "任务已存在", 409, "warning")
ERR_TASK_STATUS_INVALID = ErrorCode(10302, "任务状态不允许此操作", 409, "warning")
ERR_TASK_QUEUE_FULL = ErrorCode(10303, "任务队列已满", 503, "warning")
ERR_TASK_TIMEOUT = ErrorCode(10304, "任务执行超时", 408, "warning")
ERR_TASK_CANCELLED = ErrorCode(10305, "任务已取消", 409, "info")
ERR_DAG_INVALID = ErrorCode(10306, "DAG 结构无效", 400, "error")
ERR_DAG_CYCLE = ErrorCode(10307, "DAG 存在循环依赖", 400, "error")
ERR_SCHEDULER_BUSY = ErrorCode(10308, "调度器繁忙", 503, "warning")

# ═══════════════════════════════════════════════════════
# 10400-10499 Agent 管理错误
# ═══════════════════════════════════════════════════════

ERR_AGENT_NOT_FOUND = ErrorCode(10400, "Agent 不存在", 404, "info")
ERR_AGENT_ALREADY_EXISTS = ErrorCode(10401, "Agent 已存在", 409, "warning")
ERR_AGENT_OFFLINE = ErrorCode(10402, "Agent 离线", 503, "warning")
ERR_AGENT_UNHEALTHY = ErrorCode(10403, "Agent 健康状态异常", 503, "warning")
ERR_AGENT_TYPE_INVALID = ErrorCode(10404, "Agent 类型无效", 400, "warning")
ERR_CLONE_POOL_EXHAUSTED = ErrorCode(10405, "分身池资源耗尽", 503, "warning")
ERR_LIFECYCLE_TRANSITION = ErrorCode(10406, "生命周期状态转换非法", 409, "warning")

# ═══════════════════════════════════════════════════════
# 10500-10599 联邦调度错误
# ═══════════════════════════════════════════════════════

ERR_FEDERATION_DISABLED = ErrorCode(10500, "联邦调度未启用", 403, "warning")
ERR_FED_AGENT_NOT_FOUND = ErrorCode(10501, "联邦 Agent 不存在", 404, "info")
ERR_FED_AGENT_REGISTER_FAILED = ErrorCode(10502, "联邦 Agent 注册失败", 500, "error")
ERR_FED_INVOKE_FAILED = ErrorCode(10503, "联邦调用失败", 502, "error")
ERR_FED_COMPARE_FAILED = ErrorCode(10504, "联邦对比失败", 502, "error")
ERR_FED_DECISION_FAILED = ErrorCode(10505, "调度决策失败", 500, "error")
ERR_FED_LICENSE_RISK = ErrorCode(10506, "许可证风险未确认", 400, "warning")
ERR_FED_PATH_UNREACHABLE = ErrorCode(10507, "脱敏路径不可达", 400, "warning")

# ═══════════════════════════════════════════════════════
# 10600-10699 隐私/安全错误
# ═══════════════════════════════════════════════════════

ERR_PRIVACY_BLOCKED = ErrorCode(10600, "内容因隐私风险被拦截", 403, "warning")
ERR_PII_DETECTED = ErrorCode(10601, "检测到敏感个人信息", 403, "warning")
ERR_ENCRYPTION_FAILED = ErrorCode(10602, "加密失败", 500, "error")
ERR_DECRYPTION_FAILED = ErrorCode(10603, "解密失败", 500, "error")
ERR_KEY_NOT_FOUND = ErrorCode(10604, "密钥不存在", 404, "warning")
ERR_KEY_ROTATION_FAILED = ErrorCode(10605, "密钥轮换失败", 500, "error")
ERR_DATA_LEAK_RISK = ErrorCode(10606, "数据泄露风险", 403, "warning")
ERR_SECURITY_LEVEL_INSUFFICIENT = ErrorCode(10607, "涉密等级不足", 403, "warning")

# ═══════════════════════════════════════════════════════
# 10700-10799 配置错误
# ═══════════════════════════════════════════════════════

ERR_CONFIG_MISSING = ErrorCode(10700, "配置文件不存在", 500, "error")
ERR_CONFIG_INVALID = ErrorCode(10701, "配置格式错误", 500, "error")
ERR_CONFIG_REQUIRED = ErrorCode(10702, "缺少必要配置项", 500, "error")
ERR_CONFIG_RELOAD_FAILED = ErrorCode(10703, "配置热加载失败", 500, "warning")
ERR_CONFIG_SAVE_FAILED = ErrorCode(10704, "配置保存失败", 500, "error")

# ═══════════════════════════════════════════════════════
# 10800-10899 资源/成本错误
# ═══════════════════════════════════════════════════════

ERR_BUDGET_EXCEEDED = ErrorCode(10800, "预算超限", 402, "warning")
ERR_BUDGET_NOT_SET = ErrorCode(10801, "预算未设置", 400, "warning")
ERR_COST_RECORD_NOT_FOUND = ErrorCode(10802, "成本记录不存在", 404, "info")
ERR_RESOURCE_INSUFFICIENT = ErrorCode(10803, "系统资源不足", 503, "warning")

# ═══════════════════════════════════════════════════════
# 10900-10999 M8 对接错误
# ═══════════════════════════════════════════════════════

ERR_M8_NOT_CONFIGURED = ErrorCode(10900, "M8 对接未配置", 500, "warning")
ERR_M8_UPGRADE_FAILED = ErrorCode(10901, "升级失败", 500, "error")
ERR_M8_ROLLBACK_FAILED = ErrorCode(10902, "回滚失败", 500, "error")
ERR_M8_TEST_FAILED = ErrorCode(10903, "测试执行失败", 500, "error")
ERR_M8_TEST_NOT_FOUND = ErrorCode(10904, "测试任务不存在", 404, "info")
ERR_M8_SNAPSHOT_FAILED = ErrorCode(10905, "代码快照生成失败", 500, "error")


# ═══════════════════════════════════════════════════════
# 统一错误响应格式
# ═══════════════════════════════════════════════════════

def build_error_response(
    error_code: ErrorCode,
    detail: str = "",
    trace_id: str = "",
    data: dict | None = None,
) -> dict:
    """构建统一格式的错误响应

    响应格式：
    {
        "success": false,
        "error": {
            "code": 10100,
            "message": "需要认证",
            "detail": "详细说明",
            "level": "warning"
        },
        "trace_id": "xxx",
        "data": null
    }
    """
    return {
        "success": False,
        "error": {
            "code": error_code.code,
            "message": error_code.message,
            "detail": detail or error_code.message,
            "level": error_code.level,
        },
        "trace_id": trace_id,
        "data": data,
    }


def build_success_response(
    data: Any = None,
    message: str = "成功",
    trace_id: str = "",
) -> dict:
    """构建统一格式的成功响应"""
    return {
        "success": True,
        "message": message,
        "trace_id": trace_id,
        "data": data,
    }


# 所有错误码列表（用于文档生成）
ALL_ERROR_CODES: list[ErrorCode] = [
    SUCCESS,
    ERR_UNKNOWN, ERR_INTERNAL, ERR_NOT_IMPLEMENTED, ERR_SERVICE_UNAVAILABLE,
    ERR_TIMEOUT, ERR_TOO_MANY_REQUESTS,
    ERR_AUTH_REQUIRED, ERR_AUTH_INVALID, ERR_AUTH_EXPIRED, ERR_AUTH_SIGNATURE,
    ERR_PERMISSION_DENIED, ERR_ADMIN_KEY_REQUIRED, ERR_INTERNAL_CALL_REQUIRED,
    ERR_M8_TOKEN_INVALID,
    ERR_PARAM_MISSING, ERR_PARAM_INVALID, ERR_PARAM_TYPE, ERR_PARAM_RANGE,
    ERR_PARAM_CONFLICT, ERR_BODY_INVALID,
    ERR_TASK_NOT_FOUND, ERR_TASK_ALREADY_EXISTS, ERR_TASK_STATUS_INVALID,
    ERR_TASK_QUEUE_FULL, ERR_TASK_TIMEOUT, ERR_TASK_CANCELLED,
    ERR_DAG_INVALID, ERR_DAG_CYCLE, ERR_SCHEDULER_BUSY,
    ERR_AGENT_NOT_FOUND, ERR_AGENT_ALREADY_EXISTS, ERR_AGENT_OFFLINE,
    ERR_AGENT_UNHEALTHY, ERR_AGENT_TYPE_INVALID, ERR_CLONE_POOL_EXHAUSTED,
    ERR_LIFECYCLE_TRANSITION,
    ERR_FEDERATION_DISABLED, ERR_FED_AGENT_NOT_FOUND,
    ERR_FED_AGENT_REGISTER_FAILED, ERR_FED_INVOKE_FAILED,
    ERR_FED_COMPARE_FAILED, ERR_FED_DECISION_FAILED,
    ERR_FED_LICENSE_RISK, ERR_FED_PATH_UNREACHABLE,
    ERR_PRIVACY_BLOCKED, ERR_PII_DETECTED, ERR_ENCRYPTION_FAILED,
    ERR_DECRYPTION_FAILED, ERR_KEY_NOT_FOUND, ERR_KEY_ROTATION_FAILED,
    ERR_DATA_LEAK_RISK, ERR_SECURITY_LEVEL_INSUFFICIENT,
    ERR_CONFIG_MISSING, ERR_CONFIG_INVALID, ERR_CONFIG_REQUIRED,
    ERR_CONFIG_RELOAD_FAILED, ERR_CONFIG_SAVE_FAILED,
    ERR_BUDGET_EXCEEDED, ERR_BUDGET_NOT_SET, ERR_COST_RECORD_NOT_FOUND,
    ERR_RESOURCE_INSUFFICIENT,
    ERR_M8_NOT_CONFIGURED, ERR_M8_UPGRADE_FAILED, ERR_M8_ROLLBACK_FAILED,
    ERR_M8_TEST_FAILED, ERR_M8_TEST_NOT_FOUND, ERR_M8_SNAPSHOT_FAILED,
]
