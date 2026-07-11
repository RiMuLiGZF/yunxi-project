"""
M2 技能集群 - 启动脚本（yunxi-project 整合版）
快速启动 M2 技能集群 HTTP API 服务

配置加载优先级：
1. 环境变量（最高优先级）
2. 项目根目录 config/yunxi.env（全局配置）
3. 默认值
"""

import sys
import os

# ============================================================
# 1. 路径设置：确保模块可导入
# ============================================================
_current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _current_dir)

# Windows 兼容：resource 模块 mock（沙箱用）
if sys.platform == "win32":
    try:
        import resource  # noqa: F401
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "resource", os.path.join(_current_dir, "resource.py")
        )
        if spec and spec.loader:
            resource_module = importlib.util.module_from_spec(spec)
            sys.modules["resource"] = resource_module
            spec.loader.exec_module(resource_module)

# ============================================================
# 2. 加载全局配置 yunxi.env
# ============================================================

def _find_project_root() -> str:
    """查找 yunxi-project 项目根目录。
    
    从当前目录向上查找，找到包含 config/yunxi.env 的目录。
    """
    current = os.path.abspath(_current_dir)
    for _ in range(10):
        if os.path.exists(os.path.join(current, "config", "yunxi.env")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return ""


def _load_dotenv(env_path: str) -> None:
    """加载 .env 文件到环境变量。
    
    优先使用 python-dotenv，不可用时手动解析。
    已存在的环境变量不会被覆盖。
    """
    if not os.path.exists(env_path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass
    
    # 手动解析
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


# 加载全局配置
_project_root = _find_project_root()
if _project_root:
    _yunxi_env = os.path.join(_project_root, "config", "yunxi.env")
    _load_dotenv(_yunxi_env)

# ============================================================
# 3. 导入 M2 核心模块
# ============================================================

import uvicorn

from skill_cluster.api_v2 import create_v2_app
from skill_cluster.skill_registry import SkillRegistry
from skill_cluster.skill_router import SkillRouter
from skill_cluster.skill_discovery import SkillDiscoveryEngine
from skill_cluster.health_checker import HealthChecker
from skill_cluster.skill_discovery import SkillCategory
from skill_cluster.interfaces import ISkill


# ============================================================
# 4. 技能分类映射
# ============================================================

_SKILL_CATEGORY_MAP: dict[str, SkillCategory] = {
    "skill.code": SkillCategory.CODING,
    "skill.cod": SkillCategory.CODING,
    "skill.dev": SkillCategory.CODING,
    "skill.search": SkillCategory.CODING,
    "skill.doc": SkillCategory.DOCUMENT,
    "skill.document": SkillCategory.DOCUMENT,
    "skill.translate": SkillCategory.DOCUMENT,
    "skill.data": SkillCategory.DATA,
    "skill.analysis": SkillCategory.DATA,
    "skill.calendar": SkillCategory.LIFE,
    "skill.notify": SkillCategory.LIFE,
    "skill.memory": SkillCategory.LEARNING,
    "skill.tide": SkillCategory.LEARNING,
    "skill.web": SkillCategory.DOCUMENT,
    "skill.fetch": SkillCategory.DOCUMENT,
    "skill.fulltext": SkillCategory.DOCUMENT,
}


def _infer_category(skill_id: str) -> SkillCategory:
    """根据 skill_id 推断技能分类."""
    sid = skill_id.lower()
    for prefix, cat in _SKILL_CATEGORY_MAP.items():
        if sid.startswith(prefix):
            return cat
    return SkillCategory.DOCUMENT


# ============================================================
# 5. 内置技能加载
# ============================================================

def _load_builtin_skills(registry: SkillRegistry) -> int:
    """加载内置技能到注册表.
    
    从 skill_cluster.skills 模块中发现并注册所有 ISkill 子类。
    
    Returns:
        成功注册的技能数量
    """
    import importlib
    count = 0
    
    # 内置技能模块列表
    skill_modules = [
        "skill_cluster.skills.calendar",
        "skill_cluster.skills.translate",
        "skill_cluster.skills.web_fetch",
        "skill_cluster.skills.doc_proc",
        "skill_cluster.skills.data_analysis",
        "skill_cluster.skills.notify",
        "skill_cluster.skills.tide_memory",
        "skill_cluster.skills.fulltext_search",
        "skill_cluster.skills.code_skills",
        "skill_cluster.skills.code_search",
    ]
    
    for mod_name in skill_modules:
        try:
            mod = importlib.import_module(mod_name)
            # 在模块中查找 ISkill 子类
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, ISkill)
                    and attr is not ISkill
                ):
                    try:
                        skill_instance = attr()
                        registry.register(skill_instance)
                        count += 1
                    except Exception as e:
                        # 跳过注册失败的技能（如缺少依赖）
                        import structlog
                        logger = structlog.get_logger()
                        logger.warning(
                            "skill_register_failed",
                            skill=attr_name,
                            module=mod_name,
                            error=str(e),
                        )
        except ImportError as e:
            # 模块导入失败（缺少依赖），跳过
            import structlog
            logger = structlog.get_logger()
            logger.debug(
                "skill_module_skipped",
                module=mod_name,
                reason=str(e),
            )
    
    return count


# ============================================================
# 6. 主启动函数
# ============================================================

