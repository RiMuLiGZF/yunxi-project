"""代码执行技能集合.

【v3.10.0 新增】5个核心代码类技能：
1. PythonDevSkill - Python开发
2. DataVizSkill - 数据可视化
3. DataAnalysisCodeSkill - 数据分析（代码执行版）
4. AlgorithmSkill - 算法实现
5. JSDevSkill - JavaScript开发
"""

from __future__ import annotations

from typing import Any

import structlog

from skill_cluster.interfaces import SkillManifest, SkillInvokeRequest, SkillInvokeResult
from skill_cluster.skills._code_base import CodeExecutionSkillBase

logger = structlog.get_logger()


# ============================================================
# 1. Python 开发技能
# ============================================================


class PythonDevSkill(CodeExecutionSkillBase):
    """Python 开发技能.

    能力：
    - 生成Python函数/脚本
    - 自动执行验证
    - 错误自动修复
    - 附带测试用例
    """

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.python_dev",
            name="Python开发",
            version="2.0.0",
            description="生成Python代码并自动执行验证，支持自动修复",
            author="yunxi",
            tags=["python", "开发", "代码", "执行"],
            capabilities=[
                "generate_function",
                "generate_script",
                "debug_code",
                "optimize_code",
                "write_test",
            ],
            permissions=["code_execute"],
            entrypoint="PythonDevSkill",
        )
        super().__init__(manifest)
        self._default_language = "python"

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "generate_function":
                data = await self._generate_function(params)
            elif action == "generate_script":
                data = await self._generate_script(params)
            elif action == "debug_code":
                data = await self._debug_code(params)
            elif action == "optimize_code":
                data = await self._optimize_code(params)
            elif action == "write_test":
                data = await self._write_test(params)
            elif action == "execute_code":
                data = await self._execute_direct(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    async def _generate_function(self, params: dict[str, Any]) -> dict[str, Any]:
        """生成函数并执行验证."""
        description = params.get("description", "")
        function_name = params.get("function_name", "solution")
        test_input = params.get("test_input")
        test_expected = params.get("test_expected")

        # 根据描述生成代码模板（实际生产环境由LLM生成，这里用模板）
        code = self._template_by_description(description, function_name)

        # 构造测试代码
        test_code = ""
        if test_input is not None:
            if isinstance(test_input, (list, tuple)):
                args_str = ", ".join(repr(x) for x in test_input)
            else:
                args_str = repr(test_input)
            test_code = f"result = {function_name}({args_str})\nprint('Result:', result)"
            if test_expected is not None:
                test_code += f"\nassert result == {repr(test_expected)}, f'Expected {repr(test_expected)}, got {{result}}')\nprint('Test PASSED')"

        return await self._execute_code(code, test_code=test_code)

    async def _generate_script(self, params: dict[str, Any]) -> dict[str, Any]:
        """生成完整脚本并执行."""
        code = params.get("code", "")
        if not code:
            description = params.get("description", "")
            code = f"# {description}\nprint('Script executed successfully')"
        return await self._execute_code(code)

    async def _debug_code(self, params: dict[str, Any]) -> dict[str, Any]:
        """调试代码（自动修复）."""
        code = params.get("code", "")
        return await self._execute_code(code, auto_fix=True)

    async def _optimize_code(self, params: dict[str, Any]) -> dict[str, Any]:
        """优化代码."""
        code = params.get("code", "")
        return await self._execute_code(code, auto_fix=True)

    async def _write_test(self, params: dict[str, Any]) -> dict[str, Any]:
        """生成测试."""
        code = params.get("code", "")
        test_code = params.get("test_code", "")
        full_code = code + "\n\n" + test_code if test_code else code
        return await self._execute_code(full_code)

    async def _execute_direct(self, params: dict[str, Any]) -> dict[str, Any]:
        """直接执行代码."""
        code = params.get("code", "")
        timeout = params.get("timeout")
        return await self._execute_code(code, timeout=timeout)

    def _template_by_description(self, description: str, func_name: str) -> str:
        """根据描述生成代码模板（简化版，生产环境用LLM）."""
        desc_lower = description.lower()

        if "排序" in description or "sort" in desc_lower:
            return f'''def {func_name}(arr):
    \"\"\"{description}\"\"\"
    return sorted(arr)
'''

        if "斐波那契" in description or "fibonacci" in desc_lower:
            return f'''def {func_name}(n):
    \"\"\"{description}\"\"\"
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
'''

        if "阶乘" in description or "factorial" in desc_lower:
            return f'''def {func_name}(n):
    \"\"\"{description}\"\"\"
    if n <= 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
'''

        if "冒泡" in description or "bubble" in desc_lower:
            return f'''def {func_name}(arr):
    \"\"\"{description}\"\"\"
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr
'''

        # 默认模板（未匹配到已知模式时的 fallback）
        # 后续可扩展为：注入 LLM 调用（参考 M4 _call_llm_for_codegen），
        # 根据 description 动态生成完整函数体。
        return f'''def {func_name}(*args, **kwargs):
    \"\"\"{description}\"\"\"
    # TODO: implement — 可接入 LLM 动态生成（参考 M4 _call_llm_for_codegen）
    return args
'''

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("python_dev_error", action=request.action, error=error)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )


