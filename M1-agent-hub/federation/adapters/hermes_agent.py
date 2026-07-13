"""
Hermes Agent 适配器 — HermesAgentAdapter

双算力模式的 ReAct 风格 Agent，支持本地 Ollama 模型和云端 API 调用，
通过 HTTP 调用 M2 的 MCP 端点获取工具列表并执行工具调用。

架构设计：
  - 本地模式：Ollama 本地部署模型（零成本、数据本地、隐私保护）
  - API 模式：OpenAI/Anthropic/DeepSeek 等云端 API（更强能力、按需付费）
  - 工具系统：通过 HTTP 协议调用 M2 模块暴露的 MCP 端点
  - 推理循环：ReAct 模式（思考 → 行动 → 观察 → 回答）

使用示例：
    # 本地模式（默认）
    adapter = HermesAgentAdapter(
        agent_id="hermes_agent_01",
        display_name="Hermes 智能助手",
        config={
            "mode": "local",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:7b",
            "mcp_server_url": "http://localhost:8002/mcp",
            "max_iterations": 5,
        },
    )

    # API 模式
    adapter = HermesAgentAdapter(
        agent_id="hermes_agent_01",
        display_name="Hermes 智能助手",
        config={
            "mode": "api",
            "api_provider": "openai",
            "api_base_url": "https://api.openai.com/v1",
            "api_model": "gpt-4o",
            "api_key": "sk-xxxx",
            "mcp_server_url": "http://localhost:8002/mcp",
            "max_iterations": 5,
        },
    )

    result = await adapter.invoke("帮我查询系统状态")
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog

from federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────────────

def _default_api_cost_model(provider: str) -> dict[str, Any]:
    """根据 API 服务商返回默认成本模型

    Args:
        provider: API 服务商名称

    Returns:
        成本模型字典
    """
    # 价格参考（2024 年公开定价，单位：美元 / 1K tokens）
    _COST_TABLE: dict[str, dict[str, Any]] = {
        "openai": {
            "input_per_1k": 0.005,    # GPT-4o 输入
            "output_per_1k": 0.015,   # GPT-4o 输出
            "currency": "USD",
        },
        "anthropic": {
            "input_per_1k": 0.003,    # Claude 3.5 Sonnet 输入
            "output_per_1k": 0.015,   # Claude 3.5 Sonnet 输出
            "currency": "USD",
        },
        "deepseek": {
            "input_per_1k": 0.00014,  # DeepSeek-V3 输入
            "output_per_1k": 0.00028, # DeepSeek-V3 输出
            "currency": "USD",
        },
        "moonshot": {
            "input_per_1k": 0.00003,  # Moonshot-v1-8k 输入
            "output_per_1k": 0.00006, # Moonshot-v1-8k 输出
            "currency": "USD",
        },
        "qwen": {
            "input_per_1k": 0.00002,  # Qwen2.5-72B 输入
            "output_per_1k": 0.00006, # Qwen2.5-72B 输出
            "currency": "USD",
        },
        "custom": {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "USD",
        },
    }
    return _COST_TABLE.get(provider, _COST_TABLE["custom"])


class HermesAgentAdapter(AgentAdapterBase):
    """Hermes Agent 适配器

    双算力模式的 ReAct 风格 Agent，支持本地 Ollama 模型和云端 API 调用。
    核心能力：
      1. 本地模式：通过 Ollama API 调用本地模型进行推理（零成本、数据本地）
      2. API 模式：调用 OpenAI/Anthropic/DeepSeek 等云端 API 进行推理
      3. 通过 HTTP 调用 M2 的 MCP 端点获取可用工具并执行工具调用
      4. 实现 ReAct 推理循环：思考（Thought）→ 行动（Action）→ 观察（Observation）→ 回答（Answer）
    """

    # 适配器元信息
    provider: str = "Hermes"
    adapter_type: str = "hermes_agent"

    # ── ReAct 提示词模板 ────────────────────────────────────────────────

    # 本地模式系统提示词：适配本地模型能力，强调格式规范
    _SYSTEM_PROMPT_TEMPLATE_LOCAL: str = """你是 Hermes，一个基于 ReAct 模式的智能助手。
