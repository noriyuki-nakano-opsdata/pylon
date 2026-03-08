"""pylon doctor command."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click
import yaml

from pylon.cli.errors import fail_command
from pylon.config.pipeline import build_validation_report, validate_project_definition
from pylon.errors import ExitCode


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


@click.command()
@click.pass_context
def doctor(ctx: click.Context, **kwargs: object) -> None:
    """Check Pylon environment and configuration."""
    from pylon.cli.main import get_ctx

    cli_ctx = get_ctx(ctx)
    checks = [
        _check_python_version(),
        _check_pylon_yaml(),
        _check_docker(),
        _check_packages(),
    ]

    all_ok = True
    first_failure_code: ExitCode | None = None
    validation_report: dict | None = None
    check_payloads: list[dict[str, object]] = []
    for index, check in enumerate(checks):
        if index == 1:
            message, ok, exit_code, validation_report = check
        else:
            message, ok, exit_code = check
        check_payloads.append(
            {
                "message": message,
                "ok": ok,
                "exit_code": int(exit_code),
            }
        )
        symbol = "+" if ok else "x"
        if cli_ctx.formatter.fmt == "table":
            click.echo(f"  [{symbol}] {message}")
        if not ok:
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
                }
            )
        )

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
