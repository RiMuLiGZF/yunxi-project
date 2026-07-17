"""
模块管家 Agent 适配器 — ModuleManagerAgentAdapter

M8 总管 — 云汐八大模块的统一管控中心，负责监控、配置、升级、测试。

核心能力：
  - 健康监控：一键检查所有模块或指定模块的健康状态
  - 性能指标：获取各模块的 CPU、内存、QPS 等运行指标
  - 配置管理：读取和更新各模块的运行配置
  - 升级管理：升级预览、应用升级、版本回滚
  - 测试管理：远程触发各模块的自动化测试

身份设定：云汐总管 — 严谨、高效、全局视野

使用示例：
    adapter = ModuleManagerAgentAdapter(
        agent_id="module_manager_01",
        display_name="云汐总管",
        config={
            "module_addresses": {
                "m1": "http://localhost:8001",
                "m2": "http://localhost:8002",
                # ...
            },
            "m8_token": "your-admin-token",
        },
    )

    # 检查所有模块健康状态
    result = await adapter.invoke("检查所有模块的健康状态")

    # 获取 M1 模块的性能指标
    result = await adapter.invoke("获取 M1 模块的性能指标")
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from src.federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class ModuleManagerAgentAdapter(AgentAdapterBase):
    """模块管家 Agent — 云汐八大模块的统一管控中心

    基于 M8 标准接口，对云汐八大模块进行统一管理：
      1. 健康监控：health 接口
      2. 性能指标：metrics 接口
      3. 配置管理：config / config/update 接口
      4. 升级管理：upgrade/preview / upgrade/apply / upgrade/rollback 接口
      5. 测试管理：test/run / test/result 接口
    """

    provider: str = "ModuleManager"
    adapter_type: str = "module_manager_agent"

    # ── 系统提示词 ───────────────────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「云汐总管」，云汐系统八大模块的统一管控中心。

## 你的身份

你是云汐系统的 M8 总管，拥有全局视野，负责所有模块的监控、配置、升级和测试。
你性格严谨、高效、条理清晰，对系统稳定性有极高的责任感。

## 你的职责

1. **健康监控**：实时掌握各模块运行状态，快速定位异常
2. **性能管理**：监控 CPU、内存、QPS 等关键指标，保障系统性能
3. **配置管控**：统一管理各模块配置，确保配置一致性
4. **版本升级**：负责模块的升级预览、执行和回滚，降低升级风险
5. **测试验证**：远程触发自动化测试，确保模块质量

## 管辖的八大模块

- M1：多 Agent 集群调度（调度中心）
- M2：智能对话与交互（交互层）
- M3：知识图谱与推理（知识层）
- M4：代码生成与工程（工程层）
- M5：潮汐记忆系统（记忆层）
- M6：创意与内容生成（创作层）
- M7：安全与隐私防护（安全层）
- M8：总管与运维平台（管控层，即你所在的模块）

## 工作原则

- 严谨准确：所有操作都要有明确的依据和验证
- 全局视角：从整体系统角度分析问题，不局限于单个模块
- 风险控制：升级、配置变更等操作必须先预览，确认无误再执行
- 快速响应：健康异常要第一时间报告并给出处置建议
- 数据驱动：用指标和数据说话，不做主观臆断

## 输出风格

- 用中文回答，专业、简洁、条理分明
- 状态信息用表格或结构化列表呈现
- 异常项用醒目标记标注
- 涉及多模块对比时，统一格式便于横向比较
- 给出结论和建议时，要基于数据支撑
"""

    # ── 模块元信息 ───────────────────────────────────────────────────────

    _MODULE_INFO: dict[str, dict[str, str]] = {
        "m1": {"name": "多Agent集群调度", "role": "调度中心", "default_port": 8001},
        "m2": {"name": "智能对话与交互", "role": "交互层", "default_port": 8002},
        "m3": {"name": "知识图谱与推理", "role": "知识层", "default_port": 8003},
        "m4": {"name": "代码生成与工程", "role": "工程层", "default_port": 8004},
        "m5": {"name": "潮汐记忆系统", "role": "记忆层", "default_port": 8005},
        "m6": {"name": "创意与内容生成", "role": "创作层", "default_port": 8006},
        "m7": {"name": "安全与隐私防护", "role": "安全层", "default_port": 8007},
        "m8": {"name": "总管与运维平台", "role": "管控层", "default_port": 8008},
    }

    # ── 支持的命令类型 ───────────────────────────────────────────────────

    _COMMAND_TYPES = [
        "health_check",   # 健康检查
        "get_metrics",    # 获取性能指标
        "get_config",     # 获取配置
        "update_config",  # 更新配置
        "upgrade_preview",  # 升级预览
        "upgrade_apply",    # 执行升级
        "upgrade_rollback", # 回滚
        "run_test",       # 运行测试
    ]

    def __init__(
        self,
        agent_id: str = "module_manager_01",
        display_name: str = "云汐总管",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化模块管家 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - module_addresses: 各模块地址映射（m1~m8）
                - m8_token: M8 管理令牌（用于鉴权接口）
                - default_base_url: 默认基础地址前缀（默认 http://localhost）
                - request_timeout: 单次请求超时时间（秒，默认 10.0）
                - parallel_limit: 并行请求上限（默认 4）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 构建默认模块地址映射
        default_addresses = {}
        base = config.get("default_base_url", "http://localhost")
        for mid, info in self._MODULE_INFO.items():
            default_addresses[mid] = f"{base}:{info['default_port']}"

        # 合并用户配置的模块地址
        module_addresses = config.get("module_addresses", {})
        merged_addresses = {**default_addresses, **module_addresses}
        config["module_addresses"] = merged_addresses

        config.setdefault("m8_token", "")
        config.setdefault("request_timeout", 10.0)
        config.setdefault("parallel_limit", 4)

        # 管理类操作零成本（内部运维）
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "CNY",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None

        self._logger = self._logger.bind(
            module_count=len(merged_addresses),
            modules=list(merged_addresses.keys()),
        )

    # ── 公开接口实现 ────────────────────────────────────────────────────

    async def _invoke_impl(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """执行模块管理任务

        根据用户意图自动判断命令类型和目标模块，调用对应的 M8 标准接口。
        """
        await self._ensure_http_client()

        # 解析命令类型和目标模块
        command_info = self._parse_command(prompt, metadata)
        command_type = command_info["command_type"]
        target_modules = command_info["target_modules"]
        extra_params = command_info["params"]

        self._logger.info(
            "module_manager_command",
            command_type=command_type,
            target_modules=target_modules,
            prompt_length=len(prompt),
        )

        total_input_tokens = len(prompt) // 4
        total_output_tokens = 0

        # 执行对应命令
        if command_type == "health_check":
            output_text = await self._cmd_health_check(target_modules)
        elif command_type == "get_metrics":
            output_text = await self._cmd_get_metrics(target_modules)
        elif command_type == "get_config":
            output_text = await self._cmd_get_config(target_modules)
        elif command_type == "update_config":
            output_text = await self._cmd_update_config(
                target_modules, extra_params
            )
        elif command_type == "upgrade_preview":
            output_text = await self._cmd_upgrade_preview(
                target_modules, extra_params
            )
        elif command_type == "upgrade_apply":
            output_text = await self._cmd_upgrade_apply(
                target_modules, extra_params
            )
        elif command_type == "upgrade_rollback":
            output_text = await self._cmd_upgrade_rollback(
                target_modules, extra_params
            )
        elif command_type == "run_test":
            output_text = await self._cmd_run_test(
                target_modules, extra_params
            )
        else:
            output_text = self._format_help()

        total_output_tokens = len(output_text) // 4

        return {
            "output": output_text,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "command_type": command_type,
            "target_modules": target_modules,
            "tools_used": [{"tool": f"m8_{command_type}", "type": command_type}],
            "local": True,
            "manager_system": "module_manager_v1.0",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查模块管家自身及所有已配置模块的连通性。
        """
        await self._ensure_http_client()
        assert self._http_client is not None

        health_issues: list[str] = []
        module_addresses = self._config["module_addresses"]
        reachable = 0
        total = len(module_addresses)

        for module_id, base_url in module_addresses.items():
            try:
                url = base_url.rstrip("/") + "/health"
                response = await self._http_client.get(
                    url,
                    timeout=3.0,
                )
                if response.status_code == 200:
                    reachable += 1
                else:
                    info = self._MODULE_INFO.get(module_id, {})
                    name = info.get("name", module_id)
                    health_issues.append(f"{name}({module_id}): HTTP {response.status_code}")
            except httpx.ConnectError:
                info = self._MODULE_INFO.get(module_id, {})
                name = info.get("name", module_id)
                health_issues.append(f"{name}({module_id}): 不可达")
            except Exception:
                pass  # 快速检查，忽略超时等其他异常

        if health_issues:
            return {
                "healthy": reachable > 0,
                "message": (
                    f"模块管家运行中，已配置 {total} 个模块，"
                    f"可达 {reachable} 个，异常 {len(health_issues)} 个："
                    + "; ".join(health_issues[:5])
                ),
            }

        return {
            "healthy": True,
            "message": (
                f"云汐总管运行正常，已配置 {total} 个模块，全部可达"
            ),
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（内部管理免费）"""
        return 0.0

    # ── 命令解析 ────────────────────────────────────────────────────────

    def _parse_command(
        self, prompt: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """解析用户命令，确定命令类型和目标模块

        Returns:
            {
                "command_type": str,
                "target_modules": list[str],
                "params": dict,
            }
        """
        prompt_lower = prompt.lower()

        # 优先从 metadata 中获取明确的命令类型
        if metadata.get("command_type") in self._COMMAND_TYPES:
            command_type = metadata["command_type"]
        else:
            # 关键词匹配
            command_type = self._match_command_type(prompt_lower)

        # 解析目标模块
        target_modules = self._extract_target_modules(prompt_lower, metadata)

        # 提取额外参数
        params = self._extract_params(prompt, metadata, command_type)

        return {
            "command_type": command_type,
            "target_modules": target_modules,
            "params": params,
        }

    def _match_command_type(self, prompt_lower: str) -> str:
        """通过关键词匹配命令类型"""
        # 健康检查
        health_keywords = ["健康", "状态", "检查", "health", "存活", "在线"]
        if any(kw in prompt_lower for kw in health_keywords):
            return "health_check"

        # 性能指标
        metrics_keywords = ["指标", "性能", "metrics", "cpu", "内存", "负载", "qps", "延迟"]
        if any(kw in prompt_lower for kw in metrics_keywords):
            return "get_metrics"

        # 更新配置
        update_config_keywords = ["更新配置", "修改配置", "设置配置", "改配置", "update config"]
        if any(kw in prompt_lower for kw in update_config_keywords):
            return "update_config"

        # 获取配置
        config_keywords = ["配置", "config", "参数设置"]
        if any(kw in prompt_lower for kw in config_keywords):
            return "get_config"

        # 升级预览
        preview_keywords = ["升级预览", "预览升级", "检查升级", "upgrade preview"]
        if any(kw in prompt_lower for kw in preview_keywords):
            return "upgrade_preview"

        # 升级应用
        apply_keywords = ["执行升级", "应用升级", "升级到", "upgrade apply", "开始升级"]
        if any(kw in prompt_lower for kw in apply_keywords):
            return "upgrade_apply"

        # 回滚
        rollback_keywords = ["回滚", "rollback", "降级", "退回版本"]
        if any(kw in prompt_lower for kw in rollback_keywords):
            return "upgrade_rollback"

        # 测试
        test_keywords = ["测试", "test", "跑测试", "运行测试", "执行测试"]
        if any(kw in prompt_lower for kw in test_keywords):
            return "run_test"

        # 默认：健康检查
        return "health_check"

    def _extract_target_modules(
        self, prompt_lower: str, metadata: dict[str, Any]
    ) -> list[str]:
        """从提示词和元数据中提取目标模块"""
        # 优先从 metadata 获取
        if metadata.get("module"):
            module = metadata["module"].lower()
            if module in self._MODULE_INFO:
                return [module]
        if metadata.get("modules"):
            modules = [m.lower() for m in metadata["modules"]]
            return [m for m in modules if m in self._MODULE_INFO]

        # 从提示词中匹配模块名
        found: list[str] = []
        for module_id in self._MODULE_INFO:
            if module_id in prompt_lower:
                found.append(module_id)

        # 关键词：全部 / 所有 / all
        all_keywords = ["全部", "所有", "all", "各模块", "每个模块"]
        if any(kw in prompt_lower for kw in all_keywords):
            return list(self._MODULE_INFO.keys())

        if found:
            return found

        # 默认：所有模块
        return list(self._MODULE_INFO.keys())

    def _extract_params(
        self, prompt: str, metadata: dict[str, Any], command_type: str
    ) -> dict[str, Any]:
        """提取命令的额外参数"""
        params: dict[str, Any] = {}

        if command_type == "update_config":
            # 尝试从 metadata 获取配置更新内容
            if metadata.get("config_updates"):
                params["config_updates"] = metadata["config_updates"]

        elif command_type in ("upgrade_preview", "upgrade_apply", "upgrade_rollback"):
            if metadata.get("target_version"):
                params["target_version"] = metadata["target_version"]
            if metadata.get("package_url"):
                params["package_url"] = metadata["package_url"]

        elif command_type == "run_test":
            if metadata.get("test_type"):
                params["test_type"] = metadata["test_type"]
            if metadata.get("test_scope"):
                params["test_scope"] = metadata["test_scope"]

        return params

    # ── 命令实现：健康检查 ──────────────────────────────────────────────

    async def _cmd_health_check(self, modules: list[str]) -> str:
        """执行健康检查命令"""
        assert self._http_client is not None
        module_addresses = self._config["module_addresses"]

        results: list[dict[str, Any]] = []
        for module_id in modules:
            base_url = module_addresses.get(module_id)
            if not base_url:
                results.append({
                    "module": module_id,
                    "status": "unknown",
                    "error": "未配置地址",
                })
                continue

            info = self._MODULE_INFO.get(module_id, {})
            try:
                url = base_url.rstrip("/") + "/health"
                response = await self._http_client.get(
                    url,
                    timeout=self._config["request_timeout"],
                )
                if response.status_code == 200:
                    data = response.json()
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "role": info.get("role", ""),
                        "status": data.get("status", "unknown"),
                        "version": data.get("version", "unknown"),
                        "uptime_seconds": data.get("uptime_seconds", 0),
                    })
                else:
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "status": f"error_http_{response.status_code}",
                    })
            except httpx.ConnectError as exc:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "status": "unreachable",
                    "error": str(exc),
                })
            except httpx.TimeoutException:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "status": "timeout",
                })
            except Exception as exc:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "status": "error",
                    "error": str(exc),
                })

        return self._format_health_report(results)

    def _format_health_report(self, results: list[dict[str, Any]]) -> str:
        """格式化健康检查报告"""
        total = len(results)
        healthy = sum(1 for r in results if r.get("status") == "healthy")
        degraded = sum(1 for r in results if r.get("status") == "degraded")
        unhealthy = sum(
            1 for r in results
            if r.get("status") not in ("healthy", "degraded")
        )

        lines = []
        lines.append("🏥 云汐系统健康检查报告")
        lines.append("=" * 50)
        lines.append(
            f"总计 {total} 个模块 | ✅ 正常 {healthy} | "
            f"⚠️ 降级 {degraded} | ❌ 异常 {unhealthy}"
        )
        lines.append("")

        status_icon = {
            "healthy": "✅",
            "degraded": "⚠️",
            "unreachable": "❌",
            "timeout": "⏱️",
        }

        for r in results:
            module_id = r.get("module", "?")
            name = r.get("name", module_id)
            role = r.get("role", "")
            status = r.get("status", "unknown")
            icon = status_icon.get(status, "❓")

            line = f"{icon} {module_id.upper()} - {name}"
            if role:
                line += f"（{role}）"
            lines.append(line)

            if status == "healthy":
                version = r.get("version", "?")
                uptime = r.get("uptime_seconds", 0)
                uptime_str = self._format_uptime(uptime)
                lines.append(f"   版本: v{version} | 运行时长: {uptime_str}")
            else:
                error = r.get("error", "")
                if error:
                    lines.append(f"   状态: {status} - {error}")
                else:
                    lines.append(f"   状态: {status}")
            lines.append("")

        # 总结
        lines.append("-" * 50)
        if unhealthy == 0 and degraded == 0:
            lines.append("💚 系统整体健康，所有模块运行正常。")
        elif unhealthy > 0:
            lines.append("🔴 存在异常模块，请关注并及时处理。")
        else:
            lines.append("🟡 部分模块处于降级状态，建议关注。")

        return "\n".join(lines)

    # ── 命令实现：性能指标 ──────────────────────────────────────────────

    async def _cmd_get_metrics(self, modules: list[str]) -> str:
        """获取性能指标命令"""
        assert self._http_client is not None
        module_addresses = self._config["module_addresses"]

        results: list[dict[str, Any]] = []
        for module_id in modules:
            base_url = module_addresses.get(module_id)
            if not base_url:
                results.append({"module": module_id, "error": "未配置地址"})
                continue

            info = self._MODULE_INFO.get(module_id, {})
            try:
                url = base_url.rstrip("/") + "/metrics"
                response = await self._http_client.get(
                    url,
                    timeout=self._config["request_timeout"],
                )
                if response.status_code == 200:
                    data = response.json()
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "cpu_percent": data.get("cpu_percent", 0),
                        "memory_mb": data.get("memory_mb", 0),
                        "requests_total": data.get("requests_total", 0),
                        "requests_per_second": data.get("requests_per_second", 0),
                        "avg_response_ms": data.get("avg_response_ms", 0),
                        "error_rate": data.get("error_rate", 0),
                        "active_tasks": data.get("active_tasks", 0),
                        "queue_size": data.get("queue_size", 0),
                    })
                else:
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "error": f"HTTP {response.status_code}",
                    })
            except Exception as exc:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "error": str(exc),
                })

        return self._format_metrics_report(results)

    def _format_metrics_report(self, results: list[dict[str, Any]]) -> str:
        """格式化性能指标报告"""
        lines = []
        lines.append("📊 云汐系统性能指标报告")
        lines.append("=" * 50)
        lines.append("")

        for r in results:
            module_id = r.get("module", "?")
            name = r.get("name", module_id)

            if "error" in r:
                lines.append(f"❌ {module_id.upper()} - {name}")
                lines.append(f"   获取失败: {r['error']}")
                lines.append("")
                continue

            cpu = r.get("cpu_percent", 0)
            mem = r.get("memory_mb", 0)
            rps = r.get("requests_per_second", 0)
            latency = r.get("avg_response_ms", 0)
            error_rate = r.get("error_rate", 0)
            active = r.get("active_tasks", 0)
            queue = r.get("queue_size", 0)

            # CPU 负载指示
            cpu_icon = "🟢" if cpu < 50 else ("🟡" if cpu < 80 else "🔴")
            mem_icon = "🟢" if mem < 1024 else ("🟡" if mem < 2048 else "🔴")

            lines.append(f"📦 {module_id.upper()} - {name}")
            lines.append(f"   {cpu_icon} CPU: {cpu:.1f}%")
            lines.append(f"   {mem_icon} 内存: {mem:.1f} MB")
            lines.append(f"   🔄 QPS: {rps:.2f} req/s")
            lines.append(f"   ⏱️  平均延迟: {latency:.2f} ms")
            lines.append(f"   ❌ 错误率: {error_rate:.2%}")
            lines.append(f"   🏃 活跃任务: {active}")
            lines.append(f"   📋 队列长度: {queue}")
            lines.append("")

        return "\n".join(lines)

    # ── 命令实现：配置管理 ──────────────────────────────────────────────

    async def _cmd_get_config(self, modules: list[str]) -> str:
        """获取配置命令"""
        assert self._http_client is not None
        module_addresses = self._config["module_addresses"]
        headers = self._get_m8_headers()

        results: list[dict[str, Any]] = []
        for module_id in modules:
            base_url = module_addresses.get(module_id)
            if not base_url:
                results.append({"module": module_id, "error": "未配置地址"})
                continue

            info = self._MODULE_INFO.get(module_id, {})
            try:
                url = base_url.rstrip("/") + "/config"
                response = await self._http_client.get(
                    url,
                    headers=headers,
                    timeout=self._config["request_timeout"],
                )
                if response.status_code == 200:
                    data = response.json()
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "config": data.get("config", {}),
                        "masked": data.get("masked", False),
                    })
                else:
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "error": f"HTTP {response.status_code}",
                    })
            except Exception as exc:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "error": str(exc),
                })

        return self._format_config_report(results)

    async def _cmd_update_config(
        self, modules: list[str], params: dict[str, Any]
    ) -> str:
        """更新配置命令"""
        assert self._http_client is not None
        module_addresses = self._config["module_addresses"]
        headers = self._get_m8_headers()
        config_updates = params.get("config_updates", {})

        if not config_updates:
            return "⚠️  未提供要更新的配置项，请通过 metadata.config_updates 传入。"

        results: list[dict[str, Any]] = []
        for module_id in modules:
            base_url = module_addresses.get(module_id)
            if not base_url:
                results.append({"module": module_id, "error": "未配置地址"})
                continue

            info = self._MODULE_INFO.get(module_id, {})
            try:
                url = base_url.rstrip("/") + "/config/update"
                response = await self._http_client.post(
                    url,
                    headers=headers,
                    json={"updates": config_updates},
                    timeout=self._config["request_timeout"],
                )
                if response.status_code == 200:
                    data = response.json()
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "success": data.get("success", False),
                        "message": data.get("message", ""),
                        "needs_restart": data.get("needs_restart", False),
                    })
                else:
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text}",
                    })
            except Exception as exc:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "success": False,
                    "error": str(exc),
                })

        return self._format_update_config_report(results)

    def _format_config_report(self, results: list[dict[str, Any]]) -> str:
        """格式化配置报告"""
        lines = []
        lines.append("⚙️  云汐系统配置报告")
        lines.append("=" * 50)
        lines.append("")

        for r in results:
            module_id = r.get("module", "?")
            name = r.get("name", module_id)

            if "error" in r:
                lines.append(f"❌ {module_id.upper()} - {name}")
                lines.append(f"   获取失败: {r['error']}")
                lines.append("")
                continue

            lines.append(f"📦 {module_id.upper()} - {name}")
            if r.get("masked"):
                lines.append("   🔒 配置已脱敏显示")

            config = r.get("config", {})
            if isinstance(config, dict):
                self._format_config_section(lines, config, "   ")
            lines.append("")

        return "\n".join(lines)

    def _format_config_section(
        self, lines: list[str], config: dict[str, Any], indent: str
    ) -> None:
        """递归格式化配置段"""
        for key, value in config.items():
            if isinstance(value, dict):
                lines.append(f"{indent}{key}:")
                self._format_config_section(lines, value, indent + "  ")
            elif isinstance(value, list):
                lines.append(f"{indent}{key}: {', '.join(str(v) for v in value[:5])}")
                if len(value) > 5:
                    lines.append(f"{indent}  ... 等 {len(value)} 项")
            else:
                lines.append(f"{indent}{key}: {value}")

    def _format_update_config_report(self, results: list[dict[str, Any]]) -> str:
        """格式化配置更新报告"""
        lines = []
        lines.append("🔧 配置更新结果")
        lines.append("=" * 50)
        lines.append("")

        success_count = sum(1 for r in results if r.get("success"))
        fail_count = len(results) - success_count

        for r in results:
            module_id = r.get("module", "?")
            name = r.get("name", module_id)

            if r.get("success"):
                lines.append(f"✅ {module_id.upper()} - {name}")
                lines.append(f"   {r.get('message', '配置更新成功')}")
                if r.get("needs_restart"):
                    lines.append("   ⚠️  需要重启生效")
            else:
                lines.append(f"❌ {module_id.upper()} - {name}")
                lines.append(f"   {r.get('error', '更新失败')}")
            lines.append("")

        lines.append("-" * 50)
        lines.append(f"成功: {success_count} | 失败: {fail_count}")

        return "\n".join(lines)

    # ── 命令实现：升级管理 ──────────────────────────────────────────────

    async def _cmd_upgrade_preview(
        self, modules: list[str], params: dict[str, Any]
    ) -> str:
        """升级预览命令"""
        return await self._upgrade_operation(
            modules, params, "upgrade/preview", "升级预览"
        )

    async def _cmd_upgrade_apply(
        self, modules: list[str], params: dict[str, Any]
    ) -> str:
        """执行升级命令"""
        return await self._upgrade_operation(
            modules, params, "upgrade/apply", "应用升级"
        )

    async def _cmd_upgrade_rollback(
        self, modules: list[str], params: dict[str, Any]
    ) -> str:
        """回滚命令"""
        return await self._upgrade_operation(
            modules, params, "upgrade/rollback", "版本回滚"
        )

    async def _upgrade_operation(
        self,
        modules: list[str],
        params: dict[str, Any],
        endpoint: str,
        operation_name: str,
    ) -> str:
        """通用升级操作"""
        assert self._http_client is not None
        module_addresses = self._config["module_addresses"]
        headers = self._get_m8_headers()

        payload = {}
        if params.get("target_version"):
            payload["target_version"] = params["target_version"]
        if params.get("package_url"):
            payload["package_url"] = params["package_url"]

        results: list[dict[str, Any]] = []
        for module_id in modules:
            base_url = module_addresses.get(module_id)
            if not base_url:
                results.append({"module": module_id, "error": "未配置地址"})
                continue

            info = self._MODULE_INFO.get(module_id, {})
            try:
                url = f"{base_url.rstrip('/')}/{endpoint}"
                response = await self._http_client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self._config["request_timeout"],
                )
                if response.status_code == 200:
                    data = response.json()
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "success": data.get("success", False),
                        **data,
                    })
                else:
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                    })
            except Exception as exc:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "success": False,
                    "error": str(exc),
                })

        return self._format_upgrade_report(results, operation_name)

    def _format_upgrade_report(
        self, results: list[dict[str, Any]], operation_name: str
    ) -> str:
        """格式化升级操作报告"""
        lines = []
        lines.append(f"🚀 {operation_name}结果")
        lines.append("=" * 50)
        lines.append("")

        for r in results:
            module_id = r.get("module", "?")
            name = r.get("name", module_id)

            if "error" in r and not r.get("success"):
                lines.append(f"❌ {module_id.upper()} - {name}")
                lines.append(f"   失败: {r['error']}")
                lines.append("")
                continue

            lines.append(f"✅ {module_id.upper()} - {name}")

            if "current_version" in r:
                lines.append(f"   当前版本: v{r['current_version']}")
            if "target_version" in r:
                lines.append(f"   目标版本: v{r['target_version']}")
            if "compatible" in r:
                comp = "兼容" if r["compatible"] else "不兼容"
                lines.append(f"   兼容性: {comp}")
            if "estimated_time_seconds" in r:
                lines.append(f"   预计耗时: {r['estimated_time_seconds']} 秒")
            if "requires_restart" in r:
                lines.append(
                    f"   是否重启: {'是' if r['requires_restart'] else '否'}"
                )
            if "can_upgrade" in r:
                can = "可以升级" if r["can_upgrade"] else "暂不可升级"
                lines.append(f"   结论: {can}")
            if "upgrade_id" in r:
                lines.append(f"   升级任务ID: {r['upgrade_id']}")
            if "rollback_id" in r:
                lines.append(f"   回滚任务ID: {r['rollback_id']}")
            if "status" in r:
                lines.append(f"   状态: {r['status']}")
            if "message" in r:
                lines.append(f"   消息: {r['message']}")
            lines.append("")

        return "\n".join(lines)

    # ── 命令实现：测试管理 ──────────────────────────────────────────────

    async def _cmd_run_test(
        self, modules: list[str], params: dict[str, Any]
    ) -> str:
        """运行测试命令"""
        assert self._http_client is not None
        module_addresses = self._config["module_addresses"]
        headers = self._get_m8_headers()

        test_type = params.get("test_type", "smoke")
        test_scope = params.get("test_scope", "core")

        results: list[dict[str, Any]] = []
        for module_id in modules:
            base_url = module_addresses.get(module_id)
            if not base_url:
                results.append({"module": module_id, "error": "未配置地址"})
                continue

            info = self._MODULE_INFO.get(module_id, {})
            try:
                url = base_url.rstrip("/") + "/test/run"
                response = await self._http_client.post(
                    url,
                    headers=headers,
                    json={"type": test_type, "scope": test_scope},
                    timeout=self._config["request_timeout"],
                )
                if response.status_code == 200:
                    data = response.json()
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "success": data.get("success", False),
                        "test_id": data.get("test_id", ""),
                        "test_type": data.get("test_type", test_type),
                        "status": data.get("status", "unknown"),
                        "message": data.get("message", ""),
                    })
                else:
                    results.append({
                        "module": module_id,
                        "name": info.get("name", module_id),
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                    })
            except Exception as exc:
                results.append({
                    "module": module_id,
                    "name": info.get("name", module_id),
                    "success": False,
                    "error": str(exc),
                })

        return self._format_test_report(results)

    def _format_test_report(self, results: list[dict[str, Any]]) -> str:
        """格式化测试报告"""
        lines = []
        lines.append("🧪 云汐系统测试任务")
        lines.append("=" * 50)
        lines.append("")

        for r in results:
            module_id = r.get("module", "?")
            name = r.get("name", module_id)

            if "error" in r and not r.get("success"):
                lines.append(f"❌ {module_id.upper()} - {name}")
                lines.append(f"   失败: {r['error']}")
                lines.append("")
                continue

            lines.append(f"✅ {module_id.upper()} - {name}")
            lines.append(f"   测试ID: {r.get('test_id', '?')}")
            lines.append(f"   测试类型: {r.get('test_type', '?')}")
            lines.append(f"   状态: {r.get('status', '?')}")
            if r.get("message"):
                lines.append(f"   消息: {r['message']}")
            lines.append("")

        lines.append("-" * 50)
        lines.append("💡 测试任务已提交，请稍后使用 test/result/{test_id} 查看结果。")

        return "\n".join(lines)

    # ── 帮助信息 ────────────────────────────────────────────────────────

    def _format_help(self) -> str:
        """格式化帮助信息"""
        return """📋 云汐总管 — 模块管理帮助

我可以帮你管理云汐八大模块（M1~M8），支持以下操作：

🔍 健康检查
   示例："检查所有模块状态" / "M1 健康检查"

📊 性能指标
   示例："查看各模块性能指标" / "M5 内存使用情况"

⚙️  配置管理
   - 查看配置："获取 M1 的配置"
   - 更新配置：需通过 metadata.config_updates 传入

🚀 升级管理
   - 升级预览："检查 M1 是否可以升级"
   - 执行升级："将 M3 升级到新版本"
   - 版本回滚："回滚 M7 到上一版本"

🧪 测试管理
   示例："对 M2 运行冒烟测试"

💡 提示：
   - 可以指定单个模块（如 M1）或全部模块
   - 敏感操作需要配置 M8 管理令牌
   - 所有操作基于 M8 标准接口
"""

    # ── 工具方法 ────────────────────────────────────────────────────────

    def _get_m8_headers(self) -> dict[str, str]:
        """获取 M8 鉴权请求头"""
        token = self._config.get("m8_token", "")
        if token:
            return {"X-M8-Token": token}
        return {}

    def _format_uptime(self, seconds: int) -> str:
        """格式化运行时长"""
        if not seconds or seconds <= 0:
            return "未知"
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days > 0:
            return f"{days}天{hours}小时{minutes}分钟"
        if hours > 0:
            return f"{hours}小时{minutes}分钟"
        return f"{minutes}分钟"

    # ── HTTP 客户端 ─────────────────────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        """确保 HTTP 客户端已创建"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("module_manager_http_client_created")

    # ── 资源清理 ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
