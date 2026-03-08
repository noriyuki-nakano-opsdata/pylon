"""pylon run command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_control_plane_store, load_state, new_id, now_ts, save_state
from pylon.control_plane import WorkflowRunService
from pylon.errors import ExitCode


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

    control_plane_store = load_control_plane_store()
    control_plane_store.register_workflow_project(selected_workflow, project)
    workflow_service = WorkflowRunService(control_plane_store)
    state = load_state()
    stored_run = workflow_service.start_run(
        workflow_id=selected_workflow,
        input_data=input_data,
    )
    run_id = str(stored_run["id"])

    sandbox_id = new_id("sbx_")
    state["sandboxes"][sandbox_id] = {
        "id": sandbox_id,
        "tier": "docker",
        "status": "stopped",
        "run_id": run_id,
        "created_at": now,
    }
    stored_run["sandbox_id"] = sandbox_id
    stored_run["project_path"] = str(Path.cwd())
    stored_run["agents"] = list(project.agents.keys())
    stored_run["nodes"] = list(project.workflow.nodes.keys())
    stored_run["updated_at"] = now
    control_plane_store.put_run_record(
        stored_run,
        workflow_id=selected_workflow,
        parameters=stored_run.get("parameters", {}),
    )
    save_state(state)
    run_payload = workflow_service.get_run_payload(run_id)

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
