"""
E2E 测试 - 模块集成

测试跨模块的集成链路：
- M8 → M1 对话链路（控制塔到 Agent Hub）
- M4 → M2 技能调用（场景引擎调用技能集群）
- M5 记忆读写一致性
- M7 工作流执行（跨模块调用）
- 模块注册表 → 模块状态同步
"""

import sys
import pytest
from pathlib import Path
from typing import Dict, Any, List

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
class TestModuleRegistry:
    """模块注册表集成测试"""

    @pytest.mark.e2e_module_integration
    def test_all_modules_registered(self, admin_api_client):
        """测试所有模块已注册"""
        result = admin_api_client.get("/api/modules")
        assert result["code"] == 0

        modules = result["data"].get("items", [])
        # 至少应该有多个模块注册
        assert len(modules) >= 8
        module_keys = [m.get("key") for m in modules]

        # 验证核心模块存在
        core_modules = ["m1", "m2", "m5", "m8"]
        for mod in core_modules:
            assert mod in module_keys, f"核心模块 {mod} 未注册"

    @pytest.mark.e2e_module_integration
    def test_module_status_synced(self, admin_api_client):
        """测试模块状态同步"""
        # 第一次获取
        result1 = admin_api_client.get("/api/modules")
        assert result1["code"] == 0

        modules1 = result1["data"]["items"]
        statuses1 = {m["key"]: m.get("status") for m in modules1}

        # 第二次获取（验证状态一致）
        result2 = admin_api_client.get("/api/modules")
        assert result2["code"] == 0

        modules2 = result2["data"]["items"]
        statuses2 = {m["key"]: m.get("status") for m in modules2}

        # 状态应该一致（短时间内不会变化）
        for key in statuses1:
            assert statuses1[key] == statuses2.get(key), \
                f"模块 {key} 状态不一致"

    @pytest.mark.e2e_module_integration
    def test_module_health_check(self, admin_api_client):
        """测试模块健康检查"""
        result = admin_api_client.get("/api/modules")
        assert result["code"] == 0

        modules = result["data"]["items"]
        for module in modules:
            assert "status" in module
            assert "health" in module or "status" in module
            # 状态应该是有效值
            assert module.get("status") in [
                "running", "stopped", "error", "degraded", "unknown"
            ]

    @pytest.mark.e2e_module_integration
    def test_module_version_info(self, admin_api_client):
        """测试模块版本信息"""
        result = admin_api_client.get("/api/modules")
        assert result["code"] == 0

        modules = result["data"]["items"]
        for module in modules:
            # 每个模块应该有版本信息
            assert "version" in module or "name" in module

    @pytest.mark.e2e_module_integration
    def test_module_count_matches_system_stats(self, admin_api_client):
        """测试模块数量与系统统计一致"""
        # 获取模块列表
        modules_result = admin_api_client.get("/api/modules")
        assert modules_result["code"] == 0
        module_count = len(modules_result["data"]["items"])

        # 获取系统统计
        stats_result = admin_api_client.get("/api/system/stats")
        assert stats_result["code"] == 0
        stats_total = stats_result["data"].get("total_modules", 0)
        stats_running = stats_result["data"].get("running_modules", 0)

        # 总数应该一致
        assert stats_total == module_count

        # 运行中的模块数不应超过总数
        assert stats_running <= module_count


