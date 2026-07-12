"""统一钩子系统 - Hook Manager.

【P0-3 修复】统一中间件、事件总线、插件系统三套机制的钩子注册 API。

设计原则：
  - 统一注册：所有扩展点通过 HookManager 统一管理
  - 优先级支持：数字越小优先级越高
  - 短路返回：钩子可以直接返回结果终止后续执行
  - 与现有系统打通：中间件自动触发 before/after 钩子，事件总线可通过钩子订阅

支持的钩子点：
  - before_invoke     - 调用前
  - after_invoke      - 调用后
  - on_error          - 错误时
  - before_register   - 技能注册前
  - after_register    - 技能注册后
  - before_unregister - 技能卸载前
  - system_startup    - 系统启动
  - system_shutdown   - 系统关闭
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# 钩子函数签名：(context) -> result | None
# 返回非 None 值表示短路，终止后续钩子执行
HookHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class HookRegistration(BaseModel):
    """钩子注册信息."""

    hook_name: str = Field(..., description="钩子点名称")
    handler: Callable[[dict[str, Any]], Awaitable[Any]]
    priority: int = Field(default=100, description="优先级，数字越小优先级越高")
    description: str = Field(default="", description="钩子描述")

    model_config = {"arbitrary_types_allowed": True}


class HookManager:
    """统一钩子管理器.

    管理所有钩子点的注册与执行，支持优先级排序和短路返回。

    使用方式：
        hooks = HookManager()

        # 注册钩子
        @hooks.on("before_invoke", priority=10)
        async def my_hook(ctx):
            print("before invoke", ctx["request"])

        # 或使用 register 方法
        hooks.register("after_invoke", my_after_hook, priority=20)

        # 触发钩子
        result = await hooks.trigger("before_invoke", {"request": req})
        if result is not None:
            # 短路：有钩子直接返回了结果
            return result
    """

    # 预定义的钩子点常量
    BEFORE_INVOKE = "before_invoke"
    AFTER_INVOKE = "after_invoke"
    ON_ERROR = "on_error"
    BEFORE_REGISTER = "before_register"
    AFTER_REGISTER = "after_register"
    BEFORE_UNREGISTER = "before_unregister"
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"

    # 所有合法钩子点
    VALID_HOOKS = frozenset({
        BEFORE_INVOKE,
        AFTER_INVOKE,
        ON_ERROR,
        BEFORE_REGISTER,
        AFTER_REGISTER,
        BEFORE_UNREGISTER,
        SYSTEM_STARTUP,
        SYSTEM_SHUTDOWN,
    })

    def __init__(self) -> None:
        # 每个钩子点对应一个按优先级排序的注册列表
        self._hooks: dict[str, list[HookRegistration]] = {
            name: [] for name in self.VALID_HOOKS
        }
        self._lock = asyncio.Lock()
        self._logger = logger.bind(component="hook_manager")

    def register(
        self,
        hook_name: str,
        handler: HookHandler,
        priority: int = 100,
        description: str = "",
    ) -> HookRegistration:
        """注册钩子.

        Args:
            hook_name: 钩子点名称（必须在 VALID_HOOKS 中）.
            handler: 异步钩子处理函数，接收 context 字典.
            priority: 优先级，数字越小优先级越高，默认 100.
            description: 钩子描述.

        Returns:
            HookRegistration 注册信息对象.

        Raises:
            ValueError: 钩子点名称不合法.
        """
        if hook_name not in self.VALID_HOOKS:
            raise ValueError(
                f"Invalid hook name: {hook_name}. "
                f"Valid hooks: {sorted(self.VALID_HOOKS)}"
            )

        registration = HookRegistration(
            hook_name=hook_name,
            handler=handler,
            priority=priority,
            description=description,
        )

        # 插入到正确的优先级位置（保持列表有序）
        hooks_list = self._hooks[hook_name]
        # 找到第一个 priority > 当前 priority 的位置插入
        insert_idx = len(hooks_list)
        for i, reg in enumerate(hooks_list):
            if reg.priority > priority:
                insert_idx = i
                break
        hooks_list.insert(insert_idx, registration)

        self._logger.info(
            "hook_registered",
            hook_name=hook_name,
            priority=priority,
            description=description,
            total=len(hooks_list),
        )

        return registration

    def unregister(self, registration: HookRegistration) -> bool:
        """取消钩子注册.

        Args:
            registration: 注册信息对象.

        Returns:
            是否成功移除.
        """
        hook_name = registration.hook_name
        if hook_name not in self._hooks:
            return False
        try:
            self._hooks[hook_name].remove(registration)
            self._logger.info(
                "hook_unregistered",
                hook_name=hook_name,
                remaining=len(self._hooks[hook_name]),
            )
            return True
        except ValueError:
            return False

    def on(
        self,
        hook_name: str,
        priority: int = 100,
        description: str = "",
    ) -> Callable[[HookHandler], HookHandler]:
        """装饰器方式注册钩子.

        使用方式：
            @hooks.on("before_invoke", priority=10)
            async def my_hook(ctx):
                ...
        """
        def decorator(handler: HookHandler) -> HookHandler:
            self.register(hook_name, handler, priority, description)
            return handler
        return decorator

    async def trigger(
        self,
        hook_name: str,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """触发钩子，按优先级顺序执行所有注册的处理器.

        如果某个处理器返回非 None 值，则短路并返回该值，
        后续处理器不再执行。

        Args:
            hook_name: 钩子点名称.
            context: 上下文字典，传递给所有处理器.

        Returns:
            短路返回值，或 None 表示所有钩子正常执行完毕.
        """
        if hook_name not in self._hooks:
            self._logger.warning(
                "hook_trigger_invalid",
                hook_name=hook_name,
            )
            return None

        hooks_list = self._hooks[hook_name]
        if not hooks_list:
            return None

        ctx = context or {}
        self._logger.debug(
            "hook_trigger_start",
            hook_name=hook_name,
            handlers=len(hooks_list),
        )

        for reg in hooks_list:
            try:
                result = await reg.handler(ctx)
                if result is not None:
                    self._logger.debug(
                        "hook_short_circuit",
                        hook_name=hook_name,
                        description=reg.description,
                        priority=reg.priority,
                    )
                    return result
            except Exception as e:
                self._logger.error(
                    "hook_handler_error",
                    hook_name=hook_name,
                    handler=reg.description or str(reg.handler),
                    error=str(e),
                )
                # 单个钩子出错不影响其他钩子，继续执行

        return None

    def get_hooks(self, hook_name: str) -> list[HookRegistration]:
        """获取指定钩子点的所有注册（按优先级排序）."""
        return list(self._hooks.get(hook_name, []))

    def clear(self, hook_name: str | None = None) -> None:
        """清空钩子.

        Args:
            hook_name: 指定钩子点，None 表示清空所有.
        """
        if hook_name is None:
            for name in self._hooks:
                self._hooks[name] = []
            self._logger.info("hook_all_cleared")
        elif hook_name in self._hooks:
            self._hooks[hook_name] = []
            self._logger.info("hook_cleared", hook_name=hook_name)

    # ── 与中间件系统打通 ──────────────────────────────────

    def create_middleware(self) -> Callable[
        [Any, str, Callable[[], Awaitable[Any]]],
        Awaitable[Any],
    ]:
        """创建一个中间件，自动在调用前后触发 before_invoke / after_invoke 钩子.

        此中间件可直接注册到 MiddlewarePipeline 中，
        使得 HookManager 注册的钩子能在技能调用链中生效。

        Returns:
            中间件函数.
        """
        async def _hook_middleware(
            request: Any,
            agent_id: str,
            next_handler: Callable[[], Awaitable[Any]],
        ) -> Any:
            # 触发 before_invoke 钩子（可短路）
            before_ctx = {"request": request, "agent_id": agent_id}
            short_circuit = await self.trigger(self.BEFORE_INVOKE, before_ctx)
            if short_circuit is not None:
                return short_circuit

            try:
                result = await next_handler()
            except Exception as e:
                # 触发 on_error 钩子
                error_ctx = {
                    "request": request,
                    "agent_id": agent_id,
                    "error": e,
                }
                error_result = await self.trigger(self.ON_ERROR, error_ctx)
                if error_result is not None:
                    return error_result
                raise

            # 触发 after_invoke 钩子
            after_ctx = {
                "request": request,
                "agent_id": agent_id,
                "result": result,
            }
            after_result = await self.trigger(self.AFTER_INVOKE, after_ctx)
            if after_result is not None:
                return after_result

            return result

        return _hook_middleware

    # ── 与事件总线打通 ────────────────────────────────────

    def subscribe_event(
        self,
        event_bus: Any,
        event_pattern: str,
        hook_name: str,
        priority: int = 100,
    ) -> None:
        """订阅事件总线的事件，事件触发时自动触发指定钩子.

        将事件总线的事件系统与钩子系统打通，
        使得事件可以通过钩子 API 订阅和处理。

        Args:
            event_bus: EventBus 实例.
            event_pattern: 事件模式（支持通配符）.
            hook_name: 触发的钩子点名称.
            priority: 钩子优先级.
        """
        async def _event_to_hook(event_dict: dict[str, Any]) -> None:
            ctx = {"event": event_dict, "event_pattern": event_pattern}
            await self.trigger(hook_name, ctx)

        self.register(
            hook_name,
            _event_to_hook,
            priority=priority,
            description=f"event_bridge:{event_pattern}",
        )

        # 订阅事件总线
        asyncio.create_task(event_bus.subscribe(event_pattern, _event_to_hook))

        self._logger.info(
            "hook_event_bridge_created",
            event_pattern=event_pattern,
            hook_name=hook_name,
        )

    def list_all_hooks(self) -> dict[str, list[dict[str, Any]]]:
        """列出所有钩子注册信息（调试用）."""
        result: dict[str, list[dict[str, Any]]] = {}
        for name, regs in self._hooks.items():
            result[name] = [
                {
                    "priority": r.priority,
                    "description": r.description,
                }
                for r in regs
            ]
        return result
