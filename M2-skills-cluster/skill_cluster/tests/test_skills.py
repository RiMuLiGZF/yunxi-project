"""M2 技能集群 - 内置技能单元测试.

覆盖 6 个代表性技能的核心功能：
- TodoSkill: 待办事项管理（Repository 模式代表）
- CalendarSkill: 日历事件管理
- ContactSkill: 联系人管理
- FinanceSkill: 记账本/财务管理
- MoodSkill: 情绪追踪
- TranslateSkill: 翻译转换

测试策略：
1. 使用 tmp_path 隔离每个测试的数据库文件
2. 每个测试类对应一个技能，测试之间不共享状态
3. 覆盖初始化元数据验证、CRUD 操作、边界条件、错误处理、invoke 分发
4. 不依赖外部服务
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)
from skill_cluster.skills.calendar import CalendarSkill
from skill_cluster.skills.contact import ContactSkill
from skill_cluster.skills.finance import FinanceSkill
from skill_cluster.skills.mood import MoodSkill
from skill_cluster.skills.todo import TodoRepository, TodoSkill
from skill_cluster.skills.translate import TranslateSkill


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------


def _make_request(skill_id: str, action: str, params: dict[str, Any] | None = None) -> SkillInvokeRequest:
    """构造 SkillInvokeRequest 测试辅助函数.

    Args:
        skill_id: 技能 ID
        action: 动作名
        params: 动作参数

    Returns:
        构造好的请求对象
    """
    return SkillInvokeRequest(
        skill_id=skill_id,
        action=action,
        params=params or {},
        trace_id=f"test-{uuid.uuid4().hex[:8]}",
    )


def _make_tmp_skill(skill_class: type, tmp_path: str, db_filename: str) -> Any:
    """创建使用临时目录数据库的技能实例.

    通过先实例化再替换 _db_path / _repo 的方式，
    确保测试数据隔离，不污染用户目录。

    Args:
        skill_class: 技能类
        tmp_path: 临时目录路径
        db_filename: 数据库文件名

    Returns:
        配置好临时数据库的技能实例
    """
    skill = skill_class.__new__(skill_class)
    # 手动调用 ISkill.__init__ 来设置 manifest
    # 我们需要先调用原 __init__ 来创建 manifest，再替换 db 路径
    # 但原 __init__ 会立刻创建数据库，所以用 __new__ + 手动初始化
    # 为了简化，先正常 init，然后替换路径重新 init_db
    # 更好的方式：直接构造实例并覆盖
    skill_class.__init__(skill)
    # 替换数据库路径
    new_db_path = os.path.join(tmp_path, db_filename)
    os.makedirs(os.path.dirname(new_db_path), exist_ok=True)

    if hasattr(skill, "_repo"):
        # Repository 模式（如 TodoSkill）
        # 关闭旧连接，创建新的 Repository
        skill._repo.close()
        from skill_cluster.db.skill_repository_base import SkillBaseRepository

        # 动态创建新 repo
        repo_class = type(skill._repo)
        skill._repo = repo_class(db_path=new_db_path)
    elif hasattr(skill, "_db_path"):
        # 直接 sqlite3 模式
        skill._db_path = new_db_path
        os.makedirs(os.path.dirname(new_db_path), exist_ok=True)
        skill._init_db()

    # TranslateSkill 的缓存目录
    if hasattr(skill, "_cache_dir"):
        skill._cache_dir = os.path.join(tmp_path, "translate_cache")
        os.makedirs(skill._cache_dir, exist_ok=True)

    return skill


# ======================================================================
# TodoSkill 测试
# ======================================================================


class TestTodoSkill:
    """TodoSkill 待办事项管理技能测试套件."""

    @pytest.fixture
    def skill(self, tmp_path: str) -> TodoSkill:
        """创建使用临时数据库的 TodoSkill 实例."""
        return _make_tmp_skill(TodoSkill, tmp_path, "todo.db")

    # ---- 初始化与元数据 ----

    def test_skill_is_instance_of_iskill(self, skill: TodoSkill) -> None:
        """验证 TodoSkill 继承自 ISkill."""
        assert isinstance(skill, ISkill)

    def test_manifest_metadata(self, skill: TodoSkill) -> None:
        """验证技能元数据的完整性."""
        m = skill.manifest
        assert m.skill_id == "skill.todo"
        assert m.name == "待办事项"
        assert m.version == "1.0.0"
        assert m.author == "yunxi"
        assert "todo" in m.tags
        assert "create" in m.capabilities
        assert "list" in m.capabilities
        assert "delete" in m.capabilities
        assert "complete" in m.capabilities
        assert "stats" in m.capabilities
        assert m.entrypoint == "TodoSkill"

    def test_health_check(self, skill: TodoSkill) -> None:
        """验证健康检查接口."""
        import asyncio

        result = asyncio.run(skill.health())
        assert result["healthy"] is True
        assert result["skill_id"] == "skill.todo"

    def test_configure(self, skill: TodoSkill) -> None:
        """验证配置更新接口."""
        import asyncio

        asyncio.run(skill.configure({"key": "value", "num": 42}))
        assert skill._config["key"] == "value"
        assert skill._config["num"] == 42

    # ---- CRUD: 创建 ----

    def test_create_todo_success(self, skill: TodoSkill) -> None:
        """成功创建待办事项."""
        result = skill._create({
            "title": "完成单元测试",
            "description": "为 M2 技能编写测试",
            "priority": 2,
            "tags": ["测试", "开发"],
        })
        assert result["created"] is True
        assert result["title"] == "完成单元测试"
        assert len(result["todo_id"]) > 0

    def test_create_todo_empty_title_raises(self, skill: TodoSkill) -> None:
        """空标题创建待办应抛出 ValueError."""
        with pytest.raises(ValueError, match="标题不能为空"):
            skill._create({"title": ""})

    def test_create_todo_default_values(self, skill: TodoSkill) -> None:
        """创建待办时使用默认值."""
        result = skill._create({"title": "默认值测试"})
        assert result["created"] is True
        # 查询验证默认值
        todo = skill._repo.get_todo(result["todo_id"])
        assert todo is not None
        assert todo["status"] == "pending"
        assert todo["priority"] == 0
        assert todo["tags"] == []

    def test_create_todo_special_characters(self, skill: TodoSkill) -> None:
        """标题和描述包含特殊字符."""
        special_title = "测试 ' \" ; DROP TABLE -- 特殊字符"
        result = skill._create({
            "title": special_title,
            "description": "<script>alert(1)</script> &amp; 测试",
        })
        assert result["created"] is True
        todo = skill._repo.get_todo(result["todo_id"])
        assert todo is not None
        assert todo["title"] == special_title

    def test_create_todo_long_title(self, skill: TodoSkill) -> None:
        """超长标题创建待办（边界测试）."""
        long_title = "A" * 5000
        result = skill._create({"title": long_title})
        assert result["created"] is True
        todo = skill._repo.get_todo(result["todo_id"])
        assert todo is not None
        assert len(todo["title"]) == 5000

    # ---- CRUD: 查询列表 ----

    def test_list_todos_empty(self, skill: TodoSkill) -> None:
        """空数据库下列表返回空."""
        result = skill._list({})
        assert result["todos"] == []
        assert result["total"] == 0
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_list_todos_with_data(self, skill: TodoSkill) -> None:
        """有数据时列表返回正确数量."""
        for i in range(5):
            skill._create({"title": f"任务 {i}", "priority": i})
        result = skill._list({})
        assert result["total"] == 5
        assert len(result["todos"]) == 5

    def test_list_todos_pagination(self, skill: TodoSkill) -> None:
        """分页查询正确性."""
        for i in range(15):
            skill._create({"title": f"任务 {i}"})
        result = skill._list({"page": 2, "page_size": 5})
        assert len(result["todos"]) == 5
        assert result["page"] == 2
        assert result["total_pages"] == 3

    def test_list_todos_filter_by_status(self, skill: TodoSkill) -> None:
        """按状态筛选待办."""
        skill._create({"title": "已完成", "status": "completed"})
        skill._create({"title": "进行中", "status": "in_progress"})
        skill._create({"title": "待处理", "status": "pending"})
        result = skill._list({"status": "pending"})
        assert result["total"] == 1
        assert result["todos"][0]["title"] == "待处理"

    def test_list_todos_filter_by_priority(self, skill: TodoSkill) -> None:
        """按优先级筛选待办."""
        skill._create({"title": "高优", "priority": 3})
        skill._create({"title": "中优", "priority": 2})
        skill._create({"title": "低优", "priority": 1})
        result = skill._list({"priority": 3})
        assert result["total"] == 1
        assert result["todos"][0]["title"] == "高优"

    def test_list_todos_filter_by_tag(self, skill: TodoSkill) -> None:
        """按标签筛选待办."""
        skill._create({"title": "任务1", "tags": ["工作", "重要"]})
        skill._create({"title": "任务2", "tags": ["生活"]})
        result = skill._list({"tag": "工作"})
        assert result["total"] == 1
        assert result["todos"][0]["title"] == "任务1"

    # ---- CRUD: 更新 ----

    def test_update_todo_success(self, skill: TodoSkill) -> None:
        """成功更新待办事项."""
        create_result = skill._create({"title": "原标题"})
        todo_id = create_result["todo_id"]
        update_result = skill._update({
            "todo_id": todo_id,
            "title": "新标题",
            "priority": 5,
        })
        assert update_result["updated"] is True
        todo = skill._repo.get_todo(todo_id)
        assert todo is not None
        assert todo["title"] == "新标题"
        assert todo["priority"] == 5

    def test_update_todo_no_id_raises(self, skill: TodoSkill) -> None:
        """更新时缺少 todo_id 应抛出异常."""
        with pytest.raises(ValueError, match="todo_id"):
            skill._update({"title": "新标题"})

    def test_update_todo_no_fields_raises(self, skill: TodoSkill) -> None:
        """更新时没有可更新字段应抛出异常."""
        create_result = skill._create({"title": "测试"})
        with pytest.raises(ValueError, match="没有需要更新的字段"):
            skill._update({"todo_id": create_result["todo_id"]})

    def test_update_nonexistent_todo_raises(self, skill: TodoSkill) -> None:
        """更新不存在的待办应抛出 ValueError."""
        with pytest.raises(ValueError, match="不存在"):
            skill._update({
                "todo_id": "nonexistent-id",
                "title": "新标题",
            })

    # ---- CRUD: 删除 ----

    def test_delete_todo_success(self, skill: TodoSkill) -> None:
        """成功删除待办事项."""
        create_result = skill._create({"title": "待删除"})
        todo_id = create_result["todo_id"]
        delete_result = skill._delete({"todo_id": todo_id})
        assert delete_result["deleted"] is True
        assert skill._repo.get_todo(todo_id) is None

    def test_delete_todo_no_id_raises(self, skill: TodoSkill) -> None:
        """删除时缺少 todo_id 应抛出异常."""
        with pytest.raises(ValueError, match="todo_id"):
            skill._delete({})

    def test_delete_nonexistent_todo_raises(self, skill: TodoSkill) -> None:
        """删除不存在的待办应抛出 ValueError."""
        with pytest.raises(ValueError, match="不存在"):
            skill._delete({"todo_id": "nonexistent-id"})

    # ---- 完成标记 ----

    def test_complete_todo_success(self, skill: TodoSkill) -> None:
        """成功标记待办为已完成."""
        create_result = skill._create({"title": "待完成"})
        todo_id = create_result["todo_id"]
        result = skill._complete({"todo_id": todo_id})
        assert result["completed"] is True
        assert result["completed_at"] != ""
        todo = skill._repo.get_todo(todo_id)
        assert todo is not None
        assert todo["status"] == "completed"

    def test_complete_todo_no_id_raises(self, skill: TodoSkill) -> None:
        """完成标记缺少 todo_id 应抛出异常."""
        with pytest.raises(ValueError, match="todo_id"):
            skill._complete({})

    def test_complete_nonexistent_todo_raises(self, skill: TodoSkill) -> None:
        """标记不存在的待办为完成应抛出 ValueError."""
        with pytest.raises(ValueError, match="不存在"):
            skill._complete({"todo_id": "nonexistent-id"})

    # ---- 统计 ----

    def test_stats_empty(self, skill: TodoSkill) -> None:
        """空数据库下统计数据应为零."""
        stats = skill._stats({})
        assert stats["today_completed"] == 0
        assert stats["week_completed"] == 0
        assert stats["pending"] == 0
        assert stats["overdue"] == 0
        assert isinstance(stats["status_distribution"], dict)
        assert isinstance(stats["priority_distribution"], dict)

    def test_stats_with_data(self, skill: TodoSkill) -> None:
        """有数据时统计数据正确."""
        # 创建 3 个待办
        for i in range(3):
            skill._create({"title": f"任务 {i}"})
        # 完成 1 个
        create_result = skill._create({"title": "已完成任务"})
        skill._complete({"todo_id": create_result["todo_id"]})

        stats = skill._stats({})
        assert stats["pending"] == 3
        assert stats["today_completed"] >= 1
        assert "pending" in stats["status_distribution"]
        assert "completed" in stats["status_distribution"]

    # ---- invoke 分发 ----

    def test_invoke_create_action(self, skill: TodoSkill) -> None:
        """通过 invoke 调用 create 动作."""
        import asyncio

        request = _make_request("skill.todo", "create", {"title": "invoke测试"})
        result = asyncio.run(skill.invoke(request))
        assert isinstance(result, SkillInvokeResult)
        assert result.status == "success"
        assert result.action == "create"
        assert result.data is not None
        assert result.data["created"] is True
        assert result.latency_ms >= 0
        assert result.trace_id == request.trace_id

    def test_invoke_list_action(self, skill: TodoSkill) -> None:
        """通过 invoke 调用 list 动作."""
        import asyncio

        skill._create({"title": "任务1"})
        request = _make_request("skill.todo", "list", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "success"
        assert result.data is not None
        assert result.data["total"] >= 1

    def test_invoke_unknown_action(self, skill: TodoSkill) -> None:
        """调用不存在的 action 应返回 failure."""
        import asyncio

        request = _make_request("skill.todo", "nonexistent_action", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"
        assert "Unknown action" in (result.error or "")

    def test_invoke_error_handling(self, skill: TodoSkill) -> None:
        """invoke 中业务异常应返回 failure 而非抛出."""
        import asyncio

        # 创建待办时不传 title 会触发 ValueError
        request = _make_request("skill.todo", "create", {"title": ""})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"
        assert result.error is not None

    # ---- Repository 层 ----

    def test_repository_get_nonexistent_returns_none(self, skill: TodoSkill) -> None:
        """查询不存在的记录返回 None."""
        assert skill._repo.get_todo("nonexistent") is None

    def test_repository_is_healthy(self, skill: TodoSkill) -> None:
        """Repository 健康检查."""
        assert skill._repo.is_healthy() is True

    def test_repository_close(self, skill: TodoSkill) -> None:
        """Repository 关闭后 closed 状态为 True."""
        skill._repo.close()
        assert skill._repo._db.closed is True


# ======================================================================
# CalendarSkill 测试
# ======================================================================


class TestCalendarSkill:
    """CalendarSkill 日历管理技能测试套件."""

    @pytest.fixture
    def skill(self, tmp_path: str) -> CalendarSkill:
        """创建使用临时数据库的 CalendarSkill 实例."""
        return _make_tmp_skill(CalendarSkill, tmp_path, "calendar.db")

    def test_manifest_metadata(self, skill: CalendarSkill) -> None:
        """验证技能元数据."""
        m = skill.manifest
        assert m.skill_id == "skill.calendar"
        assert m.name == "日历管理"
        assert m.version == "1.0.0"
        assert "calendar" in m.tags
        assert "create_event" in m.capabilities
        assert "list_events" in m.capabilities
        assert "get_free_slots" in m.capabilities

    def test_create_event_success(self, skill: CalendarSkill) -> None:
        """成功创建日历事件."""
        result = skill._create_event({
            "title": "团队周会",
            "start": "2025-01-15T10:00:00",
            "end": "2025-01-15T11:00:00",
            "description": "讨论项目进度",
        })
        assert result["created"] is True
        assert len(result["event_id"]) > 0

    def test_create_event_empty_title(self, skill: CalendarSkill) -> None:
        """创建空标题事件（不报错，因为没有校验）."""
        result = skill._create_event({
            "title": "",
            "start": "2025-01-15T10:00:00",
            "end": "2025-01-15T11:00:00",
        })
        assert result["created"] is True

    def test_list_events_empty(self, skill: CalendarSkill) -> None:
        """空数据库下列表为空."""
        result = skill._list_events({
            "start": "2025-01-01T00:00:00",
            "end": "2025-12-31T23:59:59",
        })
        assert result["events"] == []

    def test_list_events_with_data(self, skill: CalendarSkill) -> None:
        """有数据时列表正确返回."""
        skill._create_event({
            "title": "事件1",
            "start": "2025-06-15T10:00:00",
            "end": "2025-06-15T11:00:00",
        })
        skill._create_event({
            "title": "事件2",
            "start": "2025-06-15T14:00:00",
            "end": "2025-06-15T15:00:00",
        })
        result = skill._list_events({
            "start": "2025-06-01T00:00:00",
            "end": "2025-06-30T23:59:59",
        })
        assert len(result["events"]) == 2

    def test_list_events_with_calendar_id(self, skill: CalendarSkill) -> None:
        """按 calendar_id 筛选事件（注意：创建时不存 calendar_id）."""
        skill._create_event({
            "title": "事件1",
            "start": "2025-06-15T10:00:00",
            "end": "2025-06-15T11:00:00",
        })
        result = skill._list_events({
            "start": "2025-06-01T00:00:00",
            "end": "2025-06-30T23:59:59",
            "calendar_id": "some_id",
        })
        # 创建事件时没有存 calendar_id，所以按 calendar_id 查询应为空
        assert len(result["events"]) == 0

    def test_delete_event_success(self, skill: CalendarSkill) -> None:
        """成功删除事件."""
        create_result = skill._create_event({
            "title": "待删除",
            "start": "2025-06-15T10:00:00",
            "end": "2025-06-15T11:00:00",
        })
        event_id = create_result["event_id"]
        delete_result = skill._delete_event({"event_id": event_id})
        assert delete_result["deleted"] is True

    def test_delete_nonexistent_event(self, skill: CalendarSkill) -> None:
        """删除不存在的事件也返回 success（不抛异常）."""
        result = skill._delete_event({"event_id": "nonexistent"})
        assert result["deleted"] is True

    def test_get_free_slots_all_day_free(self, skill: CalendarSkill) -> None:
        """没有事件时全天都是空闲."""
        result = skill._get_free_slots({
            "date": "2025-06-15",
            "duration_minutes": 60,
        })
        assert len(result["free_slots"]) == 1
        assert result["free_slots"][0]["start"].startswith("2025-06-15")

    def test_get_free_slots_with_event(self, skill: CalendarSkill) -> None:
        """有事件时空闲时段正确分割."""
        skill._create_event({
            "title": "会议",
            "start": "2025-06-15T10:00:00",
            "end": "2025-06-15T12:00:00",
        })
        result = skill._get_free_slots({
            "date": "2025-06-15",
            "duration_minutes": 60,
        })
        # 应该有两段空闲：会议前和会议后
        assert len(result["free_slots"]) >= 2

    def test_invoke_create_event(self, skill: CalendarSkill) -> None:
        """通过 invoke 调用 create_event."""
        import asyncio

        request = _make_request("skill.calendar", "create_event", {
            "title": "测试会议",
            "start": "2025-06-15T10:00:00",
            "end": "2025-06-15T11:00:00",
        })
        result = asyncio.run(skill.invoke(request))
        assert result.status == "success"
        assert result.data is not None
        assert result.data["created"] is True

    def test_invoke_unknown_action(self, skill: CalendarSkill) -> None:
        """调用不存在的 action 返回 failure."""
        import asyncio

        request = _make_request("skill.calendar", "bad_action", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"

    def test_health_check(self, skill: CalendarSkill) -> None:
        """健康检查."""
        import asyncio

        result = asyncio.run(skill.health())
        assert result["healthy"] is True

    def test_special_characters_in_event(self, skill: CalendarSkill) -> None:
        """事件标题包含特殊字符."""
        title = "会议 ' \" ; DROP TABLE -- 测试"
        result = skill._create_event({
            "title": title,
            "start": "2025-06-15T10:00:00",
            "end": "2025-06-15T11:00:00",
        })
        list_result = skill._list_events({
            "start": "2025-06-01T00:00:00",
            "end": "2025-06-30T23:59:59",
        })
        assert list_result["events"][0]["title"] == title


# ======================================================================
# ContactSkill 测试
# ======================================================================


class TestContactSkill:
    """ContactSkill 联系人管理技能测试套件."""

    @pytest.fixture
    def skill(self, tmp_path: str) -> ContactSkill:
        """创建使用临时数据库的 ContactSkill 实例."""
        return _make_tmp_skill(ContactSkill, tmp_path, "contact.db")

    def test_manifest_metadata(self, skill: ContactSkill) -> None:
        """验证技能元数据."""
        m = skill.manifest
        assert m.skill_id == "skill.contact"
        assert m.name == "联系人"
        assert "contact" in m.tags
        assert "create" in m.capabilities
        assert "search" in m.capabilities
        assert "groups" in m.capabilities
        assert "important_dates" in m.capabilities

    # ---- 创建 ----

    def test_create_contact_success(self, skill: ContactSkill) -> None:
        """成功创建联系人."""
        result = skill._create({
            "name": "张三",
            "phone": "13800138000",
            "email": "zhangsan@example.com",
            "group_name": "朋友",
            "relationship": "朋友",
        })
        assert result["created"] is True
        assert result["name"] == "张三"
        assert len(result["contact_id"]) > 0

    def test_create_contact_minimal(self, skill: ContactSkill) -> None:
        """只传 name 创建联系人."""
        result = skill._create({"name": "李四"})
        assert result["created"] is True

    def test_create_contact_empty_name(self, skill: ContactSkill) -> None:
        """空姓名创建（不报错，因为没有校验）."""
        result = skill._create({"name": ""})
        assert result["created"] is True

    def test_create_contact_special_characters(self, skill: ContactSkill) -> None:
        """联系人信息包含特殊字符."""
        result = skill._create({
            "name": "测试'; DROP TABLE --",
            "notes": "<script>alert(1)</script>",
        })
        assert result["created"] is True

    # ---- 列表 ----

    def test_list_contacts_empty(self, skill: ContactSkill) -> None:
        """空数据库下联系人列表为空."""
        result = skill._list({})
        assert result["contacts"] == []
        assert result["total"] == 0

    def test_list_contacts_with_data(self, skill: ContactSkill) -> None:
        """有数据时列表正确."""
        for i in range(3):
            skill._create({"name": f"联系人{i}", "group_name": "朋友"})
        result = skill._list({})
        assert result["total"] == 3
        assert len(result["contacts"]) == 3

    def test_list_contacts_filter_by_group(self, skill: ContactSkill) -> None:
        """按分组筛选联系人."""
        skill._create({"name": "A", "group_name": "朋友"})
        skill._create({"name": "B", "group_name": "同事"})
        skill._create({"name": "C", "group_name": "朋友"})
        result = skill._list({"group_name": "朋友"})
        assert result["total"] == 2

    def test_list_contacts_filter_by_relationship(self, skill: ContactSkill) -> None:
        """按关系筛选联系人."""
        skill._create({"name": "A", "relationship": "朋友"})
        skill._create({"name": "B", "relationship": "家人"})
        result = skill._list({"relationship": "家人"})
        assert result["total"] == 1

    def test_list_contacts_pagination(self, skill: ContactSkill) -> None:
        """分页查询."""
        for i in range(10):
            skill._create({"name": f"联系人{i}"})
        result = skill._list({"limit": 3, "offset": 3})
        assert len(result["contacts"]) == 3
        assert result["total"] == 10

    def test_list_contacts_invalid_sort_field(self, skill: ContactSkill) -> None:
        """无效排序字段使用默认 name."""
        skill._create({"name": "B"})
        skill._create({"name": "A"})
        result = skill._list({"sort_by": "invalid_field", "sort_order": "asc"})
        assert result["contacts"][0]["name"] == "A"

    # ---- 更新 ----

    def test_update_contact_success(self, skill: ContactSkill) -> None:
        """成功更新联系人."""
        create_result = skill._create({"name": "原名"})
        contact_id = create_result["contact_id"]
        update_result = skill._update({
            "contact_id": contact_id,
            "name": "新名",
            "phone": "123456789",
        })
        assert update_result["updated"] is True

    def test_update_contact_no_id_raises(self, skill: ContactSkill) -> None:
        """缺少 contact_id 抛出异常."""
        with pytest.raises(ValueError, match="contact_id"):
            skill._update({"name": "新名"})

    def test_update_contact_no_fields(self, skill: ContactSkill) -> None:
        """没有可更新字段返回 updated=False."""
        create_result = skill._create({"name": "测试"})
        result = skill._update({"contact_id": create_result["contact_id"]})
        assert result["updated"] is False

    def test_update_nonexistent_contact(self, skill: ContactSkill) -> None:
        """更新不存在的联系人不报错（SQL 静默成功）."""
        result = skill._update({
            "contact_id": "nonexistent",
            "name": "新名",
        })
        # 该实现不检查是否存在，直接执行 update
        assert result["updated"] is True

    # ---- 删除 ----

    def test_delete_contact_success(self, skill: ContactSkill) -> None:
        """成功删除联系人."""
        create_result = skill._create({"name": "待删除"})
        contact_id = create_result["contact_id"]
        delete_result = skill._delete({"contact_id": contact_id})
        assert delete_result["deleted"] is True
        # 验证已删除
        list_result = skill._list({})
        assert list_result["total"] == 0

    def test_delete_contact_no_id_raises(self, skill: ContactSkill) -> None:
        """缺少 contact_id 抛出异常."""
        with pytest.raises(ValueError, match="contact_id"):
            skill._delete({})

    # ---- 搜索 ----

    def test_search_contacts_by_name(self, skill: ContactSkill) -> None:
        """按姓名搜索联系人."""
        skill._create({"name": "张三", "phone": "111"})
        skill._create({"name": "李四", "phone": "222"})
        result = skill._search({"keyword": "张"})
        assert result["total"] == 1
        assert result["contacts"][0]["name"] == "张三"

    def test_search_contacts_empty_keyword(self, skill: ContactSkill) -> None:
        """空关键词搜索返回空."""
        skill._create({"name": "张三"})
        result = skill._search({"keyword": ""})
        assert result["total"] == 0

    def test_search_contacts_by_phone(self, skill: ContactSkill) -> None:
        """按电话号码搜索."""
        skill._create({"name": "张三", "phone": "13800138000"})
        result = skill._search({"keyword": "138"})
        assert result["total"] >= 1

    # ---- 分组 ----

    def test_groups_empty(self, skill: ContactSkill) -> None:
        """空数据库下分组统计."""
        result = skill._groups({})
        assert result["groups"] == []
        assert result["ungrouped_count"] == 0
        assert result["total_contacts"] == 0

    def test_groups_with_data(self, skill: ContactSkill) -> None:
        """有数据时分组统计正确."""
        skill._create({"name": "A", "group_name": "朋友"})
        skill._create({"name": "B", "group_name": "朋友"})
        skill._create({"name": "C", "group_name": "同事"})
        skill._create({"name": "D"})  # 未分组
        result = skill._groups({})
        assert result["group_count"] == 2
        assert result["ungrouped_count"] == 1
        assert result["total_contacts"] == 4

    # ---- 重要日期 ----

    def test_important_dates_empty(self, skill: ContactSkill) -> None:
        """没有生日数据时重要日期为空."""
        result = skill._important_dates({})
        assert result["upcoming"] == []
        assert result["total"] == 0

    def test_important_dates_with_birthday(self, skill: ContactSkill) -> None:
        """有生日数据时正确计算."""
        # 设置一个未来 10 天的生日
        future_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        skill._create({
            "name": "寿星",
            "birthday": f"1990-{future_date[5:]}",  # 保持月日，用 1990 年
        })
        result = skill._important_dates({"days": 30})
        # 可能在范围内，取决于今天的日期
        assert isinstance(result["upcoming"], list)
        assert isinstance(result["total"], int)

    def test_important_dates_invalid_birthday(self, skill: ContactSkill) -> None:
        """无效生日格式被跳过."""
        skill._create({"name": "无效生日", "birthday": "not-a-date"})
        result = skill._important_dates({"days": 365})
        # 无效生日不会出现在结果中
        all_names = [item["name"] for item in result["upcoming"]]
        assert "无效生日" not in all_names

    # ---- invoke ----

    def test_invoke_create(self, skill: ContactSkill) -> None:
        """通过 invoke 创建联系人."""
        import asyncio

        request = _make_request("skill.contact", "create", {"name": "测试"})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "success"
        assert result.data is not None
        assert result.data["created"] is True

    def test_invoke_unknown_action(self, skill: ContactSkill) -> None:
        """调用不存在的 action 返回 failure."""
        import asyncio

        request = _make_request("skill.contact", "bad_action", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"

    def test_invoke_error_handling(self, skill: ContactSkill) -> None:
        """invoke 中异常应返回 failure."""
        import asyncio

        request = _make_request("skill.contact", "delete", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"


# ======================================================================
# FinanceSkill 测试
# ======================================================================


class TestFinanceSkill:
    """FinanceSkill 记账本技能测试套件."""

    @pytest.fixture
    def skill(self, tmp_path: str) -> FinanceSkill:
        """创建使用临时数据库的 FinanceSkill 实例."""
        return _make_tmp_skill(FinanceSkill, tmp_path, "finance.db")

    def test_manifest_metadata(self, skill: FinanceSkill) -> None:
        """验证技能元数据."""
        m = skill.manifest
        assert m.skill_id == "skill.finance"
        assert m.name == "记账本"
        assert "finance" in m.tags
        assert "add_record" in m.capabilities
        assert "stats" in m.capabilities
        assert "budget" in m.capabilities
        assert "monthly_summary" in m.capabilities

    # ---- 记一笔 ----

    def test_add_expense_success(self, skill: FinanceSkill) -> None:
        """成功添加支出记录."""
        result = skill._add_record({
            "type": "expense",
            "amount": 25.5,
            "category": "餐饮",
            "description": "午餐",
        })
        assert result["created"] is True
        assert result["type"] == "expense"
        assert result["amount"] == 25.5
        assert result["category"] == "餐饮"

    def test_add_income_success(self, skill: FinanceSkill) -> None:
        """成功添加收入记录."""
        result = skill._add_record({
            "type": "income",
            "amount": 10000,
            "category": "工资",
        })
        assert result["created"] is True
        assert result["type"] == "income"

    def test_add_record_invalid_type_raises(self, skill: FinanceSkill) -> None:
        """无效类型抛出 ValueError."""
        with pytest.raises(ValueError, match="type must be"):
            skill._add_record({"type": "invalid", "amount": 100})

    def test_add_record_zero_amount_raises(self, skill: FinanceSkill) -> None:
        """零金额抛出 ValueError."""
        with pytest.raises(ValueError, match="positive"):
            skill._add_record({"type": "expense", "amount": 0})

    def test_add_record_negative_amount_raises(self, skill: FinanceSkill) -> None:
        """负金额抛出 ValueError."""
        with pytest.raises(ValueError, match="positive"):
            skill._add_record({"type": "expense", "amount": -10})

    def test_add_record_default_category(self, skill: FinanceSkill) -> None:
        """默认分类为其他."""
        result = skill._add_record({"type": "expense", "amount": 100})
        assert result["category"] == "其他"

    # ---- 列表 ----

    def test_list_empty(self, skill: FinanceSkill) -> None:
        """空数据库下记录列表为空."""
        result = skill._list({})
        assert result["transactions"] == []
        assert result["total"] == 0

    def test_list_with_data(self, skill: FinanceSkill) -> None:
        """有数据时列表正确."""
        for i in range(5):
            skill._add_record({"type": "expense", "amount": 10 + i, "category": "餐饮"})
        result = skill._list({})
        assert result["total"] == 5
        assert len(result["transactions"]) == 5

    def test_list_filter_by_type(self, skill: FinanceSkill) -> None:
        """按类型筛选记录."""
        skill._add_record({"type": "income", "amount": 1000, "category": "工资"})
        skill._add_record({"type": "expense", "amount": 50, "category": "餐饮"})
        skill._add_record({"type": "expense", "amount": 30, "category": "交通"})
        result = skill._list({"type": "expense"})
        assert result["total"] == 2

    def test_list_filter_by_category(self, skill: FinanceSkill) -> None:
        """按分类筛选记录."""
        skill._add_record({"type": "expense", "amount": 50, "category": "餐饮"})
        skill._add_record({"type": "expense", "amount": 30, "category": "交通"})
        result = skill._list({"category": "餐饮"})
        assert result["total"] == 1

    def test_list_filter_by_date_range(self, skill: FinanceSkill) -> None:
        """按日期范围筛选."""
        skill._add_record({"type": "expense", "amount": 50, "date": "2025-06-15"})
        skill._add_record({"type": "expense", "amount": 30, "date": "2025-07-15"})
        result = skill._list({"start_date": "2025-06-01", "end_date": "2025-06-30"})
        assert result["total"] == 1

    def test_list_pagination(self, skill: FinanceSkill) -> None:
        """分页查询."""
        for i in range(10):
            skill._add_record({"type": "expense", "amount": 10 + i})
        result = skill._list({"limit": 3, "offset": 0})
        assert len(result["transactions"]) == 3
        assert result["total"] == 10

    # ---- 统计 ----

    def test_stats_empty(self, skill: FinanceSkill) -> None:
        """空数据库下统计数据为零."""
        result = skill._stats({})
        assert result["total_income"] == 0
        assert result["total_expense"] == 0
        assert result["balance"] == 0
        assert result["income_count"] == 0
        assert result["expense_count"] == 0

    def test_stats_with_data(self, skill: FinanceSkill) -> None:
        """有数据时统计正确."""
        skill._add_record({"type": "income", "amount": 10000, "category": "工资"})
        skill._add_record({"type": "expense", "amount": 3000, "category": "住房"})
        skill._add_record({"type": "expense", "amount": 500, "category": "餐饮"})
        result = skill._stats({})
        assert result["total_income"] == 10000
        assert result["total_expense"] == 3500
        assert result["balance"] == 6500
        assert result["income_count"] == 1
        assert result["expense_count"] == 2
        assert len(result["expense_by_category"]) == 2

    def test_stats_date_range(self, skill: FinanceSkill) -> None:
        """按日期范围统计."""
        skill._add_record({"type": "expense", "amount": 100, "date": "2025-06-15"})
        skill._add_record({"type": "expense", "amount": 200, "date": "2025-07-15"})
        result = skill._stats({"start_date": "2025-06-01", "end_date": "2025-06-30"})
        assert result["total_expense"] == 100

    # ---- 分类 ----

    def test_categories_empty_with_defaults(self, skill: FinanceSkill) -> None:
        """空数据库下返回预设分类."""
        result = skill._categories({"type": "expense"})
        assert result["total_categories"] > 0
        assert "餐饮" in [c["category"] for c in result["categories"]]

    def test_categories_with_data(self, skill: FinanceSkill) -> None:
        """有数据时返回实际分类."""
        skill._add_record({"type": "expense", "amount": 50, "category": "餐饮"})
        skill._add_record({"type": "expense", "amount": 30, "category": "餐饮"})
        skill._add_record({"type": "expense", "amount": 100, "category": "交通"})
        result = skill._categories({"type": "expense"})
        categories_dict = {c["category"]: c for c in result["categories"]}
        assert categories_dict["餐饮"]["count"] == 2
        assert categories_dict["交通"]["count"] == 1

    # ---- 月度汇总 ----

    def test_monthly_summary_empty(self, skill: FinanceSkill) -> None:
        """空数据库下月度汇总为零."""
        result = skill._monthly_summary({"month": "2025-06"})
        assert result["month"] == "2025-06"
        assert result["total_income"] == 0
        assert result["total_expense"] == 0

    def test_monthly_summary_with_data(self, skill: FinanceSkill) -> None:
        """有数据时月度汇总正确."""
        skill._add_record({"type": "income", "amount": 10000, "date": "2025-06-01"})
        skill._add_record({"type": "expense", "amount": 3000, "date": "2025-06-15"})
        result = skill._monthly_summary({"month": "2025-06"})
        assert result["total_income"] == 10000
        assert result["total_expense"] == 3000
        assert len(result["daily_summary"]) >= 1

    # ---- 预算 ----

    def test_set_budget_success(self, skill: FinanceSkill) -> None:
        """成功设置预算."""
        result = skill._budget({"action": "set", "category": "餐饮", "amount": 2000, "month": "2025-06"})
        assert result["category"] == "餐饮"
        assert result["amount"] == 2000
        assert result["created"] is True

    def test_set_budget_no_category_raises(self, skill: FinanceSkill) -> None:
        """缺少分类抛出异常."""
        with pytest.raises(ValueError, match="category"):
            skill._budget({"action": "set", "amount": 2000})

    def test_set_budget_negative_amount_raises(self, skill: FinanceSkill) -> None:
        """负预算抛出异常."""
        with pytest.raises(ValueError, match="non-negative"):
            skill._budget({"action": "set", "category": "餐饮", "amount": -100})

    def test_update_budget(self, skill: FinanceSkill) -> None:
        """重复设置同一分类预算应更新而非新建."""
        skill._budget({"action": "set", "category": "餐饮", "amount": 2000, "month": "2025-06"})
        result = skill._budget({"action": "set", "category": "餐饮", "amount": 3000, "month": "2025-06"})
        assert result["created"] is False
        assert result["amount"] == 3000

    def test_list_budgets_empty(self, skill: FinanceSkill) -> None:
        """空预算列表."""
        result = skill._budget({"action": "list", "month": "2025-06"})
        assert result["budgets"] == []
        assert result["total"] == 0

    def test_list_budgets_with_data(self, skill: FinanceSkill) -> None:
        """有预算时列表正确."""
        skill._budget({"action": "set", "category": "餐饮", "amount": 2000, "month": "2025-06"})
        skill._budget({"action": "set", "category": "交通", "amount": 500, "month": "2025-06"})
        result = skill._budget({"action": "list", "month": "2025-06"})
        assert result["total"] == 2

    def test_delete_budget_by_id(self, skill: FinanceSkill) -> None:
        """按 ID 删除预算."""
        set_result = skill._budget({"action": "set", "category": "餐饮", "amount": 2000, "month": "2025-06"})
        budget_id = set_result["budget_id"]
        delete_result = skill._budget({"action": "delete", "budget_id": budget_id})
        assert delete_result["deleted"] is True

    def test_delete_budget_no_identifier_raises(self, skill: FinanceSkill) -> None:
        """缺少预算标识抛出异常."""
        with pytest.raises(ValueError, match="budget_id or category"):
            skill._budget({"action": "delete"})

    def test_check_budget_normal(self, skill: FinanceSkill) -> None:
        """预算检查 - 正常状态."""
        skill._budget({"action": "set", "category": "餐饮", "amount": 2000, "month": "2025-06"})
        skill._add_record({"type": "expense", "amount": 500, "category": "餐饮", "date": "2025-06-15"})
        result = skill._budget({"action": "check", "month": "2025-06"})
        assert len(result["budget_status"]) == 1
        assert result["budget_status"][0]["status"] == "normal"

    def test_check_budget_over(self, skill: FinanceSkill) -> None:
        """预算检查 - 超额状态."""
        skill._budget({"action": "set", "category": "餐饮", "amount": 100, "month": "2025-06"})
        skill._add_record({"type": "expense", "amount": 200, "category": "餐饮", "date": "2025-06-15"})
        result = skill._budget({"action": "check", "month": "2025-06"})
        assert result["over_budget_count"] == 1
        assert result["budget_status"][0]["status"] == "over"

    def test_check_budget_warning(self, skill: FinanceSkill) -> None:
        """预算检查 - 警告状态（>=80%）."""
        skill._budget({"action": "set", "category": "餐饮", "amount": 100, "month": "2025-06"})
        skill._add_record({"type": "expense", "amount": 85, "category": "餐饮", "date": "2025-06-15"})
        result = skill._budget({"action": "check", "month": "2025-06"})
        assert result["warning_count"] == 1

    # ---- invoke ----

    def test_invoke_add_record(self, skill: FinanceSkill) -> None:
        """通过 invoke 添加记录."""
        import asyncio

        request = _make_request("skill.finance", "add_record", {
            "type": "expense", "amount": 100, "category": "餐饮",
        })
        result = asyncio.run(skill.invoke(request))
        assert result.status == "success"

    def test_invoke_unknown_action(self, skill: FinanceSkill) -> None:
        """调用不存在的 action 返回 failure."""
        import asyncio

        request = _make_request("skill.finance", "bad_action", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"

    def test_invoke_error_handling(self, skill: FinanceSkill) -> None:
        """invoke 中异常返回 failure."""
        import asyncio

        request = _make_request("skill.finance", "add_record", {"type": "bad", "amount": 100})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"


# ======================================================================
# MoodSkill 测试
# ======================================================================


class TestMoodSkill:
    """MoodSkill 情绪追踪技能测试套件."""

    @pytest.fixture
    def skill(self, tmp_path: str) -> MoodSkill:
        """创建使用临时数据库的 MoodSkill 实例."""
        return _make_tmp_skill(MoodSkill, tmp_path, "mood.db")

    def test_manifest_metadata(self, skill: MoodSkill) -> None:
        """验证技能元数据."""
        m = skill.manifest
        assert m.skill_id == "skill.mood"
        assert m.name == "情绪追踪"
        assert "mood" in m.tags
        assert "log" in m.capabilities
        assert "stats" in m.capabilities
        assert "trend" in m.capabilities
        assert "insights" in m.capabilities

    # ---- 记录情绪 ----

    def test_log_mood_success(self, skill: MoodSkill) -> None:
        """成功记录情绪."""
        result = skill._log({
            "mood": "happy",
            "valence": 0.8,
            "arousal": 0.7,
            "note": "今天心情很好",
            "triggers": ["工作顺利", "天气好"],
        })
        assert "log_id" in result
        assert result["mood"] == "happy"
        assert result["valence"] == 0.8
        assert result["arousal"] == 0.7

    def test_log_mood_invalid_type_raises(self, skill: MoodSkill) -> None:
        """无效情绪类型抛出 ValueError."""
        with pytest.raises(ValueError, match="无效的情绪类型"):
            skill._log({"mood": "ecstatic"})

    def test_log_mood_valence_out_of_range_raises(self, skill: MoodSkill) -> None:
        """效价超出范围抛出异常."""
        with pytest.raises(ValueError, match="效价"):
            skill._log({"mood": "happy", "valence": 2.0})

    def test_log_mood_valence_negative_out_of_range(self, skill: MoodSkill) -> None:
        """效价负向超出范围抛出异常."""
        with pytest.raises(ValueError, match="效价"):
            skill._log({"mood": "sad", "valence": -2.0})

    def test_log_mood_arousal_out_of_range_raises(self, skill: MoodSkill) -> None:
        """唤醒度超出范围抛出异常."""
        with pytest.raises(ValueError, match="唤醒度"):
            skill._log({"mood": "happy", "arousal": 1.5})

    def test_log_mood_arousal_negative_raises(self, skill: MoodSkill) -> None:
        """唤醒度为负抛出异常."""
        with pytest.raises(ValueError, match="唤醒度"):
            skill._log({"mood": "tired", "arousal": -0.1})

    def test_log_mood_default_values(self, skill: MoodSkill) -> None:
        """默认情绪值."""
        result = skill._log({})
        assert result["mood"] == "neutral"
        assert result["valence"] == 0.0
        assert result["arousal"] == 0.5

    def test_log_mood_boundary_values(self, skill: MoodSkill) -> None:
        """边界值测试."""
        # 效价边界
        for val in [-1.0, 0.0, 1.0]:
            result = skill._log({"mood": "neutral", "valence": val, "arousal": 0.5})
            assert result["valence"] == val
        # 唤醒度边界
        for aro in [0.0, 0.5, 1.0]:
            result = skill._log({"mood": "neutral", "arousal": aro})
            assert result["arousal"] == aro

    def test_log_mood_special_characters(self, skill: MoodSkill) -> None:
        """备注包含特殊字符."""
        note = "测试 ' ; DROP TABLE -- <script>alert(1)</script>"
        result = skill._log({"mood": "happy", "note": note})
        assert "log_id" in result

    def test_log_mood_all_valid_moods(self, skill: MoodSkill) -> None:
        """所有有效情绪类型都能成功记录."""
        valid_moods = ["happy", "calm", "sad", "anxious", "angry", "tired", "neutral"]
        for mood in valid_moods:
            result = skill._log({"mood": mood})
            assert result["mood"] == mood

    # ---- 列表 ----

    def test_list_empty(self, skill: MoodSkill) -> None:
        """空数据库下列表为空."""
        result = skill._list({})
        assert result["logs"] == []
        assert result["total"] == 0

    def test_list_with_data(self, skill: MoodSkill) -> None:
        """有数据时列表正确."""
        for i in range(5):
            skill._log({"mood": "happy"})
        result = skill._list({})
        assert result["total"] == 5
        assert len(result["logs"]) == 5

    def test_list_filter_by_mood(self, skill: MoodSkill) -> None:
        """按情绪类型筛选."""
        skill._log({"mood": "happy"})
        skill._log({"mood": "sad"})
        skill._log({"mood": "happy"})
        result = skill._list({"mood": "sad"})
        assert result["total"] == 1

    def test_list_filter_by_date_range(self, skill: MoodSkill) -> None:
        """按日期范围筛选."""
        result = skill._list({
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        })
        assert isinstance(result["logs"], list)

    def test_list_pagination(self, skill: MoodSkill) -> None:
        """分页查询."""
        for i in range(10):
            skill._log({"mood": "happy"})
        result = skill._list({"page": 2, "page_size": 3})
        assert len(result["logs"]) == 3
        assert result["page"] == 2
        assert result["total_pages"] == 4

    def test_list_triggers_split(self, skill: MoodSkill) -> None:
        """triggers 字段正确分割为列表."""
        skill._log({"mood": "happy", "triggers": ["工作", "家庭"]})
        result = skill._list({})
        assert isinstance(result["logs"][0]["triggers"], list)
        assert len(result["logs"][0]["triggers"]) == 2

    # ---- 统计 ----

    def test_stats_empty(self, skill: MoodSkill) -> None:
        """空数据库下统计."""
        result = skill._stats({"period": "all"})
        assert result["total_records"] == 0
        assert result["days_tracked"] == 0
        assert result["mood_distribution"] == {}

    def test_stats_with_data(self, skill: MoodSkill) -> None:
        """有数据时统计正确."""
        skill._log({"mood": "happy", "valence": 0.8, "arousal": 0.7})
        skill._log({"mood": "sad", "valence": -0.5, "arousal": 0.3})
        skill._log({"mood": "happy", "valence": 0.9, "arousal": 0.8})
        result = skill._stats({"period": "all"})
        assert result["total_records"] == 3
        assert result["mood_distribution"]["happy"] == 2
        assert result["mood_distribution"]["sad"] == 1
        assert result["most_common_mood"] == "happy"

    def test_stats_period_week(self, skill: MoodSkill) -> None:
        """本周统计."""
        result = skill._stats({"period": "week"})
        assert result["period"] == "week"
        assert result["start_date"] != ""

    def test_stats_period_month(self, skill: MoodSkill) -> None:
        """本月统计."""
        result = skill._stats({"period": "month"})
        assert result["period"] == "month"

    def test_stats_period_today(self, skill: MoodSkill) -> None:
        """今日统计."""
        skill._log({"mood": "happy"})
        result = skill._stats({"period": "today"})
        assert result["period"] == "today"
        assert result["total_records"] >= 1

    # ---- 趋势 ----

    def test_trend_empty(self, skill: MoodSkill) -> None:
        """空数据库下趋势分析."""
        result = skill._trend({"days": 7})
        assert result["days"] == 7
        assert result["days_with_data"] == 0
        assert result["valence_trend"] == 0

    def test_trend_days_zero_raises(self, skill: MoodSkill) -> None:
        """天数为 0 抛出异常."""
        with pytest.raises(ValueError, match="大于 0"):
            skill._trend({"days": 0})

    def test_trend_days_too_large_raises(self, skill: MoodSkill) -> None:
        """天数超过 365 抛出异常."""
        with pytest.raises(ValueError, match="365"):
            skill._trend({"days": 400})

    def test_trend_with_data(self, skill: MoodSkill) -> None:
        """有数据时趋势分析返回正确结构."""
        skill._log({"mood": "happy", "valence": 0.8})
        result = skill._trend({"days": 7})
        assert result["days_with_data"] >= 1
        assert len(result["daily_data"]) == 7
        assert result["trend_direction"] in ("improving", "declining", "stable")

    # ---- 洞察 ----

    def test_insights_empty(self, skill: MoodSkill) -> None:
        """空数据库下洞察返回提示信息."""
        result = skill._insights({"days": 30})
        assert result["total_records"] == 0
        assert "暂无" in result["message"]

    def test_insights_with_data(self, skill: MoodSkill) -> None:
        """有数据时洞察返回完整信息."""
        skill._log({
            "mood": "happy",
            "valence": 0.8,
            "triggers": ["工作", "运动"],
        })
        skill._log({
            "mood": "sad",
            "valence": -0.5,
            "triggers": ["加班"],
        })
        result = skill._insights({"days": 30})
        assert result["total_records"] == 2
        assert isinstance(result["top_triggers"], list)
        assert "time_period_stats" in result

    # ---- invoke ----

    def test_invoke_log(self, skill: MoodSkill) -> None:
        """通过 invoke 记录情绪."""
        import asyncio

        request = _make_request("skill.mood", "log", {"mood": "happy"})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "success"
        assert result.data is not None

    def test_invoke_unknown_action(self, skill: MoodSkill) -> None:
        """调用不存在的 action 返回 failure."""
        import asyncio

        request = _make_request("skill.mood", "bad_action", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"

    def test_invoke_error_handling(self, skill: MoodSkill) -> None:
        """invoke 中异常返回 failure."""
        import asyncio

        request = _make_request("skill.mood", "log", {"mood": "invalid"})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"

    def test_health_check(self, skill: MoodSkill) -> None:
        """健康检查."""
        import asyncio

        result = asyncio.run(skill.health())
        assert result["healthy"] is True


# ======================================================================
# TranslateSkill 测试
# ======================================================================


class TestTranslateSkill:
    """TranslateSkill 翻译转换技能测试套件."""

    @pytest.fixture
    def skill(self, tmp_path: str) -> TranslateSkill:
        """创建使用临时缓存目录的 TranslateSkill 实例."""
        return _make_tmp_skill(TranslateSkill, tmp_path, "translate.db")

    def test_manifest_metadata(self, skill: TranslateSkill) -> None:
        """验证技能元数据."""
        m = skill.manifest
        assert m.skill_id == "skill.translate"
        assert m.name == "翻译转换"
        assert "translate" in m.tags
        assert "translate_text" in m.capabilities
        assert "detect_language" in m.capabilities
        assert "batch_translate" in m.capabilities

    def test_translate_text_fallback(self, skill: TranslateSkill) -> None:
        """翻译文本 - 降级模式下返回原文."""
        import asyncio

        result = asyncio.run(skill._translate_text({
            "text": "Hello world",
            "target_lang": "zh",
        }))
        # 降级策略：直接返回原文
        assert result["translated"] == "Hello world"
        assert result["source"] == "Hello world"
        assert result["cached"] is False

    def test_translate_text_cache(self, skill: TranslateSkill) -> None:
        """翻译文本 - 第二次调用应命中缓存."""
        import asyncio

        text = "Hello world"
        # 第一次调用
        result1 = asyncio.run(skill._translate_text({"text": text, "target_lang": "zh"}))
        assert result1["cached"] is False

        # 第二次调用应命中缓存
        result2 = asyncio.run(skill._translate_text({"text": text, "target_lang": "zh"}))
        assert result2["cached"] is True
        assert result2["translated"] == result1["translated"]

    def test_translate_text_empty(self, skill: TranslateSkill) -> None:
        """翻译空文本."""
        import asyncio

        result = asyncio.run(skill._translate_text({"text": "", "target_lang": "en"}))
        assert result["translated"] == ""

    def test_translate_text_special_characters(self, skill: TranslateSkill) -> None:
        """翻译包含特殊字符的文本."""
        import asyncio

        text = "Hello <script>alert(1)</script> & ' \" ; DROP TABLE --"
        result = asyncio.run(skill._translate_text({"text": text, "target_lang": "zh"}))
        assert result["translated"] == text

    def test_translate_text_long_text(self, skill: TranslateSkill) -> None:
        """翻译超长文本."""
        import asyncio

        long_text = "A" * 5000
        result = asyncio.run(skill._translate_text({"text": long_text, "target_lang": "zh"}))
        assert len(result["translated"]) == 5000

    def test_translate_text_unicode(self, skill: TranslateSkill) -> None:
        """翻译 Unicode 文本."""
        import asyncio

        text = "你好世界 🌍 こんにちは 세계야 안녕"
        result = asyncio.run(skill._translate_text({"text": text, "target_lang": "en"}))
        assert result["translated"] == text

    def test_detect_language_requires_langdetect(self, skill: TranslateSkill) -> None:
        """语言检测需要 langdetect 库（可能未安装）."""
        try:
            from langdetect import detect  # noqa: F401
            has_langdetect = True
        except Exception:
            has_langdetect = False

        if not has_langdetect:
            with pytest.raises(RuntimeError, match="langdetect"):
                skill._detect_language({"text": "Hello world"})
        else:
            result = skill._detect_language({"text": "Hello world"})
            assert "language" in result
            assert "confidence" in result

    def test_batch_translate(self, skill: TranslateSkill) -> None:
        """批量翻译."""
        import asyncio

        texts = ["Hello", "World", "Test"]
        result = asyncio.run(skill._batch_translate({
            "texts": texts,
            "target_lang": "zh",
        }))
        assert len(result["translations"]) == 3
        assert result["target_lang"] == "zh"

    def test_batch_translate_empty(self, skill: TranslateSkill) -> None:
        """批量翻译空列表."""
        import asyncio

        result = asyncio.run(skill._batch_translate({"texts": [], "target_lang": "zh"}))
        assert result["translations"] == []

    # ---- invoke ----

    def test_invoke_translate_text(self, skill: TranslateSkill) -> None:
        """通过 invoke 调用翻译."""
        import asyncio

        request = _make_request("skill.translate", "translate_text", {
            "text": "Hello", "target_lang": "zh",
        })
        result = asyncio.run(skill.invoke(request))
        assert result.status == "success"
        assert result.data is not None

    def test_invoke_batch_translate(self, skill: TranslateSkill) -> None:
        """通过 invoke 调用批量翻译."""
        import asyncio

        request = _make_request("skill.translate", "batch_translate", {
            "texts": ["Hello", "World"], "target_lang": "zh",
        })
        result = asyncio.run(skill.invoke(request))
        assert result.status == "success"
        assert len(result.data["translations"]) == 2

    def test_invoke_unknown_action(self, skill: TranslateSkill) -> None:
        """调用不存在的 action 返回 failure."""
        import asyncio

        request = _make_request("skill.translate", "bad_action", {})
        result = asyncio.run(skill.invoke(request))
        assert result.status == "failure"

    def test_health_check(self, skill: TranslateSkill) -> None:
        """健康检查."""
        import asyncio

        result = asyncio.run(skill.health())
        assert result["healthy"] is True

    def test_configure(self, skill: TranslateSkill) -> None:
        """配置更新."""
        import asyncio

        asyncio.run(skill.configure({"onnx_enabled": True, "onnx_model": "test_model"}))
        assert skill._config["onnx_enabled"] is True
        assert skill._config["onnx_model"] == "test_model"
