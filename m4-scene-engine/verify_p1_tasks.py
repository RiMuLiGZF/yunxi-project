"""M4 P1 任务验证脚本.

验证三个模块的导入和基本功能：
1. 幂等性管理器
2. 数据库事务管理器
3. API 请求模型
"""

from __future__ import annotations

import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pydantic import ValidationError


def test_idempotency():
    """测试幂等性管理器."""
    print("=" * 60)
    print("【任务1】幂等性管理器测试")
    print("=" * 60)

    from src.common.idempotency import IdempotencyManager, get_idempotency_manager

    print("✓ 导入成功: IdempotencyManager, get_idempotency_manager")

    mgr = IdempotencyManager(ttl=3600, max_keys=100)
    print(f"✓ 创建实例: ttl={mgr.ttl}s, max_keys={mgr.max_keys}")

    key = "test-request-001"
    result_data = {"code": 0, "message": "success", "data": {"id": 123}}

    exists, cached = mgr.check(key)
    assert not exists, "初始状态下键不应该存在"
    assert cached is None
    print("✓ check 不存在的键返回 (False, None)")

    mgr.store(key, result_data)
    print(f"✓ store 存储键: {key}")

    exists, cached = mgr.check(key)
    assert exists, "存储后键应该存在"
    assert cached == result_data, "缓存结果应该匹配"
    print(f"✓ check 命中缓存: {cached}")

    mgr.store(key, {"other": "data"})
    exists, cached = mgr.check(key)
    assert exists
    assert cached == {"other": "data"}
    print("✓ 重复 store 会更新结果")

    assert mgr.size == 1
    print(f"✓ size 属性正确: {mgr.size}")

    mgr2 = IdempotencyManager(ttl=3600, max_keys=3)
    for i in range(5):
        mgr2.store(f"key-{i}", f"value-{i}")
    assert mgr2.size == 3
    exists, _ = mgr2.check("key-0")
    assert not exists
    print(f"✓ LRU 淘汰正确: max_keys=3, 插入5个后 size={mgr2.size}")

    mgr3 = IdempotencyManager(ttl=0, max_keys=100)
    mgr3.store("expired-key", "value")
    import time
    time.sleep(0.01)
    cleaned = mgr3.cleanup()
    assert cleaned >= 1
    print(f"✓ cleanup 清理过期键: 清理了 {cleaned} 个")

    singleton1 = get_idempotency_manager()
    singleton2 = get_idempotency_manager()
    assert singleton1 is singleton2
    print("✓ 全局单例正确")

    print("\n✅ 幂等性管理器测试通过\n")


def test_transaction():
    """测试数据库事务管理器."""
    print("=" * 60)
    print("【任务2】数据库事务管理器测试")
    print("=" * 60)

    from src.common.db_transaction import transactional, transactional_decorator

    print("✓ 导入成功: transactional, transactional_decorator")

    with transactional() as session:
        assert session is not None
        print(f"✓ transactional() 上下文管理器创建 session 成功")

    @transactional_decorator
    def sample_operation(session=None, value: int = 0):
        assert session is not None
        return {"value": value * 2}

    result = sample_operation(value=21)
    assert result == {"value": 42}
    print(f"✓ transactional_decorator 装饰器正常工作: {result}")

    try:
        with transactional() as session:
            raise ValueError("测试异常")
    except ValueError:
        print("✓ 异常时正确回滚并重新抛出")

    print("\n✅ 数据库事务管理器测试通过\n")


