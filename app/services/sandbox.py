"""
PayLap Code Sandbox Service.

SECURITY MODEL AND SANDBOX LIMITATIONS:
This sandbox implements a defense-in-depth screening and execution model for evaluating
untrusted Python submissions against milestone test specifications:
1. Static AST screening on submitted code before execution, prohibiting dangerous imports,
   calls, and reflection escape hatches.
2. Isolated temporary directory per execution with scrubbed environment variables (secrets stripped).
3. Hard execution timeout of 8.0 seconds with process-tree termination.
4. OS-level resource limits (rlimits) where supported by the host operating system.

HONEST LIMITATION:
This sandbox runs on the local host process environment and is NOT an airtight VM or kernel-level
isolation boundary. For production deployments, execution should be delegated to ephemeral microVMs
(e.g., Firecracker, gVisor, or Fly.io Machines).
"""

import ast
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import List, Optional

BANNED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "ctypes",
    "importlib",
    "urllib",
    "http",
    "requests",
    "httpx",
    "multiprocessing",
    "threading",
    "signal",
    "pathlib",
    "builtins",
}

BANNED_CALLS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "input",
    "breakpoint",
}

BANNED_ATTRIBUTES = {
    "__subclasses__",
    "__globals__",
    "__builtins__",
}

MAX_OUTPUT_BYTES = 20 * 1024  # 20 KB
TIMEOUT_SECONDS = 8.0


@dataclass
class SandboxResult:
    passed: bool
    exit_code: int
    duration_ms: float
    output: str
    timed_out: bool
    violations: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "output": self.output,
            "timed_out": self.timed_out,
            "violations": self.violations,
            "notes": self.notes,
        }


def screen_code_ast(code: str) -> tuple[bool, List[str], Optional[str]]:
    """
    Statically screen submitted code AST for forbidden modules, calls, and attributes.
    Returns (is_clean, list_of_violations, syntax_error_msg).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as err:
        return False, [], f"SyntaxError: {err.msg} at line {err.lineno}, col {err.offset}"

    violations = []

    for node in ast.walk(tree):
        # 1. Reject forbidden imports: import foo, import foo.bar
        if isinstance(node, ast.Import):
            for alias in node.names:
                base_pkg = alias.name.split(".")[0]
                if base_pkg in BANNED_MODULES:
                    violations.append(f"Forbidden import: '{alias.name}'")

        # 2. Reject forbidden from imports: from foo import bar
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                base_pkg = node.module.split(".")[0]
                if base_pkg in BANNED_MODULES:
                    violations.append(f"Forbidden from-import: '{node.module}'")

        # 3. Reject forbidden function calls: eval(...), open(...)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
                violations.append(f"Forbidden call: '{node.func.id}()'")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_CALLS:
                violations.append(f"Forbidden method call: '{node.func.attr}()'")

        # 4. Reject forbidden dunder attribute access: foo.__globals__, foo.__subclasses__
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRIBUTES:
                violations.append(f"Forbidden dunder attribute access: '.{node.attr}'")

    return (len(violations) == 0, violations, None)


def _build_scrubbed_env(temp_dir: str) -> dict:
    """
    Construct a minimal scrubbed environment containing only what is strictly necessary
    for Python execution, stripping all secrets and project variables.
    """
    safe_keys_windows = {
        "SYSTEMROOT",
        "WINDIR",
        "PATHEXT",
        "COMSPEC",
        "TEMP",
        "TMP",
    }
    safe_keys_posix = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
    }

    scrubbed = {}
    is_win = sys.platform.startswith("win")
    allowed_keys = safe_keys_windows if is_win else safe_keys_posix

    for k, v in os.environ.items():
        if k.upper() in allowed_keys:
            scrubbed[k] = v

    # Preserve filtered PATH so sys.executable and core tools work
    if "PATH" in os.environ:
        scrubbed["PATH"] = os.environ["PATH"]

    # Explicitly ensure no sensitive words leak into child env
    for k in list(scrubbed.keys()):
        k_upper = k.upper()
        if any(secret_term in k_upper for secret_term in ("KEY", "SECRET", "TOKEN", "PAYPAL", "GEMINI", "AUTH", "PASS")):
            scrubbed.pop(k, None)

    scrubbed["PYTHONPATH"] = temp_dir
    scrubbed["PYTHONDONTWRITEBYTECODE"] = "1"
    scrubbed["PYTHONUNBUFFERED"] = "1"

    return scrubbed


def _get_preexec_rlimits():
    """Return preexec_fn on platforms supporting the resource module (POSIX)."""
    try:
        import resource  # Available on Linux/macOS only

        def preexec():
            try:
                # 5s CPU time limit
                resource.setrlimit(resource.RLIMIT_CPU, (5, 8))
                # 512 MB virtual memory limit
                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                # 10 MB maximum file size
                resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
                # 64 maximum open files
                resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            except Exception:
                pass

        return preexec, None
    except ImportError:
        return None, "rlimits not supported on Windows; skipped."


def _kill_process_tree(proc: subprocess.Popen):
    """Forcefully terminate a process and its child processes."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_python_tests(code: str, tests: str) -> SandboxResult:
    """
    Execute pytest verification on submitted solution code inside an isolated sandbox.
    Returns SandboxResult with execution details.
    """
    # Step 1: Static AST Screen on submitted code ONLY
    is_clean, violations, syntax_err = screen_code_ast(code)
    if syntax_err:
        return SandboxResult(
            passed=False,
            exit_code=1,
            duration_ms=0.0,
            output=syntax_err,
            timed_out=False,
            violations=[],
            notes="Rejected by AST parser due to syntax error."
        )

    if not is_clean:
        return SandboxResult(
            passed=False,
            exit_code=1,
            duration_ms=0.0,
            output=f"Security Policy Violation: Code contained forbidden constructs:\n" + "\n".join(f"- {v}" for v in violations),
            timed_out=False,
            violations=violations,
            notes="Execution blocked by static AST security screener."
        )

    # Step 2: Prepare temporary sandbox directory
    start_time = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="paylap_sb_") as temp_dir:
        solution_path = os.path.join(temp_dir, "solution.py")
        test_path = os.path.join(temp_dir, "test_solution.py")

        with open(solution_path, "w", encoding="utf-8") as f:
            f.write(code)

        with open(test_path, "w", encoding="utf-8") as f:
            f.write(tests)

        env = _build_scrubbed_env(temp_dir)
        preexec_fn, rlimits_note = _get_preexec_rlimits()

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--tb=short",
            "test_solution.py"
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=temp_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=preexec_fn
            )

            stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
            exit_code = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
            except Exception:
                stdout, stderr = "", ""
            exit_code = -1
            timed_out = True

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        raw_output = (stdout or "") + (stderr or "")
        if len(raw_output.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raw_output = raw_output[:MAX_OUTPUT_BYTES] + "\n[OUTPUT TRUNCATED TO 20 KB]"

        passed = (exit_code == 0) and not timed_out

        return SandboxResult(
            passed=passed,
            exit_code=exit_code,
            duration_ms=round(duration_ms, 2),
            output=raw_output,
            timed_out=timed_out,
            violations=[],
            notes=rlimits_note
        )
