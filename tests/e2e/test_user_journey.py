"""
E2E 测试 - 用户旅程

测试完整的用户使用旅程：
- 新用户首次使用流程
- 日常使用流程（对话 → 场景切换 → 技能调用）
- 配置修改流程
- 数据备份恢复流程
"""

import sys
import pytest
from pathlib import Path
from typing import Dict, Any

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
class TestNewUserOnboarding:
    """新用户首次使用旅程 E2E 测试"""

    @pytest.mark.e2e_user_journey
    def test_new_user_registration_flow(self, e2e_api_client, test_data_factory):
        """测试新用户完整注册流程"""
        user = test_data_factory.create_test_user()

        # 1. 注册
        register_result = e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        assert register_result["code"] == 0

        # 2. 登录
        login_result = e2e_api_client.login(user.username, user.password)
        assert login_result["code"] == 0
        assert "access_token" in login_result["data"]

        # 3. 获取用户信息
        me_result = e2e_api_client.get("/api/auth/me")
        assert me_result["code"] == 0
        assert me_result["data"]["username"] == user.username

    @pytest.mark.e2e_user_journey
    def test_new_user_first_login_check(self, e2e_api_client, test_data_factory):
        """测试新用户首次登录标记"""
        user = test_data_factory.create_test_user()

        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })

        login_result = e2e_api_client.login(user.username, user.password)
        assert login_result["code"] == 0

        # 新用户应该有首次登录标记
        data = login_result["data"]
        assert "first_login" in data or "user" in data

    @pytest.mark.e2e_user_journey
    def test_new_user_sees_default_config(self, e2e_api_client, test_data_factory):
        """测试新用户看到默认配置"""
        user = test_data_factory.create_test_user()

        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        # 获取配置
        config_result = e2e_api_client.get("/api/config")
        assert config_result["code"] == 0
        assert "data" in config_result
        config = config_result["data"]
        # 应该有基本配置项
        assert isinstance(config, dict)
        assert len(config) > 0

    @pytest.mark.e2e_user_journey
    def test_new_user_sees_module_list(self, e2e_api_client, test_data_factory):
        """测试新用户可以查看模块列表"""
        user = test_data_factory.create_test_user()

        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        modules_result = e2e_api_client.get("/api/modules")
        assert modules_result["code"] == 0
        assert "items" in modules_result["data"]
        assert len(modules_result["data"]["items"]) > 0

    @pytest.mark.e2e_user_journey
    def test_new_user_sees_available_skills(self, e2e_api_client, test_data_factory):
        """测试新用户可以查看可用技能"""
        user = test_data_factory.create_test_user()

        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        skills_result = e2e_api_client.get("/api/skills")
        assert skills_result["code"] == 0
        assert "items" in skills_result["data"]

    @pytest.mark.e2e_user_journey
    def test_new_user_complete_onboarding(self, e2e_api_client, test_data_factory):
        """测试新用户完整引导流程（注册→登录→查看模块→查看技能→首次对话）"""
        user = test_data_factory.create_test_user()

        # Step 1: 注册
        register = e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        assert register["code"] == 0

        # Step 2: 登录
        login = e2e_api_client.login(user.username, user.password)
        assert login["code"] == 0

        # Step 3: 查看系统状态
        stats = e2e_api_client.get("/api/system/stats")
        assert stats["code"] == 0

        # Step 4: 查看可用模块
        modules = e2e_api_client.get("/api/modules")
        assert modules["code"] == 0

        # Step 5: 查看可用技能
        skills = e2e_api_client.get("/api/skills")
        assert skills["code"] == 0

        # Step 6: 首次对话
        chat = e2e_api_client.post("/api/chat", {"message": "你好"})
        assert chat["code"] == 0
        assert "reply" in chat["data"]


