"""
查询改写模块 (Query Rewriter)

实现 4 种查询增强策略：
1. 查询扩展（Query Expansion）- 同义词扩展、相关术语补充
2. 查询分解（Query Decomposition）- 复杂问题拆分为多个子问题
3. 多轮改写（Conversational Rewrite）- 结合对话历史改写
4. 假设性文档生成（HyDE）- 生成假设性回答文档用于检索

纯 Python 实现，不依赖外部 LLM 服务。
当配置了 LLM 回调函数时，可使用 LLM 增强改写质量。
"""

from __future__ import annotations

import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable


class RewriteStrategy(str, Enum):
    """改写策略枚举"""
    EXPANSION = "expansion"           # 查询扩展
    DECOMPOSITION = "decomposition"   # 查询分解
    CONVERSATIONAL = "conversational"  # 多轮改写
    HYDE = "hyde"                     # 假设性文档生成


@dataclass
class RewriteResult:
    """改写结果"""
    original_query: str
    rewritten_queries: List[str]
    strategy: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_query": self.original_query,
            "rewritten_queries": self.rewritten_queries,
            "strategy": self.strategy,
            "metadata": self.metadata,
            "count": len(self.rewritten_queries),
        }


# ============================================================
# 内置同义词词典（常见领域）
# ============================================================

# 中文同义词组（简单版）
_SYNONYMS_CN: Dict[str, List[str]] = {
    "人工智能": ["AI", "机器学习", "深度学习", "神经网络"],
    "机器学习": ["AI", "人工智能", "深度学习", "模型训练"],
    "深度学习": ["神经网络", "CNN", "RNN", "Transformer"],
    "数据库": ["DB", "数据存储", "SQL", "NoSQL"],
    "性能": ["效率", "速度", "响应时间", "吞吐量"],
    "优化": ["改进", "提升", "增强", "调优"],
    "错误": ["异常", "bug", "问题", "故障"],
    "配置": ["设置", "参数", "选项", "配置项"],
    "部署": ["上线", "发布", "安装", "运维"],
    "测试": ["验证", "检验", "质量保证", "QA"],
    "安全": ["防护", "加密", "权限", "认证"],
    "用户": ["使用者", "客户", "终端用户"],
    "系统": ["平台", "架构", "体系"],
    "功能": ["特性", "能力", "模块"],
    "接口": ["API", "端点", "服务接口"],
    "缓存": ["高速缓存", "Cache", "内存存储"],
    "监控": ["观测", "告警", "指标"],
    "日志": ["记录", "log", "运行记录"],
    "并发": ["并行", "多线程", "高并发"],
    "分布式": ["集群", "微服务", "分布式系统"],
}

# 英文同义词组
_SYNONYMS_EN: Dict[str, List[str]] = {
    "performance": ["speed", "efficiency", "throughput", "latency", "response time"],
    "error": ["bug", "issue", "exception", "failure", "problem"],
    "database": ["db", "data store", "sql", "nosql", "storage"],
    "configuration": ["config", "settings", "setup", "parameters"],
    "deployment": ["deploy", "release", "launch", "rollout"],
    "optimization": ["optimization", "improvement", "enhancement", "tuning"],
    "security": ["safety", "protection", "encryption", "authentication"],
    "testing": ["test", "validation", "verification", "QA"],
    "cache": ["caching", "memory cache", "buffer"],
    "monitoring": ["observability", "metrics", "alerting", "monitor"],
    "api": ["interface", "endpoint", "service"],
    "user": ["customer", "client", "end user"],
    "system": ["platform", "architecture", "framework"],
    "feature": ["function", "capability", "module"],
    "distributed": ["cluster", "microservice", "scalable"],
}


def _get_synonyms(term: str) -> List[str]:
    """获取术语的同义词"""
    term_lower = term.lower()

    # 英文
    if re.match(r'^[a-zA-Z]+$', term_lower):
        if term_lower in _SYNONYMS_EN:
            return _SYNONYMS_EN[term_lower]
        # 尝试部分匹配
        for key, syns in _SYNONYMS_EN.items():
            if term_lower in key or key in term_lower:
                return syns[:3]

    # 中文
    if re.match(r'^[\u4e00-\u9fff]+$', term):
        if term in _SYNONYMS_CN:
            return _SYNONYMS_CN[term]
        # 尝试部分匹配
        for key, syns in _SYNONYMS_CN.items():
            if term in key or key in term:
                return syns[:3]

    return []


