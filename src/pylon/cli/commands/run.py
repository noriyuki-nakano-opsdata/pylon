"""pylon run command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_state, new_id, now_ts, save_state
from pylon.errors import ExitCode
from pylon.observability.query_service import build_run_query_payload
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
        fail_command(
            ctx,
            "Error: No pylon.yaml found in current directory.",
            exit_code=ExitCode.CONFIG_INVALID,
        )
    except Exception as e:
        fail_command(
            ctx,
            f"Error loading pylon.yaml: {e}",
            exit_code=ExitCode.CONFIG_INVALID,
        )

    input_data = None
    if input_json:
        try:
            input_data = json.loads(input_json)
        except json.JSONDecodeError as e:
            fail_command(
                ctx,
                f"Error: Invalid JSON input: {e}",
                exit_code=ExitCode.CONFIG_INVALID,
            )

    selected_workflow = workflow or "default"
    now = now_ts()

    state = load_state()
    artifacts = execute_project_sync(
        project,
        input_data=normalize_runtime_input(input_data),
        workflow_id=selected_workflow,
    )
    run_id = artifacts.run.id
    run_record = serialize_run(
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
    run_record["sandbox_id"] = sandbox_id
    run_record["project_path"] = str(Path.cwd())
    run_record["agents"] = list(project.agents.keys())
    run_record["nodes"] = list(project.workflow.nodes.keys())
    run_record["updated_at"] = now
    state["runs"][run_id] = run_record
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
    run_payload = build_run_query_payload(run_record)

    click.echo(f"Starting workflow '{selected_workflow}' for project '{project.name}'")
    click.echo(f"Run ID: {run_id}")
    approval_id = run_payload.get("approval_request_id")
    if run_payload["status"] == "waiting_approval" and approval_id:
        click.echo(f"Status: waiting approval ({approval_id})")
    else:
        click.echo(f"Status: {run_payload['status']}")

    if cli_ctx.verbose:
        click.echo(f"Agents: {list(project.agents.keys())}")
        click.echo(f"Nodes: {list(project.workflow.nodes.keys())}")
        if input_data:
            click.echo(f"Input: {input_data}")
