"""技能执行器.

管理所有已注册的技能，提供技能注册、注销、查询、执行等功能。
支持单例模式、批量执行、异常捕获和执行日志记录。
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

from src.services.skills.base import BaseSkill


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 技能执行器
# ---------------------------------------------------------------------------

class SkillExecutor:
    """技能执行器.

    负责：
    - 技能的注册与注销
    - 技能的查询与列表
    - 技能的执行（单个 / 批量）
    - 执行异常捕获与日志记录
    - 生成 function calling 格式的工具定义

    使用单例模式，通过 get_skill_executor() 获取全局实例。
    """

    def __init__(self) -> None:
        """初始化技能执行器.

        自动注册所有内置技能。
        """
        # 技能注册表: {skill_name: skill_instance}
        self._skills: dict[str, BaseSkill] = {}

        # 执行日志（最近 N 条）
        self._execution_log: list[dict[str, Any]] = []
        self._max_logs = 500

        # 线程锁
        self._lock = Lock()

        # 自动注册内置技能
        self._register_builtin_skills()

    # -----------------------------------------------------------------------
    # 内置技能注册
    # -----------------------------------------------------------------------

    def _register_builtin_skills(self) -> None:
        """注册所有内置技能.

        使用懒加载（函数内导入），避免模块级循环依赖。
        每个技能独立 try/except，单个技能加载失败不影响其他技能。
        """
        builtin_skills = []

        # 尝试导入并注册内置技能
        try:
            from src.services.skills.vscode_control_skill import VSCodeControlSkill
            builtin_skills.append(VSCodeControlSkill())
        except Exception as e:
            logger.warning(f"注册 VSCodeControlSkill 失败: {e}")

        try:
            from src.services.skills.file_operation_skill import FileOperationSkill
            builtin_skills.append(FileOperationSkill())
        except Exception as e:
            logger.warning(f"注册 FileOperationSkill 失败: {e}")

        try:
            from src.services.skills.terminal_command_skill import TerminalCommandSkill
            builtin_skills.append(TerminalCommandSkill())
        except Exception as e:
            logger.warning(f"注册 TerminalCommandSkill 失败: {e}")

        try:
            from src.services.skills.git_tool_skill import GitToolSkill
            builtin_skills.append(GitToolSkill())
        except Exception as e:
            logger.warning(f"注册 GitToolSkill 失败: {e}")

        # 注册所有成功加载的技能
        for skill in builtin_skills:
            try:
                self.register_skill(skill)
            except Exception as e:
                logger.warning(f"注册技能 {skill.name} 失败: {e}")

    # -----------------------------------------------------------------------
    # 技能注册与注销
    # -----------------------------------------------------------------------

    def register_skill(self, skill: BaseSkill) -> bool:
        """注册一个技能.

        Args:
            skill: 技能实例

        Returns:
            是否注册成功

        Raises:
            ValueError: 技能名称为空或已存在
        """
        if not skill.name:
            raise ValueError("技能名称不能为空")

        with self._lock:
            if skill.name in self._skills:
                logger.warning(f"技能 {skill.name} 已存在，将被覆盖")

            self._skills[skill.name] = skill
            logger.info(f"已注册技能: {skill.name} ({skill.display_name})")
            return True

    def unregister_skill(self, skill_name: str) -> bool:
        """注销一个技能.

        Args:
            skill_name: 技能名称

        Returns:
            是否成功注销
        """
        with self._lock:
            if skill_name in self._skills:
                del self._skills[skill_name]
                logger.info(f"已注销技能: {skill_name}")
                return True
            return False

    # -----------------------------------------------------------------------
    # 技能查询
    # -----------------------------------------------------------------------

    def get_skill(self, skill_name: str) -> BaseSkill | None:
        """获取指定技能.

        Args:
            skill_name: 技能名称

        Returns:
            技能实例，不存在返回 None
        """
        with self._lock:
            return self._skills.get(skill_name)

    def list_skills(self, category: str | None = None) -> list[dict[str, Any]]:
        """列出所有技能.

        Args:
            category: 分类筛选（可选），可选值：development / productivity / communication / system

        Returns:
            技能信息列表
        """
        with self._lock:
            skills_list = []
            for skill in self._skills.values():
                if category and skill.category != category:
                    continue
                skills_list.append(skill.get_info())

            # 按分类、名称排序
            skills_list.sort(key=lambda x: (x["category"], x["name"]))
            return skills_list

    # -----------------------------------------------------------------------
    # 技能执行
    # -----------------------------------------------------------------------

    def execute_skill(
        self,
        skill_name: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行指定技能.

        Args:
            skill_name: 技能名称
            params: 技能参数
            context: 执行上下文（可选）

        Returns:
            执行结果字典，格式:
            {
                "success": bool,
                "skill_name": str,
                "message": str,
                "data": dict,
                "execution_time": float,
                "error": str (仅失败时),
                "error_code": str (仅失败时),
            }
        """
        start_time = time.time()
        ctx = context or {}

        # 获取技能
        skill = self.get_skill(skill_name)
        if skill is None:
            elapsed = time.time() - start_time
            result = {
                "success": False,
                "skill_name": skill_name,
                "message": f"技能不存在: {skill_name}",
                "data": {},
                "execution_time": round(elapsed, 4),
                "error": f"Skill not found: {skill_name}",
                "error_code": "SKILL_NOT_FOUND",
            }
            self._log_execution(result)
            return result

        # 执行技能
        try:
            result_data = skill.execute(params, ctx)
            elapsed = time.time() - start_time

            # 确保结果格式正确
            if isinstance(result_data, dict):
                result = {
                    "success": result_data.get("success", True),
                    "skill_name": skill_name,
                    "message": result_data.get("message", "执行成功"),
                    "data": result_data.get("data", result_data),
                    "execution_time": round(elapsed, 4),
                }
            else:
                result = {
                    "success": True,
                    "skill_name": skill_name,
                    "message": "执行成功",
                    "data": {"result": result_data},
                    "execution_time": round(elapsed, 4),
                }

            self._log_execution(result)
            return result

        except NotImplementedError as e:
            elapsed = time.time() - start_time
            result = {
                "success": False,
                "skill_name": skill_name,
                "message": f"技能未实现: {e}",
                "data": {},
                "execution_time": round(elapsed, 4),
                "error": str(e),
                "error_code": "SKILL_NOT_IMPLEMENTED",
            }
            self._log_execution(result)
            return result

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"执行技能 {skill_name} 时发生异常: {e}", exc_info=True)
            result = {
                "success": False,
                "skill_name": skill_name,
                "message": f"执行技能时发生异常: {e}",
                "data": {},
                "execution_time": round(elapsed, 4),
                "error": str(e),
                "error_code": "SKILL_EXECUTION_ERROR",
            }
            self._log_execution(result)
            return result

    def execute_batch(
        self,
        skill_calls: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """批量执行多个技能.

        按顺序执行每个技能调用，失败不阻塞后续执行。

        Args:
            skill_calls: 技能调用列表，每个元素为:
                {
                    "skill_name": "技能名",
                    "params": {...},  # 可选
                }
            context: 执行上下文（可选）

        Returns:
            执行结果列表，顺序与输入一致
        """
        ctx = context or {}
        results = []

        for call in skill_calls:
            skill_name = call.get("skill_name", "")
            params = call.get("params", {})

            result = self.execute_skill(skill_name, params, ctx)
            results.append(result)

        return results

    # -----------------------------------------------------------------------
    # 工具定义（供 Agent 使用）
    # -----------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """获取所有技能的 function calling 工具定义.

        返回符合 OpenAI function calling 规范的工具定义列表，
        供 Agent 框架使用。

        Returns:
            工具定义列表
        """
        with self._lock:
            tools = []
            for skill in self._skills.values():
                try:
                    tool_def = skill.get_tool_definition()
                    tools.append(tool_def)
                except Exception as e:
                    logger.warning(f"获取技能 {skill.name} 的工具定义失败: {e}")
            return tools

    # -----------------------------------------------------------------------
    # 执行日志
    # -----------------------------------------------------------------------

    def _log_execution(self, result: dict[str, Any]) -> None:
        """记录执行日志.

        Args:
            result: 执行结果字典
        """
        log_entry = {
            "timestamp": time.time(),
            "skill_name": result.get("skill_name", ""),
            "success": result.get("success", False),
            "execution_time": result.get("execution_time", 0),
            "error_code": result.get("error_code", ""),
            "message": result.get("message", ""),
        }

        with self._lock:
            self._execution_log.append(log_entry)
            # 限制日志数量
            if len(self._execution_log) > self._max_logs:
                self._execution_log = self._execution_log[-self._max_logs:]

    def get_execution_logs(
        self,
        limit: int = 20,
        skill_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取执行日志.

        Args:
            limit: 返回条数限制
            skill_name: 按技能名筛选（可选）

        Returns:
            日志列表（按时间倒序）
        """
        with self._lock:
            logs = list(self._execution_log)

        # 筛选
        if skill_name:
            logs = [log for log in logs if log["skill_name"] == skill_name]

        # 倒序
        logs.reverse()

        # 限制数量
        if limit > 0:
            logs = logs[:limit]

        return logs

    # -----------------------------------------------------------------------
    # 统计信息
    # -----------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """获取技能统计信息.

        Returns:
            统计信息字典
        """
        with self._lock:
            total_skills = len(self._skills)
            categories: dict[str, int] = {}
            for skill in self._skills.values():
                cat = skill.category
                categories[cat] = categories.get(cat, 0) + 1

            total_executions = len(self._execution_log)
            success_count = sum(1 for log in self._execution_log if log["success"])
            failed_count = total_executions - success_count

            return {
                "total_skills": total_skills,
                "categories": categories,
                "total_executions": total_executions,
                "success_count": success_count,
                "failed_count": failed_count,
                "success_rate": round(success_count / total_executions, 4) if total_executions > 0 else 0,
            }


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_skill_executor: SkillExecutor | None = None


def get_skill_executor() -> SkillExecutor:
    """获取技能执行器单例.

    Returns:
        SkillExecutor 全局实例
    """
    global _skill_executor
    if _skill_executor is None:
        _skill_executor = SkillExecutor()
    return _skill_executor