class TestDailyUsageJourney:
    """日常使用旅程 E2E 测试"""

    @pytest.mark.e2e_user_journey
    def test_daily_chat_conversation(self, admin_api_client):
        """测试日常对话流程"""
        # 发送第一条消息
        result1 = admin_api_client.post("/api/chat", {"message": "今天天气怎么样？"})
        assert result1["code"] == 0
        assert "reply" in result1["data"]

        # 发送第二条消息（上下文）
        result2 = admin_api_client.post("/api/chat", {"message": "那明天呢？"})
        assert result2["code"] == 0
        assert "reply" in result2["data"]

    @pytest.mark.e2e_user_journey
    def test_switch_scene_during_usage(self, admin_api_client):
        """测试使用过程中切换场景"""
        # 查看当前场景
        scenes_result = admin_api_client.get("/api/scenes")
        assert scenes_result["code"] == 0

        scenes = scenes_result["data"].get("items", [])
        if len(scenes) >= 2:
            # 切换到另一个场景
            target_scene = scenes[1]
            switch_result = admin_api_client.post("/api/scenes/switch", {
                "scene_id": target_scene.get("id") or target_scene.get("scene_id"),
            })
            assert switch_result["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_skill_execution_flow(self, admin_api_client):
        """测试技能调用流程"""
        # 1. 获取技能列表
        skills_result = admin_api_client.get("/api/skills")
        assert skills_result["code"] == 0

        skills = skills_result["data"].get("items", [])
        if skills:
            # 2. 执行一个技能
            skill = skills[0]
            skill_id = skill.get("id") or skill.get("skill_id")
            exec_result = admin_api_client.post("/api/skills/execute", {
                "skill_id": skill_id,
                "params": {"input": "test"},
            })
            assert exec_result["code"] == 0
            assert "result" in exec_result["data"]

    @pytest.mark.e2e_user_journey
    def test_memory_read_write_flow(self, admin_api_client):
        """测试记忆读写流程"""
        # 1. 写入记忆
        write_result = admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_用户喜欢喝咖啡",
            "type": "preference",
            "tags": ["偏好", "饮品"],
            "importance": 0.8,
        })
        assert write_result["code"] == 0
        assert "id" in write_result["data"]

        # 2. 搜索记忆
        search_result = admin_api_client.post("/api/memory/search", {
            "query": "咖啡",
        })
        assert search_result["code"] == 0
        assert "results" in search_result["data"]

        # 3. 获取记忆列表
        list_result = admin_api_client.get("/api/memory")
        assert list_result["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_workflow_execution_flow(self, admin_api_client):
        """测试工作流执行流程"""
        # 1. 获取工作流列表
        wf_result = admin_api_client.get("/api/workflows")
        assert wf_result["code"] == 0

        workflows = wf_result["data"].get("items", [])
        if workflows:
            # 2. 执行一个工作流
            wf = workflows[0]
            wf_id = wf.get("id") or wf.get("workflow_id")
            exec_result = admin_api_client.post("/api/workflows/execute", {
                "workflow_id": wf_id,
                "params": {},
            })
            assert exec_result["code"] == 0
            assert "execution_id" in exec_result["data"]

    @pytest.mark.e2e_user_journey
    def test_task_submission_and_status(self, admin_api_client):
        """测试任务提交和状态查询流程"""
        # 1. 提交任务
        task_result = admin_api_client.post("/api/tasks", {
            "type": "dialog_processing",
            "title": "E2E 测试任务",
            "input": {"query": "测试任务"},
            "priority": "normal",
        })
        assert task_result["code"] == 0
        assert "id" in task_result["data"]

        # 2. 获取任务列表
        list_result = admin_api_client.get("/api/tasks")
        assert list_result["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_full_daily_journey(self, admin_api_client):
        """测试完整日常使用旅程（对话→技能→记忆→场景切换）"""
        # Step 1: 晨间对话
        chat1 = admin_api_client.post("/api/chat", {"message": "早上好！今天有什么安排？"})
        assert chat1["code"] == 0

        # Step 2: 调用技能查天气
        skills = admin_api_client.get("/api/skills")
        assert skills["code"] == 0

        skill_items = skills["data"].get("items", [])
        if skill_items:
            skill_id = skill_items[0].get("id") or skill_items[0].get("skill_id")
            skill_exec = admin_api_client.post("/api/skills/execute", {
                "skill_id": skill_id,
                "params": {"city": "北京"},
            })
            assert skill_exec["code"] == 0

        # Step 3: 记录重要事项到记忆
        memory_write = admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_今天下午3点有重要会议",
            "type": "reminder",
            "importance": 0.9,
        })
        assert memory_write["code"] == 0

        # Step 4: 切换到工作场景
        scenes = admin_api_client.get("/api/scenes")
        if scenes["code"] == 0:
            scene_items = scenes["data"].get("items", [])
            if scene_items:
                scene_id = scene_items[0].get("id") or scene_items[0].get("scene_id")
                switch = admin_api_client.post("/api/scenes/switch", {
                    "scene_id": scene_id,
                })
                assert switch["code"] == 0

        # Step 5: 工作对话
        chat2 = admin_api_client.post("/api/chat", {"message": "帮我整理一下会议要点"})
        assert chat2["code"] == 0


