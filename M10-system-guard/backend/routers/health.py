"""
云汐 M10 系统卫士 - 健康评估 API
提供综合评分、各维度评分、风险预测、健康趋势等接口
"""

from fastapi import APIRouter, Query

# 兼容相对导入和直接运行
try:
    from ..services.health_assessor import get_health_assessor
    from ..models import make_response, make_error_response
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from services.health_assessor import get_health_assessor
    from models import make_response, make_error_response

router = APIRouter(prefix="/api/m10/health", tags=["M10-健康评估"])


# ===== 综合评分 =====

@router.get("/score", summary="获取综合健康评分")
def get_health_score():
    """
    获取系统综合健康评分，包含7个维度的加权评分
    """
    try:
        assessor = get_health_assessor()
        score = assessor.get_health_score()
        return make_response(data=score)
    except Exception as e:
        return make_error_response(f"获取健康评分失败: {str(e)}")


# ===== 各维度评分 =====

@router.get("/dimensions", summary="获取各维度详细评分")
def get_dimension_scores():
    """
    获取7个健康维度的详细评分和对应指标数据
    """
    try:
        assessor = get_health_assessor()
        dimensions = assessor.get_dimension_scores()
        return make_response(data=dimensions)
    except Exception as e:
        return make_error_response(f"获取维度评分失败: {str(e)}")


# ===== 风险预测 =====

@router.get("/risk-prediction", summary="获取风险预测")
def get_risk_prediction():
    """
    基于历史趋势预测未来10分钟的系统资源状态和风险预警
    """
    try:
        assessor = get_health_assessor()
        prediction = assessor.get_risk_prediction()
        return make_response(data=prediction)
    except Exception as e:
        return make_error_response(f"获取风险预测失败: {str(e)}")


# ===== 健康趋势 =====

@router.get("/trend", summary="获取健康趋势")
def get_health_trend(
    minutes: int = Query(30, description="趋势时长(分钟)", ge=5, le=1440),
):
    """
    获取系统健康度趋势数据，可自定义时间范围
    """
    try:
        assessor = get_health_assessor()
        trend = assessor.get_health_trend(minutes=minutes)
        return make_response(data={
            "period_minutes": minutes,
            "data_points": len(trend),
            "trend": trend,
        })
    except Exception as e:
        return make_error_response(f"获取健康趋势失败: {str(e)}")


# ===== 完整健康报告 =====

@router.get("/report", summary="获取完整健康报告")
def get_health_report():
    """
    获取包含评分、维度详情、风险预测和优化建议的完整健康报告
    """
    try:
        assessor = get_health_assessor()
        report = assessor.get_health_report()
        return make_response(data=report)
    except Exception as e:
        return make_error_response(f"获取健康报告失败: {str(e)}")
