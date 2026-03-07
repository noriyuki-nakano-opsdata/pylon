"""Pylon CLI entry point (click-based)."""

from __future__ import annotations

import click

from pylon.cli.output import OutputFormatter, auto_detect_format

_VERSION = "0.2.0"


class CliContext:
    """Shared context passed to all commands."""

    def __init__(self, output: str, verbose: bool, quiet: bool) -> None:
        self.formatter = OutputFormatter(output)
        self.verbose = verbose
        self.quiet = quiet


@click.group()
@click.option(
    "--output",
    type=click.Choice(["json", "table", "yaml"]),
    default=None,
    help="Output format (default: table for TTY, json for pipe).",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output.")
@click.version_option(version=_VERSION, prog_name="pylon")
@click.pass_context
def cli(ctx: click.Context, output: str | None, verbose: bool, quiet: bool) -> None:
    """Pylon - Autonomous AI Agent Orchestration Platform."""
    fmt = output or auto_detect_format()
    ctx.ensure_object(dict)
    ctx.obj["ctx"] = CliContext(output=fmt, verbose=verbose, quiet=quiet)


def get_ctx(ctx: click.Context) -> CliContext:
    """Helper to extract CliContext from click context."""
    return ctx.obj["ctx"]


# Register commands
from pylon.cli.commands.agent import agent  # noqa: E402
from pylon.cli.commands.approve import approve  # noqa: E402
from pylon.cli.commands.dev import dev  # noqa: E402
from pylon.cli.commands.doctor import doctor  # noqa: E402
from pylon.cli.commands.init_cmd import init  # noqa: E402
from pylon.cli.commands.inspect_cmd import inspect  # noqa: E402
from pylon.cli.commands.run import run  # noqa: E402

cli.add_command(init)
cli.add_command(run)
cli.add_command(dev)
cli.add_command(inspect)
cli.add_command(doctor)
cli.add_command(approve)
cli.add_command(agent)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