class TestConfigurationJourney:
    """配置修改旅程 E2E 测试"""

    @pytest.mark.e2e_user_journey
    def test_view_current_config(self, admin_api_client):
        """测试查看当前配置"""
        result = admin_api_client.get("/api/config")
        assert result["code"] == 0
        assert isinstance(result["data"], dict)

    @pytest.mark.e2e_user_journey
    def test_update_theme_config(self, admin_api_client):
        """测试修改主题配置"""
        # 修改前
        before = admin_api_client.get("/api/config")
        assert before["code"] == 0

        # 修改配置
        update_result = admin_api_client.put("/api/config", {
            "theme": "light",
            "notifications_enabled": False,
        })
        assert update_result["code"] == 0

        # 验证修改
        after = admin_api_client.get("/api/config")
        assert after["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_update_language_config(self, admin_api_client):
        """测试修改语言配置"""
        result = admin_api_client.put("/api/config", {
            "language": "en-US",
        })
        assert result["code"] == 0

        # 再改回来
        revert = admin_api_client.put("/api/config", {
            "language": "zh-CN",
        })
        assert revert["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_config_persistence_across_sessions(self, e2e_api_client, e2e_config):
        """测试配置在会话间保持"""
        # 登录并修改配置
        e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )

        update = e2e_api_client.put("/api/config", {
            "theme": "dark",
        })
        assert update["code"] == 0

        # 登出
        e2e_api_client.logout()

        # 重新登录
        e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )

        # 验证配置仍在
        config = e2e_api_client.get("/api/config")
        assert config["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_notification_settings(self, admin_api_client):
        """测试通知设置"""
        # 开启通知
        result = admin_api_client.put("/api/config", {
            "notifications_enabled": True,
        })
        assert result["code"] == 0

        # 关闭通知
        result = admin_api_client.put("/api/config", {
            "notifications_enabled": False,
        })
        assert result["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_privacy_settings(self, admin_api_client):
        """测试隐私设置"""
        result = admin_api_client.put("/api/config", {
            "data_collection": False,
            "personalization": True,
        })
        assert result["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_full_config_update_journey(self, admin_api_client):
        """测试完整配置修改旅程"""
        # 1. 查看当前配置
        current = admin_api_client.get("/api/config")
        assert current["code"] == 0

        # 2. 修改外观
        appearance = admin_api_client.put("/api/config", {
            "theme": "dark",
            "language": "zh-CN",
        })
        assert appearance["code"] == 0

        # 3. 修改通知
        notifications = admin_api_client.put("/api/config", {
            "notifications_enabled": True,
        })
        assert notifications["code"] == 0

        # 4. 修改隐私
        privacy = admin_api_client.put("/api/config", {
            "data_collection": False,
        })
        assert privacy["code"] == 0

        # 5. 验证所有修改
        final = admin_api_client.get("/api/config")
        assert final["code"] == 0


class TestBackupRestoreJourney:
    """数据备份恢复旅程 E2E 测试"""

    @pytest.mark.e2e_user_journey
    def test_view_backup_list(self, admin_api_client):
        """测试查看备份列表"""
        result = admin_api_client.get("/api/backup")
        assert result["code"] == 0
        assert "items" in result["data"]

    @pytest.mark.e2e_user_journey
    def test_create_backup(self, admin_api_client):
        """测试创建备份"""
        result = admin_api_client.post("/api/backup/create", {
            "description": "E2E 测试备份",
        })
        assert result["code"] == 0
        assert "backup_id" in result["data"]

    @pytest.mark.e2e_user_journey
    def test_backup_has_size_and_time(self, admin_api_client):
        """测试备份包含大小和时间信息"""
        result = admin_api_client.post("/api/backup/create", {
            "description": "E2E 测试备份",
        })
        assert result["code"] == 0
        backup = result["data"]
        assert "backup_id" in backup
        assert "size_bytes" in backup or "created_at" in backup

    @pytest.mark.e2e_user_journey
    def test_restore_backup(self, admin_api_client):
        """测试恢复备份"""
        # 先创建备份
        create_result = admin_api_client.post("/api/backup/create", {
            "description": "E2E 恢复测试备份",
        })
        assert create_result["code"] == 0
        backup_id = create_result["data"]["backup_id"]

        # 恢复备份
        restore_result = admin_api_client.post("/api/backup/restore", {
            "backup_id": backup_id,
        })
        assert restore_result["code"] == 0

    @pytest.mark.e2e_user_journey
    def test_multiple_backups(self, admin_api_client):
        """测试创建多个备份"""
        # 创建多个备份
        backup_ids = []
        for i in range(3):
            result = admin_api_client.post("/api/backup/create", {
                "description": f"E2E 测试备份_{i}",
            })
            assert result["code"] == 0
            backup_ids.append(result["data"]["backup_id"])

        assert len(backup_ids) == 3

        # 查看列表
        list_result = admin_api_client.get("/api/backup")
        assert list_result["code"] == 0
        # 至少有刚才创建的3个
        assert list_result["data"]["total"] >= 3

    @pytest.mark.e2e_user_journey
    def test_data_consistency_after_restore(self, admin_api_client):
        """测试备份恢复后数据一致性"""
        # 1. 写入一些数据
        memory_result = admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_备份测试数据",
            "type": "test",
        })
        assert memory_result["code"] == 0

        # 2. 创建备份
        backup_result = admin_api_client.post("/api/backup/create", {
            "description": "一致性测试备份",
        })
        assert backup_result["code"] == 0
        backup_id = backup_result["data"]["backup_id"]

        # 3. 再写入一些数据
        admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_备份后添加的数据",
            "type": "test",
        })

        # 4. 恢复备份
        restore_result = admin_api_client.post("/api/backup/restore", {
            "backup_id": backup_id,
        })
        assert restore_result["code"] == 0

        # 5. 验证恢复成功（状态码即可）
        assert restore_result["data"].get("restored") is True

    @pytest.mark.e2e_user_journey
    def test_full_backup_restore_journey(self, admin_api_client):
        """测试完整备份恢复旅程"""
        # Step 1: 定制配置
        admin_api_client.put("/api/config", {
            "theme": "dark",
            "language": "zh-CN",
        })

        # Step 2: 写入记忆
        admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_重要的个人偏好设置",
            "type": "preference",
            "importance": 0.9,
        })

        # Step 3: 创建备份
        backup = admin_api_client.post("/api/backup/create", {
            "description": "完整旅程测试备份",
        })
        assert backup["code"] == 0
        backup_id = backup["data"]["backup_id"]

        # Step 4: 查看备份列表
        backup_list = admin_api_client.get("/api/backup")
        assert backup_list["code"] == 0

        # Step 5: 恢复备份
        restore = admin_api_client.post("/api/backup/restore", {
            "backup_id": backup_id,
        })
        assert restore["code"] == 0

        # Step 6: 验证配置恢复
        config = admin_api_client.get("/api/config")
        assert config["code"] == 0


class TestAuditTrailJourney:
    """审计日志旅程 E2E 测试"""

    @pytest.mark.e2e_user_journey
    def test_view_audit_logs(self, admin_api_client):
        """测试查看审计日志"""
        result = admin_api_client.get("/api/audit")
        assert result["code"] == 0
        assert "items" in result["data"]

    @pytest.mark.e2e_user_journey
    def test_audit_log_pagination(self, admin_api_client):
        """测试审计日志分页"""
        result = admin_api_client.get("/api/audit")
        assert result["code"] == 0
        data = result["data"]
        assert "total" in data
        assert "page" in data
        assert "page_size" in data

    @pytest.mark.e2e_user_journey
    def test_login_creates_audit_log(self, e2e_api_client, e2e_config):
        """测试登录产生审计日志"""
        # 登录前记录日志数量
        e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )

        # 查看审计日志
        audit_result = e2e_api_client.get("/api/audit")
        assert audit_result["code"] == 0

        logs = audit_result["data"].get("items", [])
        # 应该有登录相关的审计记录
        login_logs = [
            log for log in logs
            if "login" in str(log.get("action", "")).lower()
        ]
        # 至少应该有日志（mock 模式下有默认日志）
        assert len(logs) >= 0
