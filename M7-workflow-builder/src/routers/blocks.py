"""M7 积木平台 - 积木块管理路由.

提供积木（技能）列表、分类、详情等 API。
积木优先从 M2 技能集群拉取，失败降级到内置积木。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from ..models import ApiResponse, BlockCategory, BlockInfo
from ..services.executor import BUILTIN_BLOCKS, M2SkillClient
from ..m8_api.m8_auth_middleware import get_current_user


router = APIRouter(prefix="/api/v1/blocks", tags=["积木管理"])

_m2_client = M2SkillClient()
_m2_available: Optional[bool] = None
_m2_check_time: float = 0
_m2_cache_ttl: float = 60.0

# P2-16: 技能列表缓存（积木列表变更频率低，缓存5分钟）
_m2_skills_cache: list = []
_m2_skills_cache_time: float = 0
_m2_skills_ttl: float = 300.0  # 5分钟


# 积木分类映射
_SKILL_CATEGORY_MAP = {
    "skill.web_fetch": "信息获取",
    "skill.fulltext_search": "信息获取",
    "skill.translate": "文本处理",
    "skill.doc_proc": "文档处理",
    "skill.data_analysis": "数据分析",
    "skill.tide_memory": "记忆存储",
    "skill.notify": "通知推送",
    "skill.calendar": "日程管理",
    "skill.code_search": "开发工具",
    "skill.code_skills": "开发工具",
    "voice.asr": "语音处理",
    "voice.tts": "语音处理",
    "voice.wake_word": "语音处理",
    "voice.record": "语音处理",
}

# 积木分类定义
BLOCK_CATEGORIES: List[dict] = [
    {"id": "info", "name": "信息获取", "icon": "🔍", "color": "#3B82F6"},
    {"id": "text", "name": "文本处理", "icon": "📝", "color": "#10B981"},
    {"id": "doc", "name": "文档处理", "icon": "📄", "color": "#F59E0B"},
    {"id": "data", "name": "数据分析", "icon": "📊", "color": "#8B5CF6"},
    {"id": "memory", "name": "记忆存储", "icon": "🧠", "color": "#EC4899"},
    {"id": "notify", "name": "通知推送", "icon": "🔔", "color": "#EF4444"},
    {"id": "calendar", "name": "日程管理", "icon": "📅", "color": "#06B6D4"},
    {"id": "voice", "name": "语音处理", "icon": "🎙️", "color": "#F97316"},
    {"id": "dev", "name": "开发工具", "icon": "⚙️", "color": "#6B7280"},
    {"id": "other", "name": "其他", "icon": "📦", "color": "#9CA3AF"},
]

# 内置积木列表
BUILTIN_BLOCKS_LIST: List[dict] = [
    {
        "id": "skill.web_fetch",
        "name": "网页抓取",
        "description": "抓取网页内容，支持 HTML 解析和内容提取",
        "category": "信息获取",
        "tags": ["web", "fetch", "crawler"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "🌐",
        "inputs": [
            {"name": "url", "type": "string", "required": True, "description": "目标网址"},
            {"name": "action", "type": "string", "default": "fetch", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "title", "type": "string", "description": "页面标题"},
            {"name": "content", "type": "string", "description": "页面内容"},
        ],
    },
    {
        "id": "skill.fulltext_search",
        "name": "全文搜索",
        "description": "全文检索文档和记忆内容，支持关键词和语义检索",
        "category": "信息获取",
        "tags": ["search", "fulltext", "retrieval"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "🔍",
        "inputs": [
            {"name": "query", "type": "string", "required": True, "description": "搜索关键词"},
            {"name": "action", "type": "string", "default": "search", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "results", "type": "array", "description": "搜索结果列表"},
            {"name": "total", "type": "number", "description": "结果总数"},
        ],
    },
    {
        "id": "skill.translate",
        "name": "翻译",
        "description": "多语言文本翻译，支持 100+ 语言互译",
        "category": "文本处理",
        "tags": ["translate", "i18n", "language"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "🌍",
        "inputs": [
            {"name": "text", "type": "string", "required": True, "description": "待翻译文本"},
            {"name": "target_lang", "type": "string", "default": "zh-CN", "description": "目标语言"},
            {"name": "action", "type": "string", "default": "translate", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "translated_text", "type": "string", "description": "翻译结果"},
            {"name": "source_lang", "type": "string", "description": "源语言"},
        ],
    },
    {
        "id": "skill.doc_proc",
        "name": "文档处理",
        "description": "文档解析、格式转换、内容提取与摘要",
        "category": "文档处理",
        "tags": ["doc", "parse", "summary"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "📄",
        "inputs": [
            {"name": "file_path", "type": "string", "required": True, "description": "文件路径"},
            {"name": "action", "type": "string", "default": "parse", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "text", "type": "string", "description": "提取的文本内容"},
            {"name": "word_count", "type": "number", "description": "字数统计"},
        ],
    },
    {
        "id": "skill.data_analysis",
        "name": "数据分析",
        "description": "数据分析、统计、可视化与洞察生成",
        "category": "数据分析",
        "tags": ["data", "analysis", "statistics"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "📊",
        "inputs": [
            {"name": "data", "type": "object", "required": True, "description": "待分析数据"},
            {"name": "action", "type": "string", "default": "analyze", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "summary", "type": "string", "description": "分析摘要"},
            {"name": "stats", "type": "object", "description": "统计指标"},
        ],
    },
    {
        "id": "skill.tide_memory",
        "name": "潮汐记忆",
        "description": "存取潮汐记忆系统，支持记忆的增删改查",
        "category": "记忆存储",
        "tags": ["memory", "tide", "storage"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "🧠",
        "inputs": [
            {"name": "action", "type": "string", "default": "store", "description": "操作类型"},
            {"name": "domain", "type": "string", "default": "default", "description": "记忆域"},
        ],
        "outputs": [
            {"name": "result", "type": "object", "description": "操作结果"},
        ],
    },
    {
        "id": "skill.notify",
        "name": "通知推送",
        "description": "多渠道消息通知推送，支持邮件、系统通知等",
        "category": "通知推送",
        "tags": ["notify", "push", "notification"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "🔔",
        "inputs": [
            {"name": "message", "type": "string", "required": True, "description": "消息内容"},
            {"name": "channel", "type": "string", "default": "system", "description": "推送渠道"},
            {"name": "action", "type": "string", "default": "send", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "sent", "type": "boolean", "description": "是否发送成功"},
        ],
    },
    {
        "id": "skill.calendar",
        "name": "日程管理",
        "description": "日历日程安排与提醒，支持事件的增删改查",
        "category": "日程管理",
        "tags": ["calendar", "schedule", "reminder"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "📅",
        "inputs": [
            {"name": "action", "type": "string", "default": "list", "description": "操作类型"},
            {"name": "date", "type": "string", "description": "日期"},
        ],
        "outputs": [
            {"name": "events", "type": "array", "description": "日程列表"},
        ],
    },
    {
        "id": "voice.asr",
        "name": "语音识别",
        "description": "将音频文件转写为文本，支持中文、英文及多语言识别",
        "category": "语音处理",
        "tags": ["voice", "asr", "speech", "transcribe"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "🎤",
        "inputs": [
            {"name": "audio_path", "type": "string", "required": True, "description": "音频文件路径"},
            {"name": "language", "type": "string", "default": "zh", "description": "语言代码（zh/en/auto）"},
            {"name": "action", "type": "string", "default": "transcribe", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "text", "type": "string", "description": "识别的文本内容"},
            {"name": "language", "type": "string", "description": "检测到的语言"},
            {"name": "duration", "type": "number", "description": "音频时长（秒）"},
            {"name": "engine", "type": "string", "description": "使用的识别引擎"},
        ],
    },
    {
        "id": "voice.tts",
        "name": "语音合成",
        "description": "将文本合成为语音，支持多种音色和语速调节",
        "category": "语音处理",
        "tags": ["voice", "tts", "speech", "synthesize"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "🔊",
        "inputs": [
            {"name": "text", "type": "string", "required": True, "description": "要合成的文本"},
            {"name": "voice_type", "type": "string", "default": "warm_female", "description": "音色类型（warm_female/clear_female/gentle_male/cute_child/robot）"},
            {"name": "voice_speed", "type": "number", "default": 1.0, "description": "语速倍率（0.5-2.0）"},
            {"name": "output_path", "type": "string", "description": "输出音频文件路径（可选）"},
            {"name": "action", "type": "string", "default": "synthesize", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "audio_path", "type": "string", "description": "生成的音频文件路径"},
            {"name": "audio_format", "type": "string", "description": "音频格式（mp3/wav）"},
            {"name": "duration", "type": "number", "description": "音频时长（秒）"},
            {"name": "engine", "type": "string", "description": "使用的合成引擎"},
        ],
    },
    {
        "id": "voice.wake_word",
        "name": "唤醒词检测",
        "description": "检测音频中是否包含预设的唤醒关键词",
        "category": "语音处理",
        "tags": ["voice", "wake", "keyword", "detect"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "⏰",
        "inputs": [
            {"name": "audio_path", "type": "string", "required": True, "description": "音频文件路径"},
            {"name": "keywords", "type": "array", "default": ["小云", "小汐"], "description": "唤醒关键词列表"},
            {"name": "language", "type": "string", "default": "zh", "description": "语言代码"},
            {"name": "action", "type": "string", "default": "detect", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "detected", "type": "boolean", "description": "是否检测到唤醒词"},
            {"name": "matched_keyword", "type": "string", "description": "匹配到的关键词"},
            {"name": "confidence", "type": "number", "description": "匹配置信度"},
            {"name": "transcript", "type": "string", "description": "完整识别文本"},
        ],
    },
    {
        "id": "voice.record",
        "name": "录音控制",
        "description": "控制麦克风录音，支持指定时长录制并保存音频文件",
        "category": "语音处理",
        "tags": ["voice", "record", "audio", "microphone"],
        "version": "1.0.0",
        "enabled": True,
        "icon": "⏺️",
        "inputs": [
            {"name": "duration", "type": "number", "default": 5.0, "description": "录音时长（秒）"},
            {"name": "sample_rate", "type": "number", "default": 16000, "description": "采样率（Hz）"},
            {"name": "output_path", "type": "string", "description": "输出文件路径（可选）"},
            {"name": "action", "type": "string", "default": "record", "description": "操作类型"},
        ],
        "outputs": [
            {"name": "audio_path", "type": "string", "description": "录音文件路径"},
            {"name": "duration", "type": "number", "description": "实际录音时长（秒）"},
            {"name": "sample_rate", "type": "number", "description": "采样率"},
            {"name": "success", "type": "boolean", "description": "是否录制成功"},
        ],
    },
]


import time


async def _check_m2_available(force: bool = False) -> bool:
    """检查 M2 是否可用（带缓存）."""
    global _m2_available, _m2_check_time
    now = time.time()
    if force or _m2_available is None or (now - _m2_check_time) > _m2_cache_ttl:
        _m2_available = await _m2_client.health_check()
        _m2_check_time = now
    return _m2_available


async def _fetch_m2_skills() -> List[Dict[str, Any]]:
    """从 M2 获取技能列表并转换为积木格式（P2-16: 增加5分钟缓存）"""
    import time as _time_mod
    global _m2_skills_cache, _m2_skills_cache_time

    # 命中缓存
    if _m2_skills_cache and (_time_mod.time() - _m2_skills_cache_time) < _m2_skills_ttl:
        return _m2_skills_cache.copy()

    if not _m2_client:
        return []
    try:
        skills = await _m2_client.list_skills()
        blocks = []
        for s in skills:
            blocks.append({
                "id": s.get("skill_id", s.get("id", "")),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "category": s.get("category", "general"),
                "type": "skill",
                "source": "m2",
                "tags": s.get("tags", []),
                "inputs": s.get("inputs", []),
                "outputs": s.get("outputs", []),
            })
        # 更新缓存
        _m2_skills_cache = blocks
        _m2_skills_cache_time = _time_mod.time()
        return blocks
    except Exception:
        # 请求失败时如果有旧缓存则返回旧缓存（降级）
        if _m2_skills_cache:
            return _m2_skills_cache.copy()
        return []

async def list_blocks(
    request: Request,
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    current_user: dict = Depends(get_current_user),
):
    """获取可用积木列表.

    优先从 M2 Skills Cluster 获取技能列表，
    M2 不可用时返回本地内置积木作为降级。
    """
    blocks = []
    source = "builtin"

    # 尝试从 M2 获取
    m2_ok = await _check_m2_available()
    if m2_ok:
        m2_skills = await _fetch_m2_skills()
        if m2_skills:
            blocks = m2_skills
            source = "m2"

    # M2 不可用或返回为空，使用内置积木
    if not blocks:
        blocks = BUILTIN_BLOCKS_LIST.copy()
        source = "builtin"

    # 分类筛选
    if category:
        blocks = [b for b in blocks if b.get("category") == category]

    # 搜索
    if search:
        keyword = search.lower()
        blocks = [
            b for b in blocks
            if keyword in b.get("name", "").lower()
            or keyword in b.get("description", "").lower()
            or any(keyword in t.lower() for t in b.get("tags", []))
        ]

    return ApiResponse.success(
        data={
            "total": len(blocks),
            "items": blocks,
            "source": source,
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/categories")
async def list_block_categories(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取积木分类列表."""
    categories = []
    source = "builtin"

    # 尝试从 M2 获取分类
    m2_ok = await _check_m2_available()
    if m2_ok:
        try:
            # M2 没有专门的分类接口，使用内置分类
            pass
        except Exception:
            pass

    # 使用内置分类，并统计各分类下的积木数量
    m2_skills = []
    if m2_ok:
        m2_skills = await _fetch_m2_skills()

    count_source = m2_skills if m2_skills else BUILTIN_BLOCKS_LIST

    cat_counts = {}
    for b in count_source:
        cat = b.get("category", "其他")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    categories = []
    for cat_def in BLOCK_CATEGORIES:
        cat_copy = cat_def.copy()
        cat_name = cat_def["name"]
        cat_copy["count"] = cat_counts.get(cat_name, 0)
        categories.append(cat_copy)

    return ApiResponse.success(
        data={
            "total": len(categories),
            "items": categories,
            "source": source,
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/{block_id}")
async def get_block_detail(
    request: Request,
    block_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取积木详情."""
    # 先从 M2 查找
    m2_ok = await _check_m2_available()
    if m2_ok:
        m2_skills = await _fetch_m2_skills()
        for sk in m2_skills:
            if sk["id"] == block_id:
                return ApiResponse.success(
                    data={
                        **sk,
                        "source": "m2",
                    },
                    request_id=request.headers.get("X-Request-ID", ""),
                )

    # 从内置积木查找
    for b in BUILTIN_BLOCKS_LIST:
        if b["id"] == block_id:
            return ApiResponse.success(
                data={
                    **b,
                    "source": "builtin",
                },
                request_id=request.headers.get("X-Request-ID", ""),
            )

    return ApiResponse.error(
        code=404,
        message=f"积木 {block_id} 不存在",
        request_id=request.headers.get("X-Request-ID", ""),
    )
