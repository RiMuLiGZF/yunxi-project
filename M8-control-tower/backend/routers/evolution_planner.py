"""
自进化引擎 - 进化规划器路由
- 健康扫描与评分
- 进化计划管理
- 候选方案生成与选择

数据库持久化 + 模拟逻辑 fallback（真正的代码扫描需要 AI 能力）
所有操作需要认证
首次访问自动初始化示例数据
"""

import sys
import uuid
import random
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.module_client import get_module_registry, ModuleStatus
from ..schemas import ApiResponse
from ..auth import get_current_user
from ..models import get_db
from ..repositories.evolution_repository import EvolutionRepository

router = APIRouter()
registry = get_module_registry()


# ============================================================
# 请求体模型
# ============================================================

class PlanCreateRequest(BaseModel):
    """创建进化计划请求体"""
    title: str = Field(..., description="计划标题")
    description: str = Field("", description="计划描述")
    type: str = Field("doc_improvement", description="类型：doc_improvement/test_enhancement/bug_fix/perf_optimization")
    module_key: str = Field(..., description="目标模块")
    priority: str = Field("medium", description="优先级：low/medium/high/critical")
    risk_level: str = Field("low", description="风险等级：low/medium/high/critical")
    expected_effect: str = Field("", description="预期效果")


class CandidateSelectRequest(BaseModel):
    """选择候选方案请求体"""
    candidate_id: str = Field(..., description="候选方案ID")


# ============================================================
# 工具函数
# ============================================================

def _get_repo(db: Session) -> EvolutionRepository:
    """获取进化系统仓库，并确保示例数据初始化"""
    repo = EvolutionRepository(db)
    # 首次访问自动初始化示例数据
    try:
        repo.ensure_seed_data(username="system")
    except Exception as e:
        # 初始化失败不影响正常使用
        print(f"[Evolution] 示例数据初始化跳过: {e}")
    return repo


