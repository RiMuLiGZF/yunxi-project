"""
M8 管理工作台 - 自进化引擎模型

包含 EvoHealthScan, EvoPlan, EvoCandidate, EvoApproval, EvoVersion,
EvoRollbackRecord, EvoDeployment, EvoAuditReport。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class EvoHealthScan(Base):
    """自进化引擎 - 健康扫描记录表"""
    __tablename__ = "evolution_scans"

    id = Column(Integer, primary_key=True, index=True)
    scan_type = Column(String(50), default="health", index=True, comment="扫描类型：health/code_security/dependency/full")
    status = Column(String(20), default="pending", index=True, comment="状态：pending/running/completed/failed")
    files_scanned = Column(Integer, default=0, comment="扫描文件数")
    issues_found = Column(Integer, default=0, comment="发现问题数")
    overall_score = Column(Float, default=0.0, comment="整体健康评分 0-100")
    module_scores = Column(JSON, default=dict, comment="各模块评分详情 (JSON)")
    anomalies = Column(JSON, default=list, comment="异常项列表 (JSON)")
    recommendations = Column(JSON, default=list, comment="优化建议列表 (JSON)")
    result_json = Column(JSON, default=dict, comment="完整扫描结果 (JSON)")
    scan_time = Column(DateTime, nullable=True, comment="扫描完成时间")
    started_at = Column(DateTime, nullable=True, comment="扫描开始时间")
    completed_at = Column(DateTime, nullable=True, comment="扫描完成时间")
    user_id = Column(Integer, default=1, index=True, comment="触发用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class EvoPlan(Base):
    """自进化引擎 - 进化计划表"""
    __tablename__ = "evolution_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), unique=True, index=True, comment="计划业务ID")
    title = Column(String(255), comment="计划标题")
    description = Column(Text, default="", comment="计划描述")
    type = Column(String(50), default="doc_improvement", index=True, comment="类型：doc_improvement/test_enhancement/bug_fix/perf_optimization")
    module_key = Column(String(50), index=True, comment="目标模块")
    status = Column(String(30), default="draft", index=True, comment="状态：draft/selected/auditing/approved/deploying/completed/failed")
    priority = Column(String(20), default="medium", comment="优先级：low/medium/high/critical")
    risk_level = Column(String(20), default="low", comment="风险等级：low/medium/high/critical")
    expected_effect = Column(Text, default="", comment="预期效果")
    plan_json = Column(JSON, default=dict, comment="计划详细配置 (JSON)")
    scan_id = Column(Integer, nullable=True, index=True, comment="关联扫描记录ID")
    created_by = Column(String(100), default="", comment="创建人")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")


class EvoCandidate(Base):
    """自进化引擎 - 候选方案表"""
    __tablename__ = "evolution_candidates"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), index=True, comment="关联计划ID")
    candidate_id = Column(String(64), unique=True, index=True, comment="候选方案业务ID")
    name = Column(String(255), comment="方案名称")
    title = Column(String(255), comment="方案标题（兼容字段）")
    approach = Column(Text, default="", comment="方案思路/方法")
    description = Column(Text, default="", comment="方案描述")
    expected_effect = Column(Text, default="", comment="预期效果")
    risk_assessment = Column(Text, default="", comment="风险评估")
    cost_estimate = Column(String(100), default="", comment="成本估算")
    estimated_effort = Column(String(100), default="", comment="预估工作量")
    risk_level = Column(String(20), default="low", comment="风险等级：low/medium/high/critical")
    vote_count = Column(Integer, default=0, comment="投票数")
    candidate_json = Column(JSON, default=dict, comment="候选方案完整数据 (JSON)")
    is_selected = Column(Boolean, default=False, index=True, comment="是否被选中")
    status = Column(String(20), default="pending", index=True, comment="状态：pending/selected/rejected")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class EvoApproval(Base):
    """自进化引擎 - 审批记录表"""
    __tablename__ = "evolution_approvals"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), index=True, comment="关联计划ID")
    audit_report_id = Column(Integer, nullable=True, index=True, comment="关联审计报告ID")
    submitter = Column(String(100), default="", comment="提交人")
    status = Column(String(20), default="pending", index=True, comment="状态：pending/approved/rejected/modified")
    approver = Column(String(100), default="", comment="审批人")
    approval_comment = Column(Text, default="", comment="审批意见")
    submitted_at = Column(DateTime, nullable=True, comment="提交时间")
    decided_at = Column(DateTime, nullable=True, comment="审批时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class EvoVersion(Base):
    """自进化引擎 - 进化版本记录表"""
    __tablename__ = "evolution_versions"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(String(64), unique=True, index=True, comment="版本业务ID")
    module_key = Column(String(50), index=True, comment="所属模块")
    version_name = Column(String(100), comment="版本名称")
    evo_sequence = Column(Integer, default=1, index=True, comment="进化序号")
    parent_version_id = Column(String(64), nullable=True, comment="父版本ID")
    changelog = Column(Text, default="", comment="变更日志")
    plan_id = Column(String(64), index=True, comment="关联计划ID")
    status = Column(String(20), default="stable", index=True, comment="状态：stable/failed/rolled_back/deploying")
    deployed_at = Column(DateTime, nullable=True, comment="部署时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class EvoRollbackRecord(Base):
    """自进化引擎 - 回滚记录表"""
    __tablename__ = "evolution_rollbacks"

    id = Column(Integer, primary_key=True, index=True)
    module_key = Column(String(50), index=True, comment="模块")
    from_version = Column(String(64), comment="回滚前版本")
    to_version = Column(String(64), comment="回滚后版本")
    reason = Column(Text, default="", comment="回滚原因")
    triggered_by = Column(String(100), default="", comment="触发人")
    rollback_time = Column(DateTime, default=datetime.utcnow, comment="回滚时间")
    verification_result = Column(String(50), default="", comment="验证结果")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class EvoDeployment(Base):
    """自进化引擎 - 部署记录表"""
    __tablename__ = "evolution_deployments"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), index=True, comment="关联计划ID")
    candidate_id = Column(String(64), index=True, comment="关联候选方案ID")
    version_id = Column(String(64), index=True, comment="版本ID")
    status = Column(String(30), default="pending", index=True, comment="状态：pending/running/completed/failed/rolled_back")
    version = Column(String(100), comment="版本号")
    deploy_log = Column(Text, default="", comment="部署日志")
    deployed_by = Column(String(100), default="", comment="部署人")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class EvoAuditReport(Base):
    """自进化引擎 - 安全审计报告表"""
    __tablename__ = "evolution_audits"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), index=True, comment="关联计划ID")
    deployment_id = Column(Integer, nullable=True, index=True, comment="关联部署记录ID")
    sandbox_id = Column(String(64), nullable=True, comment="沙箱ID")
    audit_type = Column(String(50), default="security", index=True, comment="审计类型：security/code_review/compliance/full")
    status = Column(String(20), default="pending", index=True, comment="状态：pending/running/completed/failed")
    code_security_result = Column(JSON, default=dict, comment="代码安全检查结果")
    dependency_security_result = Column(JSON, default=dict, comment="依赖安全检查结果")
    permission_check_result = Column(JSON, default=dict, comment="权限检查结果")
    data_security_result = Column(JSON, default=dict, comment="数据安全检查结果")
    logic_security_result = Column(JSON, default=dict, comment="逻辑安全检查结果")
    compliance_result = Column(JSON, default=dict, comment="合规性检查结果")
    findings = Column(JSON, default=list, comment="审计发现列表")
    issues = Column(JSON, default=list, comment="问题列表")
    risk_level = Column(String(20), default="low", index=True, comment="风险等级：low/medium/high/critical")
    score = Column(Float, default=100.0, comment="安全评分 0-100")
    recommendation = Column(String(50), default="approve", comment="建议：approve/reject/modify")
    auditor = Column(String(100), default="", comment="审计人")
    auditor_id = Column(String(100), default="", comment="审计人ID（兼容字段）")
    reviewed_by = Column(String(100), default="", comment="复核人")
    reviewed_at = Column(DateTime, nullable=True, comment="复核时间")
    audited_at = Column(DateTime, nullable=True, comment="审计时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
