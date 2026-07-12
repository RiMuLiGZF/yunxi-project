"""
M10 系统卫士 - 报告生成 API

硬件保护报告生成、查询、列表等接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..models import make_response, ReportGenerateRequest
from ..report_generator import get_report_generator

router = APIRouter()


def _success(data=None, message: str = "ok"):
    """构造成功响应."""
    return make_response(data=data, message=message)


@router.post("/generate", summary="生成报告")
async def generate_report(request: ReportGenerateRequest):
    """生成硬件保护报告.

    支持每日(daily)和每周(weekly)报告，输出格式支持 Markdown 和 HTML。
    """
    generator = get_report_generator()
    report = generator.generate_report(
        report_type=request.report_type,
        start_time=request.start_time,
        end_time=request.end_time,
    )

    # 根据格式渲染
    if request.format == "html":
        content = generator.render_html(report)
    else:
        content = generator.render_markdown(report)

    return _success({
        "report": report.to_dict(),
        "format": request.format,
        "content": content,
    })


@router.get("/{report_id}", summary="报告详情")
async def report_detail(report_id: str):
    """根据 ID 获取报告详情."""
    generator = get_report_generator()
    report = generator.get_report(report_id)
    if report is None:
        return make_response(code=404, message=f"报告不存在: {report_id}")
    return _success(report.to_dict())


@router.get("/{report_id}/markdown", summary="报告 Markdown")
async def report_markdown(report_id: str):
    """获取报告的 Markdown 格式内容."""
    generator = get_report_generator()
    report = generator.get_report(report_id)
    if report is None:
        return make_response(code=404, message=f"报告不存在: {report_id}")
    content = generator.render_markdown(report)
    return _success({
        "report_id": report_id,
        "format": "markdown",
        "content": content,
    })


@router.get("/{report_id}/html", summary="报告 HTML")
async def report_html(report_id: str):
    """获取报告的 HTML 格式内容."""
    generator = get_report_generator()
    report = generator.get_report(report_id)
    if report is None:
        return make_response(code=404, message=f"报告不存在: {report_id}")
    content = generator.render_html(report)
    return _success({
        "report_id": report_id,
        "format": "html",
        "content": content,
    })


@router.get("", summary="报告列表")
async def report_list(limit: int = Query(20, ge=1, le=100, description="返回数量")):
    """获取已生成的报告列表."""
    generator = get_report_generator()
    reports = generator.list_reports(limit=limit)
    return _success({
        "count": len(reports),
        "reports": reports,
    })


@router.post("/daily", summary="生成日报")
async def generate_daily():
    """快速生成每日硬件保护报告."""
    generator = get_report_generator()
    report = generator.generate_daily_report()
    content = generator.render_markdown(report)
    return _success({
        "report": report.to_dict(),
        "markdown": content,
    })


@router.post("/weekly", summary="生成周报")
async def generate_weekly():
    """快速生成每周硬件保护报告."""
    generator = get_report_generator()
    report = generator.generate_weekly_report()
    content = generator.render_markdown(report)
    return _success({
        "report": report.to_dict(),
        "markdown": content,
    })
