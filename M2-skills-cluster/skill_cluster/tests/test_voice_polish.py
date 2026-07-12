"""v3.9.0 VoicePolish 输出润色管道测试.

覆盖：
- 5类技能润色程度分级
- 3级降级策略（快速模式/超时/错误）
- 技术术语保护机制
- 预算隔离验证
- 15种组合测试
"""

import asyncio
import pytest

from skill_cluster.voice_polish import (
    VoicePolishEngine,
    VoicePolishConfig,
    PolishLevel,
    SkillType,
    SKILL_TYPE_POLISH_MAP,
)


# ========== 基础测试 ==========

def test_polish_level_enum():
    """验证5级润色程度定义完整."""
    levels = [l.value for l in PolishLevel]
    assert "deep" in levels
    assert "medium" in levels
    assert "light" in levels
    assert "gentle" in levels
    assert "framework" in levels
    assert len(levels) == 5
    print(f"[PASS] 5级润色程度: {levels}")


def test_skill_type_enum():
    """验证5类技能类型定义完整."""
    types = [t.value for t in SkillType]
    assert "creative" in types
    assert "analysis" in types
    assert "factual" in types
    assert "error" in types
    assert "technical" in types
    assert len(types) == 5
    print(f"[PASS] 5类技能类型: {types}")


def test_skill_type_polish_mapping():
    """验证技能类型到润色级别的映射."""
    assert SKILL_TYPE_POLISH_MAP[SkillType.CREATIVE] == PolishLevel.DEEP
    assert SKILL_TYPE_POLISH_MAP[SkillType.ANALYSIS] == PolishLevel.MEDIUM
    assert SKILL_TYPE_POLISH_MAP[SkillType.FACTUAL] == PolishLevel.LIGHT
    assert SKILL_TYPE_POLISH_MAP[SkillType.ERROR] == PolishLevel.GENTLE
    assert SKILL_TYPE_POLISH_MAP[SkillType.TECHNICAL] == PolishLevel.FRAMEWORK
    print("[PASS] 技能类型→润色级别映射正确")


def test_infer_skill_type():
    """验证技能类型自动推断."""
    engine = VoicePolishEngine()

    # 代码/技术类
    assert engine.infer_skill_type("skill.code_search") == SkillType.TECHNICAL
    assert engine.infer_skill_type("skill.bug_finder") == SkillType.TECHNICAL

    # 创意/写作类
    assert engine.infer_skill_type("skill.translate") == SkillType.CREATIVE
    assert engine.infer_skill_type("skill.doc_proc") == SkillType.CREATIVE

    # 分析/建议类
    assert engine.infer_skill_type("skill.data_analysis") == SkillType.ANALYSIS

    # 事实/数据类
    assert engine.infer_skill_type("skill.calendar") == SkillType.FACTUAL
    assert engine.infer_skill_type("skill.web_fetch") == SkillType.FACTUAL

    print("[PASS] 技能类型推断正确")


# ========== 润色功能测试 ==========

@pytest.mark.asyncio
async def test_polish_success():
    """验证正常润色流程."""
    engine = VoicePolishEngine()

    async def mock_voice_polish(**kwargs):
        return {
            "polished_content": f"[润色后] {kwargs['raw_content']}",
            "tokens_consumed": 42,
        }

    engine.set_m1_voice_callback(mock_voice_polish)
    engine.set_skill_config(
        "skill.test",
        VoicePolishConfig(
            voice_polish_level=PolishLevel.MEDIUM,
            skill_type=SkillType.ANALYSIS,
        ),
    )

    result = await engine.polish(
        skill_id="skill.test",
        raw_content="这是原始输出内容。",
        scene_type="CODING",
        task_id="task_001",
    )

    assert result.voice_degraded is False
    assert "[润色后]" in result.polished_content
    assert result.tokens_consumed == 42
    assert result.polish_level == PolishLevel.MEDIUM
    assert result.technical_terms_preserved is True
    print(f"[PASS] 正常润色: {result.polished_content[:30]}...")


# ========== 降级策略测试（3级）==========

