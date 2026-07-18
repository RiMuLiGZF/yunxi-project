"""触发器系统测试.

测试内容：
1. Cron 表达式解析
2. 触发器 CRUD
3. 触发器启用/禁用
4. 触发历史记录
5. Webhook 签名验证
6. 事件总线
7. 触发器调度
"""

from __future__ import annotations

import os
import sys
import types
import importlib.util
import pytest
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# 处理相对导入：创建 m7_src 包
# ============================================================

_src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

# 创建 m7_src 包
src_pkg = types.ModuleType("m7_src")
src_pkg.__path__ = [_src_dir]
src_pkg.__package__ = "m7_src"
sys.modules["m7_src"] = src_pkg

# 导入 db 模块
db_spec = importlib.util.spec_from_file_location(
    "m7_src.db", os.path.join(_src_dir, "db.py")
)
db_module = importlib.util.module_from_spec(db_spec)
db_module.__package__ = "m7_src"
sys.modules["m7_src.db"] = db_module
src_pkg.db = db_module
db_spec.loader.exec_module(db_module)

Base = db_module.Base

# 导入 models_db 模块
models_db_spec = importlib.util.spec_from_file_location(
    "m7_src.models_db", os.path.join(_src_dir, "models_db.py")
)
models_db_module = importlib.util.module_from_spec(models_db_spec)
models_db_module.__package__ = "m7_src"
sys.modules["m7_src.models_db"] = models_db_module
src_pkg.models_db = models_db_module
models_db_spec.loader.exec_module(models_db_module)

# 创建 services 子包
services_dir = os.path.join(_src_dir, "services")
services_pkg = types.ModuleType("m7_src.services")
services_pkg.__path__ = [services_dir]
services_pkg.__package__ = "m7_src.services"
sys.modules["m7_src.services"] = services_pkg
src_pkg.services = services_pkg

# 导入 trigger_manager 模块
trigger_spec = importlib.util.spec_from_file_location(
    "m7_src.services.trigger_manager",
    os.path.join(services_dir, "trigger_manager.py"),
)
trigger_module = importlib.util.module_from_spec(trigger_spec)
trigger_module.__package__ = "m7_src.services"
sys.modules["m7_src.services.trigger_manager"] = trigger_module
services_pkg.trigger_manager = trigger_module
trigger_spec.loader.exec_module(trigger_module)

SimpleCronParser = trigger_module.SimpleCronParser
TriggerRepository = trigger_module.TriggerRepository
TriggerScheduler = trigger_module.TriggerScheduler
EventBus = trigger_module.EventBus
WebhookManager = trigger_module.WebhookManager
TriggerType = trigger_module.TriggerType


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = f"sqlite:///{tmp_path / 'test_m7.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def trigger_repo(db_session):
    return TriggerRepository(session=db_session)


# ============================================================
# 测试 1: Cron 解析
# ============================================================

class TestCronParser:
    def test_parse_simple_cron(self):
        minutes = SimpleCronParser.parse_field("*", 0, 59)
        assert len(minutes) == 60

    def test_parse_specific_value(self):
        result = SimpleCronParser.parse_field("30", 0, 59)
        assert result == {30}

    def test_parse_range(self):
        result = SimpleCronParser.parse_field("1-5", 0, 59)
        assert result == {1, 2, 3, 4, 5}

    def test_parse_step(self):
        result = SimpleCronParser.parse_field("*/15", 0, 59)
        assert result == {0, 15, 30, 45}

    def test_parse_list(self):
        result = SimpleCronParser.parse_field("1,3,5,7", 0, 59)
        assert result == {1, 3, 5, 7}

    def test_next_run_time_every_minute(self):
        base = datetime(2025, 1, 15, 10, 0, 0)
        next_run = SimpleCronParser.next_run_time("* * * * *", from_time=base)
        assert next_run is not None
        assert next_run.minute == 1
        assert next_run.hour == 10

    def test_next_run_time_specific_minute(self):
        base = datetime(2025, 1, 15, 10, 5, 0)
        next_run = SimpleCronParser.next_run_time("30 * * * *", from_time=base)
        assert next_run is not None
        assert next_run.minute == 30
        assert next_run.hour == 10

    def test_next_run_time_next_hour(self):
        base = datetime(2025, 1, 15, 10, 45, 0)
        next_run = SimpleCronParser.next_run_time("30 * * * *", from_time=base)
        assert next_run is not None
        assert next_run.minute == 30
        assert next_run.hour == 11
        assert next_run.day == 15

    def test_cron_invalid_format(self):
        result = SimpleCronParser.next_run_time("invalid")
        assert result is None

    def test_interval_based_scheduling(self):
        # interval 调度由 TriggerScheduler 内部处理，这里测试基本的时间计算
        base = datetime(2025, 1, 15, 10, 0, 0)
        interval_sec = 300
        expected = base + timedelta(seconds=interval_sec)
        assert expected.minute == 5
        assert expected.hour == 10


