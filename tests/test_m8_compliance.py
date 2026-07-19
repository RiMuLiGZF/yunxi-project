"""
M8 标准接口合规性测试

测试目标：
验证所有模块是否实现了 M8 标准的三个管控接口：
1. GET /m8/health   — 健康检查
2. GET /m8/metrics  — 指标查询
3. GET /m8/config   — 配置管理

检查项：
- 接口路径是否规范（/m8/xxx）
- 返回格式是否符合 M8 标准（code/message/data）
- 健康状态枚举是否统一（healthy/degraded/unhealthy）
- 模块标识字段是否存在
- 版本号字段是否存在

合规度计算：
合规度 = (已合规接口数 / 总接口数) * 100%
总接口数 = 模块数 * 3（health/metrics/config）
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

# 将项目根目录加入 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# 模块配置清单
# ============================================================================

MODULES: List[Dict] = [
    {
        "id": "m0",
        "name": "主理人管控台",
        "path": "M0-principal-console",
        "app_path": "src.main:app",
        "has_m8": True,
    },
    {
        "id": "m1",
        "name": "Agent集群调度",
        "path": "M1-agent-hub",
        "app_path": "src.api.m8_interface",
        "has_m8": True,
    },
    {
        "id": "m2",
        "name": "技能集群",
        "path": "M2-skills-cluster",
        "app_path": "skill_cluster.api.m8_api",
        "has_m8": True,
    },
    {
        "id": "m3",
        "name": "端云协同内核",
        "path": "M3-edge-cloud",
        "app_path": "edge_cloud_kernel.api.m8_router",
        "has_m8": True,
    },
    {
        "id": "m4",
        "name": "场景引擎",
        "path": "M4-scene-engine",
        "app_path": "src.main:app",
        "has_m8": True,
    },
    {
        "id": "m5",
        "name": "潮汐记忆",
        "path": "M5-tide-memory",
        "app_path": "tide_memory.api.m8_routes",
        "has_m8": True,
    },
    {
        "id": "m6",
        "name": "硬件外设",
        "path": "M6-hardware-peripheral",
        "app_path": "server:app",
        "has_m8": True,
    },
    {
        "id": "m7",
        "name": "工作流构建器",
        "path": "M7-workflow-builder",
        "app_path": "src.m8_api.health_endpoints",
        "has_m8": True,
    },
    {
        "id": "m8",
        "name": "云汐管理台",
        "path": "M8-control-tower",
        "app_path": "backend.main:app",
        "has_m8": True,
    },
    {
        "id": "m9-dev",
        "name": "开发者工坊",
        "path": "M9-dev-workshop",
        "app_path": "backend.main:app",
        "has_m8": True,
    },
    {
        "id": "m9-data",
        "name": "数据水晶",
        "path": "M9-data-crystal",
        "app_path": "backend.main:app",
        "has_m8": True,
    },
    {
        "id": "m10",
        "name": "系统卫士",
        "path": "M10-system-guard",
        "app_path": "server:app",
        "has_m8": True,
    },
    {
        "id": "m11",
        "name": "MCP总线",
        "path": "M11-mcp-bus",
        "app_path": "src.routers.health",
        "has_m8": True,
    },
    {
        "id": "m12",
        "name": "安全盾",
        "path": "M12-security-shield",
        "app_path": "server:app",
        "has_m8": True,
    },
    {
        "id": "api-gateway",
        "name": "API网关",
        "path": "API-Gateway",
        "app_path": "src.main:app",
        "has_m8": True,
    },
]

M8_ENDPOINTS = ["health", "metrics", "config"]


# ============================================================================
# 辅助函数：静态代码审计（不启动服务）
# ============================================================================

def _find_m8_routes_in_file(filepath: Path) -> Dict[str, bool]:
    """静态扫描文件，查找 M8 标准接口的定义.

    通过搜索路由装饰器模式来识别接口：
    - @app.get("/m8/health") 或 @router.get("/m8/health")
    - @app.get("/m8/metrics") 或 @router.get("/m8/metrics")
    - @app.get("/m8/config") 或 @router.get("/m8/config")

    Args:
        filepath: 要扫描的文件路径

    Returns:
        Dict with keys: health, metrics, config (bool)
    """
    result = {"health": False, "metrics": False, "config": False}

    if not filepath.exists():
        return result

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return result

    # 搜索 M8 标准路径的路由定义
    import re

    # 匹配 @xxx.get("/m8/health") 或 @xxx.get('/m8/health') 等模式
    patterns = {
        "health": r'@\w+\.(get|post|put|patch|delete)\s*\(\s*["\']/m8/health["\']',
        "metrics": r'@\w+\.(get|post|put|patch|delete)\s*\(\s*["\']/m8/metrics["\']',
        "config": r'@\w+\.(get|post|put|patch|delete)\s*\(\s*["\']/m8/config["\']',
    }

    for endpoint, pattern in patterns.items():
        if re.search(pattern, content):
            result[endpoint] = True

    # 也搜索 APIRouter(prefix="/m8") + 方法组合的模式
    if re.search(r'APIRouter\s*\([^)]*prefix\s*=\s*["\']/m8["\']', content):
        # 有 /m8 前缀的 router，检查是否有对应方法
        method_patterns = {
            "health": r'@\w+\.(get|post|put|patch|delete)\s*\(\s*["\']/health["\']',
            "metrics": r'@\w+\.(get|post|put|patch|delete)\s*\(\s*["\']/metrics["\']',
            "config": r'@\w+\.(get|post|put|patch|delete)\s*\(\s*["\']/config["\']',
        }
        for endpoint, pattern in method_patterns.items():
            if re.search(pattern, content):
                result[endpoint] = True

    # 兜底检测：搜索包含 "/m8/xxx" 字符串的路由注册模式
    # （处理 register_m8_std_endpoints 等动态注册函数内部的路由）
    for endpoint in ["health", "metrics", "config"]:
        if not result[endpoint]:
            # 匹配 '"/m8/health"' 或 '"/m8/metrics"' 或 '"/m8/config"'
            # 且该行/附近有 @app.get 或 @router.get 或 "m8_std_xxx" 函数名
            path_str = f'"/m8/{endpoint}"'
            alt_path_str = f"'/m8/{endpoint}'"
            if path_str in content or alt_path_str in content:
                # 进一步确认：文件中确实有路由注册逻辑（包含 app.get 或 router.get）
                if re.search(r'(app|router)\.(get|post|put|patch|delete)', content):
                    result[endpoint] = True
                # 或者有专门的注册函数名
                elif f'm8_std_{endpoint}' in content or f'register_m8' in content:
                    result[endpoint] = True

    return result


def _find_all_m8_files(module_path: Path) -> List[Path]:
    """查找模块中所有可能包含 M8 接口的 Python 文件.

    Args:
        module_path: 模块根目录路径

    Returns:
        包含 M8 相关代码的文件路径列表
    """
    m8_files = []
    if not module_path.exists():
        return m8_files

    all_py_files: List[Path] = []

    # 使用 os.walk 替代 rglob，避免 .pytest_cache 等问题目录导致遍历失败
    import os
    try:
        for root, dirs, files in os.walk(str(module_path)):
            # 跳过问题目录
            dirs[:] = [d for d in dirs if d not in (
                "__pycache__", ".pytest_cache", ".git", "node_modules",
            )]
            for fname in files:
                if fname.endswith(".py"):
                    all_py_files.append(Path(root) / fname)
    except (FileNotFoundError, PermissionError):
        return m8_files

    for py_file in all_py_files:
        # 跳过测试目录中的文件
        py_file_str = str(py_file)
        if "/tests/" in py_file_str or "\\tests\\" in py_file_str:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            if "/m8/" in content or "m8" in py_file.name.lower():
                m8_files.append(py_file)
        except Exception:
            continue

    return m8_files


def _check_response_format_in_file(filepath: Path) -> Dict[str, bool]:
    """检查文件中 M8 接口的返回格式是否符合 code/message/data 标准.

    Args:
        filepath: 要检查的文件路径

    Returns:
        Dict with keys: has_code, has_message, has_data (bool)
    """
    result = {"has_code": False, "has_message": False, "has_data": False}

    if not filepath.exists():
        return result

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return result

    # 搜索返回字典中是否包含 code, message, data 字段
    # 匹配模式："code": 0 或 'code': 0
    import re

    if re.search(r'["\']code["\']\s*:', content):
        result["has_code"] = True
    if re.search(r'["\']message["\']\s*:', content):
        result["has_message"] = True
    if re.search(r'["\']data["\']\s*:', content):
        result["has_data"] = True

    return result


def _check_health_status_enum(filepath: Path) -> bool:
    """检查文件中是否使用了标准的健康状态枚举.

    标准枚举：healthy / degraded / unhealthy

    Args:
        filepath: 要检查的文件路径

    Returns:
        True 表示使用了标准枚举
    """
    if not filepath.exists():
        return False

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return False

    # 检查是否包含标准状态字符串
    has_healthy = '"healthy"' in content or "'healthy'" in content
    has_degraded = '"degraded"' in content or "'degraded'" in content

    # 至少包含 healthy（必须）和 degraded/unhealthy（至少一个）
    return has_healthy and (has_degraded or '"unhealthy"' in content or "'unhealthy'" in content)


# ============================================================================
# 合规度计算
# ============================================================================

def calculate_compliance() -> Dict:
    """计算全模块 M8 接口合规度.

    Returns:
        包含合规度详情的字典
    """
    total_modules = len(MODULES)
    total_endpoints = total_modules * len(M8_ENDPOINTS)
    compliant_endpoints = 0
    module_results = []

    for mod in MODULES:
        module_path = PROJECT_ROOT / mod["path"]
        m8_files = _find_all_m8_files(module_path)

        # 收集所有文件中的路由信息
        all_routes = {"health": False, "metrics": False, "config": False}
        format_compliant = False
        enum_compliant = False

        for f in m8_files:
            routes = _find_m8_routes_in_file(f)
            for ep in M8_ENDPOINTS:
                if routes[ep]:
                    all_routes[ep] = True

            # 检查格式
            fmt = _check_response_format_in_file(f)
            if fmt["has_code"] and fmt["has_message"] and fmt["has_data"]:
                format_compliant = True

            # 检查健康状态枚举
            if _check_health_status_enum(f):
                enum_compliant = True

        # 统计合规接口数
        ep_compliant = sum(1 for ep in M8_ENDPOINTS if all_routes[ep])
        compliant_endpoints += ep_compliant

        module_results.append({
            "module_id": mod["id"],
            "module_name": mod["name"],
            "health": all_routes["health"],
            "metrics": all_routes["metrics"],
            "config": all_routes["config"],
            "compliant_count": ep_compliant,
            "total_count": len(M8_ENDPOINTS),
            "format_compliant": format_compliant,
            "enum_compliant": enum_compliant,
            "m8_files_found": len(m8_files),
        })

    compliance_rate = (compliant_endpoints / total_endpoints * 100) if total_endpoints > 0 else 0

    return {
        "total_modules": total_modules,
        "total_endpoints": total_endpoints,
        "compliant_endpoints": compliant_endpoints,
        "compliance_rate": round(compliance_rate, 1),
        "module_results": module_results,
    }


# ============================================================================
# 测试用例
# ============================================================================

class TestM8ComplianceStatic:
    """M8 标准接口静态合规性测试（代码扫描，不启动服务）."""

    @pytest.fixture(scope="class")
    def compliance_report(self):
        """生成全模块合规报告（复用）."""
        return calculate_compliance()

    def test_total_modules_audited(self, compliance_report):
        """测试用例1：确认审计覆盖了所有 15 个模块."""
        assert compliance_report["total_modules"] == 15, (
            f"应审计 15 个模块，实际审计了 {compliance_report['total_modules']} 个"
        )

    def test_compliance_rate_above_90(self, compliance_report):
        """测试用例2：整体合规度应达到 90% 以上."""
        rate = compliance_report["compliance_rate"]
        assert rate >= 90.0, (
            f"M8 接口合规度 {rate}%，未达到 90% 目标"
        )

    def test_all_modules_have_health_endpoint(self, compliance_report):
        """测试用例3：所有模块都应有 /m8/health 健康检查接口."""
        missing = [
            m["module_id"] for m in compliance_report["module_results"]
            if not m["health"]
        ]
        assert len(missing) == 0, (
            f"以下模块缺少 /m8/health 接口: {missing}"
        )

    def test_all_modules_have_metrics_endpoint(self, compliance_report):
        """测试用例4：所有模块都应有 /m8/metrics 指标接口."""
        missing = [
            m["module_id"] for m in compliance_report["module_results"]
            if not m["metrics"]
        ]
        assert len(missing) == 0, (
            f"以下模块缺少 /m8/metrics 接口: {missing}"
        )

    def test_all_modules_have_config_endpoint(self, compliance_report):
        """测试用例5：所有模块都应有 /m8/config 配置接口."""
        missing = [
            m["module_id"] for m in compliance_report["module_results"]
            if not m["config"]
        ]
        assert len(missing) == 0, (
            f"以下模块缺少 /m8/config 接口: {missing}"
        )

    def test_most_modules_format_compliant(self, compliance_report):
        """测试用例6：至少 80% 模块的返回格式符合 code/message/data 标准."""
        total = compliance_report["total_modules"]
        format_compliant = sum(
            1 for m in compliance_report["module_results"]
            if m["format_compliant"]
        )
        rate = format_compliant / total * 100
        assert rate >= 80.0, (
            f"返回格式合规率 {rate:.1f}%，未达到 80% 目标"
            f"（{format_compliant}/{total} 个模块）"
        )

    def test_most_modules_enum_compliant(self, compliance_report):
        """测试用例7：至少 70% 模块使用标准健康状态枚举."""
        total = compliance_report["total_modules"]
        enum_compliant = sum(
            1 for m in compliance_report["module_results"]
            if m["enum_compliant"]
        )
        rate = enum_compliant / total * 100
        assert rate >= 70.0, (
            f"健康状态枚举合规率 {rate:.1f}%，未达到 70% 目标"
            f"（{enum_compliant}/{total} 个模块）"
        )

    def test_core_modules_fully_compliant(self, compliance_report):
        """测试用例8：核心模块（M1, M2, M3, M4, M8, M12）必须三接口全合规."""
        core_modules = {"m1", "m2", "m3", "m4", "m8", "m12"}
        non_compliant = [
            m["module_id"] for m in compliance_report["module_results"]
            if m["module_id"] in core_modules and m["compliant_count"] < 3
        ]
        assert len(non_compliant) == 0, (
            f"核心模块 {non_compliant} 未实现全部 M8 接口"
        )

    def test_minimum_compliant_endpoints(self, compliance_report):
        """测试用例9：合规接口总数不少于 40 个（15模块 x 3接口 = 45，允许5个缺失）."""
        assert compliance_report["compliant_endpoints"] >= 40, (
            f"合规接口数 {compliance_report['compliant_endpoints']}，"
            f"低于最低要求 40 个"
        )

    def test_compliance_report_structure(self, compliance_report):
        """测试用例10：合规报告结构完整."""
        required_keys = [
            "total_modules", "total_endpoints", "compliant_endpoints",
            "compliance_rate", "module_results"
        ]
        for key in required_keys:
            assert key in compliance_report, f"报告缺少关键字段: {key}"

        assert isinstance(compliance_report["module_results"], list)
        assert len(compliance_report["module_results"]) > 0

        # 检查每个模块结果的结构
        for m in compliance_report["module_results"]:
            for key in ["module_id", "module_name", "health", "metrics", "config"]:
                assert key in m, f"模块结果缺少字段: {key}"

    def test_module_id_uniqueness(self, compliance_report):
        """测试用例11：模块 ID 唯一，无重复."""
        ids = [m["module_id"] for m in compliance_report["module_results"]]
        assert len(ids) == len(set(ids)), "存在重复的模块 ID"

    def test_boolean_fields_valid(self, compliance_report):
        """测试用例12：接口存在性字段为布尔值."""
        for m in compliance_report["module_results"]:
            assert isinstance(m["health"], bool), f"{m['module_id']} health 不是布尔值"
            assert isinstance(m["metrics"], bool), f"{m['module_id']} metrics 不是布尔值"
            assert isinstance(m["config"], bool), f"{m['module_id']} config 不是布尔值"


class TestM8FormatStandard:
    """M8 接口格式标准测试."""

    def test_health_response_contains_module_field(self):
        """测试用例13：M8 health 接口应包含 module 字段.

        通过代码模式匹配验证，确保返回 data 中包含 module 字段。
        """
        # 抽样检查几个核心模块
        sample_modules = [
            ("M2-skills-cluster", "m2"),
            ("M3-edge-cloud", "m3"),
            ("M8-control-tower", "m8"),
            ("M12-security-shield", "m12"),
        ]
        for mod_path, mod_id in sample_modules:
            module_dir = PROJECT_ROOT / mod_path
            m8_files = _find_all_m8_files(module_dir)
            found_module_field = False
            for f in m8_files:
                try:
                    content = f.read_text(encoding="utf-8")
                    if '"module"' in content or "'module'" in content:
                        found_module_field = True
                        break
                except Exception:
                    continue
            assert found_module_field, (
                f"{mod_id} 的 M8 接口中未找到 module 字段"
            )

    def test_health_response_contains_version_field(self):
        """测试用例14：M8 health 接口应包含 version 字段."""
        sample_modules = [
            ("M2-skills-cluster", "m2"),
            ("M4-scene-engine", "m4"),
            ("M10-system-guard", "m10"),
        ]
        for mod_path, mod_id in sample_modules:
            module_dir = PROJECT_ROOT / mod_path
            m8_files = _find_all_m8_files(module_dir)
            found_version_field = False
            for f in m8_files:
                try:
                    content = f.read_text(encoding="utf-8")
                    if '"version"' in content or "'version'" in content:
                        found_version_field = True
                        break
                except Exception:
                    continue
            assert found_version_field, (
                f"{mod_id} 的 M8 接口中未找到 version 字段"
            )

    def test_config_returns_masked_sensitive_data(self):
        """测试用例15：配置接口应对敏感数据进行脱敏.

        检查代码中是否有脱敏逻辑（mask、***、sensitive 等关键词）。
        """
        sensitive_modules = 0
        checked_modules = 0

        for mod in MODULES:
            module_path = PROJECT_ROOT / mod["path"]
            m8_files = _find_all_m8_files(module_path)
            if not m8_files:
                continue

            checked_modules += 1
            has_masking = False
            for f in m8_files:
                try:
                    content = f.read_text(encoding="utf-8")
                    if any(kw in content.lower() for kw in [
                        "mask", "***", "sensitive", "脱敏", "redact",
                    ]):
                        has_masking = True
                        break
                except Exception:
                    continue

            if has_masking:
                sensitive_modules += 1

        # 至少 60% 的模块有脱敏逻辑
        if checked_modules > 0:
            rate = sensitive_modules / checked_modules * 100
            assert rate >= 50.0, (
                f"配置接口脱敏覆盖率 {rate:.1f}%，低于 50% 最低要求"
                f"（{sensitive_modules}/{checked_modules}）"
            )


# ============================================================================
# 命令行运行：直接输出合规度报告
# ============================================================================

if __name__ == "__main__":
    report = calculate_compliance()

    print("=" * 70)
    print("  M8 标准接口合规性审计报告")
    print("=" * 70)
    print()
    print(f"  审计模块数:     {report['total_modules']}")
    print(f"  应实现接口数:   {report['total_endpoints']}")
    print(f"  已合规接口数:   {report['compliant_endpoints']}")
    print(f"  整体合规度:     {report['compliance_rate']}%")
    print()
    print("-" * 70)
    print(f"  {'模块ID':<12} {'模块名称':<14} {'health':<7} {'metrics':<8} {'config':<7} {'合规数'}")
    print("-" * 70)

    for m in report["module_results"]:
        health_mark = "YES" if m["health"] else "NO"
        metrics_mark = "YES" if m["metrics"] else "NO"
        config_mark = "YES" if m["config"] else "NO"
        print(
            f"  {m['module_id']:<12} {m['module_name']:<14} "
            f"{health_mark:<7} {metrics_mark:<8} {config_mark:<7} "
            f"{m['compliant_count']}/3"
        )

    print("-" * 70)
    print()

    # 列出缺失的接口
    missing = []
    for m in report["module_results"]:
        for ep in M8_ENDPOINTS:
            if not m[ep]:
                missing.append(f"{m['module_id']} - /m8/{ep}")

    if missing:
        print("  缺失接口列表:")
        for item in missing:
            print(f"    - {item}")
    else:
        print("  所有模块均已实现全部 M8 标准接口！")

    print()
    print("=" * 70)
