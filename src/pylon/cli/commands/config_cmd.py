"""pylon config command group."""

from __future__ import annotations

from typing import Any

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_config, save_config
from pylon.errors import ExitCode


def _coerce(value: str) -> Any:
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _resolve(config: dict[str, Any], key: str) -> Any:
    current: Any = config
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_nested(config: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


@click.group(name="config")
def config() -> None:
    """Manage local CLI configuration."""


@config.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx: click.Context, key: str) -> None:
    """Get a config value by dot-path key."""
    cfg = load_config()
    value = _resolve(cfg, key)
    if value is None:
        fail_command(ctx, f"Key not found: {key}", exit_code=ExitCode.CONFIG_INVALID)
    click.echo(value)


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a config value by dot-path key."""
    cfg = load_config()
    _set_nested(cfg, key, _coerce(value))
    save_config(cfg)
    click.echo(f"Set {key}")


@config.command("list")
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """List all config values."""
    from pylon.cli.main import get_ctx

    cli_ctx = get_ctx(ctx)
    cfg = load_config()
    click.echo(cli_ctx.formatter.render(cfg))
