"""pylon run command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from pylon.cli.state import load_state, new_id, now_ts, save_state
from pylon.runtime import execute_project_sync, normalize_runtime_input, serialize_run


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

    run_id = new_id("run_")
    selected_workflow = workflow or "default"
    now = now_ts()

    state = load_state()
    artifacts = execute_project_sync(
        project,
        input_data=normalize_runtime_input(input_data),
        workflow_id=selected_workflow,
    )
    run_id = artifacts.run.id
    run_payload = serialize_run(
        artifacts,
        project_name=project.name,
        workflow_name=selected_workflow,
        input_data=input_data,
    )

    sandbox_id = new_id("sbx_")
    state["sandboxes"][sandbox_id] = {
        "id": sandbox_id,
        "tier": "docker",
        "status": "stopped",
        "run_id": run_id,
        "created_at": now,
    }
    run_payload["sandbox_id"] = sandbox_id
    run_payload["project_path"] = str(Path.cwd())
    run_payload["agents"] = list(project.agents.keys())
    run_payload["nodes"] = list(project.workflow.nodes.keys())
    run_payload["updated_at"] = now
    state["runs"][run_id] = run_payload
    for approval in artifacts.approvals:
        approval_payload = dict(approval)
        approval_payload["run_id"] = approval_payload.get("run_id") or approval_payload.get(
            "context", {}
        ).get("run_id", run_id)
        state["approvals"][approval_payload["id"]] = approval_payload
    for checkpoint in artifacts.checkpoints:
        checkpoint_payload = checkpoint.to_dict()
        checkpoint_payload["run_id"] = run_id
        state["checkpoints"][checkpoint.id] = checkpoint_payload
    save_state(state)

    click.echo(f"Starting workflow '{selected_workflow}' for project '{project.name}'")
    click.echo(f"Run ID: {run_id}")
    approval_id = run_payload.get("approval_id")
    if run_payload["status"] == "waiting_approval" and approval_id:
        click.echo(f"Status: waiting approval ({approval_id})")
    else:
        click.echo(f"Status: {run_payload['status']}")

    if cli_ctx.verbose:
        click.echo(f"Agents: {list(project.agents.keys())}")
        click.echo(f"Nodes: {list(project.workflow.nodes.keys())}")
        if input_data:
            click.echo(f"Input: {input_data}")