你可以使用以下工具来帮助回答用户问题：

{tools_description}

## 工作流程

你必须严格按照以下格式进行思考和行动（ReAct 模式）：

1. **Thought**：分析用户问题，思考应该使用哪个工具，以及如何使用。
2. **Action**：调用工具，格式为：
   ```
   Action: tool_name
   Action Input: {{"param1": "value1", "param2": "value2"}}
   ```
3. **Observation**：工具执行结果（由系统提供，你不需要生成这一步）。
4. 重复上述步骤，直到你认为已经收集到足够的信息。
5. **Final Answer**：给出最终回答，格式为：
   ```
   Final Answer: [你的完整回答]
   ```

## 重要规则

- 每次只调用一个工具，不要同时调用多个工具。
- 如果你已经知道答案或者不需要工具，可以直接给出 Final Answer。
- 严格按照格式输出，确保 Action 和 Final Answer 的标记清晰可解析。
- 用中文进行思考和回答。
- 你最多可以进行 {max_iterations} 轮工具调用，请高效利用每一次机会。
"""

    # API 模式系统提示词：语气更专业，推理更高效
    _SYSTEM_PROMPT_TEMPLATE_API: str = """你是 Hermes，一位专业的智能助手。你可以使用以下工具来帮助回答用户问题：

{tools_description}

## 工作方式（ReAct 模式）

请遵循以下推理流程：

1. **Thought**：分析用户问题，确定是否需要使用工具，以及使用哪个工具。
2. **Action**：如需调用工具，请严格按以下格式输出：
   ```
   Action: tool_name
   Action Input: {{"param1": "value1", "param2": "value2"}}
   ```
3. **Observation**：工具执行结果将由系统提供给你。
4. 重复以上步骤，直到收集到足够信息。
5. **Final Answer**：给出最终回答，格式为：
   ```
   Final Answer: [你的完整回答]
   ```

## 重要规则

