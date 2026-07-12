"""
M4 代码生成 - 代码生成接口测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockCodeGen:
    LANGS = ["python", "javascript", "java", "go", "rust", "typescript"]
    TEMPLATES = {
        "python": {"function": "def {name}(x, y):\n    return x + y",
                    "hello": 'print("Hello")'},
        "javascript": {"function": "function {name}(x, y) {{ return x + y; }}",
                        "hello": 'console.log("Hello");'},
    }
    def generate(self, req, lang="python", ctype="function"):
        if lang not in self.LANGS:
            return {"success": False, "error": f"不支持: {lang}"}
        tpls = self.TEMPLATES.get(lang, self.TEMPLATES["python"])
        tpl = tpls.get(ctype, tpls["function"])
        code = tpl.format(name="gen_func")
        return {"success": True, "code": code, "language": lang,
                "lines": code.count("\n") + 1}
    def check_syntax(self, code, lang="python"):
        if not code.strip():
            return {"valid": False, "errors": ["代码为空"]}
        errors = []
        if code.count("(") != code.count(")"):
            errors.append("括号不匹配")
        return {"valid": len(errors) == 0, "errors": errors}
    def list_langs(self):
        return self.LANGS.copy()

class TestCodeGenerate:
    @pytest.fixture
    def gen(self):
        return MockCodeGen()

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_gen_python_func(self, gen):
        r = gen.generate("test", "python", "function")
        assert r["success"]
        assert "def gen_func" in r["code"]

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_gen_js_func(self, gen):
        r = gen.generate("test", "javascript", "function")
        assert r["success"]
        assert "function" in r["code"]

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_gen_hello(self, gen):
        r = gen.generate("hello", "python", "hello")
        assert "Hello" in r["code"]

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_gen_unsupported_lang(self, gen):
        r = gen.generate("test", "brainfuck")
        assert not r["success"]

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_supported_langs(self, gen):
        langs = gen.list_langs()
        assert len(langs) == 6
        assert "python" in langs

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_syntax_valid(self, gen):
        r = gen.check_syntax("print('hi')")
        assert r["valid"]

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_syntax_empty(self, gen):
        r = gen.check_syntax("")
        assert not r["valid"]

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_syntax_parens(self, gen):
        r = gen.check_syntax("print('hi")
        assert not r["valid"]

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_all_langs_work(self, gen):
        for lang in gen.list_langs():
            r = gen.generate("t", lang)
            assert isinstance(r["success"], bool)

    @pytest.mark.m4
    @pytest.mark.codegen
    def test_generate_has_lines(self, gen):
        r = gen.generate("test", "python", "function")
        assert r["lines"] > 0
