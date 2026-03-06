"""pylon run command."""

from __future__ import annotations

import json
import uuid

import click


@click.command()
@click.argument("workflow", required=False, default=None)
@click.option("--input", "input_json", default=None, help="Input data as JSON string.")
@click.pass_context
def run(ctx: click.Context, workflow: str | None, input_json: str | None) -> None:
    """Run a workflow from pylon.yaml."""
    from pylon.cli.main import get_ctx
    cli_ctx = get_ctx(ctx)

    try:
        from pylon.dsl.parser import load_project
        project = load_project(".")
    except FileNotFoundError:
        click.echo("Error: No pylon.yaml found in current directory.")
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error loading pylon.yaml: {e}")
        raise SystemExit(1)

    input_data = None
    if input_json:
        try:
            input_data = json.loads(input_json)
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON input: {e}")
            raise SystemExit(1)

    run_id = str(uuid.uuid4())[:8]
    click.echo(f"Starting workflow '{workflow or 'default'}' for project '{project.name}'")
    click.echo(f"Run ID: {run_id}")
    click.echo("Status: accepted (execution is pending)")

    if cli_ctx.verbose:
        click.echo(f"Agents: {list(project.agents.keys())}")
        click.echo(f"Nodes: {list(project.workflow.nodes.keys())}")
        if input_data:
            click.echo(f"Input: {input_data}")
