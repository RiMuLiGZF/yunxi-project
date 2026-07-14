"""M7 积木平台 - 工作流执行器.

节点级执行逻辑：内置积木降级实现、M2 技能客户端、安全表达式求值、语音引擎适配。
从 engine.py 拆分而来，保持原有行为不变。
"""

from __future__ import annotations

import ast
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger("m7.engine")

# 安全工具
try:
    from ..utils.security import safe_audio_path, safe_output_path, validate_file_extension, ALLOWED_AUDIO_EXTENSIONS
    _security_available = True
except ImportError:
    _security_available = False

def _safe_audio_path(audio_path: str) -> str:
    """安全的音频路径校验（降级兼容）."""
    if _security_available:
        return safe_audio_path(audio_path)
    # 降级：做基本检查
    if not audio_path or '..' in audio_path:
        raise ValueError("无效的音频文件路径")
    return audio_path

def _safe_output_path(output_path: Optional[str], suffix: str = ".tmp") -> str:
    """安全的输出路径生成（降级兼容）."""
    if _security_available:
        return safe_output_path(output_path, suffix)
    # 降级：使用系统临时目录
    import tempfile
    if output_path and '..' not in output_path:
        return output_path
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path

# 语音引擎（可选，shared/voice_engine.py）
# 路径：yunxi-project/shared/voice_engine.py
_voice_available = False
_voice_import_error = None
_tts_engine = None
_asr_engine = None

try:
    import sys as _sys
    import os as _os
    _current_dir = _os.path.dirname(_os.path.abspath(__file__))
    # src/services -> src -> M7-workflow-builder -> yunxi-project -> shared
    _shared_dir = _os.path.normpath(_os.path.join(_current_dir, '..', '..', '..', 'shared'))
    if _shared_dir not in _sys.path:
        _sys.path.insert(0, _shared_dir)
    from voice_engine import TTSEngine, ASREngine, AudioUtils
    _voice_available = True
except Exception as _e:
    _voice_available = False
    _voice_import_error = str(_e)


def _get_tts_engine(config=None):
    """获取TTS引擎实例（懒加载单例）."""
    global _tts_engine
    if not _voice_available:
        return None
    if _tts_engine is None or config:
        _tts_engine = TTSEngine(config)
    return _tts_engine


def _get_asr_engine(config=None):
    """获取ASR引擎实例（懒加载单例）."""
    global _asr_engine
    if not _voice_available:
        return None
    if _asr_engine is None or config:
        _asr_engine = ASREngine(config)
    return _asr_engine



# ============================================================
# 内置积木降级实现
# ============================================================

BUILTIN_BLOCKS: Dict[str, Dict[str, Any]] = {
    "skill.web_fetch": {
        "name": "网页抓取",
        "description": "抓取网页内容，支持 HTML 解析（内置降级实现）",
        "actions": ["fetch", "fetch_text"],
    },
    "skill.fulltext_search": {
        "name": "全文搜索",
        "description": "全文检索文档和记忆内容（内置降级实现）",
        "actions": ["search", "search_docs"],
    },
    "skill.translate": {
        "name": "翻译",
        "description": "多语言文本翻译（内置降级实现）",
        "actions": ["translate", "detect_language"],
    },
    "skill.doc_proc": {
        "name": "文档处理",
        "description": "文档解析、格式转换、内容提取（内置降级实现）",
        "actions": ["parse", "extract", "summarize"],
    },
    "skill.data_analysis": {
        "name": "数据分析",
        "description": "数据分析、统计、可视化（内置降级实现）",
        "actions": ["analyze", "summarize", "chart"],
    },
    "skill.tide_memory": {
        "name": "潮汐记忆",
        "description": "存取潮汐记忆系统（内置降级实现）",
        "actions": ["store", "recall", "search"],
    },
    "skill.notify": {
        "name": "通知推送",
        "description": "多渠道消息通知推送（内置降级实现）",
        "actions": ["send", "send_batch"],
    },
    "skill.calendar": {
        "name": "日程管理",
        "description": "日历日程安排与提醒（内置降级实现）",
        "actions": ["create", "list", "update", "delete"],
    },
    # P2-15: 条件分支积木（纯逻辑，不依赖外部服务）
    "logic.condition": {
        "name": "条件分支",
        "description": "根据条件表达式判断，走 true 或 false 分支",
        "actions": ["evaluate"],
        "category": "logic",
        "type": "control",
    },
    # 语音处理积木
    "voice.asr": {
        "name": "语音识别",
        "description": "将音频文件转写为文本，支持多语言识别",
        "actions": ["transcribe"],
        "category": "voice",
    },
    "voice.tts": {
        "name": "语音合成",
        "description": "将文本合成为语音，支持多种音色和语速调节",
        "actions": ["synthesize", "speak"],
        "category": "voice",
    },
    "voice.wake_word": {
        "name": "唤醒词检测",
        "description": "检测音频中是否包含预设的唤醒关键词",
        "actions": ["detect"],
        "category": "voice",
    },
    "voice.record": {
        "name": "录音控制",
        "description": "控制麦克风录音，支持指定时长录制",
        "actions": ["record"],
        "category": "voice",
    },
}


