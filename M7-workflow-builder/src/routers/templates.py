"""M7 积木平台 - 模板管理路由.

提供内置模板的列表、详情、应用等 API。
内置 5 个工作流模板。
"""

from __future__ import annotations

import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from ..models import ApiResponse, TemplateApplyRequest
from ..services.storage import get_storage
from ..m8_api.m8_auth_middleware import get_current_user


router = APIRouter(prefix="/api/v1/templates", tags=["模板管理"])

_storage = get_storage()


def _now_iso() -> str:
    """获取当前 ISO 格式时间字符串."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ============================================================
# 内置模板定义（5 个）
# ============================================================

TEMPLATES: List[dict] = [
    {
        "id": "tpl_news_daily",
        "name": "每日资讯日报",
        "description": "抓取每日科技资讯，翻译并生成日报，最后存入潮汐记忆",
        "category": "信息处理",
        "icon": "📰",
        "tags": ["资讯", "日报", "翻译", "记忆"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.web_fetch",
                "name": "资讯抓取",
                "config": {"url": "", "action": "fetch"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "skill.translate",
                "name": "内容翻译",
                "config": {"target_lang": "zh-CN", "action": "translate"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "skill.data_analysis",
                "name": "日报生成",
                "config": {"action": "summarize"},
                "position": {"x": 590, "y": 120},
                "next": ["block_4"],
            },
            {
                "id": "block_4",
                "type": "skill.tide_memory",
                "name": "存入记忆",
                "config": {"action": "store", "domain": "daily_news"},
                "position": {"x": 860, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_4", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "news_url", "type": "string", "default": "", "description": "资讯来源网址"},
            {"name": "target_lang", "type": "string", "default": "zh-CN", "description": "目标语言"},
        ],
        "trigger": {"type": "schedule", "config": {"cron": "0 9 * * *", "timezone": "Asia/Shanghai"}},
    },
    {
        "id": "tpl_doc_analysis",
        "name": "文档智能分析",
        "description": "读取文档内容，进行深度分析并生成结构化报告",
        "category": "文档处理",
        "icon": "📊",
        "tags": ["文档", "分析", "报告"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.doc_proc",
                "name": "文档解析",
                "config": {"action": "parse", "file_path": ""},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "skill.data_analysis",
                "name": "深度分析",
                "config": {"action": "analyze"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3", "block_4"],
            },
            {
                "id": "block_3",
                "type": "skill.tide_memory",
                "name": "存档记忆",
                "config": {"action": "store", "domain": "documents"},
                "position": {"x": 590, "y": 50},
                "next": [],
            },
            {
                "id": "block_4",
                "type": "skill.notify",
                "name": "发送报告",
                "config": {"action": "send", "channel": "email"},
                "position": {"x": 590, "y": 200},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_4", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "file_path", "type": "string", "default": "", "description": "文档路径"},
            {"name": "notify_channel", "type": "string", "default": "email", "description": "通知渠道"},
        ],
        "trigger": {"type": "manual", "config": {}},
    },
    {
        "id": "tpl_research_assistant",
        "name": "研究助手",
        "description": "多源搜索 + 网页抓取 + 全文检索 + 知识存档，辅助研究工作",
        "category": "研究辅助",
        "icon": "🔍",
        "tags": ["研究", "搜索", "知识管理"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.fulltext_search",
                "name": "文献搜索",
                "config": {"action": "search", "query": ""},
                "position": {"x": 50, "y": 60},
                "next": ["block_3"],
            },
            {
                "id": "block_2",
                "type": "skill.web_fetch",
                "name": "网页抓取",
                "config": {"action": "fetch"},
                "position": {"x": 50, "y": 200},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "skill.data_analysis",
                "name": "信息整合",
                "config": {"action": "summarize"},
                "position": {"x": 320, "y": 130},
                "next": ["block_4"],
            },
            {
                "id": "block_4",
                "type": "skill.tide_memory",
                "name": "研究档案",
                "config": {"action": "store", "domain": "research"},
                "position": {"x": 590, "y": 130},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_4", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "research_topic", "type": "string", "default": "", "description": "研究主题"},
            {"name": "sources", "type": "array", "default": [], "description": "参考来源列表"},
        ],
        "trigger": {"type": "manual", "config": {}},
    },
    {
        "id": "tpl_meeting_minutes",
        "name": "会议纪要助手",
        "description": "录入会议内容 → 提取要点 → 翻译整理 → 生成纪要 → 通知分发",
        "category": "办公效率",
        "icon": "📝",
        "tags": ["会议", "纪要", "效率"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.doc_proc",
                "name": "会议录入",
                "config": {"action": "parse"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "skill.data_analysis",
                "name": "要点提取",
                "config": {"action": "summarize"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "skill.translate",
                "name": "双语整理",
                "config": {"action": "translate", "target_lang": "en"},
                "position": {"x": 590, "y": 120},
                "next": ["block_4"],
            },
            {
                "id": "block_4",
                "type": "skill.notify",
                "name": "发送纪要",
                "config": {"action": "send", "channel": "email"},
                "position": {"x": 860, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_4", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "meeting_title", "type": "string", "default": "", "description": "会议标题"},
            {"name": "participants", "type": "array", "default": [], "description": "参会人员"},
            {"name": "target_lang", "type": "string", "default": "en", "description": "翻译目标语言"},
        ],
        "trigger": {"type": "manual", "config": {}},
    },
    {
        "id": "tpl_multi_lang_pipeline",
        "name": "多语言内容流水线",
        "description": "内容抓取 → 多语言翻译 → 记忆归档 → 多渠道发布通知",
        "category": "内容生产",
        "icon": "🌐",
        "tags": ["多语言", "内容", "流水线"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.web_fetch",
                "name": "内容源抓取",
                "config": {"action": "fetch"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "skill.data_analysis",
                "name": "内容润色",
                "config": {"action": "summarize"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3", "block_4"],
            },
            {
                "id": "block_3",
                "type": "skill.translate",
                "name": "英文翻译",
                "config": {"action": "translate", "target_lang": "en"},
                "position": {"x": 590, "y": 50},
                "next": ["block_5"],
            },
            {
                "id": "block_4",
                "type": "skill.translate",
                "name": "日文翻译",
                "config": {"action": "translate", "target_lang": "ja"},
                "position": {"x": 590, "y": 200},
                "next": ["block_5"],
            },
            {
                "id": "block_5",
                "type": "skill.tide_memory",
                "name": "多语归档",
                "config": {"action": "store", "domain": "content"},
                "position": {"x": 860, "y": 120},
                "next": ["block_6"],
            },
            {
                "id": "block_6",
                "type": "skill.notify",
                "name": "发布通知",
                "config": {"action": "send"},
                "position": {"x": 1130, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_4", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_5", "fromPort": "output", "toPort": "input"},
            {"from": "block_4", "to": "block_5", "fromPort": "output", "toPort": "input"},
            {"from": "block_5", "to": "block_6", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "source_url", "type": "string", "default": "", "description": "内容来源 URL"},
            {"name": "languages", "type": "array", "default": ["en", "ja"], "description": "目标语言列表"},
        ],
        "trigger": {"type": "schedule", "config": {"cron": "0 10 * * *", "timezone": "Asia/Shanghai"}},
    },
    # 新增模板（6-12）
    {
        "id": "tpl_api_integration",
        "name": "API 数据集成",
        "description": "调用外部 API 获取数据 → 数据转换 → 存入记忆 → 通知",
        "category": "集成",
        "icon": "🔗",
        "tags": ["API", "集成", "数据"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.http_request",
                "name": "API 调用",
                "config": {"method": "GET", "url": "", "action": "request"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "data.transform",
                "name": "数据转换",
                "config": {"operation": "map", "action": "transform"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "skill.tide_memory",
                "name": "数据归档",
                "config": {"action": "store", "domain": "api_data"},
                "position": {"x": 590, "y": 120},
                "next": ["block_4"],
            },
            {
                "id": "block_4",
                "type": "skill.notify",
                "name": "完成通知",
                "config": {"action": "send", "channel": "system"},
                "position": {"x": 860, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_4", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "api_url", "type": "string", "default": "", "description": "API 地址"},
            {"name": "api_key", "type": "string", "default": "", "description": "API 密钥"},
        ],
        "trigger": {"type": "schedule", "config": {"cron": "0 * * * *", "timezone": "Asia/Shanghai"}},
    },
    {
        "id": "tpl_conditional_notification",
        "name": "条件通知工作流",
        "description": "获取数据 → 条件判断 → 满足条件发送通知，否则跳过",
        "category": "自动化",
        "icon": "⚡",
        "tags": ["条件", "通知", "自动化"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.tide_memory",
                "name": "获取数据",
                "config": {"action": "recall", "domain": "default"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "logic.condition",
                "name": "条件判断",
                "config": {"expression": "result != None", "action": "evaluate"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3", "block_4"],
            },
            {
                "id": "block_3",
                "type": "skill.notify",
                "name": "发送通知",
                "config": {"action": "send", "channel": "system"},
                "position": {"x": 590, "y": 50},
                "next": [],
            },
            {
                "id": "block_4",
                "type": "skill.tide_memory",
                "name": "记录跳过",
                "config": {"action": "store", "domain": "skipped"},
                "position": {"x": 590, "y": 200},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_4", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "threshold", "type": "number", "default": 100, "description": "阈值"},
            {"name": "notify_channel", "type": "string", "default": "system", "description": "通知渠道"},
        ],
        "trigger": {"type": "schedule", "config": {"cron": "*/30 * * * *", "timezone": "Asia/Shanghai"}},
    },
    {
        "id": "tpl_data_pipeline",
        "name": "数据处理流水线",
        "description": "数据获取 → 过滤 → 转换 → 排序 → 存储",
        "category": "数据处理",
        "icon": "📈",
        "tags": ["数据", "流水线", "转换"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.data_analysis",
                "name": "数据获取",
                "config": {"action": "analyze"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "data.transform",
                "name": "数据过滤",
                "config": {"operation": "filter", "condition": "value > 0", "action": "filter"},
                "position": {"x": 280, "y": 120},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "data.transform",
                "name": "字段映射",
                "config": {"operation": "map", "action": "map"},
                "position": {"x": 510, "y": 120},
                "next": ["block_4"],
            },
            {
                "id": "block_4",
                "type": "data.transform",
                "name": "数据排序",
                "config": {"operation": "sort", "sort_key": "date", "reverse": True, "action": "sort"},
                "position": {"x": 740, "y": 120},
                "next": ["block_5"],
            },
            {
                "id": "block_5",
                "type": "skill.tide_memory",
                "name": "结果存储",
                "config": {"action": "store", "domain": "data_pipeline"},
                "position": {"x": 970, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_4", "fromPort": "output", "toPort": "input"},
            {"from": "block_4", "to": "block_5", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "data_source", "type": "string", "default": "", "description": "数据源"},
            {"name": "filter_condition", "type": "string", "default": "", "description": "过滤条件"},
        ],
        "trigger": {"type": "manual", "config": {}},
    },
    {
        "id": "tpl_delayed_reminder",
        "name": "延时提醒工作流",
        "description": "接收提醒内容 → 延时等待 → 发送提醒通知",
        "category": "自动化",
        "icon": "⏰",
        "tags": ["延时", "提醒", "通知"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.tide_memory",
                "name": "获取提醒",
                "config": {"action": "recall", "domain": "reminders"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "control.delay",
                "name": "延时等待",
                "config": {"duration": 300, "unit": "second", "mode": "fixed", "action": "wait"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "skill.notify",
                "name": "发送提醒",
                "config": {"action": "send", "channel": "system"},
                "position": {"x": 590, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "reminder_text", "type": "string", "default": "", "description": "提醒内容"},
            {"name": "delay_seconds", "type": "number", "default": 300, "description": "延时秒数"},
            {"name": "channel", "type": "string", "default": "system", "description": "通知渠道"},
        ],
        "trigger": {"type": "webhook", "config": {}},
    },
    {
        "id": "tpl_voice_memo",
        "name": "语音备忘录",
        "description": "录音 → 语音识别 → 文本整理 → 存入记忆",
        "category": "语音处理",
        "icon": "🎙️",
        "tags": ["语音", "ASR", "备忘录"],
        "blocks": [
            {
                "id": "block_1",
                "type": "voice.record",
                "name": "录音",
                "config": {"duration": 30, "action": "record"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "voice.asr",
                "name": "语音识别",
                "config": {"language": "zh", "action": "transcribe"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "skill.data_analysis",
                "name": "内容整理",
                "config": {"action": "summarize"},
                "position": {"x": 590, "y": 120},
                "next": ["block_4"],
            },
            {
                "id": "block_4",
                "type": "skill.tide_memory",
                "name": "存入记忆",
                "config": {"action": "store", "domain": "voice_memos"},
                "position": {"x": 860, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_4", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "duration", "type": "number", "default": 30, "description": "录音时长（秒）"},
            {"name": "language", "type": "string", "default": "zh", "description": "语言"},
        ],
        "trigger": {"type": "manual", "config": {}},
    },
    {
        "id": "tpl_batch_processing",
        "name": "批量处理工作流",
        "description": "循环处理列表中的每个项目，逐个执行操作",
        "category": "数据处理",
        "icon": "🔄",
        "tags": ["循环", "批量", "处理"],
        "blocks": [
            {
                "id": "block_1",
                "type": "logic.loop",
                "name": "循环处理",
                "config": {"loop_type": "for", "max_iterations": 100, "action": "for"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "data.transform",
                "name": "数据处理",
                "config": {"operation": "map", "action": "transform"},
                "position": {"x": 320, "y": 120},
                "next": ["block_3"],
            },
            {
                "id": "block_3",
                "type": "skill.tide_memory",
                "name": "结果存储",
                "config": {"action": "store", "domain": "batch_results"},
                "position": {"x": 590, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_3", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "items", "type": "array", "default": [], "description": "待处理项目列表"},
            {"name": "max_iterations", "type": "number", "default": 100, "description": "最大迭代次数"},
        ],
        "trigger": {"type": "manual", "config": {}},
    },
    {
        "id": "tpl_content_localization",
        "name": "内容本地化工作流",
        "description": "内容抓取 → 多语言翻译 → 格式化 → 批量输出",
        "category": "内容生产",
        "icon": "🌍",
        "tags": ["本地化", "翻译", "内容"],
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.web_fetch",
                "name": "原文抓取",
                "config": {"action": "fetch"},
                "position": {"x": 50, "y": 120},
                "next": ["block_2"],
            },
            {
                "id": "block_2",
                "type": "skill.translate",
                "name": "英文翻译",
                "config": {"action": "translate", "target_lang": "en"},
                "position": {"x": 280, "y": 60},
                "next": ["block_4"],
            },
            {
                "id": "block_3",
                "type": "skill.translate",
                "name": "日文翻译",
                "config": {"action": "translate", "target_lang": "ja"},
                "position": {"x": 280, "y": 180},
                "next": ["block_4"],
            },
            {
                "id": "block_4",
                "type": "data.transform",
                "name": "格式统一",
                "config": {"operation": "format", "template": "{text}", "action": "format"},
                "position": {"x": 540, "y": 120},
                "next": ["block_5"],
            },
            {
                "id": "block_5",
                "type": "skill.notify",
                "name": "发布通知",
                "config": {"action": "send_batch"},
                "position": {"x": 800, "y": 120},
                "next": [],
            },
        ],
        "connections": [
            {"from": "block_1", "to": "block_2", "fromPort": "output", "toPort": "input"},
            {"from": "block_1", "to": "block_3", "fromPort": "output", "toPort": "input"},
            {"from": "block_2", "to": "block_4", "fromPort": "output", "toPort": "input"},
            {"from": "block_3", "to": "block_4", "fromPort": "output", "toPort": "input"},
            {"from": "block_4", "to": "block_5", "fromPort": "output", "toPort": "input"},
        ],
        "variables": [
            {"name": "source_url", "type": "string", "default": "", "description": "原文 URL"},
            {"name": "target_languages", "type": "array", "default": ["en", "ja"], "description": "目标语言列表"},
        ],
        "trigger": {"type": "manual", "config": {}},
    },
]


# ============================================================
# API 端点
# ============================================================

@router.get("")
async def list_templates(
    request: Request,
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    current_user: dict = Depends(get_current_user),
):
    """获取模板列表."""
    templates = [t.copy() for t in TEMPLATES]

    # 分类筛选
    if category:
        templates = [t for t in templates if t.get("category") == category]

    # 搜索
    if search:
        keyword = search.lower()
        templates = [
            t for t in templates
            if keyword in t.get("name", "").lower()
            or keyword in t.get("description", "").lower()
            or any(keyword in tag.lower() for tag in t.get("tags", []))
        ]

    return ApiResponse.success(
        data={
            "total": len(templates),
            "items": templates,
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/{template_id}")
async def get_template_detail(
    request: Request,
    template_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取模板详情."""
    for tpl in TEMPLATES:
        if tpl["id"] == template_id:
            return ApiResponse.success(
                data=tpl,
                request_id=request.headers.get("X-Request-ID", ""),
            )

    return ApiResponse.error(
        code=404,
        message=f"模板 {template_id} 不存在",
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/{template_id}/apply")
async def apply_template(
    request: Request,
    template_id: str,
    req: TemplateApplyRequest = TemplateApplyRequest(),
    current_user: dict = Depends(get_current_user),
):
    """应用模板创建工作流.

    基于模板创建一个新的草稿工作流。
    """
    template = None
    for tpl in TEMPLATES:
        if tpl["id"] == template_id:
            template = tpl
            break

    if not template:
        return ApiResponse.error(
            code=404,
            message=f"模板 {template_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    now = _now_iso()
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"

    # 为每个积木块生成新的 ID（避免与模板 ID 冲突）
    id_map = {}
    new_blocks = []
    for block in template.get("blocks", []):
        new_id = f"block_{uuid.uuid4().hex[:8]}"
        id_map[block["id"]] = new_id
        new_block = {
            **block,
            "id": new_id,
            "next": [],  # 稍后重建 next 关系
        }
        new_blocks.append(new_block)

    # 重建 next 关系
    for i, block in enumerate(template.get("blocks", [])):
        new_next = []
        for next_id in block.get("next", []):
            if next_id in id_map:
                new_next.append(id_map[next_id])
        new_blocks[i]["next"] = new_next

    # 重建 connections
    new_connections = []
    for conn in template.get("connections", []):
        new_from = id_map.get(conn.get("from", ""), conn.get("from", ""))
        new_to = id_map.get(conn.get("to", ""), conn.get("to", ""))
        new_conn = {
            **conn,
            "from": new_from,
            "to": new_to,
        }
        new_connections.append(new_conn)

    workflow = {
        "id": workflow_id,
        "name": req.name or f"{template['name']} - 副本",
        "description": template.get("description", ""),
        "category": req.category or template.get("category", "未分类"),
        "status": "draft",
        "blocks": new_blocks,
        "connections": new_connections,
        "variables": template.get("variables", []),
        "trigger": template.get("trigger", {"type": "manual", "config": {}}),
        "created_at": now,
        "updated_at": now,
        "run_count": 0,
        "created_by": current_user.get("username", ""),
        "template_id": template_id,
    }

    _storage.upsert_workflow(workflow_id, workflow)

    return ApiResponse.success(
        message="模板应用成功，已创建工作流",
        data=workflow,
        request_id=request.headers.get("X-Request-ID", ""),
    )
