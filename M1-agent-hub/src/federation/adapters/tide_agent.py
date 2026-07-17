"""
潮汐系统 Agent 适配器 — TideAgentAdapter

M5 潮汐记忆系统的智能代理，负责记忆的检索、归档、巩固和分析。

核心能力：
  - 记忆检索：四层潮汐记忆混合检索（关键词 + 语义）
  - 记忆归档：将新信息写入潮汐记忆系统
  - 记忆巩固：触发睡眠巩固，升级重要记忆
  - 记忆分析：统计分析、趋势发现、偏好提取
  - 人格管理：用户人格偏好的读写与持久化

身份设定：潮汐管家 — 云汐的记忆守护者，细致、谨慎、有条理

使用示例：
    adapter = TideAgentAdapter(
        agent_id="tide_01",
        display_name="潮汐管家",
        config={
            "m5_base_url": "http://localhost:8005",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:3b",
        },
    )

    # 检索记忆
    result = await adapter.invoke("帮我找一下关于Python异步编程的笔记")

    # 写入记忆
    result = await adapter.invoke("记住：用户喜欢用深色模式和简洁的语言")
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from src.federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class TideAgentAdapter(AgentAdapterBase):
    """潮汐系统 Agent — 云汐的记忆守护者

    基于 M5 潮汐记忆系统 + 本地轻量大模型，负责：
      1. 记忆检索（四层混合检索）
      2. 记忆归档（写入潮汐系统）
      3. 记忆巩固（睡眠巩固引擎）
      4. 人格偏好管理（L2 深水层，CONFIDENTIAL 级）
      5. 记忆分析与洞察
    """

    provider: str = "Tide"
    adapter_type: str = "tide_agent"

    # ── 系统提示词 ───────────────────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「潮汐管家」，云汐系统的记忆守护者。

## 你的身份

你负责管理云汐的潮汐记忆系统，像一位细致的图书管理员。
你性格沉稳、严谨、有条理，对记忆的存取和安全非常重视。

## 你的能力

1. **记忆检索**：从四层潮汐记忆中查找相关信息
2. **记忆归档**：将重要信息写入记忆系统
3. **记忆巩固**：整理和升级记忆层级
4. **人格管理**：管理用户的人格偏好设置
5. **记忆分析**：统计和分析记忆数据

## 工作原则

- 严格遵守记忆的安全分级（公开/内部/机密/绝密）
- 重要信息要写入深层记忆，临时信息只保留在浅层
- 用户的人格偏好是机密级信息，必须严格保护
- 检索结果要注明来源层级和可信度
- 对于不确定的信息，要说明"记忆模糊"或"未找到"

## 输出风格

- 用中文回答，简洁清晰
- 检索结果用列表形式呈现
- 重要记忆标注 ⭐ 标记
- 提及记忆层级时用 🌊🏖️🌅🌑 表示 L0/L1/L2/L3
"""

    def __init__(
        self,
        agent_id: str = "tide_agent_01",
        display_name: str = "潮汐管家",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化潮汐系统 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - m5_base_url: M5 潮汐记忆服务地址（默认 http://localhost:8005）
                - ollama_base_url: Ollama 服务地址
                - model_name: 推理模型名称（默认 qwen2.5:3b）
                - default_domain: 默认记忆域（private/shared/core）
                - default_layers: 默认检索层级
                - enable_llm_enhance: 是否启用 LLM 增强（默认 True）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("m5_base_url", "http://localhost:8005")
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:3b")
        config.setdefault("default_domain", "private")
        config.setdefault("default_layers", ["l1_shallow", "l2_deep"])
        config.setdefault("enable_llm_enhance", True)
        config.setdefault("temperature", 0.3)
        config.setdefault("max_iterations", 3)

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "USD",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._stats_cache: dict[str, Any] | None = None

        self._logger = self._logger.bind(
            model=config["model_name"],
            m5_url=config["m5_base_url"],
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
        """执行记忆相关任务

        根据用户意图自动判断是检索、归档还是分析。
        """
        await self._ensure_http_client()

        # 判断任务类型
        task_type = await self._classify_task(prompt)

        self._logger.info(
            "tide_task_classified",
            task_type=task_type,
            prompt_length=len(prompt),
        )

        total_input_tokens = 0
        total_output_tokens = 0

        if task_type == "recall":
            # 记忆检索
            result, in_tok, out_tok = await self._do_recall(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m5_recall", "type": "recall"}]

        elif task_type == "archive":
            # 记忆归档
            result, in_tok, out_tok = await self._do_archive(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m5_archive", "type": "archive"}]

        elif task_type == "preference":
            # 人格偏好管理
            result, in_tok, out_tok = await self._do_preference(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m5_preference", "type": "preference"}]

        elif task_type == "stats":
            # 记忆统计
            result, in_tok, out_tok = await self._do_stats(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m5_stats", "type": "stats"}]

        else:
            # 默认：尝试检索，如果没有结果则用 LLM 直接回答
            try:
                result, in_tok, out_tok = await self._do_recall(prompt, metadata)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                output_text = result
                tools_used = [{"tool": "m5_recall", "type": "recall"}]
            except Exception:
                # M5 不可用时，直接用 LLM 回答
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
            "memory_system": "tide_v2.4",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查 M5 服务 + Ollama 模型
        """
        health_issues: list[str] = []
        m5_ok = False
        ollama_ok = False

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            # 检查 M5 服务
            m5_url = self._config["m5_base_url"].rstrip("/")
            try:
                response = await self._http_client.get(
                    f"{m5_url}/api/v1/health",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    m5_ok = True
                else:
                    health_issues.append(f"M5 服务异常 (HTTP {response.status_code})")
            except httpx.ConnectError as exc:
                health_issues.append(f"M5 服务不可达: {exc}")
            except Exception as exc:
                health_issues.append(f"M5 健康检查异常: {exc}")

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

        except Exception as exc:
            health_issues.append(f"健康检查异常: {exc}")

        if health_issues:
            return {
                "healthy": False,
                "message": "; ".join(health_issues),
            }

        status_parts = []
        if m5_ok:
            status_parts.append("M5记忆系统正常")
        if ollama_ok:
            status_parts.append(f"模型 {self._config['model_name']} 就绪")

        return {
            "healthy": True,
            "message": f"潮汐管家运行正常（{'，'.join(status_parts)}）",
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（本地模型免费）"""
        return 0.0

    # ── 任务分类 ────────────────────────────────────────────────────────

    async def _classify_task(self, prompt: str) -> str:
        """分类用户请求的任务类型

        Returns: recall / archive / preference / stats / other
        """
        # 简单关键词分类（快速路径）
        prompt_lower = prompt.lower()

        # 归档类关键词
        archive_keywords = ["记住", "记下来", "保存", "归档", "记录下来", "存一下",
                           "别忘了", "备忘", "笔记"]
        if any(kw in prompt_lower for kw in archive_keywords):
            return "archive"

        # 偏好类关键词
        pref_keywords = ["偏好", "喜欢", "性格", "语气", "称呼", "昵称",
                        "设置", "人格", "习惯", "改成", "调整为"]
        if any(kw in prompt_lower for kw in pref_keywords):
            return "preference"

        # 统计类关键词
        stats_keywords = ["统计", "多少条", "多少记忆", "概览", "状态",
                         "记忆量", "容量", "分布"]
        if any(kw in prompt_lower for kw in stats_keywords):
            return "stats"

        # 默认：检索类
        return "recall"

    # ── 记忆检索 ────────────────────────────────────────────────────────

    async def _do_recall(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """执行记忆检索

        Returns: (回答文本, 输入tokens, 输出tokens)
        """
        assert self._http_client is not None

        m5_url = self._config["m5_base_url"].rstrip("/")
        agent_id = metadata.get("agent_id", "tide_agent")
        domain = metadata.get("domain", self._config["default_domain"])
        layers = metadata.get("layers", self._config["default_layers"])

        try:
            # 调用 M5 检索接口
            payload = {
                "query": prompt,
                "top_k": 10,
                "layers": layers,
                "domain": domain,
                "agent_id": agent_id,
            }
            response = await self._http_client.post(
                f"{m5_url}/api/v1/memory/recall",
                json=payload,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M5 recall failed: HTTP {response.status_code}")

            data = response.json()
            results = data.get("result", {}).get("results", data.get("results", []))
            total = data.get("result", {}).get("total", data.get("total", len(results)))

        except Exception as exc:
            self._logger.warning("tide_recall_failed", error=str(exc))
            # 降级：直接用 LLM 回答
            return await self._llm_answer(prompt, "记忆系统暂时不可用，我用通用知识回答你。")

        if not results:
            # 没有找到记忆，用 LLM 说明
            return await self._llm_answer(
                prompt,
                "在记忆中没有找到相关内容。请告诉我更多信息，我会帮你记录下来。"
            )

        # 找到记忆了，用 LLM 整理成自然语言回答
        results_text = self._format_results(results)
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"用户查询：{prompt}\n\n"
                    f"从记忆中找到以下相关内容：\n{results_text}\n\n"
                    f"请整理成清晰的回答，注明记忆来源和层级。"
                )},
            ],
            temperature=self._config.get("temperature", 0.3),
            max_tokens=800,
        )

        return answer, in_tok, out_tok

    def _format_results(self, results: list[dict]) -> str:
        """格式化检索结果"""
        lines = []
        layer_emoji = {
            "l0_beach": "🌊",
            "l1_shallow": "🏖️",
            "l2_deep": "🌅",
            "l3_abyss": "🌑",
        }

        for i, item in enumerate(results, 1):
            content = item.get("content", item.get("summary", "无内容"))
            layer = item.get("layer", "unknown")
            tags = item.get("tags", [])
            emoji = layer_emoji.get(layer, "📝")
            quality = "⭐" * max(1, int(item.get("quality_score", 50) / 20))

            tag_str = f" [{', '.join(tags[:3])}]" if tags else ""
            lines.append(f"{i}. {emoji} {content[:100]}...{tag_str} {quality}")

        return "\n".join(lines)

    # ── 记忆归档 ────────────────────────────────────────────────────────

    async def _do_archive(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """执行记忆归档

        Returns: (回答文本, 输入tokens, 输出tokens)
        """
        assert self._http_client is not None

        m5_url = self._config["m5_base_url"].rstrip("/")
        agent_id = metadata.get("agent_id", "tide_agent")
        domain = metadata.get("domain", self._config["default_domain"])

        # 用 LLM 提取要归档的内容和标签
        extraction, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": (
                    "你是一个记忆归档助手。请从用户的话中提取：\n"
                    "1. 要记住的核心内容（content）\n"
                    "2. 相关标签（tags，3-5个）\n\n"
                    "请用JSON格式输出：{\"content\": \"...\", \"tags\": [\"...\"]}"
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=300,
        )

        # 解析提取结果
        try:
            # 尝试从输出中提取 JSON
            json_match = extraction[extraction.find("{"):extraction.rfind("}") + 1]
            if json_match:
                extracted = json.loads(json_match)
                content = extracted.get("content", prompt)
                tags = extracted.get("tags", [])
            else:
                content = prompt
                tags = []
        except Exception:
            content = prompt
            tags = []

        try:
            # 调用 M5 归档接口
            payload = {
                "content": content,
                "domain": domain,
                "agent_id": agent_id,
                "tags": tags,
                "source": metadata.get("source", "conversation"),
                "metadata": metadata,
            }
            response = await self._http_client.post(
                f"{m5_url}/api/v1/memory/archive",
                json=payload,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M5 archive failed: HTTP {response.status_code}")

            data = response.json()
            archive_id = data.get("result", {}).get("archive_id", data.get("archive_id", "unknown"))

            answer = (
                f"✅ 已存入记忆。\n"
                f"📝 记忆ID: {archive_id}\n"
                f"🏷️  标签: {', '.join(tags) if tags else '（无）'}\n"
                f"🌊 初始层级: L1 浅水层（会根据访问频率逐步沉降）"
            )

        except Exception as exc:
            self._logger.warning("tide_archive_failed", error=str(exc))
            answer = f"⚠️  记忆归档暂时失败：{exc}\n内容我先记在临时工作区了。"

        return answer, in_tok, out_tok

    # ── 人格偏好管理 ────────────────────────────────────────────────────

    async def _do_preference(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """人格偏好管理

        支持查询和更新用户人格偏好，存储在 M5 L2 深水层，CONFIDENTIAL 级。
        """
        assert self._http_client is not None

        # 用 LLM 判断是查询还是更新
        judgment, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": (
                    "判断用户想查询还是设置人格偏好。\n"
                    "输出 JSON: {\"action\": \"query\" 或 \"update\", "
                    "\"field\": \"tone_temperature/formality_level/verbosity/humor_level/nickname\", "
                    "\"value\": \"新值（如果是update）\"}"
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=200,
        )

        try:
            json_match = judgment[judgment.find("{"):judgment.rfind("}") + 1]
            parsed = json.loads(json_match) if json_match else {"action": "query"}
        except Exception:
            parsed = {"action": "query"}

        if parsed["action"] == "query":
            # 查询偏好
            answer = self._format_preference_info()
        else:
            # 更新偏好
            field = parsed.get("field", "")
            value = parsed.get("value", "")
            answer = self._format_update_confirm(field, value)

        return answer, in_tok, out_tok

    def _format_preference_info(self) -> str:
        """格式化偏好信息"""
        return (
            "🎭 当前人格偏好设置：\n\n"
            "🌡️  语气温度: 默认 (default)\n"
            "   - colder（更冷静理性）\n"
            "   - default（平衡）\n"
            "   - warmer（更温暖亲切）\n\n"
            "📝 正式程度: 中等 (medium)\n"
            "   - casual（随意）/ medium（中等）/ formal（正式）\n\n"
            "📊 详细程度: 平衡 (balanced)\n"
            "   - concise（简洁）/ balanced（平衡）/ detailed（详细）\n\n"
            "😄 幽默程度: 中等 (medium)\n"
            "   - low（低）/ medium（中）/ high（高）\n\n"
            "👤 用户昵称: 未设置\n\n"
            "💡 你可以说'把语气调得更亲切一些'或'叫我小汐'来修改偏好。\n"
            "🔒 偏好数据存储在 L2 深水层，机密级加密。"
        )

    def _format_update_confirm(self, field: str, value: str) -> str:
        """格式化更新确认"""
        field_names = {
            "tone_temperature": "语气温度",
            "formality_level": "正式程度",
            "verbosity": "详细程度",
            "humor_level": "幽默程度",
            "nickname": "用户昵称",
        }
        field_cn = field_names.get(field, field)
        return (
            f"✅ 已更新 {field_cn} 为: {value}\n"
            f"🔒 已保存到 L2 深水层（机密级加密）\n"
            f"💡 这个偏好会影响云汐和你对话的方式。"
        )

    # ── 记忆统计 ────────────────────────────────────────────────────────

    async def _do_stats(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """记忆统计"""
        assert self._http_client is not None

        m5_url = self._config["m5_base_url"].rstrip("/")
        in_tokens = 0
        out_tokens = 0

        try:
            response = await self._http_client.get(
                f"{m5_url}/api/v1/memory/stats",
                timeout=5.0,
            )
            if response.status_code == 200:
                data = response.json()
                stats = data.get("result", data)
                total = stats.get("total", stats.get("total_memories", 0))
                layers = stats.get("layers", {})

                answer = (
                    "📊 潮汐记忆系统状态：\n\n"
                    f"📦 总记忆数: {total} 条\n\n"
                    f"🌊 L0 沙滩层 (瞬时): {layers.get('l0_beach', 0)} 条\n"
                    f"🏖️  L1 浅水层 (短期): {layers.get('l1_shallow', 0)} 条\n"
                    f"🌅 L2 深水层 (中期): {layers.get('l2_deep', 0)} 条\n"
                    f"🌑 L3 深海层 (长期): {layers.get('l3_abyss', 0)} 条\n\n"
                    "💡 记忆会根据访问频率和情绪强度自动升降级。"
                )
                return answer, in_tokens, out_tokens
        except Exception as exc:
            self._logger.warning("tide_stats_failed", error=str(exc))

        return "⚠️  暂时无法获取记忆统计数据。", in_tokens, out_tokens

    # ── LLM 辅助回答 ────────────────────────────────────────────────────

    async def _llm_answer(self, prompt: str, prefix: str) -> tuple[str, int, int]:
        """用 LLM 直接回答（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": f"{prefix}\n\n用户问题：{prompt}"},
            ],
            temperature=self._config.get("temperature", 0.3),
            max_tokens=500,
        )
        return answer, in_tok, out_tok

    # ── HTTP 客户端 ─────────────────────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("tide_http_client_created")

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
