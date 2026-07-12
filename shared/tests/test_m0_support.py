"""
shared 单元测试 - M0 主理人管控平台支持验证

覆盖: M0 模块注册、ModuleKey 枚举、默认配置、角色权限系统
运行: python -m pytest tests/test_m0_support.py -v
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestModuleKey:
    """ModuleKey 枚举测试"""

    def test_module_key_contains_m0(self):
        """ModuleKey 枚举应包含 M0"""
        from shared.module_client import ModuleKey
        assert hasattr(ModuleKey, "M0")
        assert ModuleKey.M0 == "m0"

    def test_module_key_all_members(self):
        """ModuleKey 枚举应包含所有已知模块"""
        from shared.module_client import ModuleKey
        expected = ["m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m10"]
        actual = [m.value for m in ModuleKey]
        for key in expected:
            assert key in actual, f"缺少模块键: {key}"

    def test_module_key_is_string_enum(self):
        """ModuleKey 值应为字符串"""
        from shared.module_client import ModuleKey
        assert isinstance(ModuleKey.M0.value, str)
        assert ModuleKey.M0 == "m0"

    def test_module_category_enum(self):
        """ModuleCategory 枚举应包含分类"""
        from shared.module_client import ModuleCategory
        assert ModuleCategory.CONTROL == "control"
        assert ModuleCategory.CORE == "core"
        assert ModuleCategory.TOOL == "tool"
        assert ModuleCategory.INFRA == "infra"


class TestM0Config:
    """M0 配置测试"""

    def test_m0_port_config(self):
        """M0 端口配置应存在且为 8000"""
        from shared.config import get_config
        config = get_config()
        port = config.get_module_port("m0")
        assert port is not None
        assert port == 8000

    def test_m0_host_config(self):
        """M0 主机配置应存在"""
        from shared.config import get_config
        config = get_config()
        host = config.get_module_host("m0")
        assert host is not None
        assert host == "0.0.0.0"

    def test_m0_base_url_config(self):
        """M0 Base URL 配置应存在"""
        from shared.config import get_config
        config = get_config()
        url = config.get_module_base_url("m0")
        assert url is not None
        assert "8000" in url

    def test_m0_token_config(self):
        """M0 管理令牌配置应存在"""
        from shared.config import get_config
        config = get_config()
        token = config.get_module_token("m0")
        assert token is not None
        assert "m0" in token.lower()

    def test_m0_in_all_module_keys(self):
        """M0 应在所有模块 key 列表中"""
        from shared.config import get_config
        config = get_config()
        keys = config.get_all_module_keys()
        assert "m0" in keys


class TestModuleRegistryM0:
    """模块注册表 M0 测试"""

    def test_m0_in_registry(self):
        """ModuleRegistry 应包含 M0 模块"""
        from shared.module_client import ModuleRegistry
        # 重置单例以确保干净状态
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        assert m0 is not None

    def test_m0_module_info(self):
        """M0 模块信息应正确"""
        from shared.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        assert m0.key == "m0"
        assert m0.name == "主理人管控台"
        assert m0.version == "v1.0.0"
        assert m0.port == 8000
        assert "主理人" in m0.description

    def test_m0_category(self):
        """M0 模块分类应为 control"""
        from shared.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        assert m0.category == "control"

    def test_m0_health_endpoint(self):
        """M0 模块应有健康检查端点"""
        from shared.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        assert hasattr(m0, "health_endpoint")
        assert m0.health_endpoint == "/health"

    def test_m0_default_status(self):
        """M0 模块默认状态应为 unknown"""
        from shared.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        assert m0.status == "unknown"

    def test_total_module_count(self):
        """默认模块总数应为 10"""
        from shared.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        modules = registry.get_all_modules()
        assert len(modules) == 10

    def test_m0_to_dict(self):
        """M0 ModuleInfo.to_dict() 应包含关键字段"""
        from shared.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        d = m0.to_dict()
        assert d["key"] == "m0"
        assert d["name"] == "主理人管控台"
        assert "category" in d
        assert "health_endpoint" in d
        assert "status" in d


class TestDefaultModuleConfigs:
    """DEFAULT_MODULE_CONFIGS 常量测试"""

    def test_default_configs_contains_m0(self):
        """DEFAULT_MODULE_CONFIGS 应包含 M0"""
        from shared.module_client import DEFAULT_MODULE_CONFIGS
        assert "m0" in DEFAULT_MODULE_CONFIGS

    def test_default_configs_m0_info(self):
        """DEFAULT_MODULE_CONFIGS 中 M0 信息应正确"""
        from shared.module_client import DEFAULT_MODULE_CONFIGS
        m0 = DEFAULT_MODULE_CONFIGS["m0"]
        assert m0.key == "m0"
        assert m0.name == "主理人管控台"
        assert m0.category == "control"

    def test_get_module_registry_alias(self):
        """get_module_registry 别名应正常工作"""
        from shared.module_client import get_module_registry, get_registry
        assert get_module_registry is get_registry


class TestClientsModuleClientM0:
    """shared.clients.module_client 中 M0 支持测试"""

    def test_clients_module_key_has_m0(self):
        """clients 中的 ModuleKey 也应包含 M0"""
        from shared.clients.module_client import ModuleKey
        assert hasattr(ModuleKey, "M0")
        assert ModuleKey.M0 == "m0"

    def test_clients_registry_has_m0(self):
        """clients 中的 ModuleRegistry 应包含 M0"""
        from shared.clients.module_client import ModuleRegistry
        # 重置单例
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        assert m0 is not None
        assert m0.name == "主理人管控台"

    def test_clients_module_info_has_category(self):
        """clients 中的 ModuleInfo 应有 category 字段"""
        from shared.clients.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        m0 = registry.get_module("m0")
        assert hasattr(m0, "category")
        assert m0.category == "control"

    def test_clients_total_count(self):
        """clients 中默认模块总数应为 11（含 m9）"""
        from shared.clients.module_client import ModuleRegistry
        ModuleRegistry._instance = None
        registry = ModuleRegistry()
        modules = registry.get_all_modules()
        # clients 版本包含 m9，所以是 11 个（m0-m8, m9, m10）
        assert len(modules) == 11


class TestSystemRole:
    """系统角色枚举测试"""

    def test_system_role_members(self):
        """SystemRole 应包含所有 5 个角色"""
        from shared.roles import SystemRole
        roles = [r.value for r in SystemRole]
        assert "owner" in roles
        assert "admin" in roles
        assert "operator" in roles
        assert "viewer" in roles
        assert "user" in roles

    def test_system_role_owner(self):
        """OWNER 角色值应为 owner"""
        from shared.roles import SystemRole
        assert SystemRole.OWNER == "owner"

    def test_role_hierarchy_values(self):
        """角色层级数值应正确"""
        from shared.roles import ROLE_HIERARCHY
        assert ROLE_HIERARCHY["owner"] == 100
        assert ROLE_HIERARCHY["admin"] == 80
        assert ROLE_HIERARCHY["operator"] == 60
        assert ROLE_HIERARCHY["viewer"] == 30
        assert ROLE_HIERARCHY["user"] == 10

    def test_role_hierarchy_order(self):
        """角色权限等级应递减"""
        from shared.roles import ROLE_HIERARCHY
        assert ROLE_HIERARCHY["owner"] > ROLE_HIERARCHY["admin"]
        assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["operator"]
        assert ROLE_HIERARCHY["operator"] > ROLE_HIERARCHY["viewer"]
        assert ROLE_HIERARCHY["viewer"] > ROLE_HIERARCHY["user"]


class TestRoleCheckFunctions:
    """权限检查函数测试"""

    def test_has_min_role_owner_vs_admin(self):
        """owner 角色应满足 admin 最低要求"""
        from shared.roles import has_min_role
        assert has_min_role("owner", "admin") is True

    def test_has_min_role_user_vs_admin(self):
        """user 角色不应满足 admin 最低要求"""
        from shared.roles import has_min_role
        assert has_min_role("user", "admin") is False

    def test_has_min_role_same_role(self):
        """相同角色应满足要求"""
        from shared.roles import has_min_role
        assert has_min_role("viewer", "viewer") is True

    def test_has_min_role_unknown_role(self):
        """未知角色权限等级为 0"""
        from shared.roles import has_min_role
        assert has_min_role("unknown", "user") is False

    def test_is_owner(self):
        """is_owner 应正确判断主理人角色"""
        from shared.roles import is_owner
        assert is_owner("owner") is True
        assert is_owner("admin") is False
        assert is_owner("user") is False

    def test_is_admin(self):
        """is_admin 应正确判断管理员及以上角色"""
        from shared.roles import is_admin
        assert is_admin("owner") is True
        assert is_admin("admin") is True
        assert is_admin("operator") is False

    def test_is_operator(self):
        """is_operator 应正确判断运维及以上角色"""
        from shared.roles import is_operator
        assert is_operator("owner") is True
        assert is_operator("admin") is True
        assert is_operator("operator") is True
        assert is_operator("viewer") is False

    def test_is_viewer(self):
        """is_viewer 应正确判断只读及以上角色"""
        from shared.roles import is_viewer
        assert is_viewer("owner") is True
        assert is_viewer("viewer") is True
        assert is_viewer("user") is False

    def test_get_role_level(self):
        """get_role_level 应返回正确的等级数值"""
        from shared.roles import get_role_level
        assert get_role_level("owner") == 100
        assert get_role_level("admin") == 80
        assert get_role_level("nonexistent") == 0

    def test_get_role_display_name(self):
        """get_role_display_name 应返回中文名称"""
        from shared.roles import get_role_display_name
        assert get_role_display_name("owner") == "主理人"
        assert get_role_display_name("admin") == "管理员"
        assert get_role_display_name("unknown") == "unknown"

    def test_get_all_roles(self):
        """get_all_roles 应返回所有角色列表"""
        from shared.roles import get_all_roles
        roles = get_all_roles()
        assert isinstance(roles, list)
        assert len(roles) == 5
        assert roles[0] == "owner"  # 按权限从高到低

    def test_get_role_info(self):
        """get_role_info 应返回完整角色信息"""
        from shared.roles import get_role_info
        info = get_role_info("owner")
        assert info is not None
        assert info["name"] == "owner"
        assert info["level"] == 100
        assert info["display_name"] == "主理人"

    def test_get_role_info_nonexistent(self):
        """获取不存在角色的信息应返回 None"""
        from shared.roles import get_role_info
        assert get_role_info("nonexistent") is None


class TestApiResponseM0Compatible:
    """统一响应格式 M0 可用性测试"""

    def test_success_response(self):
        """成功响应格式应正确"""
        from shared.responses import ApiResponse, SUCCESS
        resp = ApiResponse.success({"module": "m0"}, message="获取成功")
        d = resp.to_dict()
        assert d["code"] == SUCCESS
        assert d["message"] == "获取成功"
        assert d["data"]["module"] == "m0"
        assert resp.is_success is True

    def test_error_response(self):
        """错误响应格式应正确"""
        from shared.responses import ApiResponse, ERROR_FORBIDDEN
        resp = ApiResponse.error(ERROR_FORBIDDEN, "无权限访问", details={"role": "user"})
        d = resp.to_dict()
        assert d["code"] == ERROR_FORBIDDEN
        assert d["message"] == "无权限访问"
        assert d["details"]["role"] == "user"
        assert resp.is_success is False

    def test_m0_can_use_api_response(self):
        """M0 场景下的响应应能正常使用 ApiResponse"""
        from shared.responses import ApiResponse
        # 模拟 M0 主理人登录场景
        resp = ApiResponse.success(
            {"role": "owner", "module": "m0", "permissions": ["*"]},
            message="主理人登录成功"
        )
        d = resp.to_dict()
        assert d["code"] == 0
        assert d["data"]["role"] == "owner"
        assert d["data"]["module"] == "m0"


class TestSharedInitExports:
    """shared 包导出测试"""

    def test_module_key_exported(self):
        """ModuleKey 应在 shared 包中导出"""
        import shared
        assert hasattr(shared, "ModuleKey")

    def test_module_category_exported(self):
        """ModuleCategory 应在 shared 包中导出"""
        import shared
        assert hasattr(shared, "ModuleCategory")

    def test_default_module_configs_exported(self):
        """DEFAULT_MODULE_CONFIGS 应在 shared 包中导出"""
        import shared
        assert hasattr(shared, "DEFAULT_MODULE_CONFIGS")

    def test_system_role_exported(self):
        """SystemRole 应在 shared 包中导出"""
        import shared
        assert hasattr(shared, "SystemRole")

    def test_role_functions_exported(self):
        """角色权限函数应在 shared 包中导出"""
        import shared
        assert hasattr(shared, "has_min_role")
        assert hasattr(shared, "is_owner")
        assert hasattr(shared, "is_admin")
        assert hasattr(shared, "ROLE_HIERARCHY")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
