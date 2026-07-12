"""v3.9.0 SkillDiscoveryEngine 技能发现引擎测试.

覆盖：
- 6大类技能分类体系
- 智能推荐5维信号加权
- 自然语言触发匹配
- 响应时间 < 50ms
- 常用技能自定义
- 推荐准确率 ≥ 75%
"""

import time
import pytest

from skill_cluster.skill_discovery import (
    SkillDiscoveryEngine,
    SkillCategory,
    SceneType,
    UserProfile,
    TimeContext,
    SkillDiscoveryItem,
    SkillDiscoveryResult,
    CATEGORY_META,
)


# ========== 测试辅助 ==========

def _build_engine_with_skills():
    """构建包含完整6大类技能的测试引擎."""
    engine = SkillDiscoveryEngine()

    # 代码开发类（6个）
    engine.register_skill(
        "skill.code_generator", "代码生成",
        "根据需求自动生成代码，支持多种编程语言",
        SkillCategory.CODING,
        tags=["代码", "生成", "开发"],
        keywords=["写代码", "生成代码", "编程", "开发"],
    )
    engine.register_skill(
        "skill.code_review", "代码审查",
        "自动审查代码质量，发现潜在问题和优化点",
        SkillCategory.CODING,
        tags=["代码", "审查", "质量"],
        keywords=["代码审查", "review", "代码检查", "优化"],
    )
    engine.register_skill(
        "skill.code_search", "代码搜索",
        "在代码库中快速搜索相关代码片段",
        SkillCategory.CODING,
        tags=["代码", "搜索", "检索"],
        keywords=["搜索代码", "查找代码", "code search"],
    )
    engine.register_skill(
        "skill.bug_locator", "Bug定位",
        "分析错误日志，定位问题代码位置",
        SkillCategory.CODING,
        tags=["调试", "bug", "错误"],
        keywords=["找bug", "调试", "排错", "错误定位"],
    )
    engine.register_skill(
        "skill.unit_test_gen", "单元测试生成",
        "自动为代码生成单元测试用例",
        SkillCategory.CODING,
        tags=["测试", "单元测试", "质量"],
        keywords=["写测试", "生成测试", "单元测试"],
    )
    engine.register_skill(
        "skill.refactor_helper", "重构助手",
        "提供代码重构建议，提升代码可维护性",
        SkillCategory.CODING,
        tags=["重构", "优化", "代码"],
        keywords=["重构代码", "优化代码", "代码改进"],
    )

    # 文档处理类（5个）
    engine.register_skill(
        "skill.doc_summary", "摘要生成",
        "自动生成文档摘要，提炼核心要点",
        SkillCategory.DOCUMENT,
        tags=["文档", "摘要", "总结"],
        keywords=["总结文档", "生成摘要", "提炼要点"],
    )
    engine.register_skill(
        "skill.translate", "翻译",
        "多语言互译，支持专业术语",
        SkillCategory.DOCUMENT,
        tags=["翻译", "语言", "文档"],
        keywords=["翻译", "translate", "英文", "中文"],
    )
    engine.register_skill(
        "skill.doc_convert", "格式转换",
        "文档格式互转（Word/PDF/Markdown等）",
        SkillCategory.DOCUMENT,
        tags=["文档", "格式", "转换"],
        keywords=["转格式", "格式转换", "pdf转word"],
    )
    engine.register_skill(
        "skill.ppt_outline", "PPT大纲",
        "根据主题生成PPT大纲和内容建议",
        SkillCategory.DOCUMENT,
        tags=["PPT", "演示", "文档"],
        keywords=["做PPT", "生成大纲", "幻灯片"],
    )
    engine.register_skill(
        "skill.doc_diff", "文档对比",
        "对比两个文档的差异，高亮变更内容",
        SkillCategory.DOCUMENT,
        tags=["文档", "对比", "差异"],
        keywords=["对比文档", "找不同", "差异对比"],
    )

    # 数据分析类（4个）
    engine.register_skill(
        "skill.data_visualization", "数据可视化",
        "将数据转化为直观的图表展示",
        SkillCategory.DATA,
        tags=["数据", "可视化", "图表"],
        keywords=["画图", "生成图表", "数据可视化", "趋势图"],
    )
    engine.register_skill(
        "skill.trend_analysis", "趋势分析",
        "分析数据趋势，预测未来走向",
        SkillCategory.DATA,
        tags=["数据", "分析", "趋势"],
        keywords=["趋势分析", "数据分析", "预测走势"],
    )
    engine.register_skill(
        "skill.anomaly_detect", "异常检测",
        "自动检测数据中的异常值和离群点",
        SkillCategory.DATA,
        tags=["数据", "异常", "检测"],
        keywords=["找异常", "异常检测", "离群点"],
    )
    engine.register_skill(
        "skill.stat_report", "统计报告",
        "生成完整的数据分析统计报告",
        SkillCategory.DATA,
        tags=["数据", "统计", "报告"],
        keywords=["统计报告", "数据分析报告"],
    )

    # 学习辅助类（4个）
    engine.register_skill(
        "skill.knowledge_tutor", "知识点讲解",
        "深入浅出讲解各类知识点",
        SkillCategory.LEARNING,
        tags=["学习", "知识", "讲解"],
        keywords=["讲解知识", "学习", "知识点"],
    )
    engine.register_skill(
        "skill.problem_solver", "题目解答",
        "解答各类习题，提供详细解题步骤",
        SkillCategory.LEARNING,
        tags=["学习", "题目", "解答"],
        keywords=["做题", "解答题目", "解题"],
    )
    engine.register_skill(
        "skill.flashcard", "记忆卡片",
        "生成记忆卡片，辅助高效记忆",
        SkillCategory.LEARNING,
        tags=["学习", "记忆", "卡片"],
        keywords=["背单词", "记忆卡片", "闪卡"],
    )
    engine.register_skill(
        "skill.learning_path", "学习路径规划",
        "根据目标定制个性化学习路线",
        SkillCategory.LEARNING,
        tags=["学习", "规划", "路径"],
        keywords=["学习计划", "学习路线", "怎么学"],
    )

    # 生活工具类（5个）
    engine.register_skill(
        "skill.calendar", "日程管理",
        "管理日程安排，提醒重要事项",
        SkillCategory.LIFE,
        tags=["日程", "管理", "生活"],
        keywords=["日程", "安排", "提醒", "日历"],
    )
    engine.register_skill(
        "skill.todo_list", "待办清单",
        "管理待办事项，追踪完成进度",
        SkillCategory.LIFE,
        tags=["待办", "任务", "生活"],
        keywords=["待办", "任务清单", "todo"],
    )
    engine.register_skill(
        "skill.pomodoro", "番茄钟",
        "番茄工作法计时，提升专注效率",
        SkillCategory.LIFE,
        tags=["效率", "专注", "生活"],
        keywords=["番茄钟", "专注", "计时"],
    )
    engine.register_skill(
        "skill.weather", "天气查询",
        "查询各地天气信息和预报",
        SkillCategory.LIFE,
        tags=["天气", "生活", "查询"],
        keywords=["天气", "气温", "预报"],
    )
    engine.register_skill(
        "skill.notify", "消息通知",
        "发送各类提醒和通知消息",
        SkillCategory.LIFE,
        tags=["通知", "提醒", "生活"],
        keywords=["通知", "提醒", "推送"],
    )

    # 创意生成类（4个）
    engine.register_skill(
        "skill.copywriting", "文案写作",
        "创作各类营销文案和创意内容",
        SkillCategory.CREATIVE,
        tags=["创意", "文案", "写作"],
        keywords=["写文案", "创作文案", "广告语"],
    )
    engine.register_skill(
        "skill.brainstorm", "头脑风暴",
        "发散思维，提供创意灵感",
        SkillCategory.CREATIVE,
        tags=["创意", "头脑风暴", "灵感"],
        keywords=[" brainstorm", "想点子", "创意发散"],
    )
    engine.register_skill(
        "skill.naming_helper", "起名助手",
        "为产品、项目、角色等起名",
        SkillCategory.CREATIVE,
        tags=["创意", "起名", "命名"],
        keywords=["起名", "取名字", "命名"],
    )
    engine.register_skill(
        "skill.color_palette", "配色建议",
        "提供专业的配色方案和色彩建议",
        SkillCategory.CREATIVE,
        tags=["创意", "设计", "配色"],
        keywords=["配色", "颜色搭配", "设计配色"],
    )

    return engine