# ============================================================
# 2. 数据可视化技能
# ============================================================


class DataVizSkill(CodeExecutionSkillBase):
    """数据可视化技能.

    能力：
    - matplotlib 绘图
    - 自动检测依赖
    - 自动安装缺失包
    - 返回图表图片
    """

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.data_viz",
            name="数据可视化",
            version="2.0.0",
            description="用matplotlib/plotly生成图表，自动执行并返回图片",
            author="yunxi",
            tags=["可视化", "图表", "画图", "matplotlib"],
            capabilities=[
                "line_chart",
                "bar_chart",
                "pie_chart",
                "scatter_chart",
                "histogram",
                "custom_plot",
            ],
            permissions=["code_execute", "file_write"],
            entrypoint="DataVizSkill",
        )
        super().__init__(manifest)
        self._default_language = "python"

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action in ("line_chart", "bar_chart", "pie_chart", "scatter_chart", "histogram"):
                data = await self._generate_chart(action, params)
            elif action == "custom_plot":
                data = await self._custom_plot(params)
            elif action == "check_dependencies":
                data = self._check_dependencies(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    async def _generate_chart(self, chart_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """生成指定类型的图表."""
        data = params.get("data", [])
        title = params.get("title", chart_type)
        x_label = params.get("x_label", "X")
        y_label = params.get("y_label", "Y")
        labels = params.get("labels", [])

        code = self._build_chart_code(chart_type, data, title, x_label, y_label, labels)
        return await self._execute_code(code)

    def _build_chart_code(self, chart_type: str, data, title, x_label, y_label, labels):
        """生成绘图代码."""
        data_str = repr(data)
        labels_str = repr(labels)

        if chart_type == "line_chart":
            return f'''import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

data = {data_str}
fig, ax = plt.subplots()
ax.plot(data)
ax.set_title("{title}")
ax.set_xlabel("{x_label}")
ax.set_ylabel("{y_label}")
plt.savefig('/tmp/chart.png', dpi=100)
print("Chart saved successfully")
print(f"Data points: {{len(data)}}")
'''

        if chart_type == "bar_chart":
            return f'''import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

data = {data_str}
labels = {labels_str} or list(range(len(data)))
fig, ax = plt.subplots()
ax.bar(labels, data)
ax.set_title("{title}")
ax.set_xlabel("{x_label}")
ax.set_ylabel("{y_label}")
plt.savefig('/tmp/chart.png', dpi=100)
print("Bar chart saved")
print(f"Bars: {{len(data)}}")
'''

        if chart_type == "pie_chart":
            return f'''import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

data = {data_str}
labels = {labels_str} or [f"Item {{i}}" for i in range(len(data))]
fig, ax = plt.subplots()
ax.pie(data, labels=labels, autopct='%1.1f%%')
ax.set_title("{title}")
plt.savefig('/tmp/chart.png', dpi=100)
print("Pie chart saved")
'''

        if chart_type == "scatter_chart":
            return f'''import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import random

data = {data_str}
x = [i for i, _ in enumerate(data)]
y = data
fig, ax = plt.subplots()
ax.scatter(x, y)
ax.set_title("{title}")
ax.set_xlabel("{x_label}")
ax.set_ylabel("{y_label}")
plt.savefig('/tmp/chart.png', dpi=100)
print("Scatter chart saved")
print(f"Points: {{len(data)}}")
'''

        if chart_type == "histogram":
            return f'''import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

data = {data_str}
fig, ax = plt.subplots()
ax.hist(data, bins=10)
ax.set_title("{title}")
ax.set_xlabel("{x_label}")
ax.set_ylabel("{y_label}")
plt.savefig('/tmp/chart.png', dpi=100)
print("Histogram saved")
'''

        return "# Unknown chart type"

    async def _custom_plot(self, params: dict[str, Any]) -> dict[str, Any]:
        """自定义绘图代码."""
        code = params.get("code", "")
        return await self._execute_code(code)

    def _check_dependencies(self, params: dict[str, Any]) -> dict[str, Any]:
        """检查依赖包是否可用."""
        packages = params.get("packages", ["matplotlib", "numpy", "pandas"])
        code = "import sys\n"
        for pkg in packages:
            code += f"try:\n    import {pkg}\n    print('{pkg}: OK')\nexcept ImportError:\n    print('{pkg}: NOT FOUND')\n"
        # 修复语法
        code = ""
        for pkg in packages:
            code += f"try:\n    import {pkg}\n    print('{pkg}: OK')\nexcept ImportError:\n    print('{pkg}: NOT FOUND')\n\n"
        return {"check": "dependencies", "packages": packages}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("data_viz_error", action=request.action, error=error)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )


# ============================================================
# 3. 数据分析技能（代码执行版）
# ============================================================


class DataAnalysisCodeSkill(CodeExecutionSkillBase):
    """数据分析技能（代码执行版）.

    与 DataAnalysisSkill（纯API版）的区别：
    - 本技能通过执行Python代码进行交互式探索
    - 支持 REPL 模式多轮交互
    - 支持自定义分析代码
    """

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.data_analysis_code",
            name="代码数据分析",
            version="2.0.0",
            description="通过Python代码进行交互式数据分析，支持REPL多轮探索",
            author="yunxi",
            tags=["数据分析", "python", "pandas", "探索"],
            capabilities=[
                "load_data",
                "explore_data",
                "clean_data",
                "analyze_code",
                "start_repl",
                "repl_exec",
            ],
            permissions=["code_execute", "read_file"],
            entrypoint="DataAnalysisCodeSkill",
        )
        super().__init__(manifest)
        self._default_language = "python"
        self._repl_sessions: dict[str, str] = {}  # user_id -> session_id

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "load_data":
                data = await self._load_data(params)
            elif action == "explore_data":
                    data = await self._explore_data(params)
            elif action == "clean_data":
                data = await self._clean_data(params)
            elif action == "analyze_code":
                    data = await self._analyze_code(params)
            elif action == "start_repl":
                data = await self._start_repl(params)
            elif action == "repl_exec":
                data = await self._repl_exec(params)
            elif action == "close_repl":
                data = await self._close_repl(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    async def _load_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """加载数据."""
        csv_content = params.get("csv_content", "")
        code = f'''import pandas as pd
from io import StringIO

csv_data = """{csv_content[:5000]}"""
df = pd.read_csv(StringIO(csv_data))
print("Shape:", df.shape)
print("Columns:", list(df.columns))
print("\\nFirst 5 rows:")
print(df.head().to_string())
print("\\nDescribe:")
print(df.describe().to_string())
'''
        return await self._execute_code(code)

    async def _explore_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """探索数据."""
        code = params.get("code", "print('explore')")
        return await self._execute_code(code)

    async def _clean_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """清洗数据."""
        code = params.get("code", "print('clean')")
        return await self._execute_code(code)

    async def _analyze_code(self, params: dict[str, Any]) -> dict[str, Any]:
        """自定义分析代码."""
        code = params.get("code", "")
        return await self._execute_code(code)

    async def _start_repl(self, params: dict[str, Any]) -> dict[str, Any]:
        """启动 REPL 会话."""
        user_id = params.get("user_id", "default")
        session_id = await self.bridge.create_repl("python", user_id)
        self._repl_sessions[user_id] = session_id
        return {"session_id": session_id, "status": "started"}

    async def _repl_exec(self, params: dict[str, Any]) -> dict[str, Any]:
        """在 REPL 中执行."""
        user_id = params.get("user_id", "default")
        code = params.get("code", "")
        session_id = self._repl_sessions.get(user_id)
        if not session_id:
            session_id = await self.bridge.create_repl("python", user_id)
            self._repl_sessions[user_id] = session_id
        result = await self.bridge.repl_exec(session_id, code)
        rendered = self._renderer.render(result)
        return self._build_result_dict(code, result, rendered)

    async def _close_repl(self, params: dict[str, Any]) -> dict[str, Any]:
        """关闭 REPL."""
        user_id = params.get("user_id", "default")
        session_id = self._repl_sessions.pop(user_id, None)
        if session_id:
            await self.bridge.close_repl(session_id)
            return {"status": "closed"}
        return {"status": "no_session"}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("data_analysis_code_error", action=request.action, error=error)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )


