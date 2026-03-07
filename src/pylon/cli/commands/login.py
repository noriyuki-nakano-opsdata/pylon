"""pylon login command."""

from __future__ import annotations

import click

from pylon.cli.state import load_config, save_config


@click.command()
@click.option("--token", default=None, help="OIDC access token.")
@click.option("--provider", default="oidc", show_default=True, help="Auth provider name.")
@click.option("--llm-api-key", default=None, help="Default LLM API key.")
def login(token: str | None, provider: str, llm_api_key: str | None) -> None:
    """Configure local auth settings."""
    resolved_token = token or click.prompt("Access token", hide_input=True)
    cfg = load_config()
    cfg.setdefault("auth", {})
    cfg["auth"]["provider"] = provider
    cfg["auth"]["token"] = resolved_token
    if llm_api_key:
        cfg.setdefault("llm", {})
        cfg["llm"]["api_key"] = llm_api_key
    save_config(cfg)
    click.echo(f"Login configuration saved (provider={provider}).")