def main():
    """启动 M2 技能集群"""
    import time as _time_mod
    _start_time = _time_mod.time()
    print("=" * 60)
    print("  M2 技能集群 (v3.10.2) - 启动中...")
    print("  云汐系统 yunxi-project 整合版")
    print("=" * 60)

    # 读取配置
    port = int(os.environ.get("M2_PORT", "8002"))
    host = os.environ.get("M2_HOST", "0.0.0.0")
    env = os.environ.get("M2_ENV", os.environ.get("YUNXI_ENV", "development"))
    admin_token = os.environ.get("M2_ADMIN_TOKEN", "")

    if _project_root:
        print(f"  项目根目录: {_project_root}")
        print(f"  配置来源: config/yunxi.env")
    else:
        print("  提示: 未找到 yunxi.env，使用环境变量/默认值")
    print(f"  运行环境: {env}")
    print()

    # 初始化组件
    print("[1/5] 初始化技能注册表...")
    registry = SkillRegistry()
    
    print("[2/5] 加载内置技能...")
    skill_count = _load_builtin_skills(registry)
    print(f"      已加载 {skill_count} 个技能")

    print("[3/5] 初始化技能路由器...")
    router = SkillRouter(registry=registry)

    print("[4/5] 初始化发现引擎...")
    discovery = SkillDiscoveryEngine()
    for skill_id in registry.list_skills():
        manifest = registry.get_manifest(skill_id)
        if manifest:
            category = _infer_category(skill_id)
            discovery.register_skill(
                skill_id=skill_id,
                skill_name=manifest.name,
                description=manifest.description,
                category=category,
                tags=list(manifest.tags) if hasattr(manifest, 'tags') else [],
                keywords=list(manifest.capabilities) if hasattr(manifest, 'capabilities') else [],
            )

    print("[5/5] 初始化健康检查器...")
    health_checker = HealthChecker(registry=registry)

    # 创建 FastAPI 应用
    print("\n创建 API 服务...")
    app = create_v2_app(
        registry=registry,
        router=router,
        discovery_engine=discovery,
        health_checker=health_checker,
    )

    if app is None:
        print("错误: FastAPI 未安装，请运行: pip install fastapi uvicorn")
        sys.exit(1)

    # 添加根路径健康检查（yunxi 标准格式）
    @app.get("/health")
    async def root_health():
        """根路径健康检查 - yunxi 标准格式.
        
        返回: {"code": 0, "message": "ok", "data": {"status": "healthy"}}
        """
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "service": "m2-skills",
                "version": "3.10.2",
                "skills": skill_count,
            }
        }

    # ---- M8 标准对接接口 ----
    from fastapi import Header, HTTPException, Request

    def _verify_m8_token(x_m8_token: str = "") -> bool:
        """验证 M8 管理令牌（P2-改进: 使用 hmac 防时序攻击）"""
        expected = os.environ.get("M2_ADMIN_TOKEN", "")
        if not expected:
            return True  # 未配置时放行
        import hmac
        return hmac.compare_digest(x_m8_token, expected)

    @app.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
    async def m8_health(x_m8_token: str = Header(default="")):
        """M8 标准健康检查接口"""
        if not _verify_m8_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "module": "m2",
                "module_name": "技能集群",
                "version": "3.10.2",
                "skills_count": skill_count,
                "uptime_seconds": int(__import__('time').time() - _start_time),
            }
        }

    @app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
    async def m8_metrics(x_m8_token: str = Header(default="")):
        """M8 标准性能指标接口（P2-改进: 接入真实系统指标）"""
        if not _verify_m8_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        # 真实系统指标
        try:
            import psutil
            _cpu = psutil.cpu_percent(interval=0.1)
            _mem = psutil.virtual_memory()
            _mem_mb = _mem.used / (1024 * 1024)
        except Exception:
            _cpu = 0.0
            _mem_mb = 0
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "cpu_usage": round(_cpu, 1),
                "memory_mb": int(_mem_mb),
                "requests_total": 0,
                "requests_per_second": 0,
                "avg_latency_ms": 0,
                "skills_registered": skill_count,
                "invocations_total": 0,
            }
        }

    @app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
    async def m8_config(x_m8_token: str = Header(default="")):
        """M8 标准配置查询接口"""
        if not _verify_m8_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "module": "m2",
                "version": "3.10.2",
                "env": os.environ.get("YUNXI_ENV", "development"),
                "skills_count": skill_count,
                "auth_enabled": bool(os.environ.get("M2_ADMIN_TOKEN", "")),
                "cors_origins": os.environ.get("M2_CORS_ORIGINS", "*"),
            }
        }

    # 启动服务
    print(f"\nM2 技能集群启动完成！")
    print(f"  服务地址: http://{host}:{port}")
    print(f"  健康检查: http://{host}:{port}/health")
    print(f"  API v2 健康: http://{host}:{port}/api/v2/health")
    print(f"  技能列表: http://{host}:{port}/api/v2/skills")
    print(f"  API 文档: http://{host}:{port}/docs")
    print(f"  技能数量: {skill_count}")
    if admin_token:
        print(f"  鉴权状态: 已启用 M8 Token 鉴权")
    else:
        print(f"  鉴权状态: 未启用（开发模式）")
    print("=" * 60)
    print()

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
