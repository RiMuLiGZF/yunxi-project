"""
自进化引擎 - 部署治理器路由
- 审批请求管理
- 进化版本管理
- 一键回滚
- 部署执行（MVP 模拟，数据库持久化）

所有操作需要认证
首次访问自动初始化示例数据
"""

import sys
import uuid
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

class ApprovalDecisionRequest(BaseModel):
    """审批决策请求体"""
    comment: str = Field("", description="审批意见")


class RollbackRequest(BaseModel):
    """回滚请求体"""
    reason: str = Field("", description="回滚原因")
    to_version_id: Optional[str] = Field(None, description="目标版本ID（不传则回滚到上一版本）")


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


def _is_owner(user: dict) -> bool:
    """检查用户是否为 owner 角色"""
    return user.get("role", "").lower() == "owner"


def _approval_to_dict(approval) -> Dict[str, Any]:
    """审批转字典"""
    return {
        "id": approval.id,
        "plan_id": approval.plan_id,
        "audit_report_id": approval.audit_report_id,
        "submitter": approval.submitter,
        "status": approval.status,
        "approver": approval.approver,
        "approval_comment": approval.approval_comment,
        "submitted_at": approval.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if approval.submitted_at else "",
        "decided_at": approval.decided_at.strftime("%Y-%m-%d %H:%M:%S") if approval.decided_at else "",
        "created_at": approval.created_at.strftime("%Y-%m-%d %H:%M:%S") if approval.created_at else "",
    }


def _version_to_dict(version) -> Dict[str, Any]:
    """版本转字典"""
    return {
        "id": version.id,
        "version_id": version.version_id,
        "module_key": version.module_key,
        "version_name": version.version_name,
        "evo_sequence": version.evo_sequence,
        "parent_version_id": version.parent_version_id,
        "changelog": version.changelog,
        "plan_id": version.plan_id,
        "status": version.status,
        "deployed_at": version.deployed_at.strftime("%Y-%m-%d %H:%M:%S") if version.deployed_at else "",
        "created_at": version.created_at.strftime("%Y-%m-%d %H:%M:%S") if version.created_at else "",
    }


def _rollback_to_dict(record) -> Dict[str, Any]:
    """回滚记录转字典"""
    return {
        "id": record.id,
        "module_key": record.module_key,
        "from_version": record.from_version,
        "to_version": record.to_version,
        "reason": record.reason,
        "triggered_by": record.triggered_by,
        "rollback_time": record.rollback_time.strftime("%Y-%m-%d %H:%M:%S") if record.rollback_time else "",
        "verification_result": record.verification_result,
        "created_at": record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else "",
    }


def _deployment_to_dict(deployment) -> Dict[str, Any]:
    """部署记录转字典"""
    return {
        "id": deployment.id,
        "plan_id": deployment.plan_id,
        "candidate_id": deployment.candidate_id,
        "version_id": deployment.version_id,
        "status": deployment.status,
        "version": deployment.version,
        "deploy_log": deployment.deploy_log,
        "deployed_by": deployment.deployed_by,
        "started_at": deployment.started_at.strftime("%Y-%m-%d %H:%M:%S") if deployment.started_at else "",
        "completed_at": deployment.completed_at.strftime("%Y-%m-%d %H:%M:%S") if deployment.completed_at else "",
        "created_at": deployment.created_at.strftime("%Y-%m-%d %H:%M:%S") if deployment.created_at else "",
    }


def _plan_to_dict(plan) -> Dict[str, Any]:
    """计划简要信息转字典"""
    return {
        "plan_id": plan.plan_id,
        "title": plan.title,
        "description": plan.description,
        "type": plan.type,
        "module_key": plan.module_key,
        "priority": plan.priority,
        "risk_level": plan.risk_level,
        "expected_effect": plan.expected_effect,
        "status": plan.status,
        "created_by": plan.created_by,
    }


# ============================================================
# 审批接口
# ============================================================

@router.get("/approvals")
async def get_approvals(
    status: Optional[str] = Query(None, description="状态筛选: pending/approved/rejected/modified"),
    plan_id: Optional[str] = Query(None, description="计划ID筛选"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """审批列表"""
    repo = _get_repo(db)
    approvals, total = repo.approvals.list(
        page=page,
        page_size=page_size,
        status=status,
        plan_id=plan_id,
    )

    # 关联计划信息
    items = []
    for approval in approvals:
        item = _approval_to_dict(approval)
        plan = repo.plans.get_by_id(approval.plan_id)
        if plan:
            item["plan"] = {
                "plan_id": plan.plan_id,
                "title": plan.title,
                "type": plan.type,
                "module_key": plan.module_key,
                "priority": plan.priority,
            }
        items.append(item)

    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    })


