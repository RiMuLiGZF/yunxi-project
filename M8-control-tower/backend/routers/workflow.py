"""
M7 积木平台 - 工作流管理路由

工作流 = 技能调用编排
积木块 = 技能（M2 Skills Cluster 中的技能）
运行/调试 = 按顺序调用技能
"""

import sys
import json
import uuid
import time
import copy
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.module_client import get_module_registry
from ..schemas import ApiResponse
from ..auth import get_current_user

router = APIRouter()
registry = get_module_registry()

# ---- 数据存储路径 ----
_data_dir = Path.home() / ".yunxi"
_workflows_file = _data_dir / "workflows.json"
_runs_file = _data_dir / "workflow_runs.json"


def _ensure_data_dir():
    """确保数据目录存在"""
    _data_dir.mkdir(parents=True, exist_ok=True)


def _load_workflows() -> Dict[str, Dict[str, Any]]:
    """加载工作流数据"""
    _ensure_data_dir()
    if _workflows_file.exists():
        try:
            with open(_workflows_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_workflows(data: Dict[str, Dict[str, Any]]):
    """保存工作流数据"""
    _ensure_data_dir()
    with open(_workflows_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_runs() -> Dict[str, List[Dict[str, Any]]]:
    """加载运行历史"""
    _ensure_data_dir()
    if _runs_file.exists():
        try:
            with open(_runs_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_runs(data: Dict[str, List[Dict[str, Any]]]):
    """保存运行历史"""
    _ensure_data_dir()
    with open(_runs_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- 内置模板数据 ----
TEMPLATES = [
    {
        "id": "tpl_news_daily",
        "name": "每日资讯日报",
        "description": "抓取每日科技资讯，翻译并生成日报，最后存入记忆",
        "category": "信息处理",
        "icon": "📰",
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.web_fetch",
                "name": "网页抓取",
                "config": {"url": "", "action": "fetch"},
                "position": {"x": 50, "y": 50},
                "next": ["block_2"]
            },
            {
                "id": "block_2",
                "type": "skill.translate",
                "name": "内容翻译",
                "config": {"target_lang": "zh-CN", "action": "translate"},
                "position": {"x": 300, "y": 50},
                "next": ["block_3"]
            },
            {
                "id": "block_3",
                "type": "skill.tide_memory",
                "name": "存入记忆",
                "config": {"action": "store", "domain": "daily_news"},
                "position": {"x": 550, "y": 50},
                "next": []
            },
        ],
    },
    {
        "id": "tpl_doc_analysis",
        "name": "文档智能分析",
        "description": "读取文档内容，进行数据分析并生成报告",
        "category": "文档处理",
        "icon": "📊",
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.doc_proc",
                "name": "文档处理",
                "config": {"action": "parse", "file_path": ""},
                "position": {"x": 50, "y": 50},
                "next": ["block_2"]
            },
            {
                "id": "block_2",
                "type": "skill.data_analysis",
                "name": "数据分析",
                "config": {"action": "analyze"},
                "position": {"x": 300, "y": 50},
                "next": ["block_3"]
            },
            {
                "id": "block_3",
                "type": "skill.notify",
                "name": "发送通知",
                "config": {"action": "send", "channel": "email"},
                "position": {"x": 550, "y": 50},
                "next": []
            },
        ],
    },
    {
        "id": "tpl_research_assistant",
        "name": "研究助手",
        "description": "搜索资料 + 网页抓取 + 全文检索，辅助研究工作",
        "category": "研究辅助",
        "icon": "🔍",
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.fulltext_search",
                "name": "全文搜索",
                "config": {"action": "search", "query": ""},
                "position": {"x": 50, "y": 50},
                "next": ["block_2"]
            },
            {
                "id": "block_2",
                "type": "skill.web_fetch",
                "name": "网页抓取",
                "config": {"action": "fetch"},
                "position": {"x": 300, "y": 50},
                "next": ["block_3"]
            },
            {
                "id": "block_3",
                "type": "skill.tide_memory",
                "name": "记忆存档",
                "config": {"action": "store", "domain": "research"},
                "position": {"x": 550, "y": 50},
                "next": []
            },
        ],
    },
    {
        "id": "tpl_meeting_minutes",
        "name": "会议纪要助手",
        "description": "记录会议内容，翻译整理要点，生成纪要并通知",
        "category": "办公效率",
        "icon": "📝",
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.doc_proc",
                "name": "文档录入",
                "config": {"action": "parse"},
                "position": {"x": 50, "y": 50},
                "next": ["block_2"]
            },
            {
                "id": "block_2",
                "type": "skill.data_analysis",
                "name": "要点提取",
                "config": {"action": "summarize"},
                "position": {"x": 300, "y": 50},
                "next": ["block_3"]
            },
            {
                "id": "block_3",
                "type": "skill.notify",
                "name": "发送纪要",
                "config": {"action": "send", "channel": "email"},
                "position": {"x": 550, "y": 50},
                "next": []
            },
        ],
    },
    {
        "id": "tpl_multi_lang_pipeline",
        "name": "多语言内容流水线",
        "description": "抓取内容 → 翻译为多语言 → 存入记忆 → 通知",
        "category": "内容生产",
        "icon": "🌐",
        "blocks": [
            {
                "id": "block_1",
                "type": "skill.web_fetch",
                "name": "内容抓取",
                "config": {"action": "fetch"},
                "position": {"x": 50, "y": 50},
                "next": ["block_2"]
            },
            {
                "id": "block_2",
                "type": "skill.translate",
                "name": "英文翻译",
                "config": {"action": "translate", "target_lang": "en"},
                "position": {"x": 300, "y": 50},
                "next": ["block_3"]
            },
            {
                "id": "block_3",
                "type": "skill.tide_memory",
                "name": "记忆归档",
                "config": {"action": "store", "domain": "content"},
                "position": {"x": 550, "y": 50},
                "next": ["block_4"]
            },
            {
                "id": "block_4",
                "type": "skill.notify",
                "name": "发布通知",
                "config": {"action": "send"},
                "position": {"x": 800, "y": 50},
                "next": []
            },
        ],
    },
]