def _extract_key_terms(query: str) -> List[str]:
    """从查询中提取关键术语"""
    terms = []

    # 提取中文词组（2-4 字）
    chinese_segs = re.findall(r'[\u4e00-\u9fff]{2,6}', query)
    terms.extend(chinese_segs)

    # 提取英文单词（3 字母以上）
    english_words = re.findall(r'[a-zA-Z]{3,}', query)
    terms.extend([w.lower() for w in english_words])

    # 提取数字 + 单位
    number_units = re.findall(r'\d+(?:\.\d+)?\s*(?:%|倍|个|条|项|MB|GB|KB)', query)
    terms.extend(number_units)

    return terms


# ============================================================
# 1. 查询扩展
# ============================================================

def expand_query(query: str, max_expansions: int = 3) -> List[str]:
    """
    查询扩展（Query Expansion）

    基于同义词词典扩展查询，生成多个相关查询。

    策略：
    1. 提取查询中的关键术语
    2. 查找每个术语的同义词
    3. 生成替换后的扩展查询
    4. 返回最多 max_expansions 个扩展查询

    Args:
        query: 原始查询
        max_expansions: 最大扩展数量

    Returns:
        扩展后的查询列表（不包含原始查询）
    """
    if not query or not query.strip():
        return []

    key_terms = _extract_key_terms(query)
    if not key_terms:
        return [query]

    expansions = set()
    used_synonyms = {}

    for term in key_terms:
        synonyms = _get_synonyms(term)
        if synonyms:
            used_synonyms[term] = synonyms[:3]

    # 生成替换版本（每次替换一个术语）
    for term, syns in used_synonyms.items():
        for syn in syns:
            # 简单替换
            expanded = re.sub(re.escape(term), syn, query, flags=re.IGNORECASE)
            if expanded != query and expanded not in expansions:
                expansions.add(expanded)
                if len(expansions) >= max_expansions:
                    break
        if len(expansions) >= max_expansions:
            break

    # 如果同义词不够，生成术语组合版本
    if len(expansions) < max_expansions and len(key_terms) >= 2:
        # 添加所有关键术语的组合查询
        combined = " ".join(key_terms[:5])
        if combined != query and combined not in expansions:
            expansions.add(combined)

    result = list(expansions)[:max_expansions]
    return result


# ============================================================
# 2. 查询分解
# ============================================================

def decompose_query(query: str, max_subqueries: int = 3) -> List[str]:
    """
    查询分解（Query Decomposition）

    将复杂问题拆分为多个子问题，每个子问题独立检索。

    识别模式：
    1. 并列结构："A 和 B"、"A 与 B"、"A、B、C"
    2. 递进结构："首先...然后...最后"
    3. 比较结构："A 和 B 的区别"、"A 相比 B"
    4. 多疑问词：连续的 "什么/如何/为什么"
    5. 英文并列："and", "or", "vs", "versus"

    Args:
        query: 原始查询
        max_subqueries: 最大子问题数量

    Returns:
        子查询列表
    """
    if not query or not query.strip():
        return []

    query = query.strip()
    subqueries = []

    # 模式 1: 中文并列（顿号分隔）
    dunhao_parts = re.split(r'[、]', query)
    if len(dunhao_parts) >= 2 and len(dunhao_parts) <= 5:
        # 检查是否是名词并列
        common_part = ""
        # 找公共后缀
        for i in range(len(dunhao_parts[0])):
            suffix = dunhao_parts[0][-i:] if i > 0 else ""
            if all(p.endswith(suffix) for p in dunhao_parts) and suffix:
                common_part = suffix

        if common_part:
            for part in dunhao_parts:
                base = part[:-len(common_part)] if common_part else part
                # 提取问题词
                q_word = ""
                for w in ["什么是", "如何", "怎么", "为什么", "怎样", "如何实现"]:
                    if w in query:
                        q_word = w
                        break

                sub_q = f"{q_word}{base}{common_part}" if q_word else f"{base}{common_part}"
                subqueries.append(sub_q.strip())

    # 模式 2: "和/与/及" 并列
    if not subqueries:
        he_pattern = r'(.+?)(?:和|与|及|以及)(.+)'
        match = re.match(he_pattern, query)
        if match and len(match.group(1)) > 1 and len(match.group(2)) > 1:
            part_a = match.group(1).strip()
            part_b = match.group(2).strip()

            # 判断是否是比较/区别类问题
            if any(w in query for w in ["区别", "对比", "比较", "差异", "哪个好", "优缺点"]):
                subqueries.append(part_a)
                subqueries.append(part_b)
                subqueries.append(f"{part_a} {part_b} 对比")
            else:
                # 普通并列，各自作为查询
                # 尝试提取共同的疑问词
                q_words = ["什么是", "如何", "怎么", "为什么", "怎样", "请问"]
                common_q = ""
                for w in q_words:
                    if part_a.startswith(w):
                        common_q = w
                        part_a = part_a[len(w):]
                        break

                subqueries.append(f"{common_q}{part_a}".strip() if common_q else part_a)
                subqueries.append(f"{common_q}{part_b}".strip() if common_q else part_b)

    # 模式 3: 英文并列 "and" / "vs" / "or"
    if not subqueries:
        en_pattern = r'(.+?)\s+(?:and|vs|versus|or)\s+(.+)'
        match = re.match(en_pattern, query, re.IGNORECASE)
        if match:
            part_a = match.group(1).strip()
            part_b = match.group(2).strip()
            if len(part_a) > 2 and len(part_b) > 2:
                subqueries.append(part_a)
                subqueries.append(part_b)

    # 模式 4: 多疑问词
    if not subqueries:
        q_markers = re.findall(
            r'(?:什么|如何|怎么|为什么|怎样|哪|多少|几)[^？。!?.]*[？。!?.]?',
            query
        )
        if len(q_markers) >= 2:
            for q in q_markers:
                q = q.strip().rstrip("？。!?.")
                if len(q) >= 3:
                    subqueries.append(q)

    # 去重和限制数量
    seen = set()
    unique_subs = []
    for q in subqueries:
        q = q.strip()
        if q and q not in seen and q != query:
            seen.add(q)
            unique_subs.append(q)

    return unique_subs[:max_subqueries]