def test_api_requests():
    """测试 API 请求模型."""
    print("=" * 60)
    print("【任务3】API 请求模型测试")
    print("=" * 60)

    from src.models.api_requests import (
        SceneSwitchRequest,
        SceneRecognizeRequest,
        SceneConfigUpdateRequest,
        ContextSaveRequest,
        AdminConfigUpdateRequest,
        AdminSceneConfigRequest,
        McpToolConfig,
        McpToolCallRequest,
        SkillBindingConfig,
        SkillExecuteRequest,
        ModeEnterRequest,
        ModeLeaveRequest,
        ChatSendRequest,
        ChatConversationCreateRequest,
        VoiceSynthesizeRequest,
        VoiceConfigUpdateRequest,
        WatchDeviceRegisterRequest,
        WatchHealthDataSubmitRequest,
    )

    print("✓ 所有 18 个模型导入成功")

    print("\n--- 正常输入测试 ---")

    req = SceneSwitchRequest(to_scene="work_dev", from_scene="chat", trigger_type="manual")
    assert req.to_scene == "work_dev"
    print(f"✓ SceneSwitchRequest 正常: to_scene={req.to_scene}")

    req = SceneRecognizeRequest(text="你好，帮我写代码")
    assert req.text == "你好，帮我写代码"
    print("✓ SceneRecognizeRequest 正常")

    req = SceneConfigUpdateRequest(config={"enabled": True})
    print("✓ SceneConfigUpdateRequest 正常")

    req = ContextSaveRequest(context_json={"key": "value"})
    print("✓ ContextSaveRequest 正常")

    req = AdminConfigUpdateRequest(config={"log_level": "info"})
    print("✓ AdminConfigUpdateRequest 正常")

    req = AdminSceneConfigRequest(scene_id="work_dev", priority=80)
    assert req.priority == 80
    print("✓ AdminSceneConfigRequest 正常")

    cfg = McpToolConfig(name="my_tool", trigger="on_enter", required=True)
    assert cfg.name == "my_tool"
    print("✓ McpToolConfig 正常")

    req = McpToolCallRequest(arguments={"x": 1})
    print("✓ McpToolCallRequest 正常")

    cfg = SkillBindingConfig(name="vscode_control", auto_trigger=["on_enter"])
    assert cfg.auto_trigger == ["on_enter"]
    print("✓ SkillBindingConfig 正常")

    req = SkillExecuteRequest(params={"action": "run"})
    print("✓ SkillExecuteRequest 正常")

    req = ModeEnterRequest(user_id="user123")
    print("✓ ModeEnterRequest 正常")
    req = ModeLeaveRequest(user_id="user123")
    print("✓ ModeLeaveRequest 正常")

    req = ChatSendRequest(message="你好", mode="main-chat")
    assert req.message == "你好"
    print("✓ ChatSendRequest 正常")

    req = ChatConversationCreateRequest(title="新对话")
    print("✓ ChatConversationCreateRequest 正常")

    req = VoiceSynthesizeRequest(text="你好世界", speed=1.0)
    assert req.speed == 1.0
    print("✓ VoiceSynthesizeRequest 正常")

    req = VoiceConfigUpdateRequest(voice_speed=1.2, voice_pitch=0.9)
    print("✓ VoiceConfigUpdateRequest 正常")

    req = WatchDeviceRegisterRequest(device_id="watch-001", name="我的手表")
    assert req.device_id == "watch-001"
    print("✓ WatchDeviceRegisterRequest 正常")

    req = WatchHealthDataSubmitRequest(
        device_id="watch-001",
        data_type="heart_rate",
        value=72.0,
    )
    assert req.value == 72.0
    print("✓ WatchHealthDataSubmitRequest 正常")

    print("\n--- 异常输入验证测试 ---")

    try:
        SceneSwitchRequest(to_scene="INVALID")
        assert False
    except ValidationError:
        print("✓ SceneSwitchRequest 拒绝无效 to_scene (含大写)")

    try:
        SceneSwitchRequest(to_scene="chat", trigger_type="invalid")
        assert False
    except ValidationError:
        print("✓ SceneSwitchRequest 拒绝无效 trigger_type")

    try:
        SceneRecognizeRequest(text="")
        assert False
    except ValidationError:
        print("✓ SceneRecognizeRequest 拒绝空文本")

    try:
        AdminSceneConfigRequest(scene_id="chat", priority=200)
        assert False
    except ValidationError:
        print("✓ AdminSceneConfigRequest 拒绝 priority > 100")

    try:
        McpToolConfig(name="tool", trigger="invalid")
        assert False
    except ValidationError:
        print("✓ McpToolConfig 拒绝无效 trigger")

    try:
        VoiceSynthesizeRequest(text="test", speed=3.0)
        assert False
    except ValidationError:
        print("✓ VoiceSynthesizeRequest 拒绝 speed > 2.0")

    try:
        VoiceSynthesizeRequest(text="test", speed=0.1)
        assert False
    except ValidationError:
        print("✓ VoiceSynthesizeRequest 拒绝 speed < 0.5")

    try:
        WatchHealthDataSubmitRequest(device_id="d", data_type="invalid", value=1)
        assert False
    except ValidationError:
        print("✓ WatchHealthDataSubmitRequest 拒绝无效 data_type")

    try:
        WatchHealthDataSubmitRequest(device_id="d", data_type="heart_rate", value=-1)
        assert False
    except ValidationError:
        print("✓ WatchHealthDataSubmitRequest 拒绝 value < 0")

    try:
        ChatSendRequest(message="")
        assert False
    except ValidationError:
        print("✓ ChatSendRequest 拒绝空消息")

    print("\n✅ API 请求模型测试通过\n")


def test_backward_compatibility():
    """测试向后兼容性 - 从 src.models 导入."""
    print("=" * 60)
    print("【向后兼容性测试】")
    print("=" * 60)

    from src.models import (
        SceneSwitchRequest,
        SceneRecognizeRequest,
        SceneConfigUpdateRequest,
        ContextSaveRequest,
        AdminConfigUpdateRequest,
        McpToolConfig,
        McpToolCallRequest,
        SceneMcpToolsUpdateRequest,
        SkillBindingConfig,
        SkillExecuteRequest,
        SceneSkillsUpdateRequest,
    )

    print("✓ 从 src.models 导入所有原有模型成功")

    req = SceneSwitchRequest(to_scene="chat")
    assert req.to_scene == "chat"
    print("✓ SceneSwitchRequest 从 src.models 导入可用")

    req = SceneMcpToolsUpdateRequest(mcp_tools=[])
    print("✓ SceneMcpToolsUpdateRequest 保持向后兼容")

    req = SceneSkillsUpdateRequest(skills=[])
    print("✓ SceneSkillsUpdateRequest 保持向后兼容")

    print("\n✅ 向后兼容性测试通过\n")


def main():
    print("\n" + "=" * 60)
    print("  M4 场景引擎 P1 任务验证")
    print("=" * 60 + "\n")

    try:
        test_idempotency()
        test_transaction()
        test_api_requests()
        test_backward_compatibility()

        print("=" * 60)
        print("🎉 所有测试全部通过！")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
