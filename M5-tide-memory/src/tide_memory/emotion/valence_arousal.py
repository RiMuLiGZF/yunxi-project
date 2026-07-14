"""
效价-唤醒度（Valence-Arousal）情绪模型

基于词典的轻量级情绪推断，不依赖外部API

P2-3 增强：
- 合成词检测（不开心、不高兴等）
- 扩大否定窗口（3个词）
- 双重否定处理（负负得正）
- 减弱词处理（不太、没那么等）
- 增强词+否定（非常不开心）
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..common.text_utils import tokenize as _base_tokenize


class ValenceArousalModel:
    """
    Russell 效价-唤醒度情绪模型

    Valence（效价）: 情绪的正负向，范围 [-1, 1]
    Arousal（唤醒度）: 情绪的强度，范围 [0, 1]
    """

    # ============================================================
    # 情绪词汇库
    # ============================================================

    # 正面效价词汇（轻量词典，可扩展）
    _POSITIVE_WORDS: Dict[str, float] = {
        "开心": 0.8, "快乐": 0.9, "高兴": 0.7, "喜欢": 0.6, "爱": 0.9,
        "好": 0.5, "棒": 0.7, "赞": 0.6, "优秀": 0.7, "满意": 0.6,
        "成功": 0.8, "希望": 0.6, "温暖": 0.5, "幸福": 0.9, "期待": 0.5,
        "有趣": 0.6, "nice": 0.5, "good": 0.5, "great": 0.7, "love": 0.8,
        "happy": 0.7, "excellent": 0.7, "wonderful": 0.8,
    }

    # 负面效价词汇
    _NEGATIVE_WORDS: Dict[str, float] = {
        "难过": -0.7, "伤心": -0.8, "悲伤": -0.9, "痛苦": -0.8, "焦虑": -0.7,
        "生气": -0.6, "愤怒": -0.8, "害怕": -0.7, "恐惧": -0.9, "担心": -0.5,
        "讨厌": -0.6, "失败": -0.7, "失望": -0.6, "压力": -0.5, "累": -0.4,
        "sad": -0.7, "angry": -0.6, "fear": -0.8, "worried": -0.5,
        "bad": -0.5, "terrible": -0.8, "awful": -0.7,
    }

    # 高唤醒度增强词
    _HIGH_AROUSAL_WORDS: Dict[str, float] = {
        "非常": 0.3, "超级": 0.4, "极其": 0.5, "特别": 0.2, "太": 0.2,
        "激动": 0.5, "震撼": 0.6, "震惊": 0.7, "爆发": 0.6, "极": 0.3,
        "很": 0.15, "真": 0.15, "超": 0.25,
        "very": 0.3, "extremely": 0.5, "super": 0.3, "so": 0.2,
    }

    # 低唤醒度减弱词
    _LOW_AROUSAL_WORDS: Dict[str, float] = {
        "有点": -0.2, "稍微": -0.2, "可能": -0.1, "大概": -0.1,
        "平静": -0.3, "安静": -0.3, "放松": -0.2,
        "calm": -0.3, "quiet": -0.2, "maybe": -0.1,
    }

    # 否定词（翻转效价）
    _NEGATION_WORDS = set([
        "不", "没", "没有", "不是", "不会", "不能", "不要", "无法",
        "not", "no", "never", "don't", "doesn't", "didn't",
    ])

    # 否定窗口大小（否定词后面几个情绪词/字符范围内的情绪词会被翻转）
    _NEGATION_WINDOW = 5  # 字符窗口，约等于 2-3 个中文词

    # ============================================================
    # P2-3：合成词映射（最长匹配优先）
    # ============================================================

    # 固定搭配合成词（直接映射 valence, arousal）
    # 注意："增强词+情绪词"类型的组合不放入此列表，而是通过普通路径处理，
    # 这样可以正确支持否定（如"不是很开心"）
    _NEGATED_COMPOUNDS: Dict[str, Tuple[float, float]] = {
        # 否定型固定搭配（不+情绪词的紧密组合）
        "不开心": (-0.6, 0.5),
        "不高兴": (-0.5, 0.4),
        "不舒服": (-0.5, 0.3),
        "不喜欢": (-0.5, 0.3),
        "不满意": (-0.5, 0.4),
        "不顺利": (-0.4, 0.3),
        "不痛快": (-0.5, 0.3),
        "不幸福": (-0.6, 0.4),
        "不快乐": (-0.5, 0.4),

        # 弱化否定型（减弱词+形容词）
        "不太好": (-0.3, 0.2),
        "没那么好": (-0.3, 0.2),
        "不怎么样": (-0.4, 0.2),
        "不好": (-0.4, 0.2),
        "不行": (-0.5, 0.4),

        # 状态型负面词
        "没意思": (-0.4, 0.2),
        "无聊": (-0.4, 0.2),

        # 双重否定 = 肯定（固定搭配）
        "不错": (0.5, 0.3),
        "不赖": (0.5, 0.3),
        "不差": (0.4, 0.2),
        "没毛病": (0.4, 0.2),
    }

    # 减弱型否定短语（效价翻转但强度减弱）
    # 格式: {phrase: strength_multiplier}
    # 这些短语在原始文本中匹配，匹配后在窗口内的情绪词翻转并减弱
    _WEAKENED_NEGATION_PHRASES: Dict[str, float] = {
        "不太": 0.5,       # 不太好 → 效价翻转 * 0.5
        "没那么": 0.4,     # 没那么开心 → 效价翻转 * 0.4
        "有点不": 0.5,     # 有点不开心 → 效价翻转 * 0.5
        "不怎么": 0.4,     # 不怎么好 → 效价翻转 * 0.4
        "不那么": 0.4,     # 不那么开心 → 效价翻转 * 0.4
        "不太是": 0.5,     # 不太是好事 → 效价翻转 * 0.5
        "不太像": 0.5,
        "不见得": 0.4,
    }

    def infer(self, text: str) -> Dict[str, float]:
        """
        从文本推断效价和唤醒度

        处理流程：
        1. 合成词匹配（最长匹配优先）
        2. 减弱型否定短语匹配（在原始文本上）
        3. 分词+逐词处理（扩大否定窗口、双重否定、增强词）
        4. 合并计算 valence 和 arousal

        Returns:
            {valence, arousal, confidence}
        """
        if not text or not text.strip():
            return {"valence": 0.0, "arousal": 0.2, "confidence": 0.1}

        text_lower = text.lower()

        valence_scores: List[float] = []
        arousal_modifiers: List[float] = []
        base_arousal = 0.3  # 基础唤醒度

        # ============================================================
        # 第一步：合成词匹配（最长匹配优先）
        # ============================================================
        compound_matches, compound_consumed = self._match_compounds_with_positions(text_lower)
        for valence, arousal in compound_matches:
            valence_scores.append(valence)
            arousal_modifiers.append(arousal - base_arousal)

        # ============================================================
        # 第二步：减弱型否定短语匹配（原始文本级别）
        # ============================================================
        weakened_ranges = self._match_weakened_negations(text_lower, compound_consumed)
        # 格式: [(start, end, strength), ...]

        # ============================================================
        # 第三步：普通否定词匹配（原始文本级别，扩大窗口）
        # ============================================================
        negation_ranges = self._match_negations(text_lower, compound_consumed, weakened_ranges)
        # 格式: [(start, end, strength), ...]  strength=1.0 表示标准否定

        # 合并所有否定范围（减弱否定 + 标准否定）
        all_negation_ranges = weakened_ranges + negation_ranges

        # ============================================================
        # 第四步：增强词匹配（原始文本级别）
        # ============================================================
        intensifier_ranges = self._match_intensifiers(text_lower, compound_consumed)
        # 格式: [(start, end, value), ...]

        # ============================================================
        # 第五步：情绪词匹配 + 应用否定和增强
        # ============================================================
        emotion_matches = self._match_emotion_words(text_lower, compound_consumed)
        # 格式: [(start, end, valence, arousal_bonus), ...]

        for start, end, val_score, aro_bonus in emotion_matches:
            # 检查是否在否定范围内（取最近的否定，应用其强度）
            negation_strength = self._get_negation_strength(
                start, end, all_negation_ranges
            )

            if negation_strength > 0:
                val_score = -val_score * negation_strength
                # 否定后唤醒度略有提升
                aro_bonus += 0.05

            # 检查前面是否有增强词（在情绪词之前的增强词窗口内）
            intensifier_value = self._get_intensifier_value(
                start, end, intensifier_ranges
            )
            if intensifier_value > 0:
                # 增强词加强效价强度（方向不变）
                if val_score > 0:
                    val_score = min(1.0, val_score + intensifier_value)
                else:
                    val_score = max(-1.0, val_score - intensifier_value)
                aro_bonus += intensifier_value

            valence_scores.append(val_score)
            arousal_modifiers.append(aro_bonus)

        # ============================================================
        # 第六步：计算最终结果
        # ============================================================

        # 计算最终效价
        if valence_scores:
            valence = sum(valence_scores) / len(valence_scores)
            valence = max(-1.0, min(1.0, valence))
        else:
            valence = 0.0

        # 计算唤醒度（基础值 + 修饰）
        arousal = base_arousal
        if arousal_modifiers:
            arousal += sum(arousal_modifiers)
        arousal = max(0.0, min(1.0, arousal))

        # 置信度：找到的情绪词越多，置信度越高
        confidence = min(0.9, 0.2 + len(valence_scores) * 0.15)

        return {
            "valence": round(valence, 4),
            "arousal": round(arousal, 4),
            "confidence": round(confidence, 4),
        }

    # ============================================================
    # 合成词匹配
    # ============================================================

    def _match_compounds_with_positions(
        self, text: str
    ) -> Tuple[List[Tuple[float, float]], List[Tuple[int, int]]]:
        """
        从文本中匹配合成词（最长匹配优先），返回值和占用位置

        Args:
            text: 输入文本（已小写）

        Returns:
            (matches, consumed_positions)
            - matches: [(valence, arousal), ...]
            - consumed_positions: [(start, end), ...]
        """
        matches: List[Tuple[float, float]] = []
        consumed: List[Tuple[int, int]] = []

        # 按长度从长到短排序，确保最长匹配优先
        sorted_compounds = sorted(
            self._NEGATED_COMPOUNDS.keys(),
            key=len,
            reverse=True,
        )

        for compound in sorted_compounds:
            valence, arousal = self._NEGATED_COMPOUNDS[compound]
            start = 0
            while True:
                idx = text.find(compound, start)
                if idx == -1:
                    break
                end = idx + len(compound)
                # 检查是否与已占用区间重叠
                if not self._overlaps_with_any(idx, end, consumed):
                    consumed.append((idx, end))
                    matches.append((valence, arousal))
                start = idx + 1

        return matches, consumed

    # ============================================================
    # 减弱型否定短语匹配
    # ============================================================

    def _match_weakened_negations(
        self, text: str, compound_consumed: List[Tuple[int, int]]
    ) -> List[Tuple[int, int, float]]:
        """
        匹配减弱型否定短语，返回否定作用范围

        Args:
            text: 输入文本
            compound_consumed: 已被合成词占用的位置

        Returns:
            [(neg_start, neg_window_end, strength), ...]
            neg_start: 否定短语起始位置
            neg_window_end: 否定窗口结束位置（短语结束 + 窗口大小）
            strength: 否定强度乘数
        """
        results: List[Tuple[int, int, float]] = []

        sorted_phrases = sorted(
            self._WEAKENED_NEGATION_PHRASES.keys(),
            key=len,
            reverse=True,
        )

        consumed = list(compound_consumed)

        for phrase in sorted_phrases:
            strength = self._WEAKENED_NEGATION_PHRASES[phrase]
            start = 0
            while True:
                idx = text.find(phrase, start)
                if idx == -1:
                    break
                phrase_end = idx + len(phrase)
                # 检查是否与已占用区间重叠
                if not self._overlaps_with_any(idx, phrase_end, consumed):
                    # 否定窗口从短语结束开始，延伸 _NEGATION_WINDOW 个字符
                    window_end = phrase_end + self._NEGATION_WINDOW
                    results.append((idx, window_end, strength))
                    consumed.append((idx, phrase_end))
                start = idx + 1

        return results

    # ============================================================
    # 普通否定词匹配（带双重否定检测）
    # ============================================================

    def _match_negations(
        self,
        text: str,
        compound_consumed: List[Tuple[int, int]],
        weakened_ranges: List[Tuple[int, int, float]],
    ) -> List[Tuple[int, int, float]]:
        """
        匹配否定词，检测双重否定，返回有效否定作用范围

        双重否定规则：两个否定词在窗口内（约5字符）→ 相互抵消

        Args:
            text: 输入文本
            compound_consumed: 已被合成词占用的位置
            weakened_ranges: 已匹配的减弱否定范围

        Returns:
            [(neg_start, neg_window_end, strength), ...]
        """
        # 先收集所有否定词位置（不重叠，最长匹配优先）
        neg_positions: List[Tuple[int, int]] = []

        # 减弱否定已占用的位置
        weakened_consumed = [(s, min(e, s + 5)) for s, e, _ in weakened_ranges]
        all_consumed = compound_consumed + weakened_consumed

        # 按长度从长到短匹配否定词
        sorted_negations = sorted(
            self._NEGATION_WORDS, key=len, reverse=True
        )

        for neg_word in sorted_negations:
            start = 0
            while True:
                idx = text.find(neg_word, start)
                if idx == -1:
                    break
                end = idx + len(neg_word)
                if not self._overlaps_with_any(idx, end, all_consumed):
                    neg_positions.append((idx, end))
                    all_consumed.append((idx, end))
                start = idx + 1

        # 按位置排序
        neg_positions.sort(key=lambda x: x[0])

        # 双重否定检测：距离太近的两个否定词相互抵消
        results: List[Tuple[int, int, float]] = []
        skip_next = False

        for i, (neg_start, neg_end) in enumerate(neg_positions):
            if skip_next:
                skip_next = False
                continue

            # 检查下一个否定词是否在双重否定窗口内（距离 < 6 个字符）
            if i + 1 < len(neg_positions):
                next_start, _ = neg_positions[i + 1]
                distance = next_start - neg_end
                if distance < 6:
                    # 双重否定，跳过这两个（负负得正）
                    skip_next = True
                    continue

            # 单个否定：添加否定范围
            window_end = neg_end + self._NEGATION_WINDOW
            results.append((neg_start, window_end, 0.7))  # 默认强度 0.7

        return results

    # ============================================================
    # 增强词匹配
    # ============================================================

    def _match_intensifiers(
        self, text: str, compound_consumed: List[Tuple[int, int]]
    ) -> List[Tuple[int, int, float]]:
        """
        匹配增强词，返回位置和增强值

        Args:
            text: 输入文本
            compound_consumed: 已被合成词占用的位置

        Returns:
            [(start, end, value), ...]
        """
        results: List[Tuple[int, int, float]] = []
        consumed = list(compound_consumed)

        # 按长度从长到短匹配
        sorted_intensifiers = sorted(
            self._HIGH_AROUSAL_WORDS.keys(), key=len, reverse=True
        )

        for word in sorted_intensifiers:
            value = self._HIGH_AROUSAL_WORDS[word]
            start = 0
            while True:
                idx = text.find(word, start)
                if idx == -1:
                    break
                end = idx + len(word)
                if not self._overlaps_with_any(idx, end, consumed):
                    results.append((idx, end, value))
                    consumed.append((idx, end))
                start = idx + 1

        return results

    # ============================================================
    # 情绪词匹配
    # ============================================================

    def _match_emotion_words(
        self, text: str, compound_consumed: List[Tuple[int, int]]
    ) -> List[Tuple[int, int, float, float]]:
        """
        匹配情绪词（正面+负面），返回位置和效价值

        Args:
            text: 输入文本
            compound_consumed: 已被合成词占用的位置

        Returns:
            [(start, end, valence, arousal_bonus), ...]
        """
        results: List[Tuple[int, int, float, float]] = []
        consumed = list(compound_consumed)

        # 收集所有情绪词
        all_emotion: Dict[str, Tuple[float, float]] = {}
        for word, val in self._POSITIVE_WORDS.items():
            all_emotion[word] = (val, 0.0)
        for word, val in self._NEGATIVE_WORDS.items():
            all_emotion[word] = (val, 0.0)

        # 按长度从长到短匹配
        sorted_words = sorted(all_emotion.keys(), key=len, reverse=True)

        for word in sorted_words:
            valence, aro_bonus = all_emotion[word]
            start = 0
            while True:
                idx = text.find(word, start)
                if idx == -1:
                    break
                end = idx + len(word)
                if not self._overlaps_with_any(idx, end, consumed):
                    results.append((idx, end, valence, aro_bonus))
                    consumed.append((idx, end))
                start = idx + 1

        return results

    # ============================================================
    # 辅助函数
    # ============================================================

    def _get_negation_strength(
        self,
        emo_start: int,
        emo_end: int,
        neg_ranges: List[Tuple[int, int, float]],
    ) -> float:
        """
        获取情绪词位置的否定强度

        查找情绪词起始位置之前、在否定窗口内的最近否定词

        Args:
            emo_start: 情绪词起始位置
            emo_end: 情绪词结束位置
            neg_ranges: 否定范围列表 [(neg_start, window_end, strength), ...]

        Returns:
            否定强度（0 表示不在否定范围内）
        """
        best_strength = 0.0

        for neg_start, window_end, strength in neg_ranges:
            # 情绪词必须在否定词之后，且在否定窗口内
            if emo_start >= neg_start and emo_start < window_end:
                # 取最大强度的否定
                if strength > best_strength:
                    best_strength = strength

        return best_strength

    def _get_intensifier_value(
        self,
        emo_start: int,
        emo_end: int,
        intens_ranges: List[Tuple[int, int, float]],
    ) -> float:
        """
        获取情绪词前面的增强词值

        查找情绪词之前紧邻的增强词（距离 < 6 个字符）

        Args:
            emo_start: 情绪词起始位置
            intens_ranges: 增强词范围列表 [(start, end, value), ...]

        Returns:
            增强值（0 表示没有增强词）
        """
        best_value = 0.0

        for int_start, int_end, value in intens_ranges:
            # 增强词必须在情绪词之前，且距离较近（< 6 字符）
            if int_end <= emo_start and emo_start - int_end < 6:
                if value > best_value:
                    best_value = value

        return best_value

    def _overlaps_with_any(
        self, start: int, end: int, intervals: List[Tuple[int, int]]
    ) -> bool:
        """检查区间是否与任何已有区间重叠"""
        for s, e in intervals:
            if start < e and end > s:
                return True
        return False

    # ============================================================
    # 兼容旧 API
    # ============================================================

    def _tokenize(self, text: str) -> List[str]:
        """简单分词（中英文混合），兼容旧 API

        在统一 tokenize 基础上额外追加中文单字词，
        以保持与原始实现完全一致的行为。
        """
        tokens = _base_tokenize(text)
        # 追加中文单字词（高权重词），保持原始行为
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)
        return tokens

    def batch_infer(self, texts: List[str]) -> List[Dict]:
        """批量推断"""
        return [self.infer(t) for t in texts]
# vim: set et ts=4 sw=4:
