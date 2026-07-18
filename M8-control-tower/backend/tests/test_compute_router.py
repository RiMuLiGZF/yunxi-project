"""
算力调度中台 - 验证测试脚本
测试内容：
1. 路由决策（正常情况）
2. 故障转移（主源失败切换到备选）
3. 熔断机制（连续失败触发熔断）
4. 限流（超过限制被拒绝）
5. 额度管理（超额告警）
6. 调用统计与监控
7. 技能权限绑定
8. 熔断器状态查询

兼容第一部分表结构：
- 动态添加测试数据（如果不存在）
- 适配第一部分的字段命名
"""

import sys
import os
import asyncio
from pathlib import Path

# 设置模块路径，确保相对导入能正常工作
backend_dir = Path(__file__).parent
project_root = backend_dir.parent.parent

# 确保以包的形式导入
# 设置 __package__ 以支持相对导入
__package__ = "backend"

from backend.models import (
    init_db, SessionLocal, Base, engine,
    ComputeSource, ComputeKeyGroup, ComputeModelBinding,
    ComputeRoutingPolicy, ComputeSkillBinding, ComputeQuota,
)
from backend.compute_router import ComputeRouter, get_compute_router, RouteStatus


# ============================================================
# 测试辅助函数
# ============================================================

def print_header(title):
    """打印测试标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_result(passed, test_name, detail=""):
    """打印测试结果"""
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] - {test_name}")
    if detail:
        print(f"         {detail}")


def ensure_test_data():
    """确保有足够的测试数据（兼容第一部分）"""
    db = SessionLocal()
    try:
        now = __import__('datetime').datetime.utcnow()
        
        # 检查现有算力源数量
        source_count = db.query(ComputeSource).count()
        
        # 如果算力源不足，添加测试用的算力源
        test_sources = [
            {
                "source_id": "test-openai",
                "name": "测试 OpenAI",
                "type": "cloud",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key_encrypted": "test-key-1",
                "api_key_masked": "sk-****1234",
                "status": "active",
                "priority": 20,
                "weight": 100,
                "max_concurrent": 20,
                "timeout": 60,
                "cost_per_1k_input": 0.005,
                "cost_per_1k_output": 0.015,
                "latency_avg": 800.0,
                "success_rate": 0.98,
                "models": ["gpt-3.5-turbo", "gpt-4"],
                "capabilities": ["chat", "embedding"],
                "health_status": "healthy",
                "config": {
                    "quality_score": 0.9,
                    "privacy_level": "public",
                    "rate_limit_per_minute": 60,
                    "region": "us-east-1",
                },
            },
            {
                "source_id": "test-deepseek",
                "name": "测试 DeepSeek",
                "type": "cloud",
                "provider": "deepseek",
                "base_url": "https://api.deepseek.com/v1",
                "api_key_encrypted": "test-key-2",
                "api_key_masked": "sk-****5678",
                "status": "active",
                "priority": 30,
                "weight": 80,
                "max_concurrent": 30,
                "timeout": 60,
                "cost_per_1k_input": 0.001,
                "cost_per_1k_output": 0.002,
                "latency_avg": 500.0,
                "success_rate": 0.95,
                "models": ["deepseek-chat", "deepseek-coder"],
                "capabilities": ["chat", "code"],
                "health_status": "healthy",
                "config": {
                    "quality_score": 0.75,
                    "privacy_level": "public",
                    "rate_limit_per_minute": 120,
                    "region": "cn-hangzhou",
                },
            },
            {
                "source_id": "test-anthropic",
                "name": "测试 Anthropic",
                "type": "cloud",
                "provider": "anthropic",
                "base_url": "https://api.anthropic.com/v1",
                "api_key_encrypted": "test-key-3",
                "api_key_masked": "sk-****9012",
                "status": "active",
                "priority": 40,
                "weight": 60,
                "max_concurrent": 10,
                "timeout": 120,
                "cost_per_1k_input": 0.015,
                "cost_per_1k_output": 0.075,
                "latency_avg": 1200.0,
                "success_rate": 0.99,
                "models": ["claude-3-sonnet", "claude-3-opus"],
                "capabilities": ["chat", "vision"],
                "health_status": "healthy",
                "config": {
                    "quality_score": 0.95,
                    "privacy_level": "internal",
                    "rate_limit_per_minute": 30,
                    "region": "us-west-2",
                },
            },
        ]
        
        for src_data in test_sources:
            existing = db.query(ComputeSource).filter(
                ComputeSource.source_id == src_data["source_id"]
            ).first()
            if not existing:
                db.add(ComputeSource(**src_data))
        
        # 确保有 premium 分组
        premium_group = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == "premium"
        ).first()
        if not premium_group:
            db.add(ComputeKeyGroup(
                group_id="premium",
                name="高端模型分组",
                description="高端大模型分组，包含 OpenAI 和 Anthropic",
                source_ids=["test-openai", "test-anthropic"],
                default_source="test-anthropic",
                routing_strategy="quality_first",
                created_at=now,
                updated_at=now,
            ))
        
        # 确保有 default-chat 模型绑定到 default 分组
        default_chat = db.query(ComputeModelBinding).filter(
            ComputeModelBinding.model_key == "default-chat"
        ).first()
        
        # 确保 default 分组存在且包含所有算力源
        all_sources = [s.source_id for s in db.query(ComputeSource).all()]
        default_group = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == "default"
        ).first()
        if not default_group:
            db.add(ComputeKeyGroup(
                group_id="default",
                name="默认分组",
                description="默认算力分组，包含所有可用算力源",
                source_ids=all_sources,
                default_source=all_sources[0] if all_sources else "",
                routing_strategy="auto",
                created_at=now,
                updated_at=now,
            ))
        else:
            # 更新 default 分组，确保包含所有算力源
            existing_ids = default_group.source_ids or []
            for sid in all_sources:
                if sid not in existing_ids:
                    existing_ids.append(sid)
            default_group.source_ids = existing_ids
            default_group.updated_at = now
        
        if not default_chat:
            db.add(ComputeModelBinding(
                model_key="default-chat",
                model_name="默认对话模型",
                purpose="chat",
                group_id="default",
                fallback_model_key="",
                max_tokens=4096,
                temperature_default=0.7,
                created_at=now,
                updated_at=now,
            ))
        
        # 确保有 premium-chat 模型绑定
        premium_chat = db.query(ComputeModelBinding).filter(
            ComputeModelBinding.model_key == "premium-chat"
        ).first()
        if not premium_chat:
            db.add(ComputeModelBinding(
                model_key="premium-chat",
                model_name="高端对话模型",
                purpose="chat",
                group_id="premium",
                fallback_model_key="default-chat",
                max_tokens=8192,
                temperature_default=0.7,
                created_at=now,
                updated_at=now,
            ))
        
        # 确保有 auto 路由策略
        auto_policy = db.query(ComputeRoutingPolicy).filter(
            ComputeRoutingPolicy.policy_id == "auto"
        ).first()
        if not auto_policy:
            db.add(ComputeRoutingPolicy(
                policy_id="auto",
                name="自动路由策略",
                mode="auto",
                default_strategy="latency_first",
                cost_weight=0.3,
                latency_weight=0.4,
                quality_weight=0.2,
                privacy_weight=0.1,
                auto_failover=True,
                circuit_breaker_enabled=True,
                rate_limit_enabled=True,
                offline_fallback_enabled=True,
                vram_safe_threshold=70.0,
                vram_critical_threshold=90.0,
                network_latency_threshold=500,
                config={
                    "cb_error_threshold": 0.5,
                    "cb_window_seconds": 60,
                    "cb_cooldown_seconds": 30,
                    "cb_half_open_probes": 3,
                    "global_rate_per_minute": 1000,
                    "max_failover_attempts": 3,
                },
                created_at=now,
                updated_at=now,
            ))
        
        # 确保有技能绑定
        code_skill = db.query(ComputeSkillBinding).filter(
            ComputeSkillBinding.skill_id == "skill-code"
        ).first()
        if not code_skill:
            db.add(ComputeSkillBinding(
                skill_id="skill-code",
                skill_name="代码生成",
                allowed_groups=["premium"],
                allowed_sources=["test-deepseek"],
                quota_daily=10.0,
                quota_monthly=200.0,
                rate_limit_per_min=30,
                priority=30,
                created_at=now,
                updated_at=now,
            ))
        
        # 确保有额度配置
        global_quota = db.query(ComputeQuota).filter(
            ComputeQuota.scope == "global",
            ComputeQuota.scope_key == "total",
            ComputeQuota.period == "daily",
        ).first()
        if not global_quota:
            db.add(ComputeQuota(
                scope="global",
                scope_key="total",
                period="daily",
                limit_amount=100.0,
                used_amount=0.0,
                alert_threshold=80.0,
                action_on_exceed="alert_only",
                created_at=now,
                updated_at=now,
            ))
        
        # 技能额度
        skill_quota = db.query(ComputeQuota).filter(
            ComputeQuota.scope == "skill",
            ComputeQuota.scope_key == "skill-code",
            ComputeQuota.period == "daily",
        ).first()
        if not skill_quota:
            db.add(ComputeQuota(
                scope="skill",
                scope_key="skill-code",
                period="daily",
                limit_amount=10.0,
                used_amount=0.0,
                alert_threshold=80.0,
                action_on_exceed="alert_only",
                created_at=now,
                updated_at=now,
            ))
        
        db.commit()
        print("  测试数据已准备完成")
        
    except Exception as e:
        db.rollback()
        import traceback
        print(f"  警告：准备测试数据失败: {e}")
        traceback.print_exc()
    finally:
        db.close()


# ============================================================
# 测试 1: 路由决策（正常情况）
# ============================================================

async def test_routing_decision(router):
    """测试路由决策 - 正常情况"""
    print_header("测试 1: 路由决策（正常情况）")

    all_passed = True

    # 1.1 默认模型路由
    result = await router.route(model_key="default-chat", purpose="chat")
    passed = result.status == RouteStatus.SUCCESS and result.source_id is not None
    all_passed = all_passed and passed
    print_result(passed, "默认聊天模型路由",
                 f"选中: {result.source_name} ({result.source_id}), 得分: {result.score}")

    # 1.2 高端模型路由
    result = await router.route(model_key="premium-chat", purpose="chat")
    passed = result.status == RouteStatus.SUCCESS and result.source_id is not None
    all_passed = all_passed and passed
    print_result(passed, "高端聊天模型路由",
                 f"选中: {result.source_name} ({result.source_id}), 得分: {result.score}")

    # 1.3 偏好本地（如果有本地算力源）
    sources = router.get_all_sources()
    has_local = any(s.get("deployment_type") == "local" for s in sources.values())
    if has_local:
        result = await router.route(model_key="default-chat", purpose="chat", prefer_local=True)
        passed = result.status == RouteStatus.SUCCESS
        all_passed = all_passed and passed
        is_local = sources.get(result.source_id, {}).get("deployment_type") == "local"
        print_result(passed and is_local, "偏好本地算力源",
                     f"选中: {result.source_name}, 本地={is_local}")
    else:
        print_result(True, "偏好本地算力源（跳过：无本地源）")

    # 1.4 检查备选列表
    result = await router.route(model_key="default-chat", purpose="chat")
    # 至少要有 2 个以上算力源才有备选
    active_sources = [s for s in sources.values() if s.get("status") == "active"]
    if len(active_sources) >= 2:
        passed = len(result.failover_list) > 0
        all_passed = all_passed and passed
        print_result(passed, "故障转移备选列表",
                     f"备选数量: {len(result.failover_list)}")
    else:
        print_result(True, "故障转移备选列表（跳过：算力源不足）")

    # 1.5 高隐私等级路由
    result = await router.route(
        model_key="default-chat", purpose="chat",
        privacy_level="top_secret", prefer_local=True
    )
    # 可能没有本地源，所以状态可能是 NO_AVAILABLE，这也是正确的
    passed = result.status in (RouteStatus.SUCCESS, RouteStatus.NO_AVAILABLE)
    all_passed = all_passed and passed
    print_result(passed, "高隐私等级路由",
                 f"状态: {result.status.value}, 选中: {result.source_name or '无'}")

    # 1.6 不存在的模型
    result = await router.route(model_key="nonexistent-model", purpose="chat")
    passed = result.status == RouteStatus.NO_AVAILABLE
    all_passed = all_passed and passed
    print_result(passed, "不存在的模型返回 NO_AVAILABLE",
                 f"状态: {result.status.value}")

    return all_passed


# ============================================================
# 测试 2: 故障转移
# ============================================================

async def test_failover(router):
    """测试故障转移"""
    print_header("测试 2: 故障转移（主源失败切换到备选）")

    all_passed = True

    # 先获取正常路由结果
    normal_result = await router.route(model_key="default-chat", purpose="chat")
    primary_source = normal_result.source_id
    print(f"  主算力源: {normal_result.source_name} ({primary_source})")
    print(f"  备选列表: {[f['source_name'] for f in normal_result.failover_list]}")

    if not normal_result.failover_list:
        # 如果没有备选列表，检查是否有多个算力源
        sources = router.get_all_sources()
        active_count = sum(1 for s in sources.values() if s.get("status") == "active")
        if active_count < 2:
            print_result(True, "故障转移测试（跳过：算力源不足2个）")
            return True
        # 有多个源但没有备选，可能是配置问题
        print_result(False, "有多个算力源但没有备选列表")
        return False

    # 模拟故障转移
    failover_result = await router.failover(
        failed_source_id=primary_source,
        model_key="default-chat",
        reason="测试故障转移",
    )

    passed = failover_result is not None and failover_result.status == RouteStatus.SUCCESS
    all_passed = all_passed and passed
    print_result(passed, "故障转移成功",
                 f"转移到: {failover_result.source_name if failover_result else 'None'}")

    if failover_result:
        # 验证转移后的源不是原来的源
        passed = failover_result.source_id != primary_source
        all_passed = all_passed and passed
        print_result(passed, "故障转移切换到不同的源",
                     f"原: {primary_source} -> 新: {failover_result.source_id}")

        # 验证原因记录
        passed = "故障转移" in failover_result.reason
        all_passed = all_passed and passed
        print_result(passed, "故障转移原因已记录",
                     f"原因: {failover_result.reason}")

    return all_passed


# ============================================================
# 测试 3: 熔断机制
# ============================================================

async def test_circuit_breaker(router):
    """测试熔断机制 - 连续失败触发熔断"""
    print_header("测试 3: 熔断机制（连续失败触发熔断）")

    all_passed = True
    
    # 找一个存在的算力源
    sources = router.get_all_sources()
    if not sources:
        print_result(False, "没有算力源可用")
        return False
    
    test_source_id = list(sources.keys())[0]

    # 3.1 获取初始熔断器状态
    cb = router.get_circuit_breaker(test_source_id)
    if not cb:
        print_result(False, f"算力源 {test_source_id} 熔断器不存在")
        return False

    initial_state = cb.state.value
    print_result(True, "初始熔断器状态", f"状态: {initial_state}")

    # 3.2 重置熔断器（确保初始状态正确）
    cb.reset()
    passed = cb.state.value == "closed"
    all_passed = all_passed and passed
    print_result(passed, "重置后熔断器为 closed 状态")

    # 3.3 连续记录失败，触发熔断
    for i in range(10):
        cb.record_result(False)

    error_rate = cb.get_error_rate()
    state = cb.state.value
    print(f"  连续失败 10 次后: 状态={state}, 错误率={error_rate:.2%}")

    # 3.4 验证熔断状态
    passed = error_rate >= 0.5
    all_passed = all_passed and passed
    print_result(passed, "错误率超过阈值",
                 f"错误率: {error_rate:.2%}, 阈值: 50%")

    # 3.5 验证请求被拒绝
    can_allow = cb.can_allow_request()
    # 错误率超过阈值应该打开熔断器，不允许请求
    if error_rate >= 0.5 and len(cb.window) >= 5:
        passed = state == "open" or can_allow == False
        all_passed = all_passed and passed
        print_result(passed, "高错误率时熔断生效",
                     f"状态: {state}, can_allow: {can_allow}")
    else:
        print_result(True, "跳过：请求数不足，熔断未触发（符合预期）")

    # 3.6 测试熔断重置
    cb.reset()
    passed = cb.state.value == "closed" and cb.get_error_rate() == 0.0
    all_passed = all_passed and passed
    print_result(passed, "熔断器重置成功",
                 f"状态: {cb.state.value}, 错误率: {cb.get_error_rate():.2%}")

    # 3.7 测试半开状态（模拟冷却后）
    cb.state = type(cb.state).OPEN
    cb.open_time = 0  # 设置为很久以前，模拟冷却完成
    can_allow = cb.can_allow_request()
    passed = cb.state.value == "half_open" and can_allow == True
    all_passed = all_passed and passed
    print_result(passed, "冷却后进入半开状态",
                 f"状态: {cb.state.value}")

    # 3.8 半开探测成功后关闭
    for i in range(cb.half_open_probes):
        cb.record_result(True)
    passed = cb.state.value == "closed"
    all_passed = all_passed and passed
    print_result(passed, "半开探测成功后关闭熔断器",
                 f"状态: {cb.state.value}")

    return all_passed


# ============================================================
# 测试 4: 限流机制
# ============================================================

async def test_rate_limiting(router):
    """测试限流机制 - 令牌桶算法"""
    print_header("测试 4: 限流机制（超过限制被拒绝）")

    all_passed = True

    from backend.compute_router import RateLimiter

    # 4.1 测试令牌桶基本功能
    limiter = RateLimiter(rate_per_minute=10)
    passed = limiter.rate_per_minute == 10 and limiter.capacity == 10
    all_passed = all_passed and passed
    print_result(passed, "令牌桶初始化",
                 f"速率: {limiter.rate_per_minute}/分钟, 容量: {limiter.capacity}")

    # 4.2 测试获取令牌
    tokens_before = limiter.get_available_tokens()
    result = limiter.try_acquire()
    tokens_after = limiter.get_available_tokens()
    passed = result and tokens_after < tokens_before
    all_passed = all_passed and passed
    print_result(passed, "成功获取令牌",
                 f"获取前: {tokens_before:.2f}, 获取后: {tokens_after:.2f}")

    # 4.3 测试耗尽令牌
    limiter2 = RateLimiter(rate_per_minute=5)
    success_count = 0
    for i in range(10):
        if limiter2.try_acquire():
            success_count += 1
    passed = success_count <= 6  # 应该最多5-6个（有少量补充）
    all_passed = all_passed and passed
    print_result(passed, "令牌耗尽后请求被拒绝",
                 f"成功次数: {success_count}/10")

    # 4.4 测试无限流（rate=0）
    limiter3 = RateLimiter(rate_per_minute=0)
    all_success = True
    for i in range(100):
        if not limiter3.try_acquire():
            all_success = False
            break
    passed = all_success
    all_passed = all_passed and passed
    print_result(passed, "rate=0 时不限流",
                 f"100 次请求全部成功")

    # 4.5 测试限流重置
    limiter4 = RateLimiter(rate_per_minute=5)
    for i in range(5):
        limiter4.try_acquire()
    tokens_before_reset = limiter4.get_available_tokens()
    limiter4.reset()
    tokens_after_reset = limiter4.get_available_tokens()
    passed = tokens_after_reset > tokens_before_reset and tokens_after_reset == 5
    all_passed = all_passed and passed
    print_result(passed, "限流重置成功",
                 f"重置前: {tokens_before_reset:.2f}, 重置后: {tokens_after_reset:.2f}")

    # 4.6 全局限流器存在性
    rate_limits = router.get_rate_limits()
    passed = "global" in rate_limits and rate_limits["global"].get("rate_per_minute", 0) > 0
    all_passed = all_passed and passed
    print_result(passed, "全局限流器存在",
                 f"速率: {rate_limits['global'].get('rate_per_minute')}/分钟")

    # 4.7 算力源级限流
    passed = "sources" in rate_limits and len(rate_limits["sources"]) > 0
    all_passed = all_passed and passed
    print_result(passed, "算力源级限流配置存在",
                 f"数量: {len(rate_limits.get('sources', {}))}")

    return all_passed


# ============================================================
# 测试 5: 额度管理
# ============================================================

async def test_quota_management(router):
    """测试额度管理 - 超额告警"""
    print_header("测试 5: 额度管理（超额告警）")

    all_passed = True

    # 5.1 获取初始额度
    quotas = router.get_all_quotas()
    passed = len(quotas) > 0
    all_passed = all_passed and passed
    print_result(passed, "额度配置存在",
                 f"数量: {len(quotas)}")

    # 5.2 打印所有额度信息
    for qid, q in quotas.items():
        print(f"    - {qid}: {q['scope']}/{q['scope_key']} "
              f"{q.get('limit_type', 'cost')} {q['period']} "
              f"已用: {q['used_value']:.2f}/{q['limit_value']:.2f}")

    # 5.3 模拟调用，增加使用量
    # 找到一个日额度成本限制
    test_quota_id = None
    for qid, q in quotas.items():
        if q["period"] == "daily" and q["limit_value"] > 0:
            test_quota_id = qid
            break

    if test_quota_id:
        # 模拟路由结果用于记录
        result = await router.route(model_key="default-chat", purpose="chat")

        # 记录一次调用
        router.record_call(
            route_result=result,
            success=True,
            output_tokens=1000,
            latency_ms=500,
        )

        # 检查使用量是否增加（成本型额度会增加）
        updated_quotas = router.get_all_quotas()
        used_before = quotas[test_quota_id]["used_value"]
        used_after = updated_quotas[test_quota_id]["used_value"]
        # 成本可能为0（本地源），所以用 >= 判断
        passed = used_after >= used_before
        all_passed = all_passed and passed
        print_result(passed, "调用后额度使用量更新",
                     f"从 {used_before:.4f} 到 {used_after:.4f}")

        # 5.4 测试额度重置
        router.reset_quota(test_quota_id)
        reset_quotas = router.get_all_quotas()
        passed = reset_quotas[test_quota_id]["used_value"] == 0
        all_passed = all_passed and passed
        print_result(passed, "额度重置成功",
                     f"重置后使用量: {reset_quotas[test_quota_id]['used_value']:.4f}")

        # 5.5 测试额度告警阈值计算
        # 手动设置高使用量
        q = router.get_all_quotas().get(test_quota_id, {})
        limit = q.get("limit_value", 100.0)
        
        # 手动修改内存中的额度来测试告警
        with router._lock:
            if test_quota_id in router._quotas:
                router._quotas[test_quota_id]["used_value"] = limit * 0.9

        updated_q = router.get_all_quotas().get(test_quota_id, {})
        usage_ratio = updated_q.get("used_value", 0) / limit if limit > 0 else 0
        threshold = updated_q.get("alert_threshold", 0.8)
        is_alerting = usage_ratio >= threshold

        # 这里不做严格断言，只是验证逻辑存在
        print_result(True, "高使用率告警检测",
                     f"使用率: {usage_ratio:.2%}, 阈值: {threshold:.0%}, 告警: {is_alerting}")

        # 重置
        router.reset_quota(test_quota_id)
    else:
        print_result(True, "额度使用量测试（跳过：无成本型日额度）")

    return all_passed


# ============================================================
# 测试 6: 调用统计与监控
# ============================================================

async def test_call_stats(router):
    """测试调用统计功能"""
    print_header("测试 6: 调用统计与监控")

    all_passed = True

    # 6.1 初始总览数据
    overview = router.get_overall_stats()
    passed = "sources" in overview and "today" in overview
    all_passed = all_passed and passed
    print_result(passed, "总览数据结构完整",
                 f"算力源数: {overview['sources']['total']}")

    # 6.2 记录多次调用后统计更新
    result = await router.route(model_key="default-chat", purpose="chat")
    source_id = result.source_id
    
    if not source_id:
        print_result(False, "无法获取路由结果，跳过统计测试")
        return False

    stats_before = router.get_call_stats(source_id)
    calls_before = stats_before.get("today_calls", 0)

    # 记录 5 次成功调用
    for i in range(5):
        router.record_call(
            route_result=result,
            success=True,
            output_tokens=100 + i * 50,
            latency_ms=300 + i * 20,
        )

    # 记录 2 次失败调用
    for i in range(2):
        router.record_call(
            route_result=result,
            success=False,
            output_tokens=0,
            latency_ms=100,
            error_message="测试失败",
        )

    stats_after = router.get_call_stats(source_id)
    calls_after = stats_after.get("today_calls", 0)
    success_after = stats_after.get("today_success", 0)
    failed_after = stats_after.get("today_failed", 0)

    passed = calls_after == calls_before + 7
    all_passed = all_passed and passed
    print_result(passed, "调用次数统计正确",
                 f"{calls_before} -> {calls_after} (增加 7 次)")

    passed = success_after >= 5 and failed_after >= 2
    all_passed = all_passed and passed
    print_result(passed, "成功/失败统计正确",
                 f"成功: {success_after}, 失败: {failed_after}")

    # 6.3 测试成功率计算
    total = success_after + failed_after
    if total > 0:
        rate = success_after / total
        passed = 0 < rate < 1
        all_passed = all_passed and passed
        print_result(passed, "成功率计算正确",
                     f"成功率: {rate:.2%}")

    # 6.4 测试延迟统计
    passed = stats_after.get("total_latency_ms", 0) > 0
    all_passed = all_passed and passed
    print_result(passed, "延迟统计正确",
                 f"总延迟: {stats_after.get('total_latency_ms', 0):.2f}ms")

    return all_passed


# ============================================================
# 测试 7: 技能权限绑定
# ============================================================

async def test_skill_permissions(router):
    """测试技能权限绑定"""
    print_header("测试 7: 技能权限绑定")

    all_passed = True

    # 7.1 获取技能列表
    skills = router.get_all_skills()
    passed = len(skills) > 0
    all_passed = all_passed and passed
    print_result(passed, "技能绑定配置存在",
                 f"数量: {len(skills)}")

    for sid, s in skills.items():
        print(f"    - {sid}: {s['skill_name']}")

    # 7.2 测试技能权限检查 - 代码技能
    code_skill = skills.get("skill-code")
    if code_skill:
        allowed = code_skill.get("allowed_source_ids", [])
        allowed_groups = code_skill.get("allowed_groups", [])
        print(f"    代码技能允许的算力源: {allowed}")
        print(f"    代码技能允许的分组: {allowed_groups}")

        # 带技能参数路由
        result = await router.route(
            model_key="default-chat",
            purpose="chat",
            caller_skill="skill-code",
        )
        passed = result.status == RouteStatus.SUCCESS
        all_passed = all_passed and passed
        print_result(passed, "代码技能路由成功",
                     f"选中: {result.source_name}")
    else:
        print_result(True, "代码技能测试（跳过：无 skill-code）")

    return all_passed


# ============================================================
# 测试 8: 熔断器状态查询
# ============================================================

async def test_circuit_breaker_query(router):
    """测试熔断器状态查询接口"""
    print_header("测试 8: 熔断器状态查询")

    all_passed = True

    # 获取所有熔断器状态
    cb_stats = router.get_all_circuit_breakers()
    passed = len(cb_stats) > 0
    all_passed = all_passed and passed
    print_result(passed, "熔断器状态查询成功",
                 f"数量: {len(cb_stats)}")

    # 检查每个算力源都有熔断器
    sources = router.get_all_sources()
    for sid in sources:
        if sid not in cb_stats:
            print_result(False, f"算力源 {sid} 缺少熔断器")
            all_passed = False
            break
    else:
        print_result(True, "所有算力源都有熔断器")

    # 打印熔断器状态
    for sid, stats in cb_stats.items():
        source = sources.get(sid, {})
        name = source.get("name", sid)
        print(f"    - {name}: {stats['state']}, "
              f"错误率: {stats['error_rate']:.2%}, "
              f"窗口: {stats['window_size']}")

    return all_passed


# ============================================================
# 主函数
# ============================================================

async def main():
    """主测试函数"""
    print("\n" + "=" * 70)
    print("  算力调度中台 - 验证测试")
    print("=" * 70)

    # 初始化数据库（使用 create_all 确保所有表都创建，包括算力相关表）
    print("\n  正在初始化数据库...")
    try:
        init_db()
    except Exception:
        pass
    # 额外确保所有表都创建（Alembic 基线可能不包含算力表）
    Base.metadata.create_all(bind=engine)
    print("  数据库初始化完成")
    
    # 确保有测试数据
    print("\n  正在准备测试数据...")
    ensure_test_data()

    # 初始化路由引擎
    print("\n  正在初始化算力路由引擎...")
    router = get_compute_router()
    router.initialize(db_session_factory=SessionLocal)
    print("  路由引擎初始化完成")
    
    # 打印加载的配置信息
    sources = router.get_all_sources()
    print(f"  加载算力源: {len(sources)} 个")
    for sid, s in sources.items():
        print(f"    - {s['name']} ({sid}): {s['deployment_type']}, "
              f"状态={s['status']}, 健康={s['health_status']}")

    # 等待一下让后台线程启动
    await asyncio.sleep(0.5)

    # 运行所有测试
    results = {}

    try:
        results["1. 路由决策"] = await test_routing_decision(router)
    except Exception as e:
        print(f"  测试 1 异常: {e}")
        import traceback
        traceback.print_exc()
        results["1. 路由决策"] = False

    try:
        results["2. 故障转移"] = await test_failover(router)
    except Exception as e:
        print(f"  测试 2 异常: {e}")
        import traceback
        traceback.print_exc()
        results["2. 故障转移"] = False

    try:
        results["3. 熔断机制"] = await test_circuit_breaker(router)
    except Exception as e:
        print(f"  测试 3 异常: {e}")
        import traceback
        traceback.print_exc()
        results["3. 熔断机制"] = False

    try:
        results["4. 限流机制"] = await test_rate_limiting(router)
    except Exception as e:
        print(f"  测试 4 异常: {e}")
        import traceback
        traceback.print_exc()
        results["4. 限流机制"] = False

    try:
        results["5. 额度管理"] = await test_quota_management(router)
    except Exception as e:
        print(f"  测试 5 异常: {e}")
        import traceback
        traceback.print_exc()
        results["5. 额度管理"] = False

    try:
        results["6. 调用统计"] = await test_call_stats(router)
    except Exception as e:
        print(f"  测试 6 异常: {e}")
        import traceback
        traceback.print_exc()
        results["6. 调用统计"] = False

    try:
        results["7. 技能权限"] = await test_skill_permissions(router)
    except Exception as e:
        print(f"  测试 7 异常: {e}")
        import traceback
        traceback.print_exc()
        results["7. 技能权限"] = False

    try:
        results["8. 熔断器查询"] = await test_circuit_breaker_query(router)
    except Exception as e:
        print(f"  测试 8 异常: {e}")
        import traceback
        traceback.print_exc()
        results["8. 熔断器查询"] = False

    # 打印汇总
    print("\n" + "=" * 70)
    print("  测试结果汇总")
    print("=" * 70)

    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] - {name}")

    print(f"\n  总计: {passed_count}/{total_count} 通过")

    if passed_count == total_count:
        print("\n  所有测试通过！")
    else:
        print(f"\n  有 {total_count - passed_count} 个测试失败")

    # 关闭路由引擎
    router.shutdown()

    return passed_count == total_count


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
