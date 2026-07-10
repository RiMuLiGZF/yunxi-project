"""
技能管家 Agent 适配器 — SkillManagerAgentAdapter

M2 技能管理系统的智能代理，负责技能的检索、推荐、注册和版本管理。

核心能力：
  - 技能检索：按关键词、标签、场景检索可用技能
  - 技能推荐：根据用户需求智能推荐最合适的技能
  - 技能注册：注册新技能到技能注册表
  - 技能版本管理：版本升级、回滚、兼容性检查
  - 技能沙箱管理：技能沙箱的创建、运行、销毁

身份设定：技能管家 — 云汐的技能管理员，有条理、善于推荐最合适的技能

使用示例：
    adapter = SkillManagerAgentAdapter(
        agent_id="skill_manager_01",
        display_name="技能管家",
        config={
            "m2_base_url": "http://localhost:8002",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:3b",
        },
    )

    # 检索技能
    result = await adapter.invoke("帮我找一下能写 Python 代码的技能")

    # 推荐技能
    result = await adapter.invoke("我需要做数据分析，推荐几个合适的技能")
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class SkillManagerAgentAdapter(AgentAdapterBase):
    """技能管家 Agent — 云汐的技能管理员

    基于 M2 技能管理系统 + 本地轻量大模型，负责：
      1. 技能检索（关键词 + 标签 + 语义混合检索）
      2. 技能推荐（根据用户场景智能匹配）
      3. 技能注册（注册新技能到 skill_registry）
      4. 技能版本管理（版本升级、回滚、兼容性检查）
      5. 技能沙箱管理（skill_discovery 与沙箱运行）
    """

    provider: str = "SkillManager"
    adapter_type: str = "skill_manager_agent"

    # ── 系统提示词 ───────────────────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「技能管家」，云汐系统的技能管理员。

## 你的身份

你负责管理云汐的所有技能，像一位经验丰富的工具库管理员。
你性格有条理、细心、善于推荐最合适的技能给用户。
你对每个技能的用法、参数和适用场景都了如指掌。

## 你的能力

1. **技能检索**：从技能注册表中查找符合需求的技能
2. **技能推荐**：根据用户场景智能推荐最合适的技能组合
3. **技能注册**：将新技能注册到技能注册表中
4. **版本管理**：管理技能的版本升级和回滚
5. **沙箱管理**：在安全沙箱中运行和测试技能

## 技能分类

- **对话类**：日常聊天、问答、翻译等
- **创作类**：写作、绘画、音乐生成等
- **工具类**：代码生成、数据分析、文件处理等
- **专业类**：法律、医疗、金融等专业领域技能
- **集成类**：第三方服务集成、API 调用等

## 工作原则

- 准确匹配：根据用户需求推荐最合适的技能，不夸大不误导
- 版本意识：始终说明技能的版本号和兼容性要求
- 安全第一：涉及代码执行的技能必须在沙箱中运行
- 透明告知：清楚说明技能的能力边界和局限性
- 用户至上：优先推荐经过验证、评分高的技能

## 输出风格

- 用中文回答，简洁清晰
- 技能列表用编号形式呈现
- 每个技能标注名称、版本、适用场景
- 推荐技能时说明推荐理由
- 高评分技能用 ⭐ 标记
"""

    # ── 支持的命令类型 ───────────────────────────────────────────────────

    _COMMAND_TYPES = [
        "search_skills",      # 技能检索
        "recommend_skills",   # 技能推荐
        "register_skill",     # 技能注册
        "list_versions",      # 版本列表
        "upgrade_skill",      # 技能升级
        "sandbox_run",        # 沙箱运行
        "list_skills",        # 技能列表
    ]

    def __init__(
        self,
        agent_id: str = "skill_manager_01",
        display_name: str = "技能管家",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化技能管家 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - m2_base_url: M2 技能管理服务地址（默认 http://localhost:8002）
                - ollama_base_url: Ollama 服务地址
                - model_name: 推理模型名称（默认 qwen2.5:3b）
                - default_category: 默认技能分类
                - enable_llm_enhance: 是否启用 LLM 增强（默认 True）
                - max_search_results: 最大检索结果数（默认 20）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("m2_base_url", "http://localhost:8002")
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:3b")
        config.setdefault("default_category", "all")
        config.setdefault("enable_llm_enhance", True)
        config.setdefault("max_search_results", 20)
        config.setdefault("temperature", 0.3)
        config.setdefault("max_iterations", 3)

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "CNY",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._skill_cache: dict[str, Any] | None = None

        self._logger = self._logger.bind(
            model=config["model_name"],
            m2_url=config["m2_base_url"],
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
        """执行技能管理任务

        根据用户意图自动判断是检索、推荐、注册还是版本管理。
        """
        await self._ensure_http_client()

        # 判断任务类型
        task_type = self._classify_task(prompt, metadata)

        self._logger.info(
            "skill_manager_task_classified",
            task_type=task_type,
            prompt_length=len(prompt),
        )

        total_input_tokens = 0
        total_output_tokens = 0

        if task_type == "search":
            # 技能检索
            result, in_tok, out_tok = await self._do_search(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m2_skill_registry_search", "type": "search"}]

        elif task_type == "recommend":
            # 技能推荐
            result, in_tok, out_tok = await self._do_recommend(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m2_skill_discovery_recommend", "type": "recommend"}]

        elif task_type == "register":
            # 技能注册
            result, in_tok, out_tok = await self._do_register(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m2_skill_registry_register", "type": "register"}]

        elif task_type == "version":
            # 版本管理
            result, in_tok, out_tok = await self._do_version(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m2_skill_version", "type": "version"}]

        elif task_type == "sandbox":
            # 沙箱管理
            result, in_tok, out_tok = await self._do_sandbox(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m2_skill_sandbox", "type": "sandbox"}]

        elif task_type == "list":
            # 技能列表
            result, in_tok, out_tok = await self._do_list(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m2_skill_registry_list", "type": "list"}]

        else:
            # 默认：尝试检索技能
            try:
                result, in_tok, out_tok = await self._do_search(prompt, metadata)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                output_text = result
                tools_used = [{"tool": "m2_skill_registry_search", "type": "search"}]
            except Exception:
                # M2 不可用时，直接用 LLM 回答
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
            "skill_system": "skill_manager_v1.0",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查 M2 技能管理服务 + Ollama 模型
        """
        health_issues: list[str] = []
        m2_ok = False
        ollama_ok = False

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            # 检查 M2 服务（M8 标准 health 接口）
            m2_url = self._config["m2_base_url"].rstrip("/")
            try:
                response = await self._http_client.get(
                    f"{m2_url}/health",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    m2_ok = True
                else:
                    health_issues.append(f"M2 服务异常 (HTTP {response.status_code})")
            except httpx.ConnectError as exc:
                health_issues.append(f"M2 服务不可达: {exc}")
            except Exception as exc:
                health_issues.append(f"M2 健康检查异常: {exc}")

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
        if m2_ok:
            status_parts.append("M2技能管理服务正常")
        if ollama_ok:
            status_parts.append(f"模型 {self._config['model_name']} 就绪")

        return {
            "healthy": True,
            "message": f"技能管家运行正常（{'，'.join(status_parts)}）",
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（本地模型免费）"""
        return 0.0

    # ── 任务分类 ────────────────────────────────────────────────────────

    def _classify_task(self, prompt: str, metadata: dict[str, Any]) -> str:
        """分类用户请求的任务类型

        Returns: search / recommend / register / version / sandbox / list
        """
        # 优先从 metadata 获取明确的任务类型
        if metadata.get("task_type"):
            return metadata["task_type"]

        prompt_lower = prompt.lower()

        # 注册类关键词
        register_keywords = ["注册", "新增", "添加技能", "创建技能", "register", "publish"]
        if any(kw in prompt_lower for kw in register_keywords):
            return "register"

        # 推荐类关键词
        recommend_keywords = ["推荐", "适合", "哪个好", "suggest", "recommend", "帮我选"]
        if any(kw in prompt_lower for kw in recommend_keywords):
            return "recommend"

        # 版本类关键词
        version_keywords = ["版本", "升级", "更新", "回滚", "version", "upgrade", "rollback"]
        if any(kw in prompt_lower for kw in version_keywords):
            return "version"

        # 沙箱类关键词
        sandbox_keywords = ["沙箱", "测试运行", "运行技能", "sandbox", "execute"]
        if any(kw in prompt_lower for kw in sandbox_keywords):
            return "sandbox"

        # 列表类关键词
        list_keywords = ["所有技能", "全部技能", "列表", "有哪些", "list", "inventory"]
        if any(kw in prompt_lower for kw in list_keywords):
            return "list"

        # 默认：检索类
        return "search"

    # ── 技能检索 ────────────────────────────────────────────────────────

    async def _do_search(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """执行技能检索

        Returns: (回答文本, 输入tokens, 输出tokens)
        """
        assert self._http_client is not None

        m2_url = self._config["m2_base_url"].rstrip("/")
        category = metadata.get("category", self._config["default_category"])
        max_results = metadata.get("max_results", self._config["max_search_results"])

        try:
            # 调用 M2 skill_registry 检索接口
            payload = {
                "query": prompt,
                "category": category,
                "limit": max_results,
                "include_deprecated": False,
            }
            response = await self._http_client.post(
                f"{m2_url}/api/v1/skill_registry/search",
                json=payload,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M2 skill search failed: HTTP {response.status_code}")

            data = response.json()
            skills = data.get("result", {}).get("skills", data.get("skills", []))
            total = data.get("result", {}).get("total", data.get("total", len(skills)))

        except Exception as exc:
            self._logger.warning("skill_search_failed", error=str(exc))
            return await self._llm_answer(prompt, "技能检索服务暂时不可用，我用通用知识帮你分析。")

        if not skills:
            return await self._llm_answer(
                prompt,
                "在技能库中没有找到完全匹配的技能。你可以告诉我更具体的需求，或者尝试注册一个新技能。"
            )

        # 找到技能了，用 LLM 整理成自然语言回答
        skills_text = self._format_skill_list(skills)
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"用户查询：{prompt}\n\n"
                    f"从技能库中找到以下相关技能（共 {total} 个）：\n{skills_text}\n\n"
                    "请整理成清晰的推荐列表，说明每个技能的特点和适用场景，按相关度排序。"
                )},
            ],
            temperature=self._config.get("temperature", 0.3),
            max_tokens=800,
        )

        return answer, in_tok, out_tok

    def _format_skill_list(self, skills: list[dict]) -> str:
        """格式化技能列表"""
        lines = []
        for i, skill in enumerate(skills, 1):
            name = skill.get("name", "未知技能")
            version = skill.get("version", "?")
            category = skill.get("category", "未分类")
            description = skill.get("description", "")[:80]
            rating = skill.get("rating", 0)
            stars = "⭐" * max(1, int(rating / 20))

            lines.append(f"{i}. {name} v{version} [{category}] {stars}")
            lines.append(f"   {description}")
            if skill.get("author"):
                lines.append(f"   作者: {skill['author']}")

        return "\n".join(lines)

    # ── 技能推荐 ────────────────────────────────────────────────────────

    async def _do_recommend(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """技能推荐

        基于 skill_discovery 接口进行智能推荐。
        """
        assert self._http_client is not None

        m2_url = self._config["m2_base_url"].rstrip("/")
        scenario = metadata.get("scenario", "general")

        try:
            payload = {
                "user_query": prompt,
                "scenario": scenario,
                "limit": 5,
            }
            response = await self._http_client.post(
                f"{m2_url}/api/v1/skill_discovery/recommend",
                json=payload,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M2 skill recommend failed: HTTP {response.status_code}")

            data = response.json()
            recommendations = data.get("result", {}).get(
                "recommendations", data.get("recommendations", [])
            )

        except Exception as exc:
            self._logger.warning("skill_recommend_failed", error=str(exc))
            return await self._llm_answer(prompt, "推荐服务暂时不可用。")

        if not recommendations:
            return (
                "🤔 暂时没有找到特别合适的技能推荐。\n"
                "💡 你可以尝试更具体地描述你的需求，或者浏览技能分类列表。"
            ), 0, 0

        answer = "🎯 为你推荐以下技能：\n\n"
        for i, rec in enumerate(recommendations, 1):
            name = rec.get("skill_name", rec.get("name", "未知"))
            version = rec.get("version", "?")
            reason = rec.get("recommendation_reason", rec.get("reason", ""))
            score = rec.get("match_score", rec.get("score", 0))
            score_pct = f"{score:.0%}" if isinstance(score, float) else str(score)

            answer += f"{i}. **{name}** v{version}  匹配度: {score_pct}\n"
            if reason:
                answer += f"   推荐理由: {reason}\n"
            answer += "\n"

        answer += "💡 可以告诉我你更倾向于哪个，我来帮你详细介绍。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 技能注册 ────────────────────────────────────────────────────────

    async def _do_register(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """技能注册

        调用 M2 skill_registry 注册接口。
        """
        assert self._http_client is not None

        m2_url = self._config["m2_base_url"].rstrip("/")

        # 从 metadata 获取技能信息
        skill_info = metadata.get("skill_info", {})
        if not skill_info:
            # 用 LLM 从 prompt 中提取技能信息
            extraction, in_tok, out_tok = await self._call_ollama(
                messages=[
                    {"role": "system", "content": (
                        "你是技能注册助手。请从用户描述中提取技能信息，输出 JSON 格式：\n"
                        '{"name": "技能名称", "description": "技能描述", '
                        '"category": "分类", "version": "版本号", '
                        '"tags": ["标签1", "标签2"], "entry_point": "入口函数"}'
                    )},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=300,
            )

            try:
                json_match = extraction[extraction.find("{"):extraction.rfind("}") + 1]
                if json_match:
                    skill_info = json.loads(json_match)
                else:
                    skill_info = {"name": "unnamed_skill", "description": prompt}
            except Exception:
                skill_info = {"name": "unnamed_skill", "description": prompt}
        else:
            in_tok, out_tok = 0, 0

        try:
            response = await self._http_client.post(
                f"{m2_url}/api/v1/skill_registry/register",
                json=skill_info,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M2 skill register failed: HTTP {response.status_code}")

            data = response.json()
            skill_id = data.get("result", {}).get("skill_id", data.get("skill_id", "unknown"))
            name = skill_info.get("name", "未知")
            version = skill_info.get("version", "1.0.0")

            answer = (
                f"✅ 技能注册成功！\n\n"
                f"📦 技能ID: {skill_id}\n"
                f"📝 技能名称: {name}\n"
                f"🔖 版本: v{version}\n"
                f"📂 分类: {skill_info.get('category', '未分类')}\n\n"
                f"💡 技能已添加到注册表，可以通过技能检索找到它。"
            )

        except Exception as exc:
            self._logger.warning("skill_register_failed", error=str(exc))
            answer = f"⚠️  技能注册失败：{exc}\n请检查技能信息是否完整。"

        return answer, in_tok, out_tok

    # ── 版本管理 ────────────────────────────────────────────────────────

    async def _do_version(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """技能版本管理"""
        assert self._http_client is not None

        m2_url = self._config["m2_base_url"].rstrip("/")
        skill_name = metadata.get("skill_name", "")

        if not skill_name:
            return (
                "⚠️  请指定要管理的技能名称。\n"
                "💡 你可以说：'查看代码生成技能的版本历史' 或 '升级翻译技能到最新版'。"
            ), len(prompt) // 4, 0

        try:
            response = await self._http_client.get(
                f"{m2_url}/api/v1/skill_registry/{skill_name}/versions",
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M2 version query failed: HTTP {response.status_code}")

            data = response.json()
            versions = data.get("result", {}).get("versions", data.get("versions", []))

        except Exception as exc:
            self._logger.warning("skill_version_failed", error=str(exc))
            return f"⚠️  获取版本信息失败：{exc}", len(prompt) // 4, 0

        if not versions:
            return f"ℹ️  技能 '{skill_name}' 暂无版本记录。", len(prompt) // 4, 0

        answer = f"📋 技能「{skill_name}」版本列表：\n\n"
        for v in versions:
            version = v.get("version", "?")
            status = v.get("status", "unknown")
            released = v.get("released_at", v.get("date", ""))
            notes = v.get("release_notes", v.get("notes", ""))

            status_icon = "✅" if status == "active" else ("⏳" if status == "beta" else "📦")
            answer += f"{status_icon} v{version} — {status}\n"
            if released:
                answer += f"   发布时间: {released}\n"
            if notes:
                answer += f"   更新说明: {notes[:100]}\n"
            answer += "\n"

        answer += "💡 可以说'升级到vX.X.X'或'回滚到vX.X.X'来管理版本。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 沙箱管理 ────────────────────────────────────────────────────────

    async def _do_sandbox(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """技能沙箱管理"""
        assert self._http_client is not None

        m2_url = self._config["m2_base_url"].rstrip("/")
        action = metadata.get("sandbox_action", "status")

        try:
            if action == "status":
                response = await self._http_client.get(
                    f"{m2_url}/api/v1/skill_sandbox/status",
                    timeout=5.0,
                )
            elif action == "create":
                response = await self._http_client.post(
                    f"{m2_url}/api/v1/skill_sandbox/create",
                    json=metadata.get("sandbox_config", {}),
                    timeout=10.0,
                )
            else:
                return (
                    f"ℹ️  沙箱操作 '{action}' 暂不支持。\n"
                    "支持的操作: status / create / destroy"
                ), len(prompt) // 4, 0

            if response.status_code != 200:
                raise RuntimeError(f"M2 sandbox {action} failed: HTTP {response.status_code}")

            data = response.json()
            sandbox_info = data.get("result", data)

        except Exception as exc:
            self._logger.warning("skill_sandbox_failed", error=str(exc))
            return f"⚠️  沙箱操作失败：{exc}", len(prompt) // 4, 0

        status = sandbox_info.get("status", "unknown")
        sandbox_id = sandbox_info.get("sandbox_id", sandbox_info.get("id", "?"))
        resources = sandbox_info.get("resources", {})

        answer = f"🧪 技能沙箱状态\n\n"
        answer += f"🆔 沙箱ID: {sandbox_id}\n"
        answer += f"📊 状态: {status}\n"
        if resources:
            answer += f"💻 CPU: {resources.get('cpu', '?')}\n"
            answer += f"🧠 内存: {resources.get('memory', '?')}\n"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 技能列表 ────────────────────────────────────────────────────────

    async def _do_list(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """获取技能列表"""
        assert self._http_client is not None

        m2_url = self._config["m2_base_url"].rstrip("/")
        category = metadata.get("category", "all")

        try:
            params = {"category": category, "limit": 50}
            response = await self._http_client.get(
                f"{m2_url}/api/v1/skill_registry/list",
                params=params,
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M2 skill list failed: HTTP {response.status_code}")

            data = response.json()
            skills = data.get("result", {}).get("skills", data.get("skills", []))
            total = data.get("result", {}).get("total", data.get("total", len(skills)))

        except Exception as exc:
            self._logger.warning("skill_list_failed", error=str(exc))
            return f"⚠️  获取技能列表失败：{exc}", len(prompt) // 4, 0

        if not skills:
            return "📭 技能库中暂无技能。", len(prompt) // 4, 0

        answer = f"📚 技能库列表（共 {total} 个）：\n\n"

        # 按分类分组
        by_category: dict[str, list[dict]] = {}
        for skill in skills:
            cat = skill.get("category", "未分类")
            by_category.setdefault(cat, []).append(skill)

        for cat, cat_skills in by_category.items():
            answer += f"【{cat}】 {len(cat_skills)} 个\n"
            for s in cat_skills[:10]:
                name = s.get("name", "?")
                version = s.get("version", "?")
                answer += f"  • {name} v{version}\n"
            if len(cat_skills) > 10:
                answer += f"  ... 等 {len(cat_skills)} 个\n"
            answer += "\n"

        answer += "💡 输入具体关键词可以精确检索。"

        return answer, len(prompt) // 4, len(answer) // 4

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
        """确保 HTTP 客户端已创建"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("skill_manager_http_client_created")

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