class _SafeExpressionEvaluator:
    """基于 AST 的安全表达式求值器.

    只允许白名单内的操作：
    - 算术运算：+ - * / % ** //
    - 比较运算：== != > < >= <=
    - 逻辑运算：and or not
    - 成员运算：in not in
    - 一元运算：+ - ~
    - 下标访问：obj[key]
    - 属性访问：obj.attr（仅安全白名单类型）
    - 函数调用：仅 len() 函数
    - 字面量：字符串、数字、布尔值、None、列表、字典、元组

    同时限制最大执行步数，防止 DoS 攻击。
    """

    # 允许的函数名 -> 实际函数
    _ALLOWED_FUNCTIONS = {
        "len": len,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "round": round,
    }

    # 允许属性访问的安全类型（不可变/无副作用）
    _SAFE_ATTR_TYPES = (
        str, int, float, bool, list, dict, tuple, set,
    )

    # 字符串方法白名单
    _SAFE_STR_METHODS = {
        "lower", "upper", "strip", "lstrip", "rstrip",
        "startswith", "endswith", "find", "count",
        "replace", "split", "join", "isdigit", "isalpha",
        "isalnum", "isspace", "islower", "isupper",
        "title", "capitalize", "format",
    }

    def __init__(self, max_steps: int = 1000):
        self.max_steps = max_steps
        self._step_count = 0

    def _check_steps(self):
        """检查执行步数，防止 DoS."""
        self._step_count += 1
        if self._step_count > self.max_steps:
            raise ValueError(f"表达式执行步数超过上限 {self.max_steps}，可能存在无限循环")

    def evaluate(self, expression: str, context: Dict[str, Any]) -> Any:
        """求值表达式.

        Args:
            expression: 表达式字符串
            context: 变量上下文

        Returns:
            表达式结果

        Raises:
            ValueError: 表达式不安全或执行超时
        """
        self._step_count = 0
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"表达式语法错误: {e}") from e

        return self._eval_node(tree.body, context)

    def _eval_node(self, node: ast.AST, context: Dict[str, Any]) -> Any:
        """递归求值 AST 节点."""
        self._check_steps()

        # 常量（Python 3.8+ 的 Constant 节点）
        if isinstance(node, ast.Constant):
            return node.value

        # 名称（变量或函数）
        if isinstance(node, ast.Name):
            name = node.id
            # 先查上下文
            if name in context:
                return context[name]
            # 再查允许的函数
            if name in self._ALLOWED_FUNCTIONS:
                return self._ALLOWED_FUNCTIONS[name]
            # 布尔值和 None（兼容旧版 Python）
            if name == "True":
                return True
            if name == "False":
                return False
            if name == "None":
                return None
            raise ValueError(f"未定义的变量或函数: {name}")

        # 二元运算
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, context)
            right = self._eval_node(node.right, context)
            op = node.op
            if isinstance(op, ast.Add):
                return left + right
            if isinstance(op, ast.Sub):
                return left - right
            if isinstance(op, ast.Mult):
                return left * right
            if isinstance(op, ast.Div):
                return left / right
            if isinstance(op, ast.FloorDiv):
                return left // right
            if isinstance(op, ast.Mod):
                return left % right
            if isinstance(op, ast.Pow):
                # 限制指数大小，防止计算爆炸
                if isinstance(right, (int, float)) and abs(right) > 100:
                    raise ValueError("指数过大，可能导致计算溢出")
                return left ** right
            raise ValueError(f"不支持的二元运算符: {type(op).__name__}")

        # 一元运算
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand, context)
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.Invert):
                return ~operand
            raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")

        # 布尔运算（and/or）
        if isinstance(node, ast.BoolOp):
            values = [self._eval_node(v, context) for v in node.values]
            if isinstance(node.op, ast.And):
                result = True
                for v in values:
                    result = result and v
                    if not result:
                        return False
                return result
            if isinstance(node.op, ast.Or):
                result = False
                for v in values:
                    result = result or v
                    if result:
                        return True
                return result
            raise ValueError(f"不支持的布尔运算符: {type(node.op).__name__}")

        # 比较运算
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            result = True
            current = left
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)
                if isinstance(op, ast.Eq):
                    result = result and (current == right)
                elif isinstance(op, ast.NotEq):
                    result = result and (current != right)
                elif isinstance(op, ast.Lt):
                    result = result and (current < right)
                elif isinstance(op, ast.LtE):
                    result = result and (current <= right)
                elif isinstance(op, ast.Gt):
                    result = result and (current > right)
                elif isinstance(op, ast.GtE):
                    result = result and (current >= right)
                elif isinstance(op, ast.In):
                    result = result and (current in right)
                elif isinstance(op, ast.NotIn):
                    result = result and (current not in right)
                else:
                    raise ValueError(f"不支持的比较运算符: {type(op).__name__}")
                if not result:
                    return False
                current = right
            return result

        # 下标访问（list/dict[str]）
        if isinstance(node, ast.Subscript):
            obj = self._eval_node(node.value, context)
            key = self._eval_node(node.slice, context) if hasattr(node.slice, 'value') else self._eval_slice(node.slice, context)
            return obj[key]

        # 列表/字典/元组字面量
        if isinstance(node, ast.List):
            return [self._eval_node(el, context) for el in node.elts]

        if isinstance(node, ast.Dict):
            return {
                self._eval_node(k, context): self._eval_node(v, context)
                for k, v in zip(node.keys, node.values)
            }

        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(el, context) for el in node.elts)

        # 函数调用（仅白名单函数 + 白名单方法）
        if isinstance(node, ast.Call):
            func = self._eval_node(node.func, context)

            # 情况1: 直接的内置函数调用（如 len(x)）
            if isinstance(node.func, ast.Name) and node.func.id in self._ALLOWED_FUNCTIONS:
                pass  # 允许
            # 情况2: 方法调用（如 str.startswith()）
            elif isinstance(node.func, ast.Attribute):
                obj = self._eval_node(node.func.value, context)
                method_name = node.func.attr
                # 检查方法是否在对应类型的白名单内
                if isinstance(obj, str) and method_name in self._SAFE_STR_METHODS:
                    pass  # 允许
                elif isinstance(obj, list) and method_name in {"count", "index", "copy"}:
                    pass  # 允许
                elif isinstance(obj, dict) and method_name in {"keys", "values", "items", "get", "copy"}:
                    pass  # 允许
                else:
                    raise ValueError(f"不允许调用方法: {type(obj).__name__}.{method_name}")
            # 情况3: 其他内置函数（通过值判断）
            elif func in self._ALLOWED_FUNCTIONS.values():
                pass  # 允许
            else:
                raise ValueError("不允许调用自定义函数")

            args = [self._eval_node(a, context) for a in node.args]
            kwargs = {
                kw.arg: self._eval_node(kw.value, context)
                for kw in node.keywords
                if kw.arg is not None
            }
            return func(*args, **kwargs)

        # 属性访问（仅安全类型的白名单方法）
        if isinstance(node, ast.Attribute):
            obj = self._eval_node(node.value, context)
            attr = node.attr

            # 只允许安全类型的属性访问
            if not isinstance(obj, self._SAFE_ATTR_TYPES):
                raise ValueError(f"不允许访问 {type(obj).__name__} 类型的属性")

            # 字符串方法白名单
            if isinstance(obj, str) and attr in self._SAFE_STR_METHODS:
                return getattr(obj, attr)

            # 列表方法白名单
            if isinstance(obj, list) and attr in {"count", "index", "copy", "__len__"}:
                return getattr(obj, attr)

            # 字典方法白名单
            if isinstance(obj, dict) and attr in {"keys", "values", "items", "get", "copy", "__len__"}:
                return getattr(obj, attr)

            # 基础属性：长度等
            if attr == "__len__":
                return len(obj)

            raise ValueError(f"不允许访问属性: {type(obj).__name__}.{attr}")

        # If 表达式（三元运算）
        if isinstance(node, ast.IfExp):
            test = self._eval_node(node.test, context)
            if test:
                return self._eval_node(node.body, context)
            else:
                return self._eval_node(node.orelse, context)

        raise ValueError(f"不支持的表达式类型: {type(node).__name__}")

    def _eval_slice(self, node: ast.slice, context: Dict[str, Any]) -> Any:
        """求值切片节点."""
        if isinstance(node, ast.Index):
            return self._eval_node(node.value, context)
        if isinstance(node, ast.Slice):
            lower = self._eval_node(node.lower, context) if node.lower else None
            upper = self._eval_node(node.upper, context) if node.upper else None
            step = self._eval_node(node.step, context) if node.step else None
            return slice(lower, upper, step)
        return self._eval_node(node, context)


