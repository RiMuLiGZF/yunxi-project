"""
自进化引擎 - 安全审计员路由
- 基于规则的静态安全检查
- 代码安全、依赖安全、权限检查、数据安全
- 风险评级与审计报告

数据库持久化 + 模拟逻辑 fallback（真正的安全审计需要 AI 和沙箱能力）
所有操作需要认证
首次访问自动初始化示例数据
"""

import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from ..models import get_db
from ..repositories.evolution_repository import EvolutionRepository

router = APIRouter()


# ============================================================
# 请求体模型
# ============================================================

class AuditDecisionRequest(BaseModel):
    """审计决策请求体"""
    comment: str = Field("", description="审计意见/备注")


# ============================================================
# 工具函数
# ============================================================

def _get_repo(db: Session) -> EvolutionRepository:
    """获取进化系统仓库，并确保示例数据初始化"""
    repo = EvolutionRepository(db)
    try:
        repo.ensure_seed_data(username="system")
    except Exception as e:
        print(f"[Evolution] 示例数据初始化跳过: {e}")
    return repo


# 已知风险包（MVP 模拟数据）
KNOWN_RISK_PACKAGES = {
    "pickle": {"severity": "high", "reason": "反序列化存在远程代码执行风险"},
    "PyYAML": {"severity": "medium", "reason": "yaml.load 可能导致任意代码执行"},
    "requests": {"severity": "low", "reason": "旧版本存在 SSL 验证绕过问题"},
    "urllib3": {"severity": "low", "reason": "需关注 CVE 更新"},
}

# 硬编码密钥检测模式
SECRET_PATTERNS = [
    (r"""password\s*=\s*['\"][^'\"]+['\"]""", "硬编码密码"),
    (r"""secret[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]""", "硬编码密钥"),
    (r"""api[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]""", "硬编码 API Key"),
    (r"""token\s*=\s*['\"][^'\"]{16,}['\"]""", "硬编码 Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key 格式"),
]

# 危险函数检测
DANGEROUS_FUNCTIONS = [
    ("eval(", "eval 函数执行任意代码"),
    ("exec(", "exec 函数执行任意代码"),
    ("__import__", "动态导入可能执行恶意代码"),
    ("os.system(", "系统命令执行"),
    ("subprocess.call(", "子进程调用"),
    ("subprocess.Popen(", "子进程调用"),
    ("pickle.loads(", "反序列化风险"),
    ("pickle.load(", "反序列化风险"),
    ("yaml.load(", "YAML 反序列化风险"),
]

# SQL 注入风险模式
SQL_INJECTION_PATTERNS = [
    (r"""f['\"].*\{.*\}.*['\"]\s*%\s*""", "f-string 拼接 SQL"),
    (r"""['\"].*['\"]\s*\+\s*""", "字符串拼接 SQL"),
    (r"\.format\(.*\)", "format 拼接 SQL"),
    (r"%s|%d", "百分号格式化 SQL"),
]

# 敏感数据泄露模式
SENSITIVE_DATA_PATTERNS = [
    (r"print\(.*password", "打印密码到日志"),
    (r"print\(.*secret", "打印密钥到日志"),
    (r"print\(.*token", "打印 Token 到日志"),
    (r"logging\.\w+\(.*password", "日志中输出密码"),
    (r"logging\.\w+\(.*secret", "日志中输出密钥"),
    (r".*\.plaintext.*", "明文密码相关"),
]

# 权限修改检测模式
PERMISSION_CHANGE_PATTERNS = [
    (r"""role\s*=\s*['\"]admin['\"]""", "直接设置管理员角色"),
    (r"""role\s*=\s*['\"]owner['\"]""", "直接设置 Owner 角色"),
    (r"chmod\s+777", "设置全局可写权限"),
    (r"grant\s+all", "数据库赋全部权限"),
]


