"""
业务模式管理路由
全部代理到 M4 场景引擎，M4 不可用时返回本地模拟数据
"""

import sys
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter
from pydantic import BaseModel

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ...m4_proxy import proxy_to_m4, strip_proxy_flag

router = APIRouter(tags=["模式管理"])

# M4 场景引擎模式管理接口前缀
M4_MODES_PREFIX = "/api/v1/modes"


# ========== 数据模型 ==========

class ModeSwitchRequest(BaseModel):
    """模式切换请求"""
    mode_id: str
    reason: Optional[str] = ""


class ModeRecognizeRequest(BaseModel):
    """模式识别请求"""
    text: str
    context: Optional[Dict[str, Any]] = None


class ModeContextRequest(BaseModel):
    """保存上下文请求"""
    context: Dict[str, Any]


# ========== 代理辅助函数 ==========

async def _proxy_m4(sub_path: str, method: str = "GET", params=None, body=None, local_func=None, *args, **kwargs):
    """
    代理到 M4 场景引擎，失败则回退到本地实现

    Args:
        sub_path: M4 子路径（如 /modes）
        method: HTTP 方法
        params: 查询参数
        body: 请求体
        local_func: 本地回退函数
        *args, **kwargs: 传递给本地函数的参数

    Returns:
        统一格式响应 {code, message, data}
    """
    m4_path = f"{M4_MODES_PREFIX}{sub_path}"
    result = await proxy_to_m4(
        path=m4_path,
        method=method,
        params=params,
        body=body,
        fallback_func=local_func,
        fallback_args=args,
        fallback_kwargs=kwargs,
    )
    return strip_proxy_flag(result)


# ========== 本地模拟数据（fallback） ==========

# 业务模式列表
_MODE_LIST = [
    {
        "id": "growth",
        "name": "成长中心",
        "icon": "🌱",
        "description": "成就系统、天赋树、赛季旅程，记录每一步成长",
        "category": "自我提升",
        "status": "available",
        "api_prefix": "/api/growth",
        "m4_path": "/api/v1/mode/growth",
    },
    {
        "id": "work-dev",
        "name": "工作开发",
        "icon": "💻",
        "description": "代码沙箱、项目管理、版本控制，开发效率倍增",
        "category": "生产力",
        "status": "available",
        "api_prefix": "/api/work-dev",
        "m4_path": "/api/v1/mode/work-dev",
    },
    {
        "id": "review",
        "name": "复盘总结",
        "icon": "📝",
        "description": "日报周报、情绪追踪、决策回溯，持续精进",
        "category": "自我提升",
        "status": "available",
        "api_prefix": "/api/review",
        "m4_path": "/api/v1/mode/review",
    },
    {
        "id": "study-plan",
        "name": "学业规划",
        "icon": "📚",
        "description": "目标拆解、知识管理、进度追踪，学业有成",
        "category": "自我提升",
        "status": "available",
        "api_prefix": "/api/study-plan",
        "m4_path": "/api/v1/mode/study-plan",
    },
    {
        "id": "life-management",
        "name": "生活管理",
        "icon": "🏠",
        "description": "日程安排、习惯养成、财务管理，井井有条",
        "category": "生活效率",
        "status": "available",
        "api_prefix": "/api/life-management",
        "m4_path": "/api/v1/mode/life-management",
    },
    {
        "id": "emotion-comfort",
        "name": "情绪陪伴",
        "icon": "💝",
        "description": "情绪记录、放松引导、助眠陪伴，温暖每一天",
        "category": "心理健康",
        "status": "available",
        "api_prefix": "/api/emotion-comfort",
        "m4_path": "/api/v1/mode/emotion-comfort",
    },
    {
        "id": "social-relation",
        "name": "人际关系",
        "icon": "🤝",
        "description": "人脉管理、社交分析、关系维护，高情商交往",
        "category": "社交",
        "status": "available",
        "api_prefix": "/api/social-relation",
        "m4_path": "/api/v1/mode/social-relation",
    },
    {
        "id": "appearance",
        "name": "形象工坊",
        "icon": "✨",
        "description": "穿搭建议、形象设计、风格管理，展现最好的你",
        "category": "个人形象",
        "status": "available",
        "api_prefix": "/api/appearance",
        "m4_path": "/api/v1/mode/appearance",
    },
]