@router.get("/approvals/{approval_id}")
async def get_approval_detail(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """审批详情"""
    repo = _get_repo(db)
    approval = repo.approvals.get_by_id(approval_id)
    if not approval:
        return ApiResponse.error(code=404, message="审批请求不存在")

    result = _approval_to_dict(approval)

    # 关联计划信息
    plan = repo.plans.get_by_id(approval.plan_id)
    if plan:
        result["plan"] = _plan_to_dict(plan)

    # 关联审计报告
    if approval.audit_report_id:
        report = repo.audits.get_by_id(approval.audit_report_id)
        if report:
            result["audit_report"] = {
                "id": report.id,
                "risk_level": report.risk_level,
                "recommendation": report.recommendation,
                "score": report.score,
                "issues_count": len(report.issues or []),
                "audited_at": report.audited_at.strftime("%Y-%m-%d %H:%M:%S") if report.audited_at else "",
            }

    return ApiResponse.success(data=result)


@router.post("/approvals/{approval_id}/submit")
async def submit_approval(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """提交审批请求（从计划创建审批）"""
    repo = _get_repo(db)
    approval = repo.approvals.get_by_id(approval_id)
    if not approval:
        return ApiResponse.error(code=404, message="审批请求不存在")

    if approval.status != "draft":
        return ApiResponse.error(
            code=400,
            message=f"审批状态为 {approval.status}，无法重复提交"
        )

    approval.status = "pending"
    approval.submitted_at = datetime.utcnow()
    db.commit()
    db.refresh(approval)

    return ApiResponse.success(
        data=_approval_to_dict(approval),
        message="审批已提交"
    )


@router.post("/approvals/{approval_id}/approve")
async def approve_deployment(
    approval_id: int,
    request: ApprovalDecisionRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """批准部署（仅 owner 角色）"""
    # 权限检查
    if not _is_owner(current_user):
        return ApiResponse.error(
            code=403,
            message="权限不足，仅 owner 角色可批准部署"
        )

    repo = _get_repo(db)
    approval = repo.approvals.get_by_id(approval_id)
    if not approval:
        return ApiResponse.error(code=404, message="审批请求不存在")

    if approval.status != "pending":
        return ApiResponse.error(
            code=400,
            message=f"审批状态为 {approval.status}，无法重复审批"
        )

    username = current_user.get("username", "unknown")
    comment = request.comment if request else ""

    # 更新审批状态
    approved = repo.approvals.decide(
        approval_id=approval_id,
        status="approved",
        approver=username,
        comment=comment,
    )

    # 更新计划状态
    repo.plans.update_status(approval.plan_id, "approved")

    return ApiResponse.success(
        data=_approval_to_dict(approved),
        message="部署已批准"
    )


@router.post("/approvals/{approval_id}/reject")
async def reject_deployment(
    approval_id: int,
    request: ApprovalDecisionRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """拒绝部署"""
    repo = _get_repo(db)
    approval = repo.approvals.get_by_id(approval_id)
    if not approval:
        return ApiResponse.error(code=404, message="审批请求不存在")

    if approval.status != "pending":
        return ApiResponse.error(
            code=400,
            message=f"审批状态为 {approval.status}，无法重复审批"
        )

    username = current_user.get("username", "unknown")
    comment = request.comment if request else ""

    # 更新审批状态
    rejected = repo.approvals.decide(
        approval_id=approval_id,
        status="rejected",
        approver=username,
        comment=comment,
    )

    # 更新计划状态
    repo.plans.update_status(approval.plan_id, "failed")

    return ApiResponse.success(
        data=_approval_to_dict(rejected),
        message="部署已拒绝"
    )


@router.post("/approvals/{approval_id}/request-change")
async def request_change_deployment(
    approval_id: int,
    request: ApprovalDecisionRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """要求修改"""
    repo = _get_repo(db)
    approval = repo.approvals.get_by_id(approval_id)
    if not approval:
        return ApiResponse.error(code=404, message="审批请求不存在")

    if approval.status != "pending":
        return ApiResponse.error(
            code=400,
            message=f"审批状态为 {approval.status}，无法重复审批"
        )

    username = current_user.get("username", "unknown")
    comment = request.comment if request else ""

    # 更新审批状态
    modified = repo.approvals.decide(
        approval_id=approval_id,
        status="modified",
        approver=username,
        comment=comment,
    )

    # 更新计划状态
    repo.plans.update_status(approval.plan_id, "draft")

    return ApiResponse.success(
        data=_approval_to_dict(modified),
        message="已要求修改方案"
    )


# ============================================================
# 部署接口
# ============================================================

@router.post("/deploy/{plan_id}")
async def execute_deploy(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """执行部署（MVP：标记为已部署，生成版本记录，模拟实际部署过程）
    实际场景需要 CI/CD 流水线支持
    """
    repo = _get_repo(db)
    plan = repo.plans.get_by_id(plan_id)
    if not plan:
        return ApiResponse.error(code=404, message="进化计划不存在")

    # 检查计划状态
    if plan.status not in ("approved", "selected", "auditing"):
        return ApiResponse.error(
            code=400,
            message=f"计划状态为 {plan.status}，需审批通过后才能部署"
        )

    # 获取选中的候选方案
    selected_candidate = repo.candidates.get_selected(plan.plan_id)

    username = current_user.get("username", "system")

    # 更新计划状态为部署中
    repo.plans.update_status(plan.plan_id, "deploying")

    # 获取当前最新版本
    latest_version = repo.versions.get_latest_stable(plan.module_key)
    parent_version_id = latest_version.version_id if latest_version else None
    new_sequence = (latest_version.evo_sequence + 1) if latest_version else 1

    # 生成版本名称
    version_name = f"evo-{plan.type}-{new_sequence:03d}"

    # 创建版本记录
    version = repo.versions.create(
        module_key=plan.module_key,
        version_name=version_name,
        plan_id=plan.plan_id,
        changelog=selected_candidate.approach if selected_candidate else plan.description,
        parent_version_id=parent_version_id,
        status="stable",
    )

    # 创建部署记录
    deployment = repo.deployments.create(
        plan_id=plan.plan_id,
        candidate_id=selected_candidate.candidate_id if selected_candidate else "",
        version=version_name,
        deployed_by=username,
    )
    # 关联版本ID
    deployment.version_id = version.version_id
    repo.deployments.complete(
        deployment_id=deployment.id,
        status="completed",
        deploy_log=f"[MVP模拟] 部署完成\n模块: {plan.module_key}\n版本: {version_name}\n部署人: {username}\n时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
    )

    # 更新计划状态为完成
    repo.plans.update_status(plan.plan_id, "completed")

    # 创建审批记录（如果还没有）
    existing_approval = repo.approvals.get_by_plan(plan.plan_id)
    if not existing_approval:
        # MVP：自动创建并批准（模拟审批流程）
        repo.approvals.create(
            plan_id=plan.plan_id,
            submitter=username,
        )
        repo.approvals.decide(
            approval_id=repo.approvals.get_by_plan(plan.plan_id).id,
            status="approved",
            approver=username,
            comment="MVP 自动批准",
        )

    return ApiResponse.success(
        data={
            "plan": {
                "plan_id": plan.plan_id,
                "title": plan.title,
                "status": "completed",
            },
            "version": _version_to_dict(version),
            "deployment": _deployment_to_dict(deployment),
            "deploy_info": {
                "module_key": plan.module_key,
                "deployed_at": version.deployed_at.strftime("%Y-%m-%d %H:%M:%S") if version.deployed_at else "",
                "sequence": new_sequence,
                "note": "MVP：部署过程为模拟，实际场景需要 CI/CD 流水线支持",
            },
        },
        message="部署完成，版本已生成（MVP：模拟部署）"
    )


@router.get("/deployments")
async def get_deployments(
    status: Optional[str] = Query(None, description="状态筛选"),
    plan_id: Optional[str] = Query(None, description="计划ID筛选"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """部署记录列表"""
    repo = _get_repo(db)
    deployments, total = repo.deployments.list(
        page=page,
        page_size=page_size,
        status=status,
        plan_id=plan_id,
    )

    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_deployment_to_dict(d) for d in deployments],
    })


@router.get("/deployments/{deployment_id}")
async def get_deployment_detail(
    deployment_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """部署详情"""
    repo = _get_repo(db)
    deployment = repo.deployments.get_by_id(deployment_id)
    if not deployment:
        return ApiResponse.error(code=404, message="部署记录不存在")

    result = _deployment_to_dict(deployment)

    # 关联计划信息
    plan = repo.plans.get_by_id(deployment.plan_id)
    if plan:
        result["plan"] = _plan_to_dict(plan)

    return ApiResponse.success(data=result)


@router.post("/rollback/{module_key}")
async def rollback_module(
    module_key: str,
    request: RollbackRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """一键回滚（MVP：模拟回滚过程，更新版本状态）
    实际场景需要 CI/CD 流水线支持回滚操作
    """
    repo = _get_repo(db)

    # 获取当前最新稳定版本
    current_version = repo.versions.get_latest_stable(module_key)
    if not current_version:
        return ApiResponse.error(
            code=400,
            message=f"模块 {module_key} 没有可回滚的版本"
        )

    # 确定目标版本
    target_version_id = request.to_version_id if request and request.to_version_id else current_version.parent_version_id

    if not target_version_id:
        return ApiResponse.error(
            code=400,
            message="没有可回滚的上一版本（当前为初始版本）"
        )

    # 查询目标版本
    target_version = repo.versions.get_by_id(target_version_id)
    if not target_version:
        return ApiResponse.error(code=404, message="目标版本不存在")

    username = current_user.get("username", "unknown")
    reason = request.reason if request and request.reason else "手动触发回滚"

    # 标记当前版本为已回滚
    repo.versions.rollback(current_version.version_id)

    # 创建回滚记录
    rollback = repo.rollbacks.create(
        module_key=module_key,
        from_version=current_version.version_id,
        to_version=target_version.version_id,
        reason=reason,
        triggered_by=username,
        verification_result="passed",  # MVP：默认验证通过
    )

    # 更新关联计划状态
    plan = repo.plans.get_by_id(current_version.plan_id)
    if plan:
        repo.plans.update_status(plan.plan_id, "failed")

    return ApiResponse.success(
        data={
            "rollback": _rollback_to_dict(rollback),
            "from_version": {
                "version_id": current_version.version_id,
                "version_name": current_version.version_name,
                "status": "rolled_back",
            },
            "to_version": {
                "version_id": target_version.version_id,
                "version_name": target_version.version_name,
                "status": target_version.status,
            },
            "note": "MVP：回滚过程为模拟，实际场景需要 CI/CD 流水线支持",
        },
        message=f"模块 {module_key} 已回滚到版本 {target_version.version_name}（MVP：模拟回滚）"
    )


# ============================================================
# 版本接口
# ============================================================

@router.get("/versions/{module_key}")
async def get_module_versions(
    module_key: str,
    status: Optional[str] = Query(None, description="状态筛选: stable/failed/rolled_back"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """版本列表"""
    repo = _get_repo(db)
    versions, total = repo.versions.list_by_module(
        module_key=module_key,
        page=page,
        page_size=page_size,
        status=status,
    )

    return ApiResponse.success(data={
        "module_key": module_key,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_version_to_dict(v) for v in versions],
    })


@router.get("/versions/id/{version_id}")
async def get_version_detail(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """版本详情"""
    repo = _get_repo(db)
    version = repo.versions.get_by_id(version_id)
    if not version:
        return ApiResponse.error(code=404, message="版本不存在")

    result = _version_to_dict(version)

    # 关联计划信息
    plan = repo.plans.get_by_id(version.plan_id)
    if plan:
        result["plan"] = {
            "plan_id": plan.plan_id,
            "title": plan.title,
            "type": plan.type,
            "priority": plan.priority,
        }

    # 父版本信息
    if version.parent_version_id:
        parent = repo.versions.get_by_id(version.parent_version_id)
        if parent:
            result["parent_version"] = {
                "version_id": parent.version_id,
                "version_name": parent.version_name,
                "status": parent.status,
            }

    return ApiResponse.success(data=result)


@router.get("/versions/{module_key}/latest")
async def get_latest_version(
    module_key: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取模块最新版本"""
    repo = _get_repo(db)
    version = repo.versions.get_latest_stable(module_key)
    if not version:
        return ApiResponse.error(code=404, message=f"模块 {module_key} 暂无版本记录")

    return ApiResponse.success(data=_version_to_dict(version))


@router.get("/rollbacks/{module_key}")
async def get_rollback_history(
    module_key: str,
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """回滚历史"""
    repo = _get_repo(db)
    records, total = repo.rollbacks.list_by_module(
        module_key=module_key,
        page=page,
        page_size=page_size,
    )

    return ApiResponse.success(data={
        "module_key": module_key,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_rollback_to_dict(r) for r in records],
    })
