import os
import pytest
from app.services.sandbox import run_python_tests, screen_code_ast


def test_sandbox_passing_code():
    code = """
def add(a, b):
    return a + b
"""
    tests = """
from solution import add

def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
"""
    result = run_python_tests(code, tests)
    assert result.passed is True
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.violations == []
    assert result.duration_ms > 0


def test_sandbox_failing_assertion():
    code = """
def multiply(a, b):
    return a + b  # Deliberate bug
"""
    tests = """
from solution import multiply

def test_multiply():
    assert multiply(2, 3) == 6
"""
    result = run_python_tests(code, tests)
    assert result.passed is False
    assert result.exit_code != 0
    assert result.timed_out is False
    assert "assert 5 == 6" in result.output or "FAILED" in result.output


def test_sandbox_ast_screening_forbidden_imports():
    bad_codes = [
        "import os\ndef f(): pass",
        "import subprocess\ndef f(): pass",
        "import socket\ndef f(): pass",
        "from sys import exit\ndef f(): pass",
        "from pathlib import Path\ndef f(): pass",
        "import requests\ndef f(): pass",
    ]
    for code in bad_codes:
        result = run_python_tests(code, "def test(): pass")
        assert result.passed is False
        assert len(result.violations) > 0
        assert "Forbidden" in result.violations[0]


def test_sandbox_ast_screening_forbidden_calls():
    bad_codes = [
        "def f():\n    eval('2+2')",
        "def f():\n    exec('x = 1')",
        "def f():\n    open('/etc/passwd')",
        "def f():\n    __import__('os')",
    ]
    for code in bad_codes:
        result = run_python_tests(code, "def test(): pass")
        assert result.passed is False
        assert len(result.violations) > 0


def test_sandbox_ast_screening_forbidden_dunder():
    code = """
def exploit():
    return ().__class__.__subclasses__()
"""
    result = run_python_tests(code, "def test(): pass")
    assert result.passed is False
    assert any("__subclasses__" in v for v in result.violations)


def test_sandbox_syntax_error():
    bad_syntax = "def broken(:"
    result = run_python_tests(bad_syntax, "def test(): pass")
    assert result.passed is False
    assert "SyntaxError" in result.output


def test_sandbox_env_scrubbing():
    # Plant a dummy secret in the parent process environment
    secret_key = "MY_SUPER_SECRET_PAYPAL_KEY"
    os.environ[secret_key] = "topsecret123"
    try:
        code = """
def check_env():
    return 42
"""
        tests = f"""
import os
from solution import check_env

def test_no_secret():
    # Verify the planted secret was scrubbed out of child process environment
    assert os.getenv("{secret_key}") is None
    assert check_env() == 42
"""
        result = run_python_tests(code, tests)
        assert result.passed is True
        assert result.exit_code == 0
    finally:
        os.environ.pop(secret_key, None)


def test_sandbox_output_truncation():
    code = """
def verbose():
    return "done"
"""
    tests = """
from solution import verbose

def test_large_output():
    # Print 60 KB of text
    for i in range(1000):
        print("X" * 60)
    assert False, "Trigger failure to dump stdout"
"""
    result = run_python_tests(code, tests)
    assert result.passed is False
    # Output should be capped around 20 KB (20480 bytes) plus truncation notice
    assert len(result.output.encode("utf-8")) <= 21000
    assert "[OUTPUT TRUNCATED TO 20 KB]" in result.output


def test_sandbox_timeout():
    code = """
def loop_forever():
    while True:
        pass
"""
    tests = """
from solution import loop_forever

def test_infinite_loop():
    loop_forever()
"""
    result = run_python_tests(code, tests)
    assert result.passed is False
    assert result.timed_out is True
    assert result.exit_code == -1
