"""语音润色扩展.

对技能输出的文本进行润色、格式调整、口语化处理等。
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger()


class VoicePolishConfig:
    """语音润色配置."""

    def __init__(
        self,
        tone: str = "friendly",  # friendly, professional, humorous, formal
        speed: str = "normal",  # slow, normal, fast
        remove_markdown: bool = True,
        add_pauses: bool = True,
        max_sentence_length: int = 30,
    ) -> None:
        self.tone = tone
        self.speed = speed
        self.remove_markdown = remove_markdown
        self.add_pauses = add_pauses
        self.max_sentence_length = max_sentence_length


class VoicePolisher:
    """语音文本润色器.

    将普通文本转换为更适合语音播报的格式。
    """

    def __init__(self, config: VoicePolishConfig | None = None) -> None:
        self._config = config or VoicePolishConfig()

    def polish(self, text: str, context: dict[str, Any] | None = None) -> str:
        """润色文本.

        Args:
            text: 原始文本.
            context: 上下文信息.

        Returns:
            润色后的文本.
        """
        if not text:
            return text

        result = text

        # 移除 Markdown 格式
        if self._config.remove_markdown:
            result = self._strip_markdown(result)

        # 调整语气
        result = self._adjust_tone(result)

        # 长句拆分
        if self._config.max_sentence_length > 0:
            result = self._split_long_sentences(result)

        # 添加停顿标记
        if self._config.add_pauses:
            result = self._add_pauses(result)

        return result.strip()

    def _strip_markdown(self, text: str) -> str:
        """移除 Markdown 标记."""
        # 移除标题标记
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # 移除粗体/斜体
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        # 移除行内代码
        text = re.sub(r'`(.+?)`', r'\1', text)
        # 移除代码块
        text = re.sub(r'```[\s\S]*?```', '', text)
        # 移除链接，保留文字
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        # 移除列表标记
        text = re.sub(r'^[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
        # 移除水平线
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
        # 移除引用
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        return text

    def _adjust_tone(self, text: str) -> str:
        """调整语气风格."""
        tone = self._config.tone

        if tone == "friendly":
            # 添加友好语气词
            if not text.endswith(("。", "！", "？", "!", "?", ".")):
                text += "。"
            return text

        elif tone == "professional":
            # 移除口语化表达
            text = re.sub(r'[嗯啊呃哦]', '', text)
            return text

        elif tone == "humorous":
            # 保持原样，可在未来扩展
            return text

        elif tone == "formal":
            # 正式语气
            text = re.sub(r'[呢啊哦啦]', '', text)
            return text

        return text

    def _split_long_sentences(self, text: str) -> str:
        """拆分长句."""
        max_len = self._config.max_sentence_length
        # 按句号、问号、感叹号分句
        sentences = re.split(r'(?<=[。！？.!?])', text)
        result_parts = []

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= max_len:
                result_parts.append(sent)
            else:
                # 尝试用逗号、分号拆分
                chunks = re.split(r'(?<=[，,；;])', sent)
                current = ""
                for chunk in chunks:
                    if len(current) + len(chunk) <= max_len:
                        current += chunk
                    else:
                        if current:
                            result_parts.append(current.strip())
                        current = chunk
                if current:
                    result_parts.append(current.strip())

        return "".join(result_parts)

    def _add_pauses(self, text: str) -> str:
        """添加适当的停顿（通过标点符号增强）."""
        # 在句号后添加轻微停顿（用省略号表示较长停顿）
        # 这里保持简单，不做过多修改
        return text

    def format_for_tts(self, text: str, ssml: bool = False) -> str:
        """格式化为 TTS 友好的格式.

        Args:
            text: 原始文本.
            ssml: 是否生成 SSML 格式.

        Returns:
            TTS 格式文本.
        """
        polished = self.polish(text)

        if not ssml:
            return polished

        # 简单 SSML 包装
        rate_map = {"slow": "slow", "normal": "medium", "fast": "fast"}
        rate = rate_map.get(self._config.speed, "medium")

        return (
            f'<speak><prosody rate="{rate}">'
            f'{polished}'
            f'</prosody></speak>'
        )