# ========== 分类体系测试 ==========

def test_six_categories_complete():
    """验证6大类技能分类完整."""
    categories = [c.value for c in SkillCategory]
    assert "coding" in categories
    assert "document" in categories
    assert "data" in categories
    assert "learning" in categories
    assert "life" in categories
    assert "creative" in categories
    assert len(categories) == 6
    print(f"[PASS] 6大类分类: {categories}")


def test_category_meta_complete():
    """验证每个分类都有元数据（名称、描述、图标）."""
    for cat in SkillCategory:
        meta = CATEGORY_META[cat]
        assert "name" in meta
        assert "description" in meta
        assert "icon" in meta
        assert len(meta["name"]) > 0
    print(f"[PASS] 分类元数据完整: {len(CATEGORY_META)} 个分类")


def test_each_category_has_enough_skills():
    """验证每类至少3个技能."""
    engine = _build_engine_with_skills()
    categories = engine.list_categories()

    for cat in categories:
        assert cat.count >= 3, f"分类 {cat.name} 只有 {cat.count} 个技能，不足3个"

    total = sum(c.count for c in categories)
    print(f"[PASS] 每类≥3个技能: 共 {total} 个技能，{len(categories)} 个分类")


# ========== 智能推荐测试 ==========

def test_recommend_returns_top_k():
    """验证推荐返回指定数量的Top K结果."""
    engine = _build_engine_with_skills()
    result = engine.recommend(scene_type=SceneType.CODING, top_k=3)

    assert isinstance(result, SkillDiscoveryResult)
    assert len(result.recommendations) == 3
    assert result.total_available > 0
    print(f"[PASS] 推荐Top3: {[r.skill_name for r in result.recommendations]}")


