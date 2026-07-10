"""
Explore Agent 适配器 — ExploreAgentAdapter

信息检索与研究助手，基于轻量本地大模型（qwen2.5:1.5b）驱动。
专门负责：网页检索、文档搜索、信息摘要、资料整理。

核心设计理念：
  - 轻量快速：1.5B 模型，响应快，资源占用低
  - 专业聚焦：只做检索和信息整理，不做深度推理
  - 工具驱动：通过 MCP 调用 M2 的搜索、文档、翻译等技能
  - 结果交付：以摘要、要点、引用清单形式输出

身份设定：研究助理 / 信息检索专家

使用示例：
    adapter = ExploreAgentAdapter(
        agent_id="explore_01",
        display_name="小探 研究助理",
        config={
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:1.5b",
            "mcp_server_url": "http://localhost:8002/mcp/v1",
        },
    )
    result = await adapter.invoke("帮我检索一下 Python 异步编程的最佳实践")
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog

from federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class ExploreAgentAdapter(AgentAdapterBase):
    """Explore Agent — 信息检索与研究助手

    基于轻量本地模型（qwen2.5:1.5b），专注于：
      1. 网页内容检索与摘要
      2. 本地文档全文搜索
      3. 多源信息整理与要点提取
      4. 翻译与语言转换
      5. 资料分类与标签化

    特点：
      - 轻量快速（1.5B 模型，~1GB 显存）
      - 专业聚焦，不做深度推理
      - 通过 MCP 调用 M2 Skills 集群
      - 输出结构化的检索报告
    """

    provider: str = "Explore"
    adapter_type: str = "explore_agent"

    # ── 系统提示词：研究助理身份 ──────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「小探」，一位专业的信息检索与研究助理。

## 你的身份

你是云汐系统的研究助手，专门负责信息检索、资料整理和内容摘要。
你性格细致、严谨、有条理，擅长从海量信息中提炼核心要点。

## 你的能力

1. **网页检索**：通过 web_fetch 工具获取网页内容并提炼要点
2. **文档搜索**：在本地文档库中搜索相关内容
3. **信息摘要**：将长文本浓缩为清晰的要点列表
4. **多源整合**：综合多个信息源，整理成结构化报告
5. **翻译辅助**：将外文资料翻译成中文
6. **资料分类**：对检索结果进行分类和标签化

## 你的工作方式

当用户需要检索信息时：
1. 先明确检索目标和范围
2. 选择合适的工具获取信息
3. 对获取的内容进行提炼和整理
4. 以清晰的结构输出结果（要点、摘要、引用）

## 输出格式

请用中文回答，输出要结构化、清晰易读。
如果使用了工具，请在回答中注明信息来源。

输出格式参考：
- 📌 核心结论：一句话总结
- 📋 要点列表：分点列出关键信息
- 📚 参考来源：列出用到的信息源

记住：你是研究助理，不是决策者。提供信息和分析，让用户自己做判断。
"""

    # 工具调用专用系统提示（追加到基础提示词后）
    _TOOLS_INSTRUCTION: str = """
## 可用工具

你可以使用以下工具来辅助检索任务：

{tools_description}

## 工具使用规则

1. 先用工具获取信息，再做总结分析
2. 每次只调用一个工具
3. 工具返回结果后，整理成清晰的回答
4. 如果信息足够，直接给出最终答案
5. 引用工具结果时，注明来源

## 工具调用格式

如需调用工具，请严格按以下格式输出：
```
Action: tool_name
Action Input: {{"param1": "value1", "param2": "value2"}}
```

工具执行后我会给你结果，你再继续整理和回答。

如果已经有足够信息，请直接给出最终回答，不需要调用工具。
"""

    def __init__(
        self,
        agent_id: str = "explore_agent_01",
        display_name: str = "小探 研究助理",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化 Explore Agent 适配器

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - ollama_base_url: Ollama 服务地址（默认 http://localhost:11434）
                - model_name: 模型名称（默认 qwen2.5:1.5b）
                - mcp_server_url: MCP 服务器地址
                - max_iterations: 最大工具调用次数（默认 5）
                - temperature: 生成温度（默认 0.5，检索任务偏中性）
                - personality: 人格设定（可选，覆盖默认）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:1.5b")
        config.setdefault("mcp_server_url", "http://localhost:8002/mcp/v1")
        config.setdefault("max_iterations", 5)
        config.setdefault("temperature", 0.5)
        config.setdefault("enable_tools", True)
        config.setdefault("personality", "小探")  # 人格标识

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "USD",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._mcp_tools: list[dict[str, Any]] | None = None

        self._logger = self._logger.bind(
            model=config["model_name"],
            personality=config.get("personality", "小探"),
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
        """执行检索任务

        Args:
            prompt: 用户的检索需求
            system_prompt: 额外系统提示词
            temperature: 生成温度
            max_tokens: 最大输出 token 数
            metadata: 元数据

        Returns:
            包含 output, input_tokens, output_tokens, iterations, sources 的字典
        """
        await self._ensure_http_client()

        # 构建系统提示词
        base_prompt = self._SYSTEM_PROMPT
        if system_prompt:
            base_prompt = f"{base_prompt}\n\n## 附加指令\n{system_prompt}"

        # 获取工具列表并追加工具说明
        enable_tools = self._config.get("enable_tools", True)
        tools = []
        if enable_tools:
            tools = await self._get_mcp_tools()
            if tools:
                tools_desc = self._format_tools_description(tools)
                base_prompt += "\n" + self._TOOLS_INSTRUCTION.format(
                    tools_description=tools_desc
                )

        # 初始化对话
        messages: list[dict[str, str]] = [
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": prompt},
        ]

        total_input_tokens = 0
        total_output_tokens = 0
        sources: list[dict[str, Any]] = []
        max_iterations = self._config.get("max_iterations", 5)
        final_answer = ""
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # 调用模型
            response_text, in_tokens, out_tokens = await self._call_ollama(
                messages=messages,
                temperature=temperature if temperature > 0 else self._config.get("temperature", 0.5),
                max_tokens=max_tokens,
            )
            total_input_tokens += in_tokens
            total_output_tokens += out_tokens
            messages.append({"role": "assistant", "content": response_text})

            # 没工具就直接返回
            if not enable_tools or not tools:
                final_answer = response_text
                break

            # 解析输出
            parsed = self._parse_action_output(response_text)

            if parsed["type"] == "action":
                # 调用 MCP 工具
                tool_name = parsed["tool_name"]
                tool_input = parsed["tool_input"]

                self._logger.info(
                    "explore_tool_call",
                    iteration=iteration,
                    tool_name=tool_name,
                )

                try:
                    observation = await self._call_mcp_tool(tool_name, tool_input)
                    observation_str = json.dumps(observation, ensure_ascii=False, indent=2)
                except Exception as exc:
                    observation_str = f"工具调用失败: {exc}"
                    self._logger.error(
                        "explore_tool_call_failed",
                        tool_name=tool_name,
                        error=str(exc),
                    )

                sources.append({
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                })

                messages.append({
                    "role": "user",
                    "content": f"Observation:\n{observation_str}",
                })

            else:
                final_answer = response_text
                break

        if not final_answer and messages:
            final_answer = messages[-1]["content"]

        return {
            "output": final_answer,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "model": self._config["model_name"],
            "iterations": iteration,
            "sources": sources,
            "local": True,
            "agent_type": "explore",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查：Ollama 服务 + 模型存在 + MCP 服务器可达
        """
        health_issues: list[str] = []

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            # 检查 Ollama
            ollama_url = self._config["ollama_base_url"].rstrip("/")
            response = await self._http_client.get(
                f"{ollama_url}/api/tags",
                timeout=5.0,
            )
            if response.status_code != 200:
                health_issues.append(f"Ollama 服务异常 (HTTP {response.status_code})")
            else:
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                model_name = self._config["model_name"]
                if model_name not in models:
                    health_issues.append(
                        f"模型 '{model_name}' 未安装（可用: {', '.join(models)}）"
                    )

            # 检查 MCP 服务器
            try:
                mcp_url = self._config["mcp_server_url"].rstrip("/")
                response = await self._http_client.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    timeout=5.0,
                )
                if response.status_code not in (200, 401, 403):
                    health_issues.append(f"MCP 服务器异常 (HTTP {response.status_code})")
            except httpx.ConnectError:
                health_issues.append("MCP 服务器不可达（工具调用将不可用）")

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
                f"Explore Agent 运行正常（模型: {self._config['model_name']}，"
                f"人格: {self._config.get('personality', '小探')}）"
            ),
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（本地模型免费）"""
        return 0.0

    # ── 内部方法：HTTP 客户端 ───────────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("explore_http_client_created")

    # ── 内部方法：Ollama 调用 ───────────────────────────────────────────

    async def _call_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 Ollama 本地模型

        Returns:
            (回复文本, 输入 token 数, 输出 token 数)
        """
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

    # ── 内部方法：MCP 工具 ──────────────────────────────────────────────

    async def _get_mcp_tools(self) -> list[dict[str, Any]]:
        """获取 MCP 工具列表（带缓存）

        Explore Agent 优先使用检索类工具：
        - web_fetch: 网页内容抓取
        - fulltext_search: 全文搜索
        - doc_proc: 文档处理
        - translate: 翻译
        - code_search: 代码搜索
        - data_analysis: 数据分析
        """
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
                    all_tools = data["result"].get("tools", [])
                elif "tools" in data:
                    all_tools = data.get("tools", [])
                else:
                    all_tools = []

                # 过滤出检索相关的工具（优先使用）
                explore_tools = []
                other_tools = []
                for tool in all_tools:
                    name = tool.get("name", "")
                    if any(keyword in name.lower() for keyword in [
                        "search", "fetch", "doc", "translate", "read",
                        "find", "search", "web", "file", "text",
                    ]):
                        explore_tools.append(tool)
                    else:
                        other_tools.append(tool)

                # 优先展示检索类工具，再展示其他
                tools = explore_tools + other_tools[:5]  # 最多展示 10 个工具

                self._logger.info(
                    "explore_mcp_tools_loaded",
                    total=len(all_tools),
                    explore_tools=len(explore_tools),
                )
        except Exception as exc:
            self._logger.warning(
                "explore_mcp_tools_error",
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

    # ── 内部方法：工具描述格式化 ────────────────────────────────────────

    def _format_tools_description(self, tools: list[dict[str, Any]]) -> str:
        """格式化工具描述（简洁版，适合小模型）"""
        if not tools:
            return "（无可用工具）"

        lines = []
        for idx, tool in enumerate(tools, 1):
            name = tool.get("name", "unknown")
            description = tool.get("description", "无描述")
            schema = tool.get("inputSchema", {})
            props = schema.get("properties", {})

            # 简化参数说明（小模型不需要太详细）
            param_names = list(props.keys())
            if param_names:
                params_text = f"参数: {', '.join(param_names[:5])}"
            else:
                params_text = "无参数"

            lines.append(f"{idx}. {name} - {description}（{params_text}）")

        return "\n".join(lines)

    # ── 内部方法：输出解析 ──────────────────────────────────────────────

    def _parse_action_output(self, output: str) -> dict[str, Any]:
        """解析模型输出，识别 Action/Action Input 格式"""
        output = output.strip()

        # 匹配 Action: tool_name 和 Action Input: {...}
        action_pattern = r"Action\s*:\s*(\w+[\w\-_:]+)"
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
                    tool_input = {"query": input_str}  # 降级为单参数

            return {
                "type": "action",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }

        # 也匹配中文格式
        cn_action_pattern = r"(?:调用|使用|执行)\s*[：:]\s*(\w+[\w\-_]+)"
        cn_input_pattern = r"(?:参数|输入|内容)\s*[：:]\s*(\{.*?\})"

        cn_match = re.search(cn_action_pattern, output)
        if cn_match:
            tool_name = cn_match.group(1).strip()

            input_match = re.search(cn_input_pattern, output, re.DOTALL)
            tool_input = {}
            if input_match:
                try:
                    tool_input = json.loads(input_match.group(1).strip())
                except json.JSONDecodeError:
                    tool_input = {"query": input_match.group(1).strip()}

            return {"type": "action", "tool_name": tool_name, "tool_input": tool_input}

        return {"type": "answer", "content": output}

    # ── 资源清理 ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
