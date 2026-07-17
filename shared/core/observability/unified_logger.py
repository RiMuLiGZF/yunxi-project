"""
云汐统一日志系统

支持：
- 结构化日志（JSON格式）
- 多输出目标（控制台+文件）
- 日志级别动态调整
- 上下文注入（trace_id、user_id等）
- 日志轮转（按大小/时间）
"""
import os
import sys
import json
import logging
import logging.handlers
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime


class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # 添加异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # 添加上下文信息（从extra传入）
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        if hasattr(record, "module_key"):
            log_entry["module_key"] = record.module_key
        if hasattr(record, "extra"):
            log_entry["extra"] = record.extra
        
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """文本格式日志格式化器（带颜色）"""
    
    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[35m",  # 紫色
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET if color else ""
        
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        
        # 上下文信息
        context = ""
        if hasattr(record, "trace_id"):
            context += f" [trace:{record.trace_id[:8]}]"
        if hasattr(record, "user_id"):
            context += f" [user:{record.user_id}]"
        
        return (
            f"{timestamp} {color}{record.levelname:<8}{reset} "
            f"{record.name}{context}: {record.getMessage()}"
        )


class UnifiedLogger:
    """统一日志管理器"""
    
    def __init__(
        self,
        name: str = "yunxi",
        level: str = "INFO",
        log_dir: Optional[str] = None,
        json_format: bool = False,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        console_output: bool = True,
    ):
        """
        初始化统一日志器
        
        Args:
            name: 日志器名称
            level: 日志级别
            log_dir: 日志目录，None则不输出到文件
            json_format: 是否使用JSON格式
            max_bytes: 单个日志文件最大大小
            backup_count: 保留的日志文件数
            console_output: 是否输出到控制台
        """
        self.name = name
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.log_dir = Path(log_dir) if log_dir else None
        self.json_format = json_format
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.console_output = console_output
        
        self._context: Dict[str, Any] = {}
        self._logger = self._build_logger()
    
    def _build_logger(self) -> logging.Logger:
        """构建日志器"""
        logger = logging.getLogger(self.name)
        logger.setLevel(self.level)
        logger.propagate = False
        
        # 清除已有handler
        logger.handlers.clear()
        
        # 控制台输出
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.level)
            if self.json_format:
                console_handler.setFormatter(JsonFormatter())
            else:
                console_handler.setFormatter(TextFormatter())
            logger.addHandler(console_handler)
        
        # 文件输出
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            
            # 普通日志文件
            log_file = self.log_dir / f"{self.name}.log"
            file_handler = logging.handlers.RotatingFileHandler(
                str(log_file),
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(self.level)
            file_handler.setFormatter(JsonFormatter())
            logger.addHandler(file_handler)
            
            # 错误日志文件（单独文件）
            error_file = self.log_dir / f"{self.name}-error.log"
            error_handler = logging.handlers.RotatingFileHandler(
                str(error_file),
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8",
            )
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(JsonFormatter())
            logger.addHandler(error_handler)
        
        return logger
    
    def set_context(self, **kwargs):
        """设置日志上下文（会附加到每条日志）"""
        self._context.update(kwargs)
    
    def clear_context(self):
        """清除上下文"""
        self._context.clear()
    
    def _build_extra(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """构建extra参数，注入上下文"""
        result = dict(self._context)
        if extra:
            result.update(extra)
        return {"extra": result} if result else {}
    
    def debug(self, msg: str, **kwargs):
        self._logger.debug(msg, **self._build_extra(kwargs))
    
    def info(self, msg: str, **kwargs):
        self._logger.info(msg, **self._build_extra(kwargs))
    
    def warning(self, msg: str, **kwargs):
        self._logger.warning(msg, **self._build_extra(kwargs))
    
    def warn(self, msg: str, **kwargs):
        self.warning(msg, **kwargs)
    
    def error(self, msg: str, exc_info=False, **kwargs):
        self._logger.error(msg, exc_info=exc_info, **self._build_extra(kwargs))
    
    def critical(self, msg: str, exc_info=False, **kwargs):
        self._logger.critical(msg, exc_info=exc_info, **self._build_extra(kwargs))
    
    def exception(self, msg: str, **kwargs):
        self._logger.exception(msg, **self._build_extra(kwargs))
    
    def set_level(self, level: str):
        """动态设置日志级别"""
        self.level = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(self.level)
        for handler in self._logger.handlers:
            handler.setLevel(self.level)
    
    def get_logger(self) -> logging.Logger:
        """获取底层logging.Logger实例"""
        return self._logger


# 全局日志器缓存
_loggers: Dict[str, UnifiedLogger] = {}


def get_logger(
    name: str = "yunxi",
    level: Optional[str] = None,
    log_dir: Optional[str] = None,
    json_format: bool = False,
) -> UnifiedLogger:
    """
    获取统一日志器（单例模式）
    
    Args:
        name: 日志器名称
        level: 日志级别，None使用默认
        log_dir: 日志目录
        json_format: 是否使用JSON格式
    
    Returns:
        UnifiedLogger 实例
    """
    if name not in _loggers:
        if level is None:
            level = os.getenv("LOG_LEVEL", "INFO")
        if log_dir is None:
            env_log_dir = os.getenv("LOG_DIR")
            if env_log_dir:
                log_dir = env_log_dir
        
        _loggers[name] = UnifiedLogger(
            name=name,
            level=level,
            log_dir=log_dir,
            json_format=json_format,
        )
    
    return _loggers[name]
