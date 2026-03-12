"""pylon doctor command."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click
import yaml

from pylon.cli.errors import fail_command
from pylon.config.pipeline import build_validation_report, validate_project_definition
from pylon.errors import ExitCode

_MINIMAL_PYLON_YAML = """\
version: "1"
name: my-project
agents:
  worker:
    role: "worker"
    autonomy: A2
workflow:
  type: graph
  nodes:
    step1:
      agent: worker
      next: END
"""


@dataclass
class RepairAction:
    """An auto-repair action for a failed doctor check."""

    check_name: str
    description: str
    repair_fn: Callable[[], bool]  # Returns True if fixed


def _check_python_version() -> tuple[str, bool, ExitCode]:
    v = sys.version_info
    ok = v >= (3, 12)
    label = f"Python {v.major}.{v.minor}.{v.micro}"
    return (f"{label} ({'OK' if ok else 'FAIL: >= 3.12 required'})", ok, ExitCode.INTERNAL_ERROR)


def _check_pylon_yaml() -> tuple[str, bool, ExitCode, dict | None]:
    path = Path.cwd() / "pylon.yaml"
    if not path.exists():
        return ("pylon.yaml: NOT FOUND", False, ExitCode.CONFIG_INVALID, None)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            return ("pylon.yaml: INVALID (empty file)", False, ExitCode.CONFIG_INVALID, None)
        if not isinstance(loaded, dict):
            return (
                "pylon.yaml: INVALID (top-level document must be a mapping)",
                False,
                ExitCode.CONFIG_INVALID,
                None,
            )
        validation = validate_project_definition(dict(loaded))
        report = build_validation_report(validation)
        if validation.valid:
            return ("pylon.yaml: OK (valid)", True, ExitCode.SUCCESS, report)
        details = "; ".join(
            f"{issue.field}: {issue.message}"
            for issue in validation.errors
        )
        return (
            f"pylon.yaml: INVALID ({details})",
            False,
            ExitCode.CONFIG_INVALID,
            report,
        )
    except Exception as e:
        return (f"pylon.yaml: INVALID ({e})", False, ExitCode.CONFIG_INVALID, None)


def _check_docker() -> tuple[str, bool, ExitCode]:
    docker = shutil.which("docker")
    if docker:
        return ("Docker: OK (found)", True, ExitCode.SUCCESS)
    return ("Docker: NOT FOUND", False, ExitCode.SANDBOX_ERROR)


def _check_packages() -> tuple[str, bool, ExitCode]:
    missing = []
    for pkg in ("click", "yaml", "pydantic"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return (
            f"Packages: MISSING ({', '.join(missing)})",
            False,
            ExitCode.INTERNAL_ERROR,
        )
    return ("Packages: OK", True, ExitCode.SUCCESS)


def _build_repair_actions() -> dict[str, RepairAction]:
    """Return repair actions keyed by check message prefix."""

    def _repair_missing_pylon_yaml() -> bool:
        path = Path.cwd() / "pylon.yaml"
        if path.exists():
            return False
        path.write_text(_MINIMAL_PYLON_YAML, encoding="utf-8")
        return True

    return {
        "pylon.yaml: NOT FOUND": RepairAction(
            check_name="pylon.yaml",
            description="Create minimal pylon.yaml scaffold",
            repair_fn=_repair_missing_pylon_yaml,
        ),
    }


def _doctor_severity(ok: bool, exit_code: ExitCode) -> str:
    if ok:
        return "ok"
    if exit_code == ExitCode.SANDBOX_ERROR:
        return "warning"
    return "error"


def _doctor_blocks_success(ok: bool, exit_code: ExitCode) -> bool:
    return not ok and _doctor_severity(ok, exit_code) == "error"


@click.command()
@click.option("--fix", is_flag=True, default=False, help="Auto-repair safe issues.")
@click.pass_context
def doctor(ctx: click.Context, fix: bool, **kwargs: object) -> None:
    """Check Pylon environment and configuration."""
    from pylon.cli.main import get_ctx

    cli_ctx = get_ctx(ctx)
    checks = [
        _check_python_version(),
        _check_pylon_yaml(),
        _check_docker(),
        _check_packages(),
    ]
    repair_actions = _build_repair_actions()

    all_ok = True
    first_failure_code: ExitCode | None = None
    validation_report: dict | None = None
    check_payloads: list[dict[str, object]] = []
    repaired: list[str] = []
    for index, check in enumerate(checks):
        if index == 1:
            message, ok, exit_code, validation_report = check
        else:
            message, ok, exit_code = check

        # Attempt auto-repair when --fix is passed
        if not ok and fix and message in repair_actions:
            action = repair_actions[message]
            if action.repair_fn():
                repaired.append(action.description)
                ok = True
                message = f"{action.check_name}: FIXED ({action.description})"
                if index == 1:
                    # Re-run pylon.yaml check after repair
                    message, ok, exit_code, validation_report = _check_pylon_yaml()

        check_payloads.append(
            {
                "message": message,
                "ok": ok,
                "severity": _doctor_severity(ok, exit_code),
                "exit_code": int(exit_code),
            }
        )
        severity = _doctor_severity(ok, exit_code)
        symbol = "+" if ok else "!" if severity == "warning" else "x"
        if cli_ctx.formatter.fmt == "table":
            click.echo(f"  [{symbol}] {message}")
        if _doctor_blocks_success(ok, exit_code):
            all_ok = False
            if first_failure_code is None:
                first_failure_code = exit_code

    if cli_ctx.formatter.fmt != "table":
        click.echo(
            cli_ctx.formatter.render(
                {
                    "ok": all_ok,
                    "checks": check_payloads,
                    "validation": validation_report,
                    "repaired": repaired,
                }
            )
        )

    if repaired and cli_ctx.formatter.fmt == "table":
        click.echo(f"\nRepaired {len(repaired)} issue(s).")

    if all_ok:
        if cli_ctx.formatter.fmt == "table":
            click.echo("\nAll checks passed.")
    else:
        if cli_ctx.formatter.fmt == "table":
            click.echo("\nSome checks failed. Fix the issues above.")
        fail_command(
            ctx,
            "",
            exit_code=first_failure_code or ExitCode.INTERNAL_ERROR,
        )