# 当前激活模式
_current_mode = {
    "mode_id": "growth",
    "mode_name": "成长中心",
    "activated_at": datetime.now().isoformat(),
    "session_id": "sess_default",
}

# 切换历史
_switch_history = []
for i in range(10):
    mode = _MODE_LIST[i % len(_MODE_LIST)]
    _switch_history.append({
        "id": 10 - i,
        "from_mode": _MODE_LIST[(i + 1) % len(_MODE_LIST)]["id"],
        "to_mode": mode["id"],
        "to_mode_name": mode["name"],
        "reason": f"切换到{mode['name']}模式",
        "switched_at": (datetime.now() - timedelta(hours=i * 3)).isoformat(),
        "duration_minutes": random.randint(15, 180) if i > 0 else None,
    })

# 当前上下文
_current_context = {
    "user_mood": "calm",
    "current_focus": "self_improvement",
    "energy_level": 7,
    "time_of_day": "daytime",
    "recent_activities": ["学习", "工作", "运动"],
}


# ========== 本地回退函数 ==========

async def _local_get_modes():
    """本地实现：获取所有业务模式列表"""
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total": len(_MODE_LIST),
            "modes": _MODE_LIST,
            "categories": list(set(m["category"] for m in _MODE_LIST)),
        },
    }


async def _local_get_mode_detail(mode_id: str):
    """本地实现：获取模式详情"""
    mode = next((m for m in _MODE_LIST if m["id"] == mode_id), None)
    if not mode:
        return {"code": 404, "message": f"模式不存在: {mode_id}", "data": None}
    return {"code": 0, "message": "ok", "data": mode}


async def _local_get_current_mode():
    """本地实现：获取当前激活的模式"""
    mode_info = next((m for m in _MODE_LIST if m["id"] == _current_mode["mode_id"]), None)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            **_current_mode,
            "mode_info": mode_info,
        },
    }


async def _local_switch_mode(mode_id: str, reason: str = ""):
    """本地实现：切换模式"""
    global _current_mode
    mode = next((m for m in _MODE_LIST if m["id"] == mode_id), None)
    if not mode:
        return {"code": 404, "message": f"模式不存在: {mode_id}", "data": None}

    old_mode = _current_mode["mode_id"]
    _current_mode = {
        "mode_id": mode_id,
        "mode_name": mode["name"],
        "activated_at": datetime.now().isoformat(),
        "session_id": f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}",
    }

    # 记录历史
    _switch_history.insert(0, {
        "id": len(_switch_history) + 1,
        "from_mode": old_mode,
        "to_mode": mode_id,
        "to_mode_name": mode["name"],
        "reason": reason or f"手动切换到{mode['name']}",
        "switched_at": datetime.now().isoformat(),
        "duration_minutes": None,
    })

    return {
        "code": 0,
        "message": f"已切换到 {mode['name']}",
        "data": _current_mode,
    }


async def _local_get_history(limit: int = 20):
    """本地实现：获取切换历史"""
    history = _switch_history[:limit]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total": len(_switch_history),
            "history": history,
        },
    }