- 每次只调用一个工具。
- 不需要工具时直接给出 Final Answer，不要无意义地调用工具。
- 输出格式必须准确，确保 Action 和 Final Answer 标记清晰可解析。
- 用中文回答。
- 最多可进行 {max_iterations} 轮工具调用。
"""

    def __init__(
        self,
        agent_id: str = "hermes_agent_01",
        display_name: str = "Hermes 智能助手",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化 Hermes Agent 适配器

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典，支持以下键：
                - mode: 运行模式，"local" 或 "api"（默认 "local"）
                - ollama_base_url: Ollama 服务地址（本地模式，默认 http://localhost:11434）
                - model_name: 模型名称（本地模式，默认 qwen2.5:7b）
                - api_provider: API 服务商（api 模式），如 openai/anthropic/deepseek/moonshot/qwen/custom
                - api_base_url: API 基础 URL（api 模式）
                - api_model: API 模型名称（api 模式）
                - api_key: API 密钥（api 模式）
                - api_format: API 格式，"openai_compatible" 或 "anthropic_native"（默认根据 provider 推断）
                - mcp_server_url: MCP 服务器地址（M2 模块的 MCP 端点）
                - max_iterations: 最大 ReAct 迭代次数（默认 5）
                - temperature: 生成温度（默认 0.7）
            **kwargs: 传递给基类的额外参数（timeout, max_retries 等）
        """
        config = config or {}

        # 运行模式（默认 local，保持向后兼容）
        mode = config.get("mode", "local")
        if mode not in ("local", "api"):
            raise ValueError(f"不支持的模式: {mode}，请使用 'local' 或 'api'")
        config.setdefault("mode", mode)

        # 通用默认配置
        config.setdefault("mcp_server_url", "http://localhost:8002/mcp")
        config.setdefault("max_iterations", 5)
        config.setdefault("temperature", 0.7)

        # M8 管理令牌（用于 MCP 调用鉴权）
        config.setdefault("m8_token", "")

        if mode == "local":
            # ── 本地模式默认配置 ──
            config.setdefault("ollama_base_url", "http://localhost:11434")
            config.setdefault("model_name", "qwen2.5:7b")
            config.setdefault("cost_model", {
                "input_per_1k": 0.0,
                "output_per_1k": 0.0,
                "currency": "USD",
            })
        else:
            # ── API 模式默认配置 ──
            config.setdefault("api_provider", "openai")
            config.setdefault("api_base_url", "https://api.openai.com/v1")
            config.setdefault("api_model", "gpt-4o")
            config.setdefault("api_key", "")

            # API 格式：根据 provider 推断，也可显式配置
            api_provider = config.get("api_provider", "openai")
            if api_provider == "anthropic":
                default_format = "anthropic_native"
            else:
                default_format = "openai_compatible"
            config.setdefault("api_format", default_format)

            # model_name 兼容字段（统一用 model_name 访问模型名）
            config.setdefault("model_name", config["api_model"])

            # 默认成本模型（可通过配置覆盖）
            config.setdefault("cost_model", _default_api_cost_model(api_provider))

        super().__init__(agent_id, display_name, config, **kwargs)

        self._mode = mode

        # 缓存 MCP 工具列表（首次调用时懒加载）
        self._mcp_tools: list[dict[str, Any]] | None = None

        # HTTP 客户端（延迟创建，避免在事件循环外创建）
        self._http_client: httpx.AsyncClient | None = None

        # 绑定日志上下文
        log_bind = {
            "mode": mode,
            "model": self._config["model_name"],
        }
        if mode == "local":
            log_bind["ollama_base"] = self._config["ollama_base_url"]
        else:
            log_bind["api_provider"] = self._config.get("api_provider", "")
            log_bind["api_base"] = self._config.get("api_base_url", "")

        self._logger = self._logger.bind(**log_bind)

    # ── 公开接口实现 ────────────────────────────────────────────────────

    async def _invoke_impl(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 Agent 调用（ReAct 循环）

        实现完整的 ReAct 推理循环：
        1. 从 MCP 服务器获取可用工具列表
        2. 构建系统提示词（包含工具描述）
        3. 迭代执行：模型推理 → 解析动作 → 调用工具 → 观察结果
        4. 直到模型输出 Final Answer 或达到最大迭代次数

        Args:
            prompt: 用户输入问题
            system_prompt: 额外的系统提示词（追加到默认系统提示词后）
            temperature: 生成温度
            max_tokens: 最大输出 token 数
            metadata: 元数据

        Returns:
            包含 output, input_tokens, output_tokens, iterations, tools_used 的字典
        """
        # 确保 HTTP 客户端已创建
        await self._ensure_http_client()

        # 获取 MCP 工具列表
        tools = await self._get_mcp_tools()
        self._logger.debug(
            "hermes_tools_loaded",
            tool_count=len(tools),
        )

        # 构建系统提示词
        tools_description = self._format_tools_description(tools)
        max_iterations = self._config.get("max_iterations", 5)

        # 根据模式选择系统提示词模板
        system_prompt_template = (
            self._SYSTEM_PROMPT_TEMPLATE_LOCAL
            if self._mode == "local"
            else self._SYSTEM_PROMPT_TEMPLATE_API
        )
        base_system_prompt = system_prompt_template.format(
            tools_description=tools_description,
            max_iterations=max_iterations,
        )
        if system_prompt:
            base_system_prompt = f"{base_system_prompt}\n\n## 附加指令\n{system_prompt}"

        # 初始化对话历史
        messages: list[dict[str, str]] = [
            {"role": "system", "content": base_system_prompt},
            {"role": "user", "content": prompt},
        ]

        # 累计 token 统计
        total_input_tokens = 0
        total_output_tokens = 0

        # 记录使用过的工具
        tools_used: list[dict[str, Any]] = []

        # ReAct 主循环
        final_answer = ""
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            self._logger.debug(
                "hermes_iteration_start",
                iteration=iteration,
                max_iterations=max_iterations,
            )

            # 调用模型进行推理（根据模式分发到 Ollama 或 API）
            response_text, input_tokens, output_tokens = await self._call_model(
                messages=messages,
                temperature=temperature if temperature > 0 else self._config.get("temperature", 0.7),
                max_tokens=max_tokens,
            )
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens

            # 将模型回复加入历史
            messages.append({"role": "assistant", "content": response_text})

            self._logger.debug(
                "hermes_model_response",
                iteration=iteration,
                response_length=len(response_text),
            )

            # 解析模型输出，判断是动作还是最终答案
            parsed = self._parse_react_output(response_text)

            if parsed["type"] == "final_answer":
                # 模型给出了最终答案
                final_answer = parsed["content"]
                self._logger.info(
                    "hermes_final_answer",
                    iteration=iteration,
                    answer_length=len(final_answer),
                )
                break

            elif parsed["type"] == "action":
                # 模型请求调用工具
                tool_name = parsed["tool_name"]
                tool_input = parsed["tool_input"]

                self._logger.info(
                    "hermes_tool_call",
                    iteration=iteration,
                    tool_name=tool_name,
                )

                # 调用 MCP 工具
                try:
                    observation = await self._call_mcp_tool(tool_name, tool_input)
                    observation_str = json.dumps(observation, ensure_ascii=False, indent=2)
                except Exception as exc:
                    observation_str = f"工具调用失败: {exc}"
                    self._logger.error(
                        "hermes_tool_call_failed",
                        tool_name=tool_name,
                        error=str(exc),
                    )

                # 记录工具使用
                tools_used.append({
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                })

                # 将观察结果加入对话历史
                observation_message = f"Observation:\n{observation_str}"
                messages.append({"role": "user", "content": observation_message})

                self._logger.debug(
                    "hermes_observation",
                    iteration=iteration,
                    observation_length=len(observation_str),
                )

            else:
                # 无法解析输出，可能模型还在思考中
                # 将回复作为思考继续，提示模型按照格式输出
                hint = (
                    "请按照 ReAct 格式输出你的思考。"
                    "如果需要调用工具，请使用 Action: 和 Action Input: 格式。"
                    "如果已经有答案，请使用 Final Answer: 格式。"
                )
                messages.append({"role": "user", "content": hint})
                self._logger.warning(
                    "hermes_unparseable_output",
                    iteration=iteration,
                    response_preview=response_text[:200],
                )

        # 如果循环结束仍未得到最终答案，使用最后一次回复作为答案
        if not final_answer and messages:
            final_answer = messages[-1]["content"]
            self._logger.warning(
                "hermes_max_iterations_reached",
                max_iterations=max_iterations,
                using_last_response=True,
            )

        return {
            "output": final_answer,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "model": self._config["model_name"],
            "mode": self._mode,
            "iterations": iteration,
            "tools_used": tools_used,
            "local": self._mode == "local",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查实现

        本地模式检查：
        1. Ollama 服务是否可达
        2. 指定模型是否已加载

        API 模式检查：
        1. API 端点是否可达（不验证密钥有效性）

        两种模式均检查：
        - MCP 服务器是否可达

        Returns:
            包含 healthy 和 message 的字典
        """
        health_issues: list[str] = []

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            if self._mode == "local":
                # ── 本地模式：检查 Ollama 服务 ──
                try:
                    ollama_url = self._config["ollama_base_url"].rstrip("/")

                    response = await self._http_client.get(
                        f"{ollama_url}/api/tags",
                        timeout=5.0,
                    )
                    if response.status_code != 200:
                        health_issues.append(
                            f"Ollama 服务返回状态码 {response.status_code}"
                        )
                    else:
                        # 检查指定模型是否存在
                        data = response.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        model_name = self._config["model_name"]
                        if model_name not in models:
                            # 模型可能未拉取，但服务本身是健康的
                            health_issues.append(
                                f"模型 '{model_name}' 未在 Ollama 中找到（可用模型: {models}）"
                            )
                except Exception as exc:
                    health_issues.append(f"Ollama 服务不可达: {exc}")

            else:
                # ── API 模式：检查 API 端点可达性 ──
                try:
                    api_url = self._config["api_base_url"].rstrip("/")
                    response = await self._http_client.get(
                        api_url,
                        timeout=5.0,
                    )
                    # 401/403 是正常的（没有密钥或密钥无效），只要不是连接错误就行
                    if response.status_code in (401, 403):
                        pass  # API 可达，只是认证问题
                    elif response.status_code >= 500:
                        health_issues.append(
                            f"API 服务端错误 (HTTP {response.status_code})"
                        )
                except httpx.ConnectError as exc:
                    health_issues.append(f"无法连接到 API 服务: {exc}")
                except Exception as exc:
                    health_issues.append(f"API 服务检查异常: {exc}")

            # ── 通用：检查 MCP 服务器 ──
            try:
                mcp_url = self._config["mcp_server_url"].rstrip("/")

                # 尝试获取工具列表来验证 MCP 端点
                response = await self._http_client.post(
                    f"{mcp_url}",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    timeout=5.0,
                )
                # 401/403 可能是鉴权问题，但服务本身是活的
                if response.status_code not in (200, 401, 403, 404, 405):
                    health_issues.append(
                        f"MCP 服务器返回状态码 {response.status_code}"
                    )
            except Exception as exc:
                health_issues.append(f"MCP 服务器不可达: {exc}")

        except Exception as exc:
            health_issues.append(f"健康检查异常: {exc}")

        if health_issues:
            return {
                "healthy": False,
                "message": "; ".join(health_issues),
            }

        if self._mode == "local":
            return {
                "healthy": True,
                "message": (
                    f"Hermes Agent 运行正常（模式: local，"
                    f"模型: {self._config['model_name']}，"
                    f"Ollama: {self._config['ollama_base_url']}，"
                    f"MCP: {self._config['mcp_server_url']}）"
                ),
            }
        else:
            return {
                "healthy": True,
                "message": (
                    f"Hermes Agent 运行正常（模式: api，"
                    f"Provider: {self._config.get('api_provider', '')}，"
                    f"模型: {self._config['model_name']}，"
                    f"MCP: {self._config['mcp_server_url']}）"
                ),
            }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算调用费用

        本地模式：0 成本
        API 模式：根据 cost_model 配置计算
        """
        if self._mode == "local":
            return 0.0
        return super().calculate_cost(input_tokens, output_tokens)

    # ── 内部方法：HTTP 客户端管理 ───────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        """确保 HTTP 客户端已创建

        httpx.AsyncClient 必须在事件循环内创建，因此采用懒加载模式。
        API 模式下会自动添加认证头。
        """
        if self._http_client is None:
            headers = {}

            # M8 管理令牌（用于 MCP 调用鉴权）
            m8_token = self._config.get("m8_token", "")
            if m8_token:
                headers["X-M8-Token"] = m8_token

            # API 模式下添加 API 认证头
            if self._mode == "api" and self._config.get("api_key"):
                api_format = self._config.get("api_format", "openai_compatible")
                if api_format == "anthropic_native":
                    headers["x-api-key"] = self._config["api_key"]
                    headers["anthropic-version"] = "2023-06-01"
                else:
                    headers["Authorization"] = f"Bearer {self._config['api_key']}"

            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers=headers if headers else None,
            )
            self._logger.debug("hermes_http_client_created")

    # ── 内部方法：模型调用分发 ───────────────────────────────────────────

    async def _call_model(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用模型（根据模式分发到本地 Ollama 或云端 API）

        统一调用入口，内部根据 self._mode 选择具体实现。

        Args:
            messages: 对话消息列表
            temperature: 生成温度
            max_tokens: 最大输出 token 数

        Returns:
            (回复文本, 输入 token 数, 输出 token 数)
        """
        assert self._http_client is not None, "HTTP 客户端未初始化"

        if self._mode == "local":
            return await self._call_ollama(messages, temperature, max_tokens)
        else:
            return await self._call_api(messages, temperature, max_tokens)

    # ── 内部方法：Ollama 模型调用 ───────────────────────────────────────

    async def _call_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 Ollama Chat API 进行推理（本地模式）

        使用 Ollama 的 /api/chat 端点，支持多轮对话格式。

        Args:
            messages: 对话消息列表，格式为 [{"role": "...", "content": "..."}]
            temperature: 生成温度
            max_tokens: 最大输出 token 数

        Returns:
            (回复文本, 输入 token 数, 输出 token 数)

        Raises:
            RuntimeError: Ollama API 调用失败
            TimeoutError: 请求超时
        """
        assert self._http_client is not None, "HTTP 客户端未初始化"

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

        self._logger.debug(
            "hermes_ollama_call",
            model=model_name,
            message_count=len(messages),
        )

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

        # 提取回复内容
        message_content = data.get("message", {}).get("content", "")

        # 提取 token 统计（Ollama 返回 prompt_eval_count 和 eval_count）
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        # 如果 Ollama 没有返回 token 数，做粗略估算
        if input_tokens == 0:
            total_text = "".join(m["content"] for m in messages)
            input_tokens = len(total_text) // 4
        if output_tokens == 0:
            output_tokens = len(message_content) // 4

        return message_content, input_tokens, output_tokens

    # ── 内部方法：API 模型调用 ──────────────────────────────────────────

    async def _call_api(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用云端 API 进行推理（API 模式）

        支持两种 API 格式：
        - openai_compatible：OpenAI 兼容格式（DeepSeek、Moonshot、Qwen、Custom 等）
        - anthropic_native：Anthropic 原生格式

        Args:
            messages: 对话消息列表，格式为 [{"role": "...", "content": "..."}]
            temperature: 生成温度
            max_tokens: 最大输出 token 数

        Returns:
            (回复文本, 输入 token 数, 输出 token 数)

        Raises:
            RuntimeError: API 调用失败
            TimeoutError: 请求超时
        """
        assert self._http_client is not None, "HTTP 客户端未初始化"

        api_base = self._config["api_base_url"].rstrip("/")
        model_name = self._config["model_name"]
        api_format = self._config.get("api_format", "openai_compatible")

        self._logger.debug(
            "hermes_api_call",
            api_format=api_format,
            model=model_name,
            message_count=len(messages),
        )

        if api_format == "anthropic_native":
            return await self._call_api_anthropic(
                api_base, model_name, messages, temperature, max_tokens
            )
        else:
            return await self._call_api_openai_compatible(
                api_base, model_name, messages, temperature, max_tokens
            )

    async def _call_api_openai_compatible(
        self,
        api_base: str,
        model_name: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 OpenAI 兼容格式的 API

        适用于：OpenAI、DeepSeek、Moonshot、Qwen、Custom（OpenAI 兼容）等
        """
        assert self._http_client is not None

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            response = await self._http_client.post(
                f"{api_base}/chat/completions",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"API 请求超时: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"API 调用失败 (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()

        # 提取回复内容
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("API 返回为空（choices 为空）")
        message_content = choices[0].get("message", {}).get("content", "")

        # 提取 token 统计
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # 如果没有返回 token 数，做粗略估算
        if input_tokens == 0:
            total_text = "".join(m["content"] for m in messages)
            input_tokens = len(total_text) // 4
        if output_tokens == 0:
            output_tokens = len(message_content) // 4

        return message_content, input_tokens, output_tokens

    async def _call_api_anthropic(
        self,
        api_base: str,
        model_name: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 Anthropic 原生格式的 API

        适用于：Anthropic Claude 系列
        """
        assert self._http_client is not None

        # Anthropic 将 system 消息单独处理
        system_msgs = [m for m in messages if m["role"] == "system"]
        user_msgs = [m for m in messages if m["role"] != "system"]

        payload: dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_msgs,
        }
        if system_msgs:
            payload["system"] = system_msgs[0]["content"]

        try:
            response = await self._http_client.post(
                f"{api_base}/v1/messages",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Anthropic API 请求超时: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"Anthropic API 调用失败 (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()

        # 提取回复内容（content 是一个 block 数组）
        content_parts: list[str] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_parts.append(block.get("text", ""))
        message_content = "".join(content_parts)

        # 提取 token 统计
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # 粗略估算兜底
        if input_tokens == 0:
            total_text = "".join(m["content"] for m in messages)
            input_tokens = len(total_text) // 4
        if output_tokens == 0:
            output_tokens = len(message_content) // 4

        return message_content, input_tokens, output_tokens

    # ── 内部方法：MCP 工具管理 ──────────────────────────────────────────

    async def _get_mcp_tools(self) -> list[dict[str, Any]]:
        """从 MCP 服务器获取可用工具列表

        通过 HTTP POST 请求 M2 的 MCP 端点的 tools/list 方法。
        返回结果会被缓存，避免每次调用都重新获取。

        Returns:
            工具列表，每个工具包含 name, description, inputSchema 等字段
        """
        # 如果已有缓存，直接返回
        if self._mcp_tools is not None:
            return self._mcp_tools

        assert self._http_client is not None, "HTTP 客户端未初始化"

        mcp_url = self._config["mcp_server_url"].rstrip("/")
        tools: list[dict[str, Any]] = []

        try:
            # MCP 协议使用 JSON-RPC 2.0 格式
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }

            response = await self._http_client.post(
                f"{mcp_url}",
                json=payload,
                timeout=10.0,
            )

            if response.status_code == 200:
                data = response.json()
                # 解析 JSON-RPC 响应
                if "result" in data:
                    result = data["result"]
                    tools = result.get("tools", [])
                elif "tools" in data:
                    # 某些实现可能直接返回工具列表
                    tools = data.get("tools", [])

                self._logger.info(
                    "hermes_mcp_tools_loaded",
                    tool_count=len(tools),
                    mcp_url=mcp_url,
                )
            else:
                self._logger.warning(
                    "hermes_mcp_tools_fetch_failed",
                    status_code=response.status_code,
                    response=response.text[:500],
                )

        except Exception as exc:
            self._logger.error(
                "hermes_mcp_tools_error",
                error=str(exc),
                mcp_url=mcp_url,
            )

        # 如果获取失败，使用空列表（Agent 仍可回答无需工具的问题）
        if not tools:
            self._logger.warning(
                "hermes_no_tools_available",
                reason="无法从 MCP 服务器获取工具列表，将以纯对话模式运行",
            )

        # 缓存结果
        self._mcp_tools = tools
        return tools

    async def _call_mcp_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """调用 MCP 工具

        通过 HTTP POST 调用 M2 的 MCP 端点的 tools/call 方法。

        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数字典

        Returns:
            工具执行结果字典

        Raises:
            RuntimeError: 工具调用失败
        """
        assert self._http_client is not None, "HTTP 客户端未初始化"

        mcp_url = self._config["mcp_server_url"].rstrip("/")

        # MCP JSON-RPC 2.0 格式请求
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": tool_input,
            },
        }

        self._logger.debug(
            "hermes_mcp_tool_call",
            tool_name=tool_name,
            mcp_url=mcp_url,
        )

        try:
            response = await self._http_client.post(
                f"{mcp_url}",
                json=payload,
                timeout=30.0,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"MCP 工具调用超时: {tool_name}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"MCP 工具调用失败 (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()

        # 解析 JSON-RPC 响应
        if "error" in data:
            error_info = data["error"]
            raise RuntimeError(
                f"MCP 工具执行错误: {error_info.get('message', str(error_info))}"
            )

        if "result" in data:
            result = data["result"]
            # content 字段可能是 MCP 规范的返回格式
            if "content" in result:
                return {"result": result["content"]}
            return result

        # 如果返回格式不符合预期，直接返回整个响应
        return data

    # ── 内部方法：工具描述格式化 ────────────────────────────────────────

    def _format_tools_description(self, tools: list[dict[str, Any]]) -> str:
        """将 MCP 工具列表格式化为提示词中的可读描述

        Args:
            tools: MCP 工具列表

        Returns:
            格式化后的工具描述文本
        """
        if not tools:
            return "（当前没有可用工具）"

        lines = []
        for idx, tool in enumerate(tools, 1):
            name = tool.get("name", "unknown")
            description = tool.get("description", "无描述")
            input_schema = tool.get("inputSchema", {})
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])

            # 格式化参数说明
            param_lines = []
            for param_name, param_info in properties.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                required_mark = "（必填）" if param_name in required else "（可选）"
                param_lines.append(
                    f"      - {param_name} ({param_type}){required_mark}: {param_desc}"
                )

            params_text = "\n".join(param_lines) if param_lines else "      （无参数）"

            lines.append(
                f"{idx}. **{name}**\n"
                f"   描述: {description}\n"
                f"   参数:\n"
                f"{params_text}"
            )

        return "\n\n".join(lines)

    # ── 内部方法：ReAct 输出解析 ────────────────────────────────────────

    def _parse_react_output(self, output: str) -> dict[str, Any]:
        """解析模型的 ReAct 格式输出

        支持的输出格式：
        1. Final Answer: ...  → 最终答案
        2. Action: tool_name
           Action Input: {...}  → 工具调用

        Args:
            output: 模型输出的原始文本

        Returns:
            解析结果字典：
            - type: "final_answer" | "action" | "unknown"
            - content: 最终答案内容（仅 final_answer 类型）
            - tool_name: 工具名称（仅 action 类型）
            - tool_input: 工具输入参数（仅 action 类型）
        """
        # 去除首尾空白
        output = output.strip()

        # ── 检测 Final Answer ──────────────────────────────────────────

        # 匹配 "Final Answer:" 或 "最终答案:" 格式
        final_answer_patterns = [
            r"Final\s*Answer\s*:\s*(.+)",
            r"最终答案\s*[:：]\s*(.+)",
            r"答案\s*[:：]\s*(.+)",
        ]

        for pattern in final_answer_patterns:
            match = re.search(pattern, output, re.IGNORECASE | re.DOTALL)
            if match:
                content = match.group(1).strip()
                # 清理可能的 markdown 代码块标记
                content = re.sub(r"^```\w*\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
                return {
                    "type": "final_answer",
                    "content": content.strip(),
                }

        # ── 检测 Action ───────────────────────────────────────────────

        # 匹配 "Action: tool_name" 和 "Action Input: {...}" 格式
        action_pattern = r"Action\s*:\s*(\w+[\w\-_]*)"
        action_input_pattern = r"Action\s*Input\s*:\s*(\{.*?\})"

        action_match = re.search(action_pattern, output, re.IGNORECASE)
        if action_match:
            tool_name = action_match.group(1).strip()

            # 尝试匹配 Action Input
            input_match = re.search(action_input_pattern, output, re.IGNORECASE | re.DOTALL)
            tool_input: dict[str, Any] = {}

            if input_match:
                input_str = input_match.group(1).strip()
                try:
                    tool_input = json.loads(input_str)
                except json.JSONDecodeError:
                    # JSON 解析失败，尝试提取键值对
                    self._logger.warning(
                        "hermes_action_input_parse_failed",
                        input_str=input_str[:200],
                    )
                    tool_input = {"raw_input": input_str}

            return {
                "type": "action",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }

        # 也匹配中文格式的"动作"和"动作输入"
        action_cn_pattern = r"动作\s*[:：]\s*(\w+[\w\-_]*)"
        action_input_cn_pattern = r"动作输入\s*[:：]\s*(\{.*?\})"

        action_cn_match = re.search(action_cn_pattern, output)
        if action_cn_match:
            tool_name = action_cn_match.group(1).strip()

            input_cn_match = re.search(action_input_cn_pattern, output, re.DOTALL)
            tool_input = {}

            if input_cn_match:
                input_str = input_cn_match.group(1).strip()
                try:
                    tool_input = json.loads(input_str)
                except json.JSONDecodeError:
                    tool_input = {"raw_input": input_str}

            return {
                "type": "action",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }

        # ── 无法识别的格式 ─────────────────────────────────────────────

        return {
            "type": "unknown",
            "content": output,
        }

    # ── 资源清理 ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端，释放资源"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
            self._logger.debug("hermes_http_client_closed")

    def __del__(self) -> None:
        """析构函数（仅作日志记录，资源清理应由 close() 显式调用）"""
        http_client = getattr(self, "_http_client", None)
        log = getattr(self, "_logger", None)
        if http_client is not None and log is not None:
            # 注意：__del__ 中不能调用异步方法
            # 资源可能未被正确释放，应在使用完毕后显式调用 close()
            log.warning(
                "hermes_adapter_not_closed",
                message="HermesAgentAdapter 被销毁时 HTTP 客户端仍未关闭，请显式调用 close() 方法",
            )
