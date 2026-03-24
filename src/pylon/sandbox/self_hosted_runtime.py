"""Shared self-hosted sandbox runtime for runner/executor commands."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_DOCKER_IMAGE = "python:3.12-slim"
CONTROL_ENV_PREFIX = "PYLON_RUNNER_"


@dataclass(frozen=True)
class RuntimeCommandConfig:
    """Configuration for a self-hosted runtime command."""

    mode_env_var: str
    delegate_command_env_var: str
    process_fallback_env_var: str = "PYLON_FIRECRACKER_ALLOW_PROCESS_FALLBACK"


@dataclass(frozen=True)
class RunnerRequest:
    action: str
    command: str
    cwd: str
    workspace_dir: Path
    timeout: int
    template: str
    env_vars: dict[str, str]

    @classmethod
    def from_stdin(cls) -> RunnerRequest:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        workspace_dir = Path(str(payload["workspace_dir"])).expanduser().resolve()
        return cls(
            action=str(payload["action"]),
            command=str(payload["command"]),
            cwd=str(payload.get("cwd", "/workspace")),
            workspace_dir=workspace_dir,
            timeout=max(int(payload.get("timeout", 30) or 30), 1),
            template=str(payload.get("template", "")),
            env_vars={
                str(key): str(value) for key, value in dict(payload.get("env_vars") or {}).items()
            },
        )


def main(config: RuntimeCommandConfig) -> None:
    started = time.monotonic()
    try:
        request = RunnerRequest.from_stdin()
        if request.action != "execute_command":
            raise ValueError(f"unsupported action: {request.action}")
        result = execute_request(request, config=config)
        result.setdefault("duration_ms", round((time.monotonic() - started) * 1000, 3))
        print(json.dumps(result))
    except Exception as exc:
        sys.stderr.write(str(exc))
        sys.exit(1)


def execute_request(
    request: RunnerRequest,
    *,
    config: RuntimeCommandConfig,
) -> dict[str, Any]:
    mode = _resolve_mode(config)
    if mode == "delegate":
        return _execute_delegate(request, config=config)
    if mode == "docker":
        return _execute_docker(request)
    if mode == "process":
        return _execute_process(request, config=config)
    raise ValueError(f"unsupported runner mode: {mode}")


def _resolve_mode(config: RuntimeCommandConfig) -> str:
    requested = os.getenv(config.mode_env_var, "auto").strip().lower() or "auto"
    if requested != "auto":
        return requested
    if os.getenv(config.delegate_command_env_var):
        return "delegate"
    if shutil.which("docker"):
        return "docker"
    if os.getenv(config.process_fallback_env_var) == "1":
        return "process"
    raise RuntimeError(
        "No self-hosted sandbox runtime available. Configure "
        f"{config.delegate_command_env_var}, install Docker, or set "
        f"{config.process_fallback_env_var}=1 for explicit host fallback."
    )


def _execute_delegate(
    request: RunnerRequest,
    *,
    config: RuntimeCommandConfig,
) -> dict[str, Any]:
    delegate_command = os.getenv(config.delegate_command_env_var, "").strip()
    if not delegate_command:
        raise RuntimeError(f"{config.delegate_command_env_var} is not configured")
    completed = subprocess.run(
        shlex.split(delegate_command),
        input=_request_payload(request),
        text=True,
        capture_output=True,
        timeout=request.timeout + 5,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "delegate runner failed")
    return json.loads(completed.stdout or "{}")


def _execute_docker(request: RunnerRequest) -> dict[str, Any]:
    image = _resolve_docker_image(request.template)
    network_mode = (
        "bridge" if request.env_vars.get(f"{CONTROL_ENV_PREFIX}ALLOW_INTERNET") == "1" else "none"
    )
    memory_bytes = int(request.env_vars.get(f"{CONTROL_ENV_PREFIX}MAX_MEMORY_BYTES", "536870912"))
    timeout_seconds = int(
        request.env_vars.get(f"{CONTROL_ENV_PREFIX}TIMEOUT_SECONDS", str(request.timeout))
    )
    cpu_ms = int(
        request.env_vars.get(f"{CONTROL_ENV_PREFIX}MAX_CPU_MS", str(timeout_seconds * 1000))
    )
    cpus = _docker_cpu_limit(cpu_ms=cpu_ms, timeout_seconds=timeout_seconds)
    env_vars = _user_env(request.env_vars)
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        network_mode,
        "--memory",
        f"{memory_bytes}b",
        "--cpus",
        f"{cpus:.2f}",
        "-v",
        f"{request.workspace_dir}:/workspace",
        "-w",
        _translate_workspace_path(request.cwd),
    ]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    for key, value in env_vars.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([image, "/bin/sh", "-lc", request.command])
    return _run_subprocess(cmd, cwd=None, timeout=request.timeout)


def _execute_process(
    request: RunnerRequest,
    *,
    config: RuntimeCommandConfig,
) -> dict[str, Any]:
    if os.getenv(config.mode_env_var) != "process":
        raise RuntimeError(
            f"Host process execution is disabled unless {config.mode_env_var}=process"
        )
    host_workspace = str(request.workspace_dir)
    return _run_subprocess(
        _rewrite_workspace_tokens(request.command, host_workspace),
        cwd=_host_cwd(request),
        timeout=request.timeout,
        env=_user_env(request.env_vars),
        shell=True,
    )


def _run_subprocess(
    command: list[str] | str,
    *,
    cwd: str | None,
    timeout: int,
    env: dict[str, str] | None = None,
    shell: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env={**os.environ, **dict(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            executable="/bin/sh" if shell else None,
            check=False,
        )
        return {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "stdout": str(exc.stdout or ""),
            "stderr": str(exc.stderr or ""),
            "exit_code": 124,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "timed_out": True,
        }


def _host_cwd(request: RunnerRequest) -> str:
    pure = PurePosixPath(request.cwd)
    if str(pure).startswith("/workspace"):
        relative = PurePosixPath(*pure.relative_to("/workspace").parts)
        return str((request.workspace_dir / Path(*relative.parts)).resolve())
    return str(request.workspace_dir)


def _translate_workspace_path(path: str) -> str:
    pure = PurePosixPath(path)
    if not pure.is_absolute():
        return str(pure)
    if str(pure).startswith("/workspace"):
        return str(PurePosixPath("/workspace") / pure.relative_to("/workspace"))
    return str(pure)


def _resolve_docker_image(template: str) -> str:
    override = os.getenv("PYLON_FIRECRACKER_DOCKER_IMAGE", "").strip()
    if override:
        return override
    normalized = template.strip()
    if "/" in normalized or ":" in normalized:
        return normalized
    return DEFAULT_DOCKER_IMAGE


def _rewrite_workspace_tokens(command: str, host_workspace: str) -> str:
    json_quoted = json.dumps(host_workspace)
    shell_quoted = shlex.quote(host_workspace)
    return (
        command.replace('"/workspace"', json_quoted)
        .replace("'/workspace'", json_quoted)
        .replace("/workspace", shell_quoted)
    )


def _docker_cpu_limit(*, cpu_ms: int, timeout_seconds: int) -> float:
    if timeout_seconds <= 0:
        return 1.0
    cpu_budget_seconds = max(cpu_ms / 1000.0, 0.25)
    cpus = cpu_budget_seconds / max(timeout_seconds, 1)
    return max(0.25, min(cpus, 4.0))


def _user_env(env_vars: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in env_vars.items() if not key.startswith(CONTROL_ENV_PREFIX)}


def _request_payload(request: RunnerRequest) -> str:
    return json.dumps(
        {
            "action": request.action,
            "command": request.command,
            "cwd": request.cwd,
            "workspace_dir": str(request.workspace_dir),
            "timeout": request.timeout,
            "template": request.template,
            "env_vars": request.env_vars,
        }
    )
