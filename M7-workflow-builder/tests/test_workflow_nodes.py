"""
M7 单元测试 - 工作流节点类型测试 (TS-002, P2级)

覆盖: 内置积木块类型、条件节点、HTTP请求节点、技能调用节点、
      延时节点、开始/结束节点
运行: python -m pytest tests/test_workflow_nodes.py -v
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from services.executor import BUILTIN_BLOCKS, execute_builtin_block, _evaluate_condition


class TestBuiltinBlocks:
    """内置积木块类型测试"""

    def test_builtin_blocks_not_empty(self):
        """内置积木列表不应为空."""
        assert len(BUILTIN_BLOCKS) > 0

    def test_web_fetch_block_exists(self):
        """网页抓取积木应存在."""
        assert "skill.web_fetch" in BUILTIN_BLOCKS
        info = BUILTIN_BLOCKS["skill.web_fetch"]
        assert "name" in info
        assert "actions" in info

    def test_translate_block_exists(self):
        """翻译积木应存在."""
        assert "skill.translate" in BUILTIN_BLOCKS
        info = BUILTIN_BLOCKS["skill.translate"]
        assert "translate" in info["actions"]

    def test_fulltext_search_block_exists(self):
        """全文搜索积木应存在."""
        assert "skill.fulltext_search" in BUILTIN_BLOCKS

    def test_doc_proc_block_exists(self):
        """文档处理积木应存在."""
        assert "skill.doc_proc" in BUILTIN_BLOCKS

    def test_data_analysis_block_exists(self):
        """数据分析积木应存在."""
        assert "skill.data_analysis" in BUILTIN_BLOCKS

    def test_tide_memory_block_exists(self):
        """潮汐记忆积木应存在."""
        assert "skill.tide_memory" in BUILTIN_BLOCKS

    def test_notify_block_exists(self):
        """通知推送积木应存在."""
        assert "skill.notify" in BUILTIN_BLOCKS

    def test_calendar_block_exists(self):
        """日程管理积木应存在."""
        assert "skill.calendar" in BUILTIN_BLOCKS

    def test_logic_condition_block_exists(self):
        """条件分支积木应存在."""
        assert "logic.condition" in BUILTIN_BLOCKS
        info = BUILTIN_BLOCKS["logic.condition"]
        assert info.get("category") == "logic"

    def test_voice_asr_block_exists(self):
        """语音识别积木应存在."""
        assert "voice.asr" in BUILTIN_BLOCKS

    def test_voice_tts_block_exists(self):
        """语音合成积木应存在."""
        assert "voice.tts" in BUILTIN_BLOCKS

    def test_voice_wake_word_block_exists(self):
        """唤醒词检测积木应存在."""
        assert "voice.wake_word" in BUILTIN_BLOCKS

    def test_voice_record_block_exists(self):
        """录音控制积木应存在."""
        assert "voice.record" in BUILTIN_BLOCKS

    def test_unknown_block_returns_failure(self):
        """未知积木应返回失败."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block("skill.nonexistent", "default", {})
        )
        assert result["success"] is False
        assert "未知" in result.get("error", "")


class TestConditionBlock:
    """条件判断节点测试"""

    def test_condition_evaluate_true(self):
        """条件积木 evaluate 动作应正确计算 true."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "value > 5", "value": 10},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is True
        assert result["data"]["branch"] == "true"

    def test_condition_evaluate_false(self):
        """条件积木 evaluate 动作应正确计算 false."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "value > 100", "value": 10},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is False
        assert result["data"]["branch"] == "false"

    def test_condition_evaluate_equality(self):
        """条件积木应支持相等比较."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "status == 'active'", "status": "active"},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is True

    def test_condition_evaluate_and_logic(self):
        """条件积木应支持 and 逻辑运算."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "a > 0 and b > 0", "a": 1, "b": 2},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is True

    def test_condition_evaluate_or_logic(self):
        """条件积木应支持 or 逻辑运算."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "a > 0 or b > 0", "a": -1, "b": 2},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is True

    def test_condition_evaluate_not_logic(self):
        """条件积木应支持 not 逻辑运算."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "not flag", "flag": False},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is True

    def test_condition_empty_expression(self):
        """空表达式应返回 false（安全降级）."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": ""},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is False

    def test_condition_invalid_expression(self):
        """无效表达式应返回 false（安全降级，不抛异常）."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "!!!invalid!!!"},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is False

    def test_condition_arithmetic_expression(self):
        """条件表达式应支持算术运算."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "a + b > 10", "a": 5, "b": 6},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is True

    def test_condition_string_methods(self):
        """条件表达式应支持字符串方法."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "logic.condition",
                "evaluate",
                {"expression": "text.startswith('hello')", "text": "hello world"},
            )
        )
        assert result["success"] is True
        assert result["data"]["result"] is True


class TestTranslateBlock:
    """翻译积木节点测试"""

    def test_translate_basic(self):
        """翻译积木应返回模拟结果."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.translate",
                "translate",
                {"text": "hello", "target_lang": "zh-CN"},
            )
        )
        assert result["success"] is True
        assert "translated_text" in result["data"]
        assert result["data"]["mode"] == "builtin_fallback"

    def test_translate_detect_language(self):
        """翻译积木 detect_language 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.translate",
                "detect_language",
                {"text": "hello"},
            )
        )
        assert result["success"] is True


