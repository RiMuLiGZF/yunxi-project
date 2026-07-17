"""M7 积木平台 - 工作流模板市场服务.

提供工作流模板的管理功能：
- 内置模板列表
- 模板分类
- 模板搜索
- 从模板创建工作流
- 自定义模板管理
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


# 内置工作流模板
BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "tpl_chat_bot",
        "name": "AI 聊天机器人",
        "description": "简单的 AI 对话工作流，接收用户输入，调用 LLM 生成回复",
        "category": "AI 助手",
        "icon": "🤖",
        "tags": ["AI", "对话", "LLM"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 1250,
        "blocks": [
            {"id": "start", "type": "start", "name": "开始", "next": ["llm"]},
            {"id": "llm", "type": "llm", "name": "AI 回复", "next": ["end"], "config": {"model": "gpt-4"}},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"user_input": {"type": "string", "default": ""}},
    },
    {
        "id": "tpl_data_pipeline",
        "name": "数据处理管道",
        "description": "获取数据 → 数据清洗 → 数据转换 → 输出结果",
        "category": "数据处理",
        "icon": "📊",
        "tags": ["数据", "管道", "ETL"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 890,
        "blocks": [
            {"id": "start", "type": "start", "name": "开始", "next": ["fetch"]},
            {"id": "fetch", "type": "http_request", "name": "获取数据", "next": ["clean"]},
            {"id": "clean", "type": "code", "name": "数据清洗", "next": ["transform"]},
            {"id": "transform", "type": "transform", "name": "数据转换", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"api_url": {"type": "string", "default": ""}},
    },
    {
        "id": "tpl_email_workflow",
        "name": "邮件通知工作流",
        "description": "触发条件 → 生成内容 → 发送邮件通知",
        "category": "通知",
        "icon": "📧",
        "tags": ["邮件", "通知", "自动化"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 720,
        "blocks": [
            {"id": "start", "type": "start", "name": "触发", "next": ["generate"]},
            {"id": "generate", "type": "llm", "name": "生成内容", "next": ["send"]},
            {"id": "send", "type": "email", "name": "发送邮件", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"to_email": {"type": "string", "default": ""}},
    },
    {
        "id": "tpl_form_processing",
        "name": "表单处理流程",
        "description": "接收表单数据 → 验证 → 存储 → 返回结果",
        "category": "业务流程",
        "icon": "📝",
        "tags": ["表单", "验证", "存储"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 650,
        "blocks": [
            {"id": "start", "type": "start", "name": "接收表单", "next": ["validate"]},
            {"id": "validate", "type": "code", "name": "数据验证", "next": ["store"]},
            {"id": "store", "type": "database", "name": "存储数据", "next": ["end"]},
            {"id": "end", "type": "end", "name": "返回结果", "next": []},
        ],
        "variables": {},
    },
    {
        "id": "tpl_approval_workflow",
        "name": "审批工作流",
        "description": "提交申请 → 条件判断 → 多级审批 → 通知结果",
        "category": "业务流程",
        "icon": "✅",
        "tags": ["审批", "工作流", "条件"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 580,
        "blocks": [
            {"id": "start", "type": "start", "name": "提交申请", "next": ["condition"]},
            {"id": "condition", "type": "condition", "name": "金额判断", "next": ["approve1", "approve2"]},
            {"id": "approve1", "type": "approval", "name": "一级审批", "next": ["notify"]},
            {"id": "approve2", "type": "approval", "name": "二级审批", "next": ["notify"]},
            {"id": "notify", "type": "notification", "name": "通知结果", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"amount": {"type": "number", "default": 0}},
    },
    {
        "id": "tpl_api_integration",
        "name": "API 数据集成",
        "description": "调用外部 API → 数据转换 → 存入记忆 → 通知",
        "category": "集成",
        "icon": "🔗",
        "tags": ["API", "集成", "数据"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 450,
        "blocks": [
            {"id": "start", "type": "start", "name": "开始", "next": ["api_call"]},
            {"id": "api_call", "type": "http_request", "name": "API 调用", "next": ["transform"]},
            {"id": "transform", "type": "transform", "name": "数据转换", "next": ["memory"]},
            {"id": "memory", "type": "memory", "name": "存入记忆", "next": ["notify"]},
            {"id": "notify", "type": "notification", "name": "发送通知", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"api_url": {"type": "string", "default": ""}},
    },
    {
        "id": "tpl_content_generation",
        "name": "内容生成器",
        "description": "根据主题生成文章/博客/营销文案等内容",
        "category": "内容创作",
        "icon": "✍️",
        "tags": ["内容", "生成", "AI"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 920,
        "blocks": [
            {"id": "start", "type": "start", "name": "输入主题", "next": ["outline"]},
            {"id": "outline", "type": "llm", "name": "生成大纲", "next": ["draft"]},
            {"id": "draft", "type": "llm", "name": "撰写初稿", "next": ["polish"]},
            {"id": "polish", "type": "llm", "name": "润色优化", "next": ["end"]},
            {"id": "end", "type": "end", "name": "输出内容", "next": []},
        ],
        "variables": {"topic": {"type": "string", "default": ""}, "content_type": {"type": "string", "default": "article"}},
    },
    {
        "id": "tpl_data_analysis",
        "name": "数据分析报告",
        "description": "加载数据 → 统计分析 → 生成图表 → 输出报告",
        "category": "数据处理",
        "icon": "📈",
        "tags": ["分析", "数据", "报告"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 780,
        "blocks": [
            {"id": "start", "type": "start", "name": "开始", "next": ["load"]},
            {"id": "load", "type": "code", "name": "加载数据", "next": ["analyze"]},
            {"id": "analyze", "type": "code", "name": "统计分析", "next": ["chart"]},
            {"id": "chart", "type": "code", "name": "生成图表", "next": ["report"]},
            {"id": "report", "type": "llm", "name": "生成报告", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"data_source": {"type": "string", "default": ""}},
    },
    {
        "id": "tpl_customer_support",
        "name": "客服自动回复",
        "description": "接收问题 → 知识库检索 → 生成回复 → 人工审核",
        "category": "AI 助手",
        "icon": "💬",
        "tags": ["客服", "知识库", "AI"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 560,
        "blocks": [
            {"id": "start", "type": "start", "name": "接收问题", "next": ["search"]},
            {"id": "search", "type": "knowledge_base", "name": "知识库检索", "next": ["generate"]},
            {"id": "generate", "type": "llm", "name": "生成回复", "next": ["review"]},
            {"id": "review", "type": "condition", "name": "是否需要人工", "next": ["human", "send"]},
            {"id": "human", "type": "human_review", "name": "人工审核", "next": ["send"]},
            {"id": "send", "type": "notification", "name": "发送回复", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"question": {"type": "string", "default": ""}},
    },
    {
        "id": "tpl_scheduled_task",
        "name": "定时任务工作流",
        "description": "定时触发 → 数据采集 → 处理 → 存档",
        "category": "自动化",
        "icon": "⏰",
        "tags": ["定时", "自动化", "调度"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 430,
        "blocks": [
            {"id": "start", "type": "start", "name": "定时触发", "next": ["collect"]},
            {"id": "collect", "type": "http_request", "name": "数据采集", "next": ["process"]},
            {"id": "process", "type": "code", "name": "数据处理", "next": ["save"]},
            {"id": "save", "type": "database", "name": "存档", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"schedule": {"type": "string", "default": "0 9 * * *"}},
    },
    {
        "id": "tpl_survey_analysis",
        "name": "问卷分析工作流",
        "description": "收集问卷 → 数据清洗 → 统计分析 → 生成洞察",
        "category": "数据处理",
        "icon": "📋",
        "tags": ["问卷", "分析", "洞察"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 340,
        "blocks": [
            {"id": "start", "type": "start", "name": "收集数据", "next": ["clean"]},
            {"id": "clean", "type": "code", "name": "数据清洗", "next": ["stats"]},
            {"id": "stats", "type": "code", "name": "统计分析", "next": ["insights"]},
            {"id": "insights", "type": "llm", "name": "生成洞察", "next": ["end"]},
            {"id": "end", "type": "end", "name": "输出报告", "next": []},
        ],
        "variables": {},
    },
    {
        "id": "tpl_multi_step_agent",
        "name": "多步骤智能体",
        "description": "规划 → 执行 → 反思 → 迭代的多步骤 AI 工作流",
        "category": "AI 助手",
        "icon": "🧠",
        "tags": ["Agent", "多步骤", "规划"],
        "version": "1.0.0",
        "language": "python",
        "usage_count": 670,
        "blocks": [
            {"id": "start", "type": "start", "name": "输入任务", "next": ["plan"]},
            {"id": "plan", "type": "llm", "name": "任务规划", "next": ["execute"]},
            {"id": "execute", "type": "code", "name": "执行步骤", "next": ["reflect"]},
            {"id": "reflect", "type": "llm", "name": "反思评估", "next": ["condition"]},
            {"id": "condition", "type": "condition", "name": "是否完成", "next": ["execute", "output"]},
            {"id": "output", "type": "llm", "name": "整理输出", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {"task": {"type": "string", "default": ""}, "max_iterations": {"type": "number", "default": 5}},
    },
]


class WorkflowTemplateManager:
    """工作流模板管理器."""

    def __init__(self, custom_templates_dir: Optional[str] = None) -> None:
        self._custom_templates: Dict[str, Dict[str, Any]] = {}
        self._custom_dir = custom_templates_dir
        if self._custom_dir:
            os.makedirs(self._custom_dir, exist_ok=True)
            self._load_custom_templates()

    def _load_custom_templates(self) -> None:
        """加载自定义模板."""
        if not self._custom_dir:
            return
        custom_file = os.path.join(self._custom_dir, "custom_templates.json")
        if os.path.exists(custom_file):
            try:
                with open(custom_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for tpl in data:
                            tpl_id = tpl.get("id", "")
                            if tpl_id:
                                self._custom_templates[tpl_id] = tpl
            except (json.JSONDecodeError, OSError):
                pass

    def _save_custom_templates(self) -> None:
        """保存自定义模板."""
        if not self._custom_dir:
            return
        custom_file = os.path.join(self._custom_dir, "custom_templates.json")
        try:
            templates_list = list(self._custom_templates.values())
            with open(custom_file, "w", encoding="utf-8") as f:
                json.dump(templates_list, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def list_templates(
        self,
        category: Optional[str] = None,
        language: Optional[str] = None,
        keyword: Optional[str] = None,
        sort_by: str = "popularity",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """获取模板列表.

        Args:
            category: 按分类筛选
            language: 按语言筛选
            keyword: 关键词搜索
            sort_by: 排序方式（popularity/name/created_at）
            limit: 数量限制
            offset: 偏移量

        Returns:
            模板列表结果
        """
        all_templates = list(BUILTIN_TEMPLATES) + list(self._custom_templates.values())

        # 分类筛选
        if category:
            all_templates = [t for t in all_templates if t.get("category") == category]

        # 语言筛选
        if language:
            all_templates = [t for t in all_templates if t.get("language") == language]

        # 关键词搜索
        if keyword:
            keyword_lower = keyword.lower()
            all_templates = [
                t for t in all_templates
                if keyword_lower in t.get("name", "").lower()
                or keyword_lower in t.get("description", "").lower()
                or any(keyword_lower in tag.lower() for tag in t.get("tags", []))
            ]

        # 排序
        if sort_by == "popularity":
            all_templates.sort(key=lambda t: t.get("usage_count", 0), reverse=True)
        elif sort_by == "name":
            all_templates.sort(key=lambda t: t.get("name", ""))

        total = len(all_templates)

        # 分页
        if limit is not None:
            all_templates = all_templates[offset : offset + limit]

        return {
            "success": True,
            "templates": all_templates,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """获取模板详情.

        Args:
            template_id: 模板 ID

        Returns:
            模板详情，不存在返回 None
        """
        # 先查内置模板
        for tpl in BUILTIN_TEMPLATES:
            if tpl["id"] == template_id:
                return tpl

        # 再查自定义模板
        if template_id in self._custom_templates:
            return self._custom_templates[template_id]

        return None

    def list_categories(self) -> List[Dict[str, Any]]:
        """获取模板分类列表.

        Returns:
            分类列表，包含每个分类的模板数量
        """
        category_count: Dict[str, int] = {}
        category_icons: Dict[str, str] = {}

        all_templates = list(BUILTIN_TEMPLATES) + list(self._custom_templates.values())

        for tpl in all_templates:
            cat = tpl.get("category", "其他")
            category_count[cat] = category_count.get(cat, 0) + 1
            if cat not in category_icons:
                category_icons[cat] = tpl.get("icon", "📁")

        return [
            {"name": name, "count": count, "icon": category_icons.get(name, "📁")}
            for name, count in sorted(category_count.items(), key=lambda x: x[1], reverse=True)
        ]

    def search_templates(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """搜索模板.

        Args:
            query: 搜索关键词
            category: 分类过滤
            limit: 最大结果数

        Returns:
            搜索结果
        """
        result = self.list_templates(
            category=category,
            keyword=query,
            sort_by="popularity",
            limit=limit,
        )
        return {
            "success": True,
            "query": query,
            "results": result["templates"],
            "total": result["total"],
        }

    def create_workflow_from_template(
        self,
        template_id: str,
        workflow_name: str,
        created_by: str = "",
        description: str = "",
    ) -> Dict[str, Any]:
        """从模板创建工作流.

        Args:
            template_id: 模板 ID
            workflow_name: 工作流名称
            created_by: 创建者
            description: 工作流描述

        Returns:
            创建结果（工作流数据）
        """
        template = self.get_template(template_id)
        if not template:
            return {
                "success": False,
                "error": f"模板不存在: {template_id}",
            }

        # 复制模板内容
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        now = time.time()

        workflow = {
            "id": workflow_id,
            "name": workflow_name,
            "description": description or f"基于模板「{template['name']}」创建",
            "category": template.get("category", ""),
            "icon": template.get("icon", "📋"),
            "blocks": [dict(block) for block in template.get("blocks", [])],
            "variables": dict(template.get("variables", {})),
            "template_id": template_id,
            "template_name": template.get("name", ""),
            "status": "draft",
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
            "version": "1.0.0",
        }

        return {
            "success": True,
            **workflow,
        }

    def save_custom_template(
        self,
        template_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """保存自定义模板.

        Args:
            template_data: 模板数据

        Returns:
            保存结果
        """
        template_id = template_data.get("id") or f"custom_{uuid.uuid4().hex[:12]}"

        template = {
            "id": template_id,
            "name": template_data.get("name", "自定义模板"),
            "description": template_data.get("description", ""),
            "category": template_data.get("category", "自定义"),
            "icon": template_data.get("icon", "🎨"),
            "tags": template_data.get("tags", []),
            "version": template_data.get("version", "1.0.0"),
            "language": template_data.get("language", "python"),
            "blocks": template_data.get("blocks", []),
            "variables": template_data.get("variables", {}),
            "usage_count": 0,
            "is_custom": True,
            "created_at": time.time(),
        }

        self._custom_templates[template_id] = template
        self._save_custom_templates()

        return {
            "success": True,
            "template_id": template_id,
            "template": template,
        }

    def delete_custom_template(self, template_id: str) -> Dict[str, Any]:
        """删除自定义模板.

        Args:
            template_id: 模板 ID

        Returns:
            删除结果
        """
        # 内置模板不能删除
        for tpl in BUILTIN_TEMPLATES:
            if tpl["id"] == template_id:
                return {
                    "success": False,
                    "error": "内置模板不能删除",
                }

        if template_id not in self._custom_templates:
            return {
                "success": False,
                "error": f"模板不存在: {template_id}",
            }

        del self._custom_templates[template_id]
        self._save_custom_templates()

        return {
            "success": True,
            "template_id": template_id,
        }


# 全局单例
_template_manager: Optional[WorkflowTemplateManager] = None


def get_template_manager() -> WorkflowTemplateManager:
    """获取模板管理器单例."""
    global _template_manager
    if _template_manager is None:
        _template_manager = WorkflowTemplateManager()
    return _template_manager
