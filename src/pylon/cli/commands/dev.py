"""pylon dev command."""

from __future__ import annotations

import platform

import click


@click.command()
@click.option("--port", default=8080, type=int, help="Development server port.")
@click.pass_context
def dev(ctx: click.Context, port: int) -> None:
    """Start the Pylon development environment."""
    system = platform.system()
    if system in ("Darwin", "Windows"):
        click.echo(f"Warning: Running on {system}. Docker sandbox will be used for isolation.")

    click.echo(f"Starting Pylon dev environment on port {port}...")
    click.echo("Expected services: API gateway, NATS, PostgreSQL, Redis, MinIO")
    click.echo("Use 'docker compose up -d' in the project root to launch dependencies.")