def _audit_report_to_dict(report) -> Dict[str, Any]:
    """审计报告转字典"""
    return {
        "id": report.id,
        "plan_id": report.plan_id,
        "deployment_id": report.deployment_id,
        "sandbox_id": report.sandbox_id,
        "audit_type": report.audit_type,
        "status": report.status,
        "code_security_result": report.code_security_result or {},
        "dependency_security_result": report.dependency_security_result or {},
        "permission_check_result": report.permission_check_result or {},
        "data_security_result": report.data_security_result or {},
        "logic_security_result": report.logic_security_result or {},
        "compliance_result": report.compliance_result or {},
        "findings": report.findings or [],
        "issues": report.issues or [],
        "risk_level": report.risk_level,
        "score": report.score,
        "recommendation": report.recommendation,
        "auditor": report.auditor or report.auditor_id,
        "auditor_id": report.auditor_id,
        "reviewed_by": report.reviewed_by,
        "reviewed_at": report.reviewed_at.strftime("%Y-%m-%d %H:%M:%S") if report.reviewed_at else "",
        "audited_at": report.audited_at.strftime("%Y-%m-%d %H:%M:%S") if report.audited_at else "",
        "created_at": report.created_at.strftime("%Y-%m-%d %H:%M:%S") if report.created_at else "",
    }