# ============================================================
# 3. 多轮改写
# ============================================================

def rewrite_conversational(query: str,
                           history: List[Dict[str, str]]) -> List[str]:
    """
    多轮改写（Conversational Query Rewrite）

    结合对话历史改写当前查询，补全省略的指代。

    处理：
    1. 代词替换（他/她/它/这/那/这个/那个）
    2. 省略补全（"怎么做" -> "XXX怎么做"）
    3. 上下文主题继承

    Args:
        query: 当前查询
        history: 对话历史，每项包含 "role" 和 "content"

    Returns:
        改写后的查询列表（通常只有 1 个）
    """
    if not query or not query.strip():
        return []

    if not history:
        return [query]

    rewritten = query

    # 获取最近的用户问题
    last_user_query = ""
    last_assistant_answer = ""
    for msg in reversed(history):
        if msg.get("role") == "user" and not last_user_query:
            last_user_query = msg.get("content", "")
        elif msg.get("role") == "assistant" and not last_assistant_answer:
            last_assistant_answer = msg.get("content", "")
        if last_user_query and last_assistant_answer:
            break

    if not last_user_query:
        return [query]

    # 提取上一轮的主题
    prev_topics = _extract_key_terms(last_user_query)

    # 检测当前查询是否有指代性词语
    anaphoric_patterns = [
        r'^(它|他|她|这|那|这个|那个|这个东西|那个东西)',
        r'^(怎么做|怎么办|怎么弄|如何做|如何处理)',
        r'^然后呢|^接下来呢|^还有呢',
        r'^说的(什么|是啥)|^指的(什么|是啥)',
    ]

    has_anaphora = any(re.match(p, query) for p in anaphoric_patterns)

    if has_anaphora and prev_topics:
        # 将上一轮的主要主题加入查询
        main_topic = prev_topics[0]
        rewritten = f"{main_topic} {query}"

    # 检测"也"字句
    if "也" in query and prev_topics:
        main_topic = prev_topics[0]
        if main_topic not in rewritten:
            rewritten = f"{main_topic} {rewritten}"

    # 检测省略式问题（太短，且上一轮有明确主题）
    if len(query) < 6 and prev_topics and query not in prev_topics:
        main_topic = prev_topics[0]
        if main_topic not in rewritten:
            rewritten = f"{main_topic} {query}"

    if rewritten != query:
        return [rewritten.strip()]

    return [query]


# ============================================================
# 4. 假设性文档生成 (HyDE)
# ============================================================

def generate_hypothetical_documents(query: str,
                                    num_docs: int = 3,
                                    llm_fn: Optional[Callable[[str], str]] = None) -> List[str]:
    """
    假设性文档生成（Hypothetical Document Embeddings, HyDE）

    生成假设性回答文档，用假设文档做向量检索，提高召回率。

    原理：
    直接用问题做向量检索可能匹配度不高（问题 vs 回答的分布差异），
    先生成假设的回答文档，再用假设文档检索，更接近目标文档分布。

    实现：
    - 如果提供了 llm_fn，使用 LLM 生成
    - 否则使用模板 + 关键词扩展生成简单的假设文档

    Args:
        query: 查询
        num_docs: 生成文档数量
        llm_fn: LLM 生成函数（可选）

    Returns:
        假设性文档列表
    """
    if not query or not query.strip():
        return []

    if llm_fn:
        # 使用 LLM 生成
        hyde_docs = []
        for i in range(num_docs):
            prompt = f"请写一段关于「{query}」的详细说明文字，约 200 字左右，风格类似技术文档或百科条目。"
            try:
                doc = llm_fn(prompt)
                if doc and doc.strip():
                    hyde_docs.append(doc.strip())
            except Exception:
                pass
        if hyde_docs:
            return hyde_docs[:num_docs]

    # 降级：基于模板 + 关键词扩展生成
    key_terms = _extract_key_terms(query)
    synonyms = []
    for term in key_terms[:3]:
        syns = _get_synonyms(term)
        synonyms.extend(syns[:2])

    # 生成不同角度的假设文档
    templates = [
        f"{query}是一个重要的技术概念。{query}的核心原理涉及多个方面，"
        f"包括基本概念、实现方法、应用场景等。在实际应用中，{query}常用于"
        f"解决相关的技术问题，提高系统效率和可靠性。",

        f"关于{query}的详细说明：{query}的主要特点包括高性能、易用性和可扩展性。"
        f"在{('、'.join(synonyms[:3])) if synonyms else '相关领域'}中，"
        f"{query}扮演着重要角色。常见的实现方式有多种，各有优缺点。",

        f"{query}的最佳实践包括：首先需要理解基本原理，然后掌握核心技术，"
        f"最后通过实践不断优化。在{('、'.join(key_terms[:3]))}方面，"
        f"{query}提供了完整的解决方案，能够满足不同场景的需求。",
    ]

    return templates[:num_docs]


# ============================================================
# 查询改写主类
# ============================================================

class QueryRewriter:
    """
    查询改写器（主入口类）

    整合多种改写策略，支持配置化。
    """

    def __init__(self,
                 strategy: str = "expansion",
                 max_queries: int = 3,
                 llm_fn: Optional[Callable[[str], str]] = None):
        """
        Args:
            strategy: 默认改写策略
            max_queries: 最大改写查询数量
            llm_fn: LLM 生成函数（用于 HyDE 等高级功能）
        """
        self.strategy = strategy
        self.max_queries = max_queries
        self.llm_fn = llm_fn

    def rewrite(self,
                query: str,
                strategy: Optional[str] = None,
                history: Optional[List[Dict[str, str]]] = None,
                max_queries: Optional[int] = None) -> RewriteResult:
        """
        改写查询

        Args:
            query: 原始查询
            strategy: 改写策略（覆盖默认值）
            history: 对话历史（用于多轮改写）
            max_queries: 最大查询数量（覆盖默认值）

        Returns:
            改写结果
        """
        strat = strategy or self.strategy
        max_q = max_queries or self.max_queries

        if strat == RewriteStrategy.EXPANSION.value:
            queries = expand_query(query, max_expansions=max_q)
            metadata = {"method": "synonym_expansion", "synonym_count": len(queries)}

        elif strat == RewriteStrategy.DECOMPOSITION.value:
            queries = decompose_query(query, max_subqueries=max_q)
            metadata = {"method": "query_decomposition", "subquery_count": len(queries)}

        elif strat == RewriteStrategy.CONVERSATIONAL.value:
            queries = rewrite_conversational(query, history or [])
            metadata = {
                "method": "conversational_rewrite",
                "history_length": len(history or []),
                "rewritten": queries[0] if queries else "",
            }
            # 多轮改写通常只有 1 个结果
            if queries:
                queries = queries[:max_q]

        elif strat == RewriteStrategy.HYDE.value:
            queries = generate_hypothetical_documents(
                query, num_docs=max_q, llm_fn=self.llm_fn
            )
            metadata = {"method": "hyde", "doc_count": len(queries), "llm_enabled": self.llm_fn is not None}

        else:
            queries = [query]
            metadata = {"method": "none", "reason": f"unknown strategy: {strat}"}

        return RewriteResult(
            original_query=query,
            rewritten_queries=queries,
            strategy=strat,
            metadata=metadata,
        )

    def rewrite_all(self,
                    query: str,
                    history: Optional[List[Dict[str, str]]] = None) -> Dict[str, RewriteResult]:
        """
        使用所有策略改写（用于对比测试）

        Returns:
            各策略的改写结果字典
        """
        results = {}
        for strat in RewriteStrategy:
            try:
                result = self.rewrite(query, strategy=strat.value, history=history)
                results[strat.value] = result
            except Exception as e:
                results[strat.value] = RewriteResult(
                    original_query=query,
                    rewritten_queries=[],
                    strategy=strat.value,
                    metadata={"error": str(e)},
                )
        return results