def _calculate_module_health_score(module_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    计算单个模块的健康评分（简化版算法）
    - CPU 使用率（25%）：越低分越高
    - 内存使用率（25%）：越低分越高
    - 健康状态（30%）：online=100, warning=60, error=0
    - 响应时间（20%）：越快分越高

    注意：CPU 和内存数据为模拟（MVP 阶段），实际场景需从监控接口获取
    """
    # MVP：模拟 CPU 和内存数据（实际场景可从监控接口获取）
    cpu_usage = random.uniform(15, 75)
    mem_usage = random.uniform(30, 80)

    # CPU 评分（25%权重）：0%->100分，100%->0分
    cpu_score = max(0, min(100, (100 - cpu_usage) * 1))

    # 内存评分（25%权重）
    mem_score = max(0, min(100, (100 - mem_usage) * 1))

    # 状态评分（30%权重）
    status = module_info.get("status", "unknown")
    if status == ModuleStatus.RUNNING.value or status == "online":
        status_score = 100
    elif status == ModuleStatus.ERROR.value or status == "error":
        status_score = 0
    else:
        status_score = 60  # stopped/unknown/warning

    # 响应时间评分（20%权重）
    latency_ms = module_info.get("latency_ms", 0) or 0
    # 0ms->100分，500ms->0分
    latency_score = max(0, min(100, (500 - latency_ms) / 5))

    # 加权总分
    total_score = round(
        cpu_score * 0.25 +
        mem_score * 0.25 +
        status_score * 0.30 +
        latency_score * 0.20,
        2
    )

    return {
        "total_score": total_score,
        "cpu_score": round(cpu_score, 2),
        "cpu_usage": round(cpu_usage, 1),
        "mem_score": round(mem_score, 2),
        "mem_usage": round(mem_usage, 1),
        "status_score": status_score,
        "status": status,
        "latency_score": round(latency_score, 2),
        "latency_ms": latency_ms,
    }


def _scan_to_dict(scan) -> Dict[str, Any]:
    """扫描记录转字典"""
    return {
        "id": scan.id,
        "scan_time": scan.scan_time.strftime("%Y-%m-%d %H:%M:%S") if scan.scan_time else "",
        "overall_score": scan.overall_score,
        "module_scores": scan.module_scores or {},
        "anomalies": scan.anomalies or [],
        "recommendations": scan.recommendations or [],
        "status": scan.status,
        "scan_type": scan.scan_type,
        "files_scanned": scan.files_scanned,
        "issues_found": scan.issues_found,
        "started_at": scan.started_at.strftime("%Y-%m-%d %H:%M:%S") if scan.started_at else "",
        "completed_at": scan.completed_at.strftime("%Y-%m-%d %H:%M:%S") if scan.completed_at else "",
        "created_at": scan.created_at.strftime("%Y-%m-%d %H:%M:%S") if scan.created_at else "",
    }


def _plan_to_dict(plan) -> Dict[str, Any]:
    """计划转字典"""
    return {
        "id": plan.id,
        "plan_id": plan.plan_id,
        "title": plan.title,
        "description": plan.description,
        "type": plan.type,
        "module_key": plan.module_key,
        "status": plan.status,
        "priority": plan.priority,
        "risk_level": plan.risk_level,
        "expected_effect": plan.expected_effect,
        "created_by": plan.created_by,
        "scan_id": plan.scan_id,
        "created_at": plan.created_at.strftime("%Y-%m-%d %H:%M:%S") if plan.created_at else "",
        "updated_at": plan.updated_at.strftime("%Y-%m-%d %H:%M:%S") if plan.updated_at else "",
    }


def _candidate_to_dict(candidate) -> Dict[str, Any]:
    """候选方案转字典"""
    return {
        "id": candidate.id,
        "plan_id": candidate.plan_id,
        "candidate_id": candidate.candidate_id,
        "name": candidate.name,
        "title": candidate.title or candidate.name,
        "approach": candidate.approach,
        "description": candidate.description,
        "expected_effect": candidate.expected_effect,
        "risk_assessment": candidate.risk_assessment,
        "cost_estimate": candidate.cost_estimate,
        "estimated_effort": candidate.estimated_effort,
        "risk_level": candidate.risk_level,
        "vote_count": candidate.vote_count,
        "is_selected": candidate.is_selected,
        "status": candidate.status,
        "created_at": candidate.created_at.strftime("%Y-%m-%d %H:%M:%S") if candidate.created_at else "",
    }


def _generate_candidates_by_type(plan_id: str, plan_type: str, module_key: str) -> List[Dict[str, Any]]:
    """
    根据计划类型生成候选方案（MVP：模板化生成 2-3 个方案）
    模拟 AI 生成候选方案的能力
    """
    candidates = []

    if plan_type == "doc_improvement":
        candidates.append({
            "plan_id": plan_id,
            "name": "API 文档补全方案",
            "approach": f"为 {module_key} 模块的所有公开接口补充详细的 API 文档，包括请求参数、响应格式、错误码说明和使用示例。",
            "expected_effect": "接口文档覆盖率从当前水平提升至 95% 以上，降低新成员上手成本约 40%。",
            "risk_assessment": "风险极低，仅修改文档文件，不涉及业务代码。",
            "cost_estimate": "低（约 4-6 小时）",
            "estimated_effort": "4-6小时",
            "risk_level": "low",
        })
        candidates.append({
            "plan_id": plan_id,
            "name": "架构设计文档完善",
            "approach": f"补充 {module_key} 模块的架构设计文档，包括模块分层、核心数据流、关键设计决策记录和扩展点说明。",
            "expected_effect": "提升团队对系统架构的理解深度，减少架构腐化风险。",
            "risk_assessment": "风险极低，纯文档工作。",
            "cost_estimate": "中（约 8-12 小时）",
            "estimated_effort": "8-12小时",
            "risk_level": "low",
        })
        candidates.append({
            "plan_id": plan_id,
            "name": "README 与使用指南优化",
            "approach": f"完善 {module_key} 模块的 README 文档，补充快速开始指南、常见问题 FAQ 和配置项说明。",
            "expected_effect": "新用户首次部署成功率提升 60%，减少重复咨询。",
            "risk_assessment": "风险极低。",
            "cost_estimate": "低（约 2-4 小时）",
            "estimated_effort": "2-4小时",
            "risk_level": "low",
        })

    elif plan_type == "test_enhancement":
        candidates.append({
            "plan_id": plan_id,
            "name": "单元测试覆盖提升",
            "approach": f"为 {module_key} 模块的核心业务逻辑补充单元测试，目标覆盖率达到 80%。",
            "expected_effect": "核心代码单元测试覆盖率提升至 80%，回归缺陷率降低约 30%。",
            "risk_assessment": "低风险，仅新增测试代码，不修改业务逻辑。",
            "cost_estimate": "中（约 10-15 小时）",
            "estimated_effort": "10-15小时",
            "risk_level": "low",
        })
        candidates.append({
            "plan_id": plan_id,
            "name": "集成测试套件搭建",
            "approach": f"搭建 {module_key} 模块的集成测试框架，覆盖主要业务流程的端到端测试。",
            "expected_effect": "关键业务流程自动化覆盖，发布前回归测试时间缩短 50%。",
            "risk_assessment": "低风险。",
            "cost_estimate": "中高（约 16-24 小时）",
            "estimated_effort": "16-24小时",
            "risk_level": "low",
        })
        candidates.append({
            "plan_id": plan_id,
            "name": "边界条件与异常测试",
            "approach": f"针对 {module_key} 模块的异常场景和边界条件补充专项测试用例。",
            "expected_effect": "异常场景覆盖率提升，线上故障率降低约 25%。",
            "risk_assessment": "低风险。",
            "cost_estimate": "中（约 6-10 小时）",
            "estimated_effort": "6-10小时",
            "risk_level": "low",
        })

    elif plan_type == "bug_fix":
        candidates.append({
            "plan_id": plan_id,
            "name": "快速修复方案",
            "approach": f"定位 {module_key} 模块的问题根因，采用最小改动原则进行修复，补充回归测试。",
            "expected_effect": "问题快速解决，对系统影响最小化。",
            "risk_assessment": "中低风险，需确保修复不引入新问题。",
            "cost_estimate": "低（约 2-6 小时）",
            "estimated_effort": "2-6小时",
            "risk_level": "medium",
        })
        candidates.append({
            "plan_id": plan_id,
            "name": "根治重构方案",
            "approach": f"深入分析 {module_key} 模块的问题根源，对相关代码进行重构优化，从根本上解决问题。",
            "expected_effect": "彻底解决问题，提升代码质量，但改动范围较大。",
            "risk_assessment": "中风险，重构可能引入新问题。",
            "cost_estimate": "高（约 16-32 小时）",
            "estimated_effort": "16-32小时",
            "risk_level": "high",
        })

    elif plan_type == "perf_optimization":
        candidates.append({
            "plan_id": plan_id,
            "name": "数据库查询优化",
            "approach": f"分析 {module_key} 模块的慢查询，添加必要索引、优化 SQL 语句、引入缓存机制。",
            "expected_effect": "典型查询响应时间降低 40-60%，数据库负载下降 30%。",
            "risk_assessment": "中低风险，需确保功能正确性。",
            "cost_estimate": "中（约 8-12 小时）",
            "estimated_effort": "8-12小时",
            "risk_level": "medium",
        })
        candidates.append({
            "plan_id": plan_id,
            "name": "缓存策略优化",
            "approach": f"为 {module_key} 模块设计多级缓存策略，热点数据内存缓存 + 二级缓存。",
            "expected_effect": "高频接口响应提升 2-5 倍，后端压力显著降低。",
            "risk_assessment": "中风险，需处理缓存一致性问题。",
            "cost_estimate": "中高（约 12-18 小时）",
            "estimated_effort": "12-18小时",
            "risk_level": "medium",
        })
        candidates.append({
            "plan_id": plan_id,
            "name": "异步化改造",
            "approach": f"将 {module_key} 模块中的耗时同步操作改为异步处理，引入消息队列。",
            "expected_effect": "接口响应时间大幅缩短，系统吞吐量提升 2-3 倍。",
            "risk_assessment": "中高风险，架构改动较大。",
            "cost_estimate": "高（约 20-30 小时）",
            "estimated_effort": "20-30小时",
            "risk_level": "high",
        })

    return candidates


# ============================================================
# 健康扫描接口
# ============================================================

@router.post("/scan")
async def trigger_health_scan(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """触发健康扫描
    - 从监控中心获取所有模块健康状态
    - 计算健康评分（0-100）（MVP：CPU/内存为模拟数据）
    - 识别异常模块
    - 生成优化建议
    - 保存扫描记录到数据库
    """
    repo = _get_repo(db)

    # 获取所有模块信息
    modules = registry.get_all_modules()

    # 计算各模块健康评分
    module_scores = {}
    anomalies = []
    recommendations = []

    for module in modules:
        module_dict = module.to_dict()
        score_result = _calculate_module_health_score(module_dict)
        module_scores[module.key] = {
            "name": module.name,
            **score_result,
        }

        # 识别异常
        total_score = score_result["total_score"]
        if total_score < 60:
            anomalies.append({
                "module_key": module.key,
                "module_name": module.name,
                "severity": "high",
                "score": total_score,
                "reason": f"整体健康评分过低（{total_score}分），需要关注",
            })
            recommendations.append({
                "type": "perf_optimization",
                "module_key": module.key,
                "title": f"优化 {module.name} 模块性能",
                "description": f"该模块健康评分仅 {total_score} 分，建议进行性能优化和健康检查。",
                "priority": "high" if total_score < 40 else "medium",
            })
        elif total_score < 80:
            anomalies.append({
                "module_key": module.key,
                "module_name": module.name,
                "severity": "medium",
                "score": total_score,
                "reason": f"健康评分偏低（{total_score}分），有优化空间",
            })

        # 状态异常
        status = score_result["status"]
        if status in [ModuleStatus.ERROR.value, "error"]:
            anomalies.append({
                "module_key": module.key,
                "module_name": module.name,
                "severity": "critical",
                "score": 0,
                "reason": "模块处于错误状态，服务不可用",
            })
            recommendations.append({
                "type": "bug_fix",
                "module_key": module.key,
                "title": f"修复 {module.name} 模块故障",
                "description": "模块当前处于错误状态，需要紧急排查和修复。",
                "priority": "critical",
            })

        # 响应时间异常
        if score_result["latency_ms"] > 300:
            anomalies.append({
                "module_key": module.key,
                "module_name": module.name,
                "severity": "medium",
                "score": score_result["latency_score"],
                "reason": f"响应时间偏高（{score_result['latency_ms']}ms）",
            })

    # 计算整体评分
    if module_scores:
        overall_score = round(
            sum(m["total_score"] for m in module_scores.values()) / len(module_scores),
            2
        )
    else:
        overall_score = 0.0

    # 全局建议
    if overall_score < 70:
        recommendations.append({
            "type": "doc_improvement",
            "module_key": "all",
            "title": "全面文档审查与完善",
            "description": "系统整体健康度偏低，建议先完善各模块文档，降低维护风险。",
            "priority": "medium",
        })
        recommendations.append({
            "type": "test_enhancement",
            "module_key": "all",
            "title": "测试体系建设",
            "description": "建议加强测试覆盖，建立完善的质量保障体系。",
            "priority": "medium",
        })

    # 保存扫描记录到数据库
    user_id = current_user.get("user_id", 1) if isinstance(current_user, dict) else 1
    scan = repo.scans.create(
        scan_type="health",
        status="running",
        overall_score=overall_score,
        module_scores=module_scores,
        anomalies=anomalies,
        recommendations=recommendations,
        user_id=user_id,
    )

    # 标记扫描完成
    completed_scan = repo.scans.complete(
        scan_id=scan.id,
        overall_score=overall_score,
        module_scores=module_scores,
        anomalies=anomalies,
        recommendations=recommendations,
        files_scanned=len(modules) * 10,  # 模拟文件数
        issues_found=len(anomalies),
    )

    return ApiResponse.success(
        data=_scan_to_dict(completed_scan),
        message="健康扫描完成（MVP：CPU/内存数据为模拟）"
    )


@router.get("/scans")
async def get_scan_list(
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """扫描历史列表"""
    repo = _get_repo(db)
    scans, total = repo.scans.list(page=page, page_size=page_size)

    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_scan_to_dict(s) for s in scans],
    })


@router.get("/scans/{scan_id}")
async def get_scan_detail(
    scan_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """扫描详情"""
    repo = _get_repo(db)
    scan = repo.scans.get_by_id(scan_id)
    if not scan:
        return ApiResponse.error(code=404, message="扫描记录不存在")

    return ApiResponse.success(data=_scan_to_dict(scan))


# ============================================================
# 进化计划接口
# ============================================================

@router.get("/plans")
async def get_plan_list(
    status: Optional[str] = Query(None, description="状态筛选"),
    module_key: Optional[str] = Query(None, description="模块筛选"),
    plan_type: Optional[str] = Query(None, description="类型筛选"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """进化计划列表"""
    repo = _get_repo(db)
    plans, total = repo.plans.list(
        page=page,
        page_size=page_size,
        status=status,
        module_key=module_key,
        plan_type=plan_type,
    )

    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_plan_to_dict(p) for p in plans],
    })


@router.post("/plans")
async def create_plan(
    request: PlanCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建进化计划（手动创建）"""
    valid_types = ["doc_improvement", "test_enhancement", "bug_fix", "perf_optimization"]
    if request.type not in valid_types:
        return ApiResponse.error(
            code=400,
            message=f"无效的计划类型，必须是: {', '.join(valid_types)}"
        )

    repo = _get_repo(db)
    username = current_user.get("username", "unknown") if isinstance(current_user, dict) else "unknown"

    plan = repo.plans.create(
        title=request.title,
        description=request.description,
        plan_type=request.type,
        module_key=request.module_key,
        priority=request.priority,
        risk_level=request.risk_level,
        expected_effect=request.expected_effect,
        created_by=username,
    )

    return ApiResponse.success(
        data=_plan_to_dict(plan),
        message="进化计划创建成功"
    )


@router.get("/plans/{plan_id}")
async def get_plan_detail(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """计划详情"""
    repo = _get_repo(db)
    plan = repo.plans.get_by_id(plan_id)
    if not plan:
        return ApiResponse.error(code=404, message="进化计划不存在")

    candidate_count = repo.candidates.count_by_plan(plan.plan_id)

    result = _plan_to_dict(plan)
    result["candidate_count"] = candidate_count

    return ApiResponse.success(data=result)


@router.post("/plans/{plan_id}/generate")
async def generate_candidates(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """生成候选方案
    MVP：根据计划类型模板化生成 2-3 个候选方案（模拟 AI 生成能力）
    实际场景需要 AI 模型根据计划内容智能生成方案
    """
    repo = _get_repo(db)
    plan = repo.plans.get_by_id(plan_id)
    if not plan:
        return ApiResponse.error(code=404, message="进化计划不存在")

    existing = repo.candidates.count_by_plan(plan.plan_id)
    if existing > 0:
        return ApiResponse.error(
            code=400,
            message="该计划已存在候选方案，如需重新生成请先删除现有方案"
        )

    # 生成候选方案（MVP：模板化生成，模拟 AI 能力）
    candidate_data_list = _generate_candidates_by_type(
        plan_id=plan.plan_id,
        plan_type=plan.type,
        module_key=plan.module_key,
    )

    saved_candidates = repo.candidates.batch_create(candidate_data_list)

    # 更新计划状态
    repo.plans.update_status(plan.plan_id, "draft")

    return ApiResponse.success(
        data={
            "plan_id": plan.plan_id,
            "count": len(saved_candidates),
            "candidates": [_candidate_to_dict(c) for c in saved_candidates],
        },
        message=f"已生成 {len(saved_candidates)} 个候选方案（MVP：模板化生成）"
    )


@router.get("/plans/{plan_id}/candidates")
async def get_plan_candidates(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """候选方案列表"""
    repo = _get_repo(db)
    plan = repo.plans.get_by_id(plan_id)
    if not plan:
        return ApiResponse.error(code=404, message="进化计划不存在")

    candidates = repo.candidates.list_by_plan(plan.plan_id)

    return ApiResponse.success(data={
        "plan_id": plan.plan_id,
        "total": len(candidates),
        "items": [_candidate_to_dict(c) for c in candidates],
    })


@router.post("/plans/{plan_id}/select")
async def select_candidate(
    plan_id: str,
    request: CandidateSelectRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """选择方案进入下一步"""
    repo = _get_repo(db)
    plan = repo.plans.get_by_id(plan_id)
    if not plan:
        return ApiResponse.error(code=404, message="进化计划不存在")

    candidate = repo.candidates.get_by_id(request.candidate_id)
    if not candidate or candidate.plan_id != plan.plan_id:
        return ApiResponse.error(code=404, message="候选方案不存在")

    # 选中方案
    selected = repo.candidates.select(plan.plan_id, request.candidate_id)

    # 更新计划状态
    updated_plan = repo.plans.update_status(plan.plan_id, "selected")

    return ApiResponse.success(
        data={
            "plan": _plan_to_dict(updated_plan),
            "selected_candidate": _candidate_to_dict(selected),
        },
        message="方案已选定，进入下一阶段"
    )


@router.post("/plans/{plan_id}/candidates/{candidate_id}/vote")
async def vote_candidate(
    plan_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """为候选方案投票"""
    repo = _get_repo(db)
    plan = repo.plans.get_by_id(plan_id)
    if not plan:
        return ApiResponse.error(code=404, message="进化计划不存在")

    candidate = repo.candidates.get_by_id(candidate_id)
    if not candidate or candidate.plan_id != plan.plan_id:
        return ApiResponse.error(code=404, message="候选方案不存在")

    voted = repo.candidates.vote(candidate_id)

    return ApiResponse.success(
        data=_candidate_to_dict(voted),
        message="投票成功"
    )