def _check_code_security(code_content: str, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    代码安全检查
    - 危险函数（eval/exec 等）
    - 硬编码密钥
    - SQL 注入风险

    注意：MVP 阶段使用简化规则匹配，实际场景需要专业安全扫描工具
    """
    score = 100
    findings = []

    # 检查危险函数
    for func_name, description in DANGEROUS_FUNCTIONS:
        if func_name in code_content:
            count = code_content.count(func_name)
            findings.append({
                "type": "dangerous_function",
                "severity": "high",
                "item": func_name,
                "description": description,
                "count": count,
            })
            score -= min(count * 8, 25)
            issues.append({
                "category": "code_security",
                "severity": "high",
                "title": f"危险函数使用: {func_name}",
                "description": description,
                "suggestion": f"建议替换 {func_name} 为更安全的实现方式",
            })

    # 检查硬编码密钥
    for pattern, description in SECRET_PATTERNS:
        try:
            matches = re.findall(pattern, code_content, re.IGNORECASE)
            if matches:
                findings.append({
                    "type": "hardcoded_secret",
                    "severity": "critical",
                    "item": description,
                    "description": f"检测到 {len(matches)} 处疑似硬编码敏感信息",
                    "count": len(matches),
                })
                score -= min(len(matches) * 10, 30)
                issues.append({
                    "category": "code_security",
                    "severity": "critical",
                    "title": f"硬编码敏感信息: {description}",
                    "description": f"代码中检测到 {len(matches)} 处疑似硬编码的敏感信息",
                    "suggestion": "使用环境变量或配置管理系统存储敏感信息",
                })
        except re.error:
            pass

    # 检查 SQL 注入风险（简化检测）
    for pattern, description in SQL_INJECTION_PATTERNS:
        try:
            matches = re.findall(pattern, code_content)
            if matches:
                findings.append({
                    "type": "sql_injection_risk",
                    "severity": "high",
                    "item": description,
                    "count": len(matches),
                })
                score -= min(len(matches) * 5, 20)
        except re.error:
            pass

    score = max(0, score)
    status = "passed" if score >= 80 else ("warning" if score >= 60 else "failed")

    return {
        "score": score,
        "status": status,
        "findings": findings,
        "checked_items": [
            "危险函数检测",
            "硬编码密钥检测",
            "SQL 注入风险检测",
        ],
        "note": "MVP：基于规则的简化检测，实际场景需专业安全工具",
    }


def _check_dependency_security(requirements_content: str, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    依赖安全检查
    - 检查 requirements.txt 中的已知风险包

    MVP：使用固定风险包列表模拟，实际场景需要调用 CVE 数据库或专业工具
    """
    score = 100
    findings = []

    if not requirements_content:
        # MVP：模拟检查结果
        return {
            "score": 90,
            "status": "passed",
            "findings": [
                {
                    "type": "low_risk_dependency",
                    "severity": "low",
                    "item": "requests",
                    "description": "旧版本存在 SSL 验证绕过问题，建议升级到最新版本",
                },
            ],
            "checked_packages": 12,
            "vulnerable_count": 1,
            "note": "MVP：模拟依赖安全检查，实际场景需调用 CVE 数据库",
        }

    for pkg_name, risk_info in KNOWN_RISK_PACKAGES.items():
        if pkg_name.lower() in requirements_content.lower():
            findings.append({
                "type": "vulnerable_dependency",
                "severity": risk_info["severity"],
                "item": pkg_name,
                "description": risk_info["reason"],
            })
            if risk_info["severity"] == "critical":
                score -= 25
            elif risk_info["severity"] == "high":
                score -= 15
            elif risk_info["severity"] == "medium":
                score -= 8
            else:
                score -= 3

            issues.append({
                "category": "dependency_security",
                "severity": risk_info["severity"],
                "title": f"风险依赖: {pkg_name}",
                "description": risk_info["reason"],
                "suggestion": "升级到安全版本或寻找替代方案",
            })

    score = max(0, score)
    status = "passed" if score >= 80 else ("warning" if score >= 60 else "failed")

    return {
        "score": score,
        "status": status,
        "findings": findings,
        "checked_packages": len(KNOWN_RISK_PACKAGES),
        "vulnerable_count": len(findings),
    }


def _check_permission_security(code_content: str, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    权限安全检查
    - 检查是否试图修改权限系统

    MVP：基于规则的简化检测
    """
    score = 100
    findings = []

    for pattern, description in PERMISSION_CHANGE_PATTERNS:
        if re.search(pattern, code_content, re.IGNORECASE):
            score -= 30
            findings.append({
                "type": "permission_change",
                "severity": "high",
                "item": description,
            })
            issues.append({
                "category": "permission_security",
                "severity": "high",
                "title": f"权限变更风险: {description}",
                "description": f"检测到可能的权限提升或权限变更操作: {description}",
                "suggestion": "权限变更需经过严格的审批流程",
            })

    score = max(0, score)
    status = "passed" if score >= 80 else ("warning" if score >= 60 else "failed")
    return {
        "score": score,
        "status": status,
        "findings": findings,
    }


def _check_data_security(code_content: str, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    数据安全检查
    - 检查是否有明文密码、敏感数据泄露

    MVP：基于规则的简化检测
    """
    score = 100
    findings = []

    for pattern, description in SENSITIVE_DATA_PATTERNS:
        try:
            matches = re.findall(pattern, code_content, re.IGNORECASE)
            if matches:
                score -= min(len(matches) * 5, 20)
                findings.append({
                    "type": "sensitive_data_leak",
                    "severity": "medium",
                    "item": description,
                    "count": len(matches),
                })
                issues.append({
                    "category": "data_security",
                    "severity": "medium",
                    "title": f"敏感数据泄露风险: {description}",
                    "description": f"检测到 {len(matches)} 处可能的敏感数据泄露",
                    "suggestion": "敏感数据不应直接打印或记录到日志中",
                })
        except re.error:
            pass

    score = max(0, score)
    status = "passed" if score >= 80 else ("warning" if score >= 60 else "failed")
    return {
        "score": score,
        "status": status,
        "findings": findings,
    }


def _calculate_risk_level(issues: List[Dict[str, Any]]) -> str:
    """根据问题列表计算整体风险等级"""
    critical = sum(1 for i in issues if i.get("severity") == "critical")
    high = sum(1 for i in issues if i.get("severity") == "high")
    medium = sum(1 for i in issues if i.get("severity") == "medium")

    if critical > 0:
        return "critical"
    elif high >= 2:
        return "high"
    elif high >= 1 or medium >= 3:
        return "medium"
    else:
        return "low"


def _calculate_recommendation(risk_level: str, plan_type: str) -> str:
    """根据风险等级和计划类型给出建议"""
    if risk_level == "critical":
        return "reject"
    elif risk_level == "high":
        return "modify"
    elif risk_level == "medium":
        # 文档和测试类型风险可接受
        if plan_type in ("doc_improvement", "test_enhancement"):
            return "approve"
        return "modify"
    else:
        return "approve"


def _plan_to_dict(plan) -> Dict[str, Any]:
    """计划简要信息"""
    return {
        "plan_id": plan.plan_id,
        "title": plan.title,
        "type": plan.type,
        "module_key": plan.module_key,
        "status": plan.status,
        "priority": plan.priority,
        "risk_level": plan.risk_level,
        "description": plan.description,
        "expected_effect": plan.expected_effect,
    }


# ============================================================
# 审计接口
# ============================================================

@router.post("/audit/{plan_id}")
async def start_audit(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """启动安全审计
    MVP：基于规则的静态检查，代码内容为模拟
    检查项：
    - 代码安全：检查是否有 eval/exec、硬编码密钥、SQL注入风险
    - 依赖安全：检查已知风险包（MVP 模拟）
    - 权限检查：检查是否试图修改权限系统
    - 数据安全：检查是否有明文密码、敏感数据泄露
    风险评级：低/中/高/极高

    注意：
    - 代码内容为模拟（从候选方案描述中提取），实际场景需从代码仓库获取
    - 依赖安全检查为模拟，实际场景需调用 CVE 数据库
    - 逻辑安全和合规性检查为 MVP 简化版本
    """
    repo = _get_repo(db)
    plan = repo.plans.get_by_id(plan_id)
    if not plan:
        return ApiResponse.error(code=404, message="进化计划不存在")

    # 检查计划状态
    if plan.status != "selected":
        return ApiResponse.error(
            code=400,
            message=f"计划状态为 {plan.status}，需先选定候选方案才能进行审计"
        )

    # 获取选中的候选方案
    selected_candidate = repo.candidates.get_selected(plan.plan_id)

    # MVP：模拟代码内容（根据方案内容生成模拟代码用于审计）
    # 实际场景中应该从代码仓库或沙箱中获取实际代码
    mock_code_content = ""
    if selected_candidate:
        mock_code_content = selected_candidate.approach or selected_candidate.description or ""

    # 收集所有问题
    issues: List[Dict[str, Any]] = []
    all_findings: List[Dict[str, Any]] = []

    # 1. 代码安全检查
    code_security_result = _check_code_security(mock_code_content, issues)
    all_findings.extend(code_security_result.get("findings", []))

    # 2. 依赖安全检查（MVP 模拟）
    dependency_security_result = _check_dependency_security("", issues)
    all_findings.extend(dependency_security_result.get("findings", []))

    # 3. 权限检查
    permission_result = _check_permission_security(mock_code_content, issues)

    # 4. 数据安全检查
    data_security_result = _check_data_security(mock_code_content, issues)

    # 5. 逻辑安全（MVP：默认通过，文档/测试类型风险低）
    if plan.type in ("doc_improvement", "test_enhancement"):
        logic_result = {"score": 95, "status": "passed", "note": "文档/测试类型，逻辑安全风险低"}
    elif plan.type == "bug_fix":
        logic_result = {"score": 85, "status": "passed", "note": "Bug修复类型，需关注逻辑正确性"}
    else:
        logic_result = {"score": 75, "status": "warning", "note": "MVP：逻辑安全需人工复核"}

    # 6. 合规性检查（MVP：默认通过）
    if plan.risk_level in ("high", "critical"):
        compliance_result = {"score": 70, "status": "warning", "note": "高风险计划需额外合规审查"}
    else:
        compliance_result = {"score": 95, "status": "passed", "note": "MVP：合规性检查简化版本"}

    # 计算整体安全评分
    total_score = round(
        code_security_result.get("score", 100) * 0.30 +
        dependency_security_result.get("score", 100) * 0.20 +
        permission_result.get("score", 100) * 0.20 +
        data_security_result.get("score", 100) * 0.15 +
        logic_result.get("score", 100) * 0.10 +
        compliance_result.get("score", 100) * 0.05,
        2
    )

    # 计算整体风险等级
    risk_level = _calculate_risk_level(issues)

    # 如果是文档/测试类型，降低一个风险等级
    if plan.type in ("doc_improvement", "test_enhancement"):
        level_order = ["low", "medium", "high", "critical"]
        current_idx = level_order.index(risk_level)
        if current_idx > 0:
            risk_level = level_order[current_idx - 1]

    # 生成建议
    recommendation = _calculate_recommendation(risk_level, plan.type)

    username = current_user.get("username", "system")

    # 保存审计报告到数据库
    report = repo.audits.create(
        plan_id=plan.plan_id,
        audit_type="security",
        code_security=code_security_result,
        dependency_security=dependency_security_result,
        permission_check=permission_result,
        data_security=data_security_result,
        logic_security=logic_result,
        compliance=compliance_result,
        issues=issues,
        risk_level=risk_level,
        score=total_score,
        recommendation=recommendation,
        auditor=username,
        findings=all_findings,
    )

    # 更新计划状态
    repo.plans.update_status(plan.plan_id, "auditing")

    return ApiResponse.success(
        data={
            "report": _audit_report_to_dict(report),
            "plan_status": "auditing",
            "note": "MVP：代码内容为模拟，依赖安全检查为模拟，实际场景需专业安全工具",
        },
        message="安全审计完成（MVP：基于规则的简化检测）"
    )


@router.get("/reports")
async def get_audit_reports(
    plan_id: Optional[str] = Query(None, description="计划ID筛选"),
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    recommendation: Optional[str] = Query(None, description="建议筛选"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """审计报告列表"""
    repo = _get_repo(db)
    reports, total = repo.audits.list(
        page=page,
        page_size=page_size,
        plan_id=plan_id,
        risk_level=risk_level,
        recommendation=recommendation,
    )

    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_audit_report_to_dict(r) for r in reports],
    })


@router.get("/reports/{report_id}")
async def get_audit_report_detail(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """审计报告详情"""
    repo = _get_repo(db)
    report = repo.audits.get_by_id(report_id)
    if not report:
        return ApiResponse.error(code=404, message="审计报告不存在")

    result = _audit_report_to_dict(report)

    # 关联计划信息
    plan = repo.plans.get_by_id(report.plan_id)
    if plan:
        result["plan"] = _plan_to_dict(plan)

    return ApiResponse.success(data=result)


@router.post("/reports/{report_id}/approve")
async def approve_audit(
    report_id: int,
    request: AuditDecisionRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """审计通过（人工复核通过）"""
    repo = _get_repo(db)
    report = repo.audits.get_by_id(report_id)
    if not report:
        return ApiResponse.error(code=404, message="审计报告不存在")

    username = current_user.get("username", "system")

    # 更新建议为通过
    updated = repo.audits.update_recommendation(
        report_id=report_id,
        recommendation="approve",
        auditor=username,
    )

    # 更新关联计划状态
    repo.plans.update_status(report.plan_id, "approved")

    return ApiResponse.success(
        data=_audit_report_to_dict(updated),
        message="审计已通过"
    )


@router.post("/reports/{report_id}/reject")
async def reject_audit(
    report_id: int,
    request: AuditDecisionRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """审计拒绝（人工复核拒绝）"""
    repo = _get_repo(db)
    report = repo.audits.get_by_id(report_id)
    if not report:
        return ApiResponse.error(code=404, message="审计报告不存在")

    username = current_user.get("username", "system")

    # 更新建议为拒绝
    updated = repo.audits.update_recommendation(
        report_id=report_id,
        recommendation="reject",
        auditor=username,
    )

    # 更新关联计划状态
    repo.plans.update_status(report.plan_id, "failed")

    return ApiResponse.success(
        data=_audit_report_to_dict(updated),
        message="审计已拒绝"
    )


@router.post("/reports/{report_id}/request-change")
async def request_change(
    report_id: int,
    request: AuditDecisionRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """要求修改（人工复核要求修改）"""
    repo = _get_repo(db)
    report = repo.audits.get_by_id(report_id)
    if not report:
        return ApiResponse.error(code=404, message="审计报告不存在")

    username = current_user.get("username", "system")

    # 更新建议为修改
    updated = repo.audits.update_recommendation(
        report_id=report_id,
        recommendation="modify",
        auditor=username,
    )

    # 更新关联计划状态
    repo.plans.update_status(report.plan_id, "draft")

    return ApiResponse.success(
        data=_audit_report_to_dict(updated),
        message="已要求修改方案"
    )