@pytest.mark.asyncio
async def test_degrade_concise_mode():
    """降级1：简洁模式（快速模式）跳过润色."""
    engine = VoicePolishEngine()
    engine.set_concise_mode(True)

    result = await engine.polish(
        skill_id="skill.test",
        raw_content="原始内容",
        task_id="t1",
    )

    assert result.voice_degraded is True
    assert result.degrade_reason == "concise_mode"
    assert result.polished_content == "原始内容"
    assert result.tokens_consumed == 0
    print(f"[PASS] 简洁模式降级: {result.degrade_reason}")


@pytest.mark.asyncio
async def test_degrade_timeout():
    """降级2：超时自动降级."""
    engine = VoicePolishEngine()

    async def slow_polish(**kwargs):
        await asyncio.sleep(0.5)  # 模拟超时
        return {"polished_content": "太慢了", "tokens_consumed": 10}

    engine.set_m1_voice_callback(slow_polish)
    engine.set_skill_config(
        "skill.slow",
        VoicePolishConfig(
            voice_polish_level=PolishLevel.DEEP,
            skill_type=SkillType.CREATIVE,
            timeout_ms=100,  # 100ms超时
        ),
    )

    result = await engine.polish(
        skill_id="skill.slow",
        raw_content="测试超时",
        task_id="t2",
    )

    assert result.voice_degraded is True
    assert result.degrade_reason == "timeout"
    assert result.polished_content == "测试超时"
    print(f"[PASS] 超时降级: {result.degrade_reason}")


@pytest.mark.asyncio
async def test_degrade_error():
    """降级3：润色错误时返回原始内容."""
    engine = VoicePolishEngine()

    async def error_polish(**kwargs):
        raise RuntimeError("YunxiVoice服务异常")

    engine.set_m1_voice_callback(error_polish)
    engine.set_skill_config(
        "skill.err",
        VoicePolishConfig(
            voice_polish_level=PolishLevel.MEDIUM,
            skill_type=SkillType.ANALYSIS,
        ),
    )

    result = await engine.polish(
        skill_id="skill.err",
        raw_content="错误测试内容",
        task_id="t3",
    )

    assert result.voice_degraded is True
    assert "error" in (result.degrade_reason or "")
    assert result.polished_content == "错误测试内容"
    print(f"[PASS] 错误降级: {result.degrade_reason}")


@pytest.mark.asyncio
async def test_degrade_budget_exceeded():
    """降级4：润色预算不足时跳过."""
    engine = VoicePolishEngine()

    def mock_budget(**kwargs):
        return False  # 预算不足

    async def mock_polish(**kwargs):
        return {"polished_content": "不会到这里", "tokens_consumed": 100}

    engine.set_m1_voice_callback(mock_polish)
    engine.set_m1_voice_budget_callback(mock_budget)

    result = await engine.polish(
        skill_id="skill.test",
        raw_content="预算测试",
        task_id="t_budget",
    )

    assert result.voice_degraded is True
    assert result.degrade_reason == "voice_budget_exceeded"
    assert result.polished_content == "预算测试"
    print(f"[PASS] 预算不足降级: {result.degrade_reason}")


# ========== 技术术语保护测试 ==========

def test_extract_technical_terms():
    """验证技术术语提取能力."""
    engine = VoicePolishEngine()

    content = """
    代码示例：
    ```python
    def hello():
        return "world"
    ```
    行内代码：`print("hi")`
    错误码：错误码 404
    数值：延迟 120ms，成功率 99.5%，大小 2.5MB
    """

    terms = engine._extract_technical_terms(content)
    # 验证提取到了术语（代码块/错误码/数值至少有一类）
    assert len(terms) > 0, "应提取到至少一个技术术语"
    # 验证提取到了代码块
    has_code_block = any("```" in t for t in terms)
    # 验证提取到了错误码或数值
    has_number = any("404" in t or "120" in t or "99.5" in t or "2.5" in t for t in terms)
    assert has_code_block or has_number, "应提取到代码块或数值类术语"
    print(f"[PASS] 技术术语提取: 提取到 {len(terms)} 个术语")