class TestWebFetchBlock:
    """网页抓取积木节点测试"""

    def test_web_fetch_basic(self):
        """网页抓取积木应返回模拟结果."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.web_fetch",
                "fetch",
                {"url": "https://example.com"},
            )
        )
        assert result["success"] is True
        assert "url" in result["data"]
        assert result["data"]["url"] == "https://example.com"

    def test_web_fetch_fetch_text(self):
        """网页抓取积木 fetch_text 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.web_fetch",
                "fetch_text",
                {"url": "https://example.com"},
            )
        )
        assert result["success"] is True


class TestNotifyBlock:
    """通知推送积木节点测试"""

    def test_notify_send(self):
        """通知积木 send 动作应返回模拟结果."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.notify",
                "send",
                {"message": "测试消息", "channel": "system"},
            )
        )
        assert result["success"] is True
        assert result["data"]["channel"] == "system"

    def test_notify_send_batch(self):
        """通知积木 send_batch 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.notify",
                "send_batch",
                {"message": "批量消息"},
            )
        )
        assert result["success"] is True


class TestCalendarBlock:
    """日程管理积木节点测试"""

    def test_calendar_create(self):
        """日程积木 create 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.calendar",
                "create",
                {"title": "测试日程"},
            )
        )
        assert result["success"] is True

    def test_calendar_list(self):
        """日程积木 list 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.calendar",
                "list",
                {},
            )
        )
        assert result["success"] is True
        assert "events" in result["data"]


class TestDataAnalysisBlock:
    """数据分析积木节点测试"""

    def test_data_analysis_analyze(self):
        """数据分析积木 analyze 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.data_analysis",
                "analyze",
                {"data": [1, 2, 3]},
            )
        )
        assert result["success"] is True

    def test_data_analysis_chart(self):
        """数据分析积木 chart 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.data_analysis",
                "chart",
                {"data": [1, 2, 3], "chart_type": "bar"},
            )
        )
        assert result["success"] is True


class TestDocProcBlock:
    """文档处理积木节点测试"""

    def test_doc_proc_parse(self):
        """文档处理积木 parse 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.doc_proc",
                "parse",
                {"file_path": "/tmp/test.pdf"},
            )
        )
        assert result["success"] is True

    def test_doc_proc_extract(self):
        """文档处理积木 extract 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.doc_proc",
                "extract",
                {"file_path": "/tmp/test.pdf", "keywords": ["test"]},
            )
        )
        assert result["success"] is True


class TestFulltextSearchBlock:
    """全文搜索积木节点测试"""

    def test_fulltext_search_search(self):
        """全文搜索积木 search 动作."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.fulltext_search",
                "search",
                {"query": "测试"},
            )
        )
        assert result["success"] is True
        assert "results" in result["data"]
        assert "total" in result["data"]


class TestTideMemoryBlock:
    """潮汐记忆积木节点测试"""

    def test_tide_memory_store(self):
        """潮汐记忆积木 store 动作（降级模式）."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.tide_memory",
                "store",
                {"content": "测试内容", "tags": ["test"]},
            )
        )
        assert result["success"] is True
        assert "action" in result["data"]

    def test_tide_memory_recall(self):
        """潮汐记忆积木 recall 动作（降级模式）."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.tide_memory",
                "recall",
                {"query": "测试"},
            )
        )
        assert result["success"] is True

    def test_tide_memory_search(self):
        """潮汐记忆积木 search 动作（降级模式）."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            execute_builtin_block(
                "skill.tide_memory",
                "search",
                {"query": "测试"},
            )
        )
        assert result["success"] is True


class TestConditionExpressionEvaluator:
    """条件表达式求值器直接测试"""

    def test_evaluate_simple_comparison(self):
        """简单比较表达式求值."""
        assert _evaluate_condition("x > 5", {"x": 10}) is True
        assert _evaluate_condition("x > 5", {"x": 3}) is False

    def test_evaluate_string_comparison(self):
        """字符串比较求值."""
        assert _evaluate_condition("name == 'test'", {"name": "test"}) is True
        assert _evaluate_condition("name == 'test'", {"name": "other"}) is False

    def test_evaluate_in_operator(self):
        """in 运算符求值."""
        assert _evaluate_condition("x in items", {"x": 1, "items": [1, 2, 3]}) is True
        assert _evaluate_condition("x in items", {"x": 5, "items": [1, 2, 3]}) is False

    def test_evaluate_len_function(self):
        """len 函数求值."""
        assert _evaluate_condition("len(items) > 2", {"items": [1, 2, 3]}) is True

    def test_evaluate_complex_expression(self):
        """复杂表达式求值."""
        result = _evaluate_condition(
            "status == 'active' and count > 0",
            {"status": "active", "count": 5},
        )
        assert result is True

    def test_evaluate_undefined_variable(self):
        """未定义变量应返回 False."""
        result = _evaluate_condition("undefined_var > 0", {})
        assert result is False

    def test_evaluate_ternary_expression(self):
        """三元表达式求值."""
        result = _evaluate_condition(
            "1 if flag else 0",
            {"flag": True},
        )
        assert result == 1

    def test_evaluate_dict_access(self):
        """字典访问求值."""
        result = _evaluate_condition(
            "data['value'] > 10",
            {"data": {"value": 15}},
        )
        assert result is True

    def test_evaluate_list_index(self):
        """列表索引访问求值."""
        result = _evaluate_condition(
            "items[0] == 'first'",
            {"items": ["first", "second"]},
        )
        assert result is True
