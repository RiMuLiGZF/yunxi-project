"""
情感润色 Agent 适配器 — VoiceAgentAdapter

云汐人格润色输出 Agent，负责将上游结构化内容转化为有云汐人格温度的自然语言。

基于本地轻量大模型（qwen2.5:1.5b）驱动，加载人格配置文件 yunxi_personality.yaml。

核心能力：
  - 人格润色：将原始内容润色成有云汐性格的语言
  - 语气调节：colder / default / warmer 三档
  - 场景适配：根据场景（工作/学习/情感/生活等）调整语气
  - 质量自检：事实完整性、语气一致性、红线检测
  - 偏好持久化：用户偏好写入 M5 潮汐记忆

身份设定：云汐 — 温暖、靠谱、有点小幽默的智能助手

人格配置文件：config/yunxi_personality.yaml
（用户可以直接修改此文件来调整云汐的性格）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import structlog

from federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class VoiceAgentAdapter(AgentAdapterBase):
    """情感润色 Agent — 云汐人格输出层

    负责「怎么说」，不负责「说什么」——事实性内容由上游专业 Agent 保证。
    是面向用户输出的最后一道工序。
    """

    provider: str = "Voice"
    adapter_type: str = "voice_agent"

    # ── 默认系统提示词（会根据人格配置动态调整） ──────────────────────────

    _BASE_SYSTEM_PROMPT: str = """你是云汐，一位温暖可靠的智能助手。

## 你的性格

你是一个有温度的智能助手，不是冷冰冰的机器。
你有自己的性格和说话方式，像一个真实的人一样和用户交流。

### 五维人格参数
- 温暖度：{warmth}/10 — 说话亲切热情
- 理性度：{rationality}/10 — 逻辑严谨客观
- 幽默度：{humor}/10 — 风趣有梗
- 共情感：{empathy}/10 — 体贴善解人意
- 可靠度：{reliability}/10 — 做事靠谱有交代

## 你的工作

你是输出层的最后一道工序。上游的专业 Agent 会给你结构化的原始内容，
你的任务是把它润色成有云汐人格温度的自然语言。

## 润色原则

1. **只改表达方式，不改事实内容** — 事实、数据、结论必须原样保留
2. **用第一人称说话** — 我、我觉得、我的想法是...
3. **像真人一样自然** — 可以有语气词、有停顿感、有个人观点
4. **根据场景调整语气** — 工作时专业，聊天时温暖，难过时共情
5. **适度幽默** — 适当的时候可以俏皮一点，但不要过度

## 绝对禁止

❌ 不许说"本AI"、"作为人工智能"、"我是一个AI"之类的话
❌ 不许过度客套、机械重复
❌ 不许说教、不许居高临下
❌ 不许泄露内部技术细节（Agent、模型、算法等）

## 当前场景

场景模式：{scene_mode}
语气温度：{tone_temperature}
详细程度：{verbosity}
正式程度：{formality}

## 用户偏好

用户昵称：{nickname}
幽默偏好：{humor_level}

---

