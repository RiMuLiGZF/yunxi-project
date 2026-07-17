"""
云汐系统 - CORS 配置统一工具

提供标准化的 CORS 来源解析与安全校验，确保各模块遵循统一的安全策略。

策略说明：
- 生产环境（ENV=production）：必须显式配置 ALLOWED_ORIGINS，禁止使用 ["*"]
  - 如果未配置或配置为 "*"，启动失败并给出明确错误提示
  - 如果 allow_credentials=True，则 origins 绝对不能为 ["*"]
- 开发环境（ENV=development）：默认允许 localhost 常用端口，输出警告日志
- 向后兼容：如果已有配置文件指定了具体 origins，则尊重原有配置

使用方式：
    from shared.cors_utils import resolve_cors_origins, validate_cors_config

    origins = resolve_cors_origins(
        configured_origins=settings.cors_origins,
        env=settings.env,
        module_name="m8",
        logger=logger,
    )
"""

import os
import logging
from typing import List, Optional


# 开发环境默认允许的 localhost 端口
DEFAULT_DEV_LOCALHOST_PORTS = [3000, 5173, 8080] + list(range(8000, 8013))

# 开发环境默认允许的来源列表
DEFAULT_DEV_ORIGINS: List[str] = [
    f"http://localhost:{port}" for port in DEFAULT_DEV_LOCALHOST_PORTS
] + [
    f"http://127.0.0.1:{port}" for port in DEFAULT_DEV_LOCALHOST_PORTS
]


def _is_production(env: str) -> bool:
    """判断是否为生产环境"""
    return env.lower() in ("production", "prod", "release")


def _parse_origins(raw_origins: Optional[str]) -> List[str]:
    """
    解析原始 origins 配置字符串为列表

    支持格式：
    - "*" → ["*"]
    - "http://a.com, http://b.com" → ["http://a.com", "http://b.com"]
    - 空字符串/None → []
    """
    if not raw_origins:
        return []
    if raw_origins.strip() == "*":
        return ["*"]
    return [o.strip() for o in raw_origins.split(",") if o.strip()]


def _has_wildcard(origins: List[str]) -> bool:
    """检查 origins 列表中是否包含通配符"""
    return any(o == "*" for o in origins)


def resolve_cors_origins(
    configured_origins: Optional[str],
    env: str = "development",
    module_name: str = "unknown",
    logger: Optional[logging.Logger] = None,
) -> List[str]:
    """
    解析 CORS 允许来源列表，根据环境应用安全策略

    Args:
        configured_origins: 配置的 origins 字符串（逗号分隔，或 "*"）
        env: 当前环境（development/production）
        module_name: 模块名称（用于日志）
        logger: 日志记录器

    Returns:
        CORS 允许来源列表

    Raises:
        RuntimeError: 生产环境未配置 ALLOWED_ORIGINS 或配置为 "*" 时抛出
    """
    if logger is None:
        logger = logging.getLogger(f"yunxi.cors.{module_name}")

    is_prod = _is_production(env)
    parsed = _parse_origins(configured_origins)

    # --- 生产环境策略 ---
    if is_prod:
        if not parsed or _has_wildcard(parsed):
            error_msg = (
                f"[CORS] 生产环境安全校验失败：模块 '{module_name}' 的 CORS origins "
                f"配置为 '{configured_origins}'。"
                f"生产环境必须显式配置具体的允许来源（ALLOWED_ORIGINS），"
                f"禁止使用通配符 '*'。请在配置文件或环境变量中设置正确的来源列表。"
            )
            logger.critical(error_msg)
            raise RuntimeError(error_msg)

        logger.info(
            f"[CORS] 生产环境已加载 {len(parsed)} 个允许来源 "
            f"(模块: {module_name})"
        )
        return parsed

    # --- 开发环境策略 ---
    if not parsed or _has_wildcard(parsed):
        # 未配置或配置为 "*"，使用开发环境默认值
        logger.warning(
            f"[CORS] ⚠️ 开发环境 CORS 配置为 '{configured_origins}'，"
            f"已自动替换为 localhost 默认端口列表（{len(DEFAULT_DEV_ORIGINS)} 个来源）。"
            f"如需自定义，请配置 ALLOWED_ORIGINS 环境变量。"
            f"（模块: {module_name}）"
        )
        return DEFAULT_DEV_ORIGINS.copy()

    # 开发环境且配置了具体来源，尊重配置
    logger.info(
        f"[CORS] 开发环境已加载 {len(parsed)} 个自定义允许来源 "
        f"(模块: {module_name})"
    )
    return parsed


def validate_cors_config(
    origins: List[str],
    allow_credentials: bool = True,
    env: str = "development",
    module_name: str = "unknown",
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    校验 CORS 配置的安全性

    主要检查：
    1. allow_credentials=True 时 origins 不能包含 "*"
    2. 生产环境不能使用 "*"

    Args:
        origins: 解析后的 origins 列表
        allow_credentials: 是否允许携带凭证
        env: 当前环境
        module_name: 模块名称
        logger: 日志记录器

    Raises:
        RuntimeError: 配置存在安全风险时抛出
    """
    if logger is None:
        logger = logging.getLogger(f"yunxi.cors.{module_name}")

    has_wildcard = _has_wildcard(origins)

    # 核心安全规则：allow_credentials=True 时绝对不能有 "*"
    if allow_credentials and has_wildcard:
        error_msg = (
            f"[CORS] 严重安全风险：模块 '{module_name}' 同时配置了 "
            f"allow_credentials=True 和 allow_origins=['*']。"
            f"这会导致 CSRF 漏洞，浏览器规范也不允许这种组合。"
            f"请将 origins 配置为具体的域名列表。"
        )
        logger.critical(error_msg)
        raise RuntimeError(error_msg)

    # 生产环境必须有具体来源
    if _is_production(env) and (not origins or has_wildcard):
        error_msg = (
            f"[CORS] 生产环境必须配置具体的允许来源（模块: {module_name}）"
        )
        logger.critical(error_msg)
        raise RuntimeError(error_msg)


def get_cors_middleware_kwargs(
    configured_origins: Optional[str],
    env: str = "development",
    module_name: str = "unknown",
    allow_credentials: bool = True,
    logger: Optional[logging.Logger] = None,
) -> dict:
    """
    获取 FastAPI CORSMiddleware 的参数字典

    这是便捷函数，直接返回可用于 app.add_middleware 的 kwargs。

    Args:
        configured_origins: 配置的 origins 字符串
        env: 当前环境
        module_name: 模块名称
        allow_credentials: 是否允许携带凭证
        logger: 日志记录器

    Returns:
        包含 allow_origins, allow_credentials, allow_methods, allow_headers 的字典
    """
    origins = resolve_cors_origins(
        configured_origins=configured_origins,
        env=env,
        module_name=module_name,
        logger=logger,
    )
    validate_cors_config(
        origins=origins,
        allow_credentials=allow_credentials,
        env=env,
        module_name=module_name,
        logger=logger,
    )
    return {
        "allow_origins": origins,
        "allow_credentials": allow_credentials,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