@pytest.mark.asyncio
async def test_technical_terms_preserved():
    """验证技术术语在润色后被完整保留."""
    engine = VoicePolishEngine()

    async def safe_polish(**kwargs):
        # 模拟正常润色，保留技术术语
        raw = kwargs["raw_content"]
        return {"polished_content": f"好的，结果如下：\n{raw}", "tokens_consumed": 30}

    engine.set_m1_voice_callback(safe_polish)
    engine.set_skill_config(
        "skill.code",
        VoicePolishConfig(
            voice_polish_level=PolishLevel.FRAMEWORK,
            skill_type=SkillType.TECHNICAL,
            preserve_technical_terms=True,
        ),
    )

    raw = "```python\ndef test(): pass\n```\n错误码: 500，耗时 120ms"
    result = await engine.polish("skill.code", raw, task_id="t_terms")

    assert result.technical_terms_preserved is True
    assert "def test()" in result.polished_content
    assert "500" in result.polished_content
    assert "120ms" in result.polished_content
    print(f"[PASS] 技术术语保护: 保留完整")


@pytest.mark.asyncio
async def test_technical_terms_tampered_degrade():
    """验证技术术语被篡改时自动降级."""
    engine = VoicePolishEngine()

    async def tamper_polish(**kwargs):
        # 模拟润色篡改了代码（把代码删掉了）
        return {"polished_content": "我把代码润色没了哈哈", "tokens_consumed": 20}

    engine.set_m1_voice_callback(tamper_polish)
    engine.set_skill_config(
        "skill.code",
        VoicePolishConfig(
            voice_polish_level=PolishLevel.FRAMEWORK,
            skill_type=SkillType.TECHNICAL,
            preserve_technical_terms=True,
        ),
    )

    raw = "```python\ncritical_code()\n```"
    result = await engine.polish("skill.code", raw, task_id="t_tamper")

    # 术语被篡改，应该降级返回原始内容
    assert result.voice_degraded is True
    assert result.degrade_reason == "technical_terms_tampered"
    assert result.technical_terms_preserved is False
    assert result.polished_content == raw  # 返回原始内容
    print(f"[PASS] 术语篡改降级: {result.degrade_reason}")


# ========== 5类 × 3级降级 = 15种组合测试 ==========

SKILL_TYPES_TO_TEST = [
    ("creative", SkillType.CREATIVE, PolishLevel.DEEP, "创意文案内容"),
    ("analysis", SkillType.ANALYSIS, PolishLevel.MEDIUM, "数据分析结果：发现3个异常点"),
    ("factual", SkillType.FACTUAL, PolishLevel.LIGHT, "今日天气：晴，25°C"),
    ("error", SkillType.ERROR, PolishLevel.GENTLE, "错误：连接失败，请重试"),
    ("technical", SkillType.TECHNICAL, PolishLevel.FRAMEWORK, "```js\nconsole.log(1)\n```"),
]

