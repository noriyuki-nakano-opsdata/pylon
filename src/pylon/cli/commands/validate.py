"""pylon validate command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
import yaml

from pylon.cli.errors import fail_command
from pylon.config.pipeline import build_validation_report, validate_project_definition
from pylon.errors import ExitCode


def _resolve_project_file(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_dir():
        for name in ("pylon.yaml", "pylon.yml", "pylon.json"):
            candidate = path / name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"No pylon.yaml found in {path}")
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {path}")
    return path


def _load_project_definition(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(content)
    else:
        data = yaml.safe_load(content) or {}
    if not isinstance(data, dict):
        raise ValueError("Project definition must be a mapping")
    return data


def _resolve_validate_path(
    ctx: click.Context,
    path: str,
    project_option: str | None,
    file_option: str | None,
) -> str:
    option_paths = [value for value in (project_option, file_option) if value]
    if len(option_paths) > 1:
        fail_command(
            ctx,
            "Error: Use only one of --project or --file.",
            exit_code=ExitCode.CONFIG_INVALID,
        )
    if project_option is not None:
        click.echo(
            "Warning: --project is deprecated; pass the project path as a positional argument instead.",
            err=True,
        )
    if file_option is not None:
        click.echo(
            "Warning: --file is deprecated; pass the project path as a positional argument instead.",
            err=True,
        )
    if option_paths:
        if path != ".":
            fail_command(
                ctx,
                "Error: Provide the project path either positionally or via --project/--file, not both.",
                exit_code=ExitCode.CONFIG_INVALID,
            )
        return option_paths[0]
    return path


@click.command()
@click.argument("path", required=False, default=".")
@click.option(
    "--project",
    "project_option",
    default=None,
    help="Deprecated alias for passing the project path positionally.",
)
@click.option(
    "--file",
    "file_option",
    default=None,
    help="Deprecated alias for --project.",
)
@click.pass_context
def validate(
    ctx: click.Context,
    path: str,
    project_option: str | None,
    file_option: str | None,
) -> None:
    """Validate a project definition without running it."""
    from pylon.cli.main import get_ctx

    cli_ctx = get_ctx(ctx)
    resolved_path = _resolve_validate_path(ctx, path, project_option, file_option)

    try:
        project_file = _resolve_project_file(resolved_path)
        project_definition = _load_project_definition(project_file)
    except FileNotFoundError as exc:
        fail_command(ctx, f"Error: {exc}", exit_code=ExitCode.CONFIG_INVALID)
    except json.JSONDecodeError as exc:
        fail_command(ctx, f"Error: Invalid JSON: {exc}", exit_code=ExitCode.CONFIG_INVALID)
    except yaml.YAMLError as exc:
        fail_command(ctx, f"Error: Invalid YAML: {exc}", exit_code=ExitCode.CONFIG_INVALID)
    except Exception as exc:
        fail_command(ctx, f"Error loading project: {exc}", exit_code=ExitCode.CONFIG_INVALID)

    validation = validate_project_definition(project_definition)
    report = build_validation_report(validation)
    payload = {
        "ok": validation.valid,
        "path": str(project_file),
        "validation": report,
    }

    if cli_ctx.formatter.fmt == "table":
        click.echo(f"Project: {project_file}")
        if validation.valid:
            click.echo("Validation: OK")
        else:
            click.echo("Validation: FAILED")
            for issue in validation.issues:
                click.echo(f"- [{issue.stage}] {issue.field}: {issue.message}")
    else:
        click.echo(cli_ctx.formatter.render(payload))

    if not validation.valid:
        fail_command(ctx, "", exit_code=ExitCode.CONFIG_INVALID)
