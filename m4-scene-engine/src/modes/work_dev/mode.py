"""工作开发模式 - 模式类.

实现 BaseMode 基类接口，提供工作开发模式的生命周期管理、
消息处理和配置管理功能。
"""

from __future__ import annotations

from typing import Any

from src.models.db import get_session
from src.modes.base_mode import BaseMode
from src.modes.work_dev.service import WorkDevService

import structlog

logger = structlog.get_logger(__name__)


class WorkDevMode(BaseMode):
    """工作开发模式类.

    提供项目管理、任务看板、AI 代码助手、Git 管理、
    代码沙箱、可视化统计等工作开发相关功能。

    功能模块:
        - 项目管理：项目 CRUD，按状态/分类筛选，项目详情统计
        - 任务看板：任务管理，看板视图，状态流转
        - AI 代码助手：代码生成、审查、解释、调试（简化版，预留 LLM 接入）
        - Git 管理：仓库列表、提交历史、分支管理
        - 代码沙箱：多语言代码执行，安全检测
        - 可视化统计：代码行数、提交频率、任务完成率
    """

    # 模式基本信息
    mode_id = "work_dev"
    mode_name = "工作开发"
    mode_description = "编程开发、代码编写、项目管理，提升工作效率"
    icon = "💻"
    category = "work"
    priority = 2
    is_enabled = True

    # -----------------------------------------------------------------------
    # 生命周期方法
    # -----------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入工作开发模式.

        加载项目概览、今日任务、最近提交等数据，
        展示欢迎信息和工作开发概览。

        Args:
            context: 上下文字典，包含 user_id 等信息

        Returns:
            进入模式结果字典
        """
        user_id = context.get("user_id", "default")

        try:
            db = get_session()
            service = WorkDevService(db, user_id=str(user_id))
            overview = service.get_overview()
            stats = overview.get("stats", {})
            recent_tasks = overview.get("recent_tasks", [])
            recent_commits = overview.get("recent_commits", [])

            # 生成欢迎语
            project_count = stats.get("total_projects", 0)
            active_projects = stats.get("active_projects", 0)
            todo_tasks = stats.get("todo_tasks", 0)
            week_commits = stats.get("week_commits", 0)

            welcome_msg = (
                f"欢迎来到「工作开发」模式！💻\n"
                f"你目前有 {project_count} 个项目（{active_projects} 个活跃中），"
                f"{todo_tasks} 个待办任务，"
                f"本周已有 {week_commits} 次代码提交。\n"
            )

            if recent_tasks:
                task_titles = "、".join(
                    [t["title"] for t in recent_tasks[:3]]
                )
                welcome_msg += f"最近在忙：{task_titles}。\n"

            welcome_msg += "有什么我可以帮你的吗？"

            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "overview": overview,
                    "welcome_message": welcome_msg,
                    "recent_tasks": recent_tasks,
                    "recent_commits": recent_commits,
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                    "work_dev_stats": stats,
                },
            }
        except Exception as e:
            logger.error("on_enter 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "welcome_message": "欢迎来到「工作开发」模式！💻 有什么我可以帮你的吗？",
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                },
            }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开工作开发模式.

        保存当前状态，释放资源。

        Args:
            context: 上下文字典

        Returns:
            离开模式结果字典
        """
        return {
            "success": True,
            "message": f"已离开「{self.mode_name}」模式",
            "data": {},
        }

    # -----------------------------------------------------------------------
    # 消息处理方法
    # -----------------------------------------------------------------------

    # -------------------------------------------------------------------
    # 消息处理子步骤
    # -------------------------------------------------------------------

    def _init_handle_context(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """初始化消息处理上下文.

        从上下文中提取用户ID，规范化消息文本。

        Args:
            message: 用户输入的原始文本消息
            context: 当前上下文字典

        Returns:
            初始化后的上下文字典，包含 user_id 和 msg（去除空白后的消息）
        """
        return {
            "user_id": context.get("user_id", "default"),
            "msg": message.strip(),
        }

    def _match_and_handle_keywords(
        self,
        msg: str,
        service: WorkDevService,
    ) -> tuple[str, dict[str, Any]]:
        """关键词匹配与处理.

        根据消息内容匹配对应的意图分类，调用 service 获取数据，
        并生成回复文本和动作数据。

        Args:
            msg: 去除空白后的消息文本
            service: WorkDevService 实例

        Returns:
            (reply, action_data) - 回复文本和动作数据字典
        """
        reply = ""
        action_data: dict[str, Any] = {}

        # 项目相关
        if any(kw in msg for kw in ["项目", "project", "工程"]):
            if any(kw in msg for kw in ["新建", "创建", "新增"]):
                reply = "好的，你想创建什么项目？可以告诉我项目名称和描述哦～"
                action_data = {"type": "create_project", "data": {}}
            elif any(kw in msg for kw in ["列表", "全部", "所有"]):
                projects = service.list_projects()
                project_names = "、".join([p["name"] for p in projects[:5]])
                reply = f"📁 你共有 {len(projects)} 个项目：{project_names}"
                if len(projects) > 5:
                    reply += f"等 {len(projects)} 个项目"
                action_data = {"type": "project_list", "data": projects}
            elif any(kw in msg for kw in ["详情", "详细"]):
                projects = service.list_projects()
                if projects:
                    detail = service.get_project_detail(projects[0]["project_id"])
                    if detail:
                        reply = (
                            f"📊 「{detail['name']}」项目详情：\n"
                            f"• 状态：{detail['status']}\n"
                            f"• 进度：{detail['progress']}%\n"
                            f"• 任务：{detail.get('task_count', 0)} 个\n"
                            f"• 代码行数：{detail['line_count']} 行"
                        )
                        action_data = {"type": "project_detail", "data": detail}
                    else:
                        reply = "未找到项目详情"
                else:
                    reply = "还没有项目，先创建一个吧！"
            else:
                overview = service.get_overview()
                stats = overview["stats"]
                reply = (
                    f"📊 工作开发概览：\n"
                    f"• 项目总数：{stats['total_projects']} 个\n"
                    f"• 活跃项目：{stats['active_projects']} 个\n"
                    f"• 任务总数：{stats['total_tasks']} 个\n"
                    f"• 本周提交：{stats['week_commits']} 次\n"
                    f"• 代码总行数：{stats['total_lines']} 行"
                )
                action_data = {"type": "overview", "data": overview}

        # 任务相关
        elif any(kw in msg for kw in ["任务", "todo", "待办"]):
            if any(kw in msg for kw in ["看板", "board"]):
                board = service.get_task_board()
                todo_count = len(board.get("todo", []))
                in_progress_count = len(board.get("in_progress", []))
                done_count = len(board.get("done", []))
                reply = (
                    f"📋 任务看板：\n"
                    f"• 待办：{todo_count} 个\n"
                    f"• 进行中：{in_progress_count} 个\n"
                    f"• 已完成：{done_count} 个"
                )
                action_data = {"type": "task_board", "data": board}
            elif any(kw in msg for kw in ["新建", "创建", "添加"]):
                reply = "好的，你想创建什么任务？可以告诉我任务标题和所属项目哦～"
                action_data = {"type": "create_task", "data": {}}
            else:
                tasks = service.list_tasks()
                todo_tasks = [t for t in tasks if t["status"] == "todo"]
                reply = f"📝 你共有 {len(tasks)} 个任务，其中 {len(todo_tasks)} 个待办。"
                if todo_tasks:
                    task_titles = "、".join(
                        [t["title"] for t in todo_tasks[:3]]
                    )
                    reply += f"\n待办任务：{task_titles}"
                action_data = {"type": "task_list", "data": tasks}

        # 代码/Git 相关
        elif any(kw in msg for kw in ["代码", "code", "编程", "写代码"]):
            reply = (
                "💻 我可以帮你进行代码操作哦！\n"
                "你可以试试：\n"
                "• 「生成代码」- AI 生成代码\n"
                "• 「代码审查」- 检查代码问题\n"
                "• 「代码解释」- 解释代码逻辑\n"
                "• 「运行代码」- 在沙箱中执行代码"
            )
            action_data = {"type": "code_help", "data": {}}

        elif any(kw in msg for kw in ["git", "提交", "commit", "仓库"]):
            commits = service.list_commits(limit=5)
            commit_msgs = "\n".join(
                [f"• {c['message']}" for c in commits[:5]]
            )
            reply = f"🔧 最近提交：\n{commit_msgs}"
            action_data = {"type": "git_commits", "data": commits}

        # 统计相关
        elif any(kw in msg for kw in ["统计", "概览", "数据", "报表"]):
            overview = service.get_overview()
            stats = overview["stats"]
            reply = (
                f"📊 工作开发统计：\n"
                f"• 项目：{stats['total_projects']} 个（活跃 {stats['active_projects']} 个）\n"
                f"• 任务：{stats['total_tasks']} 个（完成率 {stats['task_completion_rate']}%）\n"
                f"• 提交：{stats['total_commits']} 次（本周 {stats['week_commits']} 次）\n"
                f"• 代码行数：{stats['total_lines']} 行"
            )
            action_data = {"type": "stats", "data": stats}

        # 帮助
        elif any(kw in msg for kw in ["帮助", "help", "能做什么", "功能"]):
            reply = (
                "💻 工作开发模式可以帮你：\n\n"
                "📁 **项目管理**\n"
                "   查看项目列表、创建项目、项目详情统计\n\n"
                "📋 **任务看板**\n"
                "   任务管理、看板视图、状态流转\n\n"
                "🤖 **AI 代码助手**\n"
                "   代码生成、审查、解释、调试\n\n"
                "🔧 **Git 管理**\n"
                "   提交历史、分支管理\n\n"
                "⚡ **代码沙箱**\n"
                "   多语言代码执行、安全检测\n\n"
                "📊 **可视化统计**\n"
                "   代码行数、提交频率、任务完成率\n\n"
                "试试说「查看项目」、「任务看板」或「生成代码」吧～"
            )
            action_data = {"type": "help", "data": {}}

        # 默认回复
        else:
            reply = (
                "💻 我可以帮你管理开发工作哦！你可以试试：\n"
                "• 查看「项目」列表\n"
                "• 查看「任务看板」\n"
                "• 「生成代码」或「代码审查」\n"
                "• 查看 Git「提交」记录\n"
                "• 查看「统计」数据\n"
                "也可以说「帮助」了解更多功能～"
            )
            action_data = {"type": "default", "data": {}}

        return reply, action_data

    def _build_response(
        self,
        reply: str,
        action_data: dict[str, Any],
        context_updates: dict[str, Any],
    ) -> dict[str, Any]:
        """构造统一的消息处理响应.

        Args:
            reply: 回复文本
            action_data: 动作数据字典
            context_updates: 上下文更新字典

        Returns:
            标准格式的响应字典
        """
        return {
            "success": True,
            "reply": reply,
            "data": action_data,
            "context_updates": context_updates,
        }

    # -------------------------------------------------------------------
    # 主流程
    # -------------------------------------------------------------------

    async def handle_message(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理用户消息.

        根据用户输入进行简单的意图识别和响应。
        支持的意图：项目、任务、代码、Git、帮助等。

        Args:
            message: 用户输入的文本消息
            context: 当前上下文字典

        Returns:
            消息处理结果字典
        """
        # 1. 初始化上下文
        ctx = self._init_handle_context(message, context)
        user_id = ctx["user_id"]
        msg = ctx["msg"]

        reply = ""
        action_data: dict[str, Any] = {}
        context_updates: dict[str, Any] = {}

        try:
            db = get_session()
            service = WorkDevService(db, user_id=str(user_id))

            # 2. 关键词匹配与处理
            reply, action_data = self._match_and_handle_keywords(msg, service)

        except Exception as e:
            logger.error("handle_message 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
            reply = "抱歉，处理你的消息时出现了问题，请稍后再试。"
            action_data = {"type": "error", "data": {"error": str(e)}}

        # 3. 构造响应
        return self._build_response(reply, action_data, context_updates)

    # -----------------------------------------------------------------------
    # 配置管理方法
    # -----------------------------------------------------------------------

    async def get_config(self) -> dict[str, Any]:
        """获取工作开发模式配置.

        Returns:
            配置项字典
        """
        return {
            "default_language": {
                "name": "默认编程语言",
                "description": "新建项目和代码操作的默认语言",
                "type": "select",
                "value": "python",
                "options": [
                    "python", "javascript", "typescript", "go", "rust",
                ],
            },
            "code_assistant_enabled": {
                "name": "启用 AI 代码助手",
                "description": "是否启用 AI 代码生成和审查功能",
                "type": "boolean",
                "value": True,
            },
            "sandbox_enabled": {
                "name": "启用代码沙箱",
                "description": "是否允许在沙箱中执行代码",
                "type": "boolean",
                "value": True,
            },
            "git_integration_enabled": {
                "name": "启用 Git 集成",
                "description": "是否展示 Git 提交和分支管理",
                "type": "boolean",
                "value": True,
            },
            "auto_save_snippets": {
                "name": "自动保存代码片段",
                "description": "生成的代码是否自动保存到片段库",
                "type": "boolean",
                "value": False,
            },
            "sandbox_timeout": {
                "name": "沙箱超时时间",
                "description": "代码执行的超时时间（秒）",
                "type": "number",
                "value": 10,
            },
        }
