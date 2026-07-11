"""场景切换管理器.

管理场景的切换、当前状态和切换历史。
支持场景动作钩子机制（on_enter / on_leave），可在场景切换时触发自定义动作。
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from threading import Lock
from typing import Any, Callable

try:
    from src.models import SCENE_DEFINITIONS, DEFAULT_SCENE, SceneSwitchRecord
except ImportError:
    from models import SCENE_DEFINITIONS, DEFAULT_SCENE, SceneSwitchRecord  # type: ignore

try:
    from src.services.mcp_client import get_mcp_client
    _HAS_MCP_CLIENT = True
except ImportError:
    try:
        from services.mcp_client import get_mcp_client  # type: ignore
        _HAS_MCP_CLIENT = True
    except ImportError:
        _HAS_MCP_CLIENT = False

# 技能执行器（延迟导入）
try:
    from src.services.skill_executor import get_skill_executor
    _HAS_SKILL_EXECUTOR = True
except ImportError:
    try:
        from services.skill_executor import get_skill_executor  # type: ignore
        _HAS_SKILL_EXECUTOR = True
    except ImportError:
        _HAS_SKILL_EXECUTOR = False


# ---------------------------------------------------------------------------
# 场景动作钩子类型
# ---------------------------------------------------------------------------
#: on_enter 钩子签名: (scene_id, user_id, context) -> dict[str, Any]
SceneHookFunc = Callable[[str, str, dict[str, Any]], dict[str, Any]]


class SceneSwitchManager:
    """场景切换管理器.

    负责：
    - 维护当前场景状态
    - 执行场景切换
    - 记录切换历史
    - 提供历史查询
    - 场景动作钩子（on_enter / on_leave）
    """

    def __init__(
        self,
        default_scene: str = DEFAULT_SCENE,
        max_history: int = 100,
    ) -> None:
        """初始化场景切换管理器.

        Args:
            default_scene: 默认场景
            max_history: 最大历史记录数
        """
        self._default_scene = default_scene
        self._max_history = max_history

        # 当前场景（按用户ID维护）
        self._current_scenes: dict[str, str] = {}

        # 切换历史（按用户ID维护）
        self._history: dict[str, deque[SceneSwitchRecord]] = {}

        # 切换统计
        self._switch_count: dict[str, int] = {}

        # 线程锁
        self._lock = Lock()

        # 场景动作钩子
        # on_enter 钩子: {scene_id: [hook_func, ...]}
        self._on_enter_hooks: dict[str, list[SceneHookFunc]] = {}
        # on_leave 钩子: {scene_id: [hook_func, ...]}
        self._on_leave_hooks: dict[str, list[SceneHookFunc]] = {}

        # 已执行的 once 动作记录: {(user_id, scene_id, action_type): True}
        self._actions_executed: dict[tuple[str, str, str], bool] = {}

        # 初始化默认场景钩子
        self._init_default_hooks()

    # -----------------------------------------------------------------------
    # 钩子管理
    # -----------------------------------------------------------------------

    def _init_default_hooks(self) -> None:
        """初始化默认场景钩子.

        为 work_dev 场景注册默认的 VS Code 启动钩子。
        同时注册各场景的 MCP 工具调用钩子。
        """
        # work_dev 场景进入时启动 VS Code
        try:
            from src.services.vscode_launcher import get_vscode_launcher
        except ImportError:
            try:
                from services.vscode_launcher import get_vscode_launcher  # type: ignore
            except ImportError:
                return

        def _on_enter_work_dev(
            scene_id: str,
            user_id: str,
            context: dict[str, Any],
        ) -> dict[str, Any]:
            """进入 work_dev 场景时自动启动 VS Code."""
            try:
                launcher = get_vscode_launcher()
                # 检查是否已在运行，避免重复启动
                if not launcher.is_running():
                    project_path = context.get("project_path")
                    result = launcher.launch_vscode(project_path=project_path)
                    return {
                        "action": "launch_vscode",
                        "success": result.get("success", False),
                        "detail": result,
                    }
                else:
                    return {
                        "action": "launch_vscode",
                        "success": True,
                        "detail": {"message": "VS Code 已在运行"},
                    }
            except Exception as e:
                return {
                    "action": "launch_vscode",
                    "success": False,
                    "detail": {"error": str(e)},
                }

        self.register_on_enter("work_dev", _on_enter_work_dev)

        # 注册 MCP 工具调用钩子（为每个有 mcp_tools 配置的场景）
        self._init_mcp_hooks()

    def _init_mcp_hooks(self) -> None:
        """初始化 MCP 工具调用钩子.

        遍历场景定义，为配置了 mcp_tools 的场景注册 on_enter / on_leave 钩子。
        非阻塞工具失败只记录日志，不影响场景切换。
        阻塞工具失败则返回失败标记，由切换逻辑处理。
        """
        if not _HAS_MCP_CLIENT:
            return

        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            mcp_tools = scene_def.get("mcp_tools", [])
            if not mcp_tools:
                continue

            # 按触发时机分组
            on_enter_tools = [t for t in mcp_tools if t.get("trigger") == "on_enter"]
            on_leave_tools = [t for t in mcp_tools if t.get("trigger") == "on_leave"]

            if on_enter_tools:
                self._register_mcp_hook(scene_id, "on_enter", on_enter_tools)

            if on_leave_tools:
                self._register_mcp_hook(scene_id, "on_leave", on_leave_tools)

    def _register_mcp_hook(
        self,
        scene_id: str,
        trigger: str,
        tool_configs: list[dict[str, Any]],
    ) -> None:
        """注册 MCP 工具钩子.

        Args:
            scene_id: 场景ID
            trigger: 触发时机 (on_enter / on_leave)
            tool_configs: 工具配置列表
        """
        def _mcp_hook(
            hook_scene_id: str,
            user_id: str,
            context: dict[str, Any],
        ) -> dict[str, Any]:
            """MCP 工具调用钩子实现."""
            return self._execute_mcp_tools(
                scene_id=hook_scene_id,
                user_id=user_id,
                context=context,
                tool_configs=tool_configs,
                trigger=trigger,
            )

        if trigger == "on_enter":
            self.register_on_enter(scene_id, _mcp_hook)
        elif trigger == "on_leave":
            self.register_on_leave(scene_id, _mcp_hook)

    def _execute_mcp_tools(
        self,
        scene_id: str,
        user_id: str,
        context: dict[str, Any],
        tool_configs: list[dict[str, Any]],
        trigger: str,
    ) -> dict[str, Any]:
        """执行一组 MCP 工具.

        Args:
            scene_id: 场景ID
            user_id: 用户ID
            context: 上下文数据
            tool_configs: 工具配置列表
            trigger: 触发时机

        Returns:
            执行结果字典，包含所有工具的调用结果
        """
        if not _HAS_MCP_CLIENT:
            return {
                "action": "mcp_tools",
                "trigger": trigger,
                "success": True,
                "skipped": True,
                "reason": "MCP 客户端不可用",
                "results": [],
            }

        try:
            mcp_client = get_mcp_client()
        except Exception:
            return {
                "action": "mcp_tools",
                "trigger": trigger,
                "success": True,
                "skipped": True,
                "reason": "MCP 客户端初始化失败",
                "results": [],
            }

        results = []
        has_required_failure = False

        for tool_cfg in tool_configs:
            tool_name = tool_cfg.get("name", "")
            default_params = tool_cfg.get("params", {}) or {}
            required = tool_cfg.get("required", False)

            if not tool_name:
                continue

            # 合并上下文参数和默认参数（上下文参数优先级更高）
            context_tool_params = context.get("mcp_params", {}).get(tool_name, {})
            merged_params = {**default_params, **context_tool_params}

            try:
                call_result = mcp_client.call_tool(
                    tool_name=tool_name,
                    arguments=merged_params,
                )

                tool_result = {
                    "tool_name": tool_name,
                    "trigger": trigger,
                    "required": required,
                    "success": call_result.get("success", False),
                    "result": call_result.get("result", {}),
                    "error": call_result.get("error", ""),
                    "error_code": call_result.get("error_code", ""),
                }

                if not call_result.get("success", False) and required:
                    has_required_failure = True

            except Exception as e:
                tool_result = {
                    "tool_name": tool_name,
                    "trigger": trigger,
                    "required": required,
                    "success": False,
                    "result": {},
                    "error": str(e),
                    "error_code": "MCP_HOOK_EXCEPTION",
                }
                if required:
                    has_required_failure = True

            results.append(tool_result)

        return {
            "action": "mcp_tools",
            "trigger": trigger,
            "success": not has_required_failure,
            "skipped": False,
            "has_required_failure": has_required_failure,
            "results": results,
        }

    def register_on_enter(
        self,
        scene_id: str,
        hook: SceneHookFunc,
    ) -> None:
        """注册场景进入钩子.

        Args:
            scene_id: 场景ID
            hook: 钩子函数 (scene_id, user_id, context) -> dict
        """
        if scene_id not in self._on_enter_hooks:
            self._on_enter_hooks[scene_id] = []
        self._on_enter_hooks[scene_id].append(hook)

    def register_on_leave(
        self,
        scene_id: str,
        hook: SceneHookFunc,
    ) -> None:
        """注册场景离开钩子.

        Args:
            scene_id: 场景ID
            hook: 钩子函数 (scene_id, user_id, context) -> dict
        """
        if scene_id not in self._on_leave_hooks:
            self._on_leave_hooks[scene_id] = []
        self._on_leave_hooks[scene_id].append(hook)

    def unregister_on_enter(
        self,
        scene_id: str,
        hook: SceneHookFunc,
    ) -> bool:
        """注销场景进入钩子.

        Args:
            scene_id: 场景ID
            hook: 要注销的钩子函数

        Returns:
            是否成功注销
        """
        if scene_id in self._on_enter_hooks:
            try:
                self._on_enter_hooks[scene_id].remove(hook)
                return True
            except ValueError:
                pass
        return False

    def unregister_on_leave(
        self,
        scene_id: str,
        hook: SceneHookFunc,
    ) -> bool:
        """注销场景离开钩子.

        Args:
            scene_id: 场景ID
            hook: 要注销的钩子函数

        Returns:
            是否成功注销
        """
        if scene_id in self._on_leave_hooks:
            try:
                self._on_leave_hooks[scene_id].remove(hook)
                return True
            except ValueError:
                pass
        return False

    def _run_hooks(
        self,
        hooks: list[SceneHookFunc],
        scene_id: str,
        user_id: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """执行一组钩子函数.

        Args:
            hooks: 钩子函数列表
            scene_id: 场景ID
            user_id: 用户ID
            context: 上下文数据

        Returns:
            钩子执行结果列表
        """
        results = []
        for hook in hooks:
            try:
                result = hook(scene_id, user_id, context)
                results.append(result if result else {})
            except Exception as e:
                results.append({
                    "success": False,
                    "error": str(e),
                })
        return results

    # -----------------------------------------------------------------------
    # 场景动作链执行
    # -----------------------------------------------------------------------

    def _run_scene_actions(
        self,
        scene_id: str,
        user_id: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """按序执行场景配置的 actions 列表.

        支持：
        - 按顺序执行动作
        - 失败跳过（不阻塞后续动作）
        - once 标记（只在第一次进入时执行）
        - condition 条件判断

        Args:
            scene_id: 场景ID
            user_id: 用户ID
            context: 上下文数据

        Returns:
            动作执行结果列表
        """
        scene_def = SCENE_DEFINITIONS.get(scene_id, {})
        actions = scene_def.get("actions", [])

        if not actions:
            return []

        # 获取 VS Code 启动器（延迟导入避免循环依赖）
        launcher = None
        try:
            try:
                from src.services.vscode_launcher import get_vscode_launcher
            except ImportError:
                from services.vscode_launcher import get_vscode_launcher  # type: ignore
            launcher = get_vscode_launcher()
        except Exception:
            pass

        results: list[dict[str, Any]] = []

        for action in actions:
            action_type = action.get("type", "")
            params = action.get("params", {}) or {}
            condition = action.get("condition", "")
            once = action.get("once", False)

            # once 标记检查
            if once:
                action_key = (user_id, scene_id, action_type)
                if self._actions_executed.get(action_key, False):
                    results.append({
                        "type": action_type,
                        "success": True,
                        "skipped": True,
                        "reason": "once 动作已执行过，跳过",
                        "params": params,
                    })
                    continue

            # 条件判断
            if not self._check_action_condition(
                action_type, condition, context, launcher
            ):
                results.append({
                    "type": action_type,
                    "success": True,
                    "skipped": True,
                    "reason": f"条件不满足: {condition}",
                    "params": params,
                })
                continue

            # 执行动作
            try:
                result = self._execute_single_action(
                    action_type, params, context, launcher
                )
                result["type"] = action_type
                result["params"] = params
                result["skipped"] = False

                # 标记 once 动作已执行
                if once and result.get("success", False):
                    action_key = (user_id, scene_id, action_type)
                    self._actions_executed[action_key] = True

                results.append(result)

            except Exception as e:
                # 失败跳过，不阻塞后续动作
                results.append({
                    "type": action_type,
                    "success": False,
                    "skipped": False,
                    "error": str(e),
                    "params": params,
                })

        return results

    def _check_action_condition(
        self,
        action_type: str,
        condition: str,
        context: dict[str, Any],
        launcher: Any,
    ) -> bool:
        """检查动作触发条件是否满足.

        Args:
            action_type: 动作类型
            condition: 条件字符串
            context: 上下文数据
            launcher: VS Code 启动器实例

        Returns:
            True 表示条件满足，False 表示不满足
        """
        if not condition:
            return True

        if condition == "not_running":
            # VS Code 未运行时才执行
            if launcher:
                return not launcher.is_running()
            return True

        if condition == "has_project_path":
            # 上下文中有项目路径才执行
            project_path = context.get("project_path", "")
            return bool(project_path)

        if condition == "first_enter":
            # 第一次进入时执行（配合 once 使用，这里直接返回 True，
            # once 逻辑在外层处理）
            return True

        # 未知条件默认满足
        return True

    def _execute_single_action(
        self,
        action_type: str,
        params: dict[str, Any],
        context: dict[str, Any],
        launcher: Any,
    ) -> dict[str, Any]:
        """执行单个场景动作.

        Args:
            action_type: 动作类型
            params: 动作参数
            context: 上下文数据
            launcher: VS Code 启动器实例

        Returns:
            动作执行结果字典
        """
        if not launcher:
            return {
                "success": False,
                "message": "VS Code 启动器不可用",
            }

        if action_type == "launch_vscode":
            # 启动 VS Code
            project_path = context.get("project_path") or params.get("project_path")
            new_window = params.get("new_window", True)
            result = launcher.launch_vscode(
                project_path=project_path if project_path else None,
                new_window=new_window,
            )
            return {
                "success": result.get("success", False),
                "message": result.get("message", ""),
                "detail": result,
            }

        elif action_type == "open_project":
            # 打开项目
            project_path = context.get("project_path") or params.get("project_path", "")
            new_window = params.get("new_window", True)
            if not project_path:
                return {
                    "success": False,
                    "message": "项目路径为空，无法打开",
                }
            result = launcher.launch_vscode(
                project_path=project_path,
                new_window=new_window,
            )
            return {
                "success": result.get("success", False),
                "message": result.get("message", ""),
                "detail": result,
            }

        elif action_type == "open_file":
            # 打开文件
            file_path = params.get("file_path", "")
            line = params.get("line")
            if not file_path:
                return {
                    "success": False,
                    "message": "文件路径为空，无法打开",
                }
            result = launcher.open_file(file_path, line=line)
            return {
                "success": result.get("success", False),
                "message": result.get("message", ""),
                "detail": result.get("data", {}),
            }

        elif action_type == "install_extension":
            # 安装扩展（支持批量）
            extensions = params.get("extensions", [])
            if isinstance(extensions, str):
                extensions = [extensions]

            if not extensions:
                return {
                    "success": False,
                    "message": "扩展列表为空",
                }

            install_results = []
            all_success = True
            for ext_id in extensions:
                result = launcher.install_extension(ext_id)
                install_results.append(result)
                if not result.get("success", False):
                    all_success = False

            return {
                "success": all_success,
                "message": f"已安装 {len(extensions)} 个扩展" if all_success else "部分扩展安装失败",
                "detail": install_results,
                "extensions_count": len(extensions),
            }

        elif action_type == "run_command":
            # 执行命令
            command = params.get("command", "")
            cwd = params.get("cwd") or context.get("project_path")
            if not command:
                return {
                    "success": False,
                    "message": "命令为空，无法执行",
                }
            result = launcher.run_command(command, cwd=cwd)
            return {
                "success": result.get("success", False),
                "message": result.get("message", ""),
                "detail": result.get("data", {}),
            }

        else:
            return {
                "success": False,
                "message": f"未知的动作类型: {action_type}",
            }

    def _extract_mcp_results(
        self,
        hook_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """从钩子结果中提取 MCP 工具调用结果.

        Args:
            hook_results: 钩子执行结果列表

        Returns:
            MCP 工具调用结果列表（扁平化）
        """
        mcp_results = []
        for result in hook_results:
            if result.get("action") == "mcp_tools" and "results" in result:
                mcp_results.extend(result["results"])
        return mcp_results

    def _has_required_mcp_failure(
        self,
        mcp_results: list[dict[str, Any]],
    ) -> bool:
        """检查 MCP 结果中是否有阻塞级别工具调用失败.

        Args:
            mcp_results: MCP 工具调用结果列表

        Returns:
            True 表示有阻塞工具失败，False 表示没有
        """
        for result in mcp_results:
            if result.get("required", False) and not result.get("success", False):
                return True
        return False

    # -----------------------------------------------------------------------
    # 场景技能自动执行
    # -----------------------------------------------------------------------

    def _execute_scene_skills(
        self,
        scene_id: str,
        trigger: str,
        user_id: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """执行场景绑定的技能（按触发时机）.

        遍历场景的 skills 配置，找出匹配当前触发时机的技能并执行。
        非 required 技能失败不阻塞，仅记录结果。

        Args:
            scene_id: 场景ID
            trigger: 触发时机 (on_enter / on_leave)
            user_id: 用户ID
            context: 上下文数据

        Returns:
            技能执行结果列表
        """
        if not _HAS_SKILL_EXECUTOR:
            return []

        scene_def = SCENE_DEFINITIONS.get(scene_id, {})
        skill_bindings = scene_def.get("skills", [])

        if not skill_bindings:
            return []

        # 筛选匹配触发时机的技能
        target_skills = [
            s for s in skill_bindings
            if trigger in s.get("auto_trigger", [])
        ]

        if not target_skills:
            return []

        # 获取技能执行器
        try:
            skill_executor = get_skill_executor()
        except Exception:
            return []

        # 构建执行上下文
        exec_context = {
            **context,
            "user_id": user_id,
            "scene_id": scene_id,
            "trigger": trigger,
        }

        results = []
        for binding in target_skills:
            skill_name = binding.get("name", "")
            default_params = binding.get("default_params", {}) or {}
            required = binding.get("required", False)

            if not skill_name:
                continue

            # 合并上下文参数和默认参数（上下文参数优先级更高）
            context_skill_params = context.get("skill_params", {}).get(skill_name, {})
            merged_params = {**default_params, **context_skill_params}

            try:
                result = skill_executor.execute_skill(
                    skill_name=skill_name,
                    params=merged_params,
                    context=exec_context,
                )
                result["trigger"] = trigger
                result["required"] = required
                results.append(result)

            except Exception as e:
                results.append({
                    "skill_name": skill_name,
                    "trigger": trigger,
                    "required": required,
                    "success": False,
                    "message": f"技能执行异常: {e}",
                    "data": {},
                    "error": str(e),
                    "error_code": "SKILL_AUTO_TRIGGER_ERROR",
                })

        return results

    def _has_required_skill_failure(
        self,
        skill_results: list[dict[str, Any]],
    ) -> bool:
        """检查技能执行结果中是否有阻塞级别的失败.

        Args:
            skill_results: 技能执行结果列表

        Returns:
            True 表示有 required 技能失败
        """
        for result in skill_results:
            if result.get("required", False) and not result.get("success", False):
                return True
        return False

    # -----------------------------------------------------------------------
    # 场景切换
    # -----------------------------------------------------------------------

    def get_current_scene(self, user_id: str = "default") -> str:
        """获取当前场景.

        Args:
            user_id: 用户ID

        Returns:
            当前场景ID
        """
        with self._lock:
            return self._current_scenes.get(user_id, self._default_scene)

    def switch_scene(
        self,
        to_scene: str,
        from_scene: str = "",
        trigger_type: str = "manual",
        user_id: str = "default",
        reason: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """切换场景.

        Args:
            to_scene: 目标场景ID
            from_scene: 源场景ID，为空则使用当前场景
            trigger_type: 触发类型 manual/auto/recognize
            user_id: 用户ID
            reason: 切换原因
            context: 切换上下文（传递给钩子函数）

        Returns:
            切换结果字典
        """
        # 验证目标场景
        if to_scene not in SCENE_DEFINITIONS and to_scene != "unknown":
            return {
                "success": False,
                "from_scene": from_scene or self.get_current_scene(user_id),
                "to_scene": to_scene,
                "reason": f"无效的场景ID: {to_scene}",
            }

        hook_context = context or {}
        enter_hook_results: list[dict[str, Any]] = []
        leave_hook_results: list[dict[str, Any]] = []
        actions_result: list[dict[str, Any]] = []
        mcp_results: dict[str, Any] = {
            "on_enter": [],
            "on_leave": [],
        }
        skills_result: dict[str, Any] = {
            "on_enter": [],
            "on_leave": [],
        }

        with self._lock:
            current = self._current_scenes.get(user_id, self._default_scene)
            actual_from = from_scene or current

            # 相同场景不切换
            if actual_from == to_scene and to_scene != "unknown":
                return {
                    "success": True,
                    "from_scene": actual_from,
                    "to_scene": to_scene,
                    "switched": False,
                    "reason": "已在目标场景",
                    "mcp_results": mcp_results,
                    "actions_result": actions_result,
                    "skills_result": skills_result,
                }

            # 执行 on_leave 钩子（源场景）
            if actual_from in self._on_leave_hooks:
                leave_hook_results = self._run_hooks(
                    self._on_leave_hooks[actual_from],
                    actual_from,
                    user_id,
                    hook_context,
                )
                # 提取 MCP 工具结果
                mcp_results["on_leave"] = self._extract_mcp_results(
                    leave_hook_results
                )

                # 检查是否有阻塞级别的 MCP 工具失败
                if self._has_required_mcp_failure(mcp_results["on_leave"]):
                    return {
                        "success": False,
                        "from_scene": actual_from,
                        "to_scene": to_scene,
                        "switched": False,
                        "reason": "on_leave MCP 阻塞工具调用失败，场景切换已中止",
                        "mcp_results": mcp_results,
                        "enter_hook_results": [],
                        "leave_hook_results": leave_hook_results,
                        "actions_result": actions_result,
                        "skills_result": skills_result,
                    }

            # 执行 on_leave 技能（源场景）
            skills_result["on_leave"] = self._execute_scene_skills(
                scene_id=actual_from,
                trigger="on_leave",
                user_id=user_id,
                context=hook_context,
            )

            # 检查是否有阻塞级别的技能失败
            if self._has_required_skill_failure(skills_result["on_leave"]):
                return {
                    "success": False,
                    "from_scene": actual_from,
                    "to_scene": to_scene,
                    "switched": False,
                    "reason": "on_leave 阻塞技能执行失败，场景切换已中止",
                    "mcp_results": mcp_results,
                    "enter_hook_results": [],
                    "leave_hook_results": leave_hook_results,
                    "actions_result": actions_result,
                    "skills_result": skills_result,
                }

            # 执行切换
            if to_scene != "unknown":
                self._current_scenes[user_id] = to_scene

            # 执行 on_enter 钩子（目标场景）
            if to_scene in self._on_enter_hooks:
                enter_hook_results = self._run_hooks(
                    self._on_enter_hooks[to_scene],
                    to_scene,
                    user_id,
                    hook_context,
                )
                # 提取 MCP 工具结果
                mcp_results["on_enter"] = self._extract_mcp_results(
                    enter_hook_results
                )

                # 检查是否有阻塞级别的 MCP 工具失败
                if self._has_required_mcp_failure(mcp_results["on_enter"]):
                    # 回滚场景切换
                    self._current_scenes[user_id] = actual_from
                    return {
                        "success": False,
                        "from_scene": actual_from,
                        "to_scene": to_scene,
                        "switched": False,
                        "reason": "on_enter MCP 阻塞工具调用失败，场景切换已回滚",
                        "mcp_results": mcp_results,
                        "enter_hook_results": enter_hook_results,
                        "leave_hook_results": leave_hook_results,
                        "actions_result": actions_result,
                        "skills_result": skills_result,
                    }

            # 执行 on_enter 技能（目标场景）
            skills_result["on_enter"] = self._execute_scene_skills(
                scene_id=to_scene,
                trigger="on_enter",
                user_id=user_id,
                context=hook_context,
            )

            # 检查是否有阻塞级别的技能失败
            if self._has_required_skill_failure(skills_result["on_enter"]):
                # 回滚场景切换
                self._current_scenes[user_id] = actual_from
                return {
                    "success": False,
                    "from_scene": actual_from,
                    "to_scene": to_scene,
                    "switched": False,
                    "reason": "on_enter 阻塞技能执行失败，场景切换已回滚",
                    "mcp_results": mcp_results,
                    "enter_hook_results": enter_hook_results,
                    "leave_hook_results": leave_hook_results,
                    "actions_result": actions_result,
                    "skills_result": skills_result,
                }

            # 执行场景动作链（on_enter 时触发）
            actions_result = self._run_scene_actions(
                to_scene, user_id, hook_context
            )

            # 记录历史
            record = SceneSwitchRecord(
                id=uuid.uuid4().hex[:12],
                from_scene=actual_from,
                to_scene=to_scene,
                trigger_type=trigger_type,
                user_id=user_id,
                timestamp=time.time(),
                reason=reason,
            )

            if user_id not in self._history:
                self._history[user_id] = deque(maxlen=self._max_history)
            self._history[user_id].append(record)

            # 更新统计
            self._switch_count[user_id] = self._switch_count.get(user_id, 0) + 1

            return {
                "success": True,
                "from_scene": actual_from,
                "to_scene": to_scene,
                "switched": True,
                "record_id": record.id,
                "timestamp": record.timestamp,
                "trigger_type": trigger_type,
                "reason": reason,
                "enter_hook_results": enter_hook_results,
                "leave_hook_results": leave_hook_results,
                "mcp_results": mcp_results,
                "actions_result": actions_result,
                "skills_result": skills_result,
            }

    # -----------------------------------------------------------------------
    # 历史与状态查询
    # -----------------------------------------------------------------------

    def get_history(
        self,
        user_id: str = "default",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """获取切换历史.

        Args:
            user_id: 用户ID
            limit: 返回条数
            offset: 偏移量

        Returns:
            历史记录字典
        """
        with self._lock:
            history = self._history.get(user_id, deque())
            records = list(history)
            total = len(records)

            # 按时间倒序
            records.reverse()

            # 分页
            end = min(offset + limit, total)
            page_records = records[offset:end]

            result_records = [
                {
                    "id": r.id,
                    "from_scene": r.from_scene,
                    "to_scene": r.to_scene,
                    "trigger_type": r.trigger_type,
                    "user_id": r.user_id,
                    "timestamp": r.timestamp,
                    "reason": r.reason,
                }
                for r in page_records
            ]

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "records": result_records,
            }

    def get_switch_count(self, user_id: str = "default") -> int:
        """获取切换次数."""
        with self._lock:
            return self._switch_count.get(user_id, 0)

    def get_all_users(self) -> list[str]:
        """获取所有有记录的用户ID."""
        with self._lock:
            return list(self._current_scenes.keys())

    def get_all_scene_status(self) -> dict[str, Any]:
        """获取所有用户的场景状态."""
        with self._lock:
            result = {}
            for user_id, scene_id in self._current_scenes.items():
                scene_info = SCENE_DEFINITIONS.get(scene_id, {})
                result[user_id] = {
                    "scene_id": scene_id,
                    "scene_name": scene_info.get("name", scene_id),
                    "switch_count": self._switch_count.get(user_id, 0),
                }
            return result

    def reset_user(self, user_id: str = "default") -> None:
        """重置用户场景状态."""
        with self._lock:
            self._current_scenes[user_id] = self._default_scene
            if user_id in self._history:
                self._history[user_id].clear()
            self._switch_count[user_id] = 0
