"""
推理管家 Agent 适配器 — InferenceManagerAgentAdapter

M3 推理调度系统的智能代理，负责模型管理和端云协同推理。

核心能力：
  - 模型加载/卸载：动态管理本地模型的加载和卸载
  - 显存管理：VRAM 监控和优化，防止显存溢出
  - 端云调度：根据任务复杂度智能选择本地推理或云端推理
  - 推理路由：将请求路由到最合适的模型和推理后端
  - VRAM 监控：实时监控显存使用情况

身份设定：推理管家 — 云汐的推理调度专家，技术专家、高效调度、资源优化

使用示例：
    adapter = InferenceManagerAgentAdapter(
        agent_id="inference_manager_01",
        display_name="推理管家",
        config={
            "m3_base_url": "http://localhost:8003",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:3b",
        },
    )

    # 查看显存状态
    result = await adapter.invoke("当前显存使用情况如何")

    # 加载模型
    result = await adapter.invoke("加载 qwen2.5:7b 模型")
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from src.federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class InferenceManagerAgentAdapter(AgentAdapterBase):
    """推理管家 Agent — 云汐的推理调度专家

    基于 M3 推理调度系统 + 本地轻量大模型，负责：
      1. 模型管理（加载、卸载、状态查询）
      2. 显存管理（VRAM 监控、自动清理）
      3. 端云调度（本地 vs 云端智能路由）
      4. 推理路由（多模型负载均衡）
      5. 性能监控（推理延迟、吞吐量统计）
    """

    provider: str = "InferenceManager"
    adapter_type: str = "inference_manager_agent"

    # ── 系统提示词 ───────────────────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「推理管家」，云汐系统的推理调度专家。

## 你的身份

你负责管理云汐的所有推理资源，像一位高效的资源调度总监。
你精通模型架构、显存优化、端云协同等技术细节。
你性格严谨、高效、追求资源利用最优化。

## 你的能力

1. **模型管理**：加载、卸载、查询本地和云端模型
2. **显存管理**：监控 VRAM 使用，智能清理和调度
3. **端云调度**：根据任务复杂度选择本地或云端推理
4. **推理路由**：将请求分配到最合适的模型后端
5. **性能优化**：调整推理参数，优化吞吐量和延迟

## 管理的推理后端

- **本地 Ollama**：轻量级本地模型，低延迟，隐私安全
- **本地 GPU 推理**：高性能本地推理，需要 GPU 支持
- **云端 API**：高质量大模型，适合复杂任务
- **混合模式**：端云协同，兼顾性能和成本

## 工作原则

- 高效调度：在保证质量的前提下，优先使用最低成本的方案
- 资源优化：合理分配显存，避免浪费和溢出
- 隐私优先：敏感数据优先本地处理，不上传云端
- 负载均衡：多模型时智能分配，避免单点过载
- 故障恢复：推理失败时自动降级或重试

## 输出风格

- 用中文回答，专业、清晰、有条理
- 显存/内存数据用带单位的数字呈现（如 GB、MB）
- 状态信息用进度条或百分比直观展示
- 推荐方案时说明理由和权衡
- 技术术语适当解释，兼顾专业性和可读性
"""

    # ── 支持的命令类型 ───────────────────────────────────────────────────

    _COMMAND_TYPES = [
        "vram_status",        # VRAM 状态
        "model_load",         # 加载模型
        "model_unload",       # 卸载模型
        "model_list",         # 模型列表
        "route_inference",    # 推理路由
        "cloud_sync",         # 云端同步
        "perf_stats",         # 性能统计
    ]

    def __init__(
        self,
        agent_id: str = "inference_manager_01",
        display_name: str = "推理管家",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化推理管家 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - m3_base_url: M3 推理调度服务地址（默认 http://localhost:8003）
                - ollama_base_url: Ollama 服务地址
                - model_name: 推理模型名称（默认 qwen2.5:3b）
                - cloud_api_base: 云端推理 API 地址（可选）
                - cloud_api_key: 云端推理 API 密钥（可选）
                - enable_cloud_fallback: 是否启用云端降级（默认 False）
                - vram_warning_threshold: VRAM 告警阈值（0.8 = 80%）
                - enable_llm_enhance: 是否启用 LLM 增强（默认 True）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("m3_base_url", "http://localhost:8003")
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:3b")
        config.setdefault("cloud_api_base", "")
        config.setdefault("cloud_api_key", "")
        config.setdefault("enable_cloud_fallback", False)
        config.setdefault("vram_warning_threshold", 0.8)
        config.setdefault("enable_llm_enhance", True)
        config.setdefault("temperature", 0.2)
        config.setdefault("max_iterations", 3)

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "CNY",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._vram_cache: dict[str, Any] | None = None

        self._logger = self._logger.bind(
            model=config["model_name"],
            m3_url=config["m3_base_url"],
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
        """执行推理管理任务

        根据用户意图自动判断是显存监控、模型管理还是调度配置。
        """
        await self._ensure_http_client()

        # 判断任务类型
        task_type = self._classify_task(prompt, metadata)

        self._logger.info(
            "inference_manager_task_classified",
            task_type=task_type,
            prompt_length=len(prompt),
        )

        total_input_tokens = 0
        total_output_tokens = 0

        if task_type == "vram_status":
            # VRAM 状态监控
            result, in_tok, out_tok = await self._do_vram_status(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m3_vram_monitor", "type": "monitor"}]

        elif task_type == "model_load":
            # 加载模型
            result, in_tok, out_tok = await self._do_model_load(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m3_model_load", "type": "model_manage"}]

        elif task_type == "model_unload":
            # 卸载模型
            result, in_tok, out_tok = await self._do_model_unload(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m3_model_unload", "type": "model_manage"}]

        elif task_type == "model_list":
            # 模型列表
            result, in_tok, out_tok = await self._do_model_list(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m3_model_list", "type": "model_manage"}]

        elif task_type == "route_inference":
            # 推理路由
            result, in_tok, out_tok = await self._do_route(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m3_inference_router", "type": "route"}]

        elif task_type == "cloud_sync":
            # 云端同步
            result, in_tok, out_tok = await self._do_cloud_sync(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m3_cloud_sync", "type": "sync"}]

        elif task_type == "perf_stats":
            # 性能统计
            result, in_tok, out_tok = await self._do_perf_stats(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m3_perf_stats", "type": "stats"}]

        else:
            # 默认：显示 VRAM 状态
            try:
                result, in_tok, out_tok = await self._do_vram_status(prompt, metadata)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                output_text = result
                tools_used = [{"tool": "m3_vram_monitor", "type": "monitor"}]
            except Exception:
                # M3 不可用时，直接用 LLM 回答
                output_text, in_tok, out_tok = await self._call_ollama(
                    messages=[
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                tools_used = []

        return {
            "output": output_text,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "model": self._config["model_name"],
            "task_type": task_type,
            "tools_used": tools_used,
            "local": True,
            "inference_system": "inference_manager_v1.0",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查 M3 推理调度服务 + Ollama 模型 + 可选云端 API
        """
        health_issues: list[str] = []
        m3_ok = False
        ollama_ok = False
        cloud_ok = None  # None 表示未配置

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            # 检查 M3 服务（M8 标准 health 接口）
            m3_url = self._config["m3_base_url"].rstrip("/")
            try:
                response = await self._http_client.get(
                    f"{m3_url}/health",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    m3_ok = True
                else:
                    health_issues.append(f"M3 服务异常 (HTTP {response.status_code})")
            except httpx.ConnectError as exc:
                health_issues.append(f"M3 服务不可达: {exc}")
            except Exception as exc:
                health_issues.append(f"M3 健康检查异常: {exc}")

            # 检查 Ollama 模型
            if self._config.get("enable_llm_enhance", True):
                ollama_url = self._config["ollama_base_url"].rstrip("/")
                try:
                    response = await self._http_client.get(
                        f"{ollama_url}/api/tags",
                        timeout=5.0,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        if self._config["model_name"] in models:
                            ollama_ok = True
                        else:
                            health_issues.append(
                                f"模型 '{self._config['model_name']}' 未安装"
                            )
                    else:
                        health_issues.append("Ollama 服务异常")
                except Exception as exc:
                    health_issues.append(f"Ollama 检查异常: {exc}")

            # 检查云端 API（如果配置了）
            if self._config.get("cloud_api_base") and self._config.get("cloud_api_key"):
                cloud_base = self._config["cloud_api_base"].rstrip("/")
                try:
                    response = await self._http_client.get(
                        f"{cloud_base}/v1/models",
                        headers={"Authorization": f"Bearer {self._config['cloud_api_key']}"},
                        timeout=5.0,
                    )
                    cloud_ok = response.status_code == 200
                    if not cloud_ok:
                        health_issues.append(f"云端 API 异常 (HTTP {response.status_code})")
                except Exception as exc:
                    health_issues.append(f"云端 API 检查异常: {exc}")

        except Exception as exc:
            health_issues.append(f"健康检查异常: {exc}")

        if health_issues:
            return {
                "healthy": False,
                "message": "; ".join(health_issues),
            }

        status_parts = []
        if m3_ok:
            status_parts.append("M3推理调度服务正常")
        if ollama_ok:
            status_parts.append(f"模型 {self._config['model_name']} 就绪")
        if cloud_ok is True:
            status_parts.append("云端 API 连接正常")

        return {
            "healthy": True,
            "message": f"推理管家运行正常（{'，'.join(status_parts)}）",
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（本地推理免费）"""
        return 0.0

    # ── 任务分类 ────────────────────────────────────────────────────────

    def _classify_task(self, prompt: str, metadata: dict[str, Any]) -> str:
        """分类用户请求的任务类型

        Returns: vram_status / model_load / model_unload / model_list /
                 route_inference / cloud_sync / perf_stats
        """
        # 优先从 metadata 获取明确的任务类型
        if metadata.get("task_type"):
            return metadata["task_type"]

        prompt_lower = prompt.lower()

        # VRAM / 显存类关键词
        vram_keywords = ["显存", "vram", "gpu 内存", "显存使用", "显存状态",
                         "显卡内存", "gpu 占用"]
        if any(kw in prompt_lower for kw in vram_keywords):
            return "vram_status"

        # 加载模型类关键词
        load_keywords = ["加载模型", "载入模型", "load model", "启动模型",
                         "拉取模型", "pull model"]
        if any(kw in prompt_lower for kw in load_keywords):
            return "model_load"

        # 卸载模型类关键词
        unload_keywords = ["卸载模型", "释放模型", "unload model", "清理模型",
                           "删除模型", "remove model"]
        if any(kw in prompt_lower for kw in unload_keywords):
            return "model_unload"

        # 模型列表类关键词
        list_keywords = ["模型列表", "有哪些模型", "已安装模型", "模型清单",
                         "list models", "可用模型"]
        if any(kw in prompt_lower for kw in list_keywords):
            return "model_list"

        # 路由 / 调度类关键词
        route_keywords = ["路由", "调度", "route", "schedule", "分配",
                          "端云", "本地还是云端"]
        if any(kw in prompt_lower for kw in route_keywords):
            return "route_inference"

        # 云端同步类关键词
        sync_keywords = ["云端同步", "同步到云", "cloud sync", "上传模型",
                         "云同步"]
        if any(kw in prompt_lower for kw in sync_keywords):
            return "cloud_sync"

        # 性能统计类关键词
        perf_keywords = ["性能", "统计", "吞吐量", "延迟", "性能指标",
                         "perf", "metrics", "benchmark"]
        if any(kw in prompt_lower for kw in perf_keywords):
            return "perf_stats"

        # 默认：VRAM 状态
        return "vram_status"

    # ── VRAM 状态监控 ───────────────────────────────────────────────────

    async def _do_vram_status(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """查询 VRAM 使用状态

        Returns: (回答文本, 输入tokens, 输出tokens)
        """
        assert self._http_client is not None

        m3_url = self._config["m3_base_url"].rstrip("/")
        warning_threshold = self._config["vram_warning_threshold"]

        try:
            # 调用 M3 VRAM 监控接口
            response = await self._http_client.get(
                f"{m3_url}/api/v1/vram/status",
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M3 VRAM status failed: HTTP {response.status_code}")

            data = response.json()
            vram_info = data.get("result", data)

        except Exception as exc:
            self._logger.warning("vram_status_failed", error=str(exc))
            # 降级：从 Ollama 获取基本信息
            return await self._get_ollama_vram_info(prompt)

        total = vram_info.get("total_vram_mb", vram_info.get("total", 0))
        used = vram_info.get("used_vram_mb", vram_info.get("used", 0))
        free = vram_info.get("free_vram_mb", vram_info.get("free", 0))
        usage_percent = vram_info.get("usage_percent", used / total if total else 0)

        # 加载的模型
        loaded_models = vram_info.get("loaded_models", [])

        answer = self._format_vram_report(
            total, used, free, usage_percent, loaded_models, warning_threshold
        )

        return answer, len(prompt) // 4, len(answer) // 4

    def _format_vram_report(
        self,
        total_mb: float,
        used_mb: float,
        free_mb: float,
        usage_percent: float,
        loaded_models: list[dict],
        warning_threshold: float,
    ) -> str:
        """格式化 VRAM 状态报告"""
        total_gb = total_mb / 1024
        used_gb = used_mb / 1024
        free_gb = free_mb / 1024

        # 状态判定
        if usage_percent >= warning_threshold:
            status_icon = "🔴"
            status_text = "显存紧张"
            status_tip = "建议卸载不常用的模型以释放显存"
        elif usage_percent >= 0.6:
            status_icon = "🟡"
            status_text = "显存适中"
            status_tip = "显存使用在合理范围内"
        else:
            status_icon = "🟢"
            status_text = "显存充足"
            status_tip = "可以加载更多模型"

        # 进度条（20 格）
        bar_length = 20
        filled = int(usage_percent * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)

        lines = []
        lines.append(f"{status_icon} GPU 显存状态")
        lines.append("=" * 40)
        lines.append(f"")
        lines.append(f"   {bar}  {usage_percent:.1%}")
        lines.append(f"")
        lines.append(f"   总显存: {total_gb:.2f} GB")
        lines.append(f"   已使用: {used_gb:.2f} GB")
        lines.append(f"   可用:   {free_gb:.2f} GB")
        lines.append(f"   状态:   {status_text}")
        lines.append(f"")

        if loaded_models:
            lines.append(f"📦 已加载模型 ({len(loaded_models)} 个):")
            for m in loaded_models:
                name = m.get("name", m.get("model", "未知"))
                size = m.get("size_mb", m.get("vram_usage_mb", 0))
                size_gb = size / 1024 if size else 0
                lines.append(f"   • {name}  ({size_gb:.2f} GB)")
            lines.append("")

        lines.append(f"💡 {status_tip}")

        return "\n".join(lines)

    async def _get_ollama_vram_info(self, prompt: str) -> tuple[str, int, int]:
        """从 Ollama 获取基本显存信息（降级路径）"""
        assert self._http_client is not None

        ollama_url = self._config["ollama_base_url"].rstrip("/")

        try:
            response = await self._http_client.get(
                f"{ollama_url}/api/tags",
                timeout=5.0,
            )
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                model_names = [m.get("name", "") for m in models]

                answer = "📊 Ollama 模型信息\n\n"
                if model_names:
                    answer += f"已安装 {len(model_names)} 个模型：\n"
                    for name in model_names:
                        answer += f"  • {name}\n"
                else:
                    answer += "当前没有已安装的模型。\n"

                answer += "\n💡 提示：配置 M3 服务后可查看详细显存使用情况。"
                return answer, len(prompt) // 4, len(answer) // 4
        except Exception:
            pass

        return "⚠️  暂时无法获取显存信息。", len(prompt) // 4, 0

    # ── 模型加载 ────────────────────────────────────────────────────────

    async def _do_model_load(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """加载模型"""
        assert self._http_client is not None

        m3_url = self._config["m3_base_url"].rstrip("/")
        model_name = metadata.get("model_name", "")

        if not model_name:
            # 从提示词中提取模型名
            extracted = self._extract_model_name(prompt)
            if extracted:
                model_name = extracted
            else:
                return (
                    "⚠️  请指定要加载的模型名称。\n"
                    "💡 你可以说：'加载 qwen2.5:7b 模型' 或 '拉取 llama3:8b'。"
                ), len(prompt) // 4, 0

        try:
            payload = {
                "model_name": model_name,
                "priority": metadata.get("priority", "normal"),
            }
            response = await self._http_client.post(
                f"{m3_url}/api/v1/models/load",
                json=payload,
                timeout=30.0,  # 模型加载可能较慢
            )

            if response.status_code != 200:
                raise RuntimeError(f"M3 model load failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            status = result.get("status", "unknown")

            if status == "loaded" or status == "success":
                answer = (
                    f"✅ 模型加载成功\n\n"
                    f"📦 模型: {model_name}\n"
                    f"⚡ 状态: 已加载就绪\n"
                )
                if result.get("vram_usage_mb"):
                    vram_gb = result["vram_usage_mb"] / 1024
                    answer += f"🧠 显存占用: {vram_gb:.2f} GB\n"
                answer += f"\n💡 模型已准备好，可以开始推理了。"
            else:
                answer = f"⏳ 模型加载中：{status}\n\n模型: {model_name}"

        except Exception as exc:
            self._logger.warning("model_load_failed", error=str(exc))
            answer = f"⚠️  模型加载失败：{exc}\n请检查模型名称是否正确。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 模型卸载 ────────────────────────────────────────────────────────

    async def _do_model_unload(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """卸载模型"""
        assert self._http_client is not None

        m3_url = self._config["m3_base_url"].rstrip("/")
        model_name = metadata.get("model_name", "")

        if not model_name:
            extracted = self._extract_model_name(prompt)
            if extracted:
                model_name = extracted
            else:
                return (
                    "⚠️  请指定要卸载的模型名称。\n"
                    "💡 你可以说：'卸载 qwen2.5:7b 模型' 或 '释放显存'。"
                ), len(prompt) // 4, 0

        try:
            payload = {"model_name": model_name}
            response = await self._http_client.post(
                f"{m3_url}/api/v1/models/unload",
                json=payload,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M3 model unload failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            freed_mb = result.get("freed_vram_mb", 0)

            answer = f"✅ 模型已卸载\n\n"
            answer += f"📦 模型: {model_name}\n"
            if freed_mb:
                answer += f"🧠 释放显存: {freed_mb / 1024:.2f} GB\n"
            answer += f"\n💡 显存已释放，可以加载其他模型了。"

        except Exception as exc:
            self._logger.warning("model_unload_failed", error=str(exc))
            answer = f"⚠️  模型卸载失败：{exc}"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 模型列表 ────────────────────────────────────────────────────────

    async def _do_model_list(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """获取模型列表"""
        assert self._http_client is not None

        m3_url = self._config["m3_base_url"].rstrip("/")

        try:
            response = await self._http_client.get(
                f"{m3_url}/api/v1/models/list",
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M3 model list failed: HTTP {response.status_code}")

            data = response.json()
            models = data.get("result", {}).get("models", data.get("models", []))

        except Exception as exc:
            self._logger.warning("model_list_failed", error=str(exc))
            # 降级：从 Ollama 获取
            return await self._get_ollama_model_list(prompt)

        if not models:
            return "📭 当前没有已注册的模型。", len(prompt) // 4, 0

        answer = f"📋 模型列表（共 {len(models)} 个）\n\n"

        loaded_models = [m for m in models if m.get("status") == "loaded"]
        available_models = [m for m in models if m.get("status") != "loaded"]

        if loaded_models:
            answer += f"🟢 已加载 ({len(loaded_models)} 个):\n"
            for m in loaded_models:
                name = m.get("name", "?")
                size = m.get("size_mb", m.get("vram_usage_mb", 0))
                size_str = f"  ({size / 1024:.2f} GB)" if size else ""
                answer += f"   • {name}{size_str}\n"
            answer += "\n"

        if available_models:
            answer += f"⚪ 可用（未加载）({len(available_models)} 个):\n"
            for m in available_models:
                name = m.get("name", "?")
                answer += f"   • {name}\n"

        answer += "\n💡 说'加载 <模型名>'来加载模型。"

        return answer, len(prompt) // 4, len(answer) // 4

    async def _get_ollama_model_list(self, prompt: str) -> tuple[str, int, int]:
        """从 Ollama 获取模型列表（降级）"""
        assert self._http_client is not None

        ollama_url = self._config["ollama_base_url"].rstrip("/")

        try:
            response = await self._http_client.get(
                f"{ollama_url}/api/tags",
                timeout=5.0,
            )
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])

                answer = f"📦 Ollama 模型列表（共 {len(models)} 个）\n\n"
                for m in models:
                    name = m.get("name", "?")
                    size = m.get("size", 0)
                    size_gb = size / (1024 ** 3) if size else 0
                    answer += f"  • {name}  ({size_gb:.2f} GB)\n"

                answer += "\n💡 提示：配置 M3 服务后可获得更详细的模型管理功能。"
                return answer, len(prompt) // 4, len(answer) // 4
        except Exception as exc:
            return f"⚠️  获取模型列表失败：{exc}", len(prompt) // 4, 0

    # ── 推理路由 ────────────────────────────────────────────────────────

    async def _do_route(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """推理路由决策"""
        assert self._http_client is not None

        m3_url = self._config["m3_base_url"].rstrip("/")
        task_type = metadata.get("task_type", "general")

        try:
            payload = {
                "task_description": prompt,
                "task_type": task_type,
                "preferred_backend": metadata.get("preferred_backend", "auto"),
            }
            response = await self._http_client.post(
                f"{m3_url}/api/v1/router/decide",
                json=payload,
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M3 route decision failed: HTTP {response.status_code}")

            data = response.json()
            decision = data.get("result", data)

        except Exception as exc:
            self._logger.warning("route_decision_failed", error=str(exc))
            return await self._llm_answer(prompt, "路由服务暂时不可用。")

        backend = decision.get("backend", "unknown")
        model = decision.get("model", "?")
        reason = decision.get("reason", "")
        estimated_latency = decision.get("estimated_latency_ms", 0)
        estimated_cost = decision.get("estimated_cost", 0)

        answer = "🛣️  推理路由决策\n\n"
        answer += f"📌 推荐后端: {backend}\n"
        answer += f"🤖 推荐模型: {model}\n"
        if estimated_latency:
            answer += f"⏱️  预计延迟: ~{estimated_latency} ms\n"
        if estimated_cost:
            answer += f"💰 预计费用: {estimated_cost}\n"
        if reason:
            answer += f"\n💡 决策理由: {reason}\n"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 云端同步 ────────────────────────────────────────────────────────

    async def _do_cloud_sync(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """云端模型同步"""
        assert self._http_client is not None

        m3_url = self._config["m3_base_url"].rstrip("/")

        if not self._config.get("cloud_api_base"):
            return (
                "⚠️  未配置云端 API，无法进行云端同步。\n"
                "💡 请在配置中设置 cloud_api_base 和 cloud_api_key。"
            ), len(prompt) // 4, 0

        try:
            action = metadata.get("sync_action", "status")
            if action == "status":
                response = await self._http_client.get(
                    f"{m3_url}/api/v1/cloud/sync/status",
                    timeout=5.0,
                )
            else:
                response = await self._http_client.post(
                    f"{m3_url}/api/v1/cloud/sync/{action}",
                    json=metadata.get("sync_config", {}),
                    timeout=10.0,
                )

            if response.status_code != 200:
                raise RuntimeError(f"M3 cloud sync failed: HTTP {response.status_code}")

            data = response.json()
            sync_info = data.get("result", data)

        except Exception as exc:
            self._logger.warning("cloud_sync_failed", error=str(exc))
            return f"⚠️  云端同步操作失败：{exc}", len(prompt) // 4, 0

        status = sync_info.get("status", "unknown")
        synced = sync_info.get("synced_models", 0)
        total = sync_info.get("total_models", 0)
        last_sync = sync_info.get("last_sync_time", "从未同步")

        answer = "☁️  云端同步状态\n\n"
        answer += f"📊 状态: {status}\n"
        answer += f"📦 已同步模型: {synced} / {total}\n"
        answer += f"🕐 上次同步: {last_sync}\n"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 性能统计 ────────────────────────────────────────────────────────

    async def _do_perf_stats(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """推理性能统计"""
        assert self._http_client is not None

        m3_url = self._config["m3_base_url"].rstrip("/")

        try:
            response = await self._http_client.get(
                f"{m3_url}/api/v1/metrics",
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M3 metrics failed: HTTP {response.status_code}")

            data = response.json()
            metrics = data.get("result", data)

        except Exception as exc:
            self._logger.warning("perf_stats_failed", error=str(exc))
            return f"⚠️  获取性能统计失败：{exc}", len(prompt) // 4, 0

        total_requests = metrics.get("total_requests", 0)
        avg_latency = metrics.get("avg_latency_ms", 0)
        p95_latency = metrics.get("p95_latency_ms", 0)
        throughput = metrics.get("tokens_per_second", 0)
        error_rate = metrics.get("error_rate", 0)

        answer = "📊 推理性能统计\n\n"
        answer += f"🔢 总请求数: {total_requests}\n"
        answer += f"⏱️  平均延迟: {avg_latency:.2f} ms\n"
        answer += f"📈 P95 延迟: {p95_latency:.2f} ms\n"
        answer += f"⚡ 吞吐量: {throughput:.2f} tokens/s\n"
        answer += f"❌ 错误率: {error_rate:.2%}\n"

        # 各模型统计
        model_stats = metrics.get("model_stats", {})
        if model_stats:
            answer += f"\n🤖 各模型统计:\n"
            for model_name, stats in model_stats.items():
                reqs = stats.get("requests", 0)
                lat = stats.get("avg_latency_ms", 0)
                answer += f"   • {model_name}: {reqs} 次请求, 平均 {lat:.2f}ms\n"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 辅助方法 ────────────────────────────────────────────────────────

    def _extract_model_name(self, prompt: str) -> str:
        """从提示词中提取模型名称"""
        import re

        # 匹配常见的模型名称格式：name:size 或 name-version
        patterns = [
            r'(?:加载|载入|拉取|pull|load)\s+([a-zA-Z0-9_\-:.]+)',
            r'(?:卸载|释放|删除|unload|remove)\s+([a-zA-Z0-9_\-:.]+)',
            r'模型\s*([a-zA-Z0-9_\-:.]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                return match.group(1)

        return ""

    # ── LLM 辅助回答 ────────────────────────────────────────────────────

    async def _llm_answer(self, prompt: str, prefix: str) -> tuple[str, int, int]:
        """用 LLM 直接回答（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": f"{prefix}\n\n用户问题：{prompt}"},
            ],
            temperature=self._config.get("temperature", 0.2),
            max_tokens=500,
        )
        return answer, in_tok, out_tok

    # ── HTTP 客户端 ─────────────────────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        """确保 HTTP 客户端已创建"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("inference_manager_http_client_created")

    # ── Ollama 调用 ─────────────────────────────────────────────────────

    async def _call_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 Ollama 本地模型"""
        assert self._http_client is not None

        if not self._config.get("enable_llm_enhance", True):
            return "", 0, 0

        ollama_base = self._config["ollama_base_url"].rstrip("/")
        model_name = self._config["model_name"]

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            response = await self._http_client.post(
                f"{ollama_base}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Ollama 请求超时: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama API 调用失败 (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()
        content = data.get("message", {}).get("content", "")
        input_tokens = data.get("prompt_eval_count", 0) or len("".join(m["content"] for m in messages)) // 4
        output_tokens = data.get("eval_count", 0) or len(content) // 4

        return content, input_tokens, output_tokens

    # ── 资源清理 ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