DEGRADE_SCENARIOS = ["concise_mode", "timeout", "error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("type_name,skill_type,level,sample_text", SKILL_TYPES_TO_TEST)
@pytest.mark.parametrize("degrade_type", DEGRADE_SCENARIOS)
async def test_15_combinations(type_name, skill_type, level, sample_text, degrade_type):
    """15种组合测试：5类技能 × 3种降级场景."""
    engine = VoicePolishEngine()

    # 设置技能配置
    engine.set_skill_config(
        f"skill.{type_name}",
        VoicePolishConfig(
            voice_polish_level=level,
            skill_type=skill_type,
            timeout_ms=100,
        ),
    )

    # 根据降级类型设置不同的触发条件
    if degrade_type == "concise_mode":
        engine.set_concise_mode(True)
        result = await engine.polish(f"skill.{type_name}", sample_text, task_id=f"t_{type_name}_c")
        assert result.degrade_reason == "concise_mode"

    elif degrade_type == "timeout":
        async def slow(**kwargs):
            await asyncio.sleep(0.3)
            return {"polished_content": "慢", "tokens_consumed": 5}
        engine.set_m1_voice_callback(slow)
        result = await engine.polish(f"skill.{type_name}", sample_text, task_id=f"t_{type_name}_t")
        assert result.degrade_reason == "timeout"

    elif degrade_type == "error":
        async def err(**kwargs):
            raise RuntimeError("service error")
        engine.set_m1_voice_callback(err)
        result = await engine.polish(f"skill.{type_name}", sample_text, task_id=f"t_{type_name}_e")
        assert "error" in (result.degrade_reason or "")

    # 共同验证：降级状态、返回原始内容、零token消耗
    assert result.voice_degraded is True
    assert result.polished_content == sample_text
    assert result.tokens_consumed == 0
    assert result.polish_level == level

    print(f"[PASS] 组合 {type_name} × {degrade_type}: 降级正常")


# ========== 预算隔离测试 ==========

@pytest.mark.asyncio
async def test_voice_budget_isolation():
    """验证润色消耗单独计量，不挤占主技能预算."""
    engine = VoicePolishEngine(voice_budget_ratio=0.1)

    budget_calls = []
    def mock_budget(**kwargs):
        budget_calls.append(kwargs)
        return True

    engine.set_m1_voice_budget_callback(mock_budget)

    async def mock_polish(**kwargs):
        return {"polished_content": "润色后内容", "tokens_consumed": 50}

    engine.set_m1_voice_callback(mock_polish)
    engine.set_skill_config(
        "skill.test",
        VoicePolishConfig(skill_type=SkillType.ANALYSIS),
    )

    result = await engine.polish(
        "skill.test",
        "原始内容",
        task_id="t_budget_iso",
    )

    # 验证预算申请使用了独立的 voice_polish 分类
    assert len(budget_calls) >= 1
    assert budget_calls[0].get("category") == "voice_polish"
    assert result.tokens_consumed == 50
    print(f"[PASS] 预算隔离: category=voice_polish, 消耗{result.tokens_consumed}tokens")


# ========== 性能测试 ==========

@pytest.mark.asyncio
async def test_polish_performance():
    """验证润色响应时间（含M1调用开销）P95 < 500ms."""
    engine = VoicePolishEngine()

    async def fast_polish(**kwargs):
        await asyncio.sleep(0.01)  # 模拟10ms网络+计算
        return {"polished_content": kwargs["raw_content"][::-1], "tokens_consumed": 10}

    engine.set_m1_voice_callback(fast_polish)
    engine.set_skill_config(
        "skill.fast",
        VoicePolishConfig(skill_type=SkillType.ANALYSIS, timeout_ms=500),
    )

    # 运行10次，统计P95
    latencies = []
    for i in range(10):
        result = await engine.polish("skill.fast", f"测试内容{i}", task_id=f"perf_{i}")
        latencies.append(result.latency_ms)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]

    assert p95 < 500, f"P95延迟{p95}ms超过500ms阈值"
    print(f"[PASS] 性能: P95={p95:.1f}ms < 500ms, 平均={sum(latencies)/len(latencies):.1f}ms")


# ========== 全局开关测试 ==========

def test_global_enable_disable():
    """验证全局开关功能."""
    engine = VoicePolishEngine()
    stats = engine.stats()
    assert stats["enabled"] is True

    engine.disable()
    assert engine.stats()["enabled"] is False

    engine.enable()
    assert engine.stats()["enabled"] is True
    print("[PASS] 全局开关正常")


def test_stats():
    """验证统计信息完整."""
    engine = VoicePolishEngine()
    stats = engine.stats()

    assert "enabled" in stats
    assert "concise_mode" in stats
    assert "configured_skills" in stats
    assert "default_timeout_ms" in stats
    assert "voice_budget_ratio" in stats
    assert "polish_levels" in stats
    assert "skill_types" in stats
    assert len(stats["polish_levels"]) == 5
    assert len(stats["skill_types"]) == 5
    print(f"[PASS] 统计信息: {len(stats)} 项指标")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
