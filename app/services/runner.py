import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
from app.config import settings
from app.services.sandbox import _build_scrubbed_env, _get_preexec_rlimits, _kill_process_tree, screen_code_ast


@dataclass
class RunnerResult:
    passed: bool
    output: str
    duration_ms: float = 0.0
    timed_out: bool = False
    exit_code: int = 0
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "output": self.output,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "exit_code": self.exit_code,
            "violations": self.violations,
        }


class CodeRunner(ABC):
    @abstractmethod
    def run(
        self,
        code: str,
        tests: str,
        timeout_seconds: float = 8.0,
        memory_mb: int = 256
    ) -> RunnerResult:
        """Execute test suite against untrusted submission code."""
        pass


class ProcessRunner(CodeRunner):
    """
    Subprocess-based code runner with strict AST screening, scrubbed env,
    and process-tree timeout termination.
    Default in development and test environments.
    """

    def run(
        self,
        code: str,
        tests: str,
        timeout_seconds: float = 8.0,
        memory_mb: int = 256
    ) -> RunnerResult:
        # Production safety guard
        if settings.PAYLAP_ENV == "production" and not settings.PAYLAP_ALLOW_INSECURE_RUNNER:
            raise RuntimeError(
                "ProcessRunner is disabled in production without PAYLAP_ALLOW_INSECURE_RUNNER=true. "
                "Remote runner required."
            )

        start_time = time.perf_counter()

        # Step 1: Static AST Screening
        is_clean, violations, syntax_err = screen_code_ast(code)
        if syntax_err:
            return RunnerResult(
                passed=False,
                output=f"Syntax Error: {syntax_err}",
                duration_ms=0.0,
                timed_out=False,
                exit_code=1,
                violations=[],
            )

        if not is_clean:
            return RunnerResult(
                passed=False,
                output="Security Policy Violation: Submission contained forbidden constructs:\n" + "\n".join(f"- {v}" for v in violations),
                duration_ms=0.0,
                timed_out=False,
                exit_code=1,
                violations=violations,
            )

        # Step 2: Isolated directory execution
        with tempfile.TemporaryDirectory(prefix="paylap_proc_") as temp_dir:
            solution_path = os.path.join(temp_dir, "solution.py")
            test_path = os.path.join(temp_dir, "test_solution.py")

            with open(solution_path, "w", encoding="utf-8") as f:
                f.write(code)

            with open(test_path, "w", encoding="utf-8") as f:
                f.write(tests)

            env = _build_scrubbed_env(temp_dir)
            preexec_fn, _ = _get_preexec_rlimits(memory_mb=memory_mb)

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

                stdout, stderr = proc.communicate(timeout=timeout_seconds)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                full_output = (stdout + "\n" + stderr).strip()

                return RunnerResult(
                    passed=(proc.returncode == 0),
                    output=full_output,
                    duration_ms=round(duration_ms, 2),
                    timed_out=False,
                    exit_code=proc.returncode,
                    violations=[]
                )

            except subprocess.TimeoutExpired:
                _kill_process_tree(proc)
                try:
                    proc.communicate(timeout=2.0)
                except Exception:
                    pass
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return RunnerResult(
                    passed=False,
                    output=f"Execution timed out after {timeout_seconds}s limit exceeded.",
                    duration_ms=round(duration_ms, 2),
                    timed_out=True,
                    exit_code=-9,
                    violations=["TIMEOUT_EXCEEDED"]
                )

            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return RunnerResult(
                    passed=False,
                    output=f"Execution error: {exc}",
                    duration_ms=round(duration_ms, 2),
                    timed_out=False,
                    exit_code=1,
                    violations=[]
                )


class RemoteRunner(CodeRunner):
    """
    Remote runner client for isolated execution in ephemeral microVMs over TLS.
    Required for live environment contracts.
    """

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        self.url = (url or settings.PAYLAP_RUNNER_URL).rstrip("/")
        self.token = token or settings.PAYLAP_RUNNER_TOKEN

    def run(
        self,
        code: str,
        tests: str,
        timeout_seconds: float = 8.0,
        memory_mb: int = 256
    ) -> RunnerResult:
        if not self.url:
            raise RuntimeError("PAYLAP_RUNNER_URL must be configured when PAYLAP_RUNNER=remote")

        start_time = time.perf_counter()
        payload = {
            "code": code,
            "tests": tests,
            "timeout_ms": int(timeout_seconds * 1000),
            "memory_mb": memory_mb,
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=timeout_seconds + 5.0) as client:
                res = client.post(f"{self.url}/run", json=payload, headers=headers)
                duration_ms = (time.perf_counter() - start_time) * 1000.0

                if res.status_code == 200:
                    data = res.json()
                    return RunnerResult(
                        passed=bool(data.get("passed", False)),
                        output=str(data.get("output", "")),
                        duration_ms=float(data.get("duration_ms", duration_ms)),
                        timed_out=bool(data.get("timed_out", False)),
                        exit_code=int(data.get("exit_code", 0)),
                        violations=list(data.get("violations", [])),
                    )
                else:
                    return RunnerResult(
                        passed=False,
                        output=f"Remote runner returned status {res.status_code}: {res.text}",
                        duration_ms=round(duration_ms, 2),
                        timed_out=False,
                        exit_code=res.status_code,
                        violations=[],
                    )

        except httpx.TimeoutException:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return RunnerResult(
                passed=False,
                output=f"Remote runner request timed out after {timeout_seconds}s.",
                duration_ms=round(duration_ms, 2),
                timed_out=True,
                exit_code=-9,
                violations=["REMOTE_RUNNER_TIMEOUT"],
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return RunnerResult(
                passed=False,
                output=f"Remote runner communication error: {exc}",
                duration_ms=round(duration_ms, 2),
                timed_out=False,
                exit_code=1,
                violations=[],
            )


def get_runner() -> CodeRunner:
    """Factory returning the configured CodeRunner instance."""
    if settings.PAYLAP_RUNNER == "remote":
        return RemoteRunner()
    return ProcessRunner()