async def _local_recognize_mode(text: str, context: dict = None):
    """本地实现：识别模式"""
    text_lower = text.lower()
    # 简单关键词匹配
    mode_scores = {
        "growth": ["成长", "成就", "天赋", "赛季", "升级", "growth", "level"],
        "work-dev": ["工作", "代码", "开发", "项目", "编程", "work", "code", "dev"],
        "review": ["复盘", "总结", "日报", "周报", "回顾", "review", "summary"],
        "study-plan": ["学习", "学业", "考试", "知识", "计划", "study", "learn", "exam"],
        "life-management": ["生活", "日程", "习惯", "待办", "财务", "life", "schedule", "todo"],
        "emotion-comfort": ["情绪", "心情", "放松", "睡眠", "压力", "emotion", "mood", "relax", "sleep"],
        "social-relation": ["社交", "人际", "朋友", "关系", "人脉", "social", "friend", "relation"],
        "appearance": ["形象", "穿搭", "外表", "打扮", "颜值", "appearance", "outfit", "style"],
    }

    scores = {}
    for mode_id, keywords in mode_scores.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        scores[mode_id] = score

    # 如果没有匹配，返回成长模式（默认）
    if max(scores.values()) == 0:
        best_mode = "growth"
        confidence = 0.3
    else:
        best_mode = max(scores, key=scores.get)
        total = sum(scores.values())
        confidence = round(scores[best_mode] / max(total, 1), 2)

    mode_info = next((m for m in _MODE_LIST if m["id"] == best_mode), None)

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "recognized_mode": best_mode,
            "mode_name": mode_info["name"] if mode_info else best_mode,
            "confidence": confidence,
            "all_scores": scores,
            "input_text": text,
        },
    }


async def _local_get_context():
    """本地实现：获取当前上下文"""
    return {
        "code": 0,
        "message": "ok",
        "data": _current_context,
    }


async def _local_save_context(context: dict):
    """本地实现：保存上下文"""
    global _current_context
    _current_context.update(context)
    return {
        "code": 0,
        "message": "上下文已保存",
        "data": _current_context,
    }


# ========== API 路由 ==========

@router.get("")
async def get_modes():
    """获取所有业务模式列表（代理到 M4，失败回退本地）"""
    return await _proxy_m4("/modes", "GET", local_func=_local_get_modes)


@router.get("/current")
async def get_current_mode():
    """获取当前激活的模式（代理到 M4，失败回退本地）"""
    return await _proxy_m4("/current", "GET", local_func=_local_get_current_mode)


@router.get("/history")
async def get_mode_history(limit: int = 20):
    """获取模式切换历史（代理到 M4，失败回退本地）"""
    return await _proxy_m4("/history", "GET", params={"limit": limit}, local_func=_local_get_history, limit=limit)


@router.get("/context")
async def get_mode_context():
    """获取当前模式上下文（代理到 M4，失败回退本地）"""
    return await _proxy_m4("/context", "GET", local_func=_local_get_context)


@router.post("/context")
async def save_mode_context(req: ModeContextRequest):
    """保存模式上下文（代理到 M4，失败回退本地）"""
    return await _proxy_m4(
        "/context", "POST",
        body={"context": req.context},
        local_func=_local_save_context,
        context=req.context,
    )


@router.post("/switch")
async def switch_mode(req: ModeSwitchRequest):
    """切换业务模式（代理到 M4，失败回退本地）"""
    return await _proxy_m4(
        "/switch", "POST",
        body={"mode_id": req.mode_id, "reason": req.reason},
        local_func=_local_switch_mode,
        mode_id=req.mode_id,
        reason=req.reason,
    )


@router.post("/recognize")
async def recognize_mode(req: ModeRecognizeRequest):
    """根据输入内容识别适合的模式（代理到 M4，失败回退本地）"""
    return await _proxy_m4(
        "/recognize", "POST",
        body={"text": req.text, "context": req.context},
        local_func=_local_recognize_mode,
        text=req.text,
        context=req.context,
    )


@router.get("/{mode_id}")
async def get_mode_detail(mode_id: str):
    """获取模式详情（代理到 M4，失败回退本地）"""
    return await _proxy_m4(f"/{mode_id}", "GET", local_func=_local_get_mode_detail, mode_id=mode_id)
