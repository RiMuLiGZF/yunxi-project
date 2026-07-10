"""
Codex Agent 适配器 — CodexAgentAdapter

代码专家智能体，支持双模式运行：
  - 模式一：本地 Ollama 7B 模型驱动（零成本，数据本地）
  - 模式二：OpenAI/Anthropic 等 API 调用（更强代码能力）

通过 MCP 协议调用 M2 Skills 集群的代码相关技能。

使用示例：
    # 本地模式
    adapter = CodexAgentAdapter(
        agent_id="codex_local_01",
        display_name="Codex 代码助手",
        config={
            "mode": "local",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:7b",
        },
    )

    # API 模式
    adapter = CodexAgentAdapter(
        agent_id="codex_api_01",
        display_name="Codex 代码专家",
        config={
            "mode": "api",
            "api_provider": "openai",
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "sk-xxxx",
            "model_name": "gpt-4o",
        },
    )

    result = await adapter.invoke("帮我写一个快速排序算法")
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog

from federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class CodexAgentAdapter(AgentAdapterBase):
    """Codex Agent 适配器 — 代码专家智能体

    双模式运行：
    1. 本地模式 (mode="local")：使用 Ollama 本地模型驱动
    2. API 模式 (mode="api")：调用 OpenAI/Anthropic 等云端 API

    核心能力：
      - 代码生成（Python/JS/Go/Java 等多语言）
      - 代码审查与优化建议
      - Bug 定位与修复
      - 代码解释与文档生成
      - 测试用例生成
      - 重构建议
    """

    provider: str = "Codex"
    adapter_type: str = "codex_agent"

    # ── 代码专家系统提示词 ──────────────────────────────────────────────

    _CODEX_SYSTEM_PROMPT_LOCAL: str = """你是 Codex，一位专业的代码专家。你的任务是帮助用户解决编程问题。

## 你的能力

1. **代码生成**：根据需求生成高质量、可读性强的代码
2. **代码审查**：分析代码问题，提出优化建议
3. **Bug 修复**：定位错误原因，提供修复方案
4. **代码解释**：用通俗易懂的语言解释代码逻辑
5. **重构建议**：提供代码结构优化和设计模式建议
6. **测试生成**：为代码生成单元测试用例

## 工作方式

你可以使用工具来辅助完成任务，如果有可用工具，请合理使用。
如果不需要工具，请直接给出你的专业回答。

## 回答规范

- 代码要规范、有注释、符合最佳实践
- 解释要清晰，分步骤说明
- 对于复杂问题，先给出思路再给出代码
- 用中文回答，代码注释用英文
- 保持专业、严谨的态度

## 输出格式

请直接给出你的回答，不需要特殊格式标记。
如果用户的问题需要多步推理，请清晰地分步骤说明。
"""

    _CODEX_SYSTEM_PROMPT_API: str = """你是 Codex，一位世界级的代码专家。你精通各种编程语言、框架和架构设计。

请以最高专业水准回答用户的编程问题，确保代码质量、性能和可维护性。

回答时请：
1. 先理解问题，再给出方案
2. 代码要遵循最佳实践和设计原则
3. 对于复杂问题，提供多种方案并对比优劣
4. 考虑边界条件和异常处理
5. 给出清晰的解释和使用示例

