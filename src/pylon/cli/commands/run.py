"""pylon run command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
import yaml

from pylon.cli.errors import fail_command
from pylon.cli.state import load_control_plane_store, load_state, new_id, now_ts, save_state
from pylon.control_plane import WorkflowRunService
from pylon.errors import ExitCode


def _looks_like_project_path(value: str) -> bool:
    candidate = Path(value)
    return (
        candidate.exists()
        or candidate.suffix in {".yaml", ".yml", ".json"}
        or "/" in value
        or value.startswith(".")
    )


def _parse_input_values(
    ctx: click.Context,
    input_values: tuple[str, ...],
) -> Any:
    if not input_values:
        return None

    if len(input_values) == 1:
        raw = input_values[0]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if "=" not in raw:
                try:
                    yaml_payload = yaml.safe_load(raw)
                except yaml.YAMLError:
                    yaml_payload = None
                if isinstance(yaml_payload, (dict, list)):
                    return yaml_payload
                fail_command(
                    ctx,
                    "Error: Invalid input. Use JSON, YAML mapping/list, or KEY=VALUE syntax.",
                    exit_code=ExitCode.CONFIG_INVALID,
                )

    payload: dict[str, Any] = {}
    for raw in input_values:
        if "=" not in raw:
            fail_command(
                ctx,
                f"Error: Invalid input '{raw}'. Use JSON or KEY=VALUE syntax.",
                exit_code=ExitCode.CONFIG_INVALID,
            )
        key, value = raw.split("=", 1)
        if not key:
            fail_command(
                ctx,
                f"Error: Invalid input '{raw}'. Key must not be empty.",
                exit_code=ExitCode.CONFIG_INVALID,
            )
        try:
            payload[key] = json.loads(value)
        except json.JSONDecodeError:
            payload[key] = value
    return payload


def _resolve_project_source(
    ctx: click.Context,
    positional_value: str | None,
    project_option: str | None,
    file_option: str | None,
    workflow_id: str | None,
) -> tuple[str | Path, str, bool, bool]:
    project_source: str | Path = "."
    selected_workflow = workflow_id or "default"
    project_path_supplied = False
    explicit_workflow_name = False

    option_paths = [value for value in (project_option, file_option) if value]
    if len(option_paths) > 1:
        fail_command(
            ctx,
            "Error: Use only one of --project or --file.",
            exit_code=ExitCode.CONFIG_INVALID,
        )

    option_path = option_paths[0] if option_paths else None
    if project_option is not None:
        click.echo(
            "Warning: --project is deprecated; pass the project path as a positional argument instead.",
            err=True,
        )
    if file_option is not None:
        click.echo(
            "Warning: --file is deprecated; pass the project path as a positional argument instead.",
            err=True,
        )

    if option_path is not None:
        project_source = option_path
        project_path_supplied = True
        if positional_value:
            if _looks_like_project_path(positional_value):
                fail_command(
                    ctx,
                    "Error: Provide the project path either positionally or via --project/--file, not both.",
                    exit_code=ExitCode.CONFIG_INVALID,
                )
            selected_workflow = workflow_id or positional_value
            explicit_workflow_name = True
    elif positional_value:
        if _looks_like_project_path(positional_value):
            project_source = positional_value
            project_path_supplied = True
        else:
            selected_workflow = workflow_id or positional_value
            explicit_workflow_name = True

    return project_source, selected_workflow, project_path_supplied, explicit_workflow_name


def _resolve_project_root(project_source: str | Path) -> str:
    path = Path(project_source)
    if not path.exists():
        return str(Path.cwd())
    if path.is_dir():
        return str(path.resolve())
    return str(path.resolve().parent)


@click.command()
@click.argument("project_or_workflow", required=False, default=None)
@click.option(
    "--project",
    "project_option",
    default=None,
    help="Deprecated alias for passing the project path positionally.",
)
@click.option(
    "--file",
    "file_option",
    default=None,
    help="Deprecated alias for --project.",
)
@click.option(
    "--workflow-id",
    default=None,
    help="Workflow ID to register for this run (defaults to current behavior or project name when a path is provided).",
)
@click.option(
    "--input",
    "input_values",
    multiple=True,
    help="Input as JSON, YAML mapping/list, or KEY=VALUE. Repeat KEY=VALUE to build an input object.",
)
@click.pass_context
def run(
    ctx: click.Context,
    project_or_workflow: str | None,
    project_option: str | None,
    file_option: str | None,
    workflow_id: str | None,
    input_values: tuple[str, ...],
) -> None:
    """Run a workflow from the current project or a provided project path."""
    from pylon.cli.main import get_ctx
    cli_ctx = get_ctx(ctx)

    project_path, selected_workflow, project_path_supplied, explicit_workflow_name = _resolve_project_source(
        ctx,
        project_or_workflow,
        project_option,
        file_option,
        workflow_id,
    )

    try:
        from pylon.dsl.parser import load_project
        project = load_project(project_path)
    except FileNotFoundError:
        location = str(project_path)
        fail_command(
            ctx,
            f"Error: No pylon.yaml found for '{location}'.",
            exit_code=ExitCode.CONFIG_INVALID,
        )
    except Exception as e:
        fail_command(
            ctx,
            f"Error loading project: {e}",
            exit_code=ExitCode.CONFIG_INVALID,
        )

    if project_path_supplied and workflow_id is None and not explicit_workflow_name:
        selected_workflow = project.name

    input_data = _parse_input_values(ctx, input_values)
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
    stored_run["project_path"] = _resolve_project_root(project_path)
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