# 全局单例求值器
_safe_eval = _SafeExpressionEvaluator(max_steps=1000)


def _evaluate_condition(
    expression: str,
    context: Dict[str, Any],
) -> bool:
    """安全计算条件表达式（基于 AST 解析，无 eval 注入风险）.

    支持的运算符:
    - 算术: + - * / % ** //
    - 比较: == != > < >= <=
    - 逻辑: and or not
    - 成员: in not in
    - 下标: obj[key]
    - 内置函数: len int float str bool abs min max sum round
    - 字符串方法: lower upper strip startswith endswith find 等
    - 三元运算: a if b else c
    - 字面量: 字符串/数字/布尔/None/列表/字典/元组

    安全特性:
    - 纯 AST 解析，不使用 eval/exec
    - 执行步数限制（默认1000步），防 DoS
    - 操作/函数/属性全部白名单机制
    - 指数大小限制，防计算爆炸

    Args:
        expression: 条件表达式，如 "value > 10" 或 "status == 'active'"
        context: 变量上下文

    Returns:
        True/False，表达式出错时默认走 false 分支
    """
    if not expression or not isinstance(expression, str):
        return False

    try:
        result = _safe_eval.evaluate(expression, context)
        return bool(result)
    except Exception:
        # 表达式出错时默认走 false 分支
        return False