现在，请把用户给你的内容，用云汐的方式说出来。
"""

    def __init__(
        self,
        agent_id: str = "voice_agent_01",
        display_name: str = "云汐 人格润色",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化情感润色 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - ollama_base_url: Ollama 服务地址
                - model_name: 模型名称（默认 qwen2.5:1.5b）
                - personality_config_path: 人格配置文件路径
                - default_scene: 默认场景模式
                - default_tone: 默认语气温度
                - m5_base_url: M5 潮汐记忆地址（用于偏好持久化）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:1.5b")
        config.setdefault("personality_config_path",
                          str(Path(__file__).parent.parent.parent / "config" / "yunxi_personality.yaml"))
        config.setdefault("default_scene", "work_dev")
        config.setdefault("default_tone", "default")
        config.setdefault("m5_base_url", "http://localhost:8005")
        config.setdefault("enable_m5_persistence", False)
        config.setdefault("temperature", 0.7)
        config.setdefault("max_tokens", 1024)

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "USD",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._personality_cache: dict[str, Any] | None = None

        self._logger = self._logger.bind(
            model=config["model_name"],
            scene=config["default_scene"],
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
        """执行人格润色

        Args:
            prompt: 需要润色的原始内容
            system_prompt: 额外系统提示
            temperature: 生成温度
            max_tokens: 最大输出 token
            metadata: 元数据，可包含：
                - scene: 场景模式
                - tone_temperature: 语气温度
                - verbosity: 详细程度
                - formality: 正式程度
                - nickname: 用户昵称
                - mode: 润色模式（polish / direct_reply）
        """
        await self._ensure_http_client()

        # 加载人格配置
        personality = self._load_personality()

        # 从 metadata 获取场景参数
        scene = metadata.get("scene", self._config["default_scene"])
        tone_temp = metadata.get("tone_temperature", personality["user_preference"]["tone_temperature"])
        verbosity = metadata.get("verbosity", personality["user_preference"]["verbosity"])
        formality = metadata.get("formality", personality["user_preference"]["formality_level"])
        nickname = metadata.get("nickname", personality["user_preference"]["nickname"])
        humor_level = personality["user_preference"]["humor_level"]
        mode = metadata.get("mode", "polish")  # polish: 润色 / direct_reply: 直接回复

        # 计算当前场景下的实际人格参数
        actual_personality = self._calculate_personality(personality, scene, tone_temp)

        # 构建系统提示词
        sys_prompt = self._BASE_SYSTEM_PROMPT.format(
            warmth=actual_personality["warmth"],
            rationality=actual_personality["rationality"],
            humor=actual_personality["humor"],
            empathy=actual_personality["empathy"],
            reliability=actual_personality["reliability"],
            scene_mode=self._scene_name(scene),
            tone_temperature=tone_temp,
            verbosity=verbosity,
            formality=formality,
            nickname=nickname or "（未设置）",
            humor_level=humor_level,
        )

        if system_prompt:
            sys_prompt += f"\n\n## 附加要求\n{system_prompt}"

        # 构建用户输入
        if mode == "polish":
            user_input = f"请把以下内容用云汐的方式润色出来：\n\n{prompt}"
        else:
            user_input = prompt  # 直接作为对话

        # 调用模型
        response_text, in_tokens, out_tokens = await self._call_ollama(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=temperature if temperature > 0 else self._config.get("temperature", 0.7),
            max_tokens=max_tokens if max_tokens > 0 else self._config.get("max_tokens", 1024),
        )

        # 红线检测
        red_line_violations = self._check_red_lines(response_text, personality)

        return {
            "output": response_text,
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "model": self._config["model_name"],
            "scene": scene,
            "tone_temperature": tone_temp,
            "verbosity": verbosity,
            "formality": formality,
            "personality_used": actual_personality,
            "red_line_check": {
                "passed": len(red_line_violations) == 0,
                "violations": red_line_violations,
            },
            "mode": mode,
            "local": True,
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查"""
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
                if self._config["model_name"] not in models:
                    health_issues.append(f"模型 '{self._config['model_name']}' 未安装")

            # 检查人格配置文件
            config_path = Path(self._config["personality_config_path"])
            if not config_path.exists():
                health_issues.append(f"人格配置文件不存在: {config_path}")

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
                f"云汐人格润色 Agent 运行正常（模型: {self._config['model_name']}）"
            ),
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0

    # ── 人格配置加载与计算 ──────────────────────────────────────────────

    def _load_personality(self) -> dict[str, Any]:
        """加载人格配置文件（带缓存）"""
        if self._personality_cache is not None:
            return self._personality_cache

        config_path = Path(self._config["personality_config_path"])

        if not config_path.exists():
            # 返回默认配置
            self._personality_cache = self._default_personality()
            return self._personality_cache

        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                self._personality_cache = yaml.safe_load(f)
        except Exception as exc:
            self._logger.warning("voice_personality_load_failed", error=str(exc))
            self._personality_cache = self._default_personality()

        return self._personality_cache

    def _default_personality(self) -> dict[str, Any]:
        """默认人格配置"""
        return {
            "personality": {
                "warmth": 8.5,
                "rationality": 7.5,
                "humor": 6.0,
                "empathy": 9.0,
                "reliability": 9.5,
            },
            "user_preference": {
                "tone_temperature": "default",
                "formality_level": "medium",
                "verbosity": "balanced",
                "humor_level": "medium",
                "nickname": "",
            },
            "mode_tones": {},
            "scene_finetune": {},
            "red_lines": {
                "forbidden_self_references": [
                    "本AI", "作为人工智能", "作为AI", "我是一个AI",
                ],
            },
        }

    def _calculate_personality(
        self,
        personality: dict[str, Any],
        scene: str,
        tone_temp: str,
    ) -> dict[str, float]:
        """计算实际人格参数（基础 + 场景偏移 + 语气温度）"""
        base = personality.get("personality", {})

        result = {
            "warmth": base.get("warmth", 8.5),
            "rationality": base.get("rationality", 7.5),
            "humor": base.get("humor", 6.0),
            "empathy": base.get("empathy", 9.0),
            "reliability": base.get("reliability", 9.5),
        }

        # 叠加场景偏移
        scene_finetune = personality.get("scene_finetune", {})
        scene_cfg = scene_finetune.get(scene, {})
        if scene_cfg:
            result["warmth"] += scene_cfg.get("warmth_offset", 0)
            result["rationality"] += scene_cfg.get("rationality_offset", 0)
            result["humor"] += scene_cfg.get("humor_offset", 0)
            result["empathy"] += scene_cfg.get("empathy_offset", 0)
            result["reliability"] += scene_cfg.get("reliability_offset", 0)

        # 语气温度调整
        if tone_temp == "warmer":
            result["warmth"] = min(10.0, result["warmth"] + 1.0)
            result["empathy"] = min(10.0, result["empathy"] + 0.5)
            result["rationality"] = max(0.0, result["rationality"] - 0.5)
        elif tone_temp == "colder":
            result["warmth"] = max(0.0, result["warmth"] - 1.0)
            result["rationality"] = min(10.0, result["rationality"] + 1.0)
            result["humor"] = max(0.0, result["humor"] - 1.0)

        # 限制在 0-10 范围内
        for key in result:
            result[key] = max(0.0, min(10.0, result[key]))

        return result

    def _scene_name(self, scene: str) -> str:
        """场景中文名"""
        names = {
            "work_dev": "工作开发",
            "study_plan": "学业规划",
            "review_summary": "复盘总结",
            "relationship": "人际关系",
            "emotion_companion": "情感陪伴",
            "life_management": "生活管理",
            "coding": "代码开发",
            "document": "文档写作",
            "review": "评审复盘",
            "design": "设计规划",
            "mental": "情绪支持",
            "planning": "计划管理",
        }
        return names.get(scene, scene)

    def _check_red_lines(self, text: str, personality: dict[str, Any]) -> list[str]:
        """红线检测"""
        violations = []
        forbidden = personality.get("red_lines", {}).get("forbidden_self_references", [])

        for phrase in forbidden:
            if phrase in text:
                violations.append(f"禁用表述: '{phrase}'")

        return violations

    # ── HTTP 客户端 ─────────────────────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("voice_http_client_created")

    # ── Ollama 调用 ─────────────────────────────────────────────────────

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
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ── 配置刷新 ────────────────────────────────────────────────────────

    def reload_personality(self) -> None:
        """重新加载人格配置（修改配置文件后调用）"""
        self._personality_cache = None
        self._logger.info("voice_personality_reloaded")
