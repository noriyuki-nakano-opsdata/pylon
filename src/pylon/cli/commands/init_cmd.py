"""pylon init command."""

from __future__ import annotations

from pathlib import Path

import click

_PYLON_YAML_TEMPLATE = """\
version: "1"
name: {name}
description: ""

agents:
  assistant:
    model: ""
    role: "General-purpose assistant"
    autonomy: A2
    tools: []
    sandbox: docker

workflow:
  type: graph
  nodes:
    start:
      agent: assistant

policy:
  max_cost_usd: 10.0
  max_duration: 60m
  require_approval_above: A3
  safety:
    blocked_actions: []
    max_file_changes: 50
  compliance:
    audit_log: required
"""

_DOCKER_COMPOSE_TEMPLATE = """\
version: "3.8"
services:
  nats:
    image: nats:latest
    ports:
      - "4222:4222"
  pylon:
    build: .
    depends_on:
      - nats
    environment:
      - PYLON_NATS_URL=nats://nats:4222
"""


@click.command()
@click.option("--quickstart", is_flag=True, help="Quick start with SQLite + embedded NATS + Docker sandbox.")
@click.option("--name", "project_name", default=None, help="Project name.")
@click.pass_context
def init(ctx: click.Context, quickstart: bool, project_name: str | None) -> None:
    """Initialize a new Pylon project."""
    from pylon.cli.main import get_ctx
    get_ctx(ctx)

    cwd = Path.cwd()
    name = project_name or cwd.name

    pylon_yaml = cwd / "pylon.yaml"
    if pylon_yaml.exists():
        click.echo("pylon.yaml already exists. Aborting.")
        raise SystemExit(1)

    pylon_yaml.write_text(_PYLON_YAML_TEMPLATE.format(name=name))
    click.echo(f"Created pylon.yaml for project '{name}'")

    if quickstart:
        click.echo("Quickstart mode: SQLite + embedded NATS + Docker sandbox")
        compose = cwd / "docker-compose.yaml"
        if not compose.exists():
            compose.write_text(_DOCKER_COMPOSE_TEMPLATE)
            click.echo("Created docker-compose.yaml")
        click.echo("Run 'pylon dev' to start the development environment.")
    else:
        click.echo("Run 'pylon doctor' to verify your setup.")