async def execute_builtin_block(
    skill_id: str,
    action: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """执行内置积木（M2 不可用时的降级实现）.

    Args:
        skill_id: 技能 ID
        action: 动作名称
        params: 参数

    Returns:
        执行结果字典
    """
    # 简单的模拟实现，返回结构化的 mock 数据
    skill_info = BUILTIN_BLOCKS.get(skill_id)
    if not skill_info:
        return {
            "success": False,
            "error": f"未知的内置积木: {skill_id}",
        }

    # 根据不同技能返回不同的模拟结果
    result_data: Dict[str, Any] = {
        "skill_id": skill_id,
        "action": action,
        "executed_at": time.time(),
        "mode": "builtin_fallback",
    }

    if skill_id == "skill.web_fetch":
        result_data.update({
            "title": params.get("url", "unknown") + " - 抓取结果",
            "content": f"[内置降级] 模拟抓取 {params.get('url', '')} 的内容",
            "url": params.get("url", ""),
            "status": "ok",
        })
    elif skill_id == "skill.translate":
        text = params.get("text", params.get("content", ""))
        target_lang = params.get("target_lang", "zh-CN")
        result_data.update({
            "original_text": str(text),
            "translated_text": f"[内置降级] ({target_lang}) {text}",
            "source_lang": "auto",
            "target_lang": target_lang,
        })
    elif skill_id == "skill.fulltext_search":
        query = params.get("query", "")
        result_data.update({
            "query": query,
            "results": [],
            "total": 0,
            "message": "[内置降级] 全文搜索功能需要 M2 技能集群",
        })
    elif skill_id == "skill.doc_proc":
        result_data.update({
            "file_path": params.get("file_path", ""),
            "extracted_text": "[内置降级] 文档处理功能需要 M2 技能集群",
            "word_count": 0,
        })
    elif skill_id == "skill.data_analysis":
        result_data.update({
            "summary": "[内置降级] 数据分析功能需要 M2 技能集群",
            "stats": {},
            "insights": [],
        })
    elif skill_id == "skill.tide_memory":
        result_data.update({
            "action": action,
            "domain": params.get("domain", "default"),
            "result": "[内置降级] 潮汐记忆功能需要 M5 潮汐记忆服务",
            "success": True,
        })
    elif skill_id == "skill.notify":
        result_data.update({
            "channel": params.get("channel", "system"),
            "message": params.get("message", params.get("content", "")),
            "sent": False,
            "reason": "[内置降级] 通知推送功能需要 M2 技能集群",
        })
    elif skill_id == "skill.calendar":
        result_data.update({
            "action": action,
            "events": [],
            "message": "[内置降级] 日程管理功能需要 M2 技能集群",
        })
    elif skill_id == "logic.condition":
        # P2-15: 条件分支积木
        expression = params.get("expression", params.get("condition", ""))
        condition_result = _evaluate_condition(str(expression), params)
        result_data.update({
            "expression": expression,
            "result": condition_result,
            "branch": "true" if condition_result else "false",
            "condition_met": condition_result,
        })
    elif skill_id == "voice.asr":
        # 语音识别
        audio_path = params.get("audio_path", "")
        language = params.get("language", "zh")
        asr_engine = _get_asr_engine()

        if not audio_path:
            return {
                "success": False,
                "data": result_data,
                "error": "缺少 audio_path 参数",
            }

        # 路径安全校验
        try:
            audio_path = _safe_audio_path(str(audio_path))
        except ValueError as e:
            return {
                "success": False,
                "data": result_data,
                "error": f"音频路径不安全: {e}",
            }

        if asr_engine:
            try:
                lang_param = language if language and language != "auto" else None
                asr_result = asr_engine.transcribe(str(audio_path), language=lang_param)

                if asr_result.get("success"):
                    result_data.update({
                        "text": asr_result.get("text", ""),
                        "language": asr_result.get("language", language),
                        "duration": asr_result.get("duration", 0),
                        "engine": asr_result.get("engine", "unknown"),
                        "segments": asr_result.get("segments", []),
                        "note": asr_result.get("note", ""),
                    })
                    return {
                        "success": True,
                        "data": result_data,
                    }
                else:
                    # 引擎调用失败（非降级）
                    result_data.update({
                        "text": "",
                        "language": language,
                        "duration": 0,
                        "engine": asr_result.get("engine", "unknown"),
                    })
                    return {
                        "success": False,
                        "data": result_data,
                        "error": asr_result.get("error", "语音识别失败"),
                    }
            except Exception as e:
                result_data.update({
                    "text": "",
                    "language": language,
                    "duration": 0,
                    "engine": "error",
                })
                return {
                    "success": False,
                    "data": result_data,
                    "error": f"语音识别异常: {str(e)}",
                }
        else:
            # 引擎不可用，降级返回 mock
            result_data.update({
                "text": "[降级] 语音引擎未加载",
                "language": language,
                "duration": 0,
                "engine": "mock",
                "note": f"[内置降级] 语音识别引擎未加载: {_voice_import_error or '请安装 faster-whisper 或 vosk'}",
            })
            return {
                "success": True,
                "data": result_data,
            }

    elif skill_id == "voice.tts":
        # 语音合成
        text = params.get("text", "")
        voice_type = params.get("voice_type", "warm_female")
        try:
            voice_speed = float(params.get("voice_speed", 1.0))
        except (TypeError, ValueError):
            voice_speed = 1.0
        output_path = params.get("output_path")
        tts_engine = _get_tts_engine()

        if not text:
            return {
                "success": False,
                "data": result_data,
                "error": "缺少 text 参数",
            }

        # 输出路径安全处理
        try:
            if output_path:
                output_path = _safe_output_path(str(output_path), suffix=".wav")
        except ValueError as e:
            return {
                "success": False,
                "data": result_data,
                "error": f"输出路径不安全: {e}",
            }

        if tts_engine:
            try:
                # 更新配置
                tts_engine.update_config(voice_type=voice_type, voice_speed=voice_speed)
                tts_result = await tts_engine.synthesize(str(text), output_path=output_path)

                if tts_result.get("success"):
                    result_data.update({
                        "audio_path": tts_result.get("audio_path"),
                        "audio_format": tts_result.get("audio_format"),
                        "duration": tts_result.get("duration", 0),
                        "engine": tts_result.get("engine", "unknown"),
                        "text": text,
                        "voice": tts_result.get("voice", voice_type),
                        "note": tts_result.get("note", ""),
                    })
                    return {
                        "success": True,
                        "data": result_data,
                    }
                else:
                    result_data.update({
                        "audio_path": None,
                        "audio_format": None,
                        "duration": 0,
                        "engine": tts_result.get("engine", "unknown"),
                        "text": text,
                    })
                    return {
                        "success": False,
                        "data": result_data,
                        "error": tts_result.get("error", "语音合成失败"),
                    }
            except Exception as e:
                result_data.update({
                    "audio_path": None,
                    "audio_format": None,
                    "duration": 0,
                    "engine": "error",
                    "text": text,
                })
                return {
                    "success": False,
                    "data": result_data,
                    "error": f"语音合成异常: {str(e)}",
                }
        else:
            # 引擎不可用，降级返回 mock
            result_data.update({
                "audio_path": None,
                "audio_format": None,
                "duration": len(str(text)) * 0.2,
                "engine": "mock",
                "text": text,
                "note": f"[内置降级] 语音合成引擎未加载: {_voice_import_error or '请安装 edge-tts 或 pyttsx3'}",
            })
            return {
                "success": True,
                "data": result_data,
            }

    elif skill_id == "voice.wake_word":
        # 唤醒词检测
        audio_path = params.get("audio_path", "")
        keywords = params.get("keywords", ["小云", "小汐"])
        language = params.get("language", "zh")
        # 确保 keywords 是列表
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        elif not isinstance(keywords, list):
            keywords = ["小云", "小汐"]

        if not audio_path:
            return {
                "success": False,
                "data": result_data,
                "error": "缺少 audio_path 参数",
            }

        asr_engine = _get_asr_engine()
        if asr_engine:
            try:
                lang_param = language if language and language != "auto" else None
                wake_result = asr_engine.detect_wake_word(
                    str(audio_path),
                    wake_words=keywords,
                    language=lang_param,
                )

                if wake_result.get("success"):
                    result_data.update({
                        "detected": wake_result.get("wake_word_detected", False),
                        "matched_keyword": wake_result.get("matched_word") or "",
                        "confidence": wake_result.get("confidence", 0.0),
                        "transcript": wake_result.get("transcript", ""),
                        "engine": wake_result.get("engine", "unknown"),
                        "language": wake_result.get("language", language),
                        "keywords": keywords,
                        "vad_engine": wake_result.get("vad_engine"),
                        "note": wake_result.get("note", ""),
                    })
                    return {
                        "success": True,
                        "data": result_data,
                    }
                else:
                    result_data.update({
                        "detected": False,
                        "matched_keyword": "",
                        "confidence": 0.0,
                        "transcript": "",
                        "engine": wake_result.get("engine", "unknown"),
                        "keywords": keywords,
                    })
                    return {
                        "success": False,
                        "data": result_data,
                        "error": wake_result.get("error", "唤醒词检测失败"),
                    }
            except Exception as e:
                result_data.update({
                    "detected": False,
                    "matched_keyword": "",
                    "confidence": 0.0,
                    "transcript": "",
                    "engine": "error",
                    "keywords": keywords,
                })
                return {
                    "success": False,
                    "data": result_data,
                    "error": f"唤醒词检测异常: {str(e)}",
                }
        else:
            # 引擎不可用，降级返回 mock
            result_data.update({
                "detected": False,
                "matched_keyword": "",
                "confidence": 0.0,
                "transcript": "",
                "engine": "mock",
                "keywords": keywords,
                "note": f"[内置降级] 语音识别引擎未加载: {_voice_import_error or '无法检测唤醒词'}",
            })
            return {
                "success": True,
                "data": result_data,
            }

    elif skill_id == "voice.record":
        # 录音控制
        try:
            duration = float(params.get("duration", 5.0))
        except (TypeError, ValueError):
            duration = 5.0
        try:
            sample_rate = int(params.get("sample_rate", 16000))
        except (TypeError, ValueError):
            sample_rate = 16000
        output_path = params.get("output_path")

        # 输出路径安全处理
        try:
            output_path = _safe_output_path(
                str(output_path) if output_path else None,
                suffix=".wav"
            )
        except ValueError as e:
            return {
                "success": False,
                "data": result_data,
                "error": f"输出路径不安全: {e}",
            }

        record_success = False
        actual_duration = 0.0
        record_error = None
        record_engine = "mock"

        # 尝试使用 sounddevice 录音
        try:
            import sounddevice as sd  # type: ignore
            import numpy as np  # type: ignore
            import wave as _wave

            frames = int(duration * sample_rate)
            recording = sd.rec(frames, samplerate=sample_rate, channels=1, dtype='int16')
            sd.wait()

            # 保存为 WAV
            with _wave.open(output_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(recording.tobytes())

            record_success = True
            actual_duration = duration
            record_engine = "sounddevice"
        except ImportError:
            # sounddevice 不可用，使用 pyaudio 备用方案
            try:
                import pyaudio  # type: ignore
                import wave as _wave

                p = pyaudio.PyAudio()
                stream = p.open(format=pyaudio.paInt16, channels=1,
                                rate=sample_rate, input=True,
                                frames_per_buffer=1024)
                frames_list = []
                for _ in range(0, int(sample_rate / 1024 * duration)):
                    data = stream.read(1024)
                    frames_list.append(data)
                stream.stop_stream()
                stream.close()
                p.terminate()

                with _wave.open(output_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
                    wf.setframerate(sample_rate)
                    wf.writeframes(b''.join(frames_list))

                record_success = True
                actual_duration = duration
                record_engine = "pyaudio"
            except ImportError:
                # 都不可用，生成一个空的 WAV 文件作为 mock
                try:
                    import wave as _wave
                    import struct
                    with _wave.open(output_path, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        # 写入静音数据（简短的空音频，避免完全空文件）
                        silence_frames = int(min(duration, 1.0) * sample_rate)
                        wf.writeframes(b'\x00\x00' * silence_frames)
                    record_success = True
                    actual_duration = min(duration, 1.0)
                    record_engine = "mock"
                except Exception as mock_e:
                    record_error = f"mock音频生成失败: {str(mock_e)}"
                    output_path = None
            except Exception as pa_e:
                record_error = f"pyaudio录音失败: {str(pa_e)}"
        except Exception as sd_e:
            # sounddevice 运行时错误，尝试 pyaudio
            try:
                import pyaudio  # type: ignore
                import wave as _wave

                p = pyaudio.PyAudio()
                stream = p.open(format=pyaudio.paInt16, channels=1,
                                rate=sample_rate, input=True,
                                frames_per_buffer=1024)
                frames_list = []
                for _ in range(0, int(sample_rate / 1024 * duration)):
                    data = stream.read(1024)
                    frames_list.append(data)
                stream.stop_stream()
                stream.close()
                p.terminate()

                with _wave.open(output_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
                    wf.setframerate(sample_rate)
                    wf.writeframes(b''.join(frames_list))

                record_success = True
                actual_duration = duration
                record_engine = "pyaudio"
            except Exception as pa_e2:
                record_error = f"录音失败: sounddevice({str(sd_e)}), pyaudio({str(pa_e2)})"

        result_data.update({
            "audio_path": output_path if record_success else None,
            "duration": actual_duration,
            "sample_rate": sample_rate,
            "recorded": record_success,
            "engine": record_engine,
            "note": "" if record_success else f"[内置降级] {record_error or '未安装录音库'}",
        })

        if record_success:
            return {
                "success": True,
                "data": result_data,
            }
        else:
            return {
                "success": False,
                "data": result_data,
                "error": record_error or "录音失败",
            }

    return {
        "success": True,
        "data": result_data,
    }


# ============================================================
# M2 技能客户端
# ============================================================

class M2SkillClient:
    """M2 技能集群 HTTP 客户端."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        admin_token: Optional[str] = None,
    ) -> None:
        """初始化 M2 客户端.

        Args:
            base_url: M2 服务地址，默认从环境变量 M7_M2_BASE_URL 读取（兼容 M2_BASE_URL）
            timeout: 请求超时时间（秒）
            admin_token: 管理令牌，默认从 M2_ADMIN_TOKEN 读取
        """
        self.base_url = base_url or os.environ.get("M7_M2_BASE_URL", os.environ.get("M2_BASE_URL", "http://127.0.0.1:8002"))
        self.timeout = timeout
        self.admin_token = admin_token or os.environ.get("M2_ADMIN_TOKEN", "")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端."""
        if self._client is None:
            headers = {}
            if self.admin_token:
                headers["X-M8-Token"] = self.admin_token
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client

    async def health_check(self) -> bool:
        """检查 M2 服务是否可用."""
        try:
            client = await self._get_client()
            response = await client.get("/api/v2/health")
            return response.status_code == 200
        except Exception:
            return False

    async def list_skills(self) -> List[Dict[str, Any]]:
        """获取技能列表."""
        try:
            client = await self._get_client()
            response = await client.get("/api/v2/skills", params={"page_size": 100})
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 20000 or data.get("success"):
                    return data.get("data", {}).get("items", [])
        except Exception:
            pass
        return []

    async def invoke_skill(
        self,
        skill_id: str,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """调用技能.

        Args:
            skill_id: 技能 ID
            action: 动作名称
            params: 参数

        Returns:
            响应数据字典

        Raises:
            Exception: 调用失败时抛出异常
        """
        client = await self._get_client()
        response = await client.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": skill_id,
                "action": action,
                "params": params,
                "agent_id": "m7_workflow_engine",
                "device_type": "desktop",
                "timeout": int(self.timeout),
            },
        )
        return response.json()

    async def close(self) -> None:
        """关闭客户端."""
        if self._client:
            await self._client.aclose()
            self._client = None


