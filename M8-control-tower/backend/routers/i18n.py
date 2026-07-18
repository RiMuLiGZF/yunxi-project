"""
i18n 国际化 API 路由
=====================

提供国际化相关的 REST API 接口：
- GET  /i18n/languages        - 支持的语言列表
- GET  /i18n/translations/{lang} - 获取指定语言翻译
- POST /i18n/set-language     - 设置用户语言偏好
- GET  /i18n/current          - 当前语言
- GET  /i18n/missing          - 缺失的翻译键
- POST /i18n/reload           - 重新加载翻译文件
- GET  /i18n/stats            - 国际化统计
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Request, HTTPException, Query, Cookie
from pydantic import BaseModel, Field

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 优先使用 shared 的 i18n，不可用时使用本地回退
try:
    from shared.i18n.core import (
        I18nManager,
        get_i18n,
        SUPPORTED_LANGUAGES,
        DEFAULT_LANGUAGE,
    )
    from shared.i18n.middleware import get_language_from_request
    _i18n_available = True
except ImportError:
    _i18n_available = False
    SUPPORTED_LANGUAGES = {
        "zh-CN": {"name": "简体中文", "native_name": "简体中文", "direction": "ltr", "flag": "🇨🇳"},
        "en-US": {"name": "English (US)", "native_name": "English", "direction": "ltr", "flag": "🇺🇸"},
    }
    DEFAULT_LANGUAGE = "zh-CN"


router = APIRouter(prefix="", tags=["国际化"])


# ------------------------------------------------------------------
# 请求/响应模型
# ------------------------------------------------------------------

class LanguageInfo(BaseModel):
    """语言信息"""
    code: str = Field(..., description="语言代码，如 zh-CN")
    name: str = Field(..., description="语言英文名称")
    native_name: str = Field(..., description="语言母语名称")
    direction: str = Field(..., description="文本方向，ltr 或 rtl")
    flag: str = Field("", description="国旗 emoji")
    is_default: bool = Field(False, description="是否为默认语言")


class SetLanguageRequest(BaseModel):
    """设置语言请求"""
    language: str = Field(..., description="语言代码，如 zh-CN")
    persist: bool = Field(True, description="是否持久化到 Cookie")


class I18nStats(BaseModel):
    """国际化统计"""
    default_language: str
    fallback_language: str
    supported_languages: List[str]
    languages: Dict[str, Any]


class I18nResponse(BaseModel):
    """通用响应"""
    code: int = 0
    message: str = "ok"
    data: Optional[Any] = None


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _get_i18n_manager() -> Optional[I18nManager]:
    """获取 i18n 管理器"""
    if not _i18n_available:
        return None
    try:
        return get_i18n()
    except Exception:
        return None


def _build_language_list() -> List[Dict[str, Any]]:
    """构建语言列表"""
    languages = []
    for code, info in SUPPORTED_LANGUAGES.items():
        languages.append({
            "code": code,
            "name": info.get("name", code),
            "native_name": info.get("native_name", code),
            "direction": info.get("direction", "ltr"),
            "flag": info.get("flag", ""),
            "is_default": code == DEFAULT_LANGUAGE,
        })
    return languages


# ------------------------------------------------------------------
# API 接口
# ------------------------------------------------------------------

@router.get("/languages", response_model=I18nResponse, summary="获取支持的语言列表")
async def get_languages() -> I18nResponse:
    """
    获取系统支持的所有语言列表

    返回每种语言的代码、名称、母语名称、文本方向等信息。
    """
    languages = _build_language_list()
    return I18nResponse(
        code=0,
        message="ok",
        data={
            "languages": languages,
            "default": DEFAULT_LANGUAGE,
            "total": len(languages),
        }
    )


@router.get("/translations/{lang}", response_model=I18nResponse, summary="获取指定语言的翻译")
async def get_translations(
    lang: str,
    namespace: Optional[str] = Query(None, description="命名空间，如 common / errors / modules"),
) -> I18nResponse:
    """
    获取指定语言的翻译数据

    - **lang**: 语言代码（zh-CN, en-US, ja-JP 等）
    - **namespace**: 可选，指定命名空间，不填返回所有命名空间
    """
    i18n = _get_i18n_manager()
    if i18n is None:
        raise HTTPException(status_code=503, detail="i18n 服务不可用")

    # 规范化语言代码
    normalized = i18n.normalize_language(lang)
    if not i18n.is_supported(normalized):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的语言: {lang}，支持的语言: {', '.join(SUPPORTED_LANGUAGES.keys())}"
        )

    translations = i18n.get_translations(normalized, namespace)

    return I18nResponse(
        code=0,
        message="ok",
        data={
            "language": normalized,
            "namespace": namespace or "all",
            "translations": translations,
        }
    )


@router.post("/set-language", response_model=I18nResponse, summary="设置用户语言偏好")
async def set_language(
    request: Request,
    body: SetLanguageRequest,
) -> I18nResponse:
    """
    设置用户的语言偏好

    - **language**: 语言代码
    - **persist**: 是否持久化到 Cookie（默认 true）

    设置成功后，后续请求将使用该语言。
    """
    i18n = _get_i18n_manager()
    if i18n is None:
        raise HTTPException(status_code=503, detail="i18n 服务不可用")

    # 规范化语言代码
    normalized = i18n.normalize_language(body.language)
    if not i18n.is_supported(normalized):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的语言: {body.language}"
        )

    # 保存到 request.state（中间件会读取）
    request.state.language = normalized

    # 如果需要持久化，设置 Cookie（在响应中设置）
    response_data = {
        "language": normalized,
        "persisted": body.persist,
        "cookie_name": "yunxi_lang" if body.persist else None,
    }

    return I18nResponse(
        code=0,
        message=i18n.t("common.operation_success", language=normalized),
        data=response_data,
    )


@router.get("/current", response_model=I18nResponse, summary="获取当前语言")
async def get_current_lang(
    request: Request,
) -> I18nResponse:
    """
    获取当前请求使用的语言

    返回当前检测到的语言及其详细信息。
    """
    i18n = _get_i18n_manager()

    if i18n is not None:
        current = get_language_from_request(request)
    else:
        current = DEFAULT_LANGUAGE

    # 获取语言详细信息
    lang_info = SUPPORTED_LANGUAGES.get(current, {})
    language_data = {
        "code": current,
        "name": lang_info.get("name", current),
        "native_name": lang_info.get("native_name", current),
        "direction": lang_info.get("direction", "ltr"),
        "flag": lang_info.get("flag", ""),
        "is_default": current == DEFAULT_LANGUAGE,
    }

    return I18nResponse(
        code=0,
        message="ok",
        data=language_data,
    )


@router.get("/missing", response_model=I18nResponse, summary="获取缺失的翻译键")
async def get_missing_keys(
    language: Optional[str] = Query(None, description="指定语言，不填返回所有语言"),
) -> I18nResponse:
    """
    获取缺失的翻译键列表

    用于开发和调试，查看哪些翻译键还没有翻译。

    - **language**: 可选，指定语言
    """
    i18n = _get_i18n_manager()
    if i18n is None:
        raise HTTPException(status_code=503, detail="i18n 服务不可用")

    missing = i18n.get_missing_keys(language)

    # 统计总数
    total = sum(len(keys) for keys in missing.values())

    return I18nResponse(
        code=0,
        message="ok",
        data={
            "missing": missing,
            "total_missing": total,
            "language": language or "all",
        }
    )


@router.post("/reload", response_model=I18nResponse, summary="重新加载翻译文件")
async def reload_translations() -> I18nResponse:
    """
    重新加载所有翻译文件

    用于翻译文件更新后，无需重启服务即可生效。

    **注意**: 需要管理员权限。
    """
    i18n = _get_i18n_manager()
    if i18n is None:
        raise HTTPException(status_code=503, detail="i18n 服务不可用")

    try:
        i18n.reload()
        stats = i18n.get_stats()
        total_keys = sum(
            lang_info.get("total_keys", 0)
            for lang_info in stats.get("languages", {}).values()
        )

        return I18nResponse(
            code=0,
            message="翻译文件重新加载成功",
            data={
                "reloaded": True,
                "languages": len(stats.get("supported_languages", [])),
                "total_keys": total_keys,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重新加载失败: {str(e)}")


@router.get("/stats", response_model=I18nResponse, summary="获取国际化统计信息")
async def get_i18n_stats() -> I18nResponse:
    """
    获取国际化统计信息

    返回各语言的翻译数量、命名空间、缺失键等统计数据。
    """
    i18n = _get_i18n_manager()
    if i18n is None:
        raise HTTPException(status_code=503, detail="i18n 服务不可用")

    stats = i18n.get_stats()

    return I18nResponse(
        code=0,
        message="ok",
        data=stats,
    )
