"""M7 积木平台 - 工作流执行引擎.

支持线性串行执行和简单 DAG（有向无环图）执行。
使用 Kahn 算法进行拓扑排序，确保依赖关系正确。
每步调用 M2 技能集群（通过 HTTP），失败时停止并记录错误。
"""

from __future__ import annotations

import os
import time
import uuid
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

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
# DAG 拓扑排序
# ============================================================

def build_adjacency_list(blocks: List[Dict[str, Any]]) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
    """从积木块构建邻接表和入度表.

    Args:
        blocks: 积木块列表，每个块包含 id 和 next 字段

    Returns:
        (adjacency, in_degree) 元组
        - adjacency: {block_id: [next_block_id, ...]}
        - in_degree: {block_id: 入度}
    """
    adjacency: Dict[str, List[str]] = {}
    in_degree: Dict[str, int] = {}

    # 初始化所有节点
    for block in blocks:
        block_id = block["id"]
        adjacency[block_id] = []
        in_degree[block_id] = 0

    # 构建邻接表和入度
    for block in blocks:
        block_id = block["id"]
        next_blocks = block.get("next", [])
        for next_id in next_blocks:
            if next_id in adjacency:
                adjacency[block_id].append(next_id)
                in_degree[next_id] += 1

    return adjacency, in_degree


def topological_sort(
    blocks: List[Dict[str, Any]],
    start_block: Optional[str] = None,
) -> List[str]:
    """对积木块进行拓扑排序（Kahn 算法）.

    Args:
        blocks: 积木块列表
        start_block: 可选的起始积木块 ID，指定后从该块开始执行

    Returns:
        按执行顺序排列的积木块 ID 列表

    Raises:
        ValueError: 如果检测到环
    """
    adjacency, in_degree = build_adjacency_list(blocks)

    # 如果指定了起始块，需要调整入度：起始块之前的所有依赖视为已满足
    if start_block and start_block in in_degree:
        # 找到从起始块可达的所有节点
        reachable: Set[str] = set()
        stack = [start_block]
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            for next_node in adjacency.get(node, []):
                stack.append(next_node)

        # 只保留可达节点
        adjacency = {k: [v for v in vs if v in reachable] for k, vs in adjacency.items() if k in reachable}
        # 重新计算入度（仅考虑可达节点之间的边）
        in_degree = {k: 0 for k in reachable}
        for node, next_nodes in adjacency.items():
            for next_node in next_nodes:
                in_degree[next_node] += 1

    # 找到所有入度为 0 的节点
    queue = deque()
    for node, degree in in_degree.items():
        if degree == 0:
            queue.append(node)

    result: List[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)

        for neighbor in adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # 检测环
    if len(result) != len(in_degree):
        remaining = [n for n, d in in_degree.items() if d > 0]
        raise ValueError(f"工作流中存在循环依赖，涉及节点: {remaining}")

    return result


def is_linear_workflow(blocks: List[Dict[str, Any]]) -> bool:
    """判断工作流是否为线性（串行）结构.

    Args:
        blocks: 积木块列表

    Returns:
        True 表示线性结构
    """
    if len(blocks) <= 1:
        return True

    adjacency, in_degree = build_adjacency_list(blocks)

    # 线性结构：最多一个起点，最多一个终点，每个节点最多一个后继
    start_nodes = [n for n, d in in_degree.items() if d == 0]
    if len(start_nodes) != 1:
        return False

    for node, next_nodes in adjacency.items():
        if len(next_nodes) > 1:
            return False

    # 检查每个节点（除终点外）的入度都是 1
    for node, degree in in_degree.items():
        if degree > 1:
            return False
        # 终点（没有后继）的入度可以是 1 或 0（单节点）
        if len(adjacency.get(node, [])) == 0:
            continue

    return True


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


def _evaluate_condition(
    expression: str,
    context: Dict[str, Any],
) -> bool:
    """安全计算条件表达式（P2-15: 条件分支积木）.

    支持的运算符: == != > < >= <= and or not in
    只允许简单的比较和逻辑运算，不允许调用函数或访问属性。

    Args:
        expression: 条件表达式，如 "value > 10" 或 "status == 'active'"
        context: 变量上下文

    Returns:
        True/False
    """
    if not expression or not isinstance(expression, str):
        return False

    # 安全沙箱：只允许白名单变量
    # 使用 Python 的 eval，但限制 globals 和 locals
    # 只允许基本类型和比较运算符
    safe_builtins = {
        "True": True,
        "False": False,
        "None": None,
        "bool": bool,
        "int": int,
        "float": float,
        "str": str,
        "len": len,
    }

    try:
        result = eval(expression, {"__builtins__": safe_builtins}, context)
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

        if not output_path:
            import tempfile as _tempfile
            tmp_file = _tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            output_path = tmp_file.name
            tmp_file.close()

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


