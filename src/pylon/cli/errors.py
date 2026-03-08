"""Shared CLI error helpers."""

from __future__ import annotations

import click

from pylon.errors import ExitCode, resolve_exit_code


def fail_command(
    ctx: click.Context,
    message: str,
    *,
    exit_code: ExitCode | None = None,
    exc: BaseException | None = None,
    err: bool = False,
) -> None:
    """Print a message and terminate the command with a structured exit code."""
    if message:
        click.echo(message, err=err)
    ctx.exit(int(exit_code or resolve_exit_code(exc)))
