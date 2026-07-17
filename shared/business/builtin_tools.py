"""
内置核心工具集 - 云汐Agent默认工具
计算/记忆/知识库/时间/文本处理 等基础工具

工具列表：
1. calculator - 数学计算器
2. search_memory - 搜索长期记忆
3. search_knowledge - 搜索知识库
4. get_current_time - 获取当前时间
5. text_analysis - 文本分析（字数、关键词等）
6. save_memory - 保存记忆
7. web_search - 联网搜索（占位，后续接入）
"""

import re
import ast
import math
import time
import json
import operator
from datetime import datetime
from typing import Optional, Dict, Any

from .tool_system import (
    BaseTool, ToolParameter, ToolResult, ToolCategory,
    create_tool, get_tool_registry,
)


# ==================== 计算工具 ====================

class CalculatorTool(BaseTool):
    """数学计算器工具
    
    安全设计：
    - 使用 AST 解析验证表达式结构（第一道防线）
    - 只允许数字、运算符、白名单函数调用
    - 禁止属性访问、赋值、import、lambda 等危险操作
    - 最后执行时仍使用受限命名空间（第二道防线）
    """
    
    name = "calculator"
    description = "执行数学计算，支持加减乘除、幂运算、平方根、三角函数等。适合需要精确数值计算的场景。"
    category = ToolCategory.CALCULATION.value
    
    parameters = [
        ToolParameter(
            name="expression",
            type="string",
            description="要计算的数学表达式，如 '2+3*4'、'sqrt(16)'、'sin(pi/2)'",
            required=True,
        ),
    ]
    
    # 允许的函数和常量
    _allowed_names = {
        'abs': abs, 'round': round, 'min': min, 'max': max,
        'sqrt': math.sqrt, 'pow': math.pow, 'exp': math.exp, 'log': math.log, 'log10': math.log10,
        'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
        'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
        'pi': math.pi, 'e': math.e,
        'ceil': math.ceil, 'floor': math.floor, 'factorial': math.factorial,
        'degrees': math.degrees, 'radians': math.radians,
        'log2': math.log2,
    }
    
    # 允许的 AST 节点类型（白名单）
    _allowed_ast_nodes = {
        ast.Expression, ast.Constant, ast.Num, ast.Str,
        ast.BinOp, ast.UnaryOp, ast.Call, ast.Name,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
        ast.Mod, ast.Pow, ast.USub, ast.UAdd,
        ast.Load,  # Name.Load 上下文
    }
    
    @classmethod
    def _validate_ast(cls, node: ast.AST, depth: int = 0) -> None:
        """递归验证 AST 节点是否在白名单内.
        
        Args:
            node: AST 节点
            depth: 当前递归深度（防止栈溢出）
        
        Raises:
            ValueError: 发现不允许的节点类型
        """
        if depth > 50:
            raise ValueError("表达式嵌套过深")
        
        node_type = type(node)
        
        # 检查节点类型是否允许
        if node_type not in cls._allowed_ast_nodes:
            raise ValueError(f"不允许的表达式元素: {node_type.__name__}")
        
        # 常量节点 - 只允许数字
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, complex)):
                raise ValueError(f"不允许的常量类型: {type(node.value).__name__}")
            return
        
        # Name 节点 - 检查是否在白名单
        if isinstance(node, ast.Name):
            if node.id not in cls._allowed_names:
                raise ValueError(f"未定义的标识符: {node.id}")
            return
        
        # Call 节点 - 检查函数名是否在白名单
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in cls._allowed_names:
                    raise ValueError(f"未定义的函数: {node.func.id}")
            else:
                raise ValueError("不允许的函数调用形式")
            # 递归验证参数
            for arg in node.args:
                cls._validate_ast(arg, depth + 1)
            for kw in node.keywords:
                cls._validate_ast(kw.value, depth + 1)
            return
        
        # BinOp 节点 - 递归验证左右操作数
        if isinstance(node, ast.BinOp):
            cls._validate_ast(node.left, depth + 1)
            cls._validate_ast(node.right, depth + 1)
            return
        
        # UnaryOp 节点 - 递归验证操作数
        if isinstance(node, ast.UnaryOp):
            cls._validate_ast(node.operand, depth + 1)
            return
        
        # Expression 根节点 - 递归验证 body
        if isinstance(node, ast.Expression):
            cls._validate_ast(node.body, depth + 1)
            return
    
    def execute(self, expression: str, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            # 1. 长度限制
            if len(expression) > 500:
                return ToolResult(
                    success=False,
                    error="表达式过长（限制500字符）",
                )
            
            # 2. AST 解析与验证（第一道防线）
            try:
                tree = ast.parse(expression, mode='eval')
                self._validate_ast(tree)
            except (SyntaxError, ValueError) as e:
                return ToolResult(
                    success=False,
                    error=f"表达式无效: {str(e)}",
                )
            
            # 3. 安全执行（第二道防线 - 受限命名空间）
            result = eval(
                compile(tree, '<calculator>', 'eval'),
                {"__builtins__": {}},
                self._allowed_names,
            )
            
            # 4. 结果类型校验
            if not isinstance(result, (int, float, complex)):
                return ToolResult(
                    success=False,
                    error="计算结果类型无效",
                )
            
            return ToolResult(
                success=True,
                output=f"{expression} = {result}",
                data={"expression": expression, "result": result},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"计算错误: {str(e)}",
            )


# ==================== 记忆工具 ====================

class SearchMemoryTool(BaseTool):
    """搜索长期记忆工具"""
    
    name = "search_memory"
    description = "搜索用户的长期记忆，查找相关的事实、偏好、事件等信息。当需要回忆用户之前说过的内容时使用。"
    category = ToolCategory.MEMORY.value
    
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="搜索关键词或问题",
            required=True,
        ),
        ToolParameter(
            name="limit",
            type="number",
            description="返回结果数量，默认5条",
            required=False,
            default=5,
            min_value=1,
            max_value=20,
        ),
    ]
    
    def execute(self, query: str, limit: int = 5,
                context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            from .long_term_memory import get_long_term_memory
            ltm = get_long_term_memory()
            
            user_id = "default"
            if context and "user_id" in context:
                user_id = context["user_id"]
            
            memories = ltm.search(
                user_id=user_id,
                query=query,
                limit=limit,
                sort_by="relevance",
            )
            
            if not memories:
                return ToolResult(
                    success=True,
                    output="没有找到相关记忆。",
                    data={"memories": []},
                )
            
            output_lines = []
            for i, mem in enumerate(memories, 1):
                type_label = mem.memory_type
                output_lines.append(
                    f"[{i}] ({type_label}) {mem.title}: {mem.content[:200]}"
                )
            
            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                data={"memories": [m.to_dict() for m in memories]},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"记忆搜索失败: {str(e)}")


