"""
E2E 测试 - 测试数据工厂

提供各类测试数据的生成和管理：
- 测试用户生成
- 测试配置生成
- 测试任务生成
- 测试记忆生成
- 测试场景生成
- 测试工作流生成
- 数据快照与恢复
"""

import uuid
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class TestUser:
    """测试用户数据"""
    username: str
    password: str
    email: str
    role: str = "user"
    nickname: str = ""
    user_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "password": self.password,
            "email": self.email,
            "role": self.role,
            "nickname": self.nickname,
            "user_id": self.user_id,
        }


@dataclass
class TestDataSnapshot:
    """测试数据快照"""
    snapshot_id: str
    created_at: str
    data: Dict[str, Any] = field(default_factory=dict)


class E2ETestDataFactory:
    """
    E2E 测试数据工厂

    负责生成各类测试数据，确保测试数据的：
    - 唯一性（每个测试用例独立数据）
    - 可预测性（固定种子可复现）
    - 完整性（包含所有必要字段）
    - 可清理性（测试后自动清理）
    """

    def __init__(self, seed: Optional[int] = None, prefix: str = "e2e_test_"):
        self.prefix = prefix
        self._counter = 0
        self._snapshots: Dict[str, TestDataSnapshot] = {}
        self._created_users: List[TestUser] = []
        self._created_resources: List[Dict[str, Any]] = []

        if seed is not None:
            random.seed(seed)

    # ============================================================
    # 基础数据生成
    # ============================================================

    def _unique_id(self, suffix: str = "") -> str:
        """生成唯一标识符"""
        self._counter += 1
        return f"{self.prefix}{self._counter}_{uuid.uuid4().hex[:8]}{suffix}"

    @staticmethod
    def random_string(length: int = 10, chars: Optional[str] = None) -> str:
        """生成随机字符串"""
        if chars is None:
            chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    @staticmethod
    def random_email(domain: str = "e2e.test") -> str:
        """生成随机邮箱"""
        name = E2ETestDataFactory.random_string(10).lower()
        return f"{name}@{domain}"

    @staticmethod
    def random_int(min_val: int = 0, max_val: int = 100) -> int:
        """生成随机整数"""
        return random.randint(min_val, max_val)

    @staticmethod
    def random_float(min_val: float = 0.0, max_val: float = 1.0) -> float:
        """生成随机浮点数"""
        return round(random.uniform(min_val, max_val), 4)

    @staticmethod
    def random_bool() -> bool:
        """生成随机布尔值"""
        return random.choice([True, False])

    @staticmethod
    def random_datetime(days_back: int = 30) -> str:
        """生成随机日期时间字符串（ISO 格式）"""
        now = datetime.now()
        delta = timedelta(
            days=random.randint(0, days_back),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )
        return (now - delta).isoformat()

    # ============================================================
    # 用户数据
    # ============================================================

    def create_test_user(
        self,
        role: str = "user",
        is_active: bool = True,
    ) -> TestUser:
        """
        创建测试用户

        Args:
            role: 用户角色
            is_active: 是否激活

        Returns:
            TestUser 对象
        """
        username = self._unique_id("user").lower()
        password = f"Test@{self.random_string(8)}123"
        email = f"{username}@e2e.test"
        nickname = f"测试用户{self.random_string(4)}"

        user = TestUser(
            username=username,
            password=password,
            email=email,
            role=role,
            nickname=nickname,
        )
        self._created_users.append(user)
        return user

    def create_admin_user(self) -> TestUser:
        """创建管理员测试用户"""
        return self.create_test_user(role="admin")

    def create_multiple_users(self, count: int = 5, role: str = "user") -> List[TestUser]:
        """创建多个测试用户"""
        return [self.create_test_user(role=role) for _ in range(count)]

    # ============================================================
    # 任务数据
    # ============================================================

    TASK_TYPES = [
        "intent_classification",
        "dialog_processing",
        "memory_query",
        "memory_store",
        "skill_execution",
        "scene_switching",
        "workflow_execution",
        "compute_routing",
        "code_generation",
        "data_analysis",
    ]

    TASK_STATUSES = ["pending", "running", "completed", "failed", "cancelled"]

    def create_task_data(
        self,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        module: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建测试任务数据"""
        task_type = task_type or random.choice(self.TASK_TYPES)
        status = status or random.choice(self.TASK_STATUSES)
        module = module or f"m{random.randint(1, 12)}"

        duration = None
        if status in ["completed", "failed"]:
            duration = round(self.random_float(0.1, 30.0), 2)

        task = {
            "task_id": self._unique_id("task"),
            "type": task_type,
            "title": f"{task_type}_{self.random_string(8)}",
            "module": module,
            "status": status,
            "priority": random.choice(["low", "normal", "high", "urgent"]),
            "duration_seconds": duration,
            "input": {
                "query": f"测试输入_{self.random_string(20)}",
                "context": {"source": "e2e_test"},
            },
            "output": {
                "result": f"测试输出_{self.random_string(20)}",
            } if status == "completed" else None,
            "created_at": self.random_datetime(7),
            "tags": [f"tag_{i}" for i in range(random.randint(1, 5))],
        }

        self._created_resources.append({"type": "task", "id": task["task_id"], "data": task})
        return task

    # ============================================================
    # 记忆数据
    # ============================================================

    MEMORY_TYPES = [
        "general",
        "conversation",
        "preference",
        "fact",
        "emotion",
        "skill_result",
    ]

    def create_memory_data(
        self,
        memory_type: Optional[str] = None,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建测试记忆数据"""
        memory_type = memory_type or random.choice(self.MEMORY_TYPES)
        content = content or f"E2E_TEST_记忆内容_{self.random_string(50)}"

        memory = {
            "memory_id": self._unique_id("mem"),
            "type": memory_type,
            "content": content,
            "importance": self.random_float(0.0, 1.0),
            "tags": [f"tag_{i}" for i in range(random.randint(1, 5))],
            "source": "e2e_test",
            "created_at": self.random_datetime(30),
            "last_accessed": self.random_datetime(7),
            "access_count": random.randint(0, 100),
            "decay_rate": self.random_float(0.0, 0.1),
        }

        self._created_resources.append({"type": "memory", "id": memory["memory_id"], "data": memory})
        return memory

    def create_memories(self, count: int = 10) -> List[Dict[str, Any]]:
        """创建多条记忆数据"""
        return [self.create_memory_data() for _ in range(count)]

    # ============================================================
    # 场景数据
    # ============================================================

    SCENE_TEMPLATES = [
        {"id": "work", "name": "工作模式", "description": "专注工作，屏蔽干扰"},
        {"id": "study", "name": "学习模式", "description": "学习辅助，知识整理"},
        {"id": "life", "name": "生活助手", "description": "日常生活管理"},
        {"id": "creative", "name": "创作模式", "description": "创意写作与设计"},
        {"id": "coding", "name": "开发模式", "description": "代码开发与调试"},
        {"id": "meeting", "name": "会议模式", "description": "会议记录与整理"},
    ]

    def create_scene_data(
        self,
        scene_id: Optional[str] = None,
        active: bool = False,
    ) -> Dict[str, Any]:
        """创建测试场景数据"""
        template = random.choice(self.SCENE_TEMPLATES)
        if scene_id:
            template["id"] = scene_id

        scene = {
            "scene_id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "active": active,
            "config": {
                "theme": random.choice(["dark", "light", "auto"]),
                "notifications": self.random_bool(),
                "voice_enabled": self.random_bool(),
                "memory_enabled": self.random_bool(),
            },
            "skills": [f"skill_{i}" for i in range(random.randint(2, 8))],
            "created_at": self.random_datetime(90),
            "updated_at": self.random_datetime(7),
        }

        self._created_resources.append({"type": "scene", "id": scene["scene_id"], "data": scene})
        return scene

    # ============================================================
    # 工作流数据
    # ============================================================

    def create_workflow_data(
        self,
        step_count: Optional[int] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        """创建测试工作流数据"""
        step_count = step_count or random.randint(2, 10)

        steps = []
        for i in range(step_count):
            steps.append({
                "step_id": f"step_{i+1}",
                "name": f"步骤{i+1}",
                "type": random.choice(["skill", "memory", "agent", "condition", "delay"]),
                "config": {"param": f"value_{i}"},
                "timeout": random.randint(10, 300),
                "retry_count": random.randint(0, 3),
            })

        workflow = {
            "workflow_id": self._unique_id("wf"),
            "name": f"测试工作流_{self.random_string(6)}",
            "description": f"E2E 测试工作流 {self.random_string(20)}",
            "status": status,
            "steps": steps,
            "step_count": step_count,
            "created_by": "e2e_test",
            "created_at": self.random_datetime(30),
            "updated_at": self.random_datetime(7),
            "execution_count": random.randint(0, 100),
            "avg_duration_ms": self.random_float(100, 5000),
        }

        self._created_resources.append({"type": "workflow", "id": workflow["workflow_id"], "data": workflow})
        return workflow

    # ============================================================
    # 技能数据
    # ============================================================

    SKILL_CATEGORIES = [
        "utility", "language", "development", "productivity",
        "creative", "analysis", "communication", "system",
    ]

    def create_skill_data(
        self,
        category: Optional[str] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """创建测试技能数据"""
        category = category or random.choice(self.SKILL_CATEGORIES)

        skill = {
            "skill_id": self._unique_id("skill"),
            "name": f"测试技能_{self.random_string(6)}",
            "category": category,
            "description": f"E2E 测试技能 - {self.random_string(30)}",
            "enabled": enabled,
            "version": f"v{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,9)}",
            "author": "e2e_test",
            "tags": [f"tag_{i}" for i in range(random.randint(1, 5))],
            "parameters": {
                "input": {"type": "string", "description": "输入参数"},
                "output": {"type": "string", "description": "输出结果"},
            },
            "rating": self.random_float(3.0, 5.0),
            "usage_count": random.randint(0, 1000),
            "created_at": self.random_datetime(90),
        }

        self._created_resources.append({"type": "skill", "id": skill["skill_id"], "data": skill})
        return skill

    # ============================================================
    # 配置数据
    # ============================================================

    def create_config_data(self) -> Dict[str, Any]:
        """创建测试配置数据"""
        return {
            "system_name": "云汐系统 - E2E测试",
            "language": "zh-CN",
            "theme": random.choice(["dark", "light", "auto"]),
            "timezone": "Asia/Shanghai",
            "notifications": {
                "email": self.random_bool(),
                "push": self.random_bool(),
                "sound": self.random_bool(),
            },
            "privacy": {
                "data_collection": self.random_bool(),
                "analytics": self.random_bool(),
                "personalization": self.random_bool(),
            },
            "performance": {
                "max_concurrent_tasks": random.randint(1, 10),
                "cache_enabled": self.random_bool(),
                "streaming_enabled": self.random_bool(),
            },
        }

    # ============================================================
    # 对话数据
    # ============================================================

    def create_conversation_data(
        self,
        message_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建测试对话数据"""
        message_count = message_count or random.randint(2, 10)

        messages = []
        for i in range(message_count):
            is_user = i % 2 == 0
            messages.append({
                "message_id": self._unique_id("msg"),
                "role": "user" if is_user else "assistant",
                "content": f"{'用户' if is_user else '助手'}消息_{i+1}_{self.random_string(20)}",
                "timestamp": self.random_datetime(1),
                "metadata": {
                    "agent": "principal" if not is_user else None,
                    "tokens": random.randint(10, 200),
                },
            })

        conversation = {
            "conversation_id": self._unique_id("conv"),
            "title": f"测试对话_{self.random_string(8)}",
            "messages": messages,
            "message_count": message_count,
            "created_at": self.random_datetime(7),
            "last_message_at": self.random_datetime(1),
            "participants": ["user", "assistant"],
        }

        self._created_resources.append({
            "type": "conversation",
            "id": conversation["conversation_id"],
            "data": conversation,
        })
        return conversation

    # ============================================================
    # 模块状态数据
    # ============================================================

    def create_module_status_data(
        self,
        module_key: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建模块状态数据"""
        module_key = module_key or f"m{random.randint(1, 12)}"
        status = status or random.choices(
            ["running", "stopped", "error", "degraded"],
            weights=[0.7, 0.15, 0.05, 0.1],
            k=1,
        )[0]

        return {
            "key": module_key,
            "name": f"模块 {module_key.upper()}",
            "status": status,
            "version": f"v{random.randint(1,2)}.{random.randint(0,9)}.{random.randint(0,9)}",
            "cpu_usage": self.random_int(5, 90),
            "memory_usage": self.random_int(10, 85),
            "disk_usage": self.random_int(20, 70),
            "uptime_seconds": self.random_int(3600, 86400 * 30),
            "last_health_check": self.random_datetime(1),
            "health": "healthy" if status == "running" else "unhealthy",
        }

    # ============================================================
    # 数据快照
    # ============================================================

    def create_snapshot(self, name: str = "") -> str:
        """
        创建测试数据快照

        用于数据备份恢复测试。
        """
        snapshot_id = self._unique_id("snapshot")
        snapshot = TestDataSnapshot(
            snapshot_id=snapshot_id,
            created_at=datetime.now().isoformat(),
            data={
                "users": [u.to_dict() for u in self._created_users],
                "resources": list(self._created_resources),
                "name": name,
            },
        )
        self._snapshots[snapshot_id] = snapshot
        return snapshot_id

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """
        恢复测试数据快照

        Returns:
            是否恢复成功
        """
        if snapshot_id not in self._snapshots:
            return False

        snapshot = self._snapshots[snapshot_id]
        # 清理当前数据
        self._created_users.clear()
        self._created_resources.clear()

        # 恢复快照数据（此处仅做记录，实际恢复需要配合 API 客户端）
        return True

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """列出所有快照"""
        return [
            {
                "snapshot_id": s.snapshot_id,
                "created_at": s.created_at,
                "name": s.data.get("name", ""),
                "user_count": len(s.data.get("users", [])),
                "resource_count": len(s.data.get("resources", [])),
            }
            for s in self._snapshots.values()
        ]

    # ============================================================
    # 数据清理
    # ============================================================

    def get_created_users(self) -> List[TestUser]:
        """获取所有创建的测试用户"""
        return list(self._created_users)

    def get_created_resources(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有创建的资源"""
        if resource_type:
            return [
                r for r in self._created_resources
                if r["type"] == resource_type
            ]
        return list(self._created_resources)

    def cleanup(self) -> Dict[str, int]:
        """
        清理所有测试数据记录

        Returns:
            清理统计 {users: int, resources: int, snapshots: int}
        """
        stats = {
            "users": len(self._created_users),
            "resources": len(self._created_resources),
            "snapshots": len(self._snapshots),
        }

        self._created_users.clear()
        self._created_resources.clear()
        self._snapshots.clear()
        self._counter = 0

        return stats

    def reset(self):
        """重置工厂状态"""
        self.cleanup()
        self._counter = 0