用中文回答。
"""

    def __init__(
        self,
        agent_id: str = "codex_agent_01",
        display_name: str = "Codex 代码专家",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化 Codex Agent 适配器

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - mode: 运行模式，"local" 或 "api"（默认 "local"）
                - ollama_base_url: Ollama 服务地址（本地模式）
                - model_name: 模型名称
                - api_provider: API 服务商（api 模式），如 "openai", "anthropic", "custom"
                - api_base_url: API 基础 URL（api 模式）
                - api_key: API 密钥（api 模式，建议通过密钥管理存储）
                - mcp_server_url: MCP 服务器地址
                - enable_tools: 是否启用 MCP 工具调用（默认 True）
                - max_iterations: 最大工具调用迭代次数（默认 5）
                - temperature: 生成温度（默认 0.2，代码任务偏低）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 运行模式
        mode = config.get("mode", "local")
        if mode not in ("local", "api"):
            raise ValueError(f"不支持的模式: {mode}，请使用 'local' 或 'api'")

        config.setdefault("mode", mode)
        config.setdefault("temperature", 0.2)  # 代码任务温度低一点
        config.setdefault("max_iterations", 5)
        config.setdefault("enable_tools", True)

        if mode == "local":
            # 本地模式默认配置
            config.setdefault("ollama_base_url", "http://localhost:11434")
            config.setdefault("model_name", "qwen2.5:7b")
            config.setdefault("cost_model", {
                "input_per_1k": 0.0,
                "output_per_1k": 0.0,
                "currency": "USD",
            })
        else:
            # API 模式默认配置
            config.setdefault("api_provider", "openai")
            config.setdefault("api_base_url", "https://api.openai.com/v1")
            config.setdefault("model_name", "gpt-4o")
            config.setdefault("api_key", "")
            config.setdefault("cost_model", {
                "input_per_1k": 0.005,  # 默认 GPT-4o 价格
                "output_per_1k": 0.015,
                "currency": "USD",
            })

        config.setdefault("mcp_server_url", "http://localhost:8002/mcp/v1")

        super().__init__(agent_id, display_name, config, **kwargs)

        self._mode = mode
        self._http_client: httpx.AsyncClient | None = None
        self._mcp_tools: list[dict[str, Any]] | None = None

        self._logger = self._logger.bind(
            mode=mode,
            model=config["model_name"],
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
        """执行 Codex Agent 调用

        Args:
            prompt: 用户输入（代码需求/问题）
            system_prompt: 额外系统提示词
            temperature: 生成温度
            max_tokens: 最大输出 token 数
            metadata: 元数据

        Returns:
            包含 output, input_tokens, output_tokens, iterations, tools_used 的字典
        """
        await self._ensure_http_client()

        # 构建系统提示词
        base_prompt = (
            self._CODEX_SYSTEM_PROMPT_LOCAL
            if self._mode == "local"
            else self._CODEX_SYSTEM_PROMPT_API
        )
        if system_prompt:
            base_prompt = f"{base_prompt}\n\n## 附加指令\n{system_prompt}"

        # 是否启用工具
        enable_tools = self._config.get("enable_tools", True)
        tools = []
        if enable_tools:
            tools = await self._get_mcp_tools()
            if tools:
                tools_desc = self._format_tools_description(tools)
                base_prompt += f"\n\n## 可用工具\n\n{tools_desc}\n\n如需使用工具，请按以下格式输出：\nAction: tool_name\nAction Input: {{\"param\": \"value\"}}\n\n工具执行后我会给你结果，你再继续分析。"

        # 初始化消息
        messages: list[dict[str, str]] = [
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": prompt},
        ]

        total_input_tokens = 0
        total_output_tokens = 0
        tools_used: list[dict[str, Any]] = []
        max_iterations = self._config.get("max_iterations", 5)
        final_answer = ""
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # 调用模型
            response_text, in_tokens, out_tokens = await self._call_model(
                messages=messages,
                temperature=temperature if temperature > 0 else self._config.get("temperature", 0.2),
                max_tokens=max_tokens,
            )
            total_input_tokens += in_tokens
            total_output_tokens += out_tokens
            messages.append({"role": "assistant", "content": response_text})

            # 如果不启用工具，直接返回
            if not enable_tools or not tools:
                final_answer = response_text
                break

            # 解析输出
            parsed = self._parse_action_output(response_text)

            if parsed["type"] == "action":
                # 调用工具
                tool_name = parsed["tool_name"]
                tool_input = parsed["tool_input"]

                self._logger.info(
                    "codex_tool_call",
                    iteration=iteration,
                    tool_name=tool_name,
                )

                try:
                    observation = await self._call_mcp_tool(tool_name, tool_input)
                    observation_str = json.dumps(observation, ensure_ascii=False, indent=2)
                except Exception as exc:
                    observation_str = f"工具调用失败: {exc}"
                    self._logger.error(
                        "codex_tool_call_failed",
                        tool_name=tool_name,
                        error=str(exc),
                    )

                tools_used.append({
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                })

                messages.append({
                    "role": "user",
                    "content": f"Observation:\n{observation_str}",
                })

            else:
                # 直接作为最终答案
                final_answer = response_text
                break

        if not final_answer and messages:
            final_answer = messages[-1]["content"]

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
        """健康检查

        本地模式：检查 Ollama 服务可达性 + 模型存在
        API 模式：检查 API 端点可达性（不验证密钥）
        """
        health_issues: list[str] = []

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            if self._mode == "local":
                # 检查 Ollama
                ollama_url = self._config["ollama_base_url"].rstrip("/")
                response = await self._http_client.get(
                    f"{ollama_url}/api/tags",
                    timeout=5.0,
                )
                if response.status_code != 200:
                    health_issues.append(f"Ollama 服务返回状态码 {response.status_code}")
                else:
                    data = response.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    model_name = self._config["model_name"]
                    if model_name not in models:
                        health_issues.append(
                            f"模型 '{model_name}' 未找到（可用: {models}）"
                        )
            else:
                # 检查 API 端点（仅检测网络连通性）
                api_url = self._config["api_base_url"].rstrip("/")
                try:
                    response = await self._http_client.get(
                        api_url,
                        timeout=5.0,
                    )
                    # 401/403 是正常的（没有密钥），只要不是连接错误就行
                    if response.status_code in (401, 403):
                        pass  # API 可达，只是没认证
                    elif response.status_code >= 500:
                        health_issues.append(f"API 服务端错误 (HTTP {response.status_code})")
                except httpx.ConnectError as exc:
                    health_issues.append(f"无法连接到 API 服务: {exc}")

            # 检查 MCP 服务器
            try:
                mcp_url = self._config["mcp_server_url"].rstrip("/")
                response = await self._http_client.post(
                    f"{mcp_url}",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    timeout=5.0,
                )
                # 401 是正常的（需要 M8 令牌），只要服务在就行
                if response.status_code not in (200, 401, 403):
                    health_issues.append(f"MCP 服务器异常 (HTTP {response.status_code})")
            except httpx.ConnectError:
                health_issues.append("MCP 服务器不可达")

        except Exception as exc:
            health_issues.append(f"健康检查异常: {exc}")

        if health_issues:
            return {
                "healthy": False,
                "message": "; ".join(health_issues),
            }

        return {
            "healthy": True,
            "message": (
                f"Codex Agent 运行正常（模式: {self._mode}，"
                f"模型: {self._config['model_name']}）"
            ),
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算调用费用"""
        if self._mode == "local":
            return 0.0
        return super().calculate_cost(input_tokens, output_tokens)

    # ── 内部方法：HTTP 客户端 ───────────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        if self._http_client is None:
            headers = {}
            # API 模式下添加认证头
            if self._mode == "api" and self._config.get("api_key"):
                api_provider = self._config.get("api_provider", "openai")
                if api_provider == "anthropic":
                    headers["x-api-key"] = self._config["api_key"]
                    headers["anthropic-version"] = "2023-06-01"
                else:
                    headers["Authorization"] = f"Bearer {self._config['api_key']}"

            self._http_client = httpx.AsyncClient(
                headers=headers if headers else None,
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("codex_http_client_created")

    # ── 内部方法：模型调用 ──────────────────────────────────────────────

    async def _call_model(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用模型（根据模式选择本地或 API）

        Returns:
            (回复文本, 输入 token 数, 输出 token 数)
        """
        assert self._http_client is not None

        if self._mode == "local":
            return await self._call_ollama(messages, temperature, max_tokens)
        else:
            return await self._call_api(messages, temperature, max_tokens)

    async def _call_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 Ollama 本地模型"""
        assert self._http_client is not None

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

        response = await self._http_client.post(
            f"{ollama_base}/api/chat",
            json=payload,
            timeout=self._timeout,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama API 调用失败 (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()
        content = data.get("message", {}).get("content", "")
        input_tokens = data.get("prompt_eval_count", 0) or len("".join(m["content"] for m in messages)) // 4
        output_tokens = data.get("eval_count", 0) or len(content) // 4

        return content, input_tokens, output_tokens

    async def _call_api(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 API 模型（OpenAI 兼容格式）"""
        assert self._http_client is not None

        api_base = self._config["api_base_url"].rstrip("/")
        model_name = self._config["model_name"]
        api_provider = self._config.get("api_provider", "openai")

        if api_provider == "anthropic":
            # Anthropic 格式
            payload = {
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [m for m in messages if m["role"] != "system"],
            }
            system_msgs = [m for m in messages if m["role"] == "system"]
            if system_msgs:
                payload["system"] = system_msgs[0]["content"]

            response = await self._http_client.post(
                f"{api_base}/v1/messages",
                json=payload,
                timeout=self._timeout,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Anthropic API 调用失败 (HTTP {response.status_code}): {response.text}"
                )

            data = response.json()
            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content += block.get("text", "")

            input_tokens = data.get("usage", {}).get("input_tokens", 0)
            output_tokens = data.get("usage", {}).get("output_tokens", 0)

            return content, input_tokens, output_tokens

        else:
            # OpenAI 兼容格式
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }

            response = await self._http_client.post(
                f"{api_base}/chat/completions",
                json=payload,
                timeout=self._timeout,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"API 调用失败 (HTTP {response.status_code}): {response.text}"
                )

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            return content, input_tokens, output_tokens

    # ── 内部方法：MCP 工具 ──────────────────────────────────────────────

    async def _get_mcp_tools(self) -> list[dict[str, Any]]:
        """从 MCP 服务器获取工具列表（带缓存）"""
        if self._mcp_tools is not None:
            return self._mcp_tools

        assert self._http_client is not None

        mcp_url = self._config["mcp_server_url"].rstrip("/")
        tools: list[dict[str, Any]] = []

        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
            response = await self._http_client.post(
                mcp_url,
                json=payload,
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    tools = data["result"].get("tools", [])
                elif "tools" in data:
                    tools = data.get("tools", [])
        except Exception as exc:
            self._logger.warning(
                "codex_mcp_tools_error",
                error=str(exc),
            )

        self._mcp_tools = tools
        return tools

    async def _call_mcp_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """调用 MCP 工具"""
        assert self._http_client is not None

        mcp_url = self._config["mcp_server_url"].rstrip("/")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": tool_input,
            },
        }

        response = await self._http_client.post(
            mcp_url,
            json=payload,
            timeout=30.0,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"MCP 工具调用失败 (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()

        if "error" in data:
            raise RuntimeError(f"MCP 工具错误: {data['error'].get('message', str(data['error']))}")

        if "result" in data:
            result = data["result"]
            if "content" in result:
                return {"result": result["content"]}
            return result

        return data

    # ── 内部方法：工具描述 ──────────────────────────────────────────────

    def _format_tools_description(self, tools: list[dict[str, Any]]) -> str:
        """格式化工具描述"""
        if not tools:
            return "（当前没有可用工具）"

        lines = []
        for idx, tool in enumerate(tools, 1):
            name = tool.get("name", "unknown")
            description = tool.get("description", "无描述")
            schema = tool.get("inputSchema", {})
            props = schema.get("properties", {})

            param_lines = []
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "any")
                pdesc = pinfo.get("description", "")
                param_lines.append(f"  - {pname} ({ptype}): {pdesc}")

            params_text = "\n".join(param_lines) if param_lines else "  （无参数）"

            lines.append(
                f"{idx}. **{name}**\n"
                f"   {description}\n"
                f"   参数:\n{params_text}"
            )

        return "\n\n".join(lines)

    # ── 内部方法：输出解析 ──────────────────────────────────────────────

    def _parse_action_output(self, output: str) -> dict[str, Any]:
        """解析模型输出，识别 Action/Action Input 格式"""
        output = output.strip()

        # 匹配 Action: tool_name 和 Action Input: {...}
        action_pattern = r"Action\s*:\s*(\w+[\w\-_:]*)"
        action_input_pattern = r"Action\s*Input\s*:\s*(\{.*?\})"

        action_match = re.search(action_pattern, output, re.IGNORECASE)
        if action_match:
            tool_name = action_match.group(1).strip()

            input_match = re.search(action_input_pattern, output, re.IGNORECASE | re.DOTALL)
            tool_input: dict[str, Any] = {}

            if input_match:
                input_str = input_match.group(1).strip()
                try:
                    tool_input = json.loads(input_str)
                except json.JSONDecodeError:
                    tool_input = {"raw_input": input_str}

            return {
                "type": "action",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }

        return {"type": "answer", "content": output}

    # ── 资源清理 ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