class SaveMemoryTool(BaseTool):
    """保存记忆工具"""
    
    name = "save_memory"
    description = "将重要信息保存到用户的长期记忆中。当用户提到重要的个人信息、偏好、事件时使用。"
    category = ToolCategory.MEMORY.value
    
    parameters = [
        ToolParameter(
            name="content",
            type="string",
            description="要保存的记忆内容",
            required=True,
        ),
        ToolParameter(
            name="memory_type",
            type="string",
            description="记忆类型",
            required=False,
            default="fact",
            enum=["fact", "event", "person", "knowledge", "preference", "goal", "emotion"],
        ),
        ToolParameter(
            name="title",
            type="string",
            description="记忆标题（简短描述）",
            required=False,
        ),
        ToolParameter(
            name="importance",
            type="string",
            description="重要性",
            required=False,
            default="normal",
            enum=["trivial", "low", "normal", "important", "critical"],
        ),
    ]
    
    def execute(self, content: str, memory_type: str = "fact",
                title: Optional[str] = None, importance: str = "normal",
                context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            from .long_term_memory import get_long_term_memory
            ltm = get_long_term_memory()
            
            user_id = "default"
            if context and "user_id" in context:
                user_id = context["user_id"]
            
            mem_title = title or content[:50]
            memory = ltm.add_memory(
                user_id=user_id,
                memory_type=memory_type,
                title=mem_title,
                content=content,
                importance=importance,
                source="agent_tool",
            )
            
            return ToolResult(
                success=True,
                output=f"记忆已保存: {mem_title}",
                data={"memory_id": memory.memory_id},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"保存记忆失败: {str(e)}")


# ==================== 知识库工具 ====================

class SearchKnowledgeTool(BaseTool):
    """搜索知识库工具"""
    
    name = "search_knowledge"
    description = "搜索RAG知识库，查找相关的文档和知识片段。当需要参考资料、技术文档、知识文章时使用。"
    category = ToolCategory.KNOWLEDGE.value
    
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="搜索查询",
            required=True,
        ),
        ToolParameter(
            name="limit",
            type="number",
            description="返回结果数量，默认3条",
            required=False,
            default=3,
            min_value=1,
            max_value=10,
        ),
        ToolParameter(
            name="category",
            type="string",
            description="知识库分类",
            required=False,
        ),
    ]
    
    def execute(self, query: str, limit: int = 3,
                category: Optional[str] = None,
                context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            from .rag_knowledge import get_rag_knowledge_base
            rag = get_rag_knowledge_base()
            
            results = rag.search(query, category=category, limit=limit)
            
            if not results:
                return ToolResult(
                    success=True,
                    output="知识库中没有找到相关内容。",
                    data={"results": []},
                )
            
            output_lines = []
            for i, r in enumerate(results, 1):
                score_pct = round(r.score * 100, 1)
                text_preview = r.text[:200]
                output_lines.append(f"[{i}] (相关度{score_pct}%) {text_preview}")
            
            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                data={
                    "results": [
                        {
                            "chunk_id": r.chunk.chunk_id,
                            "doc_id": r.chunk.doc_id,
                            "score": r.score,
                            "text": r.chunk.text,
                        }
                        for r in results
                    ]
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"知识库搜索失败: {str(e)}")


# ==================== 时间工具 ====================

class CurrentTimeTool(BaseTool):
    """获取当前时间工具"""
    
    name = "get_current_time"
    description = "获取当前日期和时间。当需要知道现在几点、今天星期几、什么日期时使用。"
    category = ToolCategory.UTILITY.value
    
    parameters = [
        ToolParameter(
            name="format",
            type="string",
            description="时间格式，可选 full/date/time",
            required=False,
            default="full",
            enum=["full", "date", "time"],
        ),
    ]
    
    def execute(self, format: str = "full",
                context: Optional[Dict[str, Any]] = None) -> ToolResult:
        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[now.weekday()]
        
        if format == "date":
            output = now.strftime("%Y年%m月%d日") + f" {weekday}"
        elif format == "time":
            output = now.strftime("%H:%M:%S")
        else:  # full
            output = now.strftime("%Y年%m月%d日 %H:%M:%S") + f" {weekday}"
        
        return ToolResult(
            success=True,
            output=output,
            data={
                "year": now.year,
                "month": now.month,
                "day": now.day,
                "hour": now.hour,
                "minute": now.minute,
                "second": now.second,
                "weekday": weekday,
                "timestamp": time.time(),
            },
        )


# ==================== 文本处理工具 ====================

class TextAnalysisTool(BaseTool):
    """文本分析工具"""
    
    name = "text_analysis"
    description = "分析文本的基本信息，包括字数、段落数、关键词提取等。"
    category = ToolCategory.UTILITY.value
    
    parameters = [
        ToolParameter(
            name="text",
            type="string",
            description="要分析的文本",
            required=True,
        ),
        ToolParameter(
            name="top_keywords",
            type="number",
            description="返回关键词数量",
            required=False,
            default=10,
            min_value=1,
            max_value=30,
        ),
    ]
    
    def execute(self, text: str, top_keywords: int = 10,
                context: Optional[Dict[str, Any]] = None) -> ToolResult:
        # 字符统计
        char_count = len(text)
        # 中文汉字数
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        # 单词数（简单按空格/标点分割）
        words = re.findall(r'[\w\u4e00-\u9fff]+', text)
        word_count = len(words)
        # 段落数
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        para_count = len(paragraphs)
        # 句子数
        sentences = re.split(r'[。！？.!?]+', text)
        sent_count = len([s for s in sentences if s.strip()])
        
        # 简单关键词提取（中文2-gram）
        all_bigrams = []
        for word in words:
            if re.match(r'^[\u4e00-\u9fff]+$', word) and len(word) >= 2:
                for i in range(len(word) - 1):
                    all_bigrams.append(word[i:i+2])
            elif len(word) >= 3:
                all_bigrams.append(word.lower())
        
        freq = {}
        for bg in all_bigrams:
            freq[bg] = freq.get(bg, 0) + 1
        
        sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        top_kw = [kw for kw, _ in sorted_keywords[:top_keywords]]
        
        result_text = f"""文本分析结果：
- 总字符数：{char_count}
- 汉字数：{chinese_chars}
- 词数：{word_count}
- 句子数：{sent_count}
- 段落数：{para_count}
- 关键词：{', '.join(top_kw)}"""
        
        return ToolResult(
            success=True,
            output=result_text,
            data={
                "char_count": char_count,
                "chinese_chars": chinese_chars,
                "word_count": word_count,
                "sentence_count": sent_count,
                "paragraph_count": para_count,
                "keywords": top_kw,
            },
        )


# ==================== 工具注册 ====================

def register_builtin_tools():
    """注册所有内置工具"""
    registry = get_tool_registry()
    
    tools = [
        CalculatorTool(),
        SearchMemoryTool(),
        SaveMemoryTool(),
        SearchKnowledgeTool(),
        CurrentTimeTool(),
        TextAnalysisTool(),
    ]
    
    registered = 0
    for tool in tools:
        if registry.register(tool):
            registered += 1
    
    return registered


# 自动注册
_registered_count = 0


def _ensure_registered():
    """确保工具已注册"""
    global _registered_count
    if _registered_count == 0:
        _registered_count = register_builtin_tools()
    return _registered_count