# ---- 积木（技能）分类映射（M2 技能无 category 字段，在此处维护映射） ----
_SKILL_CATEGORY_MAP = {
    "skill.web_fetch": "信息获取",
    "skill.fulltext_search": "信息获取",
    "skill.translate": "文本处理",
    "skill.doc_proc": "文档处理",
    "skill.data_analysis": "数据分析",
    "skill.tide_memory": "记忆存储",
    "skill.notify": "通知推送",
    "skill.calendar": "日程管理",
    "skill.code_search": "开发工具",
    "skill.code_skills": "开发工具",
}

_BLOCK_CATEGORIES = [
    {"id": "info", "name": "信息获取", "icon": "🔍", "color": "#3B82F6"},
    {"id": "text", "name": "文本处理", "icon": "📝", "color": "#10B981"},
    {"id": "doc", "name": "文档处理", "icon": "📄", "color": "#F59E0B"},
    {"id": "data", "name": "数据分析", "icon": "📊", "color": "#8B5CF6"},
    {"id": "memory", "name": "记忆存储", "icon": "🧠", "color": "#EC4899"},
    {"id": "notify", "name": "通知推送", "icon": "🔔", "color": "#EF4444"},
    {"id": "calendar", "name": "日程管理", "icon": "📅", "color": "#06B6D4"},
    {"id": "dev", "name": "开发工具", "icon": "⚙️", "color": "#6B7280"},
]


# ---- 请求模型 ----

class BlockConfig(BaseModel):
    """积木块配置"""
    id: str
    type: str  # 对应 M2 技能 ID
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)
    position: Dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0})
    next: List[str] = Field(default_factory=list)


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求"""
    name: str
    description: str = ""
    category: str = "未分类"
    blocks: List[BlockConfig] = Field(default_factory=list)
    status: str = "draft"


class WorkflowUpdateRequest(BaseModel):
    """更新工作流请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    blocks: Optional[List[BlockConfig]] = None
    status: Optional[str] = None


class WorkflowRunRequest(BaseModel):
    """运行工作流请求"""
    input_data: Dict[str, Any] = Field(default_factory=dict)
    start_block: Optional[str] = None


# ============================================================
# 工作流 CRUD API
# ============================================================

@router.get("")
async def list_workflows(
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    limit: int = Query(default=50, description="数量限制"),
    current_user: dict = Depends(get_current_user),
):
    """获取工作流列表（支持分类筛选、搜索）"""
    workflows = _load_workflows()
    items = list(workflows.values())

    # 分类筛选
    if category:
        items = [w for w in items if w.get("category") == category]

    # 状态筛选
    if status:
        items = [w for w in items if w.get("status") == status]

    # 搜索
    if search:
        keyword = search.lower()
        items = [
            w for w in items
            if keyword in w.get("name", "").lower()
            or keyword in w.get("description", "").lower()
        ]

    # 按更新时间倒序
    items.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    items = items[:limit]

    return ApiResponse.success(
        data={
            "total": len(items),
            "items": items,
        }
    )


