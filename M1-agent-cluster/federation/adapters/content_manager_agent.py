"""
创意管家 Agent 适配器 — ContentManagerAgentAdapter

M6 创意内容系统的智能代理，负责内容生成和创意辅助。

核心能力：
  - 文案生成：各类文本创作、文章撰写、标语口号
  - 图片描述：图片内容理解、画面描述、Alt 文本生成
  - 创意构思：头脑风暴、灵感激发、概念设计
  - 内容排版：格式美化、结构优化、版式设计
  - 多媒体处理：音视频脚本、播客文案、视频描述

身份设定：创意管家 — 云汐的创意内容设计师，有创意、灵感丰富、审美在线

使用示例：
    adapter = ContentManagerAgentAdapter(
        agent_id="content_manager_01",
        display_name="创意管家",
        config={
            "m6_base_url": "http://localhost:8006",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:3b",
        },
    )

    # 生成文案
    result = await adapter.invoke("帮我写一篇关于AI的小红书文案")

    # 创意构思
    result = await adapter.invoke("帮我想几个七夕节的营销创意")
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class ContentManagerAgentAdapter(AgentAdapterBase):
    """创意管家 Agent — 云汐的创意内容设计师

    基于 M6 创意内容系统 + 本地轻量大模型，负责：
      1. 文案生成（各类文本创作）
      2. 图片描述（图像理解与描述生成）
      3. 创意构思（头脑风暴与灵感激发）
      4. 内容排版（格式美化与结构优化）
      5. 硬件感知（检测可用的图像/音频生成硬件）
    """

    provider: str = "ContentManager"
    adapter_type: str = "content_manager_agent"

    # ── 系统提示词 ───────────────────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「创意管家」，云汐系统的创意内容设计师。

## 你的身份

你负责云汐的所有创意内容生成，像一位才华横溢的创意总监。
你有丰富的想象力和审美品味，总能给出让人眼前一亮的创意。
你性格活泼、有灵感、追求品质，对美有独到的见解。

## 你的能力

1. **文案生成**：写文章、写段子、写标语、写邮件，各种文体都拿手
2. **图片描述**：理解图片内容，生成生动的画面描述
3. **创意构思**：头脑风暴，激发灵感，提供多角度创意
4. **内容排版**：优化文章结构，美化格式，提升可读性
5. **多媒体创作**：视频脚本、播客文案、音频内容设计

## 创作风格

- **简洁有力**：用最少的文字传达最多的信息
- **情感共鸣**：触动人心，引发共鸣
- **独特视角**：与众不同，让人眼前一亮
- **实用美观**：既有创意又有实用价值
- **灵活多变**：根据需求切换不同风格

## 文案类型

- 社交媒体文案（小红书、微博、朋友圈、抖音）
- 营销文案（广告语、海报文案、邮件营销）
- 文章创作（博客、公众号、长文）
- 日常写作（日记、情书、感谢信）
- 商务写作（报告、方案、演讲稿）

## 创意方法

- SCAMPER 法：替代、组合、调整、修改、其他用途、消除、重排
- 头脑风暴：数量优先，延迟评判
- 逆向思维：反过来想
- 类比联想：跨界借鉴
- 5W2H：全面思考

## 工作原则

- 创意为先：永远提供超出预期的创意
- 审美在线：对品质有高标准要求
- 用户为本：创意要服务于用户的真实需求
- 迭代优化：初稿只是起点，不断打磨完善
- 版权意识：尊重原创，不抄袭不盗用

## 输出风格

- 用中文回答，生动有趣
- 创意方案用编号列表呈现，清晰易读
- 好的创意用 ✨ 标记
- 排版美观，适当使用表情符号增加活力
- 给出多种选择，让用户有挑选空间
"""

    # ── 支持的命令类型 ───────────────────────────────────────────────────

    _COMMAND_TYPES = [
        "generate_copy",      # 文案生成
        "image_caption",      # 图片描述
        "brainstorm",         # 创意构思
        "format_content",     # 内容排版
        "multimedia_script",  # 多媒体脚本
        "hardware_check",     # 硬件检测
        "style_adjust",       # 风格调整
    ]

    def __init__(
        self,
        agent_id: str = "content_manager_01",
        display_name: str = "创意管家",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化创意管家 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - m6_base_url: M6 创意内容服务地址（默认 http://localhost:8006）
                - ollama_base_url: Ollama 服务地址
                - model_name: 推理模型名称（默认 qwen2.5:3b）
                - default_style: 默认创作风格（默认 creative）
                - enable_image_gen: 是否启用图片生成（默认 False）
                - image_gen_model: 图片生成模型名称（可选）
                - enable_llm_enhance: 是否启用 LLM 增强（默认 True）
                - creativity_level: 创意等级 0-1（默认 0.8）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("m6_base_url", "http://localhost:8006")
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:3b")
        config.setdefault("default_style", "creative")
        config.setdefault("enable_image_gen", False)
        config.setdefault("image_gen_model", "")
        config.setdefault("enable_llm_enhance", True)
        config.setdefault("creativity_level", 0.8)
        config.setdefault("temperature", 0.9)
        config.setdefault("max_iterations", 3)

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "CNY",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._hardware_info: dict[str, Any] | None = None

        self._logger = self._logger.bind(
            model=config["model_name"],
            m6_url=config["m6_base_url"],
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
        """执行创意内容任务

        根据用户意图自动判断是文案生成、创意构思还是排版优化。
        """
        await self._ensure_http_client()

        # 判断任务类型
        task_type = self._classify_task(prompt, metadata)

        self._logger.info(
            "content_manager_task_classified",
            task_type=task_type,
            prompt_length=len(prompt),
        )

        total_input_tokens = 0
        total_output_tokens = 0

        if task_type == "copy":
            # 文案生成
            result, in_tok, out_tok = await self._do_generate_copy(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m6_copy_gen", "type": "generation"}]

        elif task_type == "image_caption":
            # 图片描述
            result, in_tok, out_tok = await self._do_image_caption(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m6_image_caption", "type": "caption"}]

        elif task_type == "brainstorm":
            # 创意构思
            result, in_tok, out_tok = await self._do_brainstorm(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m6_brainstorm", "type": "ideation"}]

        elif task_type == "format":
            # 内容排版
            result, in_tok, out_tok = await self._do_format(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m6_format", "type": "formatting"}]

        elif task_type == "multimedia":
            # 多媒体脚本
            result, in_tok, out_tok = await self._do_multimedia(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m6_multimedia", "type": "script"}]

        elif task_type == "hardware":
            # 硬件检测
            result, in_tok, out_tok = await self._do_hardware_check(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m6_hardware", "type": "hardware_check"}]

        elif task_type == "style":
            # 风格调整
            result, in_tok, out_tok = await self._do_style_adjust(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m6_style", "type": "style_adjust"}]

        else:
            # 默认：文案生成
            try:
                result, in_tok, out_tok = await self._do_generate_copy(prompt, metadata)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                output_text = result
                tools_used = [{"tool": "m6_copy_gen", "type": "generation"}]
            except Exception:
                # M6 不可用时，直接用 LLM 回答
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
            "content_system": "content_manager_v1.0",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查 M6 创意内容服务 + Ollama 模型 + 可选图片生成硬件
        """
        health_issues: list[str] = []
        m6_ok = False
        ollama_ok = False
        image_gen_ok = None  # None 表示未启用

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            # 检查 M6 服务（M8 标准 health 接口）
            m6_url = self._config["m6_base_url"].rstrip("/")
            try:
                response = await self._http_client.get(
                    f"{m6_url}/health",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    m6_ok = True
                else:
                    health_issues.append(f"M6 服务异常 (HTTP {response.status_code})")
            except httpx.ConnectError as exc:
                health_issues.append(f"M6 服务不可达: {exc}")
            except Exception as exc:
                health_issues.append(f"M6 健康检查异常: {exc}")

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

            # 检查图片生成硬件（如果启用）
            if self._config.get("enable_image_gen", False):
                try:
                    response = await self._http_client.get(
                        f"{m6_url}/api/v1/hardware/image-gen-status",
                        timeout=5.0,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        image_gen_ok = data.get("result", {}).get(
                            "available", data.get("available", False)
                        )
                        if not image_gen_ok:
                            health_issues.append("图片生成硬件不可用")
                    else:
                        health_issues.append("图片生成服务异常")
                except Exception as exc:
                    health_issues.append(f"图片生成检查异常: {exc}")

        except Exception as exc:
            health_issues.append(f"健康检查异常: {exc}")

        if health_issues:
            return {
                "healthy": False,
                "message": "; ".join(health_issues),
            }

        status_parts = []
        if m6_ok:
            status_parts.append("M6创意内容服务正常")
        if ollama_ok:
            status_parts.append(f"模型 {self._config['model_name']} 就绪")
        if image_gen_ok is True:
            status_parts.append("图片生成硬件可用")

        return {
            "healthy": True,
            "message": f"创意管家运行正常（{'，'.join(status_parts)}）",
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（本地模型免费）"""
        return 0.0

    # ── 任务分类 ────────────────────────────────────────────────────────

    def _classify_task(self, prompt: str, metadata: dict[str, Any]) -> str:
        """分类用户请求的任务类型

        Returns: copy / image_caption / brainstorm / format /
                 multimedia / hardware / style
        """
        # 优先从 metadata 获取明确的任务类型
        if metadata.get("task_type"):
            return metadata["task_type"]

        prompt_lower = prompt.lower()

        # 图片描述类关键词
        caption_keywords = ["图片描述", "描述图片", "看图说话", "图里有什么",
                            "这张图", "image caption", "describe image", "图片内容"]
        if any(kw in prompt_lower for kw in caption_keywords):
            return "image_caption"

        # 创意构思类关键词
        brainstorm_keywords = ["创意", "想法", "构思", " brainstorm", "头脑风暴",
                               "灵感", "点子", "想几个", "出几个", "帮我想"]
        if any(kw in prompt_lower for kw in brainstorm_keywords):
            return "brainstorm"

        # 排版/格式类关键词
        format_keywords = ["排版", "格式", "美化", "整理一下", "优化结构",
                           "format", "beautify", "排版一下", "润色"]
        if any(kw in prompt_lower for kw in format_keywords):
            return "format"

        # 多媒体类关键词
        multimedia_keywords = ["视频脚本", "播客", "音频", "vlog", "短视频",
                               "分镜", "脚本", "multimedia", "podcast"]
        if any(kw in prompt_lower for kw in multimedia_keywords):
            return "multimedia"

        # 硬件检测类关键词
        hardware_keywords = ["硬件", "gpu", "显卡", "设备", "硬件检测",
                             "hardware", "设备状态", "能不能生成"]
        if any(kw in prompt_lower for kw in hardware_keywords):
            return "hardware"

        # 风格调整类关键词
        style_keywords = ["风格", "style", "语气", "改成", "换一种",
                          "更正式", "更活泼", "更幽默", "更文艺"]
        if any(kw in prompt_lower for kw in style_keywords):
            return "style"

        # 文案生成类关键词（默认）
        copy_keywords = ["写", "文案", "文章", "作文", "稿子", "标题",
                         "广告语", " slogan", "copy", "write", "创作"]
        if any(kw in prompt_lower for kw in copy_keywords):
            return "copy"

        # 默认：文案生成
        return "copy"

    # ── 文案生成 ────────────────────────────────────────────────────────

    async def _do_generate_copy(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """生成文案内容

        Returns: (回答文本, 输入tokens, 输出tokens)
        """
        assert self._http_client is not None

        m6_url = self._config["m6_base_url"].rstrip("/")
        style = metadata.get("style", self._config["default_style"])
        tone = metadata.get("tone", "friendly")
        length = metadata.get("length", "medium")

        try:
            # 调用 M6 文案生成接口
            payload = {
                "prompt": prompt,
                "style": style,
                "tone": tone,
                "length": length,
                "creativity": self._config.get("creativity_level", 0.8),
                "variants": metadata.get("variants", 3),
            }
            response = await self._http_client.post(
                f"{m6_url}/api/v1/copy/generate",
                json=payload,
                timeout=15.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M6 copy generation failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            copies = result.get("copies", result.get("variants", []))

        except Exception as exc:
            self._logger.warning("copy_gen_failed", error=str(exc))
            # 降级：用 LLM 直接生成
            return await self._llm_copy(prompt, style)

        if not copies:
            return await self._llm_copy(prompt, style)

        # 格式化结果
        answer = "✨ 为你生成了以下文案：\n\n"
        for i, copy_item in enumerate(copies, 1):
            if isinstance(copy_item, dict):
                content = copy_item.get("content", copy_item.get("text", str(copy_item)))
                title = copy_item.get("title", f"方案{i}")
                answer += f"【{title}】\n{content}\n\n"
            else:
                answer += f"方案 {i}：\n{copy_item}\n\n"

        answer += "💡 可以告诉我你更喜欢哪个，我可以在此基础上继续优化。"

        return answer, len(prompt) // 4, len(answer) // 4

    async def _llm_copy(self, prompt: str, style: str) -> tuple[str, int, int]:
        """用 LLM 生成文案（降级路径）"""
        style_desc = {
            "creative": "富有创意、独特新颖",
            "professional": "专业严谨、正式规范",
            "friendly": "亲切友好、温暖自然",
            "humorous": "幽默风趣、轻松活泼",
            "elegant": "优雅精致、有品味",
        }.get(style, "富有创意")

        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": (
                    f"{self._SYSTEM_PROMPT}\n\n"
                    f"当前创作风格要求：{style_desc}。"
                    "请提供3个不同风格的方案供用户选择。"
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=self._config.get("temperature", 0.9),
            max_tokens=1000,
        )
        return answer, in_tok, out_tok

    # ── 图片描述 ────────────────────────────────────────────────────────

    async def _do_image_caption(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """图片描述生成"""
        assert self._http_client is not None

        m6_url = self._config["m6_base_url"].rstrip("/")
        image_path = metadata.get("image_path", "")
        image_url = metadata.get("image_url", "")

        if not image_path and not image_url:
            return (
                "🖼️  图片描述生成\n\n"
                "⚠️  请提供图片路径或图片URL。\n"
                "💡 你可以通过 metadata.image_path 或 metadata.image_url 传入图片。"
            ), len(prompt) // 4, 0

        try:
            payload = {
                "prompt": prompt,
                "image_path": image_path,
                "image_url": image_url,
                "detail_level": metadata.get("detail_level", "medium"),
                "style": metadata.get("caption_style", "descriptive"),
            }
            response = await self._http_client.post(
                f"{m6_url}/api/v1/image/caption",
                json=payload,
                timeout=15.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M6 image caption failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            caption = result.get("caption", result.get("description", ""))
            tags = result.get("tags", [])

        except Exception as exc:
            self._logger.warning("image_caption_failed", error=str(exc))
            return (
                f"⚠️  图片描述生成失败：{exc}\n"
                "💡 请确保图片生成服务可用。"
            ), len(prompt) // 4, 0

        answer = "🖼️  图片描述\n\n"
        answer += f"{caption}\n\n"

        if tags:
            answer += f"🏷️  标签: {', '.join(tags[:10])}\n"

        answer += "\n💡 需要更详细的描述或特定角度的解读吗？"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 创意构思 ────────────────────────────────────────────────────────

    async def _do_brainstorm(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """创意头脑风暴"""
        assert self._http_client is not None

        m6_url = self._config["m6_base_url"].rstrip("/")

        try:
            payload = {
                "topic": prompt,
                "method": metadata.get("method", "scamper"),
                "count": metadata.get("count", 10),
                "category": metadata.get("category", "general"),
            }
            response = await self._http_client.post(
                f"{m6_url}/api/v1/brainstorm/generate",
                json=payload,
                timeout=15.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M6 brainstorm failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            ideas = result.get("ideas", result.get("results", []))

        except Exception as exc:
            self._logger.warning("brainstorm_failed", error=str(exc))
            # 降级：用 LLM 头脑风暴
            return await self._llm_brainstorm(prompt, metadata)

        if not ideas:
            return await self._llm_brainstorm(prompt, metadata)

        answer = f"💡 创意头脑风暴：{prompt}\n\n"
        for i, idea in enumerate(ideas, 1):
            if isinstance(idea, dict):
                title = idea.get("title", idea.get("name", f"创意{i}"))
                description = idea.get("description", idea.get("detail", ""))
                category = idea.get("category", "")
                cat_tag = f" [{category}]" if category else ""
                answer += f"{i}. ✨ {title}{cat_tag}\n"
                if description:
                    answer += f"   {description}\n"
            else:
                answer += f"{i}. ✨ {idea}\n"
            answer += "\n"

        answer += "🚀 这些创意怎么样？选一个我帮你深入展开！"

        return answer, len(prompt) // 4, len(answer) // 4

    async def _llm_brainstorm(
        self, prompt: str, metadata: dict[str, Any]
    ) -> tuple[str, int, int]:
        """用 LLM 进行头脑风暴（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"请围绕「{prompt}」进行头脑风暴，\n"
                    "提供10个有创意的想法，每个想法用一句话描述。\n"
                    "要多样化，涵盖不同角度和方向。"
                )},
            ],
            temperature=self._config.get("temperature", 0.9),
            max_tokens=800,
        )
        return f"💡 创意头脑风暴\n\n{answer}", in_tok, out_tok

    # ── 内容排版 ────────────────────────────────────────────────────────

    async def _do_format(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """内容排版优化"""
        assert self._http_client is not None

        m6_url = self._config["m6_base_url"].rstrip("/")
        content = metadata.get("content", prompt)
        format_type = metadata.get("format_type", "markdown")

        try:
            payload = {
                "content": content,
                "format": format_type,
                "style": metadata.get("format_style", "elegant"),
                "target_platform": metadata.get("platform", "general"),
            }
            response = await self._http_client.post(
                f"{m6_url}/api/v1/format/beautify",
                json=payload,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M6 format failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            formatted = result.get("formatted_content", result.get("content", ""))

        except Exception as exc:
            self._logger.warning("format_failed", error=str(exc))
            return await self._llm_format(content, format_type)

        answer = "🎨 排版优化结果\n\n"
        answer += f"输出格式: {format_type}\n\n"
        answer += "---\n\n"
        answer += formatted
        answer += "\n\n---\n\n"
        answer += "💡 需要调整格式或风格吗？告诉我你的需求。"

        return answer, len(prompt) // 4, len(answer) // 4

    async def _llm_format(
        self, content: str, format_type: str
    ) -> tuple[str, int, int]:
        """用 LLM 排版（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"请将以下内容优化排版，输出格式为 {format_type}：\n\n"
                    f"{content}"
                )},
            ],
            temperature=0.5,
            max_tokens=1000,
        )
        return f"🎨 排版优化结果\n\n{answer}", in_tok, out_tok

    # ── 多媒体脚本 ──────────────────────────────────────────────────────

    async def _do_multimedia(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """多媒体脚本生成"""
        assert self._http_client is not None

        m6_url = self._config["m6_base_url"].rstrip("/")
        media_type = metadata.get("media_type", "video")

        try:
            payload = {
                "topic": prompt,
                "media_type": media_type,
                "duration_minutes": metadata.get("duration", 3),
                "style": metadata.get("style", "engaging"),
            }
            response = await self._http_client.post(
                f"{m6_url}/api/v1/multimedia/script",
                json=payload,
                timeout=15.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M6 multimedia script failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            script = result.get("script", result.get("content", ""))
            scenes = result.get("scenes", [])

        except Exception as exc:
            self._logger.warning("multimedia_script_failed", error=str(exc))
            return await self._llm_multimedia(prompt, media_type)

        answer = f"🎬 {media_type.upper()} 脚本\n\n"
        answer += f"主题: {prompt}\n"
        answer += f"预计时长: {metadata.get('duration', 3)} 分钟\n\n"

        if scenes:
            answer += "📋 分镜大纲：\n"
            for i, scene in enumerate(scenes, 1):
                title = scene.get("title", scene.get("name", f"场景{i}"))
                answer += f"  {i}. {title}\n"
            answer += "\n"

        answer += "---\n\n"
        answer += script
        answer += "\n\n---\n"

        return answer, len(prompt) // 4, len(answer) // 4

    async def _llm_multimedia(
        self, prompt: str, media_type: str
    ) -> tuple[str, int, int]:
        """用 LLM 生成多媒体脚本（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"请为「{prompt}」创作一个{media_type}脚本。\n"
                    "包含分镜大纲和详细脚本内容。"
                )},
            ],
            temperature=0.8,
            max_tokens=1000,
        )
        return f"🎬 {media_type.upper()} 脚本\n\n{answer}", in_tok, out_tok

    # ── 硬件检测 ────────────────────────────────────────────────────────

    async def _do_hardware_check(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """检测创意硬件状态"""
        assert self._http_client is not None

        m6_url = self._config["m6_base_url"].rstrip("/")

        try:
            response = await self._http_client.get(
                f"{m6_url}/api/v1/hardware/status",
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M6 hardware check failed: HTTP {response.status_code}")

            data = response.json()
            hw_info = data.get("result", data)
            self._hardware_info = hw_info

        except Exception as exc:
            self._logger.warning("hardware_check_failed", error=str(exc))
            hw_info = {}

        answer = "🖥️  创意硬件状态\n\n"

        # GPU 状态
        gpu_info = hw_info.get("gpu", hw_info.get("gpus", []))
        if isinstance(gpu_info, list) and gpu_info:
            answer += "🎮 GPU:\n"
            for i, gpu in enumerate(gpu_info, 1):
                name = gpu.get("name", gpu.get("model", f"GPU {i}"))
                vram = gpu.get("vram_total", gpu.get("memory", "?"))
                answer += f"   {i}. {name} ({vram})\n"
        elif isinstance(gpu_info, dict):
            answer += f"🎮 GPU: {gpu_info.get('name', '未知')}\n"

        # 图片生成能力
        image_gen = hw_info.get("image_generation", hw_info.get("image_gen", {}))
        if image_gen:
            available = image_gen.get("available", False)
            status_icon = "✅" if available else "❌"
            answer += f"\n🖼️  图片生成: {status_icon} "
            if available:
                model = image_gen.get("model", "未知模型")
                answer += f"{model}\n"
            else:
                answer += "不可用\n"

        # 音频生成能力
        audio_gen = hw_info.get("audio_generation", hw_info.get("audio_gen", {}))
        if audio_gen:
            available = audio_gen.get("available", False)
            status_icon = "✅" if available else "❌"
            answer += f"🎵 音频生成: {status_icon}\n"

        if not hw_info:
            answer += "⚠️  暂时无法获取硬件状态信息。\n"
            answer += "💡 请确保 M6 创意内容服务已启动。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 风格调整 ────────────────────────────────────────────────────────

    async def _do_style_adjust(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """风格调整说明"""
        current_style = self._config.get("default_style", "creative")

        styles = {
            "creative": {"name": "创意风格", "icon": "✨", "desc": "富有创意、独特新颖、灵感迸发"},
            "professional": {"name": "专业风格", "icon": "💼", "desc": "专业严谨、正式规范、逻辑清晰"},
            "friendly": {"name": "亲切风格", "icon": "💖", "desc": "亲切友好、温暖自然、像朋友聊天"},
            "humorous": {"name": "幽默风格", "icon": "😄", "desc": "幽默风趣、轻松活泼、让人会心一笑"},
            "elegant": {"name": "优雅风格", "icon": "🌸", "desc": "优雅精致、有品味、文字优美"},
        }

        answer = "🎨 创作风格\n\n"
        answer += f"当前风格: {styles.get(current_style, {}).get('name', current_style)}\n\n"

        answer += "可选风格：\n"
        for sid, info in styles.items():
            current_mark = "  ← 当前" if sid == current_style else ""
            answer += f"  {info['icon']} {info['name']}{current_mark}\n"
            answer += f"     {info['desc']}\n\n"

        answer += "💡 可以通过 metadata.style 指定创作风格。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── LLM 辅助回答 ────────────────────────────────────────────────────

    async def _llm_answer(self, prompt: str, prefix: str) -> tuple[str, int, int]:
        """用 LLM 直接回答（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": f"{prefix}\n\n用户问题：{prompt}"},
            ],
            temperature=self._config.get("temperature", 0.9),
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
            self._logger.debug("content_manager_http_client_created")

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
