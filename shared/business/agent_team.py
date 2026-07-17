"""
专业Agent团队 - 云汐的智能体伙伴们
5个专业Agent：研究员/作家/分析师/创意师/执行官

每个Agent都有独特的专长和工作风格，
通过协作完成复杂任务。
"""

import re
import json
import time
import random
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

from .multi_agent import (
    BaseAgent, AgentTask, AgentResult, AgentSpecialty, TaskType,
)


# ==================== 研究员Agent ====================

class ResearchAgent(BaseAgent):
    """研究员Agent - 擅长信息搜集与调研"""
    
    name = "研究员·知微"
    description = "擅长信息搜集、资料调研、事实核查，能够快速整理出全面准确的背景信息。"
    specialty = AgentSpecialty.RESEARCH.value
    
    strengths = ["信息搜集", "资料整理", "事实核查", "背景调研"]
    limitations = ["不擅长创意创作", "不做主观判断"]
    working_style = "严谨细致，注重数据来源和事实依据"
    
    def execute(self, task: AgentTask, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        start_time = time.time()
        context = context or {}
        user_id = context.get("user_id", "default")
        
        try:
            query = task.description
            
            # 尝试从记忆和知识库获取信息
            findings = []
            sources = []
            
            # 1. 搜索长期记忆
            try:
                from .long_term_memory import get_long_term_memory
                ltm = get_long_term_memory()
                memories = ltm.search(user_id=user_id, query=query, limit=3)
                if memories:
                    for m in memories[:2]:
                        findings.append(f"（来自记忆）{m.title}：{m.content[:150]}")
                    sources.append("长期记忆")
            except Exception as e:
                # 长期记忆检索失败不影响研究流程，仅记录调试日志
                logger.debug("长期记忆检索失败: %s", e)
            
            # 2. 搜索知识库
            try:
                from .rag_knowledge import get_rag_knowledge_base
                rag = get_rag_knowledge_base()
                results = rag.search(query, limit=3)
                if results:
                    for r in results[:2]:
                        findings.append(f"（来自知识库）{r.chunk.text[:150]}")
                    sources.append("RAG知识库")
            except Exception as e:
                # 知识库检索失败不影响研究流程，仅记录调试日志
                logger.debug("RAG 知识库检索失败: %s", e)
            
            # 3. 如果没有外部信息，生成结构化研究框架
            if not findings:
                findings = self._generate_research_framework(query)
                sources.append("知识框架（待验证）")
            
            # 组织研究报告
            report = self._format_research_report(query, findings, sources)
            
            execution_time = time.time() - start_time
            return AgentResult(
                agent_name=self.name,
                success=True,
                output=report,
                data={
                    "findings_count": len(findings),
                    "sources": sources,
                    "findings": findings,
                },
                execution_time=execution_time,
                confidence=0.7 if sources else 0.5,
            )
            
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    def _generate_research_framework(self, query: str) -> List[str]:
        """生成研究框架（当没有数据时给出研究方向）"""
        frameworks = [
            f"关于「{query}」的研究可以从以下几个维度展开：",
            "1. 定义与内涵：明确核心概念和基本定义",
            "2. 背景与历史：了解发展历程和关键节点",
            "3. 现状与趋势：分析当前状况和未来走向",
            "4. 关键要素：识别影响因素和核心变量",
            "5. 相关案例：参考典型案例和实践经验",
            "6. 注意事项：明确风险点和需要注意的问题",
        ]
        return frameworks
    
    def _format_research_report(self, query: str, findings: List[str],
                                 sources: List[str]) -> str:
        """格式化研究报告"""
        report = f"📚 研究报告：{query}\n\n"
        report += "=" * 40 + "\n\n"
        
        report += "🔍 研究发现：\n\n"
        for i, finding in enumerate(findings, 1):
            report += f"{i}. {finding}\n\n"
        
        report += "=" * 40 + "\n"
        report += f"📋 信息来源：{', '.join(sources)}\n"
        report += f"📝 共 {len(findings)} 条发现\n"
        
        if "待验证" in str(sources):
            report += "⚠️ 注：部分内容为框架性建议，建议结合实际数据验证\n"
        
        return report


# ==================== 作家Agent ====================

class WritingAgent(BaseAgent):
    """作家Agent - 擅长文案创作与写作"""
    
    name = "作家·文思"
    description = "擅长各类文案创作，包括文章、邮件、报告、总结等，文笔流畅，风格多样。"
    specialty = AgentSpecialty.WRITING.value
    
    strengths = ["文案撰写", "内容创作", "文章润色", "结构优化"]
    limitations = ["不擅长事实核查", "创意可能需要调整"]
    working_style = "文笔流畅，善于根据不同场景调整风格"
    
    def execute(self, task: AgentTask, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        start_time = time.time()
        
        try:
            query = task.description
            
            # 判断写作类型
            writing_type = self._detect_writing_type(query)
            content = self._generate_content(query, writing_type)
            
            execution_time = time.time() - start_time
            return AgentResult(
                agent_name=self.name,
                success=True,
                output=content,
                data={
                    "writing_type": writing_type,
                    "word_count": len(content),
                },
                execution_time=execution_time,
                confidence=0.65,
            )
            
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    def _detect_writing_type(self, query: str) -> str:
        """判断写作类型"""
        q = query.lower()
        
        if "邮件" in q or "email" in q or "写信" in q:
            return "email"
        elif "报告" in q or "汇报" in q:
            return "report"
        elif "总结" in q or "归纳" in q:
            return "summary"
        elif "文章" in q or "作文" in q or "写一篇" in q:
            return "article"
        elif "方案" in q or "策划" in q:
            return "proposal"
        else:
            return "general"
    
    def _generate_content(self, query: str, writing_type: str) -> str:
        """生成写作内容（模板化生成）"""
        # 提取主题
        topic = self._extract_topic(query)
        
        templates = {
            "email": self._email_template,
            "report": self._report_template,
            "summary": self._summary_template,
            "article": self._article_template,
            "proposal": self._proposal_template,
            "general": self._general_template,
        }
        
        template_func = templates.get(writing_type, self._general_template)
        return template_func(topic, query)
    
    def _extract_topic(self, query: str) -> str:
        """提取写作主题"""
        # 简单提取：去掉常见动词
        patterns_to_remove = [
            r'帮我写', r'写一个', r'写一篇', r'撰写', r'创作',
            r'关于', r'有关', r'的邮件', r'的报告', r'的总结',
            r'的文章', r'的方案',
        ]
        topic = query
        for p in patterns_to_remove:
            topic = re.sub(p, '', topic)
        topic = topic.strip(' ，。、')
        return topic if topic else "相关主题"
    
    def _email_template(self, topic: str, query: str) -> str:
        return f"""📧 邮件：关于{topic}

尊敬的收件人：

您好！

关于{topic}，我想和您沟通一下。

主要内容如下：
1. 背景说明：{topic}的相关情况
2. 具体事项：需要沟通和确认的内容
3. 期望结果：希望达成的目标

如有任何问题，请随时回复。期待您的反馈！

此致
敬礼

—— 云汐
{time.strftime('%Y年%m月%d日')}

---
💡 提示：请根据实际情况调整收件人和具体内容"""
    
    def _report_template(self, topic: str, query: str) -> str:
        return f"""📊 报告：{topic}分析报告

一、报告概述
本报告针对{topic}进行全面分析，旨在提供清晰的现状判断和可行建议。

二、背景介绍
{topic}是当前关注的重要议题，涉及多方面因素。

三、现状分析
1. 整体情况：当前处于发展阶段
2. 关键数据：各项指标表现良好
3. 存在问题：部分领域有待改进

四、趋势预测
- 短期：保持稳定发展态势
- 中期：有望实现突破性进展
- 长期：前景广阔

五、建议措施
1. 加强基础建设
2. 优化资源配置
3. 推动创新发展

六、总结
综上所述，{topic}机遇与挑战并存，建议积极应对。

---
💡 提示：请补充实际数据和具体分析"""
    
    def _summary_template(self, topic: str, query: str) -> str:
        return f"""📝 总结：{topic}

一、核心要点
• 关键信息一：{topic}的核心内容
• 关键信息二：重要发现和结论
• 关键信息三：下一步行动建议

二、详细回顾
1. 背景：{topic}的来龙去脉
2. 过程：发展历程和关键节点
3. 结果：取得的成果和经验

三、经验教训
✓ 做得好的地方：需要继续保持
⚠ 需要改进的地方：持续优化

四、下一步计划
- 近期行动：立即着手的事项
- 中期目标：未来1-3个月的规划
- 长期愿景：长远发展方向

---
💡 提示：请根据实际情况填充具体内容"""
    
    def _article_template(self, topic: str, query: str) -> str:
        return f"""📄 文章：浅谈{topic}

引言
{topic}是一个值得深入探讨的话题。在当今时代，它的重要性日益凸显。

一、什么是{topic}
{topic}，简而言之，就是与我们生活息息相关的一个概念。它包含丰富的内涵，涉及多个层面。

二、为什么重要
{topic}的重要性体现在以下几个方面：
1. 对个人的影响
2. 对社会的价值
3. 对未来的意义

三、如何实践
要真正理解和应用{topic}，我们可以从以下几点入手：
• 学习基础知识
• 积累实践经验
• 持续反思总结

结语
{topic}是一个不断发展的领域。希望本文能给你带来一些启发。

---
💡 提示：可根据需要扩展各部分内容"""
    
    def _proposal_template(self, topic: str, query: str) -> str:
        return f"""💡 方案：{topic}策划方案

一、项目背景
当前{topic}面临新的机遇和挑战，需要系统性的解决方案。

二、目标设定
🎯 总体目标：实现{topic}的优化升级
📈 具体指标：
   - 效率提升30%
   - 成本降低20%
   - 用户满意度提升

三、实施方案
阶段一：调研准备（第1-2周）
• 现状调研
• 需求分析
• 方案设计

阶段二：落地执行（第3-6周）
• 核心功能开发
• 测试验证
• 试运行

阶段三：优化完善（第7-8周）
• 反馈收集
• 迭代优化
• 正式上线

四、资源需求
- 人力：核心团队3-5人
- 时间：约2个月
- 预算：根据实际情况确定

五、风险与对策
⚠️ 风险一：进度延期 → 对策：设置里程碑节点
⚠️ 风险二：资源不足 → 对策：优先保障核心需求

---
💡 提示：请根据实际情况调整方案细节"""
    
    def _general_template(self, topic: str, query: str) -> str:
        return f"""✍️ 关于{topic}

关于{topic}，有以下几点想法：

1. 整体概述
{topic}是一个有意思的话题。它涉及到我们生活的方方面面。

2. 深入思考
从不同角度来看，{topic}有多重含义和价值。

3. 实践建议
如果想要更好地理解{topic}，可以从以下几个方面入手：
• 多阅读相关资料
• 与他人交流讨论
• 在实践中体会

希望以上内容对你有所帮助！

---
💡 提示：这是基础版本，可以根据需要调整风格和内容"""


# ==================== 分析师Agent ====================

class AnalysisAgent(BaseAgent):
    """分析师Agent - 擅长问题分析与诊断"""
    
    name = "分析师·明鉴"
    description = "擅长问题分析、原因诊断、数据解读，能够从复杂现象中找出关键问题。"
    specialty = AgentSpecialty.ANALYSIS.value
    
    strengths = ["问题诊断", "数据分析", "原因分析", "趋势判断"]
    limitations = ["不擅长创意发散", "需要数据支撑"]
    working_style = "逻辑严谨，层层递进，注重因果关系"
    
    def execute(self, task: AgentTask, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        start_time = time.time()
        
        try:
            query = task.description
            
            # 进行多维度分析
            analysis = self._analyze_problem(query)
            
            execution_time = time.time() - start_time
            return AgentResult(
                agent_name=self.name,
                success=True,
                output=analysis,
                data={"analysis_dimensions": 6},
                execution_time=execution_time,
                confidence=0.6,
            )
            
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    def _analyze_problem(self, query: str) -> str:
        """进行多维度问题分析"""
        # 提取核心问题
        core_issue = self._extract_core_issue(query)
        
        report = f"🔍 分析报告：{core_issue}\n\n"
        report += "=" * 40 + "\n\n"
        
        # 1. 问题定义
        report += "📌 一、问题定义\n"
        report += f"核心问题：{core_issue}\n"
        report += f"问题性质：{self._classify_problem(query)}\n\n"
        
        # 2. 可能原因（鱼骨图式分析）
        report += "🔗 二、可能原因分析\n"
        causes = self._generate_causes(query)
        for category, cause_list in causes.items():
            report += f"\n【{category}】\n"
            for cause in cause_list:
                report += f"  • {cause}\n"
        report += "\n"
        
        # 3. 影响评估
        report += "📊 三、影响评估\n"
        impacts = self._assess_impact(query)
        for impact in impacts:
            report += f"  • {impact}\n"
        report += "\n"
        
        # 4. 趋势判断
        report += "📈 四、趋势判断\n"
        report += f"  • 短期趋势：{self._short_term_trend(query)}\n"
        report += f"  • 中期趋势：{self._mid_term_trend(query)}\n"
        report += f"  • 长期趋势：{self._long_term_trend(query)}\n\n"
        
        # 5. 关键指标
        report += "🎯 五、关键监控指标\n"
        metrics = self._key_metrics(query)
        for metric in metrics:
            report += f"  • {metric}\n"
        report += "\n"
        
        # 6. 建议方向
        report += "💡 六、建议方向\n"
        suggestions = self._generate_suggestions(query)
        for i, sug in enumerate(suggestions, 1):
            report += f"  {i}. {sug}\n"
        
        report += "\n" + "=" * 40 + "\n"
        report += "⚠️ 注：以上分析基于通用框架，具体结论需结合实际数据验证\n"
        
        return report
    
    def _extract_core_issue(self, query: str) -> str:
        """提取核心问题"""
        # 简单提取
        issue = re.sub(r'(分析|为什么|怎么回事|原因|问题是|诊断)', '', query)
        issue = issue.strip(' ？?。，')
        return issue if issue else query[:30]
    
    def _classify_problem(self, query: str) -> str:
        """问题分类"""
        q = query.lower()
        if "效率" in q or "慢" in q or "速度" in q:
            return "效率类问题"
        elif "错误" in q or "bug" in q or "异常" in q or "失败" in q:
            return "故障类问题"
        elif "下降" in q or "减少" in q or "低" in q:
            return "衰退类问题"
        elif "增长" in q or "提升" in q or "提高" in q:
            return "发展类问题"
        else:
            return "综合类问题"
    
    def _generate_causes(self, query: str) -> Dict[str, List[str]]:
        """生成可能原因（鱼骨图式）"""
        return {
            "人的因素": [
                "人员能力或经验不足",
                "工作态度或积极性问题",
                "人员配置不合理",
                "沟通协作不畅",
            ],
            "流程因素": [
                "流程设计不合理",
                "关键环节缺失",
                "审批层级过多",
                "缺乏标准化",
            ],
            "技术因素": [
                "技术方案选择不当",
                "系统性能瓶颈",
                "技术债务积累",
                "工具选型问题",
            ],
            "环境因素": [
                "外部环境变化",
                "资源供给不足",
                "政策法规影响",
                "市场竞争加剧",
            ],
            "管理因素": [
                "目标设定不清晰",
                "缺乏有效监控",
                "激励机制不足",
                "决策效率低下",
            ],
        }
    
    def _assess_impact(self, query: str) -> List[str]:
        """影响评估"""
        return [
            "对业务效率的影响：可能导致效率下降10-30%",
            "对用户体验的影响：用户满意度可能降低",
            "对成本控制的影响：运营成本可能上升",
            "对团队士气的影响：团队信心可能受挫",
            "对长期发展的影响：如不解决可能形成惯性问题",
        ]
    
    def _short_term_trend(self, query: str) -> str:
        return "如果不采取措施，问题可能持续存在或小幅恶化"
    
    def _mid_term_trend(self, query: str) -> str:
        return "问题影响范围可能扩大，需要引起重视"
    
    def _long_term_trend(self, query: str) -> str:
        return "如能及时解决，反而可能成为改进和提升的契机"
    
    def _key_metrics(self, query: str) -> List[str]:
        """关键监控指标"""
        return [
            "问题发生频率：每周/每月发生次数",
            "影响范围：涉及的用户/业务比例",
            "恢复时间：从发现到解决的时长",
            "趋势变化：环比/同比变化率",
            "关联指标：相关核心KPI的表现",
        ]
    
    def _generate_suggestions(self, query: str) -> List[str]:
        """生成建议"""
        return [
            "深入调研：收集更多数据和案例，准确界定问题",
            "根因分析：透过现象看本质，找到根本原因",
            "试点验证：小范围测试解决方案，降低风险",
            "分步推进：制定清晰的实施路线图",
            "持续监控：建立反馈机制，及时调整策略",
        ]


# ==================== 创意师Agent ====================

class CreativeAgent(BaseAgent):
    """创意师Agent - 擅长头脑风暴与创意构思"""
    
    name = "创意师·灵感"
    description = "擅长头脑风暴、创意构思、方案策划，思维活跃，想法天马行空。"
    specialty = AgentSpecialty.CREATIVE.value
    
    strengths = ["创意发散", "头脑风暴", "方案策划", "跨界联想"]
    limitations = ["不擅长细节执行", "想法可能不切实际"]
    working_style = "思维活跃，善于联想，总能想出意想不到的点子"
    
    def execute(self, task: AgentTask, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        start_time = time.time()
        
        try:
            query = task.description
            
            # 生成创意方案
            ideas = self._generate_ideas(query)
            
            execution_time = time.time() - start_time
            return AgentResult(
                agent_name=self.name,
                success=True,
                output=ideas,
                data={"ideas_count": 10},
                execution_time=execution_time,
                confidence=0.55,  # 创意类置信度稍低
            )
            
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    def _generate_ideas(self, query: str) -> str:
        """生成创意方案"""
        topic = re.sub(r'(创意|方案|想法|点子|构思|策划|头脑风暴)', '', query).strip(' ？?。，')
        
        result = f"💡 创意风暴：{topic}\n\n"
        result += "=" * 40 + "\n\n"
        result += "🎯 主题：" + (topic if topic else query[:30]) + "\n\n"
        
        # 10个创意方向
        idea_categories = [
            ("🌟 简约极致风", "少即是多，聚焦核心体验，去除一切冗余"),
            ("🎮 游戏化思维", "引入游戏机制，让过程变得有趣有成就感"),
            ("🤝 社交互动", "强化人与人的连接，创造社群归属感"),
            ("🔧 实用主义", "解决真实痛点，功能至上，好用才是硬道理"),
            ("🎨 艺术美学", "注重视觉和情感体验，打造艺术品级品质"),
            ("⚡ 效率至上", "快、准、狠，用最短路径达成目标"),
            ("🌱 成长体系", "设计进阶路径，让用户伴随产品一起成长"),
            ("🎭 个性化定制", "千人千面，每个人都有专属体验"),
            ("🔮 未来科技", "引入前沿技术概念，打造科技感和未来感"),
            ("💝 情感温度", "注入人文关怀，让产品有温度有灵魂"),
        ]
        
        result += "💭 十大创意方向：\n\n"
        for i, (name, desc) in enumerate(idea_categories, 1):
            result += f"{i:2d}. {name}\n"
            result += f"    → {desc}\n\n"
        
        # 跨界联想
        result += "🔄 跨界灵感来源：\n\n"
        cross_domains = [
            "从自然界汲取灵感：生物进化、生态系统、物理规律",
            "从艺术领域借鉴：绘画、音乐、文学、建筑",
            "从其他行业移植：游戏设计、餐饮服务、航空体验",
            "从历史中寻找：传统文化、经典案例、古人智慧",
        ]
        for domain in cross_domains:
            result += f"  • {domain}\n"
        
        result += "\n" + "=" * 40 + "\n"
        result += "💡 创意小贴士：\n"
        result += "  1. 好创意往往是＂旧元素的新组合＂\n"
        result += "  2. 先发散再收敛，数量优先于质量\n"
        result += "  3. 最疯狂的想法往往藏着最好的种子\n"
        result += "  4. 结合实际场景筛选可落地的方向\n"
        
        return result


# ==================== 执行官Agent ====================

class ExecutionAgent(BaseAgent):
    """执行官Agent - 擅长任务执行与工具调用"""
    
    name = "执行官·力行"
    description = "擅长任务执行、工具调用、操作处理，行动迅速，执行力强。"
    specialty = AgentSpecialty.EXECUTION.value
    
    strengths = ["任务执行", "工具调用", "操作处理", "效率优先"]
    limitations = ["不擅长复杂思考", "可能忽略细节"]
    working_style = "行动迅速，结果导向，高效完成任务"
    
    def execute(self, task: AgentTask, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        start_time = time.time()
        context = context or {}
        
        try:
            query = task.description
            
            # 检测需要的操作类型
            action_type = self._detect_action_type(query)
            
            # 尝试调用工具执行
            output = self._execute_action(query, action_type, context)
            
            execution_time = time.time() - start_time
            return AgentResult(
                agent_name=self.name,
                success=True,
                output=output,
                data={"action_type": action_type},
                execution_time=execution_time,
                confidence=0.7,
            )
            
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    def _detect_action_type(self, query: str) -> str:
        """检测操作类型"""
        q = query.lower()
        
        calc_patterns = [r'计算', r'等于多少', r'[0-9]+\s*[+\-*/]']
        if any(re.search(p, q) for p in calc_patterns):
            return "calculation"
        
        time_patterns = [r'几点了', r'现在时间', r'今天几号', r'星期几']
        if any(re.search(p, q) for p in time_patterns):
            return "time_check"
        
        memory_patterns = [r'保存.*记忆', r'记住', r'记录下来']
        if any(re.search(p, q) for p in memory_patterns):
            return "save_memory"
        
        search_patterns = [r'搜索', r'查找', r'查询']
        if any(re.search(p, q) for p in search_patterns):
            return "search"
        
        return "general"
    
    def _execute_action(self, query: str, action_type: str,
                        context: Dict[str, Any]) -> str:
        """执行具体操作"""
        user_id = context.get("user_id", "default")
        
        try:
            from .tool_system import get_tool_registry
            from .builtin_tools import _ensure_registered
            _ensure_registered()
            registry = get_tool_registry()
        except Exception:
            return f"任务收到：{query}\n\n正在处理中...（工具系统暂不可用，将以人工方式执行）"
        
        result_text = f"⚡ 执行任务：{query}\n\n"
        result_text += "=" * 40 + "\n\n"
        
        if action_type == "calculation":
            # 提取表达式并计算
            expr_match = re.search(r'[\d.]+\s*[+\-*/]\s*[\d.]+(?:\s*[+\-*/]\s*[\d.]+)*', query)
            if expr_match:
                expr = expr_match.group(0)
                result = registry.call_tool("calculator", {"expression": expr})
                if result.success:
                    result_text += f"✅ 计算完成\n"
                    result_text += f"  表达式：{expr}\n"
                    result_text += f"  结果：{result.data['result']}\n"
                else:
                    result_text += f"❌ 计算失败：{result.error}\n"
            else:
                result_text += "⚠️ 未能识别计算表达式\n"
        
        elif action_type == "time_check":
            result = registry.call_tool("get_current_time", {"format": "full"})
            if result.success:
                result_text += f"✅ 查询完成\n"
                result_text += f"  当前时间：{result.output}\n"
            else:
                result_text += f"❌ 查询失败：{result.error}\n"
        
        elif action_type == "save_memory":
            # 提取要保存的内容
            content = re.sub(r'^(记住|保存|记录|帮我记)', '', query).strip()
            if content:
                result = registry.call_tool(
                    "save_memory",
                    {"content": content, "memory_type": "fact", "title": content[:30]},
                    context=context,
                )
                if result.success:
                    result_text += f"✅ 已保存到记忆\n"
                    result_text += f"  内容：{content[:50]}...\n"
                else:
                    result_text += f"❌ 保存失败：{result.error}\n"
            else:
                result_text += "⚠️ 未能识别要保存的内容\n"
        
        else:
            result_text += f"📋 任务类型：通用执行\n"
            result_text += f"任务描述：{query}\n\n"
            result_text += "执行步骤：\n"
            result_text += "  1. 理解任务需求\n"
            result_text += "  2. 制定执行计划\n"
            result_text += "  3. 逐步推进落地\n"
            result_text += "  4. 检查结果质量\n\n"
            result_text += "✅ 任务框架已就绪，具体执行可根据实际情况展开\n"
        
        result_text += "\n" + "=" * 40 + "\n"
        result_text += f"⏱️ 执行状态：完成\n"
        
        return result_text


# ==================== 团队注册 ====================

def register_agent_team():
    """注册完整的Agent团队"""
    from .multi_agent import get_agent_team
    
    team = get_agent_team()
    
    agents = [
        ResearchAgent(),
        WritingAgent(),
        AnalysisAgent(),
        CreativeAgent(),
        ExecutionAgent(),
    ]
    
    registered = 0
    for agent in agents:
        if team.register_agent(agent):
            registered += 1
    
    return registered


# 自动注册
_team_registered = False


def _ensure_team_registered():
    """确保团队已注册"""
    global _team_registered
    if not _team_registered:
        _team_registered = register_agent_team() > 0
    return _team_registered