# ============================================================
# 测试 2: 触发器类型常量
# ============================================================

class TestTriggerType:
    def test_all_types(self):
        assert "schedule" in TriggerType.ALL
        assert "webhook" in TriggerType.ALL
        assert "event" in TriggerType.ALL
        assert "manual" in TriggerType.ALL
        assert len(TriggerType.ALL) == 4

    def test_type_constants(self):
        assert TriggerType.SCHEDULE == "schedule"
        assert TriggerType.WEBHOOK == "webhook"
        assert TriggerType.EVENT == "event"
        assert TriggerType.MANUAL == "manual"


# ============================================================
# 测试 3: 触发器 CRUD
# ============================================================

class TestTriggerCRUD:
    def test_create_schedule_trigger(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="每日定时任务",
            workflow_id="wf_daily",
            trigger_type="schedule",
            description="每天早上 9 点执行",
            config={"cron": "0 9 * * *"},
            input_mapping={"param": "value"},
            enabled=True,
            timezone="Asia/Shanghai",
            created_by="test_user",
        )
        assert trigger is not None
        assert trigger["id"].startswith("trig_")
        assert trigger["name"] == "每日定时任务"
        assert trigger["trigger_type"] == "schedule"
        assert trigger["enabled"] is True
        assert trigger["workflow_id"] == "wf_daily"

    def test_create_webhook_trigger(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="Webhook 触发器",
            workflow_id="wf_webhook",
            trigger_type="webhook",
            config={"secret": "mysecret"},
            enabled=True,
            created_by="test_user",
        )
        assert trigger is not None
        assert trigger["trigger_type"] == "webhook"
        assert trigger["webhook_path"] != ""
        assert "/webhook/" in trigger["webhook_path"]

    def test_create_event_trigger(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="事件触发器",
            workflow_id="wf_event",
            trigger_type="event",
            config={"event_type": "order.created"},
            filter_config={"source": "api"},
            enabled=False,
            created_by="test_user",
        )
        assert trigger is not None
        assert trigger["enabled"] is False
        assert trigger["filter_config"] == {"source": "api"}

    def test_get_trigger(self, trigger_repo):
        created = trigger_repo.create_trigger(
            name="测试", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        fetched = trigger_repo.get_trigger(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "测试"

    def test_get_nonexistent_trigger(self, trigger_repo):
        result = trigger_repo.get_trigger("nonexistent")
        assert result is None

    def test_update_trigger(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="原始名称", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        success = trigger_repo.update_trigger(
            trigger["id"],
            name="新名称",
            description="新描述",
        )
        assert success is True

        updated = trigger_repo.get_trigger(trigger["id"])
        assert updated["name"] == "新名称"
        assert updated["description"] == "新描述"

    def test_update_trigger_config(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        success = trigger_repo.update_trigger(
            trigger["id"],
            config={"cron": "*/30 * * * *"},
        )
        assert success is True

        updated = trigger_repo.get_trigger(trigger["id"])
        assert updated["config"]["cron"] == "*/30 * * * *"

    def test_update_nonexistent_trigger(self, trigger_repo):
        success = trigger_repo.update_trigger("nonexistent", name="new")
        assert success is False

    def test_delete_trigger(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="待删除", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        success = trigger_repo.delete_trigger(trigger["id"])
        assert success is True
        assert trigger_repo.get_trigger(trigger["id"]) is None

    def test_delete_nonexistent_trigger(self, trigger_repo):
        success = trigger_repo.delete_trigger("nonexistent")
        assert success is False

    def test_list_triggers(self, trigger_repo):
        for i in range(5):
            trigger_repo.create_trigger(
                name=f"触发器{i}",
                workflow_id=f"wf_{i % 2}",
                trigger_type="schedule" if i % 2 == 0 else "webhook",
                config={"cron": "0 * * * *"},
                enabled=i < 3,
            )

        result = trigger_repo.list_triggers(page=1, page_size=10)
        assert result["total"] == 5
        assert len(result["items"]) == 5

    def test_list_triggers_filter_by_type(self, trigger_repo):
        for i in range(4):
            trigger_repo.create_trigger(
                name=f"t{i}",
                workflow_id=f"wf_{i}",
                trigger_type="schedule" if i < 2 else "webhook",
                config={"cron": "0 * * * *"} if i < 2 else {"secret": "s"},
                enabled=True,
            )

        result = trigger_repo.list_triggers(trigger_type="schedule")
        assert result["total"] == 2

    def test_list_triggers_filter_by_workflow(self, trigger_repo):
        trigger_repo.create_trigger(
            name="t1", workflow_id="wf_a", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        trigger_repo.create_trigger(
            name="t2", workflow_id="wf_b", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )

        result = trigger_repo.list_triggers(workflow_id="wf_a")
        assert result["total"] == 1

    def test_list_triggers_filter_by_enabled(self, trigger_repo):
        for i in range(3):
            trigger_repo.create_trigger(
                name=f"t{i}", workflow_id=f"wf_{i}", trigger_type="schedule",
                config={"cron": "0 * * * *"}, enabled=i == 0,
            )

        result = trigger_repo.list_triggers(enabled=True)
        assert result["total"] == 1

    def test_list_triggers_pagination(self, trigger_repo):
        for i in range(12):
            trigger_repo.create_trigger(
                name=f"t{i}", workflow_id=f"wf_{i}", trigger_type="schedule",
                config={"cron": "0 * * * *"}, enabled=True,
            )

        page1 = trigger_repo.list_triggers(page=1, page_size=5)
        assert page1["total"] == 12
        assert len(page1["items"]) == 5

        page3 = trigger_repo.list_triggers(page=3, page_size=5)
        assert len(page3["items"]) == 2


# ============================================================
# 测试 4: 触发器启用/禁用
# ============================================================

class TestTriggerEnableDisable:
    def test_enable_trigger(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=False,
        )
        result = trigger_repo.enable_trigger(trigger["id"])
        assert result is True
        assert trigger_repo.get_trigger(trigger["id"])["enabled"] is True

    def test_disable_trigger(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        result = trigger_repo.disable_trigger(trigger["id"])
        assert result is True
        assert trigger_repo.get_trigger(trigger["id"])["enabled"] is False

    def test_enable_nonexistent(self, trigger_repo):
        assert trigger_repo.enable_trigger("nonexistent") is False

    def test_disable_nonexistent(self, trigger_repo):
        assert trigger_repo.disable_trigger("nonexistent") is False

    def test_enable_already_enabled(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        result = trigger_repo.enable_trigger(trigger["id"])
        assert result is True
        assert trigger_repo.get_trigger(trigger["id"])["enabled"] is True


# ============================================================
# 测试 5: 触发历史
# ============================================================

class TestTriggerHistory:
    def test_add_history_success(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        hist_id = trigger_repo.add_history(
            trigger_id=trigger["id"],
            workflow_id="wf_1",
            status="success",
            run_id="run_abc123",
            payload={"key": "value"},
            error_message="",
        )
        assert hist_id > 0

    def test_add_history_failed(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        hist_id = trigger_repo.add_history(
            trigger_id=trigger["id"],
            workflow_id="wf_1",
            status="failed",
            error_message="触发失败",
        )
        assert hist_id > 0

    def test_list_history(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        for i in range(5):
            trigger_repo.add_history(
                trigger_id=trigger["id"],
                workflow_id="wf_1",
                status="success",
                run_id=f"run_{i}",
            )

        history = trigger_repo.list_history(
            trigger["id"], page=1, page_size=10,
        )
        assert history["total"] == 5
        assert len(history["items"]) == 5

    def test_list_history_empty(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        history = trigger_repo.list_history(trigger["id"])
        assert history["total"] == 0

    def test_list_history_filter_status(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="t", workflow_id="wf_1", trigger_type="schedule",
            config={"cron": "0 * * * *"}, enabled=True,
        )
        trigger_repo.add_history(trigger["id"], "wf_1", status="success")
        trigger_repo.add_history(trigger["id"], "wf_1", status="success")
        trigger_repo.add_history(trigger["id"], "wf_1", status="failed")

        success_hist = trigger_repo.list_history(trigger["id"], status="success")
        assert success_hist["total"] == 2


# ============================================================
# 测试 6: Webhook 签名验证
# ============================================================

class TestWebhookSignature:
    def test_generate_and_verify_signature(self):
        secret = "test_secret_key"
        payload = b'{"key": "value", "num": 42}'

        signature = WebhookManager.generate_signature(payload, secret)
        assert signature is not None
        assert signature.startswith("sha256=")
        assert len(signature) > 10

        assert WebhookManager.verify_signature(payload, signature, secret) is True

    def test_verify_wrong_signature(self):
        secret = "test_secret"
        payload = b'{"data": "test"}'

        assert WebhookManager.verify_signature(payload, "wrong_signature", secret) is False

    def test_verify_tampered_payload(self):
        secret = "test_secret"
        original = b'{"data": "original"}'
        tampered = b'{"data": "tampered"}'

        signature = WebhookManager.generate_signature(original, secret)
        assert WebhookManager.verify_signature(tampered, signature, secret) is False

    def test_verify_empty_secret(self):
        payload = b'{"data": "test"}'
        sig = WebhookManager.generate_signature(payload, "secret")
        assert WebhookManager.verify_signature(payload, sig, "") is False

    def test_verify_sha1_algorithm(self):
        secret = "test_secret"
        payload = b'{"data": "test"}'

        signature = WebhookManager.generate_signature(payload, secret, algorithm="sha1")
        assert signature.startswith("sha1=")
        assert WebhookManager.verify_signature(payload, signature, secret, algorithm="sha1") is True

    def test_webhook_input_mapping(self):
        payload = {
            "user": {"name": "Alice", "email": "alice@example.com"},
            "action": "created",
        }
        mapping = {
            "username": "user.name",
            "user_email": "user.email",
            "event_type": {"static": "user_created"},
            "raw": {"$raw": True},
        }
        result = WebhookManager.map_input(payload, mapping)
        assert result["username"] == "Alice"
        assert result["user_email"] == "alice@example.com"
        assert result["event_type"] == "user_created"
        assert result["raw"] == payload

    def test_webhook_input_mapping_empty(self):
        payload = {"key": "value"}
        result = WebhookManager.map_input(payload, {})
        assert "payload" in result
        assert result["payload"] == payload


# ============================================================
# 测试 7: 事件总线
# ============================================================

class TestEventBus:
    def test_publish_subscribe(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        sub_id = bus.subscribe("test.event", handler)
        assert sub_id.startswith("sub_")

        count = bus.publish("test.event", {"value": 42})
        assert count == 1
        assert len(received) == 1
        assert received[0]["event_type"] == "test.event"
        assert received[0]["data"] == {"value": 42}

    def test_multiple_subscribers(self):
        bus = EventBus()
        count1 = [0]
        count2 = [0]

        def h1(event):
            count1[0] += 1

        def h2(event):
            count2[0] += 1

        bus.subscribe("event.x", h1)
        bus.subscribe("event.x", h2)
        bus.publish("event.x", {})

        assert count1[0] == 1
        assert count2[0] == 1

    def test_unsubscribe(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        sub_id = bus.subscribe("test", handler)
        bus.publish("test", {"n": 1})
        assert len(received) == 1

        result = bus.unsubscribe(sub_id)
        assert result is True

        bus.publish("test", {"n": 2})
        assert len(received) == 1

    def test_unsubscribe_invalid(self):
        bus = EventBus()
        result = bus.unsubscribe("invalid_sub_id")
        assert result is False

    def test_no_subscribers(self):
        bus = EventBus()
        count = bus.publish("no_subscribers", {"data": "test"})
        assert count == 0

    def test_handler_exception(self):
        bus = EventBus()
        received = []

        def bad_handler(event):
            raise ValueError("error")

        def good_handler(event):
            received.append(event)

        bus.subscribe("event", bad_handler)
        bus.subscribe("event", good_handler)
        count = bus.publish("event", {"ok": True})

        # 只有成功的 handler 被计数（异常被捕获）
        assert count == 1
        assert len(received) == 1
        assert received[0]["data"] == {"ok": True}

    def test_list_event_types(self):
        bus = EventBus()
        bus.subscribe("evt.a", lambda e: None)
        bus.subscribe("evt.b", lambda e: None)
        bus.subscribe("evt.a", lambda e: None)

        types = bus.list_event_types()
        assert "evt.a" in types
        assert "evt.b" in types
        assert len(types) == 2

    def test_event_contains_metadata(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("meta.test", handler)
        bus.publish("meta.test", {"x": 1}, source="api")

        evt = received[0]
        assert "event_id" in evt
        assert evt["event_id"].startswith("evt_")
        assert evt["source"] == "api"
        assert "timestamp" in evt


# ============================================================
# 测试 8: Webhook 路径查找
# ============================================================

class TestWebhookLookup:
    def test_get_by_webhook_path(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="wh", workflow_id="wf_1", trigger_type="webhook",
            config={}, enabled=True,
        )
        path = trigger["webhook_path"]

        found = trigger_repo.get_by_webhook_path(path)
        assert found is not None
        assert found["id"] == trigger["id"]

    def test_get_by_webhook_path_disabled(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="wh", workflow_id="wf_1", trigger_type="webhook",
            config={}, enabled=False,
        )
        path = trigger["webhook_path"]

        found = trigger_repo.get_by_webhook_path(path)
        assert found is None

    def test_get_by_webhook_path_not_found(self, trigger_repo):
        found = trigger_repo.get_by_webhook_path("/webhook/nonexistent")
        assert found is None


# ============================================================
# 测试 9: 触发器调度器基础
# ============================================================

class TestTriggerScheduler:
    def test_scheduler_create(self, trigger_repo):
        scheduler = TriggerScheduler(trigger_repo)
        assert scheduler is not None
        assert scheduler._running is False

    def test_scheduler_has_callback_list(self, trigger_repo):
        scheduler = TriggerScheduler(trigger_repo)
        assert hasattr(scheduler, "_on_trigger_callbacks")
        assert isinstance(scheduler._on_trigger_callbacks, list)

    def test_on_trigger_registers_callback(self, trigger_repo):
        scheduler = TriggerScheduler(trigger_repo)
        calls = []

        def callback(trigger_id, trigger_type, workflow_id, payload):
            calls.append((trigger_id, workflow_id))

        scheduler.on_trigger(callback)
        assert len(scheduler._on_trigger_callbacks) == 1


# ============================================================
# 测试 10: 触发器配置验证
# ============================================================

class TestTriggerConfigValidation:
    def test_schedule_config_valid_cron(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="cron_test",
            workflow_id="wf_1",
            trigger_type="schedule",
            config={"cron": "0 9 * * 1-5"},
            enabled=True,
        )
        assert trigger is not None
        assert trigger["config"]["cron"] == "0 9 * * 1-5"

    def test_schedule_config_interval(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="interval_test",
            workflow_id="wf_1",
            trigger_type="schedule",
            config={"interval_seconds": 300},
            enabled=True,
        )
        assert trigger is not None
        assert trigger["config"]["interval_seconds"] == 300

    def test_webhook_config_with_secret(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="wh_test",
            workflow_id="wf_1",
            trigger_type="webhook",
            config={"secret": "my_webhook_secret"},
            enabled=True,
        )
        assert trigger is not None
        assert trigger["webhook_path"] != ""
        assert "/webhook/" in trigger["webhook_path"]

    def test_event_config_with_type(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="ev_test",
            workflow_id="wf_1",
            trigger_type="event",
            config={"event_type": "user.created"},
            filter_config={"source": "api", "level": "info"},
            enabled=True,
        )
        assert trigger is not None
        assert trigger["config"]["event_type"] == "user.created"
        assert trigger["filter_config"] == {"source": "api", "level": "info"}

    def test_trigger_timezone_setting(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="tz_test",
            workflow_id="wf_1",
            trigger_type="schedule",
            config={"cron": "0 9 * * *"},
            timezone="America/New_York",
            enabled=True,
        )
        assert trigger["timezone"] == "America/New_York"

    def test_trigger_default_timezone(self, trigger_repo):
        trigger = trigger_repo.create_trigger(
            name="tz_default",
            workflow_id="wf_1",
            trigger_type="schedule",
            config={"cron": "0 9 * * *"},
            enabled=True,
        )
        assert trigger["timezone"] == "Asia/Shanghai"
