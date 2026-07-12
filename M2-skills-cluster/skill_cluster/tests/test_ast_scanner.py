"""Tests for AST Security Scanner."""

import pytest

from skill_cluster.ast_scanner import (
    ASTSecurityScanner,
    ScanResult,
    SecurityFinding,
    Severity,
)


def test_scan_safe_code():
    scanner = ASTSecurityScanner()
    result = scanner.scan("x = 1 + 2\ny = math.sqrt(x)")
    assert result.passed
    assert result.block_count == 0


def test_scan_dangerous_import():
    scanner = ASTSecurityScanner()
    result = scanner.scan("import os\nos.system('rm -rf /')")
    assert not result.passed
    assert result.block_count >= 1
    assert any(f.category == "dangerous_import" for f in result.findings)


def test_scan_eval():
    scanner = ASTSecurityScanner()
    result = scanner.scan("x = eval(input())")
    assert not result.passed
    assert any("eval" in f.description for f in result.findings if f.category == "dangerous_call")


def test_scan_exec():
    scanner = ASTSecurityScanner()
    result = scanner.scan("exec('import os')")
    assert not result.passed


def test_scan_compile():
    scanner = ASTSecurityScanner()
    result = scanner.scan("compile('import os', '<string>', 'exec')")
    assert not result.passed


def test_scan_syntax_error():
    scanner = ASTSecurityScanner()
    result = scanner.scan("def (")
    assert not result.passed
    assert any(f.category == "syntax_error" for f in result.findings)


def test_scan_getattr_dunder():
    scanner = ASTSecurityScanner()
    result = scanner.scan("getattr(__builtins__, '__import__')")
    assert not result.passed
    assert any(f.category == "dunder_access" for f in result.findings)


def test_scan_os_system():
    scanner = ASTSecurityScanner()
    result = scanner.scan("import os\nos.system('ls')")
    assert not result.passed


def test_scan_subprocess():
    scanner = ASTSecurityScanner()
    result = scanner.scan("from subprocess import run\nrun(['ls'])")
    assert not result.passed


def test_scan_socket():
    scanner = ASTSecurityScanner()
    result = scanner.scan("import socket\ns = socket.socket()")
    assert not result.passed


def test_scan_math_allowed():
    scanner = ASTSecurityScanner()
    result = scanner.scan("import math\nx = math.sqrt(4)")
    assert result.passed


def test_scan_json_allowed():
    scanner = ASTSecurityScanner()
    result = scanner.scan("import json\ndata = json.loads('{}')")
    assert result.passed


def test_custom_blocked_modules():
    scanner = ASTSecurityScanner(blocked_modules=frozenset({"numpy"}))
    result = scanner.scan("import numpy")
    assert not result.passed
    assert any("numpy" in f.description for f in result.findings)


def test_scan_result_summary():
    scanner = ASTSecurityScanner()
    result = scanner.scan("x = 1")
    assert "PASS" in result.summary


def test_scan_result_summary_blocked():
    scanner = ASTSecurityScanner()
    result = scanner.scan("import os")
    assert "BLOCK" in result.summary


def test_scan_result_summary_warning():
    scanner = ASTSecurityScanner()
    result = scanner.scan("x = 1")
    # No warnings in this code, but the summary format works
    assert result.warn_count == 0
