"""云端推理执行器.

对接兼容 OpenAI 格式的云端 LLM API（支持 DeepSeek、通义千问、GPT 等），
通过 CloudGateway 进行限流熔断保护。
支持多 Provider 配置，按优先级选择可用服务。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from edge_cloud_kernel.models.call_log import CallLogRecord
from edge_cloud_kernel.models.exceptions import InferenceError, ProviderError

logger = structlog.get_logger(__name__)

# 默认配置
DEFAULT_TIMEOUT: float = 30.0
DEFAULT_MAX_RETRIES: int = 2

# 流式响应处理中聚合的最大 chunk 数上限（保护）
MAX_STREAM_CHUNKS: int = 100_000


class CloudInferenceExecutor:
    """云端推理执行器.

    管理多个云端 LLM Provider，通过 CloudGateway 进行统一的
    限流、熔断和重试管理。支持按优先级选择 Provider。

    Attributes:
        _providers: Provider 配置列表 [{name, base_url, api_key, default_model, priority, enabled}].
        _timeout: 请求超时时间（秒）.
        _max_retries: 最大重试次数.
        _cloud_gateway: CloudGateway 实例（用于限流熔断）.
        _call_logger: CallLogWriter 实例（用于调用日志）.
        _provider_sessions: 按 provider name 缓存的 aiohttp session 字典（按需创建）.
        _closed: 是否已关闭.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        cloud_gateway: Any = None,
        call_logger: Any = None,
    ) -> None:
        """初始化 CloudInferenceExecutor.

        Args:
            config: 配置字典，支持 providers / timeout / max_retries.
                providers 为列表，每项含 name / base_url / api_key /
                default_model / priority / enabled.
            cloud_gateway: CloudGateway 实例，用于限流熔断.
            call_logger: CallLogWriter 实例，用于记录调用日志.
        """
        cfg = config or {}
        self._providers: list[dict[str, Any]] = list(cfg.get("providers", []))
        self._timeout: float = float(cfg.get("timeout", DEFAULT_TIMEOUT))
        self._max_retries: int = int(cfg.get("max_retries", DEFAULT_MAX_RETRIES))
        self._cloud_gateway = cloud_gateway
        self._call_logger = call_logger
        self._closed = False

        # 按优先级排序（数值越小优先级越高）
        self._providers.sort(key=lambda p: p.get("priority", 100))

        logger.info(
            "cloud_executor.init",
            providers_count=len(self._providers),
            provider_names=[p.get("name", "") for p in self._providers],
            timeout=self._timeout,
            max_retries=self._max_retries,
            has_cloud_gateway=cloud_gateway is not None,
            has_call_logger=call_logger is not None,
        )

    async def close(self) -> None:
        """关闭执行器，释放资源."""
        if not self._closed:
            self._closed = True
            logger.info("cloud_executor.closed")

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
        provider: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """文本生成（补全模式）.

        调用云端 /v1/completions 接口。若指定 provider 则使用该 provider，
        否则按优先级顺序尝试可用的 provider。

        Args:
            model: 模型名称，为空时使用 provider 的默认模型.
            prompt: 输入提示文本.
            system: 系统提示词（通过 messages 方式注入）.
            max_tokens: 最大生成 token 数.
            temperature: 采样温度.
            provider: 指定 Provider 名称，为空时自动选择.
            agent_id: 调用方 Agent 标识.

        Returns:
            包含 text / model / usage / latency_ms / provider 的字典.

        Raises:
            InferenceError: 所有 Provider 均不可用或推理失败.
        """
        start_time = time.perf_counter()
        last_error: Exception | None = None

        # 获取候选 provider 列表
        candidates = self._get_candidate_providers(provider)
        if not candidates:
            raise InferenceError(
                message="No available cloud providers",
                error_code="NO_AVAILABLE_PROVIDER",
                context={"requested_provider": provider},
            )

        # 按优先级尝试每个 provider
        for prov in candidates:
            prov_name = prov.get("name", "unknown")
            try:
                result = await self._generate_with_provider(
                    provider_cfg=prov,
                    model=model,
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                latency_ms = (time.perf_counter() - start_time) * 1000
                result["latency_ms"] = round(latency_ms, 2)
                result["provider"] = prov_name

                # 记录调用日志
                await self._log_call(
                    model=result.get("model", model or ""),
                    provider=prov_name,
                    target="cloud",
                    status="success",
                    latency_ms=latency_ms,
                    usage=result.get("usage", {}),
                    agent_id=agent_id or "",
                )

                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    "cloud_executor.provider_failed",
                    provider=prov_name,
                    error=str(e),
                )
                continue

        # 所有 provider 都失败
        latency_ms = (time.perf_counter() - start_time) * 1000
        await self._log_call(
            model=model or "",
            provider=provider or "",
            target="cloud",
            status="failed",
            latency_ms=latency_ms,
            usage={},
            agent_id=agent_id or "",
            error_message=str(last_error) if last_error else "all providers failed",
        )

        raise InferenceError(
            message=f"All cloud providers failed: {last_error}",
            error_code="ALL_PROVIDERS_FAILED",
            context={"last_error": str(last_error) if last_error else ""},
        ) from last_error

    async def chat(
        self,
        model: str | None = None,
        messages: list[dict[str, str]] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        provider: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """对话式推理（Chat Completion 模式）.

        调用云端 /v1/chat/completions 接口。

        Args:
            model: 模型名称，为空时使用 provider 的默认模型.
            messages: 对话消息列表，每项含 role 和 content.
            max_tokens: 最大生成 token 数.
            temperature: 采样温度.
            provider: 指定 Provider 名称，为空时自动选择.
            agent_id: 调用方 Agent 标识.

        Returns:
            包含 text / model / usage / latency_ms / provider 的字典.

        Raises:
            InferenceError: 所有 Provider 均不可用或推理失败.
        """
        start_time = time.perf_counter()
        last_error: Exception | None = None
        msgs = messages or []

        candidates = self._get_candidate_providers(provider)
        if not candidates:
            raise InferenceError(
                message="No available cloud providers",
                error_code="NO_AVAILABLE_PROVIDER",
                context={"requested_provider": provider},
            )

        for prov in candidates:
            prov_name = prov.get("name", "unknown")
            try:
                result = await self._chat_with_provider(
                    provider_cfg=prov,
                    model=model,
                    messages=msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                latency_ms = (time.perf_counter() - start_time) * 1000
                result["latency_ms"] = round(latency_ms, 2)
                result["provider"] = prov_name

                await self._log_call(
                    model=result.get("model", model or ""),
                    provider=prov_name,
                    target="cloud",
                    status="success",
                    latency_ms=latency_ms,
                    usage=result.get("usage", {}),
                    agent_id=agent_id or "",
                )

                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    "cloud_executor.provider_chat_failed",
                    provider=prov_name,
                    error=str(e),
                )
                continue

        latency_ms = (time.perf_counter() - start_time) * 1000
        await self._log_call(
            model=model or "",
            provider=provider or "",
            target="cloud",
            status="failed",
            latency_ms=latency_ms,
            usage={},
            agent_id=agent_id or "",
            error_message=str(last_error) if last_error else "all providers failed",
        )

        raise InferenceError(
            message=f"All cloud providers failed: {last_error}",
            error_code="ALL_PROVIDERS_FAILED",
            context={"last_error": str(last_error) if last_error else ""},
        ) from last_error

    async def health_check(self) -> dict[str, Any]:
        """健康检查.

        检查所有已启用 Provider 的健康状态。

        Returns:
            健康检查结果字典，含总体状态和各 provider 状态.
        """
        result: dict[str, Any] = {
            "status": "unknown",
            "providers_count": len(self._providers),
            "healthy_count": 0,
            "providers": {},
        }

        import aiohttp

        healthy = 0
        for prov in self._providers:
            if not prov.get("enabled", True):
                result["providers"][prov.get("name", "unknown")] = {
                    "status": "disabled",
                }
                continue

            prov_name = prov.get("name", "unknown")
            base_url = prov.get("base_url", "").rstrip("/")
            api_key = prov.get("api_key", "")

            try:
                timeout = aiohttp.ClientTimeout(total=5.0)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                    async with session.get(f"{base_url}/v1/models", headers=headers) as resp:
                        if resp.status == 200:
                            result["providers"][prov_name] = {"status": "healthy"}
                            healthy += 1
                        else:
                            result["providers"][prov_name] = {
                                "status": "unhealthy",
                                "status_code": resp.status,
                            }
            except Exception as e:
                result["providers"][prov_name] = {
                    "status": "unreachable",
                    "error": str(e),
                }

        result["healthy_count"] = healthy
        if healthy > 0:
            result["status"] = "healthy" if healthy == len(self._enabled_providers()) else "degraded"
        else:
            result["status"] = "unhealthy"

        return result

    def list_providers(self) -> list[dict[str, Any]]:
        """列出所有已配置的 Provider.

        Returns:
            Provider 配置列表（不含 api_key 等敏感字段）.
        """
        result: list[dict[str, Any]] = []
        for prov in self._providers:
            result.append({
                "name": prov.get("name", ""),
                "base_url": prov.get("base_url", ""),
                "default_model": prov.get("default_model", ""),
                "priority": prov.get("priority", 100),
                "enabled": prov.get("enabled", True),
            })
        return result

    # ------------------------------------------------------------------
    # 内部方法：Provider 选择
    # ------------------------------------------------------------------

    def _get_candidate_providers(self, provider: str | None = None) -> list[dict[str, Any]]:
        """获取候选 Provider 列表.

        若指定了 provider 名称，返回匹配的已启用 provider；
        否则返回所有已启用的 provider（按优先级排序）。

        Args:
            provider: 指定的 Provider 名称.

        Returns:
            候选 Provider 配置列表.
        """
        if provider:
            for prov in self._providers:
                if prov.get("name") == provider and prov.get("enabled", True):
                    return [prov]
            return []

        return [p for p in self._providers if p.get("enabled", True)]

    def _enabled_providers(self) -> list[dict[str, Any]]:
        """获取所有已启用的 Provider."""
        return [p for p in self._providers if p.get("enabled", True)]

    # ------------------------------------------------------------------
    # 内部方法：Completions API
    # ------------------------------------------------------------------

    async def _generate_with_provider(
        self,
        provider_cfg: dict[str, Any],
        model: str | None,
        prompt: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """使用指定 Provider 执行文本生成.

        优先使用 CloudGateway 发送请求（带熔断限流），
        若未配置 CloudGateway 则直接使用 aiohttp。

        Args:
            provider_cfg: Provider 配置字典.
            model: 模型名称.
            prompt: 提示文本.
            system: 系统提示词.
            max_tokens: 最大 token 数.
            temperature: 采样温度.

        Returns:
            生成结果字典.
        """
        model_name = model or provider_cfg.get("default_model", "")
        if not model_name:
            raise ProviderError(
                message="No model specified and no default model for provider",
                error_code="NO_MODEL_SPECIFIED",
                provider_name=provider_cfg.get("name", ""),
            )

        # 构造 messages 形式（系统提示 + 用户提示）
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        return await self._chat_completion_request(
            provider_cfg=provider_cfg,
            payload=payload,
        )

    # ------------------------------------------------------------------
    # 内部方法：Chat Completions API
    # ------------------------------------------------------------------

    async def _chat_with_provider(
        self,
        provider_cfg: dict[str, Any],
        model: str | None,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """使用指定 Provider 执行对话生成.

        Args:
            provider_cfg: Provider 配置字典.
            model: 模型名称.
            messages: 对话消息列表.
            max_tokens: 最大 token 数.
            temperature: 采样温度.

        Returns:
            生成结果字典.
        """
        model_name = model or provider_cfg.get("default_model", "")
        if not model_name:
            raise ProviderError(
                message="No model specified and no default model for provider",
                error_code="NO_MODEL_SPECIFIED",
                provider_name=provider_cfg.get("name", ""),
            )

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        return await self._chat_completion_request(
            provider_cfg=provider_cfg,
            payload=payload,
        )

    # ------------------------------------------------------------------
    # 内部方法：统一的 Chat Completion 请求
    # ------------------------------------------------------------------

    async def _chat_completion_request(
        self,
        provider_cfg: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """发送 Chat Completion 请求.

        若配置了 CloudGateway，则通过 gateway 发送（带熔断限流重试）；
        否则直接使用 aiohttp 发送。

        Args:
            provider_cfg: Provider 配置.
            payload: 请求体.

        Returns:
            标准化的结果字典.

        Raises:
            ProviderError: 请求失败.
        """
        prov_name = provider_cfg.get("name", "unknown")
        base_url = provider_cfg.get("base_url", "").rstrip("/")
        api_key = provider_cfg.get("api_key", "")
        path = "/v1/chat/completions"

        # 通过 CloudGateway 发送请求
        if self._cloud_gateway is not None:
            return await self._request_via_gateway(
                provider_cfg=provider_cfg,
                path=path,
                payload=payload,
            )

        # 直接使用 aiohttp
        return await self._request_direct(
            base_url=base_url,
            api_key=api_key,
            path=path,
            payload=payload,
            provider_name=prov_name,
        )

    async def _request_via_gateway(
        self,
        provider_cfg: dict[str, Any],
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """通过 CloudGateway 发送请求.

        动态为每个 Provider 维护独立的 gateway session（复用单例 gateway 的逻辑）。
        当前实现：使用 provider 的 base_url 和 api_key 临时构造请求，
        利用 gateway 的熔断和重试能力。

        Args:
            provider_cfg: Provider 配置.
            path: API 路径.
            payload: 请求体.

        Returns:
            标准化结果字典.
        """
        import aiohttp

        prov_name = provider_cfg.get("name", "unknown")
        base_url = provider_cfg.get("base_url", "").rstrip("/")
        api_key = provider_cfg.get("api_key", "")
        service_name = f"cloud_{prov_name}"

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self._timeout)
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }

                # 检查熔断器状态
                cb = None
                if self._cloud_gateway is not None and hasattr(self._cloud_gateway, "get_circuit_breaker"):
                    cb = self._cloud_gateway.get_circuit_breaker(service_name)
                    if not cb.allow_request():
                        raise ProviderError(
                            message=f"Circuit breaker open for provider '{prov_name}'",
                            error_code="CIRCUIT_OPEN",
                            provider_name=prov_name,
                        )

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"{base_url}{path}",
                        json=payload,
                        headers=headers,
                    ) as resp:
                        data = await resp.json()

                        if resp.status >= 400:
                            # 记录熔断失败
                            if cb is not None:
                                cb.record_failure(0.0, error_type=f"http_{resp.status}")

                            # 4xx 不重试（除了 429）
                            if resp.status < 500 and resp.status != 429:
                                raise ProviderError(
                                    message=f"Cloud API error: status={resp.status}",
                                    error_code=f"CLOUD_API_{resp.status}",
                                    provider_name=prov_name,
                                    status_code=resp.status,
                                    context={"body": data},
                                )

                            # 可重试错误
                            if attempt >= self._max_retries:
                                raise ProviderError(
                                    message=f"Cloud API error: status={resp.status}",
                                    error_code=f"CLOUD_API_{resp.status}",
                                    provider_name=prov_name,
                                    status_code=resp.status,
                                    context={"body": data},
                                )

                            last_error = ProviderError(
                                message=f"Cloud API error: status={resp.status}",
                                error_code=f"CLOUD_API_{resp.status}",
                                provider_name=prov_name,
                                status_code=resp.status,
                                context={"body": data},
                            )
                        else:
                            # 成功，记录熔断成功
                            if cb is not None:
                                cb.record_success(0.0)

                            return self._parse_chat_response(data)

            except ProviderError:
                raise
            except Exception as e:
                last_error = e

            # 指数退避
            if attempt < self._max_retries:
                delay = min(1.0 * (2 ** attempt), 30.0)
                logger.warning(
                    "cloud_executor.retry",
                    provider=prov_name,
                    attempt=attempt + 1,
                    delay_s=delay,
                    error=str(last_error),
                )
                import asyncio
                await asyncio.sleep(delay)

        raise ProviderError(
            message=f"Cloud request failed after {self._max_retries} retries: {last_error}",
            error_code="CLOUD_RETRY_EXHAUSTED",
            provider_name=prov_name,
            context={"last_error": str(last_error)},
        ) from last_error

    async def _request_direct(
        self,
        base_url: str,
        api_key: str,
        path: str,
        payload: dict[str, Any],
        provider_name: str,
    ) -> dict[str, Any]:
        """直接使用 aiohttp 发送请求（无 CloudGateway 时）.

        Args:
            base_url: API 基础 URL.
            api_key: API 密钥.
            path: API 路径.
            payload: 请求体.
            provider_name: Provider 名称.

        Returns:
            标准化结果字典.
        """
        import aiohttp

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self._timeout)
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"{base_url}{path}",
                        json=payload,
                        headers=headers,
                    ) as resp:
                        data = await resp.json()

                        if resp.status >= 400:
                            if resp.status < 500 and resp.status != 429:
                                raise ProviderError(
                                    message=f"Cloud API error: status={resp.status}",
                                    error_code=f"CLOUD_API_{resp.status}",
                                    provider_name=provider_name,
                                    status_code=resp.status,
                                    context={"body": data},
                                )

                            if attempt >= self._max_retries:
                                raise ProviderError(
                                    message=f"Cloud API error: status={resp.status}",
                                    error_code=f"CLOUD_API_{resp.status}",
                                    provider_name=provider_name,
                                    status_code=resp.status,
                                    context={"body": data},
                                )

                            last_error = ProviderError(
                                message=f"Cloud API error: status={resp.status}",
                                error_code=f"CLOUD_API_{resp.status}",
                                provider_name=provider_name,
                                status_code=resp.status,
                                context={"body": data},
                            )
                        else:
                            return self._parse_chat_response(data)

            except ProviderError:
                raise
            except Exception as e:
                last_error = e

            if attempt < self._max_retries:
                delay = min(1.0 * (2 ** attempt), 30.0)
                logger.warning(
                    "cloud_executor.direct_retry",
                    provider=provider_name,
                    attempt=attempt + 1,
                    delay_s=delay,
                    error=str(last_error),
                )
                import asyncio
                await asyncio.sleep(delay)

        raise ProviderError(
            message=f"Cloud request failed after {self._max_retries} retries: {last_error}",
            error_code="CLOUD_RETRY_EXHAUSTED",
            provider_name=provider_name,
            context={"last_error": str(last_error)},
        ) from last_error

    # ------------------------------------------------------------------
    # 内部方法：响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_chat_response(data: dict[str, Any]) -> dict[str, Any]:
        """解析 OpenAI 格式的 Chat Completion 响应.

        Args:
            data: 原始响应 JSON.

        Returns:
            标准化的 {text, model, usage} 字典.
        """
        choices = data.get("choices", [])
        text = ""
        if choices:
            msg = choices[0].get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "")

        usage_raw = data.get("usage", {}) or {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
            "completion_tokens": int(usage_raw.get("completion_tokens", 0)),
            "total_tokens": int(usage_raw.get("total_tokens", 0)),
        }

        return {
            "text": text,
            "model": data.get("model", ""),
            "usage": usage,
        }

    # ------------------------------------------------------------------
    # 内部方法：成本估算（可选）
    # ------------------------------------------------------------------

    def estimate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        provider: str | None = None,
    ) -> float:
        """估算调用成本（美元）.

        基于各 Provider 的定价粗略估算。返回 0.0 表示无定价信息。

        Args:
            model: 模型名称.
            prompt_tokens: 输入 token 数.
            completion_tokens: 输出 token 数.
            provider: 指定 Provider，为空时取第一个已启用的.

        Returns:
            估算成本（美元）.
        """
        # 粗略定价表（每 1M token 的美元价格）
        # 仅作示例，实际应从配置读取
        pricing_table: dict[str, dict[str, tuple[float, float]]] = {
            "deepseek": {
                "deepseek-chat": (0.14, 0.28),  # (input per 1M, output per 1M)
                "deepseek-coder": (0.14, 0.28),
            },
            "openai": {
                "gpt-4o": (5.0, 15.0),
                "gpt-4o-mini": (0.15, 0.6),
                "gpt-3.5-turbo": (0.5, 1.5),
            },
            "qwen": {
                "qwen-turbo": (0.3, 0.6),
                "qwen-plus": (0.8, 2.0),
                "qwen-max": (2.4, 9.6),
            },
        }

        prov_name = provider
        if prov_name is None:
            enabled = self._enabled_providers()
            if enabled:
                prov_name = enabled[0].get("name", "")

        if not prov_name or not model:
            return 0.0

        prov_pricing = pricing_table.get(prov_name.lower(), {})
        # 模糊匹配模型名
        price: tuple[float, float] | None = None
        for model_key, p in prov_pricing.items():
            if model_key in model.lower():
                price = p
                break

        if price is None:
            return 0.0

        input_cost = (prompt_tokens / 1_000_000) * price[0]
        output_cost = (completion_tokens / 1_000_000) * price[1]
        return round(input_cost + output_cost, 6)

    # ------------------------------------------------------------------
    # 内部方法：调用日志
    # ------------------------------------------------------------------

    async def _log_call(
        self,
        model: str,
        provider: str,
        target: str,
        status: str,
        latency_ms: float,
        usage: dict[str, int],
        agent_id: str = "",
        error_message: str | None = None,
    ) -> None:
        """记录调用日志.

        Args:
            model: 模型名称.
            provider: Provider 名称.
            target: 路由目标.
            status: 调用状态.
            latency_ms: 延迟（毫秒）.
            usage: token 使用统计.
            agent_id: 调用方 Agent.
            error_message: 错误信息.
        """
        if self._call_logger is None:
            return

        try:
            import uuid
            record = CallLogRecord(
                log_id=f"cloud_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}",
                task_id=agent_id,
                agent_name=agent_id,
                target=target,
                provider_name=provider,
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=round(latency_ms, 2),
                status=status,
                error_message=error_message,
            )
            await self._call_logger.write(record)
        except Exception:
            logger.exception("cloud_executor.log_call_failed")
