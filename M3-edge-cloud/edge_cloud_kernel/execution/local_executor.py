"""本地推理执行器.

对接 Ollama 本地大模型，实现端侧推理。
与 VRAMMonitor 联动进行显存检查，支持流式和非流式调用，
内置指数退避重试和调用日志记录。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp
import structlog

from edge_cloud_kernel.models.call_log import CallLogRecord
from edge_cloud_kernel.models.exceptions import InferenceError, VRAMOverflowError
from edge_cloud_kernel.models.vram_report import VRAMLevel

logger = structlog.get_logger(__name__)

# 默认配置
DEFAULT_OLLAMA_BASE_URL: str = "http://localhost:11434"
DEFAULT_MODEL: str = "qwen2.5:7b"
DEFAULT_TIMEOUT: float = 60.0
DEFAULT_MAX_RETRIES: int = 2
DEFAULT_MIN_VRAM_SAFE_RATIO: float = 0.3

# 重试退避配置
RETRY_BASE_DELAY_S: float = 1.0
RETRY_MAX_DELAY_S: float = 30.0
RETRY_BACKOFF_FACTOR: float = 2.0

# 模型估算显存占用（MB），用于显存预检
# 实际占用取决于量化方式、上下文长度等因素，此处为保守估算
MODEL_VRAM_ESTIMATE_MB: dict[str, float] = {
    "qwen2.5:0.5b": 800.0,
    "qwen2.5:1.5b": 1500.0,
    "qwen2.5:3b": 3000.0,
    "qwen2.5:7b": 6000.0,
    "qwen2.5:14b": 12000.0,
    "qwen2.5:32b": 24000.0,
}


class LocalInferenceExecutor:
    """本地推理执行器.

    对接 Ollama 本地大模型服务，提供文本生成和对话能力。
    与 VRAMMonitor 联动，推理前检查显存状态，不足时降级或拒绝。
    支持流式/非流式调用、指数退避重试、调用日志记录。

    Attributes:
        _base_url: Ollama 服务基础 URL.
        _default_model: 默认使用的模型名称.
        _timeout: 请求超时时间（秒）.
        _max_retries: 最大重试次数.
        _min_vram_safe_ratio: 推理时最低保留显存比例.
        _session: aiohttp ClientSession.
        _vram_monitor: 显存监控器实例.
        _call_logger: 调用日志写入器实例.
        _closed: 是否已关闭.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        vram_monitor: Any = None,
        call_logger: Any = None,
    ) -> None:
        """初始化 LocalInferenceExecutor.

        Args:
            config: 配置字典，支持 ollama_base_url / default_model /
                timeout / max_retries / min_vram_safe_ratio.
            vram_monitor: VRAMMonitor 实例，用于显存预检.
            call_logger: CallLogWriter 实例，用于记录调用日志.
        """
        cfg = config or {}
        self._base_url: str = cfg.get("ollama_base_url", DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        self._default_model: str = cfg.get("default_model", DEFAULT_MODEL)
        self._timeout: float = float(cfg.get("timeout", DEFAULT_TIMEOUT))
        self._max_retries: int = int(cfg.get("max_retries", DEFAULT_MAX_RETRIES))
        self._min_vram_safe_ratio: float = float(
            cfg.get("min_vram_safe_ratio", DEFAULT_MIN_VRAM_SAFE_RATIO)
        )
        self._session: aiohttp.ClientSession | None = None
        self._vram_monitor = vram_monitor
        self._call_logger = call_logger
        self._closed = False
        logger.info(
            "local_executor.init",
            base_url=self._base_url,
            default_model=self._default_model,
            timeout=self._timeout,
            max_retries=self._max_retries,
            min_vram_safe_ratio=self._min_vram_safe_ratio,
            has_vram_monitor=vram_monitor is not None,
            has_call_logger=call_logger is not None,
        )

    async def start(self) -> None:
        """启动执行器，创建 aiohttp 会话."""
        if self._session is not None:
            return
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        self._session = aiohttp.ClientSession(
            base_url=self._base_url,
            timeout=timeout,
            connector=connector,
            headers={"Content-Type": "application/json"},
        )
        logger.info("local_executor.started")

    async def close(self) -> None:
        """关闭执行器，释放会话资源."""
        if self._session and not self._closed:
            await self._session.close()
            self._closed = True
            logger.info("local_executor.closed")

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def generate(
        self,
        model: str | None = None,
        prompt: str = "",
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        stream: bool = False,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """文本生成（补全模式）.

        调用 Ollama /api/generate 接口进行文本生成。

        Args:
            model: 模型名称，为空时使用默认模型.
            prompt: 输入提示文本.
            system: 系统提示词.
            max_tokens: 最大生成 token 数.
            temperature: 采样温度.
            stream: 是否流式返回.
            agent_id: 调用方 Agent 标识，用于日志记录.

        Returns:
            包含 text / model / usage / latency_ms 的字典.

        Raises:
            InferenceError: 推理失败.
            VRAMOverflowError: 显存不足.
        """
        model_name = model or self._default_model
        start_time = time.perf_counter()
        vram_before = self._get_vram_usage()

        # 显存预检
        self._check_vram_before_inference(model_name)

        try:
            if stream:
                result = await self._generate_stream(
                    model=model_name,
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                result = await self._generate_non_stream(
                    model=model_name,
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            latency_ms = (time.perf_counter() - start_time) * 1000
            result["latency_ms"] = round(latency_ms, 2)

            # 记录调用日志
            await self._log_call(
                model=model_name,
                target="local",
                status="success",
                latency_ms=latency_ms,
                usage=result.get("usage", {}),
                agent_id=agent_id or "",
                vram_before=vram_before,
                vram_after=self._get_vram_usage(),
            )

            return result

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            await self._log_call(
                model=model_name,
                target="local",
                status="failed",
                latency_ms=latency_ms,
                usage={},
                agent_id=agent_id or "",
                error_message=str(e),
                vram_before=vram_before,
                vram_after=self._get_vram_usage(),
            )
            if isinstance(e, (InferenceError, VRAMOverflowError)):
                raise
            raise InferenceError(
                message=f"Local inference generate failed: {e}",
                error_code="LOCAL_GENERATE_ERROR",
                context={"model": model_name, "error": str(e)},
            ) from e

    async def chat(
        self,
        model: str | None = None,
        messages: list[dict[str, str]] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """对话式推理（Chat Completion 模式）.

        调用 Ollama /api/chat 接口进行多轮对话。

        Args:
            model: 模型名称，为空时使用默认模型.
            messages: 对话消息列表，每项含 role 和 content.
            max_tokens: 最大生成 token 数.
            temperature: 采样温度.
            agent_id: 调用方 Agent 标识.

        Returns:
            包含 text / model / usage / latency_ms 的字典.

        Raises:
            InferenceError: 推理失败.
            VRAMOverflowError: 显存不足.
        """
        model_name = model or self._default_model
        msgs = messages or []
        start_time = time.perf_counter()
        vram_before = self._get_vram_usage()

        # 显存预检
        self._check_vram_before_inference(model_name)

        try:
            result = await self._chat_non_stream(
                model=model_name,
                messages=msgs,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            result["latency_ms"] = round(latency_ms, 2)

            # 记录调用日志
            await self._log_call(
                model=model_name,
                target="local",
                status="success",
                latency_ms=latency_ms,
                usage=result.get("usage", {}),
                agent_id=agent_id or "",
                vram_before=vram_before,
                vram_after=self._get_vram_usage(),
            )

            return result

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            await self._log_call(
                model=model_name,
                target="local",
                status="failed",
                latency_ms=latency_ms,
                usage={},
                agent_id=agent_id or "",
                error_message=str(e),
                vram_before=vram_before,
                vram_after=self._get_vram_usage(),
            )
            if isinstance(e, (InferenceError, VRAMOverflowError)):
                raise
            raise InferenceError(
                message=f"Local inference chat failed: {e}",
                error_code="LOCAL_CHAT_ERROR",
                context={"model": model_name, "error": str(e)},
            ) from e

    def check_model_available(self, model: str) -> bool:
        """检查指定模型在本地是否可用.

        通过 list_models 查询已安装模型列表。
        若无法连接 Ollama，返回 False。

        Args:
            model: 模型名称.

        Returns:
            模型是否可用.
        """
        try:
            # 同步包装：使用 asyncio.run 可能在已有事件循环中报错
            # 实际调用方应确保在异步上下文中使用
            models = asyncio.get_event_loop().run_until_complete(self.list_models())
            return model in models
        except Exception:
            logger.warning("local_executor.check_model_available_failed", model=model)
            return False

    async def list_models(self) -> list[str]:
        """列出本地已安装的模型.

        调用 Ollama /api/tags 接口获取模型列表。

        Returns:
            模型名称列表.
        """
        if self._session is None:
            await self.start()

        assert self._session is not None
        try:
            async with self._session.get("/api/tags") as resp:
                if resp.status != 200:
                    logger.warning(
                        "local_executor.list_models_failed",
                        status=resp.status,
                    )
                    return []
                data = await resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return [m for m in models if m]
        except Exception as e:
            logger.warning("local_executor.list_models_error", error=str(e))
            return []

    async def health_check(self) -> dict[str, Any]:
        """健康检查.

        检查 Ollama 服务是否可达，并返回状态信息。

        Returns:
            健康检查结果字典，含 status / models_count / version 等.
        """
        result: dict[str, Any] = {
            "status": "unhealthy",
            "service": "ollama",
            "base_url": self._base_url,
            "models_count": 0,
            "version": None,
        }

        if self._session is None:
            await self.start()

        assert self._session is not None
        try:
            async with self._session.get("/api/version") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result["status"] = "healthy"
                    result["version"] = data.get("version", "")
                else:
                    result["error"] = f"HTTP {resp.status}"
        except Exception as e:
            result["status"] = "unreachable"
            result["error"] = str(e)
            logger.warning("local_executor.health_check_failed", error=str(e))

        # 尝试获取模型数量
        try:
            models = await self.list_models()
            result["models_count"] = len(models)
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # 内部方法：非流式生成
    # ------------------------------------------------------------------

    async def _generate_non_stream(
        self,
        model: str,
        prompt: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """非流式文本生成（带指数退避重试）.

        Args:
            model: 模型名称.
            prompt: 提示文本.
            system: 系统提示词.
            max_tokens: 最大 token 数.
            temperature: 采样温度.

        Returns:
            生成结果字典.
        """
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            payload["system"] = system

        data = await self._request_with_retry("POST", "/api/generate", payload)

        usage = self._extract_ollama_usage(data)
        return {
            "text": data.get("response", ""),
            "model": data.get("model", model),
            "usage": usage,
        }

    # ------------------------------------------------------------------
    # 内部方法：流式生成
    # ------------------------------------------------------------------

    async def _generate_stream(
        self,
        model: str,
        prompt: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """流式文本生成（聚合所有 chunk 后返回完整结果）.

        注：当前实现以聚合方式模拟非流式接口返回，
        未来可扩展为真正的异步生成器。

        Args:
            model: 模型名称.
            prompt: 提示文本.
            system: 系统提示词.
            max_tokens: 最大 token 数.
            temperature: 采样温度.

        Returns:
            生成结果字典.
        """
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            payload["system"] = system

        if self._session is None:
            await self.start()

        assert self._session is not None

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                full_text_parts: list[str] = []
                final_data: dict[str, Any] = {}

                async with self._session.post("/api/generate", json=payload) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        raise InferenceError(
                            message=f"Ollama generate error: status={resp.status}",
                            error_code=f"OLLAMA_{resp.status}",
                            context={"status": resp.status, "body": body},
                        )

                    async for line in resp.content:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = __import__("json").loads(line)
                        except Exception:
                            continue

                        if "response" in chunk:
                            full_text_parts.append(chunk["response"])

                        if chunk.get("done", False):
                            final_data = chunk

                usage = self._extract_ollama_usage(final_data)
                return {
                    "text": "".join(full_text_parts),
                    "model": final_data.get("model", model),
                    "usage": usage,
                }

            except InferenceError:
                raise
            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = min(
                        RETRY_BASE_DELAY_S * (RETRY_BACKOFF_FACTOR ** attempt),
                        RETRY_MAX_DELAY_S,
                    )
                    logger.warning(
                        "local_executor.stream_retry",
                        attempt=attempt + 1,
                        delay_s=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                break

        raise InferenceError(
            message=f"Ollama stream generate failed after {self._max_retries} retries: {last_error}",
            error_code="OLLAMA_STREAM_RETRY_EXHAUSTED",
            context={"last_error": str(last_error)},
        ) from last_error

    # ------------------------------------------------------------------
    # 内部方法：对话非流式
    # ------------------------------------------------------------------

    async def _chat_non_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """非流式对话生成（带指数退避重试）.

        Args:
            model: 模型名称.
            messages: 对话消息列表.
            max_tokens: 最大 token 数.
            temperature: 采样温度.

        Returns:
            生成结果字典.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        data = await self._request_with_retry("POST", "/api/chat", payload)

        # 提取助手消息
        message = data.get("message", {})
        text = message.get("content", "") if isinstance(message, dict) else ""

        usage = self._extract_ollama_usage(data)
        return {
            "text": text,
            "model": data.get("model", model),
            "usage": usage,
        }

    # ------------------------------------------------------------------
    # 内部方法：带重试的请求
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """带指数退避重试的 HTTP 请求.

        对网络错误和 5xx 重试，对 4xx 不重试。

        Args:
            method: HTTP 方法.
            path: API 路径.
            payload: 请求体 JSON.

        Returns:
            响应 JSON 字典.

        Raises:
            InferenceError: 请求最终失败.
        """
        if self._session is None:
            await self.start()

        assert self._session is not None
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                async with self._session.request(method, path, json=payload) as resp:
                    data = await resp.json()

                    if resp.status >= 400:
                        # 4xx 错误不重试
                        if resp.status < 500:
                            raise InferenceError(
                                message=f"Ollama API error: status={resp.status}",
                                error_code=f"OLLAMA_{resp.status}",
                                context={"status": resp.status, "body": data},
                            )

                        # 5xx 可重试
                        if attempt >= self._max_retries:
                            raise InferenceError(
                                message=f"Ollama API error: status={resp.status}",
                                error_code=f"OLLAMA_{resp.status}",
                                context={"status": resp.status, "body": data},
                            )

                        last_error = InferenceError(
                            message=f"Ollama API error: status={resp.status}",
                            error_code=f"OLLAMA_{resp.status}",
                            context={"status": resp.status, "body": data},
                        )
                    else:
                        return data

            except InferenceError:
                raise
            except Exception as e:
                last_error = e

            # 指数退避
            if attempt < self._max_retries:
                delay = min(
                    RETRY_BASE_DELAY_S * (RETRY_BACKOFF_FACTOR ** attempt),
                    RETRY_MAX_DELAY_S,
                )
                logger.warning(
                    "local_executor.retry",
                    method=method,
                    path=path,
                    attempt=attempt + 1,
                    delay_s=delay,
                    error=str(last_error),
                )
                await asyncio.sleep(delay)

        raise InferenceError(
            message=f"Ollama request failed after {self._max_retries} retries: {last_error}",
            error_code="OLLAMA_RETRY_EXHAUSTED",
            context={"last_error": str(last_error)},
        ) from last_error

    # ------------------------------------------------------------------
    # 内部方法：显存检查
    # ------------------------------------------------------------------

    def _check_vram_before_inference(self, model: str) -> None:
        """推理前显存检查.

        若配置了 VRAMMonitor，则检查当前显存状态：
        - CRITICAL 水位：直接抛出 VRAMOverflowError
        - WARNING 水位 + 大模型：抛出 VRAMOverflowError（建议用小模型或云端）
        - 保留显存不足 min_vram_safe_ratio：抛出 VRAMOverflowError

        Args:
            model: 模型名称.

        Raises:
            VRAMOverflowError: 显存不足.
        """
        if self._vram_monitor is None:
            return

        monitor = self._vram_monitor
        report = monitor.current_report

        # GPU 不可用时跳过检查（允许 CPU 推理）
        if report.total_mb == 0.0:
            return

        # CRITICAL 水位直接拒绝
        if report.level == VRAMLevel.CRITICAL:
            raise VRAMOverflowError(
                message=f"VRAM is critical ({report.usage_ratio:.1%}), local inference rejected",
                error_code="VRAM_CRITICAL_REJECT",
                required_mb=MODEL_VRAM_ESTIMATE_MB.get(model, 0.0),
                available_mb=report.free_mb,
            )

        # 检查保留显存比例
        free_ratio = report.free_mb / report.total_mb if report.total_mb > 0 else 0.0
        if free_ratio < self._min_vram_safe_ratio:
            raise VRAMOverflowError(
                message=(
                    f"Free VRAM ratio {free_ratio:.1%} is below "
                    f"safe threshold {self._min_vram_safe_ratio:.1%}"
                ),
                error_code="VRAM_SAFE_RATIO_VIOLATION",
                required_mb=MODEL_VRAM_ESTIMATE_MB.get(model, 0.0),
                available_mb=report.free_mb,
            )

        # WARNING 水位且模型较大时拒绝
        estimated_mb = MODEL_VRAM_ESTIMATE_MB.get(model, 3000.0)
        if report.level == VRAMLevel.WARNING and estimated_mb > 4000.0:
            raise VRAMOverflowError(
                message=(
                    f"VRAM is warning ({report.usage_ratio:.1%}), "
                    f"large model '{model}' may cause OOM, try smaller model or cloud"
                ),
                error_code="VRAM_WARNING_LARGE_MODEL",
                required_mb=estimated_mb,
                available_mb=report.free_mb,
            )

    # ------------------------------------------------------------------
    # 内部方法：工具函数
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_ollama_usage(data: dict[str, Any]) -> dict[str, int]:
        """从 Ollama 响应中提取 token 使用信息.

        Args:
            data: Ollama 响应 JSON.

        Returns:
            含 prompt_tokens / completion_tokens / total_tokens 的字典.
        """
        return {
            "prompt_tokens": int(data.get("prompt_eval_count", 0)),
            "completion_tokens": int(data.get("eval_count", 0)),
            "total_tokens": int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0)),
        }

    def _get_vram_usage(self) -> float | None:
        """获取当前显存使用率.

        Returns:
            显存使用率 0.0-1.0，无监控器时返回 None.
        """
        if self._vram_monitor is None:
            return None
        try:
            return self._vram_monitor.usage_ratio
        except Exception:
            return None

    async def _log_call(
        self,
        model: str,
        target: str,
        status: str,
        latency_ms: float,
        usage: dict[str, int],
        agent_id: str = "",
        error_message: str | None = None,
        vram_before: float | None = None,
        vram_after: float | None = None,
    ) -> None:
        """记录调用日志.

        Args:
            model: 模型名称.
            target: 路由目标.
            status: 调用状态.
            latency_ms: 延迟（毫秒）.
            usage: token 使用统计.
            agent_id: 调用方 Agent.
            error_message: 错误信息.
            vram_before: 调用前显存率.
            vram_after: 调用后显存率.
        """
        if self._call_logger is None:
            return

        try:
            record = CallLogRecord(
                log_id=f"local_{int(time.time()*1000)}_{__import__('uuid').uuid4().hex[:8]}",
                task_id=agent_id,
                agent_name=agent_id,
                target=target,
                provider_name="ollama",
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=round(latency_ms, 2),
                status=status,
                error_message=error_message,
                vram_usage_before=vram_before,
                vram_usage_after=vram_after,
            )
            await self._call_logger.write(record)
        except Exception:
            logger.exception("local_executor.log_call_failed")
