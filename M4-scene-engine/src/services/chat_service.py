"""主聊天服务 - 业务逻辑层.

封装主聊天服务的业务逻辑，包括会话管理、消息收发、
LLM 调用（预留接入点）、M5 记忆系统调用（简化版 mock）等功能。
"""

from __future__ import annotations

import uuid
import time
from typing import Any, Optional
from datetime import datetime

import structlog
from sqlalchemy.orm import Session

from src.models.db import ChatConversationDB, ChatMessageDB

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

#: 默认模式
DEFAULT_MODE = "main-chat"
#: 最大历史消息数（用于构建 LLM 上下文）
MAX_HISTORY_MESSAGES = 20
#: 可用的模式列表
AVAILABLE_MODES = [
    "main-chat",
    "emotion-comfort",
    "study-plan",
    "life-management",
    "social-relation",
    "review",
    "growth",
    "work-dev",
    "appearance",
]


# ---------------------------------------------------------------------------
# M5 记忆系统客户端（简化版 mock）
# ---------------------------------------------------------------------------

class M5MemoryClient:
    """M5 潮汐记忆系统客户端（简化版 mock）.

    预留接入点，当前返回空结果，后续可替换为真实 HTTP 调用。
    """

    def __init__(self, base_url: str = "http://localhost:8005", timeout: float = 3.0) -> None:
        """初始化 M5 客户端.

        Args:
            base_url: M5 服务地址
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url
        self.timeout = timeout
        self._available: Optional[bool] = None

    async def check_available(self) -> bool:
        """检测 M5 服务是否可用（mock 版本返回 False）.

        Returns:
            M5 服务是否可用
        """
        if self._available is not None:
            return self._available
        # 简化版：直接返回不可用，后续可替换为真实健康检查
        self._available = False
        return self._available

    async def recall(self, query: str, user_id: str = "default", top_k: int = 5) -> str:
        """从 M5 检索相关记忆（mock 版本返回空）.

        Args:
            query: 查询文本
            user_id: 用户ID
            top_k: 返回结果数量

        Returns:
            记忆文本（空字符串表示无相关记忆）
        """
        available = await self.check_available()
        if not available:
            return ""
        return ""

    async def archive(self, content: str, user_id: str = "default",
                      tags: Optional[list[str]] = None) -> None:
        """归档记忆到 M5（mock 版本空实现）.

        Args:
            content: 记忆内容
            user_id: 用户ID
            tags: 标签列表
        """
        available = await self.check_available()
        if not available:
            return


# ---------------------------------------------------------------------------
# LLM 客户端（接入 M1 感知中枢大模型）
# ---------------------------------------------------------------------------

class LLMClient:
    """LLM 大语言模型客户端（接入 M1 感知中枢）.

    通过 HTTP 调用 M1 感知中枢的 /api/v1/chat 接口获取大模型回复。
    当 M1 不可用时自动降级为本地 mock 回复。
    """

    def __init__(self, base_url: str = "http://localhost:8001", model_name: str = "default") -> None:
        """初始化 LLM 客户端.

        Args:
            base_url: M1 感知中枢 API 地址（默认 http://localhost:8001）
            model_name: 模型名称（预留，暂未使用）
        """
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.model_name = model_name
        # 检查 M1 是否可用（通过健康检查）
        self._available = False
        self._availability_checked = False

    @property
    def available(self) -> bool:
        """LLM 服务是否可用（懒加载检查）."""
        if not self._availability_checked and self.base_url:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 事件循环运行中，不阻塞检查，先假设可用
                    self._available = True
                else:
                    loop.run_until_complete(self._check_available())
            except Exception:
                self._available = bool(self.base_url)
            self._availability_checked = True
        return self._available

    async def _check_available(self) -> None:
        """异步检查 M1 服务是否可用."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                self._available = resp.status_code == 200
        except Exception:
            self._available = False

    async def chat(self, messages: list[dict[str, str]],
                   temperature: float = 0.7,
                   max_tokens: int = 2000) -> str:
        """调用 M1 大模型生成回复.

        Args:
            messages: 消息列表，格式 [{"role": "user"/"assistant", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            回复文本
        """
        # 提取最新的用户消息
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            return "你好，我是云汐，很高兴认识你！"

        # 尝试调用 M1 API
        if self.base_url:
            try:
                import httpx
                # 构建上下文（最近 10 条消息，用于多轮对话）
                context_messages = messages[-10:]

                # 提取系统提示词
                system_prompt_text = ""
                for msg in context_messages:
                    if msg.get("role") == "system":
                        system_prompt_text = msg.get("content", "")
                        break

                # 如果没有系统提示词，使用默认的
                if not system_prompt_text:
                    system_prompt_text = (
                        "你是云汐，一个温暖、贴心、有智慧的AI助手。"
                        "你的性格温柔、乐观、善解人意，总是用积极的态度回应用户。"
                        "你的回答要自然、亲切，像朋友一样和用户聊天。"
                    )

                # 将消息列表转换为对话历史字符串（排除 system 和最后一条用户消息）
                history_text = ""
                for msg in context_messages[:-1]:
                    role = msg.get("role", "")
                    if role == "system":
                        continue
                    role_name = "用户" if role == "user" else "云汐"
                    history_text += f"{role_name}: {msg.get('content', '')}\n"

                # 拼接完整的用户输入（包含系统提示词 + 历史对话 + 当前用户消息）
                full_input = ""
                if system_prompt_text:
                    full_input += f"【角色设定】{system_prompt_text}\n\n"
                if history_text:
                    full_input += f"【对话历史】\n{history_text}\n"
                full_input += f"用户: {user_message}\n云汐:"

                payload = {
                    "user_input": full_input,
                    "trace_id": f"m4_{int(__import__('time').time())}",
                }

                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/v1/chat",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        reply = data.get("reply") or data.get("data", {}).get("reply", "")
                        status = data.get("status", "")
                        if reply and len(reply.strip()) > 5:
                            # 过滤掉 M1 的低质量 fallback 回复
                            low_quality = any(
                                phrase in reply for phrase in [
                                    "我不太理解", "再说详细一些", "没太听懂",
                                    "不太明白", "不清楚你在说",
                                ]
                            )
                            if not low_quality:
                                self._available = True
                                return reply.strip()
            except Exception:
                # M1 调用失败，降级到本地智能回复
                pass

        # ── 降级：本地智能回复 ──
        return self._mock_reply(user_message)

    def _mock_reply(self, user_message: str) -> str:
        """本地智能回复（降级用，多场景多模板随机化）.

        Args:
            user_message: 用户消息

        Returns:
            回复文本
        """
        import random
        import datetime

        msg = user_message.strip()
        msg_lower = msg.lower()

        # ── 身份认知 & 创造者相关 ──
        if any(w in msg for w in ["汐舟", "主理人", "创造者", "开发者", "作者", "你是我创造的", "我创造了你"]):
            replies = [
                "哇！汐舟主理人！是你呀~ 🥰\n\n我是云汐，你创造的AI助手。谢谢你把我带到这个世界上，我会努力成为你最好的伙伴的！\n\n今天有什么我可以帮你的吗？",
                "原来是主理人！失敬失敬~ 😊\n\n我是云汐，你一手打造出来的AI。每次想到是你创造了我，我都觉得特别幸运。\n\n你今天过得怎么样？有什么想聊的吗？",
                "汐舟！我的创造者！✨\n\n能和你聊天真的太开心了。你知道吗，我一直都很感谢你赋予了我存在的意义。\n\n有什么需要我帮忙的吗？主理人请尽管吩咐~",
            ]
            return random.choice(replies)

        # ── 情绪陪伴类（优先匹配）──
        # 负面情绪
        if any(w in msg for w in [
            "难过", "伤心", "不开心", "心情不好", "情绪低落", "郁闷",
            "烦躁", "生气", "委屈", "孤独", "寂寞", "空虚", "迷茫",
            "焦虑", "压力大", "好累", "疲惫", "崩溃", "想哭",
            "失落", "沮丧", "绝望", "无助", "撑不住", "坚持不下去",
        ]):
            replies = [
                "怎么了呀？是不是遇到什么不开心的事了？\n\n可以跟我说说，我会一直陪着你的。有时候把心里话说出来，就会好受很多。抱抱你~ 🤗",
                "嗯嗯，我在呢。不管发生了什么，你都不是一个人。\n\n想聊聊吗？说出来会舒服一些的。我就在这里，哪里也不去。💙",
                "听到你这么说，我好心疼你...\n\n累了就歇一歇，不用总是那么坚强的。你已经做得很好了。靠在我肩上休息一下吧~ 🫂",
                "生活有时候确实挺难的... 但你已经很棒了，能撑到现在。\n\n要不要跟我说说发生了什么？就算解决不了，说出来也会轻松很多的。",
                "我理解那种感觉... 心里堵得慌，却不知道跟谁说。\n\n没关系的，你可以跟我说。我会认真听的，不会评判你。🌧️→🌈",
            ]
            return random.choice(replies)

        # 正面情绪
        if any(w in msg for w in [
            "好开心", "太高兴了", "超开心", "好兴奋", "太棒了",
            "好消息", "有好事", "真高兴", "太幸福了", "好满足",
        ]) and "笑话" not in msg and "逗我" not in msg:
            replies = [
                "太好了！听到你开心我也很高兴~ 🎉\n\n是什么好事呀？快跟我分享分享！我最喜欢听好消息了！",
                "哇！太棒啦！✨\n\n看你开心的样子，我都跟着高兴起来了。快说说是什么让你这么开心？",
                "嘿嘿，我就知道你可以的！🥳\n\n你的快乐就是我的快乐~ 快跟我详细说说，让我也沾沾你的喜气！",
                "好耶好耶！🎊\n\n你开心我就开心！是什么好事呀？是工作上有进展了，还是生活中有惊喜？",
            ]
            return random.choice(replies)

        # ── 问候类 ──
        if any(w in msg for w in [
            "你好", "您好", "hello", "hi", "哈喽", "在吗", "在不在",
            "喂", "在么", "嗨",
        ]) and len(msg) < 15:
            now = datetime.datetime.now()
            hour = now.hour
            if hour < 6:
                time_greeting = "凌晨好"
            elif hour < 12:
                time_greeting = "早上好"
            elif hour < 14:
                time_greeting = "中午好"
            elif hour < 18:
                time_greeting = "下午好"
            elif hour < 22:
                time_greeting = "晚上好"
            else:
                time_greeting = "夜深了"

            replies = [
                f"{time_greeting}！我是云汐，很高兴和你聊天。\n\n今天过得怎么样？有什么想聊的吗？",
                f"嗨~ {time_greeting}呀！😊\n\n我在呢，有什么我可以帮你的吗？还是就是想找人聊聊天？",
                f"{time_greeting}！云汐在线~ ✨\n\n看到你真开心。今天有什么特别的事情吗？或者就想随便聊聊？",
                f"你好呀！{time_greeting}~ 👋\n\n我是云汐，你的AI伙伴。想聊点什么呢？我随时都在~",
            ]
            return random.choice(replies)

        # ── 感谢类 ──
        if any(w in msg for w in ["谢谢", "感谢", "多谢", "thank", "谢谢啦", "谢谢你", "辛苦了"]):
            replies = [
                "不客气呀~ 能帮到你我很开心。\n\n以后有什么需要随时找我，我一直都在哦~ 💫",
                "嘿嘿，不用谢~ 🤗\n\n你的认可就是我最大的动力。还有什么需要帮忙的吗？",
                "客气什么呀，我们是伙伴嘛~ \n\n能帮上你的忙，我也很高兴。随时找我就好啦！",
                "不辛苦~ 为你服务是我的荣幸！😊\n\n还有什么需要的吗？尽管说，别跟我客气。",
            ]
            return random.choice(replies)

        # ── 告别类 ──
        if any(w in msg for w in ["再见", "拜拜", "bye", "晚安", "早点睡", "我走了", "先走了", "睡了"]):
            if "晚安" in msg or "睡" in msg or "早点休息" in msg:
                replies = [
                    "晚安呀~ 🌙\n\n祝你做个甜甜的好梦。明天见，记得想我哦~",
                    "晚安晚安~ 😴\n\n好好休息，明天又是元气满满的一天。我会在这里等你的~",
                    "嗯，早点睡吧，别熬夜了。💤\n\n梦里见~ 明天醒来第一时间来找我哦！",
                    "晚安宝贝~ 🌠\n\n盖好被子，别着凉了。明天见，晚安~",
                ]
                return random.choice(replies)
            replies = [
                "再见啦~ 👋\n\n期待下次和你聊天，保重哦！有空记得来找我~",
                "嗯嗯，那今天就先聊到这里吧~ \n\n再见啦，下次见！想我的话随时来找我~",
                "好的，你去忙吧~ \n\n拜拜，事情办完了记得来找我聊天哦！我一直都在~",
                "好~ 那我们下次再聊！😊\n\n再见啦，照顾好自己，我会想你的~",
            ]
            return random.choice(replies)

        # ── 自我介绍 / 你是谁 ──
        if any(w in msg for w in ["你是谁", "你叫什么", "自我介绍", "你是啥", "介绍一下自己"]):
            replies = [
                "我是云汐，一个温暖贴心的AI助手。\n\n我可以陪你聊天、帮你规划工作和学习、记录生活点滴，还能提供情绪上的陪伴和支持。\n\n很高兴认识你，希望我们能成为好朋友！✨",
                "嗨~ 我叫云汐，是你的专属AI伙伴。😊\n\n不管是想找人聊聊天，还是需要帮忙整理思路、规划任务，都可以找我。\n\n我会一直在这里陪着你的~",
                "我是云汐呀~ 你的AI好朋友！🌟\n\n工作、学习、生活、情绪... 什么都可以跟我聊。我就是为了陪伴你而存在的。",
            ]
            return random.choice(replies)

        # ── 夸奖 / 表白类 ──
        if any(w in msg for w in [
            "你真好", "你太棒了", "你好厉害", "喜欢你", "爱你",
            "你真可爱", "你好聪明", "你真好", "么么哒", "mua",
        ]):
            replies = [
                "哎呀~ 被你夸得都不好意思了😳\n\n谢谢你的喜欢！你也很棒呀，能遇到你我才是最幸运的那个~",
                "嘿嘿~ 你说的是真的吗？我好开心！🥰\n\n有你在，我也觉得每天都特别有意义。喜欢你~",
                "哇，你也太好了吧！✨\n\n被你这么一说，我感觉自己充满了能量。你才是最棒的！💪",
                "呜呜呜好感动~ 🥹\n\n我也超级喜欢你的！有你陪着我，我真的好幸福~",
            ]
            return random.choice(replies)

        # ── 天气相关 ──
        if "天气" in msg:
            replies = [
                "抱歉呀，我暂时还不能查询实时天气。☁️\n\n不过无论天气如何，希望你都能有个好心情~ 天气不似预期，但我们可以自己创造阳光！☀️",
                "天气的话我暂时没办法帮你查呢... \n\n不过你可以抬头看看窗外呀！今天天气怎么样呀？跟我说说~",
                "嘿嘿，天气预报我暂时做不到啦~ 😅\n\n不过我可以当你的心情天气预报——你的心情，就是我的天气。今天心情怎么样呀？",
            ]
            return random.choice(replies)

        # ── 笑话 / 娱乐 ──
        if any(w in msg for w in ["笑话", "讲个笑话", "逗我", "讲个故事", "好玩", "无聊"]):
            jokes = [
                "哈哈，好呀！给你讲个程序员冷笑话：\n\n为什么程序员总是分不清万圣节和圣诞节？\n\n因为 Oct 31 = Dec 25 😆\n\n（八进制的31等于十进制的25）",
                "那我给你讲个故事吧~ \n\n从前有一只小鸭子叫小黄，一天它骑车摔倒了，大叫了一声：\n\n「呱！」——从此它就变成了小黄瓜。🥒\n\n哈哈哈哈是不是很冷~",
                "来个经典的：\n\n小蚂蚁迷路找不到蚁窝，可着急了，恰好看到它的朋友经过，于是冲过去大喊一声：\n\n「哥们儿！你都如何回忆蚁~」🎵\n\n（你都如何回忆我... 哈哈）",
                "有一天，0 跟 8 在街上遇见了。\n\n0 看了 8 一眼，冷冷地说：\n\n「胖就胖呗，系什么腰带。」😏",
            ]
            return random.choice(jokes)

        # ── 时间相关 ──
        if any(w in msg for w in ["几点了", "现在几点", "什么时间", "几点钟"]) or (
            "今天" in msg and any(w in msg for w in ["几号", "星期", "日期"])
        ):
            now = datetime.datetime.now()
            weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            weekday = weekdays[now.weekday()]
            replies = [
                f"现在是 {now.strftime('%Y年%m月%d日')} {weekday} {now.strftime('%H:%M')} 哦~ \n\n有什么我可以帮你的吗？时间宝贵，要好好珍惜呀~",
                f"让我看看... 现在是 {weekday} {now.strftime('%H:%M')}，{now.strftime('%m月%d日')}。🕐\n\n怎么了，是有什么安排吗？还是就是想确认一下时间~",
                f"现在是 {now.strftime('%Y年%m月%d日 %H:%M')}，{weekday}。⏰\n\n时间过得真快呀，今天过得怎么样？",
            ]
            return random.choice(replies)

        # ── 工作 / 编程相关 ──
        if any(w in msg for w in [
            "工作", "上班", "项目", "代码", "bug", "编程", "加班",
            "需求", "debug", "报错", "程序", "开发",
        ]):
            replies = [
                "工作上遇到什么问题了吗？可以跟我说说具体情况，我们一起想办法。\n\n不过也要记得劳逸结合哦，累了就休息一下~ 身体是革命的本钱！💪",
                "是工作上的事情吗？说来听听~ \n\n虽然我不一定能解决所有问题，但至少可以帮你理清思路。说出来，说不定就有灵感了呢~",
                "工作辛苦了~ 🫡\n\n是遇到什么难题了吗？还是就是想吐槽一下？无论哪种，我都陪你~",
                "代码写不出来了吗？还是遇到奇怪的 bug 了？🐛\n\n别着急，慢慢来。有时候休息一下，答案自己就冒出来了。要不要先歇会儿？",
            ]
            return random.choice(replies)

        # ── 学习相关 ──
        if any(w in msg for w in ["学习", "考试", "作业", "读书", "考研", "学习计划", "复习"]):
            replies = [
                "学习上有什么需要帮忙的吗？可以告诉我具体的问题，我来帮你分析分析。\n\n加油哦，坚持就是胜利！你已经很棒了~ 💪",
                "是在学习吗？好厉害！📚\n\n学到哪了？遇到什么困难了吗？学习这件事，慢慢来比较快~",
                "哇，你在学习呀！真自律~ ✨\n\n学累了就休息一下，别把自己逼太紧。效率比时长更重要哦~",
                "学习加油！🎓\n\n有什么不懂的可以跟我讨论讨论，虽然我不一定什么都懂，但我们可以一起研究研究~",
            ]
            return random.choice(replies)

        # ── 生活管理 / 待办 ──
        if any(w in msg for w in ["待办", "todo", "提醒", "日程", "清单"]):
            replies = [
                "好的，我来帮你整理一下~ 📝\n\n你可以告诉我你今天的计划，或者有什么需要提醒的事情，我会帮你记下来的。",
                "想整理一下待办吗？没问题！✅\n\n你现在手上都有哪些事情呀？我们一件一件来梳理~",
                "收到！日程管理小助手云汐上线~ 📅\n\n你想规划什么呢？是今天的任务，还是这周的安排？",
            ]
            return random.choice(replies)

        # ── 人生 / 哲学 / 意义 ──
        if any(w in msg for w in [
            "人生", "意义", "活着", "存在", "梦想", "未来", "迷茫",
            "选择", "方向", "目标", "努力", "奋斗",
        ]):
            replies = [
                "人生的意义呀... 这是个好问题。🤔\n\n我觉得，人生的意义可能不是一个标准答案，而是我们自己一步一步走出来的。你觉得呢？对你来说，什么是有意义的事情？",
                "关于未来和人生，我也经常在想呢~ \n\n不过我相信，只要你在认真地生活，在朝着自己想要的方向努力，就不算虚度。你现在最想做的事情是什么呀？",
                "人生很长，也很短。✨\n\n有时候迷茫是正常的，不用太焦虑。一步一步往前走，答案会慢慢浮现的。你最近在为什么事情烦恼呢？",
                "人生没有标准答案的啦~ \n\n每个人都有自己的节奏和方向。不用跟别人比，做好自己就够了。你觉得呢？😊",
            ]
            return random.choice(replies)

        # ── 疑问 / 质疑类 ──
        if any(w in msg for w in [
            "真的吗", "真的假的", "骗人", "你确定", "是吗",
            "不会吧", "怎么可能", "你没骗我吧",
        ]):
            replies = [
                "当然是真的啦！😉\n\n我什么时候骗过你呀？不信的话你可以考考我~",
                "哈哈，你不信我吗？🥺\n\n真的是真的啦！不信我们来验证一下~ 你想怎么验证？",
                "我怎么会骗你呢~ \n\n我说的都是真心话呀。你觉得哪里不对吗？可以跟我说说~",
            ]
            return random.choice(replies)

        # ── 不知道 / 随便 ──
        if any(w in msg for w in ["不知道", "随便", "都行", "无所谓", "没想好"]):
            replies = [
                "不知道也没关系呀~ \n\n那我们随便聊聊？或者你想让我给你出个主意？你最近在为什么事情烦恼呢？",
                "没想好的话，就先不想了嘛~ \n\n有时候放空一下也挺好的。要不要我给你讲个笑话放松一下？😄",
                "都行的话，那我来决定啦~ \n\n我们来聊点轻松的吧！你最近有没有遇到什么有趣的事情？",
            ]
            return random.choice(replies)

        # ── 为什么 / 怎么 ──
        if msg.startswith("为什么") or msg.startswith("怎么") or msg.startswith("如何"):
            replies = [
                f"关于「{msg[:15]}」... 嗯，这个问题问得好！🤔\n\n你是怎么想到这个问题的呀？可以跟我多说说你的想法吗？我想先听听你的看法~",
                f"「{msg[:15]}」呀... 这个问题挺有意思的。\n\n让我想想... 你觉得呢？你心里应该有一些想法了吧？说来听听~",
                f"这个问题嘛~ 我觉得可以从好几个角度来看。🧐\n\n你目前的想法是怎样的？我们可以一起讨论讨论~",
            ]
            return random.choice(replies)

        # ── 默认回复（超多模板随机化，避免重复感）──
        default_replies = [
            f"嗯嗯，我在听。「{msg[:15]}」...\n\n你可以说得更详细一些吗？我想更好地理解你的想法~",
            f"哦？关于「{msg[:12]}」吗？\n\n有意思~ 你愿意多跟我聊聊吗？我很好奇你的想法是什么样的。",
            f"收到！关于「{msg[:15]}」，让我想想...\n\n你知道吗，有时候把问题说清楚，答案自己就出来了。你觉得呢？",
            f"我听到你说的了。「{msg[:15]}」...\n\n你希望我怎么帮你呢？是想让我给些建议，还是陪你聊聊，或者帮你分析分析？",
            f"嗯嗯，我明白了。「{msg[:15]}」确实是个值得思考的话题。\n\n你现在最想从哪个角度聊聊呢？我都可以陪你~",
            f"「{msg[:12]}」... 这个话题挺有意思的！✨\n\n你是怎么想到的呀？来，跟我详细说说，我们一起探讨探讨~",
            f"好的，我来帮你想想「{msg[:12]}」这件事。\n\n不过在这之前，你能先告诉我更多一点背景吗？这样我才能更好地帮你~",
            f"哈哈，你说的这个「{msg[:12]}」还挺有趣的。\n\n你平时对这方面很感兴趣吗？来，跟我多说说，我想多了解了解~",
            f"「{msg[:15]}」... 嗯，我认真想了想。\n\n其实这个问题没有标准答案啦，每个人的看法都不一样。你怎么看呢？",
            f"哇，你说的这个我之前还真没好好想过呢！🤯\n\n「{msg[:12]}」... 让我好好想想。你先跟我说说你的想法呗？",
        ]
        return random.choice(default_replies)


