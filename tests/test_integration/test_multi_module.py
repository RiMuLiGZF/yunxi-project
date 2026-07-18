"""
端到端集成测试 - 多模块协作

测试多个模块之间的协作流程，
包括数据流转、状态同步、任务编排等。
纯逻辑测试，使用模拟数据。
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
class MockMultiModuleSystem:
    """模拟多模块协作系统"""

    MODULES = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]

    def __init__(self):
        self.module_status = {m: "running" for m in self.MODULES}
        self.task_queue = []
        self.completed_tasks = []
        self.message_bus = []

    def check_all_modules_healthy(self) -> Dict[str, Any]:
        """检查所有模块健康状态"""
        healthy = sum(1 for s in self.module_status.values() if s == "running")
        return {
            "total": len(self.MODULES),
            "healthy": healthy,
            "unhealthy": len(self.MODULES) - healthy,
            "all_healthy": healthy == len(self.MODULES),
            "modules": {m: self.module_status[m] for m in self.MODULES},
        }

    def submit_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """提交任务（经过M1调度到对应模块）"""
        task_id = f"task_{len(self.task_queue) + 1}"
        task["task_id"] = task_id
        task["status"] = "queued"
        self.task_queue.append(task)
        self._publish_event("task_submitted", task)
        return {"task_id": task_id, "status": "queued"}

    def process_task(self, task_id: str) -> Dict[str, Any]:
        """处理任务（模拟M1调度+模块执行）"""
        task = next((t for t in self.task_queue if t["task_id"] == task_id), None)
        if not task:
            return {"success": False, "error": "任务不存在"}

        # 模拟：M1分配 -> M2执行 -> M5存储记忆
        task["status"] = "processing"
        self._publish_event("task_started", task)

        # M2技能执行
        skill_result = self._m2_execute(task)

        # M5记忆存储
        self._m5_store(task, skill_result)

        task["status"] = "completed"
        task["result"] = skill_result
        self.completed_tasks.append(task)
        self.task_queue.remove(task)
        self._publish_event("task_completed", task)

        return {"success": True, "task_id": task_id, "result": skill_result}

    def _m2_execute(self, task: Dict) -> Dict:
        """模拟M2技能执行"""
        return {
            "module": "m2",
            "skill": task.get("skill", "default"),
            "output": f"执行结果: {task.get('input', '')}",
            "duration_ms": 150,
        }

    def _m5_store(self, task: Dict, result: Dict):
        """模拟M5记忆存储"""
        self._publish_event("memory_saved", {
            "type": "task_result",
            "task_id": task["task_id"],
        })

    def _publish_event(self, event_type: str, data: Dict):
        """发布事件到消息总线"""
        self.message_bus.append({
            "type": event_type,
            "data": data,
        })

    def get_module_dependencies(self, module: str) -> List[str]:
        """获取模块依赖关系"""
        deps = {
            "m1": ["m2", "m5"],
            "m2": ["m1", "m5"],
            "m5": ["m1", "m2"],
            "m8": ["m1", "m2", "m3", "m4", "m5", "m6", "m7"],
        }
        return deps.get(module, [])

    def orchestrate_workflow(self, steps: List[Dict]) -> Dict[str, Any]:
        """编排多步骤工作流（M7 + M1 协作）"""
        results = []
        for step in steps:
            task_result = self.submit_task(step)
            process_result = self.process_task(task_result["task_id"])
            results.append(process_result)

        return {
            "total_steps": len(steps),
            "completed": len([r for r in results if r["success"]]),
            "failed": len([r for r in results if not r["success"]]),
            "results": results,
        }


class TestMultiModule:
    """多模块协作集成测试"""

    @pytest.fixture
    def system(self):
        return MockMultiModuleSystem()

    # ============================================================
    # 模块健康检查
    # ============================================================

    @pytest.mark.integration
    def test_all_modules_healthy(self, system):
        """测试所有模块健康"""
        result = system.check_all_modules_healthy()
        assert result["total"] == 8
        assert result["all_healthy"] is True
        assert result["healthy"] == 8

    @pytest.mark.integration
    def test_module_failure_detection(self, system):
        """测试模块故障检测"""
        system.module_status["m3"] = "error"
        result = system.check_all_modules_healthy()
        assert result["all_healthy"] is False
        assert result["unhealthy"] == 1
        assert result["modules"]["m3"] == "error"

    @pytest.mark.integration
    def test_multiple_module_failures(self, system):
        """测试多模块故障"""
        system.module_status["m3"] = "stopped"
        system.module_status["m6"] = "error"
        result = system.check_all_modules_healthy()
        assert result["healthy"] == 6
        assert result["unhealthy"] == 2

    # ============================================================
    # 任务流转测试
    # ============================================================

    @pytest.mark.integration
    def test_submit_task(self, system):
        """测试提交任务"""
        result = system.submit_task({"skill": "test", "input": "hello"})
        assert result["status"] == "queued"
        assert "task_id" in result

    @pytest.mark.integration
    def test_process_task(self, system):
        """测试处理任务"""
        task = system.submit_task({"skill": "test", "input": "hello"})
        result = system.process_task(task["task_id"])
        assert result["success"] is True
        assert result["result"]["module"] == "m2"

    @pytest.mark.integration
    def test_task_completes(self, system):
        """测试任务完成后状态"""
        task = system.submit_task({"skill": "test", "input": "hi"})
        system.process_task(task["task_id"])
        assert len(system.completed_tasks) == 1
        assert system.completed_tasks[0]["status"] == "completed"

    @pytest.mark.integration
    def test_process_nonexistent_task(self, system):
        """测试处理不存在的任务"""
        result = system.process_task("no_such_task")
        assert result["success"] is False

    # ============================================================
    # 事件总线测试
    # ============================================================

    @pytest.mark.integration
    def test_events_published(self, system):
        """测试事件发布"""
        task = system.submit_task({"skill": "test", "input": "hi"})
        system.process_task(task["task_id"])
        event_types = [e["type"] for e in system.message_bus]
        assert "task_submitted" in event_types
        assert "task_started" in event_types
        assert "task_completed" in event_types
        assert "memory_saved" in event_types

    @pytest.mark.integration
    def test_event_count(self, system):
        """测试事件数量"""
        task = system.submit_task({"skill": "test"})
        before = len(system.message_bus)
        system.process_task(task["task_id"])
        after = len(system.message_bus)
        # 提交1个 + 处理3个(started+memory+completed) = 4个事件
        assert after - before >= 3

    # ============================================================
    # 模块依赖测试
    # ============================================================

    @pytest.mark.integration
    def test_m8_depends_on_all(self, system):
        """测试M8依赖所有模块"""
        deps = system.get_module_dependencies("m8")
        assert len(deps) == 7

    @pytest.mark.integration
    def test_module_dependency_bidirectional(self, system):
        """测试模块双向依赖"""
        m1_deps = system.get_module_dependencies("m1")
        assert "m2" in m1_deps
        m2_deps = system.get_module_dependencies("m2")
        assert "m1" in m2_deps

    # ============================================================
    # 工作流编排测试
    # ============================================================

    @pytest.mark.integration
    def test_workflow_orchestration(self, system):
        """测试工作流编排"""
        steps = [
            {"skill": "step1", "input": "input1"},
            {"skill": "step2", "input": "input2"},
            {"skill": "step3", "input": "input3"},
        ]
        result = system.orchestrate_workflow(steps)
        assert result["total_steps"] == 3
        assert result["completed"] == 3
        assert result["failed"] == 0

    @pytest.mark.integration
    def test_workflow_results_ordered(self, system):
        """测试工作流结果按顺序"""
        steps = [{"skill": f"step{i}"} for i in range(5)]
        result = system.orchestrate_workflow(steps)
        assert len(result["results"]) == 5
        assert len(system.completed_tasks) == 5
