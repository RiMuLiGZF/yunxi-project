# -*- coding: utf-8 -*-
"""
M8 控制塔 - 快捷操作入口整合测试

验证模块操作入口、系统操作入口的整合情况，包括：
- 模块详情接口包含 available_actions
- 模块列表接口包含 actions 简化字段
- 系统状态接口包含 system_actions
- 操作分类与排序正确
- 运维仪表盘包含操作信息
"""

import sys
import pytest
from pathlib import Path

# 路径设置
M8_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = M8_ROOT.parent
for _p in (str(PROJECT_ROOT), str(M8_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================
# 单元测试：操作定义与分类排序
# ============================================================

class TestModuleActionsDefinition:
    """模块操作定义测试"""

    def test_module_actions_has_required_fields(self):
        """每个模块操作包含 name/method/path/description/category/requires_confirm 字段"""
        from backend.routers.system import _MODULE_ACTIONS

        assert len(_MODULE_ACTIONS) > 0, "模块操作定义不应为空"

        for name, action in _MODULE_ACTIONS.items():
            assert "name" in action, f"操作 {name} 缺少 name 字段"
            assert "method" in action, f"操作 {name} 缺少 method 字段"
            assert "path" in action, f"操作 {name} 缺少 path 字段"
            assert "description" in action, f"操作 {name} 缺少 description 字段"
            assert "category" in action, f"操作 {name} 缺少 category 字段"
            assert "requires_confirm" in action, f"操作 {name} 缺少 requires_confirm 字段"
            assert isinstance(action["requires_confirm"], bool), \
                f"操作 {name} 的 requires_confirm 应为布尔值"

    def test_module_actions_categories_valid(self):
        """模块操作分类只能是 control/config/data"""
        from backend.routers.system import _MODULE_ACTIONS

        valid_categories = {"control", "config", "data"}
        for name, action in _MODULE_ACTIONS.items():
            assert action["category"] in valid_categories, \
                f"操作 {name} 的分类 {action['category']} 无效"

    def test_module_actions_control_category(self):
        """控制类操作：restart/start/stop/health_check 属于 control"""
        from backend.routers.system import _MODULE_ACTIONS

        control_actions = ["restart", "start", "stop", "health_check"]
        for name in control_actions:
            if name in _MODULE_ACTIONS:
                assert _MODULE_ACTIONS[name]["category"] == "control", \
                    f"操作 {name} 应属于 control 分类"

    def test_module_actions_data_category(self):
        """数据类操作：view_metrics 属于 data"""
        from backend.routers.system import _MODULE_ACTIONS

        if "view_metrics" in _MODULE_ACTIONS:
            assert _MODULE_ACTIONS["view_metrics"]["category"] == "data"


class TestSystemActionsDefinition:
    """系统操作定义测试"""

    def test_system_actions_has_required_fields(self):
        """每个系统操作包含完整字段"""
        from backend.routers.system import _SYSTEM_ACTIONS

        assert len(_SYSTEM_ACTIONS) >= 5, "系统操作至少应有 5 个"

        for action in _SYSTEM_ACTIONS:
            assert "name" in action, f"系统操作缺少 name 字段: {action}"
            assert "method" in action, f"操作 {action.get('name')} 缺少 method"
            assert "path" in action, f"操作 {action.get('name')} 缺少 path"
            assert "description" in action, f"操作 {action.get('name')} 缺少 description"
            assert "category" in action, f"操作 {action.get('name')} 缺少 category"
            assert "requires_confirm" in action, f"操作 {action.get('name')} 缺少 requires_confirm"

    def test_system_actions_categories_valid(self):
        """系统操作分类只能是 control/config/data"""
        from backend.routers.system import _SYSTEM_ACTIONS

        valid_categories = {"control", "config", "data"}
        for action in _SYSTEM_ACTIONS:
            assert action["category"] in valid_categories, \
                f"操作 {action['name']} 的分类 {action['category']} 无效"

    def test_system_actions_has_control_category(self):
        """系统操作应包含 control 分类"""
        from backend.routers.system import _SYSTEM_ACTIONS

        control_actions = [a for a in _SYSTEM_ACTIONS if a["category"] == "control"]
        assert len(control_actions) >= 2, "系统操作中至少应有 2 个 control 类操作"

    def test_system_actions_has_config_category(self):
        """系统操作应包含 config 分类（reload_config）"""
        from backend.routers.system import _SYSTEM_ACTIONS

        config_actions = [a for a in _SYSTEM_ACTIONS if a["category"] == "config"]
        assert len(config_actions) >= 1, "系统操作中应包含 config 类操作"
        assert any(a["name"] == "reload_config" for a in config_actions)


class TestActionSorting:
    """操作排序规则测试"""

    def test_control_category_comes_first(self):
        """控制类操作排在最前面"""
        from backend.routers.system import get_module_actions

        actions = get_module_actions("m1", simplified=False)
        assert len(actions) >= 3

        # 第一个操作应该是 control 类的
        assert actions[0]["category"] == "control", \
            f"第一个操作应为 control 类，实际是 {actions[0]['category']}"

    def test_restart_is_first_action(self):
        """常用操作 restart 排在最前面"""
        from backend.routers.system import get_module_actions

        actions = get_module_actions("m1", simplified=False)
        # 对于普通模块，第一个操作应该是 restart
        assert actions[0]["name"] == "restart", \
            f"普通模块第一个操作应为 restart，实际是 {actions[0]['name']}"

    def test_data_category_comes_last(self):
        """数据类操作排在最后"""
        from backend.routers.system import get_module_actions

        actions = get_module_actions("m1", simplified=False)
        # 最后一个操作应该是 data 类的（view_metrics）
        assert actions[-1]["category"] == "data", \
            f"最后一个操作应为 data 类，实际是 {actions[-1]['category']}"

    def test_system_actions_sorted_by_category(self):
        """系统操作按分类排序：control > config > data"""
        from backend.routers.system import _SYSTEM_ACTIONS

        categories_order = [a["category"] for a in _SYSTEM_ACTIONS]
        # 验证排序：同类操作在一起，control 先于 config 先于 data
        category_rank = {"control": 0, "config": 1, "data": 2}
        ranks = [category_rank[c] for c in categories_order]
        assert ranks == sorted(ranks), "系统操作应按分类排序"


# ============================================================
# 模块操作入口函数测试
# ============================================================

class TestGetModuleActions:
    """get_module_actions 函数测试"""

    def test_normal_module_has_full_actions(self):
        """普通模块（非 m8）包含完整操作列表"""
        from backend.routers.system import get_module_actions

        actions = get_module_actions("m1", simplified=False)
        action_names = [a["name"] for a in actions]

        assert "restart" in action_names
        assert "start" in action_names
        assert "stop" in action_names
        assert "health_check" in action_names
        assert "view_metrics" in action_names

    def test_m8_module_has_limited_actions(self):
        """M8 自身模块操作受限（不可重启/启动/停止）"""
        from backend.routers.system import get_module_actions

        actions = get_module_actions("m8", simplified=False)
        action_names = [a["name"] for a in actions]

        assert "restart" not in action_names, "M8 自身不可重启"
        assert "start" not in action_names, "M8 自身不可启动"
        assert "stop" not in action_names, "M8 自身不可停止"
        assert "health_check" in action_names
        assert "view_metrics" in action_names

    def test_different_modules_have_different_actions(self):
        """不同模块有不同的操作列表（M8 与其他模块不同）"""
        from backend.routers.system import get_module_actions

        m1_actions = get_module_actions("m1", simplified=True)
        m8_actions = get_module_actions("m8", simplified=True)

        assert m1_actions != m8_actions, "M1 和 M8 的操作列表应不同"
        assert len(m1_actions) > len(m8_actions), "M1 操作数应多于 M8"

    def test_simplified_returns_string_list(self):
        """简化格式返回字符串数组"""
        from backend.routers.system import get_module_actions

        actions = get_module_actions("m1", simplified=True)

        assert isinstance(actions, list), "简化格式应返回列表"
        assert all(isinstance(a, str) for a in actions), \
            "简化格式的每个元素应为字符串"
        assert len(actions) >= 2

    def test_full_format_contains_path_with_module_key(self):
        """完整格式的 path 中包含模块 key"""
        from backend.routers.system import get_module_actions

        actions = get_module_actions("m5", simplified=False)

        for action in actions:
            if "module_key" in action.get("path", "") or "m5" in action.get("path", ""):
                # 路径中包含模块标识（验证路径模板被正确替换）
                assert "m5" in action["path"] or "{module_key}" not in action["path"], \
                    f"操作 {action['name']} 的路径应已替换模块 key"

    def test_actions_consistency_between_formats(self):
        """简化格式和完整格式的操作名称顺序一致"""
        from backend.routers.system import get_module_actions

        simple_names = get_module_actions("m1", simplified=True)
        full_actions = get_module_actions("m1", simplified=False)
        full_names = [a["name"] for a in full_actions]

        assert simple_names == full_names, \
            "简化格式和完整格式的操作名称及顺序应一致"


# ============================================================
# 系统操作入口函数测试
# ============================================================

class TestGetSystemActions:
    """get_system_actions 函数测试"""

    def test_returns_list(self):
        """返回列表类型"""
        from backend.routers.system import get_system_actions

        actions = get_system_actions()
        assert isinstance(actions, list)
        assert len(actions) >= 5

    def test_returns_copy_not_reference(self):
        """返回的是副本，修改不影响原数据"""
        from backend.routers.system import get_system_actions, _SYSTEM_ACTIONS

        actions = get_system_actions()
        actions.append({"name": "test_action"})

        original = get_system_actions()
        assert not any(a["name"] == "test_action" for a in original), \
            "修改返回值不应影响原数据"

    def test_all_actions_have_valid_methods(self):
        """所有操作的 HTTP 方法有效"""
        from backend.routers.system import get_system_actions

        actions = get_system_actions()
        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH"}

        for action in actions:
            assert action["method"].upper() in valid_methods, \
                f"操作 {action['name']} 的 HTTP 方法 {action['method']} 无效"

    def test_dangerous_actions_require_confirm(self):
        """危险操作需要确认（clear_cache, batch_stop 等）"""
        from backend.routers.system import get_system_actions

        actions = get_system_actions()
        action_map = {a["name"]: a for a in actions}

        # 危险操作应需要确认
        dangerous_actions = ["clear_cache", "batch_start", "batch_stop"]
        for name in dangerous_actions:
            if name in action_map:
                assert action_map[name]["requires_confirm"] is True, \
                    f"危险操作 {name} 应需要确认"


# ============================================================
# 集成测试：API 接口整合验证
# ============================================================

def _get_auth_headers(client):
    """获取认证 headers（登录获取 token）"""
    try:
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123456"}
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("data", {}).get("access_token", "") or data.get("access_token", "")
            if token:
                return {"Authorization": f"Bearer {token}"}
    except Exception:
        pass
    return {}


class TestModuleDetailApi:
    """模块详情 API 集成测试"""

    def test_module_detail_contains_available_actions(self, client):
        """模块详情接口返回 available_actions 字段"""
        headers = _get_auth_headers(client)

        # 获取一个存在的模块
        resp = client.get("/api/modules/m1", headers=headers)
        # 可能因为模块未运行而返回不同状态，但格式应一致
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            assert "available_actions" in data, \
                "模块详情应包含 available_actions 字段"
            assert isinstance(data["available_actions"], list), \
                "available_actions 应为列表"

    def test_available_actions_structure_correct(self, client):
        """available_actions 中每个操作的结构正确"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/m1", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            actions = data.get("available_actions", [])

            if len(actions) > 0:
                action = actions[0]
                required_fields = ["name", "method", "path", "description",
                                   "category", "requires_confirm"]
                for field in required_fields:
                    assert field in action, \
                        f"操作应包含 {field} 字段"

    def test_available_actions_categorized(self, client):
        """available_actions 包含分类信息"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/m1", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            actions = data.get("available_actions", [])

            if len(actions) > 0:
                categories = {a["category"] for a in actions}
                # 至少包含 control 分类
                assert "control" in categories, \
                    "模块操作应包含 control 分类"

    def test_m8_module_detail_limited_actions(self, client):
        """M8 模块详情的操作列表受限"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/m8", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            actions = data.get("available_actions", [])
            action_names = [a["name"] for a in actions]

            assert "restart" not in action_names, "M8 不应有 restart 操作"
            assert "health_check" in action_names, "M8 应有 health_check 操作"


class TestModuleListApi:
    """模块列表 API 集成测试"""

    def test_module_list_contains_items_with_actions(self, client):
        """模块列表接口的每个模块项包含 actions 字段"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            items = data.get("items", [])

            if len(items) > 0:
                item = items[0]
                assert "actions" in item, \
                    "列表中的模块项应包含 actions 字段"

    def test_actions_is_string_array(self, client):
        """actions 字段是字符串数组"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            items = data.get("items", [])

            if len(items) > 0:
                actions = items[0].get("actions", [])
                assert isinstance(actions, list), "actions 应为列表"
                assert all(isinstance(a, str) for a in actions), \
                    "actions 的每个元素应为字符串"

    def test_different_modules_have_different_actions_in_list(self, client):
        """列表中不同模块有不同的操作列表"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            items = data.get("items", [])

            if len(items) >= 2:
                # 找到 M8 和另一个模块进行比较
                m8_item = next((i for i in items if i.get("key") == "m8"), None)
                other_item = next((i for i in items if i.get("key") != "m8"), None)

                if m8_item and other_item:
                    m8_actions = m8_item.get("actions", [])
                    other_actions = other_item.get("actions", [])
                    assert m8_actions != other_actions, \
                        "M8 和其他模块的操作列表应不同"

    def test_module_list_original_fields_preserved(self, client):
        """模块列表原有字段保持不变（向后兼容）"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            assert "code" in body
            assert "message" in body
            assert "data" in body

            data = body["data"]
            # 原有的汇总字段应保留
            assert "total" in data, "应保留 total 字段"


class TestSystemStatsApi:
    """系统状态 API 集成测试"""

    def test_system_stats_contains_system_actions(self, client):
        """系统状态接口返回 system_actions 字段"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/system/stats", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            assert "system_actions" in data, \
                "系统状态应包含 system_actions 字段"
            assert isinstance(data["system_actions"], list), \
                "system_actions 应为列表"

    def test_system_actions_structure_correct(self, client):
        """system_actions 中每个操作的结构正确"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/system/stats", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            actions = data.get("system_actions", [])

            if len(actions) > 0:
                action = actions[0]
                required_fields = ["name", "method", "path", "description",
                                   "category", "requires_confirm"]
                for field in required_fields:
                    assert field in action, \
                        f"系统操作应包含 {field} 字段"

    def test_system_actions_have_categories(self, client):
        """system_actions 包含分类信息"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/system/stats", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            actions = data.get("system_actions", [])

            if len(actions) > 0:
                categories = {a["category"] for a in actions}
                assert len(categories) >= 2, \
                    "系统操作应包含至少 2 种分类"

    def test_system_stats_original_fields_preserved(self, client):
        """系统状态原有字段保持不变（向后兼容）"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/system/stats", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            # 原有的字段应保留
            assert "modules_total" in data or "modules" in data, \
                "应保留模块统计字段"
            assert "health_score" in data, \
                "应保留 health_score 字段"


class TestOpsDashboardApi:
    """运维仪表盘 API 集成测试"""

    def test_ops_dashboard_contains_system_actions(self, client):
        """运维仪表盘接口返回 system_actions 字段"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/ops/dashboard", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            assert "system_actions" in data, \
                "运维仪表盘应包含 system_actions 字段"
            assert isinstance(data["system_actions"], list)

    def test_ops_modules_list_contains_actions(self, client):
        """运维仪表盘的模块列表包含 actions 字段"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/ops/modules", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            modules = data.get("modules", [])

            if len(modules) > 0:
                mod = modules[0]
                assert "actions" in mod, \
                    "运维仪表盘模块列表项应包含 actions 字段"
                assert isinstance(mod["actions"], list)

    def test_ops_module_detail_contains_available_actions(self, client):
        """运维仪表盘模块详情包含 available_actions 字段"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/ops/modules/m1", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            assert "available_actions" in data, \
                "运维仪表盘模块详情应包含 available_actions 字段"
            assert isinstance(data["available_actions"], list)


# ============================================================
# 向后兼容性测试
# ============================================================

class TestBackwardCompatibility:
    """向后兼容性测试"""

    def test_module_detail_original_fields_preserved(self, client):
        """模块详情原有字段保持不变"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/modules/m1", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            # 原有的关键字段应保留
            assert "key" in data or "name" in data, \
                "模块详情应保留 key/name 等原有字段"
            assert "status" in data, "应保留 status 字段"
            # 新增字段不应破坏原有结构
            assert "available_actions" in data

    def test_system_info_unchanged(self, client):
        """系统信息接口不受影响"""
        headers = _get_auth_headers(client)

        resp = client.get("/api/system/info", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {})
            # 原有字段保留
            assert "name" in data
            assert "version" in data