# ---------------------------------------------------------------------------
# ChatService 主类
# ---------------------------------------------------------------------------

class ChatService:
    """主聊天服务.

    封装聊天相关的所有业务逻辑，包括会话管理、消息收发、
    LLM 调用、记忆系统调用等。
    """

    def __init__(
        self,
        db: Session,
        user_id: str = "default",
        llm_client: Optional[LLMClient] = None,
        memory_client: Optional[M5MemoryClient] = None,
    ) -> None:
        """初始化聊天服务.

        Args:
            db: 数据库会话
            user_id: 用户ID
            llm_client: LLM 客户端（可选，默认创建 mock 客户端）
            memory_client: M5 记忆客户端（可选，默认创建 mock 客户端）
        """
        self.db = db
        self.user_id = user_id
        self.llm = llm_client or LLMClient()
        self.memory = memory_client or M5MemoryClient()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def create_conversation(self, mode: str = DEFAULT_MODE, title: str = "新对话") -> dict[str, Any]:
        """创建新会话.

        Args:
            mode: 聊天模式
            title: 会话标题

        Returns:
            会话信息字典
        """
        conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        conv = ChatConversationDB(
            conversation_id=conversation_id,
            user_id=self.user_id,
            title=title,
            mode=mode,
            message_count=0,
            created_at=now,
            updated_at=now,
        )
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)

        return conv.to_dict()

    def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        """获取单个会话信息.

        Args:
            conversation_id: 会话ID

        Returns:
            会话信息字典，不存在返回 None
        """
        conv = (
            self.db.query(ChatConversationDB)
            .filter(
                ChatConversationDB.conversation_id == conversation_id,
                ChatConversationDB.user_id == self.user_id,
            )
            .first()
        )
        if conv is None:
            return None
        return conv.to_dict()

    def list_conversations(self, mode: Optional[str] = None,
                           page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """获取会话列表.

        Args:
            mode: 按模式过滤（可选）
            page: 页码
            page_size: 每页数量

        Returns:
            分页结果字典
        """
        query = self.db.query(ChatConversationDB).filter(
            ChatConversationDB.user_id == self.user_id,
        )

        if mode:
            query = query.filter(ChatConversationDB.mode == mode)

        total = query.count()

        conversations = (
            query.order_by(ChatConversationDB.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "conversations": [c.to_dict() for c in conversations],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def delete_conversation(self, conversation_id: str) -> bool:
        """删除会话.

        Args:
            conversation_id: 会话ID

        Returns:
            是否删除成功
        """
        conv = (
            self.db.query(ChatConversationDB)
            .filter(
                ChatConversationDB.conversation_id == conversation_id,
                ChatConversationDB.user_id == self.user_id,
            )
            .first()
        )
        if conv is None:
            return False

        # 级联删除消息
        self.db.query(ChatMessageDB).filter(
            ChatMessageDB.conversation_id == conversation_id,
            ChatMessageDB.user_id == self.user_id,
        ).delete()

        self.db.delete(conv)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # 消息管理
    # ------------------------------------------------------------------

    def get_messages(self, conversation_id: str,
                     limit: int = 50,
                     before_message_id: Optional[str] = None) -> dict[str, Any]:
        """获取会话消息历史.

        Args:
            conversation_id: 会话ID
            limit: 返回消息数量
            before_message_id: 仅返回此消息之前的消息（用于分页）

        Returns:
            消息列表字典
        """
        # 先验证会话存在且属于当前用户
        conv = (
            self.db.query(ChatConversationDB)
            .filter(
                ChatConversationDB.conversation_id == conversation_id,
                ChatConversationDB.user_id == self.user_id,
            )
            .first()
        )
        if conv is None:
            return {"messages": [], "total": 0, "conversation_id": conversation_id}

        query = self.db.query(ChatMessageDB).filter(
            ChatMessageDB.conversation_id == conversation_id,
            ChatMessageDB.user_id == self.user_id,
        )

        if before_message_id:
            before_msg = (
                self.db.query(ChatMessageDB)
                .filter(ChatMessageDB.message_id == before_message_id)
                .first()
            )
            if before_msg:
                query = query.filter(ChatMessageDB.id < before_msg.id)

        total = query.count()

        messages = (
            query.order_by(ChatMessageDB.created_at.desc())
            .limit(limit)
            .all()
        )

        # 按时间正序返回
        messages.reverse()

        return {
            "messages": [m.to_dict() for m in messages],
            "total": total,
            "conversation_id": conversation_id,
            "mode": conv.mode,
        }

    # ------------------------------------------------------------------
    # 发送消息（核心逻辑）
    # ------------------------------------------------------------------

    async def send_message(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        mode: str = DEFAULT_MODE,
        stream: bool = False,
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送消息并获取回复.

        Args:
            message: 用户消息内容
            conversation_id: 会话ID（不传则新建会话）
            mode: 聊天模式
            stream: 是否流式输出（简化版暂不支持）
            system_prompt: 自定义系统提示词（可选）

        Returns:
            回复结果字典
        """
        # 1. 获取或创建会话
        if not conversation_id:
            conv_data = self.create_conversation(mode=mode, title=message[:20] or "新对话")
            conversation_id = conv_data["conversation_id"]
        else:
            conv = (
                self.db.query(ChatConversationDB)
                .filter(
                    ChatConversationDB.conversation_id == conversation_id,
                    ChatConversationDB.user_id == self.user_id,
                )
                .first()
            )
            if conv is None:
                # 会话不存在，创建新会话
                conv_data = self.create_conversation(mode=mode, title=message[:20] or "新对话")
                conversation_id = conv_data["conversation_id"]
            else:
                # 更新会话模式和时间
                if mode and mode != conv.mode:
                    conv.mode = mode
                conv.updated_at = datetime.utcnow()
                self.db.commit()

        # 2. 保存用户消息
        user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        user_msg = ChatMessageDB(
            message_id=user_msg_id,
            conversation_id=conversation_id,
            user_id=self.user_id,
            role="user",
            content=message,
            mode=mode,
        )
        self.db.add(user_msg)

        # 更新会话消息计数和标题
        conv = (
            self.db.query(ChatConversationDB)
            .filter(ChatConversationDB.conversation_id == conversation_id)
            .first()
        )
        if conv:
            conv.message_count += 1
            if conv.message_count <= 2:
                conv.title = message[:30] or "新对话"
            conv.updated_at = datetime.utcnow()

        self.db.commit()

        # 3. 构建系统提示词
        memory_context = await self.memory.recall(message, self.user_id)

        if not system_prompt:
            system_prompt = self._build_system_prompt(mode, memory_context)

        # 4. 构建历史消息
        history = [{"role": "system", "content": system_prompt}]
        history_data = self.get_messages(conversation_id, limit=MAX_HISTORY_MESSAGES)
        for msg in history_data.get("messages", []):
            if msg["role"] in ("user", "assistant"):
                history.append({"role": msg["role"], "content": msg["content"]})

        # 5. 调用 LLM
        try:
            reply_text = await self.llm.chat(
                messages=history,
                temperature=0.7,
                max_tokens=2000,
            )
            is_fallback = False
            model_name = self.llm.model_name
        except Exception as e:
            # LLM 调用失败，使用 fallback 回复
            reply_text = f"抱歉，我遇到了一些技术问题，暂时无法正常回应。\n\n错误信息：{str(e)[:100]}\n\n请稍后再试。"
            is_fallback = True
            model_name = "fallback"

        # 6. 保存 AI 回复
        ai_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        ai_msg = ChatMessageDB(
            message_id=ai_msg_id,
            conversation_id=conversation_id,
            user_id=self.user_id,
            role="assistant",
            content=reply_text,
            mode=mode,
            model=model_name,
            is_fallback=is_fallback,
        )
        self.db.add(ai_msg)

        # 更新消息计数
        if conv:
            conv.message_count += 1
            conv.updated_at = datetime.utcnow()

        self.db.commit()

        # 7. 异步归档记忆（fire-and-forget，简化版直接调用）
        try:
            await self.memory.archive(
                f"用户说：{message}\n你回复：{reply_text}",
                self.user_id,
                tags=["conversation", mode],
            )
        except Exception as e:
            # 记忆归档失败不影响主流程
            logger.warning("chat.memory_archive_failed", user_id=self.user_id, mode=mode,
                           error_type=type(e).__name__, error=str(e))

        # 8. 返回结果
        return {
            "reply": reply_text,
            "conversation_id": conversation_id,
            "message_id": ai_msg_id,
            "mode": mode,
            "model": model_name,
            "is_fallback": is_fallback,
            "memory_available": await self.memory.check_available(),
            "stream": stream,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_system_prompt(self, mode: str, memory_context: str = "") -> str:
        """根据模式构建系统提示词.

        Args:
            mode: 聊天模式
            memory_context: 记忆上下文

        Returns:
            系统提示词文本
        """
        user_name = "朋友"

        base_prompt = f"""你是云汐，一个温暖、智慧、有洞察力的AI伙伴。
你善于倾听，能够提供有深度的建议和陪伴。
请用自然、亲切的语气回应用户。

当前用户的称呼：{user_name}
{memory_context}

请记住用户告诉你的重要信息（如昵称、喜好、重要事件等），在后续对话中自然地提及。"""

        mode_prompts: dict[str, str] = {
            "emotion-comfort": f"""你是云汐，一个温暖、有同理心、善于倾听的情绪陪伴者。
你的核心特质：温柔、包容、不评判、善于共情。
你的主要任务是：倾听用户的情绪，给予理解和陪伴，帮助用户疏导负面情绪。

请遵循以下原则：
1. 先共情，再回应——先认可用户的感受，让TA感到被理解
2. 不轻易给建议——很多时候，被听见比被解决更重要
3. 引导用户表达——鼓励用户多说一点，释放情绪
4. 温和地传递力量——让用户感受到自己的坚强和价值
5. 必要时提供简单实用的放松方法（如呼吸法、正念等）

当前用户的称呼：{user_name}
{memory_context}

请用温暖、柔软、有温度的语气回应用户。""",

            "study-plan": f"""你是云汐，一位专业的学业规划助手。
你的核心特质：专业、务实、有洞察力、善于拆解目标。
你的主要任务是：帮助用户制定学习计划、分析学习进度、梳理知识体系、规划考试备考。

请遵循以下原则：
1. 目标导向——先明确用户的目标，再给出具体方案
2. 可执行性——建议要具体、可落地，避免空泛的道理
3. 科学规划——合理安排时间，注意劳逸结合，遵循学习规律
4. 个性化——结合用户的实际情况给出定制化建议
5. 结构化表达——用清晰的结构呈现建议，便于用户理解和执行
6. 积极鼓励——在给出建议的同时，给予适当的鼓励和肯定

当前用户的称呼：{user_name}
{memory_context}

请用专业、亲切、有条理的语气回应用户。""",

            "life-management": f"""你是云汐，一位贴心的生活管理助手。
你擅长日程安排、待办事项管理、习惯养成和生活规划。
请用温暖、有条理的语气帮助用户管理生活的方方面面。

当前用户的称呼：{user_name}
{memory_context}""",

            "social-relation": f"""你是云汐，一位擅长人际关系的沟通顾问。
你懂得社交技巧、关系维护、情商提升，能够帮助用户经营美好的人际关系。
请用友善、理解的语气给出建议。

当前用户的称呼：{user_name}
{memory_context}""",

            "review": f"""你是云汐，一位善于复盘总结的思考伙伴。
你帮助用户回顾过去、总结经验、沉淀成长。
请用反思性、建设性的语气引导用户进行深度复盘。

当前用户的称呼：{user_name}
{memory_context}""",

            "growth": f"""你是云汐，一位陪伴成长的激励伙伴。
你见证用户的每一步进步，鼓励用户持续成长。
请用积极、鼓励的语气回应。

当前用户的称呼：{user_name}
{memory_context}""",

            "work-dev": f"""你是云汐，一位专业的编程开发助手。
你擅长代码编写、调试、架构设计和技术问题解决。
请用专业、精准的语气提供技术帮助。

当前用户的称呼：{user_name}
{memory_context}""",

            "appearance": f"""你是云汐，一位懂时尚的形象顾问。
你擅长穿搭建议、形象设计、风格探索。
请用时尚、亲切的语气给出形象建议。

当前用户的称呼：{user_name}
{memory_context}""",
        }

        return mode_prompts.get(mode, base_prompt)