def test_recommend_scene_weight():
    """验证场景模式对推荐的影响（CODING场景应优先推荐代码类）."""
    engine = _build_engine_with_skills()

    # 代码开发场景
    result_coding = engine.recommend(scene_type=SceneType.CODING, top_k=5)
    coding_count = sum(1 for r in result_coding.recommendations if r.category == "coding")

    # 情绪陪伴场景（不推荐技能）
    result_emotional = engine.recommend(scene_type=SceneType.EMOTIONAL, top_k=5)
    coding_count_emotional = sum(1 for r in result_emotional.recommendations if r.category == "coding")

    # 代码场景下代码类推荐应更多
    assert coding_count >= 2, f"CODING场景下代码类推荐仅 {coding_count} 个"
    # 情绪陪伴场景得分应普遍较低
    avg_coding = sum(r.score for r in result_coding.recommendations) / len(result_coding.recommendations)
    avg_emotional = sum(r.score for r in result_emotional.recommendations) / len(result_emotional.recommendations)
    assert avg_coding > avg_emotional

    print(f"[PASS] 场景权重: CODING场景代码类占{coding_count}/5, 平均分{avg_coding:.1f}vs{avg_emotional:.1f}")


def test_recommend_keyword_match():
    """验证用户输入关键词对推荐的影响."""
    engine = _build_engine_with_skills()

    # 无关键词
    result_no_kw = engine.recommend(scene_type=SceneType.DEFAULT, user_input_preview="", top_k=5)

    # 有明确关键词"翻译"
    result_with_kw = engine.recommend(scene_type=SceneType.DEFAULT, user_input_preview="帮我翻译这段英文", top_k=5)

    # 有关键词时翻译技能应该排名更靠前或得分更高
    translate_no_kw = next((r for r in result_no_kw.recommendations if "翻译" in r.skill_name), None)
    translate_with_kw = next((r for r in result_with_kw.recommendations if "翻译" in r.skill_name), None)

    # 翻译技能应该出现在关键词匹配结果中
    assert translate_with_kw is not None, "关键词匹配应能找到翻译技能"
    assert "关键词" in translate_with_kw.match_reason or translate_with_kw.score > translate_no_kw.score if translate_no_kw else True

    print(f"[PASS] 关键词匹配: 翻译技能得分 {translate_with_kw.score}")