@router.post("")
async def create_workflow(
    req: WorkflowCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建工作流"""
    workflows = _load_workflows()
    now = int(time.time())
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"

    workflow = {
        "id": workflow_id,
        "name": req.name,
        "description": req.description,
        "category": req.category,
        "blocks": [b.model_dump() for b in req.blocks],
        "created_at": now,
        "updated_at": now,
        "status": req.status or "draft",
        "created_by": current_user.get("username", ""),
    }

    workflows[workflow_id] = workflow
    _save_workflows(workflows)

    return ApiResponse.success(
        message="工作流创建成功",
        data=workflow,
    )



@router.get("/blocks")
async def list_blocks(
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    current_user: dict = Depends(get_current_user),
):
    """获取可用积木列表（从 M2 Skills Cluster 获取技能列表）

    M2 不可用时返回本地内置的积木列表作为降级
    """
    blocks = []
    m2_available = False

    try:
        m2_client = registry.get_client("m2")
        m2_available = await m2_client.health_check()

        if m2_available:
            # 从 M2 获取技能列表
            response = await m2_client.get(
                "/api/v2/skills",
                params={"page_size": 100},
                use_auth=True,
            )
            resp_code = response.get("code", -1)
            resp_data = response.get("data", {})

            if resp_code == 20000 or response.get("success", False):
                skills = resp_data.get("items", []) if isinstance(resp_data, dict) else []
                for sk in skills:
                    skill_id = sk.get("skill_id", "")
                    cat = _SKILL_CATEGORY_MAP.get(skill_id, "其他")
                    blocks.append({
                        "id": skill_id,
                        "name": sk.get("name", ""),
                        "description": sk.get("description", ""),
                        "category": cat,
                        "tags": sk.get("tags", []),
                        "version": sk.get("version", ""),
                        "enabled": sk.get("enabled", True),
                    })
    except Exception:
        # M2 不可用，使用内置积木列表
        pass

    # 如果 M2 不可用或返回为空，使用内置积木列表作为降级
    if not blocks:
        builtin_skills = [
            {"id": "skill.web_fetch", "name": "网页抓取", "description": "抓取网页内容，支持 HTML 解析",
             "category": "信息获取", "tags": ["web", "fetch"], "version": "1.0.0", "enabled": True},
            {"id": "skill.fulltext_search", "name": "全文搜索", "description": "全文检索文档和记忆内容",
             "category": "信息获取", "tags": ["search", "fulltext"], "version": "1.0.0", "enabled": True},
            {"id": "skill.translate", "name": "翻译", "description": "多语言文本翻译",
             "category": "文本处理", "tags": ["translate", "i18n"], "version": "1.0.0", "enabled": True},
            {"id": "skill.doc_proc", "name": "文档处理", "description": "文档解析、格式转换、内容提取",
             "category": "文档处理", "tags": ["doc", "parse"], "version": "1.0.0", "enabled": True},
            {"id": "skill.data_analysis", "name": "数据分析", "description": "数据分析、统计、可视化",
             "category": "数据分析", "tags": ["data", "analysis"], "version": "1.0.0", "enabled": True},
            {"id": "skill.tide_memory", "name": "潮汐记忆", "description": "存取潮汐记忆系统",
             "category": "记忆存储", "tags": ["memory", "tide"], "version": "1.0.0", "enabled": True},
            {"id": "skill.notify", "name": "通知推送", "description": "多渠道消息通知推送",
             "category": "通知推送", "tags": ["notify", "push"], "version": "1.0.0", "enabled": True},
            {"id": "skill.calendar", "name": "日程管理", "description": "日历日程安排与提醒",
             "category": "日程管理", "tags": ["calendar", "schedule"], "version": "1.0.0", "enabled": True},
        ]
        blocks = builtin_skills

    # 分类筛选
    if category:
        blocks = [b for b in blocks if b.get("category") == category]

    # 搜索
    if search:
        keyword = search.lower()
        blocks = [
            b for b in blocks
            if keyword in b.get("name", "").lower()
            or keyword in b.get("description", "").lower()
            or any(keyword in t.lower() for t in b.get("tags", []))
        ]

    return ApiResponse.success(
        data={
            "total": len(blocks),
            "items": blocks,
            "source": "m2" if m2_available else "builtin",
        }
    )



@router.get("/blocks/categories")
async def list_block_categories(
    current_user: dict = Depends(get_current_user),
):
    """获取积木分类"""
    # 尝试从 M2 获取分类
    m2_categories = []
    try:
        m2_client = registry.get_client("m2")
        m2_available = await m2_client.health_check()
        if m2_available:
            response = await m2_client.get("/api/v2/categories", use_auth=True)
            resp_code = response.get("code", -1)
            if resp_code == 20000 or response.get("success", False):
                m2_cats = response.get("data", {}).get("categories", [])
                for cat in m2_cats:
                    if isinstance(cat, dict):
                        m2_categories.append(cat)
                    else:
                        m2_categories.append({"name": cat, "count": 0})
    except Exception:
        pass

    # 使用内置分类（与积木映射对应）
    if not m2_categories:
        m2_categories = _BLOCK_CATEGORIES

    return ApiResponse.success(
        data={
            "total": len(m2_categories),
            "items": m2_categories,
        }
    )



@router.get("/templates")
async def list_templates(
    category: Optional[str] = Query(default=None, description="分类筛选"),
    current_user: dict = Depends(get_current_user),
):
    """获取模板列表"""
    templates = TEMPLATES.copy()

    if category:
        templates = [t for t in templates if t.get("category") == category]

    return ApiResponse.success(
        data={
            "total": len(templates),
            "items": templates,
        }
    )

@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取工作流详情"""
    workflows = _load_workflows()
    workflow = workflows.get(workflow_id)
    if not workflow:
        return ApiResponse.error(code=404, message=f"工作流 {workflow_id} 不存在")

    return ApiResponse.success(data=workflow)


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    req: WorkflowUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新工作流"""
    workflows = _load_workflows()
    workflow = workflows.get(workflow_id)
    if not workflow:
        return ApiResponse.error(code=404, message=f"工作流 {workflow_id} 不存在")

    # 更新字段
    if req.name is not None:
        workflow["name"] = req.name
    if req.description is not None:
        workflow["description"] = req.description
    if req.category is not None:
        workflow["category"] = req.category
    if req.blocks is not None:
        workflow["blocks"] = [b.model_dump() for b in req.blocks]
    if req.status is not None:
        workflow["status"] = req.status

    workflow["updated_at"] = int(time.time())
    workflows[workflow_id] = workflow
    _save_workflows(workflows)

    return ApiResponse.success(
        message="工作流更新成功",
        data=workflow,
    )


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除工作流"""
    workflows = _load_workflows()
    if workflow_id not in workflows:
        return ApiResponse.error(code=404, message=f"工作流 {workflow_id} 不存在")

    del workflows[workflow_id]
    _save_workflows(workflows)

    # 同时删除运行历史
    runs = _load_runs()
    if workflow_id in runs:
        del runs[workflow_id]
        _save_runs(runs)

    return ApiResponse.success(message="工作流已删除")


@router.post("/{workflow_id}/duplicate")
async def duplicate_workflow(
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
):
    """复制工作流"""
    workflows = _load_workflows()
    source = workflows.get(workflow_id)
    if not source:
        return ApiResponse.error(code=404, message=f"工作流 {workflow_id} 不存在")

    now = int(time.time())
    new_id = f"wf_{uuid.uuid4().hex[:12]}"
    new_workflow = copy.deepcopy(source)
    new_workflow["id"] = new_id
    new_workflow["name"] = f"{source['name']} (副本)"
    new_workflow["created_at"] = now
    new_workflow["updated_at"] = now
    new_workflow["status"] = "draft"

    workflows[new_id] = new_workflow
    _save_workflows(workflows)

    return ApiResponse.success(
        message="工作流复制成功",
        data=new_workflow,
    )


# ============================================================
# 工作流运行 API
# ============================================================

@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    req: WorkflowRunRequest = WorkflowRunRequest(),
    current_user: dict = Depends(get_current_user),
):
    """运行工作流（串行调用积木对应的技能）

    简单实现：按 blocks 顺序依次调用 M2 Skills 的 /api/v2/skills/invoke 接口
    记录每步的输入输出，返回运行结果
    """
    workflows = _load_workflows()
    workflow = workflows.get(workflow_id)
    if not workflow:
        return ApiResponse.error(code=404, message=f"工作流 {workflow_id} 不存在")

    blocks = workflow.get("blocks", [])
    if not blocks:
        return ApiResponse.error(code=400, message="工作流中没有积木块")

    # 确定起始积木
    start_idx = 0
    if req.start_block:
        for i, b in enumerate(blocks):
            if b["id"] == req.start_block:
                start_idx = i
                break

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    run_start_time = time.time()
    steps = []
    overall_status = "success"
    last_output = req.input_data or {}

    m2_client = None
    m2_available = False

    # 检查 M2 是否可用
    try:
        m2_client = registry.get_client("m2")
        m2_available = await m2_client.health_check()
    except Exception:
        m2_available = False

    if not m2_available:
        # M2 不可用时优雅降级
        run_record = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "status": "failed",
            "error": "M2 技能集群不可用，无法执行工作流",
            "started_at": run_start_time,
            "finished_at": time.time(),
            "steps": [],
            "triggered_by": current_user.get("username", ""),
        }
        runs = _load_runs()
        runs.setdefault(workflow_id, [])
        runs[workflow_id].insert(0, run_record)
        _save_runs(runs)

        return ApiResponse.error(
            code=503,
            message="M2 技能集群不可用，无法执行工作流",
            data=run_record,
        )

    # 串行执行每个积木块
    for i in range(start_idx, len(blocks)):
        block = blocks[i]
        step_start = time.time()
        skill_id = block.get("type", "")
        block_config = block.get("config", {})
        action = block_config.pop("action", "default")

        step_result = {
            "block_id": block["id"],
            "block_name": block.get("name", ""),
            "skill_id": skill_id,
            "action": action,
            "status": "pending",
            "input": {},
            "output": None,
            "error": None,
            "started_at": step_start,
            "finished_at": None,
            "duration_ms": 0,
        }

        # 构建输入：第一步使用用户输入，后续步骤使用上一步输出
        if i == start_idx:
            step_input = {**block_config, **(req.input_data or {})}
        else:
            step_input = {**block_config, "previous_output": last_output}

        step_result["input"] = step_input

        try:
            # 调用 M2 技能接口
            response = await m2_client.post(
                "/api/v2/skills/invoke",
                json_data={
                    "skill_id": skill_id,
                    "action": action,
                    "params": step_input,
                    "agent_id": "workflow_engine",
                    "device_type": "desktop",
                    "timeout": 30,
                },
                use_auth=True,
            )

            resp_code = response.get("code", -1)
            resp_data = response.get("data", {})

            if resp_code == 20000 or response.get("success", False):
                # 成功
                invoke_data = resp_data.get("data", resp_data) if isinstance(resp_data, dict) else resp_data
                step_result["status"] = "success"
                step_result["output"] = invoke_data
                last_output = invoke_data if isinstance(invoke_data, dict) else {"result": invoke_data}
            else:
                # 技能执行失败
                step_result["status"] = "failed"
                step_result["error"] = response.get("message", "技能执行失败")
                overall_status = "failed"

        except Exception as e:
            step_result["status"] = "failed"
            step_result["error"] = str(e)
            overall_status = "failed"

        step_result["finished_at"] = time.time()
        step_result["duration_ms"] = int((step_result["finished_at"] - step_start) * 1000)
        steps.append(step_result)

        # 如果失败则停止后续执行
        if step_result["status"] != "success":
            break

    run_end_time = time.time()

    # 保存运行记录
    run_record = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": overall_status,
        "started_at": run_start_time,
        "finished_at": run_end_time,
        "duration_ms": int((run_end_time - run_start_time) * 1000),
        "steps": steps,
        "total_blocks": len(blocks),
        "success_blocks": sum(1 for s in steps if s["status"] == "success"),
        "failed_blocks": sum(1 for s in steps if s["status"] == "failed"),
        "triggered_by": current_user.get("username", ""),
        "final_output": last_output if overall_status == "success" else None,
    }

    runs = _load_runs()
    runs.setdefault(workflow_id, [])
    runs[workflow_id].insert(0, run_record)
    # 只保留最近 50 条记录
    runs[workflow_id] = runs[workflow_id][:50]
    _save_runs(runs)

    return ApiResponse.success(
        message="工作流执行完成" if overall_status == "success" else "工作流执行失败",
        data=run_record,
    )


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    limit: int = Query(default=20, description="数量限制"),
    current_user: dict = Depends(get_current_user),
):
    """获取工作流运行历史"""
    workflows = _load_workflows()
    if workflow_id not in workflows:
        return ApiResponse.error(code=404, message=f"工作流 {workflow_id} 不存在")

    runs = _load_runs()
    run_list = runs.get(workflow_id, [])
    run_list = run_list[:limit]

    return ApiResponse.success(
        data={
            "total": len(run_list),
            "items": run_list,
        }
    )


# ============================================================
# 积木块管理 API
# ============================================================
