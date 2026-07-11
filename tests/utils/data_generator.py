"""
云汐系统 - 测试数据生成器

提供各种测试数据的生成方法，包括：
- 用户数据
- 任务数据
- 模块状态数据
- 算力调用数据
- 随机字符串/数字
"""

import uuid
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


class TestDataGenerator:
    """测试数据生成器"""

    # 模块列表
    MODULES = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]
    MODULE_NAMES = {
        "m1": "多Agent集群调度",
        "m2": "技能集群",
        "m3": "端云协同",
        "m4": "场景引擎",
        "m5": "潮汐记忆",
        "m6": "硬件外设",
        "m7": "积木平台",
        "m8": "管理控制塔",
    }

    # 任务类型
    TASK_TYPES = [
        "intent_classification",
        "dialog_processing",
        "memory_query",
        "skill_execution",
        "scene_switching",
        "workflow_execution",
        "compute_routing",
    ]

    # 任务状态
    TASK_STATUSES = ["pending", "running", "completed", "failed", "cancelled"]

    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)

    # ============================================================
    # 基础数据生成
    # ============================================================

    @staticmethod
    def random_string(length: int = 10, chars: str = None) -> str:
        """生成随机字符串"""
        if chars is None:
            chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    @staticmethod
    def random_email() -> str:
        """生成随机邮箱"""
        name = TestDataGenerator.random_string(8).lower()
        domains = ["example.com", "test.com", "yunxi.io", "demo.org"]
        return f"{name}@{random.choice(domains)}"

    @staticmethod
    def random_int(min_val: int = 0, max_val: int = 100) -> int:
        """生成随机整数"""
        return random.randint(min_val, max_val)

    @staticmethod
    def random_float(min_val: float = 0.0, max_val: float = 1.0) -> float:
        """生成随机浮点数"""
        return random.uniform(min_val, max_val)

    @staticmethod
    def random_bool() -> bool:
        """生成随机布尔值"""
        return random.choice([True, False])

    @staticmethod
    def random_uuid() -> str:
        """生成随机 UUID"""
        return str(uuid.uuid4())

    @staticmethod
    def random_datetime(days_back: int = 30) -> datetime:
        """生成随机日期时间（过去 N 天内）"""
        now = datetime.now()
        delta = timedelta(
            days=random.randint(0, days_back),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )
        return now - delta

    # ============================================================
    # 用户数据
    # ============================================================

    def generate_user(self, role: str = "user", status: str = "active") -> Dict[str, Any]:
        """生成测试用户数据"""
        username = f"test_user_{self.random_string(6).lower()}"
        return {
            "username": username,
            "password": "Test@123456",
            "email": self.random_email(),
            "nickname": f"测试用户{self.random_string(4)}",
            "role": role,
            "status": status,
        }

    # ============================================================
    # 任务数据
    # ============================================================

    def generate_task(self, module: str = None, status: str = None) -> Dict[str, Any]:
        """生成测试任务数据"""
        task_type = random.choice(self.TASK_TYPES)
        module = module or random.choice(self.MODULES)
        status = status or random.choice(self.TASK_STATUSES)
        
        duration = None
        if status in ["completed", "failed"]:
            duration = round(self.random_float(0.1, 10.0), 2)

        return {
            "task_id": f"T{self.random_int(10000, 99999)}",
            "type": task_type,
            "title": f"{task_type}_{self.random_string(8)}",
            "module": module,
            "status": status,
            "priority": random.choice(["low", "normal", "high", "urgent"]),
            "duration": duration,
            "created_at": self.random_datetime(7).strftime("%Y-%m-%d %H:%M:%S"),
            "params": {
                "input": self.random_string(20),
                "options": {
                    "timeout": self.random_int(10, 120),
                    "retry": self.random_int(0, 3),
                }
            }
        }

    def generate_tasks(self, count: int = 10) -> List[Dict[str, Any]]:
        """生成多个任务"""
        return [self.generate_task() for _ in range(count)]

    # ============================================================
    # 模块状态数据
    # ============================================================

    def generate_module_status(self, module: str = None) -> Dict[str, Any]:
        """生成模块状态数据"""
        module = module or random.choice(self.MODULES)
        status = random.choices(
            ["running", "stopped", "error", "degraded"],
            weights=[0.7, 0.15, 0.05, 0.1],
            k=1
        )[0]

        return {
            "key": module,
            "name": self.MODULE_NAMES.get(module, module),
            "status": status,
            "cpu_usage": self.random_int(5, 90),
            "memory_usage": self.random_int(10, 85),
            "uptime_seconds": self.random_int(3600, 86400 * 30),
            "version": f"v{self.random_int(1,2)}.{self.random_int(0,9)}.{self.random_int(0,9)}",
            "last_health_check": self.random_datetime(1).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def generate_all_modules_status(self) -> List[Dict[str, Any]]:
        """生成所有模块的状态数据"""
        return [self.generate_module_status(m) for m in self.MODULES]

    # ============================================================
    # 算力调用数据
    # ============================================================

    def generate_compute_call(self, status: str = "success") -> Dict[str, Any]:
        """生成算力调用记录"""
        models = ["gpt-4o-mini", "claude-3-haiku", "gemini-1.5-flash", "llama3.1:8b", "qwen2.5:7b"]
        sources = ["openai", "anthropic", "google", "ollama", "dashscope"]
        idx = self.random_int(0, len(models) - 1)
        
        input_tokens = self.random_int(100, 5000)
        output_tokens = self.random_int(50, 2000)
        
        return {
            "call_id": f"call_{self.random_string(12)}",
            "model_key": models[idx],
            "source_id": sources[idx],
            "caller_module": random.choice(self.MODULES),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost": round(self.random_float(0.001, 0.1), 4),
            "latency_ms": self.random_int(100, 5000),
            "status": status,
            "created_at": self.random_datetime(1).strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ============================================================
    # 系统统计数据
    # ============================================================

    def generate_system_stats(self) -> Dict[str, Any]:
        """生成系统统计数据"""
        modules_status = self.generate_all_modules_status()
        running = sum(1 for m in modules_status if m["status"] == "running")
        
        return {
            "total_modules": 8,
            "running_modules": running,
            "tasks_today": self.random_int(50, 500),
            "active_users": self.random_int(5, 50),
            "compute_calls_today": self.random_int(500, 5000),
            "health_score": self.random_int(80, 100),
            "uptime_seconds": self.random_int(86400, 86400 * 30),
        }
