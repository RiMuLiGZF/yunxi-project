"""M7 积木平台 - 高级节点类型实现.

提供控制流节点和数据处理节点的完整实现：
- 循环节点（logic.loop）：for 循环和 while 循环
- 延时节点（control.delay）：等待指定时间
- HTTP 请求节点（skill.http_request）：调用外部 API
- 数据转换节点（data.transform）：JSON 转换/映射
- 子工作流节点（workflow.subflow）：调用另一个工作流

所有节点均作为内置积木实现，与现有 BUILTIN_BLOCKS 体系兼容。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("m7.nodes")


# ============================================================
# 循环节点 (logic.loop)
# ============================================================

async def execute_loop_node(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行循环节点.

    支持两种循环模式：
    1. for 循环：遍历列表或指定次数
    2. while 循环：条件表达式为真时继续

    由于循环节点需要在工作流引擎层面处理子节点迭代，
    本函数仅计算循环配置和元数据，实际迭代由引擎控制。

    Args:
        params: 节点参数
        context: 执行上下文

    Returns:
        循环配置结果
    """
    loop_type = params.get("loop_type", "for")  # for / while
    max_iterations = int(params.get("max_iterations", 100))

    result_data: Dict[str, Any] = {
        "loop_type": loop_type,
        "max_iterations": max_iterations,
        "iterations": 0,
        "items": [],
        "current_index": 0,
        "current_item": None,
    }

    if loop_type == "for":
        # for 循环：支持遍历列表或指定次数
        items = params.get("items", [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except (json.JSONDecodeError, TypeError):
                items = [items]

        count = int(params.get("count", 0))
        if count > 0 and not items:
            # 指定次数的 for 循环
            items = list(range(count))

        result_data["items"] = items
        result_data["total_count"] = len(items)
        result_data["mode"] = "items" if items else "count"

    elif loop_type == "while":
        # while 循环：条件表达式
        condition = params.get("condition", "True")
        result_data["condition"] = condition
        result_data["mode"] = "condition"

    else:
        return {
            "success": False,
            "error": f"不支持的循环类型: {loop_type}",
            "data": result_data,
        }

    return {
        "success": True,
        "data": result_data,
    }


# ============================================================
# 延时节点 (control.delay)
# ============================================================

async def execute_delay_node(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行延时节点.

    支持固定延时和随机延时两种模式。

    Args:
        params: 节点参数
            - duration: 延时秒数（固定模式）
            - min_duration: 最小时延（随机模式）
            - max_duration: 最大时延（随机模式）
            - unit: 时间单位（second/millisecond），默认 second
            - mode: fixed/random，默认 fixed
        context: 执行上下文

    Returns:
        延时结果
    """
    import random

    mode = params.get("mode", "fixed")
    unit = params.get("unit", "second")

    # 计算延时时间（秒）
    if mode == "random":
        min_dur = float(params.get("min_duration", 0))
        max_dur = float(params.get("max_duration", 1))
        duration = random.uniform(min_dur, max_dur)
    else:
        duration = float(params.get("duration", 1))

    # 单位转换
    if unit == "millisecond" or unit == "ms":
        duration = duration / 1000.0

    # 安全限制：最大延时 1 小时
    max_delay = float(params.get("max_delay", 3600))
    if duration > max_delay:
        return {
            "success": False,
            "error": f"延时时间 {duration}s 超过最大限制 {max_delay}s",
            "data": {"requested_duration": duration, "max_delay": max_delay},
        }

    if duration < 0:
        duration = 0

    start_time = time.time()
    await asyncio.sleep(duration)
    actual_duration = time.time() - start_time

    return {
        "success": True,
        "data": {
            "mode": mode,
            "unit": unit,
            "requested_duration": duration,
            "actual_duration": actual_duration,
            "started_at": start_time,
            "finished_at": start_time + actual_duration,
        },
    }


# ============================================================
# HTTP 请求节点 (skill.http_request)
# ============================================================

async def execute_http_request_node(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行 HTTP 请求节点.

    支持 GET/POST/PUT/DELETE/PATCH 等常用方法。

    Args:
        params: 请求参数
            - url: 请求 URL
            - method: HTTP 方法（GET/POST/PUT/DELETE/PATCH）
            - headers: 请求头字典
            - body: 请求体（JSON 或字符串）
            - params: URL 查询参数
            - timeout: 超时时间（秒）
            - follow_redirects: 是否跟随重定向
            - auth: 认证信息 {type: "basic"/"bearer", ...}
        context: 执行上下文

    Returns:
        HTTP 响应结果
    """
    url = params.get("url", "")
    method = (params.get("method", "GET") or "GET").upper()
    headers = params.get("headers", {}) or {}
    query_params = params.get("params", {}) or {}
    body = params.get("body")
    timeout = float(params.get("timeout", 30))
    follow_redirects = bool(params.get("follow_redirects", True))

    if not url:
        return {
            "success": False,
            "error": "缺少 url 参数",
            "data": None,
        }

    # 安全校验：URL 必须是 http/https
    if not (url.startswith("http://") or url.startswith("https://")):
        return {
            "success": False,
            "error": "仅支持 http/https 协议的 URL",
            "data": {"url": url},
        }

    # 处理认证
    auth_config = params.get("auth", {})
    if auth_config:
        auth_type = auth_config.get("type", "")
        if auth_type == "bearer":
            token = auth_config.get("token", "")
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            # httpx 的 basic auth 通过 auth 参数传递
            pass

    auth = None
    if auth_config and auth_config.get("type") == "basic":
        auth = (auth_config.get("username", ""), auth_config.get("password", ""))

    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
            # 构建请求参数
            request_kwargs: Dict[str, Any] = {
                "headers": headers,
                "params": query_params,
            }
            if auth:
                request_kwargs["auth"] = auth

            # 根据方法处理 body
            if method in ("POST", "PUT", "PATCH") and body is not None:
                if isinstance(body, (dict, list)):
                    request_kwargs["json"] = body
                else:
                    request_kwargs["content"] = str(body)
                    if "Content-Type" not in headers:
                        request_kwargs["headers"]["Content-Type"] = "text/plain"

            response = await client.request(method, url, **request_kwargs)

            # 解析响应
            response_data: Dict[str, Any] = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "url": str(response.url),
                "method": method,
                "duration_ms": int((time.time() - start_time) * 1000),
            }

            # 尝试解析 JSON
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    response_data["body"] = response.json()
                    response_data["body_type"] = "json"
                except (json.JSONDecodeError, ValueError):
                    response_data["body"] = response.text
                    response_data["body_type"] = "text"
            else:
                response_data["body"] = response.text
                response_data["body_type"] = "text"

            # 截断过长的响应体
            if isinstance(response_data["body"], str) and len(response_data["body"]) > 100000:
                response_data["body"] = response_data["body"][:100000] + "...[truncated]"
                response_data["body_truncated"] = True

            success = 200 <= response.status_code < 300

            return {
                "success": success,
                "data": response_data,
                "error": None if success else f"HTTP {response.status_code}",
            }

    except httpx.TimeoutException:
        return {
            "success": False,
            "error": f"请求超时（{timeout}秒）",
            "data": {
                "url": url,
                "method": method,
                "duration_ms": int((time.time() - start_time) * 1000),
                "timeout": timeout,
            },
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"HTTP 请求失败: {str(e)}",
            "data": {
                "url": url,
                "method": method,
                "duration_ms": int((time.time() - start_time) * 1000),
            },
        }


# ============================================================
# 数据转换节点 (data.transform)
# ============================================================

async def execute_transform_node(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行数据转换节点.

    支持多种数据转换操作：
    1. 字段映射：将输入字段映射到新字段
    2. JSON 路径提取：使用 JMESPath 风格的路径提取数据
    3. 数组操作：过滤、映射、排序
    4. 格式化：字符串模板格式化

    Args:
        params: 转换参数
            - operation: 操作类型（map/extract/filter/format）
            - mappings: 字段映射规则 {output_field: input_path}
            - expression: 提取/过滤表达式
            - template: 格式化模板
            - input_data: 输入数据（可选，默认从 context 获取）
        context: 执行上下文

    Returns:
        转换结果
    """
    operation = params.get("operation", "map")
    input_data = params.get("input_data", params.get("previous_output", {}))

    if context and isinstance(context, dict):
        # 合并上下文中的前驱输出
        for key, val in context.items():
            if key not in params and key not in ("operation", "mappings", "expression", "template"):
                if input_data is None or isinstance(input_data, dict):
                    if not isinstance(input_data, dict):
                        input_data = {}
                    input_data.setdefault(key, val)

    result_data: Dict[str, Any] = {
        "operation": operation,
        "input": input_data,
    }

    try:
        if operation == "map":
            # 字段映射
            mappings = params.get("mappings", {})
            output: Dict[str, Any] = {}
            for target_field, source_path in mappings.items():
                value = _extract_by_path(input_data, source_path)
                output[target_field] = value
            result_data["output"] = output
            result_data["mapped_fields"] = list(mappings.keys())

        elif operation == "extract":
            # 按路径提取
            expression = params.get("expression", "")
            extracted = _extract_by_path(input_data, expression)
            result_data["output"] = extracted
            result_data["expression"] = expression

        elif operation == "filter":
            # 数组过滤
            items = params.get("items", input_data if isinstance(input_data, list) else [])
            condition = params.get("condition", "")
            filtered = []
            if isinstance(items, list) and condition:
                from .executor import _evaluate_condition
                for item in items:
                    ctx = {"item": item, "index": len(filtered)}
                    if isinstance(item, dict):
                        ctx.update(item)
                    if _evaluate_condition(condition, ctx):
                        filtered.append(item)
            result_data["output"] = filtered
            result_data["original_count"] = len(items) if isinstance(items, list) else 0
            result_data["filtered_count"] = len(filtered)

        elif operation == "format":
            # 字符串模板格式化
            template = params.get("template", "")
            if isinstance(input_data, dict):
                try:
                    formatted = template.format(**input_data)
                except (KeyError, IndexError, ValueError) as e:
                    return {
                        "success": False,
                        "error": f"模板格式化失败: {str(e)}",
                        "data": result_data,
                    }
            else:
                formatted = template.format(input_data)
            result_data["output"] = formatted
            result_data["template"] = template

        elif operation == "sort":
            # 数组排序
            items = params.get("items", input_data if isinstance(input_data, list) else [])
            sort_key = params.get("sort_key", "")
            reverse = bool(params.get("reverse", False))
            sorted_items = list(items) if isinstance(items, list) else []
            if sort_key and sorted_items and isinstance(sorted_items[0], dict):
                sorted_items.sort(key=lambda x: x.get(sort_key, ""), reverse=reverse)
            elif not sort_key and sorted_items:
                sorted_items.sort(reverse=reverse)
            result_data["output"] = sorted_items
            result_data["sort_key"] = sort_key
            result_data["reverse"] = reverse

        else:
            return {
                "success": False,
                "error": f"不支持的转换操作: {operation}",
                "data": result_data,
            }

        return {
            "success": True,
            "data": result_data,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"数据转换失败: {str(e)}",
            "data": result_data,
        }


def _extract_by_path(data: Any, path: str) -> Any:
    """按路径提取数据.

    支持的路径格式：
    - "key" - 顶层字段
    - "key.subkey" - 嵌套字段
    - "key[0]" - 数组索引
    - "key.subkey[1].value" - 混合路径

    Args:
        data: 数据源
        path: 路径字符串

    Returns:
        提取的值，路径不存在返回 None
    """
    if not path:
        return data

    parts = []
    current = ""
    i = 0
    while i < len(path):
        c = path[i]
        if c == ".":
            if current:
                parts.append(("key", current))
                current = ""
        elif c == "[":
            if current:
                parts.append(("key", current))
                current = ""
            # 找到匹配的 ]
            end = path.find("]", i)
            if end == -1:
                break
            index_str = path[i + 1 : end]
            try:
                parts.append(("index", int(index_str)))
            except ValueError:
                parts.append(("key", index_str))
            i = end
        else:
            current += c
        i += 1

    if current:
        parts.append(("key", current))

    result = data
    for part_type, part_value in parts:
        if result is None:
            return None
        if part_type == "key":
            if isinstance(result, dict):
                result = result.get(part_value)
            else:
                return None
        elif part_type == "index":
            if isinstance(result, (list, tuple)) and isinstance(part_value, int):
                if 0 <= part_value < len(result):
                    result = result[part_value]
                else:
                    return None
            else:
                return None

    return result


# ============================================================
# 子工作流节点 (workflow.subflow)
# ============================================================

async def execute_subflow_node(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    engine: Optional[Any] = None,
) -> Dict[str, Any]:
    """执行子工作流节点.

    注意：实际的子工作流执行需要引擎参与，
    本函数提供配置验证和元数据返回，
    真正的执行由 WorkflowEngine 中的子工作流处理逻辑完成。

    Args:
        params: 子工作流参数
            - workflow_id: 要调用的工作流 ID
            - workflow_name: 工作流名称（显示用）
            - input_mapping: 输入映射 {subflow_var: parent_path}
            - output_mapping: 输出映射 {parent_var: subflow_path}
            - inherit_variables: 是否继承父工作流变量
        context: 执行上下文
        engine: 工作流引擎实例（用于实际执行）

    Returns:
        子工作流执行结果
    """
    workflow_id = params.get("workflow_id", "")
    inherit_variables = bool(params.get("inherit_variables", True))

    result_data: Dict[str, Any] = {
        "workflow_id": workflow_id,
        "workflow_name": params.get("workflow_name", ""),
        "inherit_variables": inherit_variables,
        "input_mapping": params.get("input_mapping", {}),
        "output_mapping": params.get("output_mapping", {}),
    }

    if not workflow_id:
        return {
            "success": False,
            "error": "缺少 workflow_id 参数",
            "data": result_data,
        }

    # 如果提供了引擎实例，尝试实际执行
    if engine is not None and hasattr(engine, "run_workflow"):
        try:
            # 构建子工作流的输入
            subflow_input: Dict[str, Any] = {}
            if inherit_variables and context:
                subflow_input.update(context if isinstance(context, dict) else {})

            # 应用输入映射
            input_mapping = params.get("input_mapping", {})
            if input_mapping and isinstance(context, dict):
                for subflow_var, parent_path in input_mapping.items():
                    value = _extract_by_path(context, parent_path)
                    subflow_input[subflow_var] = value

            # 从存储加载子工作流定义
            from .storage import get_storage

            storage = get_storage()
            sub_workflow = storage.get_workflow(workflow_id)
            if not sub_workflow:
                return {
                    "success": False,
                    "error": f"子工作流不存在: {workflow_id}",
                    "data": result_data,
                }

            # 执行子工作流
            sub_result = await engine.run_workflow(
                workflow=sub_workflow,
                input_data=subflow_input,
                triggered_by="subflow",
            )

            result_data["subflow_result"] = sub_result
            result_data["subflow_status"] = sub_result.get("status")
            result_data["subflow_run_id"] = sub_result.get("run_id")

            # 应用输出映射
            output_mapping = params.get("output_mapping", {})
            mapped_output: Dict[str, Any] = {}
            sub_output = sub_result.get("final_output", {})
            if output_mapping and sub_output:
                for parent_var, subflow_path in output_mapping.items():
                    value = _extract_by_path(sub_output, subflow_path)
                    mapped_output[parent_var] = value

            result_data["mapped_output"] = mapped_output

            return {
                "success": sub_result.get("status") == "success",
                "data": result_data,
                "error": sub_result.get("error"),
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"子工作流执行失败: {str(e)}",
                "data": result_data,
            }

    # 没有引擎实例，返回配置信息
    return {
        "success": True,
        "data": result_data,
        "note": "子工作流配置已验证，实际执行需要引擎实例",
    }


# ============================================================
# 高级节点注册表
# ============================================================

ADVANCED_NODES: Dict[str, Dict[str, Any]] = {
    "logic.loop": {
        "name": "循环节点",
        "description": "for/while 循环，支持遍历列表和条件循环",
        "actions": ["execute", "for", "while"],
        "category": "logic",
        "type": "control",
        "icon": "repeat",
    },
    "control.delay": {
        "name": "延时节点",
        "description": "等待指定时间后继续执行，支持固定和随机延时",
        "actions": ["wait"],
        "category": "control",
        "type": "control",
        "icon": "clock",
    },
    "skill.http_request": {
        "name": "HTTP 请求",
        "description": "调用外部 API，支持 GET/POST/PUT/DELETE 等方法",
        "actions": ["request", "get", "post", "put", "delete"],
        "category": "integration",
        "type": "action",
        "icon": "globe",
    },
    "data.transform": {
        "name": "数据转换",
        "description": "JSON 数据转换、字段映射、过滤、排序、格式化",
        "actions": ["transform", "map", "extract", "filter", "format", "sort"],
        "category": "data",
        "type": "transform",
        "icon": "shuffle",
    },
    "workflow.subflow": {
        "name": "子工作流",
        "description": "调用另一个工作流作为子流程",
        "actions": ["invoke", "call"],
        "category": "workflow",
        "type": "subflow",
        "icon": "git-branch",
    },
}


# 高级节点执行函数映射
ADVANCED_NODE_EXECUTORS: Dict[str, Any] = {
    "logic.loop": execute_loop_node,
    "control.delay": execute_delay_node,
    "skill.http_request": execute_http_request_node,
    "data.transform": execute_transform_node,
    "workflow.subflow": execute_subflow_node,
}


async def execute_advanced_node(
    skill_id: str,
    action: str,
    params: Dict[str, Any],
    engine: Optional[Any] = None,
) -> Dict[str, Any]:
    """执行高级节点.

    Args:
        skill_id: 节点类型 ID
        action: 动作名称
        params: 执行参数
        engine: 工作流引擎实例（子工作流节点需要）

    Returns:
        执行结果字典
    """
    executor = ADVANCED_NODE_EXECUTORS.get(skill_id)
    if not executor:
        return {
            "success": False,
            "error": f"未知的高级节点类型: {skill_id}",
        }

    start_time = time.time()
    try:
        if skill_id == "workflow.subflow":
            result = await executor(params, context=params, engine=engine)
        else:
            result = await executor(params, context=params)

        # 添加执行时间
        if isinstance(result.get("data"), dict):
            result["data"]["action"] = action
            result["data"]["executed_at"] = start_time
            result["data"]["duration_ms"] = int((time.time() - start_time) * 1000)

        return result
    except Exception as e:
        return {
            "success": False,
            "error": f"高级节点执行异常: {str(e)}",
            "data": {"skill_id": skill_id, "action": action},
        }


# ============================================================
# 条件节点 (control.condition)
# ============================================================

def evaluate_expression(
    expression: str,
    context: Optional[Dict[str, Any]] = None,
) -> Any:
    """安全地求值表达式.

    使用受限的命名空间进行表达式求值，防止代码注入。

    Args:
        expression: 表达式字符串
        context: 变量上下文

    Returns:
        表达式求值结果，出错返回 None
    """
    if not expression or not isinstance(expression, str):
        return None

    context = context or {}

    # 安全的内置函数白名单
    safe_builtins = {
        "abs": abs,
        "len": len,
        "max": max,
        "min": min,
        "round": round,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "sum": sum,
        "sorted": sorted,
        "range": range,
        "True": True,
        "False": False,
        "None": None,
    }

    try:
        result = eval(
            expression,
            {"__builtins__": safe_builtins},
            context,
        )
        return result
    except Exception:
        return None


async def execute_condition_node(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行条件节点（if/else）.

    基于表达式判断走哪个分支。

    Args:
        params: 节点参数
            - condition: 条件表达式
            - true_branch: 条件为真时的分支节点 ID
            - false_branch: 条件为假时的分支节点 ID
            - true_label: 真分支标签
            - false_label: 假分支标签
        context: 执行上下文

    Returns:
        条件判断结果
    """
    context = context or {}
    condition = params.get("condition", "")
    true_branch = params.get("true_branch", "")
    false_branch = params.get("false_branch", "")
    true_label = params.get("true_label", "是")
    false_label = params.get("false_label", "否")

    if not condition:
        return {
            "success": False,
            "error": "缺少条件表达式",
            "data": {},
        }

    start_time = time.time()

    try:
        condition_result = evaluate_expression(condition, context)
        condition_met = bool(condition_result)

        branch = true_branch if condition_met else false_branch
        branch_label = true_label if condition_met else false_label

        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "data": {
                "condition": condition,
                "condition_result": condition_result,
                "condition_met": condition_met,
                "branch": branch,
                "branch_label": branch_label,
                "true_branch": true_branch,
                "false_branch": false_branch,
                "duration_ms": duration_ms,
            },
            "branch": branch,
            "condition_met": condition_met,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"条件判断异常: {str(e)}",
            "data": {"condition": condition},
        }


# 更新高级节点映射
ADVANCED_NODE_EXECUTORS["control.condition"] = execute_condition_node


# ============================================================
# 同步版本的节点执行函数（用于测试）
# ============================================================

def execute_condition_node_sync(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """条件节点的同步版本（用于测试）."""
    import asyncio
    return asyncio.run(execute_condition_node(params, context))


def execute_loop_node_sync(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """循环节点的同步版本（用于测试）."""
    import asyncio
    return asyncio.run(execute_loop_node(params, context))


def execute_delay_node_sync(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """延时节点的同步版本（用于测试）."""
    import asyncio
    return asyncio.run(execute_delay_node(params, context))


def execute_http_node_sync(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """HTTP 请求节点的同步版本（用于测试）."""
    import asyncio
    return asyncio.run(execute_http_request_node(params, context))


def execute_data_transform_node_sync(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """数据转换节点的同步版本（用于测试）."""
    import asyncio
    return asyncio.run(execute_transform_node(params, context))


def execute_subworkflow_node_sync(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """子工作流节点的同步版本（用于测试）."""
    import asyncio
    return asyncio.run(execute_subflow_node(params, context))