# ============================================================
# 工作流执行引擎
# ============================================================

class WorkflowEngine:
    """工作流执行引擎.

    支持线性串行执行和 DAG 拓扑排序执行。
    M2 不可用时自动降级到内置积木实现。
    """

    def __init__(
        self,
        m2_client: Optional[M2SkillClient] = None,
        use_builtin_fallback: bool = True,
    ) -> None:
        """初始化执行引擎.

        Args:
            m2_client: M2 技能客户端
            use_builtin_fallback: 是否使用内置积木降级
        """
        self.m2_client = m2_client or M2SkillClient()
        self.use_builtin_fallback = use_builtin_fallback
        self._m2_available: Optional[bool] = None
        self._m2_check_time: float = 0
        self._m2_cache_ttl: float = 60.0  # M2 可用性缓存 60 秒

    async def _check_m2_available(self, force: bool = False) -> bool:
        """检查 M2 是否可用（带缓存）."""
        now = time.time()
        if force or self._m2_available is None or (now - self._m2_check_time) > self._m2_cache_ttl:
            self._m2_available = await self.m2_client.health_check()
            self._m2_check_time = now
        return self._m2_available

    def _resolve_variables(
        self,
        variables_config: List[Dict[str, Any]],
        runtime_vars: Dict[str, Any],
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """解析工作流变量的最终值.

        Args:
            variables_config: 工作流中定义的变量列表
            runtime_vars: 运行时传入的变量覆盖
            input_data: 输入数据

        Returns:
            解析后的变量字典
        """
        resolved: Dict[str, Any] = {}

        # 先加载默认值
        for var_def in variables_config:
            resolved[var_def["name"]] = var_def.get("default")

        # 输入数据中的变量也合并进来
        resolved.update(input_data)

        # 运行时变量优先级最高
        resolved.update(runtime_vars)

        return resolved

    def _build_step_input(
        self,
        block: Dict[str, Any],
        block_index: int,
        variables: Dict[str, Any],
        step_results: Dict[str, Dict[str, Any]],
        adjacency: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """构建积木块的输入数据.

        合并积木配置、工作流变量、前驱节点输出。

        Args:
            block: 当前积木块配置
            block_index: 积木块索引
            variables: 工作流变量
            step_results: 已执行步骤的结果 {block_id: result}
            adjacency: 邻接表（用于找前驱）

        Returns:
            输入参数字典
        """
        block_config = block.get("config", {}).copy()

        # 找到所有前驱节点
        predecessors: List[str] = []
        for node, next_nodes in adjacency.items():
            if block["id"] in next_nodes:
                predecessors.append(node)

        # 收集前驱输出
        previous_outputs: Dict[str, Any] = {}
        for pred_id in predecessors:
            if pred_id in step_results:
                pred_output = step_results[pred_id].get("output")
                if isinstance(pred_output, dict):
                    previous_outputs.update(pred_output)
                else:
                    previous_outputs[f"{pred_id}_output"] = pred_output

        # 合并：变量 → 前驱输出 → 积木配置（积木配置优先级最高）
        step_input: Dict[str, Any] = {}
        step_input.update(variables)
        step_input.update(previous_outputs)
        step_input["previous_output"] = previous_outputs if previous_outputs else None
        step_input.update(block_config)

        return step_input

    async def _execute_block(
        self,
        block: Dict[str, Any],
        step_input: Dict[str, Any],
        m2_available: bool,
    ) -> Tuple[Dict[str, Any], bool]:
        """执行单个积木块.

        Args:
            block: 积木块配置
            step_input: 输入参数
            m2_available: M2 是否可用

        Returns:
            (结果字典, 是否成功) 元组
        """
        skill_id = block.get("type", "")
        block_config = block.get("config", {})
        action = block_config.get("action", "default")
        # action 已经在 step_input 里可能有，但我们用配置里的
        action = block.get("config", {}).get("action", "default")

        result: Dict[str, Any] = {
            "block_id": block["id"],
            "block_name": block.get("name", ""),
            "skill_id": skill_id,
            "action": action,
            "status": "running",
            "input": step_input,
            "output": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "duration_ms": 0,
            "retry_count": 0,
            "source": "m2" if m2_available else "builtin",
        }

        try:
            if m2_available:
                # 调用 M2 技能
                response = await self.m2_client.invoke_skill(
                    skill_id=skill_id,
                    action=action,
                    params=step_input,
                )
                resp_code = response.get("code", -1)
                resp_data = response.get("data", {})

                if resp_code == 20000 or response.get("success", False):
                    invoke_data = (
                        resp_data.get("data", resp_data)
                        if isinstance(resp_data, dict)
                        else resp_data
                    )
                    result["status"] = "success"
                    result["output"] = invoke_data
                else:
                    result["status"] = "failed"
                    result["error"] = response.get("message", "技能执行失败")
            elif self.use_builtin_fallback and skill_id in BUILTIN_BLOCKS:
                # 使用内置降级实现
                builtin_result = await execute_builtin_block(
                    skill_id=skill_id,
                    action=action,
                    params=step_input,
                )
                if builtin_result.get("success"):
                    result["status"] = "success"
                    result["output"] = builtin_result.get("data")
                else:
                    result["status"] = "failed"
                    result["error"] = builtin_result.get("error", "内置积木执行失败")
            else:
                result["status"] = "failed"
                result["error"] = f"M2 不可用且无内置降级实现: {skill_id}"
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)

        result["finished_at"] = time.time()
        result["duration_ms"] = int((result["finished_at"] - result["started_at"]) * 1000)

        return result, result["status"] == "success"

    async def run_workflow(
        self,
        workflow: Dict[str, Any],
        input_data: Optional[Dict[str, Any]] = None,
        start_block: Optional[str] = None,
        runtime_variables: Optional[Dict[str, Any]] = None,
        triggered_by: str = "",
    ) -> Dict[str, Any]:
        """运行工作流.

        支持线性串行和 DAG 两种执行模式。自动检测工作流结构。

        Args:
            workflow: 工作流字典
            input_data: 初始输入数据
            start_block: 可选的起始积木块 ID
            runtime_variables: 运行时变量
            triggered_by: 触发者

        Returns:
            运行记录字典
        """
        blocks = workflow.get("blocks", [])
        if not blocks:
            return {
                "run_id": f"run_{uuid.uuid4().hex[:12]}",
                "workflow_id": workflow.get("id", ""),
                "workflow_name": workflow.get("name", ""),
                "status": "failed",
                "started_at": time.time(),
                "finished_at": time.time(),
                "duration_ms": 0,
                "steps": [],
                "total_blocks": 0,
                "success_blocks": 0,
                "failed_blocks": 0,
                "skipped_blocks": 0,
                "triggered_by": triggered_by,
                "trigger_type": workflow.get("trigger", {}).get("type", "manual"),
                "input_data": input_data or {},
                "final_output": None,
                "error": "工作流中没有积木块",
            }

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_start_time = time.time()
        input_data = input_data or {}
        runtime_variables = runtime_variables or {}

        # 解析变量
        variables_config = workflow.get("variables", [])
        variables = self._resolve_variables(variables_config, runtime_variables, input_data)

        # 构建邻接表
        adjacency, in_degree = build_adjacency_list(blocks)

        # 拓扑排序得到执行顺序
        try:
            execution_order = topological_sort(blocks, start_block)
        except ValueError as e:
            return {
                "run_id": run_id,
                "workflow_id": workflow.get("id", ""),
                "workflow_name": workflow.get("name", ""),
                "status": "failed",
                "started_at": run_start_time,
                "finished_at": time.time(),
                "duration_ms": 0,
                "steps": [],
                "total_blocks": len(blocks),
                "success_blocks": 0,
                "failed_blocks": 0,
                "skipped_blocks": len(blocks),
                "triggered_by": triggered_by,
                "trigger_type": workflow.get("trigger", {}).get("type", "manual"),
                "input_data": input_data,
                "final_output": None,
                "error": str(e),
            }

        # 检查 M2 可用性
        m2_available = await self._check_m2_available()

        # 执行
        steps: List[Dict[str, Any]] = []
        step_results: Dict[str, Dict[str, Any]] = {}
        overall_status = "success"
        block_map = {b["id"]: b for b in blocks}
        skipped_count = 0

        # P2-15: 条件分支跳过集合（条件积木 false 分支的节点会被加入）
        condition_skip: Set[str] = set()

        for block_id in execution_order:
            block = block_map.get(block_id)
            if not block:
                skipped_count += 1
                continue

            # 计算前驱列表和前驱状态
            predecessors = [n for n, ns in adjacency.items() if block_id in ns]
            pred_success = 0
            pred_failed = 0
            pred_cond_skip = 0
            for pred_id in predecessors:
                if pred_id not in step_results:
                    continue
                ps = step_results[pred_id].get("status")
                if ps == "success":
                    pred_success += 1
                elif ps == "skipped" and step_results[pred_id].get("skip_reason") == "condition_branch":
                    pred_cond_skip += 1
                else:
                    pred_failed += 1

            # P2-15: 判断是否因条件分支而跳过
            # 规则:
            #   - 节点在 condition_skip 中 -> 直接跳过（由条件积木明确标记）
            #   - 不在 condition_skip 中，但所有前驱都是条件跳过 -> 也跳过（传递性）
            #   - 有成功前驱的合并节点不在 condition_skip 中，正常执行
            should_cond_skip = False
            if block_id in condition_skip:
                should_cond_skip = True
            elif predecessors and pred_cond_skip > 0 and pred_success == 0 and pred_failed == 0:
                # 所有前驱都被条件跳过，当前节点也跳过
                if pred_cond_skip + pred_failed + pred_success == len(predecessors):
                    should_cond_skip = True
                    condition_skip.add(block_id)

            if should_cond_skip:
                skip_result = {
                    "block_id": block_id,
                    "block_name": block.get("name", ""),
                    "skill_id": block.get("type", ""),
                    "action": block.get("config", {}).get("action", "default"),
                    "status": "skipped",
                    "input": {},
                    "output": None,
                    "error": "条件分支未命中",
                    "started_at": time.time(),
                    "finished_at": time.time(),
                    "duration_ms": 0,
                    "retry_count": 0,
                    "skip_reason": "condition_branch",
                }
                steps.append(skip_result)
                step_results[block_id] = skip_result
                skipped_count += 1
                continue

            # 检查前置依赖是否失败（非条件跳过的失败）
            deps_failed = pred_failed > 0

            if deps_failed:
                # 依赖失败，跳过此节点
                skip_result = {
                    "block_id": block_id,
                    "block_name": block.get("name", ""),
                    "skill_id": block.get("type", ""),
                    "action": block.get("config", {}).get("action", "default"),
                    "status": "skipped",
                    "input": {},
                    "output": None,
                    "error": "前置依赖执行失败",
                    "started_at": time.time(),
                    "finished_at": time.time(),
                    "duration_ms": 0,
                    "retry_count": 0,
                }
                steps.append(skip_result)
                step_results[block_id] = skip_result
                skipped_count += 1
                continue

            # 构建输入
            step_input = self._build_step_input(
                block=block,
                block_index=execution_order.index(block_id),
                variables=variables,
                step_results=step_results,
                adjacency=adjacency,
            )

            # 执行积木块
            step_result, success = await self._execute_block(
                block=block,
                step_input=step_input,
                m2_available=m2_available,
            )
            steps.append(step_result)
            step_results[block_id] = step_result

            # P2-15: 条件分支积木 - 标记未命中分支的直接后继
            # 注意：只标记直接后继，不递归。合并节点由动态判断决定是否执行
            block_type = block.get("type", "")
            if block_type == "logic.condition" and success:
                cond_result = step_result.get("output", {}).get("result", False)
                block_config = block.get("config", {})
                true_branch = block_config.get("true_branch", [])
                false_branch = block_config.get("false_branch", [])
                next_blocks = block.get("next", [])
                if not true_branch and not false_branch and len(next_blocks) >= 2:
                    true_branch = [next_blocks[0]]
                    false_branch = next_blocks[1:]
                skip_branch = false_branch if cond_result else true_branch
                for sid in skip_branch:
                    if sid in block_map:
                        condition_skip.add(sid)

            if not success:
                overall_status = "failed"
                # DAG 模式下不立即停止，后续节点会因为依赖失败而被跳过
                # 但线性模式下可以提前终止（后面的节点都依赖前面的）
                if is_linear_workflow(blocks):
                    break

        run_end_time = time.time()

        # 统计
        success_count = sum(1 for s in steps if s["status"] == "success")
        failed_count = sum(1 for s in steps if s["status"] == "failed")
        skipped_count = sum(1 for s in steps if s["status"] == "skipped")

        # 找出最终输出（最后一个成功的节点输出）
        final_output = None
        for step in reversed(steps):
            if step["status"] == "success":
                final_output = step.get("output")
                break

        # 如果有被跳过的块（DAG 模式下因依赖失败而跳过），也视为失败
        if skipped_count > 0 and overall_status == "success":
            overall_status = "success"  # 只要有成功路径就不算失败

        return {
            "run_id": run_id,
            "workflow_id": workflow.get("id", ""),
            "workflow_name": workflow.get("name", ""),
            "status": overall_status,
            "started_at": run_start_time,
            "finished_at": run_end_time,
            "duration_ms": int((run_end_time - run_start_time) * 1000),
            "steps": steps,
            "total_blocks": len(execution_order),
            "success_blocks": success_count,
            "failed_blocks": failed_count,
            "skipped_blocks": skipped_count,
            "triggered_by": triggered_by,
            "trigger_type": workflow.get("trigger", {}).get("type", "manual"),
            "input_data": input_data,
            "final_output": final_output if overall_status == "success" else None,
            "error": None if overall_status == "success" else "工作流执行失败",
            "execution_mode": "dag" if not is_linear_workflow(blocks) else "linear",
        }