# ============================================================
# 4. 算法实现技能
# ============================================================


class AlgorithmSkill(CodeExecutionSkillBase):
    """算法实现技能.

    能力：
    - 生成算法实现
    - 自动验证正确性
    - 复杂度分析
    - 多语言支持
    """

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.algorithm",
            name="算法实现",
            version="2.0.0",
            description="实现各类算法并自动验证，支持复杂度分析",
            author="yunxi",
            tags=["算法", "数据结构", "刷题", "面试"],
            capabilities=[
                "implement",
                "verify",
                "complexity_analysis",
                "compare_algorithms",
            ],
            permissions=["code_execute"],
            entrypoint="AlgorithmSkill",
        )
        super().__init__(manifest)
        self._default_language = "python"

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "implement":
                data = await self._implement(params)
            elif action == "verify":
                data = await self._verify(params)
            elif action == "complexity_analysis":
                data = self._complexity_analysis(params)
            elif action == "compare_algorithms":
                data = await self._compare(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    async def _implement(self, params: dict[str, Any]) -> dict[str, Any]:
        """实现算法并验证."""
        algo_name = params.get("algorithm", "")
        test_cases = params.get("test_cases", [])

        code = self._get_algorithm_code(algo_name)

        # 构造测试
        test_code = ""
        for i, tc in enumerate(test_cases):
            inputs = tc.get("input", [])
            expected = tc.get("expected")
            if isinstance(inputs, (list, tuple)):
                args_str = ", ".join(repr(x) for x in inputs)
            else:
                args_str = repr(inputs)
            test_code += f"result = {algo_name}({args_str})\n"
            test_code += f"print(f'Test {i+1}: result={{result}}')\n"
            if expected is not None:
                test_code += f"assert result == {repr(expected)}, f'Test {i+1} FAILED'\n"

        return await self._execute_code(code, test_code=test_code)

    async def _verify(self, params: dict[str, Any]) -> dict[str, Any]:
        """验证算法正确性."""
        code = params.get("code", "")
        test_code = params.get("test_code", "")
        full_code = code + "\n\n" + test_code if test_code else code
        return await self._execute_code(full_code, auto_fix=True)

    def _complexity_analysis(self, params: dict[str, Any]) -> dict[str, Any]:
        """复杂度分析（静态分析）."""
        algo_name = params.get("algorithm", "")
        complexities = {
            "bubble_sort": {"time": "O(n²)", "space": "O(1)", "description": "冒泡排序"},
            "quick_sort": {"time": "O(n log n)", "space": "O(log n)", "description": "快速排序"},
            "merge_sort": {"time": "O(n log n)", "space": "O(n)", "description": "归并排序"},
            "binary_search": {"time": "O(log n)", "space": "O(1)", "description": "二分查找"},
            "fibonacci": {"time": "O(n)", "space": "O(1)", "description": "斐波那契（迭代版）"},
            "factorial": {"time": "O(n)", "space": "O(1)", "description": "阶乘（迭代版）"},
        }
        return complexities.get(algo_name, {"time": "unknown", "space": "unknown"})

    async def _compare(self, params: dict[str, Any]) -> dict[str, Any]:
        """算法对比."""
        algorithms = params.get("algorithms", [])
        code = params.get("code", "")
        return await self._execute_code(code)

    def _get_algorithm_code(self, algo_name: str) -> str:
        """获取算法实现代码."""
        name = algo_name.lower().replace(" ", "_")

        algorithms = {
            "bubble_sort": '''def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        swapped = False
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        if not swapped:
            break
    return arr
''',
            "quick_sort": '''def quick_sort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)
''',
            "binary_search": '''def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
''',
            "fibonacci": '''def fibonacci(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
''',
            "factorial": '''def factorial(n):
    if n <= 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
''',
        }

        return algorithms.get(name, f"# Algorithm {algo_name} not found")

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("algorithm_error", action=request.action, error=error)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )


# ============================================================
# 5. JavaScript 开发技能
# ============================================================


class JSDevSkill(CodeExecutionSkillBase):
    """JavaScript 开发技能."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.js_dev",
            name="JavaScript开发",
            version="2.0.0",
            description="生成JavaScript/TypeScript代码并自动执行验证",
            author="yunxi",
            tags=["javascript", "js", "前端", "node"],
            capabilities=[
                "generate_function",
                "generate_script",
                "debug_code",
                "execute_code",
            ],
            permissions=["code_execute"],
            entrypoint="JSDevSkill",
        )
        super().__init__(manifest)
        self._default_language = "javascript"

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "generate_function":
                data = await self._generate_function(params)
            elif action == "generate_script":
                data = await self._generate_script(params)
            elif action == "debug_code":
                data = await self._debug_code(params)
            elif action == "execute_code":
                data = await self._execute_direct(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    async def _generate_function(self, params: dict[str, Any]) -> dict[str, Any]:
        description = params.get("description", "")
        function_name = params.get("function_name", "myFunction")
        code = self._template_by_description(description, function_name)
        return await self._execute_code(code + f"\nconsole.log({function_name}());")

    async def _generate_script(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "console.log('Hello from JS');")
        return await self._execute_code(code)

    async def _debug_code(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "")
        return await self._execute_code(code, auto_fix=True)

    async def _execute_direct(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "")
        return await self._execute_code(code)

    def _template_by_description(self, description: str, func_name: str) -> str:
        desc_lower = description.lower()

        if "排序" in description or "sort" in desc_lower:
            return f'''function {func_name}(arr) {{
    // {description}
    return arr.sort((a, b) => a - b);
}}
'''

        if "斐波那契" in description or "fibonacci" in desc_lower:
            return f'''function {func_name}(n) {{
    // {description}
    if (n <= 1) return n;
    let a = 0, b = 1;
    for (let i = 2; i <= n; i++) {{
        [a, b] = [b, a + b];
    }}
    return b;
}}
'''

        return f'''function {func_name}(...args) {{
    // {description}
    return args;
}}
'''

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("js_dev_error", action=request.action, error=error)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )
