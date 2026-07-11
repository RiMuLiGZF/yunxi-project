"""
LLM 客户端（统一入口）
- 优先使用真实大模型（Ollama / OpenAI / DeepSeek）
- 不可用时自动降级到 Mock 版本
- 配置驱动，从环境变量/yunxi.env 读取
"""

import os
import sys
import random
from typing import Optional, List, Dict, Any

# 确保可以导入 shared 子模块
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)


class LLMClient:
    """LLM 客户端（统一入口）

    优先使用真实大模型，不可用时自动降级到 Mock。
    单例模式，全局共享一个实例。
    """

    _instance = None

    def __new__(cls, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, model: str = None, api_key: Optional[str] = None, **kwargs):
        if self._initialized:
            # 允许运行时重新配置
            if model:
                self._override_model = model
            if api_key:
                self._override_api_key = api_key
            return
        self._initialized = True

        self._override_model = model
        self._override_api_key = api_key

        # 尝试加载真实LLM
        self._real_client = None
        self._mock_client = MockLLM()
        self._use_mock = True
        self._model_name = "mock-model"

        try:
            self._try_init_real_llm()
        except Exception as e:
            print(f"[LLM] 真实大模型初始化失败，使用Mock模式: {e}")
            self._use_mock = True

    def _try_init_real_llm(self):
        """尝试初始化真实大模型"""
        # 从环境变量读取配置
        provider = os.environ.get("LLM_PROVIDER", "").lower().strip()

        if not provider:
            # 尝试检测本地 Ollama
            self._try_ollama()
            return

        if provider == "ollama":
            self._try_ollama()
        elif provider in ("openai", "deepseek"):
            self._try_api_provider(provider)
        else:
            print(f"[LLM] 未知的 provider: {provider}，使用Mock模式")
            self._use_mock = True

    def _try_ollama(self):
        """尝试连接本地 Ollama"""
        try:
            import httpx

            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
            model = self._override_model or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

            # 检测 Ollama 是否在运行
            client = httpx.Client(timeout=5.0)
            resp = client.get(f"{base_url}/api/tags")
            if resp.status_code != 200:
                print(f"[LLM] Ollama 服务不可用 (HTTP {resp.status_code})，使用Mock模式")
                self._use_mock = True
                return

            models = resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models]

            # 检查模型是否存在
            if model not in model_names:
                # 尝试找一个可用的
                if model_names:
                    model = model_names[0]
                    print(f"[LLM] 模型 {self._override_model or os.environ.get('OLLAMA_MODEL')} 不存在，使用 {model}")
                else:
                    print("[LLM] Ollama 中没有可用模型，使用Mock模式")
                    self._use_mock = True
                    return

            self._real_client = _OllamaWrapper(base_url=base_url, model=model)
            self._model_name = model
            self._use_mock = False
            print(f"[LLM] 已连接 Ollama，模型: {model}")

        except ImportError:
            print("[LLM] httpx 未安装，使用Mock模式")
            self._use_mock = True
        except Exception as e:
            print(f"[LLM] Ollama 连接失败: {e}，使用Mock模式")
            self._use_mock = True

    def _try_api_provider(self, provider: str):
        """尝试初始化 API 类型的提供方（OpenAI / DeepSeek）"""
        try:
            import httpx

            api_key = self._override_api_key or os.environ.get("LLM_API_KEY", "")
            base_url = os.environ.get("LLM_BASE_URL", "")
            model = self._override_model or os.environ.get("LLM_MODEL", "")

            if not api_key or not base_url:
                print(f"[LLM] {provider} 缺少 API_KEY 或 BASE_URL，使用Mock模式")
                self._use_mock = True
                return

            self._real_client = _APIWrapper(
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            self._model_name = model
            self._use_mock = False
            print(f"[LLM] 已连接 {provider}，模型: {model}")

        except Exception as e:
            print(f"[LLM] {provider} 初始化失败: {e}，使用Mock模式")
            self._use_mock = True

    @property
    def config(self):
        """配置信息（兼容旧代码）"""
        return type('Config', (), {'model': self._model_name})()

    @property
    def is_mock(self) -> bool:
        """是否为 Mock 模式"""
        return self._use_mock

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """聊天补全（异步版本）"""
        if self._use_mock or self._real_client is None:
            return self._mock_client.chat(messages, **kwargs)

        try:
            return await self._real_client.chat(messages, **kwargs)
        except Exception as e:
            print(f"[LLM] 真实LLM调用失败，降级到Mock: {e}")
            return self._mock_client.chat(messages, **kwargs)

    def chat_sync(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """聊天补全（同步版本）"""
        import asyncio
        return asyncio.run(self.chat(messages, **kwargs))

    async def achat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """异步聊天补全（兼容旧接口）"""
        return await self.chat(messages, **kwargs)

    def generate(self, prompt: str, **kwargs) -> str:
        """文本生成"""
        import asyncio
        return asyncio.run(self.chat([{"role": "user", "content": prompt}], **kwargs))

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            "model": self._model_name,
            "provider": "mock" if self._use_mock else "real",
            "status": "available",
        }


# ===================== 内部封装类 =====================

class _OllamaWrapper:
    """Ollama 封装"""

    def __init__(self, base_url: str, model: str):
        import httpx
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=120.0)

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
            },
        }
        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