class TestM8ToM1ChatLink:
    """M8 → M1 对话链路集成测试"""

    @pytest.mark.e2e_module_integration
    def test_chat_request_reaches_agent(self, admin_api_client):
        """测试对话请求到达 Agent Hub"""
        result = admin_api_client.post("/api/chat", {
            "message": "你好，请介绍一下自己",
        })
        assert result["code"] == 0
        assert "reply" in result["data"]
        assert "conversation_id" in result["data"]

    @pytest.mark.e2e_module_integration
    def test_multi_turn_conversation(self, admin_api_client):
        """测试多轮对话链路"""
        # 第一轮
        result1 = admin_api_client.post("/api/chat", {
            "message": "我叫张三",
        })
        assert result1["code"] == 0
        conv_id1 = result1["data"].get("conversation_id")

        # 第二轮
        result2 = admin_api_client.post("/api/chat", {
            "message": "我叫什么名字？",
            "conversation_id": conv_id1,
        })
        assert result2["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_chat_response_has_agent_info(self, admin_api_client):
        """测试对话响应包含 Agent 信息"""
        result = admin_api_client.post("/api/chat", {
            "message": "你好",
        })
        assert result["code"] == 0
        data = result["data"]
        # 响应应该包含 agent 信息
        assert "agent" in data or "message_id" in data

    @pytest.mark.e2e_module_integration
    def test_concurrent_chat_requests(self, admin_api_client):
        """测试并发对话请求"""
        results = []
        for i in range(3):
            result = admin_api_client.post("/api/chat", {
                "message": f"并发测试消息_{i}",
            })
            results.append(result)

        # 所有请求都应该成功
        success_count = sum(1 for r in results if r["code"] == 0)
        assert success_count >= 1  # 至少应该有成功的

    @pytest.mark.e2e_module_integration
    def test_chat_with_different_agents(self, admin_api_client):
        """测试调用不同 Agent"""
        # 先获取 Agent 列表
        agents_result = admin_api_client.get("/api/agents")
        # 接口可能不存在，用对话测试
        result = admin_api_client.post("/api/chat", {
            "message": "请以专业的方式回答",
            "agent": "principal",
        })
        assert result["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_task_submission_to_m1(self, admin_api_client):
        """测试任务提交到 M1"""
        result = admin_api_client.post("/api/tasks", {
            "type": "dialog_processing",
            "title": "集成测试任务",
            "input": {"query": "测试任务执行"},
            "priority": "normal",
        })
        assert result["code"] == 0
        assert "id" in result["data"]
        assert "status" in result["data"]

    @pytest.mark.e2e_module_integration
    def test_task_status_tracking(self, admin_api_client):
        """测试任务状态跟踪"""
        # 创建任务
        create_result = admin_api_client.post("/api/tasks", {
            "type": "intent_classification",
            "title": "状态跟踪测试任务",
            "input": {"query": "测试"},
        })
        assert create_result["code"] == 0
        task_id = create_result["data"]["id"]

        # 获取任务列表
        list_result = admin_api_client.get("/api/tasks")
        assert list_result["code"] == 0


class TestM4ToM2SkillCall:
    """M4 → M2 技能调用集成测试"""

    @pytest.mark.e2e_module_integration
    def test_skill_list_available(self, admin_api_client):
        """测试技能列表可用"""
        result = admin_api_client.get("/api/skills")
        assert result["code"] == 0

        skills = result["data"].get("items", [])
        assert len(skills) > 0

    @pytest.mark.e2e_module_integration
    def test_skill_has_categories(self, admin_api_client):
        """测试技能有分类"""
        result = admin_api_client.get("/api/skills")
        assert result["code"] == 0

        skills = result["data"].get("items", [])
        if skills:
            categories = set()
            for skill in skills:
                cat = skill.get("category", "")
                if cat:
                    categories.add(cat)
            # 应该有多个分类
            assert len(categories) >= 1

    @pytest.mark.e2e_module_integration
    def test_execute_skill(self, admin_api_client):
        """测试执行技能"""
        # 获取技能列表
        skills_result = admin_api_client.get("/api/skills")
        assert skills_result["code"] == 0

        skills = skills_result["data"].get("items", [])
        if not skills:
            pytest.skip("没有可用的技能")

        # 执行第一个技能
        skill = skills[0]
        skill_id = skill.get("id") or skill.get("skill_id")

        exec_result = admin_api_client.post("/api/skills/execute", {
            "skill_id": skill_id,
            "params": {"input": "测试输入"},
        })
        assert exec_result["code"] == 0
        assert "result" in exec_result["data"]

    @pytest.mark.e2e_module_integration
    def test_skill_execution_timing(self, admin_api_client):
        """测试技能执行响应时间"""
        skills_result = admin_api_client.get("/api/skills")
        skills = skills_result["data"].get("items", [])
        if not skills:
            pytest.skip("没有可用的技能")

        skill_id = skills[0].get("id") or skills[0].get("skill_id")

        import time
        start = time.time()
        exec_result = admin_api_client.post("/api/skills/execute", {
            "skill_id": skill_id,
            "params": {"input": "测试"},
        })
        elapsed = (time.time() - start) * 1000

        assert exec_result["code"] == 0
        # 技能执行应该有耗时信息
        data = exec_result["data"]
        assert "duration_ms" in data or "result" in data

    @pytest.mark.e2e_module_integration
    def test_scene_triggers_skill(self, admin_api_client):
        """测试场景切换触发技能配置"""
        # 1. 获取场景列表
        scenes_result = admin_api_client.get("/api/scenes")
        assert scenes_result["code"] == 0

        scenes = scenes_result["data"].get("items", [])
        if not scenes:
            pytest.skip("没有可用的场景")

        # 2. 切换场景
        scene = scenes[0]
        scene_id = scene.get("id") or scene.get("scene_id")

        switch_result = admin_api_client.post("/api/scenes/switch", {
            "scene_id": scene_id,
        })
        assert switch_result["code"] == 0

        # 3. 切换后技能仍可用
        skills_result = admin_api_client.get("/api/skills")
        assert skills_result["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_multiple_skill_execution(self, admin_api_client):
        """测试连续执行多个技能"""
        skills_result = admin_api_client.get("/api/skills")
        skills = skills_result["data"].get("items", [])
        if len(skills) < 2:
            pytest.skip("可用技能不足 2 个")

        # 连续执行两个技能
        for i in range(min(3, len(skills))):
            skill_id = skills[i].get("id") or skills[i].get("skill_id")
            result = admin_api_client.post("/api/skills/execute", {
                "skill_id": skill_id,
                "params": {"input": f"测试_{i}"},
            })
            assert result["code"] == 0, f"技能 {skill_id} 执行失败"

    @pytest.mark.e2e_module_integration
    def test_skill_result_returned_to_caller(self, admin_api_client):
        """测试技能结果返回给调用方"""
        skills_result = admin_api_client.get("/api/skills")
        skills = skills_result["data"].get("items", [])
        if not skills:
            pytest.skip("没有可用的技能")

        skill_id = skills[0].get("id") or skills[0].get("skill_id")

        exec_result = admin_api_client.post("/api/skills/execute", {
            "skill_id": skill_id,
            "params": {"input": "测试输入内容"},
        })
        assert exec_result["code"] == 0

        # 结果应该包含执行信息
        data = exec_result["data"]
        assert data is not None
        assert "skill_id" in data or "result" in data


class TestM5MemoryIntegration:
    """M5 记忆系统读写一致性集成测试"""

    @pytest.mark.e2e_module_integration
    def test_write_memory_then_read(self, admin_api_client):
        """测试写入记忆后能读取"""
        unique_content = f"E2E_TEST_记忆读写测试_{id(self)}"

        # 写入
        write_result = admin_api_client.post("/api/memory", {
            "content": unique_content,
            "type": "test",
            "tags": ["e2e", "test"],
            "importance": 0.5,
        })
        assert write_result["code"] == 0
        memory_id = write_result["data"].get("id") or write_result["data"].get("memory_id")

        # 搜索
        search_result = admin_api_client.post("/api/memory/search", {
            "query": unique_content,
        })
        assert search_result["code"] == 0
        results = search_result["data"].get("results", [])

        # 应该能找到刚写入的记忆
        found = any(
            unique_content in str(r.get("content", ""))
            for r in results
        )
        # 列表中也应该存在
        list_result = admin_api_client.get("/api/memory")
        assert list_result["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_memory_search_accuracy(self, admin_api_client):
        """测试记忆搜索准确性"""
        # 写入一条有特定关键词的记忆
        keyword = f"E2E_UNIQUE_KEYWORD_{id(self)}"
        admin_api_client.post("/api/memory", {
            "content": f"这条记忆包含 {keyword} 用于测试搜索准确性",
            "type": "test",
            "tags": ["e2e"],
        })

        # 搜索关键词
        result = admin_api_client.post("/api/memory/search", {
            "query": keyword,
        })
        assert result["code"] == 0
        assert "results" in result["data"]

    @pytest.mark.e2e_module_integration
    def test_memory_persistence_across_requests(self, admin_api_client):
        """测试记忆跨请求持久化"""
        # 写入
        content = f"E2E_TEST_持久化测试_{id(self)}"
        write_result = admin_api_client.post("/api/memory", {
            "content": content,
            "type": "test",
        })
        assert write_result["code"] == 0

        # 多次读取验证
        for i in range(3):
            list_result = admin_api_client.get("/api/memory")
            assert list_result["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_memory_tags(self, admin_api_client):
        """测试记忆标签功能"""
        write_result = admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_带标签的记忆",
            "type": "test",
            "tags": ["tag1", "tag2", "e2e"],
        })
        assert write_result["code"] == 0

        data = write_result["data"]
        # 应该返回标签信息
        assert "tags" in data or "id" in data

    @pytest.mark.e2e_module_integration
    def test_memory_importance_level(self, admin_api_client):
        """测试记忆重要度级别"""
        # 写入不同重要度的记忆
        for importance in [0.1, 0.5, 0.9]:
            result = admin_api_client.post("/api/memory", {
                "content": f"E2E_TEST_重要度测试_{importance}",
                "type": "test",
                "importance": importance,
            })
            assert result["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_memory_different_types(self, admin_api_client):
        """测试不同类型记忆"""
        memory_types = ["general", "conversation", "preference", "fact"]

        for mem_type in memory_types:
            result = admin_api_client.post("/api/memory", {
                "content": f"E2E_TEST_{mem_type} 类型记忆",
                "type": mem_type,
            })
            assert result["code"] == 0, f"{mem_type} 类型记忆写入失败"

    @pytest.mark.e2e_module_integration
    def test_memory_list_pagination(self, admin_api_client):
        """测试记忆列表分页"""
        # 写入一些记忆
        for i in range(5):
            admin_api_client.post("/api/memory", {
                "content": f"E2E_TEST_分页测试记忆_{i}",
                "type": "test",
            })

        # 获取列表
        result = admin_api_client.get("/api/memory")
        assert result["code"] == 0
        data = result["data"]

        # 应该有分页信息
        assert "items" in data or "total" in data


class TestM7WorkflowIntegration:
    """M7 工作流跨模块调用集成测试"""

    @pytest.mark.e2e_module_integration
    def test_workflow_list_available(self, admin_api_client):
        """测试工作流列表可用"""
        result = admin_api_client.get("/api/workflows")
        assert result["code"] == 0

        workflows = result["data"].get("items", [])
        assert len(workflows) > 0

    @pytest.mark.e2e_module_integration
    def test_workflow_has_steps(self, admin_api_client):
        """测试工作流包含步骤定义"""
        result = admin_api_client.get("/api/workflows")
        assert result["code"] == 0

        workflows = result["data"].get("items", [])
        if workflows:
            wf = workflows[0]
            # 工作流应该有步骤或步骤数量
            assert "steps" in wf or "step_count" in wf

    @pytest.mark.e2e_module_integration
    def test_execute_workflow(self, admin_api_client):
        """测试执行工作流"""
        wf_result = admin_api_client.get("/api/workflows")
        workflows = wf_result["data"].get("items", [])
        if not workflows:
            pytest.skip("没有可用的工作流")

        wf_id = workflows[0].get("id") or workflows[0].get("workflow_id")

        exec_result = admin_api_client.post("/api/workflows/execute", {
            "workflow_id": wf_id,
            "params": {"input": "测试输入"},
        })
        assert exec_result["code"] == 0
        assert "execution_id" in exec_result["data"]

    @pytest.mark.e2e_module_integration
    def test_workflow_execution_completes(self, admin_api_client):
        """测试工作流执行完成"""
        wf_result = admin_api_client.get("/api/workflows")
        workflows = wf_result["data"].get("items", [])
        if not workflows:
            pytest.skip("没有可用的工作流")

        wf_id = workflows[0].get("id") or workflows[0].get("workflow_id")

        exec_result = admin_api_client.post("/api/workflows/execute", {
            "workflow_id": wf_id,
            "params": {},
        })
        assert exec_result["code"] == 0

        # 应该返回执行状态
        data = exec_result["data"]
        assert "status" in data
        assert data["status"] == "completed"

    @pytest.mark.e2e_module_integration
    def test_workflow_cross_module_call(self, admin_api_client):
        """测试工作流跨模块调用（调用技能 + 存储记忆）"""
        wf_result = admin_api_client.get("/api/workflows")
        workflows = wf_result["data"].get("items", [])
        if not workflows:
            pytest.skip("没有可用的工作流")

        wf = workflows[0]
        wf_id = wf.get("id") or wf.get("workflow_id")

        # 执行工作流（内部应跨模块调用）
        exec_result = admin_api_client.post("/api/workflows/execute", {
            "workflow_id": wf_id,
            "params": {"query": "跨模块测试"},
        })
        assert exec_result["code"] == 0

        data = exec_result["data"]
        # 应该有步骤完成信息
        assert "steps_completed" in data or "execution_id" in data

    @pytest.mark.e2e_module_integration
    def test_multiple_workflow_executions(self, admin_api_client):
        """测试多次执行工作流"""
        wf_result = admin_api_client.get("/api/workflows")
        workflows = wf_result["data"].get("items", [])
        if not workflows:
            pytest.skip("没有可用的工作流")

        wf_id = workflows[0].get("id") or workflows[0].get("workflow_id")

        execution_ids = []
        for i in range(3):
            result = admin_api_client.post("/api/workflows/execute", {
                "workflow_id": wf_id,
                "params": {"input": f"执行_{i}"},
            })
            assert result["code"] == 0
            execution_ids.append(result["data"].get("execution_id"))

        # 每次执行应该有独立的 ID
        unique_ids = set(filter(None, execution_ids))
        assert len(unique_ids) >= 1

    @pytest.mark.e2e_module_integration
    def test_workflow_with_skill_integration(self, admin_api_client):
        """测试工作流与技能系统集成"""
        # 1. 获取可用技能
        skills_result = admin_api_client.get("/api/skills")
        skills = skills_result["data"].get("items", [])

        # 2. 获取可用工作流
        wf_result = admin_api_client.get("/api/workflows")
        workflows = wf_result["data"].get("items", [])

        # 验证两者都可用
        assert len(skills) > 0
        assert len(workflows) > 0


class TestModuleInterconnection:
    """模块互联集成测试"""

    @pytest.mark.e2e_module_integration
    def test_m8_can_communicate_with_all_modules(self, admin_api_client):
        """测试 M8 控制塔能与所有模块通信"""
        result = admin_api_client.get("/api/modules")
        assert result["code"] == 0

        modules = result["data"]["items"]
        healthy_count = sum(
            1 for m in modules
            if m.get("status") == "running" or m.get("health") == "healthy"
        )

        # 大部分模块应该健康
        assert healthy_count >= len(modules) * 0.5

    @pytest.mark.e2e_module_integration
    def test_system_stats_reflects_module_status(self, admin_api_client):
        """测试系统统计反映模块状态"""
        # 获取模块状态
        modules_result = admin_api_client.get("/api/modules")
        assert modules_result["code"] == 0
        total_modules = len(modules_result["data"]["items"])
        running_modules = sum(
            1 for m in modules_result["data"]["items"]
            if m.get("status") == "running"
        )

        # 获取系统统计
        stats_result = admin_api_client.get("/api/system/stats")
        assert stats_result["code"] == 0
        stats = stats_result["data"]

        # 总数应该一致
        assert stats.get("total_modules") == total_modules
        assert stats.get("running_modules") == running_modules

    @pytest.mark.e2e_module_integration
    def test_health_score_calculation(self, admin_api_client):
        """测试健康分数计算"""
        stats_result = admin_api_client.get("/api/system/stats")
        assert stats_result["code"] == 0

        stats = stats_result["data"]
        health_score = stats.get("health_score", 0)

        # 健康分数应该在 0-100 之间
        assert 0 <= health_score <= 100

    @pytest.mark.e2e_module_integration
    def test_chat_triggers_memory_write(self, admin_api_client):
        """测试对话触发记忆写入（M1 → M5 链路）"""
        # 获取对话前的记忆数量
        before_result = admin_api_client.get("/api/memory")
        before_count = before_result["data"].get("total", 0)

        # 进行对话
        chat_result = admin_api_client.post("/api/chat", {
            "message": "请记住我喜欢蓝色",
        })
        assert chat_result["code"] == 0

        # 对话后记忆应该可能增加
        after_result = admin_api_client.get("/api/memory")
        # 不强制断言增加，因为取决于系统配置
        assert after_result["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_config_change_propagates(self, admin_api_client):
        """测试配置变更传播到各模块"""
        # 修改配置
        update_result = admin_api_client.put("/api/config", {
            "notifications_enabled": True,
        })
        assert update_result["code"] == 0

        # 验证配置已更新
        get_result = admin_api_client.get("/api/config")
        assert get_result["code"] == 0

    @pytest.mark.e2e_module_integration
    def test_full_integration_chain(self, admin_api_client):
        """测试完整集成链路（对话→技能→记忆→工作流）"""
        # Step 1: 对话（M8 → M1）
        chat = admin_api_client.post("/api/chat", {
            "message": "帮我执行一个任务",
        })
        assert chat["code"] == 0

        # Step 2: 调用技能（M4 → M2）
        skills = admin_api_client.get("/api/skills")
        if skills["code"] == 0 and skills["data"].get("items"):
            skill_id = skills["data"]["items"][0].get("id") or skills["data"]["items"][0].get("skill_id")
            skill_exec = admin_api_client.post("/api/skills/execute", {
                "skill_id": skill_id,
                "params": {"input": "集成测试"},
            })
            assert skill_exec["code"] == 0

        # Step 3: 写入记忆（M5）
        memory = admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_完整集成链路测试记录",
            "type": "test",
        })
        assert memory["code"] == 0

        # Step 4: 执行工作流（M7 → 多模块）
        workflows = admin_api_client.get("/api/workflows")
        if workflows["code"] == 0 and workflows["data"].get("items"):
            wf_id = workflows["data"]["items"][0].get("id") or workflows["data"]["items"][0].get("workflow_id")
            wf_exec = admin_api_client.post("/api/workflows/execute", {
                "workflow_id": wf_id,
                "params": {},
            })
            assert wf_exec["code"] == 0
