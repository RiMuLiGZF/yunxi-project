"""Tests for SkillBanditRouter."""

import pytest

from skill_cluster.skill_bandit_router import BanditArm, SkillBanditRouter


@pytest.fixture
def router():
    return SkillBanditRouter(explore_rate=0.0, min_calls_for_exploit=1)


def test_register_arm(router):
    router.register_arm("skill.a", "act1")
    assert router.get_arm_stats("skill.a", "act1")["registered"]


def test_select_single_candidate(router):
    result = router.select([("skill.a", "act1")])
    assert result == ("skill.a", "act1")


def test_select_explores(router):
    r = SkillBanditRouter(explore_rate=1.0)  # 100% explore
    candidates = [("skill.a", "act1"), ("skill.b", "act2")]
    # 多次选择应该覆盖所有候选（高概率）
    selected = {r.select(candidates) for _ in range(50)}
    assert len(selected) == 2


def test_record_success(router):
    router.register_arm("skill.a", "act1")
    reward = router.record("skill.a", "act1", success=True, latency_ms=100.0)
    assert 0.8 <= reward <= 1.0
    stats = router.get_arm_stats("skill.a", "act1")
    assert stats["success_rate"] > 0.5
    assert stats["total_calls"] == 1


def test_record_failure(router):
    router.register_arm("skill.a", "act1")
    reward = router.record("skill.a", "act1", success=False, latency_ms=5000.0)
    assert 0.0 <= reward <= 0.2
    stats = router.get_arm_stats("skill.a", "act1")
    assert stats["success_rate"] < 0.5


def test_exploit_prefers_high_success(router):
    router.register_arm("skill.a", "act1")
    router.register_arm("skill.b", "act1")

    # skill.a 成功率高
    for _ in range(10):
        router.record("skill.a", "act1", success=True)
    # skill.b 成功率低
    for _ in range(10):
        router.record("skill.b", "act1", success=False)

    ranked = router.rank_candidates([("skill.a", "act1"), ("skill.b", "act1")])
    assert ranked[0][0] == "skill.a"
    assert ranked[0][2] > ranked[1][2]


def test_stats(router):
    router.register_arm("skill.a", "act1")
    router.record("skill.a", "act1", True)
    stats = router.get_stats()
    assert stats["total_arms"] == 1
    assert stats["total_calls"] == 1
    assert stats["explore_rate"] == 0.0


def test_arm_decay():
    arm = BanditArm(skill_id="s", action="a")
    arm.alpha = 10.0
    arm.beta = 2.0
    arm.decay()
    assert arm.alpha == pytest.approx(10.0 * 0.995, abs=0.01)
    assert arm.beta == pytest.approx(2.0 * 0.995, abs=0.01)


def test_bandit_arm_sample():
    arm = BanditArm(skill_id="s", action="a", alpha=10.0, beta=2.0)
    # 高 alpha 应采样到高值
    samples = [arm.sample for _ in range(100)]
    assert all(0 <= s <= 1 for s in samples)


def test_bandit_arm_sample_value():
    arm = BanditArm(skill_id="s", action="a", alpha=10.0, beta=2.0)
    samples = [arm.sample_value() for _ in range(100)]
    assert all(0 <= s <= 1 for s in samples)


def test_record_with_user_feedback(router):
    """第二轮优化：上下文感知奖励 - 用户反馈调制."""
    router.register_arm("skill.a", "act1")
    # 成功 + 高反馈
    r1 = router.record("skill.a", "act1", success=True, latency_ms=100.0, user_feedback=1.0)
    # 成功 + 低反馈
    r2 = router.record("skill.a", "act1", success=True, latency_ms=100.0, user_feedback=0.0)
    # r1 应高于 r2（因为正向反馈上调，负向反馈下调）
    assert r1 > r2