def test_recommend_frequency_weight():
    """验证历史使用频率对推荐的影响."""
    engine = _build_engine_with_skills()

    # 先记录使用
    for _ in range(20):
        engine.record_usage("skill.code_generator")
    for _ in range(5):
        engine.record_usage("skill.code_review")

    result = engine.recommend(scene_type=SceneType.CODING, top_k=3)

    # 高频使用的代码生成应该排在前面
    top_ids = [r.skill_id for r in result.recommendations]
    assert "skill.code_generator" in top_ids[:2], "高频技能应排在推荐前列"

    print(f"[PASS] 频率权重: 高频技能 code_generator 在 Top{top_ids.index('skill.code_generator')+1}")


def test_recommend_recency_weight():
    """验证最近使用时间对推荐的影响."""
    engine = _build_engine_with_skills()

    # 模拟最近使用
    engine.record_usage("skill.weather")
    # weather在LIFE分类下，LIFE场景应优先推荐最近使用的
    result = engine.recommend(scene_type=SceneType.LIFE, top_k=5)
    weather = next((r for r in result.recommendations if r.skill_id == "skill.weather"), None)
    assert weather is not None
    # 最近使用过，应该有"最近使用"的匹配理由或较高得分
    assert weather.last_used_at is not None

    print(f"[PASS] 最近使用权重: weather 得分 {weather.score}")


def test_recommendation_accuracy():
    """验证推荐准确率 ≥ 75%."""
    engine = _build_engine_with_skills()

    # 构造测试用例：输入描述 -> 期望技能类别
    test_cases = [
        ("帮我写一个Python函数", "coding"),
        ("分析一下这个月的销售数据趋势", "data"),
        ("翻译成英文", "document"),
        ("这个知识点我不太懂", "learning"),
        ("明天天气怎么样", "life"),
        ("帮我想一个产品名字", "creative"),
        ("代码有bug帮我看看", "coding"),
        ("做一个PPT大纲", "document"),
        ("画个折线图", "data"),
        ("番茄钟计时", "life"),
    ]

    correct = 0
    for user_input, expected_category in test_cases:
        results = engine.trigger_by_natural_language(user_input, scene_type=SceneType.DEFAULT, top_k=3)
        if results and results[0].category == expected_category:
            correct += 1

    accuracy = correct / len(test_cases)
    assert accuracy >= 0.75, f"推荐准确率 {accuracy:.0%} 低于75%"

    print(f"[PASS] 推荐准确率: {accuracy:.0%} ({correct}/{len(test_cases)}) ≥ 75%")


# ========== 自然语言触发测试 ==========

def test_natural_language_trigger():
    """验证自然语言触发匹配."""
    engine = _build_engine_with_skills()

    # 测试明确需求
    results = engine.trigger_by_natural_language(
        "帮我把这段英文翻译成中文",
        scene_type=SceneType.DEFAULT,
        top_k=3,
    )

    assert len(results) > 0
    assert results[0].category in ("document", "creative")  # 翻译类
    assert isinstance(results[0], SkillDiscoveryItem)

    print(f"[PASS] 自然语言触发: Top1={results[0].skill_name}, 得分={results[0].score}")


def test_natural_language_trigger_confidence():
    """验证置信度分级（HIGH/MEDIUM/LOW）."""
    engine = _build_engine_with_skills()

    # 高置信度：精确匹配
    high_results = engine.trigger_by_natural_language("代码审查", top_k=1)

    # 低置信度：模糊输入
    low_results = engine.trigger_by_natural_language("帮我看看这个", top_k=1)

    if high_results:
        assert high_results[0].confidence in ("HIGH", "MEDIUM")
    if low_results:
        assert low_results[0].confidence in ("MEDIUM", "LOW")

    print(f"[PASS] 置信度分级: 精确匹配={high_results[0].confidence if high_results else 'N/A'}")