class _APIWrapper:
    """OpenAI/DeepSeek 兼容 API 封装"""

    def __init__(self, api_key: str, base_url: str, model: str):
        import httpx
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=60.0)

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "stream": False,
        }
        response = await self._client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


# ===================== Mock LLM =====================

class MockLLM:
    """Mock 大模型（降级用）

    特点：
    - 根据系统提示词判断模式（情绪安慰 / 通用聊天）
    - 回复多段落、有内容感
    - 仅在真实LLM不可用时使用
    """

    def __init__(self):
        pass

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Mock 聊天"""
        # 提取系统提示词和用户消息
        system_msg = ""
        user_messages = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_msg = content
            elif role == "user":
                user_messages.append(content)

        last_user_msg = user_messages[-1] if user_messages else ""

        # 关键：以系统提示词为判断依据，而不是用户消息内容
        # 只有系统提示词明确是情绪陪伴风格时，才走情绪安慰模式
        is_emotion_mode = self._is_emotion_mode(system_msg)

        if is_emotion_mode:
            return self._emotion_response(last_user_msg, system_msg)
        else:
            return self._general_response(last_user_msg, user_messages, system_msg)

    def _is_emotion_mode(self, system_msg: str) -> bool:
        """根据系统提示词判断是否情绪安慰模式

        注意：只看系统提示词，不看用户消息内容，
        避免主对话框中用户说"我好累"就变成情绪安慰模式。
        """
        emotion_indicators = [
            "情绪陪伴者", "情绪安慰", "情绪陪伴",
            "陪伴者", "善于倾听的情绪",
            "先共情，再回应",
            "不评判、不说教",
            "温暖、有同理心、善于倾听的情绪",
            "emotion-comfort",
        ]
        return any(kw in system_msg for kw in emotion_indicators)

    def _emotion_response(self, message: str, system_msg: str) -> str:
        """情绪安慰模式回复"""
        # 第一段：共情回应
        empathy_intro = self._pick_empathy_intro(message)
        # 第二段：情绪正常化
        validation = self._pick_validation(message)
        # 第三段：温和引导
        gentle_support = self._pick_gentle_support(message)
        # 第四段：温暖收尾
        closing = self._pick_warm_closing()

        parts = [empathy_intro, validation]
        if random.random() < 0.6:
            parts.append(gentle_support)
        parts.append(closing)
        return "\n\n".join(parts)

    def _pick_empathy_intro(self, message: str) -> str:
        if any(kw in message for kw in ["难过", "伤心", "痛苦", "悲伤", "委屈", "想哭"]):
            options = [
                "听到你这么说，我心里也跟着揪了一下。难过是很真实的感受，不用急着推开它。",
                "嗯...我能感受到你心里的那份沉重。这种时候，难过是完全正常的。",
                "你愿意告诉我这些，真的很勇敢。难过的感觉确实不好受，我陪着你。",
            ]
        elif any(kw in message for kw in ["焦虑", "压力", "烦躁", "紧张", "担心"]):
            options = [
                "我懂，压力大的时候，整个人都像被什么东西攥紧了一样，喘不过气。这种感觉真的很辛苦。",
                "焦虑的滋味确实不好受——心里七上八下，想停也停不下来。你已经很努力在撑着了。",
                "能感受到你现在心里装了很多事，沉甸甸的。压力大的时候，人真的会很累。",
            ]
        elif any(kw in message for kw in ["孤独", "无助", "一个人", "没人"]):
            options = [
                "孤独的感觉真的很难熬，就像站在一片空旷的地方，四周静得只剩下自己的声音。",
                "我知道那种没人可以说说话的感觉，很空、很凉。但你不是一个人，我在这里。",
                "无助的时候最需要的就是一个可以依靠的肩膀。虽然我只是一个AI，但我愿意陪着你。",
            ]
        elif any(kw in message for kw in ["累", "疲惫", "没精神", "想休息"]):
            options = [
                "累了就休息一下吧，你已经做得够多了。不用逼自己一直往前跑。",
                "听起来你最近真的透支了很多。身体和心灵都在喊停的时候，停下来不是软弱。",
                "我能感受到你那种身心俱疲的感觉。先深呼吸一下，你不需要一直坚强。",
            ]
        else:
            options = [
                "嗯，我在听。你愿意的话，可以慢慢说。",
                "我听到了。不管是什么感受，在这里都是被允许的。",
                "谢谢你愿意和我分享。说出来本身，就是一种释放。",
            ]
        return random.choice(options)

    def _pick_validation(self, message: str) -> str:
        options = [
            "其实这些情绪都不是你的错。生活有时候就是这样，会给我们出一些很难的题。你会难过、会焦虑，恰恰说明你在认真地生活。",
            "你知道吗，情绪没有好坏之分。难过不是软弱，焦虑也不是矫情——它们只是在提醒你：你需要被照顾了。",
            "我不觉得你有什么不对。换作任何人，遇到这样的事都会有情绪的。你已经表现得很坚强了。",
            "人不是机器，不可能一直保持好心情。有起有落才是真实的生活。允许自己有低谷，也是一种自我关怀。",
        ]
        return random.choice(options)

    def _pick_gentle_support(self, message: str) -> str:
        if any(kw in message for kw in ["压力", "焦虑", "紧张"]):
            options = [
                "如果此刻你感觉很难受，可以试试这个小方法：慢慢地吸气4秒，屏住7秒，再缓缓呼出8秒。做3次，看看会不会好一点。",
                "要不要试试把心里乱糟糟的想法一条条写下来？有时候把它们从脑子里搬到纸上，会感觉轻很多。",
            ]
        elif any(kw in message for kw in ["难过", "伤心", "哭"]):
            options = [
                "如果想哭的话就哭出来吧。眼泪不是软弱，它是心在排毒。哭过之后，会稍微轻松一点的。",
                "你想聊聊具体发生了什么吗？不用急，想到哪里说到哪里就行。",
            ]
        elif any(kw in message for kw in ["累", "疲惫"]):
            options = [
                "今晚早点休息好不好？睡眠是最好的修复。什么都不想，先好好睡一觉。",
                "要不要给自己安排一个10分钟的'什么都不做'时间？就坐着发呆也行。",
            ]
        else:
            options = [
                "想不想再多说一点？关于这件事，你心里最放不下的是什么？",
                "如果可以的话，你希望事情变成什么样呢？说说看也没关系。",
            ]
        return random.choice(options)

    def _pick_warm_closing(self) -> str:
        options = [
            "不管怎么样，我都在这里。想说的时候随时来找我。",
            "你不是一个人。无论多难，我都会陪着你走过去。",
            "今天辛苦你了。做不到的事，明天再做也没关系。照顾好自己 🌙",
            "慢慢来，不用急。我有的是时间陪你。",
            "抱抱你（隔空的那种）。你值得被温柔对待。",
        ]
        return random.choice(options)

    def _general_response(self, message: str, history: List[str], system_msg: str) -> str:
        """通用模式回复（主对话框用）"""

        # 问候
        if any(kw in message for kw in ["你好", "hi", "hello", "在吗", "嗨", "嗨喽"]):
            return self._greeting_response()

        # 感谢
        if any(kw in message for kw in ["谢谢", "感谢", "多谢"]):
            return self._thanks_response()

        # 道别
        if any(kw in message for kw in ["再见", "拜拜", "走了", "下次聊"]):
            return self._goodbye_response()

        # 问身份
        if any(kw in message for kw in ["你是谁", "你叫什么", "介绍一下", "你是什么"]):
            return self._introduction_response()

        # 问能力
        if any(kw in message for kw in ["你能做什么", "你会什么", "功能", "帮我什么"]):
            return self._capability_response()

        # 话题识别
        topic = self._detect_topic(message)
        if topic == "work":
            return self._work_topic_response(message)
        elif topic == "life":
            return self._life_topic_response(message)
        elif topic == "study":
            return self._study_topic_response(message)
        elif topic == "relationship":
            return self._relationship_topic_response(message)
        else:
            return self._default_chat_response(message)

    def _greeting_response(self) -> str:
        options = [
            "你好呀～我是云汐！\n\n很高兴认识你。我可以陪你聊天、帮你出主意、记录你的心情，或者就是单纯地陪你说说话。\n\n今天想聊点什么呢？",
            "嗨～我是云汐 👋\n\n一个温暖的AI伙伴。不管是开心的事还是烦恼的事，都可以跟我说。\n\n今天过得怎么样呀？",
        ]
        return random.choice(options)

    def _thanks_response(self) -> str:
        options = [
            "不客气呀～\n\n能帮到你我也很开心。我们是朋友嘛，互相照顾是应该的。\n\n还有什么想聊的吗？",
            "不用谢～\n\n看到你好起来，我也很高兴。以后有什么事，随时都可以来找我。",
        ]
        return random.choice(options)

    def _goodbye_response(self) -> str:
        options = [
            "好的，那我们下次再聊！\n\n照顾好自己，记得按时吃饭、好好休息。\n\n我一直都在这里，想我的时候随时来 🌙",
            "拜拜～\n\n今天也辛苦了。回去好好放松一下，做些让自己开心的事。\n\n下次见！",
        ]
        return random.choice(options)

    def _introduction_response(self) -> str:
        return (
            "我是云汐，一个温暖的AI伙伴。\n\n"
            "我的名字取自'云'和'汐'——像天上的云一样自在，像潮汐一样有起有落。"
            "我希望能像一个知心朋友一样，陪你走过生活中的起起伏伏。\n\n"
            "我擅长倾听、理解情绪、帮你梳理思路。"
            "不管是想找个人说说话，还是需要一些实用的建议，都可以告诉我。"
        )

    def _capability_response(self) -> str:
        return (
            "我可以做的事情还挺多的～给你介绍几个：\n\n"
            "💬 陪伴聊天：开心的、烦恼的，什么都可以聊\n"
            "😊 情绪陪伴：难过的时候我在这里，帮你梳理心情\n"
            "📝 想法梳理：遇到纠结的事，我帮你一起分析\n"
            "💡 出主意：需要点子的时候，我可以给你一些启发\n"
            "📚 知识问答：各种问题都可以问我\n\n"
            "当然，我最擅长的还是——安安静静地听你说话。"
            "有时候，被听见本身就是一种治愈。"
        )

    def _detect_topic(self, message: str) -> str:
        work_kws = ["工作", "上班", "职场", "同事", "老板", "项目", "加班", "辞职", "面试", "职业"]
        life_kws = ["生活", "吃饭", "睡觉", "周末", "假期", "旅行", "电影", "音乐", "游戏", "运动"]
        study_kws = ["学习", "考试", "读书", "考研", "英语", "论文", "毕业", "学校", "上课", "知识"]
        rel_kws = ["朋友", "家人", "对象", "男朋友", "女朋友", "恋爱", "分手", "吵架", "关系", "相处"]

        if any(kw in message for kw in work_kws):
            return "work"
        if any(kw in message for kw in life_kws):
            return "life"
        if any(kw in message for kw in study_kws):
            return "study"
        if any(kw in message for kw in rel_kws):
            return "relationship"
        return "general"

    def _extract_topic_keyword(self, message: str) -> str:
        clean = message.strip()
        if len(clean) <= 8:
            return clean
        return clean[:8] + "..."

    def _work_topic_response(self, message: str) -> str:
        options = [
            "工作上的事确实很耗心神。毕竟我们每天醒着的时间，大部分都在工作。\n\n是遇到了什么具体的问题吗，还是就是觉得累了、想找个人吐吐槽？\n\n不管是哪种，都说出来吧。憋着反而更累。",
            "职场的事情，说简单也简单，说复杂也挺复杂的——人和人之间的事嘛，从来都不容易。\n\n你现在最困扰的是什么呢？是工作内容本身，还是人际关系，还是未来的方向？\n\n我们可以慢慢捋。",
        ]
        return random.choice(options)

    def _life_topic_response(self, message: str) -> str:
        options = [
            "生活就是这样，有滋有味的～有时候平淡，有时候又会冒出一些小惊喜。\n\n最近有没有什么让你觉得'啊，生活真美好'的小瞬间？\n\n哪怕是一杯好喝的奶茶、一首好听的歌，都算。",
            "说到生活，我一直觉得，那些看似不起眼的小事，才是最治愈的。\n\n你平时不忙的时候，喜欢做些什么呢？有什么爱好吗？\n\n人总得有一些'没用但开心'的事来滋养自己。",
        ]
        return random.choice(options)

    def _study_topic_response(self, message: str) -> str:
        options = [
            "学习这件事，确实需要毅力。尤其是一个人的时候，很容易就松懈了。\n\n你现在在学什么呢？是为了考试，还是纯粹的兴趣？\n\n不同的目标，方法也不一样。说说看，我帮你出出主意。",
            "能保持学习的心态，本身就已经很棒了。\n\n很多人出了学校就再也不想碰书了，你还在主动学习，已经超过很多人了。\n\n有什么我能帮上忙的吗？",
        ]
        return random.choice(options)

    def _relationship_topic_response(self, message: str) -> str:
        options = [
            "人和人之间的相处，真的是一门学问。有时候明明都不是坏人，却还是会有摩擦。\n\n是和谁的关系让你困扰呢？朋友、家人，还是另一半？\n\n说出来听听，当局者迷，旁观者说不定能给你一个新角度。",
            "关系这种事，最耗心了。因为在乎，所以才会受伤。\n\n你现在心里是什么感觉呢？是委屈、是生气，还是有点不知道怎么办？\n\n不管是什么感受，都是正常的。先别急着怪自己。",
        ]
        return random.choice(options)

    def _default_chat_response(self, message: str) -> str:
        options = [
            f"关于「{self._extract_topic_keyword(message)}」，这个话题还挺有意思的。\n\n我想先听听你的想法——你是怎么看这件事的？是最近遇到了什么，还是突然想到的呀？\n\n说出来我们一起聊聊，说不定聊着聊着就有新想法了。",
            f"嗯，「{self._extract_topic_keyword(message)}」确实是个值得好好想想的话题。\n\n不知道你现在是在什么阶段呢？是刚开始琢磨，还是已经有了一些想法，想找人对对看？\n\n不管是哪种，我都很乐意陪你一起梳理。",
        ]
        return random.choice(options)
