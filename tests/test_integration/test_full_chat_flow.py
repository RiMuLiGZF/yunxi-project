"""
端到端集成测试 - 完整对话流程

测试从用户发起到系统响应的完整流程，
包括意图识别、技能调用、记忆存储等。
纯逻辑测试，使用模拟数据。
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class MockChatFlow:
    """模拟完整对话流程"""

    def __init__(self):
        self.memory = []
        self.conversation_id = "conv_test_001"
        self.user_id = "user_test"

    def process_message(self, message: str) -> Dict[str, Any]:
        """处理用户消息的完整流程"""
        # 1. 输入验证
        if not message or not message.strip():
            return {"success": False, "error": "消息不能为空"}

        # 2. 意图识别（模拟）
        intent = self._classify_intent(message)

        # 3. 技能匹配
        skill = self._match_skill(intent)

        # 4. 执行技能
        result = self._execute_skill(skill, message)

        # 5. 存储记忆
        self._store_memory(message, result, intent)

        # 6. 生成回复
        reply = self._generate_reply(result, intent)

        return {
            "success": True,
            "conversation_id": self.conversation_id,
            "message": reply,
            "intent": intent,
            "skill": skill,
            "memory_stored": True,
        }

    def _classify_intent(self, message: str) -> str:
        """模拟意图识别"""
        msg = message.lower()
        if "天气" in message:
            return "weather_query"
        elif "日程" in message or "安排" in message:
            return "schedule_manage"
        elif "翻译" in message:
            return "translation"
        elif "记得" in message or "记住" in message:
            return "memory_store"
        elif "代码" in message or "编程" in message:
            return "code_generation"
        else:
            return "general_chat"

    def _match_skill(self, intent: str) -> str:
        """模拟技能匹配"""
        skill_map = {
            "weather_query": "weather_skill",
            "schedule_manage": "calendar_skill",
            "translation": "translate_skill",
            "memory_store": "memory_skill",
            "code_generation": "code_skill",
            "general_chat": "chat_skill",
        }
        return skill_map.get(intent, "chat_skill")

    def _execute_skill(self, skill: str, message: str) -> Dict[str, Any]:
        """模拟技能执行"""
        return {
            "skill": skill,
            "status": "success",
            "output": f"执行{skill}的结果",
        }

    def _store_memory(self, message: str, result: Dict, intent: str):
        """存储对话记忆"""
        self.memory.append({
            "role": "user",
            "content": message,
            "intent": intent,
        })
        self.memory.append({
            "role": "assistant",
            "content": result.get("output", ""),
        })

    def _generate_reply(self, result: Dict, intent: str) -> str:
        """生成回复"""
        return f"[{intent}] {result.get('output', '处理完成')}"

    def get_conversation_history(self) -> list:
        """获取对话历史"""
        return self.memory.copy()


class TestFullChatFlow:
    """完整对话流程集成测试"""

    @pytest.fixture
    def chat(self):
        return MockChatFlow()

    # ============================================================
    # 基本对话流程
    # ============================================================

    @pytest.mark.integration
    @pytest.mark.smoke
    def test_basic_chat_flow(self, chat):
        """测试基本对话流程"""
        result = chat.process_message("你好")
        assert result["success"] is True
        assert result["conversation_id"] == "conv_test_001"
        assert "message" in result

    @pytest.mark.integration
    def test_empty_message_rejected(self, chat):
        """测试空消息被拒绝"""
        result = chat.process_message("")
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.integration
    def test_whitespace_message_rejected(self, chat):
        """测试纯空格消息被拒绝"""
        result = chat.process_message("   ")
        assert result["success"] is False

    # ============================================================
    # 意图识别测试
    # ============================================================

    @pytest.mark.integration
    def test_weather_intent(self, chat):
        """测试天气意图识别"""
        result = chat.process_message("今天天气怎么样")
        assert result["intent"] == "weather_query"
        assert result["skill"] == "weather_skill"

    @pytest.mark.integration
    def test_schedule_intent(self, chat):
        """测试日程意图识别"""
        result = chat.process_message("帮我安排明天的日程")
        assert result["intent"] == "schedule_manage"

    @pytest.mark.integration
    def test_translation_intent(self, chat):
        """测试翻译意图识别"""
        result = chat.process_message("帮我翻译这段话")
        assert result["intent"] == "translation"

    @pytest.mark.integration
    def test_general_chat_intent(self, chat):
        """测试通用聊天意图"""
        result = chat.process_message("你好呀")
        assert result["intent"] == "general_chat"

    # ============================================================
    # 记忆存储测试
    # ============================================================

    @pytest.mark.integration
    def test_memory_stored_after_chat(self, chat):
        """测试对话后记忆被存储"""
        chat.process_message("你好")
        history = chat.get_conversation_history()
        assert len(history) >= 2  # 用户 + 助手
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    @pytest.mark.integration
    def test_multiple_turns_memory(self, chat):
        """测试多轮对话记忆累积"""
        chat.process_message("第一句")
        chat.process_message("第二句")
        chat.process_message("第三句")
        history = chat.get_conversation_history()
        assert len(history) == 6  # 3轮 * 2（用户+助手）

    # ============================================================
    # 完整流程集成
    # ============================================================

    @pytest.mark.integration
    def test_full_flow_pipeline(self, chat):
        """测试完整流程流水线"""
        result = chat.process_message("帮我写段代码")
        # 验证流程各阶段都有结果
        assert result["intent"] is not None
        assert result["skill"] is not None
        assert result["memory_stored"] is True
        assert result["message"] is not None

    @pytest.mark.integration
    def test_conversation_id_consistent(self, chat):
        """测试会话ID一致性"""
        r1 = chat.process_message("第一句")
        r2 = chat.process_message("第二句")
        assert r1["conversation_id"] == r2["conversation_id"]
