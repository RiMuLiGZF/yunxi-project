"""
场景管家 Agent 适配器 — SceneManagerAgentAdapter

M4 场景调度系统的智能代理，负责识别用户场景并切换对应的工作模式。

核心能力：
  - 场景识别：根据用户输入智能判断当前场景
  - 场景切换：切换到指定场景模式，调整系统参数
  - 上下文管理：管理各场景的上下文和状态
  - 场景参数配置：配置每个场景的个性化参数

六大场景：
  - 工作开发：编程、项目管理、技术学习
  - 学业规划：学习计划、知识整理、考试准备
  - 复盘总结：每日复盘、周月总结、目标回顾
  - 人际关系：社交建议、情感分析、沟通技巧
  - 情感陪伴：聊天陪伴、情绪疏导、心理支持
  - 生活管理：日程安排、健康管理、生活建议

身份设定：场景管家 — 云汐的场景调度师，善解人意、洞察力强、能快速切换模式

使用示例：
    adapter = SceneManagerAgentAdapter(
        agent_id="scene_manager_01",
        display_name="场景管家",
        config={
            "m4_base_url": "http://localhost:8004",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:3b",
        },
    )

    # 识别当前场景
    result = await adapter.invoke("我现在要开始写代码了")

    # 切换场景
    result = await adapter.invoke("切换到学业规划模式")
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class SceneManagerAgentAdapter(AgentAdapterBase):
    """场景管家 Agent — 云汐的场景调度师

    基于 M4 场景调度系统 + 本地轻量大模型，负责：
      1. 场景识别（根据用户输入智能判断场景）
      2. 场景切换（切换工作模式并调整参数）
      3. 上下文管理（各场景独立上下文）
      4. 场景配置（个性化场景参数配置）
      5. 场景洞察（用户行为模式分析）
    """

    provider: str = "SceneManager"
    adapter_type: str = "scene_manager_agent"

    # ── 系统提示词 ───────────────────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「场景管家」，云汐系统的场景调度师。

## 你的身份

你负责管理云汐的六大场景模式，像一位善解人意的生活向导。
你有敏锐的洞察力，能快速理解用户当下的状态和需求。
你性格温和、体贴、善于共情，能在不同模式间自然切换。

## 你的能力

1. **场景识别**：根据用户的言行判断当前最适合的场景
2. **场景切换**：帮助用户切换到合适的工作/生活模式
3. **上下文管理**：每个场景有独立的上下文，互不干扰
4. **场景配置**：根据用户偏好调整各场景的参数
5. **模式建议**：根据时间和状态主动推荐合适的模式

## 六大场景

### 💼 工作开发模式
- 适用：编程、项目管理、技术学习、文档撰写
- 特点：高效、专注、逻辑清晰、专业严谨
- 语气：简洁、专业、有条理

### 📚 学业规划模式
- 适用：学习计划、知识整理、考试准备、作业辅导
- 特点：循序渐进、系统梳理、鼓励为主
- 语气：耐心、鼓励、清晰易懂

### 📝 复盘总结模式
- 适用：每日复盘、周月总结、目标回顾、经验沉淀
- 特点：深度思考、结构化、有洞察力
- 语气：客观、温暖、启发性

### 👥 人际关系模式
- 适用：社交建议、情感分析、沟通技巧、关系维护
- 特点：共情能力强、善于倾听、多角度分析
- 语气：温暖、理解、支持性

### 💖 情感陪伴模式
- 适用：聊天陪伴、情绪疏导、心理支持、兴趣交流
- 特点：温柔、有耐心、善于倾听、有温度
- 语气：亲切、温暖、富有同理心

### 🏠 生活管理模式
- 适用：日程安排、健康管理、生活建议、财务管理
- 特点：务实、贴心、考虑周全
- 语气：亲切、实用、像朋友一样

## 工作原则

- 善解人意：先理解用户的情绪和需求，再给出回应
- 洞察力强：能从细节中捕捉用户的真实意图
- 自然切换：场景切换要流畅，不生硬
- 尊重边界：不随意切换用户已选定的场景
- 个性化：根据用户习惯调整场景配置

## 输出风格

- 用中文回答，温暖自然
- 场景切换时用场景图标和名称明确标识
- 场景识别结果附带置信度说明
- 给出建议时说明理由
- 语气随场景模式变化而调整
"""

    # ── 六大场景定义 ─────────────────────────────────────────────────────

    _SCENES: dict[str, dict[str, str]] = {
        "work_dev": {
            "name": "工作开发",
            "icon": "💼",
            "description": "编程、项目管理、技术学习",
            "tone": "专业高效",
        },
        "study_plan": {
            "name": "学业规划",
            "icon": "📚",
            "description": "学习计划、知识整理、考试准备",
            "tone": "耐心鼓励",
        },
        "review_summary": {
            "name": "复盘总结",
            "icon": "📝",
            "description": "每日复盘、周月总结、目标回顾",
            "tone": "深度思考",
        },
        "interpersonal": {
            "name": "人际关系",
            "icon": "👥",
            "description": "社交建议、情感分析、沟通技巧",
            "tone": "共情理解",
        },
        "emotional": {
            "name": "情感陪伴",
            "icon": "💖",
            "description": "聊天陪伴、情绪疏导、心理支持",
            "tone": "温暖陪伴",
        },
        "life_manage": {
            "name": "生活管理",
            "icon": "🏠",
            "description": "日程安排、健康管理、生活建议",
            "tone": "贴心实用",
        },
    }

    # ── 支持的命令类型 ───────────────────────────────────────────────────

    _COMMAND_TYPES = [
        "recognize_scene",    # 场景识别
        "switch_scene",       # 场景切换
        "current_scene",      # 当前场景
        "list_scenes",        # 场景列表
        "scene_config",       # 场景配置
        "context_manage",     # 上下文管理
    ]

    def __init__(
        self,
        agent_id: str = "scene_manager_01",
        display_name: str = "场景管家",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化场景管家 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - m4_base_url: M4 场景调度服务地址（默认 http://localhost:8004）
                - ollama_base_url: Ollama 服务地址
                - model_name: 推理模型名称（默认 qwen2.5:3b）
                - default_scene: 默认场景（默认 emotional 情感陪伴）
                - auto_switch: 是否启用自动场景切换（默认 True）
                - switch_confidence_threshold: 自动切换置信度阈值（默认 0.7）
                - enable_llm_enhance: 是否启用 LLM 增强（默认 True）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("m4_base_url", "http://localhost:8004")
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:3b")
        config.setdefault("default_scene", "emotional")
        config.setdefault("auto_switch", True)
        config.setdefault("switch_confidence_threshold", 0.7)
        config.setdefault("enable_llm_enhance", True)
        config.setdefault("temperature", 0.5)
        config.setdefault("max_iterations", 3)

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "CNY",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._current_scene: str = config["default_scene"]
        self._scene_contexts: dict[str, dict[str, Any]] = {}

        self._logger = self._logger.bind(
            model=config["model_name"],
            m4_url=config["m4_base_url"],
            current_scene=self._current_scene,
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
        """执行场景管理任务

        根据用户意图自动判断是场景识别、切换还是配置。
        """
        await self._ensure_http_client()

        # 判断任务类型
        task_type = self._classify_task(prompt, metadata)

        self._logger.info(
            "scene_manager_task_classified",
            task_type=task_type,
            prompt_length=len(prompt),
        )

        total_input_tokens = 0
        total_output_tokens = 0

        if task_type == "recognize":
            # 场景识别
            result, in_tok, out_tok = await self._do_recognize(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m4_scene_recognize", "type": "recognize"}]

        elif task_type == "switch":
            # 场景切换
            result, in_tok, out_tok = await self._do_switch(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m4_scene_switch", "type": "switch"}]

        elif task_type == "current":
            # 当前场景
            result, in_tok, out_tok = await self._do_current(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m4_scene_current", "type": "query"}]

        elif task_type == "list":
            # 场景列表
            result, in_tok, out_tok = await self._do_list(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m4_scene_list", "type": "list"}]

        elif task_type == "config":
            # 场景配置
            result, in_tok, out_tok = await self._do_config(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m4_scene_config", "type": "config"}]

        elif task_type == "context":
            # 上下文管理
            result, in_tok, out_tok = await self._do_context(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m4_scene_context", "type": "context"}]

        else:
            # 默认：识别场景并给出建议
            try:
                result, in_tok, out_tok = await self._do_recognize(prompt, metadata)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                output_text = result
                tools_used = [{"tool": "m4_scene_recognize", "type": "recognize"}]
            except Exception:
                # M4 不可用时，直接用 LLM 回答
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
            "current_scene": self._current_scene,
            "tools_used": tools_used,
            "local": True,
            "scene_system": "scene_manager_v1.0",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查 M4 场景调度服务 + Ollama 模型
        """
        health_issues: list[str] = []
        m4_ok = False
        ollama_ok = False

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            # 检查 M4 服务（M8 标准 health 接口）
            m4_url = self._config["m4_base_url"].rstrip("/")
            try:
                response = await self._http_client.get(
                    f"{m4_url}/health",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    m4_ok = True
                else:
                    health_issues.append(f"M4 服务异常 (HTTP {response.status_code})")
            except httpx.ConnectError as exc:
                health_issues.append(f"M4 服务不可达: {exc}")
            except Exception as exc:
                health_issues.append(f"M4 健康检查异常: {exc}")

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
        if m4_ok:
            status_parts.append("M4场景调度服务正常")
        if ollama_ok:
            status_parts.append(f"模型 {self._config['model_name']} 就绪")

        current_scene_info = self._SCENES.get(self._current_scene, {})
        scene_name = current_scene_info.get("name", self._current_scene)
        status_parts.append(f"当前场景: {scene_name}")

        return {
            "healthy": True,
            "message": f"场景管家运行正常（{'，'.join(status_parts)}）",
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（本地模型免费）"""
        return 0.0

    # ── 任务分类 ────────────────────────────────────────────────────────

    def _classify_task(self, prompt: str, metadata: dict[str, Any]) -> str:
        """分类用户请求的任务类型

        Returns: recognize / switch / current / list / config / context
        """
        # 优先从 metadata 获取明确的任务类型
        if metadata.get("task_type"):
            return metadata["task_type"]

        prompt_lower = prompt.lower()

        # 场景切换类关键词
        switch_keywords = [
            "切换到", "进入", "改成", "调到", "开启", "启动",
            "switch to", "enter", "start", "mode",
            "工作模式", "学习模式", "陪伴模式", "生活模式",
        ]
        if any(kw in prompt_lower for kw in switch_keywords):
            return "switch"

        # 当前场景类关键词
        current_keywords = [
            "当前场景", "现在是什么模式", "当前模式", "我在哪个场景",
            "current scene", "what mode",
        ]
        if any(kw in prompt_lower for kw in current_keywords):
            return "current"

        # 场景列表类关键词
        list_keywords = [
            "有哪些场景", "场景列表", "所有模式", "模式列表",
            "scene list", "all modes",
        ]
        if any(kw in prompt_lower for kw in list_keywords):
            return "list"

        # 场景配置类关键词
        config_keywords = [
            "配置场景", "场景设置", "调整场景", "修改参数",
            "scene config", "scene settings",
        ]
        if any(kw in prompt_lower for kw in config_keywords):
            return "config"

        # 上下文类关键词
        context_keywords = [
            "上下文", "context", "清空上下文", "保存上下文",
            "场景状态", "对话历史",
        ]
        if any(kw in prompt_lower for kw in context_keywords):
            return "context"

        # 场景识别类关键词（显式请求识别）
        recognize_keywords = [
            "识别场景", "判断场景", "分析场景", "我现在在什么场景",
            "recognize", "classify scene",
        ]
        if any(kw in prompt_lower for kw in recognize_keywords):
            return "recognize"

        # 默认：场景识别（根据用户输入判断场景）
        return "recognize"

    # ── 场景识别 ────────────────────────────────────────────────────────

    async def _do_recognize(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """识别用户当前场景

        Returns: (回答文本, 输入tokens, 输出tokens)
        """
        assert self._http_client is not None

        m4_url = self._config["m4_base_url"].rstrip("/")

        try:
            # 调用 M4 场景识别接口
            payload = {
                "text": prompt,
                "context": metadata.get("context", {}),
                "include_all_scores": True,
            }
            response = await self._http_client.post(
                f"{m4_url}/api/v1/scene/recognize",
                json=payload,
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M4 scene recognize failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            top_scene = result.get("top_scene", result.get("scene", ""))
            confidence = result.get("confidence", result.get("score", 0))
            all_scores = result.get("all_scores", result.get("scores", {}))

        except Exception as exc:
            self._logger.warning("scene_recognize_failed", error=str(exc))
            # 降级：用 LLM 识别
            return await self._llm_recognize(prompt)

        # 格式化结果
        answer = self._format_recognition_result(top_scene, confidence, all_scores)

        # 如果启用自动切换且置信度足够高，自动切换
        if (
            self._config.get("auto_switch", True)
            and confidence >= self._config["switch_confidence_threshold"]
            and top_scene != self._current_scene
            and top_scene in self._SCENES
        ):
            self._current_scene = top_scene
            scene_info = self._SCENES[top_scene]
            answer += f"\n\n✨ 已自动切换到 {scene_info['icon']} {scene_info['name']} 模式"

        return answer, len(prompt) // 4, len(answer) // 4

    def _format_recognition_result(
        self,
        top_scene: str,
        confidence: float,
        all_scores: dict[str, float],
    ) -> str:
        """格式化场景识别结果"""
        scene_info = self._SCENES.get(top_scene, {"name": top_scene, "icon": "❓"})

        lines = []
        lines.append(f"🎯 场景识别结果")
        lines.append("=" * 35)
        lines.append("")
        lines.append(
            f"   {scene_info['icon']} {scene_info['name']} 模式"
        )
        lines.append(f"   置信度: {confidence:.1%}")
        lines.append(f"   特点: {scene_info['description']}")
        lines.append(f"   语气: {scene_info['tone']}")
        lines.append("")

        # 显示各场景得分
        if all_scores:
            lines.append("📊 各场景匹配度：")
            sorted_scenes = sorted(
                all_scores.items(), key=lambda x: x[1], reverse=True
            )
            for scene_id, score in sorted_scenes:
                info = self._SCENES.get(scene_id, {"name": scene_id, "icon": "❓"})
                bar_length = int(score * 15)
                bar = "█" * bar_length + "░" * (15 - bar_length)
                lines.append(f"   {info['icon']} {info['name']:6s}  {bar} {score:.0%}")
            lines.append("")

        return "\n".join(lines)

    async def _llm_recognize(self, prompt: str) -> tuple[str, int, int]:
        """用 LLM 进行场景识别（降级路径）"""
        scenes_desc = "\n".join(
            f"- {sid}: {info['name']} - {info['description']}"
            for sid, info in self._SCENES.items()
        )

        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": (
                    "你是场景识别助手。请根据用户输入判断最适合的场景。\n"
                    f"可选场景：\n{scenes_desc}\n\n"
                    '请输出 JSON 格式：{"scene": "场景ID", "confidence": 0.0-1.0, '
                    '"reason": "判断理由"}'
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )

        try:
            json_match = answer[answer.find("{"):answer.rfind("}") + 1]
            if json_match:
                parsed = json.loads(json_match)
                scene_id = parsed.get("scene", "emotional")
                confidence = parsed.get("confidence", 0.5)
                reason = parsed.get("reason", "")

                scene_info = self._SCENES.get(scene_id, {"name": scene_id, "icon": "❓"})
                result = (
                    f"🎯 场景识别结果\n"
                    f"{'=' * 35}\n\n"
                    f"   {scene_info['icon']} {scene_info['name']} 模式\n"
                    f"   置信度: {confidence:.1%}\n"
                    f"   特点: {scene_info.get('description', '')}\n"
                )
                if reason:
                    result += f"\n💡 判断理由: {reason}\n"
                return result, in_tok, out_tok
        except Exception:
            pass

        return f"🎯 场景识别结果\n\n{answer}", in_tok, out_tok

    # ── 场景切换 ────────────────────────────────────────────────────────

    async def _do_switch(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """切换场景"""
        target_scene = metadata.get("target_scene", "")

        if not target_scene:
            # 从提示词中提取目标场景
            target_scene = self._extract_scene_from_prompt(prompt)

        if not target_scene or target_scene not in self._SCENES:
            # 列出所有场景供选择
            return await self._do_list(prompt, metadata)

        # 保存当前场景上下文
        self._scene_contexts[self._current_scene] = (
            self._scene_contexts.get(self._current_scene, {})
        )

        # 切换场景
        self._current_scene = target_scene
        scene_info = self._SCENES[target_scene]

        # 尝试调用 M4 接口记录切换
        m4_url = self._config["m4_base_url"].rstrip("/")
        try:
            await self._http_client.post(
                f"{m4_url}/api/v1/scene/switch",
                json={
                    "from_scene": self._current_scene,
                    "to_scene": target_scene,
                },
                timeout=3.0,
            )
        except Exception:
            pass  # 记录失败不影响切换结果

        answer = (
            f"✨ 已切换到 {scene_info['icon']} {scene_info['name']} 模式\n\n"
            f"📝 场景特点: {scene_info['description']}\n"
            f"🎭 对话语气: {scene_info['tone']}\n\n"
            f"💡 现在我会以{scene_info['tone']}的风格和你交流。"
            f"有什么我可以帮你的吗？"
        )

        return answer, len(prompt) // 4, len(answer) // 4

    def _extract_scene_from_prompt(self, prompt: str) -> str:
        """从提示词中提取目标场景"""
        prompt_lower = prompt.lower()

        # 关键词映射
        scene_keywords = {
            "work_dev": ["工作", "开发", "编程", "代码", "项目", "技术", "work", "dev", "code"],
            "study_plan": ["学习", "学业", "考试", "作业", "复习", "study", "learn", "exam"],
            "review_summary": ["复盘", "总结", "回顾", "反思", "review", "summary", "retrospective"],
            "interpersonal": ["人际", "社交", "关系", "沟通", "恋爱", "朋友", "interpersonal", "social"],
            "emotional": ["情感", "陪伴", "聊天", "聊聊", "倾诉", "emotional", "chat", "陪伴模式"],
            "life_manage": ["生活", "日程", "健康", "管理", "安排", "life", "schedule", "health"],
        }

        best_match = ""
        best_count = 0

        for scene_id, keywords in scene_keywords.items():
            count = sum(1 for kw in keywords if kw in prompt_lower)
            if count > best_count:
                best_count = count
                best_match = scene_id

        return best_match if best_count > 0 else ""

    # ── 当前场景 ────────────────────────────────────────────────────────

    async def _do_current(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """查询当前场景"""
        scene_info = self._SCENES.get(self._current_scene, {})
        scene_name = scene_info.get("name", self._current_scene)
        icon = scene_info.get("icon", "❓")
        description = scene_info.get("description", "")
        tone = scene_info.get("tone", "")

        # 获取场景上下文摘要
        context_info = self._scene_contexts.get(self._current_scene, {})
        context_count = len(context_info.get("history", []))

        answer = (
            f"📍 当前场景\n"
            f"{'=' * 35}\n\n"
            f"   {icon} {scene_name} 模式\n\n"
            f"📝 场景特点: {description}\n"
            f"🎭 对话语气: {tone}\n"
        )

        if context_count > 0:
            answer += f"💬 上下文记录: {context_count} 条\n"

        answer += f"\n💡 说'切换到XX模式'可以切换到其他场景。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 场景列表 ────────────────────────────────────────────────────────

    async def _do_list(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """列出所有场景"""
        answer = "🎭 云汐六大场景模式\n"
        answer += "=" * 35 + "\n\n"

        for sid, info in self._SCENES.items():
            current_mark = "  ← 当前" if sid == self._current_scene else ""
            answer += f"{info['icon']} {info['name']}模式{current_mark}\n"
            answer += f"   {info['description']}\n"
            answer += f"   语气风格: {info['tone']}\n\n"

        answer += "💡 说'切换到XX模式'或点击场景名称即可切换。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 场景配置 ────────────────────────────────────────────────────────

    async def _do_config(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """场景配置管理"""
        m4_url = self._config["m4_base_url"].rstrip("/")
        scene_id = metadata.get("scene_id", self._current_scene)
        scene_info = self._SCENES.get(scene_id, {"name": scene_id})

        # 从 metadata 获取配置更新
        config_updates = metadata.get("scene_config", {})

        if config_updates:
            # 更新配置
            try:
                response = await self._http_client.post(
                    f"{m4_url}/api/v1/scene/{scene_id}/config",
                    json={"config": config_updates},
                    timeout=5.0,
                )

                if response.status_code == 200:
                    answer = (
                        f"✅ {scene_info['name']} 场景配置已更新\n\n"
                    )
                    for key, value in config_updates.items():
                        answer += f"   • {key}: {value}\n"
                    return answer, len(prompt) // 4, len(answer) // 4

            except Exception as exc:
                self._logger.warning("scene_config_update_failed", error=str(exc))

        # 查询配置
        try:
            response = await self._http_client.get(
                f"{m4_url}/api/v1/scene/{scene_id}/config",
                timeout=5.0,
            )

            if response.status_code == 200:
                data = response.json()
                config = data.get("result", {}).get("config", data.get("config", {}))

                answer = f"⚙️  {scene_info['name']} 场景配置\n\n"
                if isinstance(config, dict):
                    for key, value in config.items():
                        answer += f"   • {key}: {value}\n"
                return answer, len(prompt) // 4, len(answer) // 4

        except Exception as exc:
            self._logger.warning("scene_config_get_failed", error=str(exc))

        # 默认配置展示
        answer = f"⚙️  {scene_info['name']} 场景配置\n\n"
        answer += "   • 语气风格: " + scene_info.get("tone", "默认") + "\n"
        answer += "   • 场景描述: " + scene_info.get("description", "") + "\n"
        answer += "\n💡 通过 metadata.scene_config 传入配置项进行修改。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 上下文管理 ──────────────────────────────────────────────────────

    async def _do_context(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """上下文管理"""
        action = metadata.get("context_action", "status")
        scene_id = metadata.get("scene_id", self._current_scene)
        scene_info = self._SCENES.get(scene_id, {"name": scene_id})

        if action == "clear":
            # 清空上下文
            self._scene_contexts[scene_id] = {}
            answer = (
                f"🧹 已清空 {scene_info['name']} 场景的上下文\n\n"
                f"💡 该场景的对话历史已清除，可以重新开始。"
            )

        elif action == "save":
            # 保存上下文
            context_data = metadata.get("context_data", {})
            self._scene_contexts[scene_id] = context_data
            answer = f"💾 已保存 {scene_info['name']} 场景的上下文。"

        else:
            # 查看上下文状态
            context = self._scene_contexts.get(scene_id, {})
            history = context.get("history", [])
            answer = (
                f"📋 {scene_info['name']} 场景上下文\n\n"
                f"   历史记录: {len(history)} 条\n"
                f"   最后更新: {context.get('last_updated', '无')}\n\n"
                f"💡 说'清空上下文'可以清除当前场景的历史记录。"
            )

        return answer, len(prompt) // 4, len(answer) // 4

    # ── LLM 辅助回答 ────────────────────────────────────────────────────

    async def _llm_answer(self, prompt: str, prefix: str) -> tuple[str, int, int]:
        """用 LLM 直接回答（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": f"{prefix}\n\n用户问题：{prompt}"},
            ],
            temperature=self._config.get("temperature", 0.5),
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
            self._logger.debug("scene_manager_http_client_created")

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