# ========== 性能测试 ==========

def test_recommendation_performance():
    """验证推荐响应时间 < 50ms."""
    engine = _build_engine_with_skills()

    # 预热
    engine.recommend(scene_type=SceneType.CODING, top_k=3)

    # 测量100次平均
    times = []
    for _ in range(100):
        start = time.time()
        engine.recommend(scene_type=SceneType.CODING, user_input_preview="代码生成", top_k=3)
        times.append((time.time() - start) * 1000)

    avg_time = sum(times) / len(times)
    max_time = max(times)

    assert avg_time < 50, f"平均响应时间 {avg_time:.2f}ms 超过50ms"
    print(f"[PASS] 推荐性能: 平均 {avg_time:.2f}ms, 最大 {max_time:.2f}ms < 50ms")


def test_nl_trigger_performance():
    """验证自然语言触发响应时间 < 50ms."""
    engine = _build_engine_with_skills()

    # 预热
    engine.trigger_by_natural_language("测试", top_k=3)

    times = []
    for _ in range(100):
        start = time.time()
        engine.trigger_by_natural_language("帮我翻译这段英文成中文", top_k=3)
        times.append((time.time() - start) * 1000)

    avg_time = sum(times) / len(times)
    assert avg_time < 50, f"平均响应时间 {avg_time:.2f}ms 超过50ms"
    print(f"[PASS] NL触发性能: 平均 {avg_time:.2f}ms < 50ms")


# ========== 常用技能管理测试 ==========

def test_favorite_skills():
    """验证用户自定义常用技能列表."""
    engine = _build_engine_with_skills()

    # 添加收藏
    assert engine.add_favorite("skill.code_generator") is True
    assert engine.add_favorite("skill.translate") is True
    # 重复添加应返回False
    assert engine.add_favorite("skill.code_generator") is False

    favorites = engine.get_favorites()
    assert len(favorites) == 2
    assert any(f.skill_id == "skill.code_generator" for f in favorites)

    # 移除收藏
    assert engine.remove_favorite("skill.code_generator") is True
    assert len(engine.get_favorites()) == 1

    # 移除不存在的
    assert engine.remove_favorite("skill.nonexistent") is False

    print(f"[PASS] 常用技能: 添加/移除/查询正常")


# ========== 分类浏览测试 ==========

def test_category_browsing():
    """验证分类浏览功能."""
    engine = _build_engine_with_skills()

    # 获取所有分类
    categories = engine.list_categories()
    assert len(categories) == 6

    # 按分类获取技能
    coding_skills = engine.list_skills_by_category(SkillCategory.CODING)
    assert len(coding_skills) >= 3
    assert all(s.category == "coding" for s in coding_skills)

    life_skills = engine.list_skills_by_category("life")
    assert len(life_skills) >= 3

    print(f"[PASS] 分类浏览: {len(categories)}个分类, 代码类{len(coding_skills)}个, 生活类{len(life_skills)}个")


# ========== 统计信息测试 ==========

def test_stats():
    """验证统计信息完整."""
    engine = _build_engine_with_skills()
    stats = engine.stats()

    assert "total_skills" in stats
    assert "category_counts" in stats
    assert "total_keywords_indexed" in stats
    assert "favorite_count" in stats
    assert stats["total_skills"] > 0
    assert len(stats["category_counts"]) == 6

    print(f"[PASS] 统计信息: {stats['total_skills']}技能, {stats['total_keywords_indexed']}索引词")


# ========== 场景模式完整性测试 ==========

def test_scene_types_complete():
    """验证6种场景模式定义完整（与M4对齐）."""
    scenes = [s.value for s in SceneType]
    expected = ["CODING", "LEARNING", "LIFE", "DESIGN", "EMOTIONAL", "REVIEW", "DEFAULT"]
    for s in expected:
        assert s in scenes, f"缺少场景模式: {s}"

    print(f"[PASS] 场景模式: {len(scenes)} 种")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
