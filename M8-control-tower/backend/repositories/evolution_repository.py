"""
M8 自进化引擎 - 数据仓库

封装进化系统所有数据库 CRUD 和查询操作。
- 健康扫描记录
- 进化计划管理
- 候选方案管理
- 部署记录管理
- 版本与回滚管理
- 审计报告管理

首次访问时自动初始化示例数据。
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models import (
    EvoHealthScan,
    EvoPlan,
    EvoCandidate,
    EvoApproval,
    EvoVersion,
    EvoRollbackRecord,
    EvoDeployment,
    EvoAuditReport,
)


# ============================================================
# 工具函数
# ============================================================

def _generate_plan_id() -> str:
    """生成计划ID"""
    return f"plan_{uuid.uuid4().hex[:12]}"


def _generate_candidate_id() -> str:
    """生成候选方案ID"""
    return f"cand_{uuid.uuid4().hex[:10]}"


def _generate_version_id() -> str:
    """生成版本ID"""
    return f"ver_{uuid.uuid4().hex[:12]}"


# ============================================================
# 健康扫描仓库
# ============================================================

class ScanRepository:
    """健康扫描数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, scan_type: str = "health", status: str = "running",
               overall_score: float = 0.0, module_scores: Optional[Dict] = None,
               anomalies: Optional[List] = None, recommendations: Optional[List] = None,
               result_json: Optional[Dict] = None, user_id: int = 1) -> EvoHealthScan:
        """创建扫描记录"""
        now = datetime.utcnow()
        scan = EvoHealthScan(
            scan_type=scan_type,
            status=status,
            overall_score=overall_score,
            module_scores=module_scores or {},
            anomalies=anomalies or [],
            recommendations=recommendations or [],
            result_json=result_json or {},
            started_at=now,
            user_id=user_id,
        )
        self.db.add(scan)
        self.db.commit()
        self.db.refresh(scan)
        return scan

    def complete(self, scan_id: int, overall_score: float,
                 module_scores: Dict, anomalies: List,
                 recommendations: List, files_scanned: int = 0,
                 issues_found: int = 0, result_json: Optional[Dict] = None) -> Optional[EvoHealthScan]:
        """标记扫描完成"""
        scan = self.db.query(EvoHealthScan).filter(EvoHealthScan.id == scan_id).first()
        if not scan:
            return None
        scan.status = "completed"
        scan.overall_score = overall_score
        scan.module_scores = module_scores
        scan.anomalies = anomalies
        scan.recommendations = recommendations
        scan.files_scanned = files_scanned
        scan.issues_found = issues_found
        scan.result_json = result_json or {}
        scan.scan_time = datetime.utcnow()
        scan.completed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(scan)
        return scan

    def get_by_id(self, scan_id: int) -> Optional[EvoHealthScan]:
        """按ID获取扫描记录"""
        return self.db.query(EvoHealthScan).filter(EvoHealthScan.id == scan_id).first()

    def list(self, page: int = 1, page_size: int = 20,
             scan_type: Optional[str] = None,
             status: Optional[str] = None) -> Tuple[List[EvoHealthScan], int]:
        """扫描记录列表（分页）"""
        query = self.db.query(EvoHealthScan)
        if scan_type:
            query = query.filter(EvoHealthScan.scan_type == scan_type)
        if status:
            query = query.filter(EvoHealthScan.status == status)
        total = query.count()
        items = (
            query.order_by(desc(EvoHealthScan.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def count(self) -> int:
        """总扫描数"""
        return self.db.query(EvoHealthScan).count()


# ============================================================
# 进化计划仓库
# ============================================================

class PlanRepository:
    """进化计划数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, title: str, description: str = "", plan_type: str = "doc_improvement",
               module_key: str = "", priority: str = "medium", risk_level: str = "low",
               expected_effect: str = "", created_by: str = "",
               scan_id: Optional[int] = None) -> EvoPlan:
        """创建进化计划"""
        plan = EvoPlan(
            plan_id=_generate_plan_id(),
            title=title,
            description=description,
            type=plan_type,
            module_key=module_key,
            status="draft",
            priority=priority,
            risk_level=risk_level,
            expected_effect=expected_effect,
            created_by=created_by,
            scan_id=scan_id,
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def get_by_id(self, plan_id: str) -> Optional[EvoPlan]:
        """按业务ID获取计划"""
        plan = self.db.query(EvoPlan).filter(EvoPlan.plan_id == plan_id).first()
        if not plan and plan_id.isdigit():
            plan = self.db.query(EvoPlan).filter(EvoPlan.id == int(plan_id)).first()
        return plan

    def update_status(self, plan_id: str, status: str) -> Optional[EvoPlan]:
        """更新计划状态"""
        plan = self.get_by_id(plan_id)
        if not plan:
            return None
        plan.status = status
        plan.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def list(self, page: int = 1, page_size: int = 20,
             status: Optional[str] = None, module_key: Optional[str] = None,
             plan_type: Optional[str] = None) -> Tuple[List[EvoPlan], int]:
        """计划列表（分页）"""
        query = self.db.query(EvoPlan)
        if status:
            query = query.filter(EvoPlan.status == status)
        if module_key:
            query = query.filter(EvoPlan.module_key == module_key)
        if plan_type:
            query = query.filter(EvoPlan.type == plan_type)
        total = query.count()
        items = (
            query.order_by(desc(EvoPlan.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def count(self) -> int:
        """总计划数"""
        return self.db.query(EvoPlan).count()


# ============================================================
# 候选方案仓库
# ============================================================

class CandidateRepository:
    """候选方案数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, plan_id: str, name: str, approach: str = "",
               expected_effect: str = "", risk_assessment: str = "",
               cost_estimate: str = "", description: str = "",
               estimated_effort: str = "", risk_level: str = "low") -> EvoCandidate:
        """创建候选方案"""
        candidate = EvoCandidate(
            plan_id=plan_id,
            candidate_id=_generate_candidate_id(),
            name=name,
            title=name,
            approach=approach,
            description=description,
            expected_effect=expected_effect,
            risk_assessment=risk_assessment,
            cost_estimate=cost_estimate,
            estimated_effort=estimated_effort,
            risk_level=risk_level,
        )
        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def batch_create(self, candidates: List[Dict[str, Any]]) -> List[EvoCandidate]:
        """批量创建候选方案"""
        result = []
        for data in candidates:
            cand = EvoCandidate(
                plan_id=data.get("plan_id", ""),
                candidate_id=_generate_candidate_id(),
                name=data.get("name", ""),
                title=data.get("name", ""),
                approach=data.get("approach", ""),
                description=data.get("description", ""),
                expected_effect=data.get("expected_effect", ""),
                risk_assessment=data.get("risk_assessment", ""),
                cost_estimate=data.get("cost_estimate", ""),
                estimated_effort=data.get("estimated_effort", ""),
                risk_level=data.get("risk_level", "low"),
            )
            self.db.add(cand)
            result.append(cand)
        self.db.commit()
        for cand in result:
            self.db.refresh(cand)
        return result

    def get_by_id(self, candidate_id: str) -> Optional[EvoCandidate]:
        """按业务ID获取候选方案"""
        return (
            self.db.query(EvoCandidate)
            .filter(EvoCandidate.candidate_id == candidate_id)
            .first()
        )

    def list_by_plan(self, plan_id: str) -> List[EvoCandidate]:
        """获取计划的所有候选方案"""
        return (
            self.db.query(EvoCandidate)
            .filter(EvoCandidate.plan_id == plan_id)
            .order_by(EvoCandidate.created_at.asc())
            .all()
        )

    def count_by_plan(self, plan_id: str) -> int:
        """计划的候选方案数量"""
        return (
            self.db.query(EvoCandidate)
            .filter(EvoCandidate.plan_id == plan_id)
            .count()
        )

    def get_selected(self, plan_id: str) -> Optional[EvoCandidate]:
        """获取计划选中的候选方案"""
        return (
            self.db.query(EvoCandidate)
            .filter(
                EvoCandidate.plan_id == plan_id,
                EvoCandidate.is_selected == True,  # noqa: E712
            )
            .first()
        )

    def select(self, plan_id: str, candidate_id: str) -> Optional[EvoCandidate]:
        """选中某个候选方案（取消其他方案的选中状态）"""
        self.db.query(EvoCandidate).filter(
            EvoCandidate.plan_id == plan_id,
            EvoCandidate.candidate_id != candidate_id,
        ).update({"is_selected": False, "status": "rejected"})

        candidate = self.get_by_id(candidate_id)
        if candidate:
            candidate.is_selected = True
            candidate.status = "selected"
            self.db.commit()
            self.db.refresh(candidate)
        return candidate

    def vote(self, candidate_id: str) -> Optional[EvoCandidate]:
        """投票"""
        candidate = self.get_by_id(candidate_id)
        if candidate:
            candidate.vote_count += 1
            self.db.commit()
            self.db.refresh(candidate)
        return candidate


# ============================================================
# 审批仓库
# ============================================================

class ApprovalRepository:
    """审批数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, plan_id: str, submitter: str = "",
               audit_report_id: Optional[int] = None) -> EvoApproval:
        """创建审批请求"""
        approval = EvoApproval(
            plan_id=plan_id,
            audit_report_id=audit_report_id,
            submitter=submitter,
            status="pending",
            submitted_at=datetime.utcnow(),
        )
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def get_by_id(self, approval_id: int) -> Optional[EvoApproval]:
        """按ID获取审批"""
        return self.db.query(EvoApproval).filter(EvoApproval.id == approval_id).first()

    def get_by_plan(self, plan_id: str) -> Optional[EvoApproval]:
        """按计划ID获取审批"""
        return self.db.query(EvoApproval).filter(EvoApproval.plan_id == plan_id).first()

    def decide(self, approval_id: int, status: str,
               approver: str = "", comment: str = "") -> Optional[EvoApproval]:
        """审批决策"""
        approval = self.get_by_id(approval_id)
        if not approval:
            return None
        approval.status = status
        approval.approver = approver
        approval.approval_comment = comment
        approval.decided_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def list(self, page: int = 1, page_size: int = 20,
             status: Optional[str] = None,
             plan_id: Optional[str] = None) -> Tuple[List[EvoApproval], int]:
        """审批列表（分页）"""
        query = self.db.query(EvoApproval)
        if status:
            query = query.filter(EvoApproval.status == status)
        if plan_id:
            query = query.filter(EvoApproval.plan_id == plan_id)
        total = query.count()
        items = (
            query.order_by(desc(EvoApproval.submitted_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total


# ============================================================
# 部署仓库
# ============================================================

class DeploymentRepository:
    """部署数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, plan_id: str, candidate_id: str, version: str = "",
               deployed_by: str = "") -> EvoDeployment:
        """创建部署记录"""
        deployment = EvoDeployment(
            plan_id=plan_id,
            candidate_id=candidate_id,
            status="pending",
            version=version,
            deployed_by=deployed_by,
            started_at=datetime.utcnow(),
        )
        self.db.add(deployment)
        self.db.commit()
        self.db.refresh(deployment)
        return deployment

    def complete(self, deployment_id: int, status: str = "completed",
                 deploy_log: str = "") -> Optional[EvoDeployment]:
        """标记部署完成"""
        deployment = self.db.query(EvoDeployment).filter(EvoDeployment.id == deployment_id).first()
        if not deployment:
            return None
        deployment.status = status
        deployment.deploy_log = deploy_log
        deployment.completed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(deployment)
        return deployment

    def get_by_id(self, deployment_id: int) -> Optional[EvoDeployment]:
        """按ID获取部署记录"""
        return self.db.query(EvoDeployment).filter(EvoDeployment.id == deployment_id).first()

    def list(self, page: int = 1, page_size: int = 20,
             status: Optional[str] = None,
             plan_id: Optional[str] = None) -> Tuple[List[EvoDeployment], int]:
        """部署记录列表（分页）"""
        query = self.db.query(EvoDeployment)
        if status:
            query = query.filter(EvoDeployment.status == status)
        if plan_id:
            query = query.filter(EvoDeployment.plan_id == plan_id)
        total = query.count()
        items = (
            query.order_by(desc(EvoDeployment.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total


# ============================================================
# 版本仓库
# ============================================================

class VersionRepository:
    """版本数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, module_key: str, version_name: str, plan_id: str = "",
               changelog: str = "", parent_version_id: Optional[str] = None,
               status: str = "stable") -> EvoVersion:
        """创建版本记录"""
        latest = self.get_latest_stable(module_key)
        sequence = (latest.evo_sequence + 1) if latest else 1

        version = EvoVersion(
            version_id=_generate_version_id(),
            module_key=module_key,
            version_name=version_name,
            evo_sequence=sequence,
            parent_version_id=parent_version_id,
            changelog=changelog,
            plan_id=plan_id,
            status=status,
            deployed_at=datetime.utcnow() if status == "stable" else None,
        )
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        return version

    def get_by_id(self, version_id: str) -> Optional[EvoVersion]:
        """按业务ID获取版本"""
        version = self.db.query(EvoVersion).filter(EvoVersion.version_id == version_id).first()
        if not version and version_id.isdigit():
            version = self.db.query(EvoVersion).filter(EvoVersion.id == int(version_id)).first()
        return version

    def get_latest_stable(self, module_key: str) -> Optional[EvoVersion]:
        """获取模块最新稳定版本"""
        return (
            self.db.query(EvoVersion)
            .filter(
                EvoVersion.module_key == module_key,
                EvoVersion.status == "stable",
            )
            .order_by(desc(EvoVersion.evo_sequence))
            .first()
        )

    def list_by_module(self, module_key: str, page: int = 1, page_size: int = 20,
                       status: Optional[str] = None) -> Tuple[List[EvoVersion], int]:
        """模块版本列表（分页）"""
        query = self.db.query(EvoVersion).filter(EvoVersion.module_key == module_key)
        if status:
            query = query.filter(EvoVersion.status == status)
        total = query.count()
        items = (
            query.order_by(desc(EvoVersion.evo_sequence))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def rollback(self, version_id: str) -> Optional[EvoVersion]:
        """标记版本为已回滚"""
        version = self.get_by_id(version_id)
        if version:
            version.status = "rolled_back"
            self.db.commit()
            self.db.refresh(version)
        return version


# ============================================================
# 回滚仓库
# ============================================================

class RollbackRepository:
    """回滚记录数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, module_key: str, from_version: str, to_version: str,
               reason: str = "", triggered_by: str = "",
               verification_result: str = "passed") -> EvoRollbackRecord:
        """创建回滚记录"""
        record = EvoRollbackRecord(
            module_key=module_key,
            from_version=from_version,
            to_version=to_version,
            reason=reason,
            triggered_by=triggered_by,
            rollback_time=datetime.utcnow(),
            verification_result=verification_result,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_by_module(self, module_key: str, page: int = 1,
                       page_size: int = 20) -> Tuple[List[EvoRollbackRecord], int]:
        """模块回滚历史（分页）"""
        query = self.db.query(EvoRollbackRecord).filter(EvoRollbackRecord.module_key == module_key)
        total = query.count()
        items = (
            query.order_by(desc(EvoRollbackRecord.rollback_time))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total


# ============================================================
# 审计报告仓库
# ============================================================

class AuditReportRepository:
    """审计报告数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, plan_id: str, audit_type: str = "security",
               code_security: Optional[Dict] = None,
               dependency_security: Optional[Dict] = None,
               permission_check: Optional[Dict] = None,
               data_security: Optional[Dict] = None,
               logic_security: Optional[Dict] = None,
               compliance: Optional[Dict] = None,
               issues: Optional[List] = None,
               risk_level: str = "low",
               score: float = 100.0,
               recommendation: str = "approve",
               auditor: str = "",
               deployment_id: Optional[int] = None,
               sandbox_id: Optional[str] = None,
               findings: Optional[List] = None) -> EvoAuditReport:
        """创建审计报告"""
        report = EvoAuditReport(
            plan_id=plan_id,
            deployment_id=deployment_id,
            sandbox_id=sandbox_id,
            audit_type=audit_type,
            status="completed",
            code_security_result=code_security or {},
            dependency_security_result=dependency_security or {},
            permission_check_result=permission_check or {},
            data_security_result=data_security or {},
            logic_security_result=logic_security or {},
            compliance_result=compliance or {},
            findings=findings or [],
            issues=issues or [],
            risk_level=risk_level,
            score=score,
            recommendation=recommendation,
            auditor=auditor,
            auditor_id=auditor,
            audited_at=datetime.utcnow(),
        )
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def get_by_id(self, report_id: int) -> Optional[EvoAuditReport]:
        """按ID获取审计报告"""
        return self.db.query(EvoAuditReport).filter(EvoAuditReport.id == report_id).first()

    def get_latest_by_plan(self, plan_id: str) -> Optional[EvoAuditReport]:
        """获取计划最新的审计报告"""
        return (
            self.db.query(EvoAuditReport)
            .filter(EvoAuditReport.plan_id == plan_id)
            .order_by(desc(EvoAuditReport.created_at))
            .first()
        )

    def update_recommendation(self, report_id: int, recommendation: str,
                              auditor: str = "") -> Optional[EvoAuditReport]:
        """更新审计建议"""
        report = self.get_by_id(report_id)
        if not report:
            return None
        report.recommendation = recommendation
        report.auditor = auditor
        report.auditor_id = auditor
        report.audited_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(report)
        return report

    def list(self, page: int = 1, page_size: int = 20,
             plan_id: Optional[str] = None,
             risk_level: Optional[str] = None,
             recommendation: Optional[str] = None) -> Tuple[List[EvoAuditReport], int]:
        """审计报告列表（分页）"""
        query = self.db.query(EvoAuditReport)
        if plan_id:
            query = query.filter(EvoAuditReport.plan_id == plan_id)
        if risk_level:
            query = query.filter(EvoAuditReport.risk_level == risk_level)
        if recommendation:
            query = query.filter(EvoAuditReport.recommendation == recommendation)
        total = query.count()
        items = (
            query.order_by(desc(EvoAuditReport.audited_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def count(self) -> int:
        """总报告数"""
        return self.db.query(EvoAuditReport).count()


# ============================================================
# 总入口
# ============================================================

class EvolutionRepository:
    """进化系统统一数据仓库入口"""

    def __init__(self, db: Session):
        self.db = db
        self.scans = ScanRepository(db)
        self.plans = PlanRepository(db)
        self.candidates = CandidateRepository(db)
        self.approvals = ApprovalRepository(db)
        self.deployments = DeploymentRepository(db)
        self.versions = VersionRepository(db)
        self.rollbacks = RollbackRepository(db)
        self.audits = AuditReportRepository(db)

    def ensure_seed_data(self, username: str = "system") -> bool:
        """确保示例数据存在（幂等操作）

        当数据库中没有进化系统数据时，初始化一些示例数据，
        方便首次访问时能看到内容。
        """
        if self.plans.count() > 0:
            return False

        # 1. 创建一条示例扫描记录
        scan = self.scans.create(
            scan_type="health",
            status="completed",
            overall_score=72.5,
            module_scores={
                "m8-core": {
                    "name": "核心引擎",
                    "total_score": 85.3,
                    "cpu_score": 80.0,
                    "mem_score": 75.0,
                    "status_score": 100,
                    "latency_score": 90.0,
                },
                "m8-vision": {
                    "name": "视觉模块",
                    "total_score": 65.0,
                    "cpu_score": 55.0,
                    "mem_score": 60.0,
                    "status_score": 100,
                    "latency_score": 45.0,
                },
            },
            anomalies=[
                {
                    "module_key": "m8-vision",
                    "module_name": "视觉模块",
                    "severity": "medium",
                    "score": 65.0,
                    "reason": "健康评分偏低，有优化空间",
                },
            ],
            recommendations=[
                {
                    "type": "perf_optimization",
                    "module_key": "m8-vision",
                    "title": "优化视觉模块性能",
                    "description": "该模块健康评分偏低，建议进行性能优化和健康检查。",
                    "priority": "medium",
                },
            ],
            user_id=1,
        )
        self.scans.complete(
            scan_id=scan.id,
            overall_score=72.5,
            module_scores=scan.module_scores,
            anomalies=scan.anomalies,
            recommendations=scan.recommendations,
            files_scanned=156,
            issues_found=3,
        )

        # 2. 创建示例进化计划
        plan = self.plans.create(
            title="视觉模块性能优化",
            description="针对视觉模块响应时间偏长的问题，进行性能优化，提升用户体验。",
            plan_type="perf_optimization",
            module_key="m8-vision",
            priority="high",
            risk_level="medium",
            expected_effect="典型查询响应时间降低 40-60%，数据库负载下降 30%。",
            created_by=username,
            scan_id=scan.id,
        )

        # 3. 创建示例候选方案
        self.candidates.batch_create([
            {
                "plan_id": plan.plan_id,
                "name": "数据库查询优化方案",
                "approach": "分析视觉模块的慢查询，添加必要索引、优化 SQL 语句、引入缓存机制。",
                "expected_effect": "典型查询响应时间降低 40-60%，数据库负载下降 30%。",
                "risk_assessment": "中低风险，需确保功能正确性。",
                "cost_estimate": "中（约 8-12 小时）",
                "estimated_effort": "8-12小时",
                "risk_level": "medium",
            },
            {
                "plan_id": plan.plan_id,
                "name": "缓存策略优化方案",
                "approach": "为视觉模块设计多级缓存策略，热点数据内存缓存 + 二级缓存。",
                "expected_effect": "高频接口响应提升 2-5 倍，后端压力显著降低。",
                "risk_assessment": "中风险，需处理缓存一致性问题。",
                "cost_estimate": "中高（约 12-18 小时）",
                "estimated_effort": "12-18小时",
                "risk_level": "medium",
            },
            {
                "plan_id": plan.plan_id,
                "name": "异步化改造方案",
                "approach": "将视觉模块中的耗时同步操作改为异步处理，引入消息队列。",
                "expected_effect": "接口响应时间大幅缩短，系统吞吐量提升 2-3 倍。",
                "risk_assessment": "中高风险，架构改动较大。",
                "cost_estimate": "高（约 20-30 小时）",
                "estimated_effort": "20-30小时",
                "risk_level": "high",
            },
        ])

        # 4. 创建第二个示例计划（已完成的）
        plan2 = self.plans.create(
            title="API 文档补全",
            description="为核心引擎模块的所有公开接口补充详细的 API 文档。",
            plan_type="doc_improvement",
            module_key="m8-core",
            priority="medium",
            risk_level="low",
            expected_effect="接口文档覆盖率从当前水平提升至 95% 以上。",
            created_by=username,
        )
        self.plans.update_status(plan2.plan_id, "completed")

        # 5. 创建示例版本记录
        self.versions.create(
            module_key="m8-core",
            version_name="evo-doc_improvement-001",
            plan_id=plan2.plan_id,
            changelog="API 文档补全，新增 23 个接口文档。",
            status="stable",
        )

        # 6. 创建示例审计报告
        self.audits.create(
            plan_id=plan2.plan_id,
            audit_type="security",
            code_security={"score": 95, "status": "passed", "findings": []},
            dependency_security={"score": 90, "status": "passed", "vulnerable_count": 1},
            permission_check="passed",
            data_security="passed",
            logic_security="passed",
            compliance="passed",
            issues=[],
            risk_level="low",
            score=92.5,
            recommendation="approve",
            auditor="system",
            findings=[],
        )

        return True
