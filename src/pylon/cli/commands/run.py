"""pylon run command."""

from __future__ import annotations

import json

import click

from pylon.cli.state import load_state, new_id, now_ts, save_state


def _autonomy_value(level: str) -> int:
    mapping = {"A0": 0, "A1": 1, "A2": 2, "A3": 3, "A4": 4}
    return mapping.get(level.upper(), 2)


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
    node_ids = list(project.workflow.nodes.keys())
    agent_names = list(project.agents.keys())
    now = now_ts()

    checkpoint_ids: list[str] = []
    checkpoint_events: list[dict[str, object]] = []
    for node_id in node_ids:
        checkpoint_id = new_id("cp_")
        checkpoint_ids.append(checkpoint_id)
        checkpoint_events.append(
            {
                "checkpoint_id": checkpoint_id,
                "node_id": node_id,
                "output": {"node": node_id, "status": "ok"},
                "timestamp": now,
            }
        )

    state = load_state()
    requires_approval = False
    approval_id: str | None = None

    require_above = _autonomy_value(project.policy.require_approval_above)
    referenced_agents = {
        node.agent for node in project.workflow.nodes.values() if node.agent in project.agents
    }
    for agent_name in referenced_agents:
        agent = project.agents[agent_name]
        if _autonomy_value(agent.autonomy) >= require_above:
            requires_approval = True
            approval_id = new_id("apr_")
            state["approvals"][approval_id] = {
                "id": approval_id,
                "run_id": run_id,
                "status": "pending",
                "agent": agent_name,
                "created_at": now,
            }
            break

    sandbox_id = new_id("sbx_")
    state["sandboxes"][sandbox_id] = {
        "id": sandbox_id,
        "tier": "docker",
        "status": "stopped",
        "run_id": run_id,
        "created_at": now,
    }

    run_status = "waiting_approval" if requires_approval else "completed"
    logs = [
        f"run:{run_id} project:{project.name} workflow:{selected_workflow}",
        *(f"node:{node_id} status:ok" for node_id in node_ids),
    ]
    if requires_approval and approval_id:
        logs.append(f"approval_required:{approval_id}")

    state["runs"][run_id] = {
        "id": run_id,
        "project": project.name,
        "workflow": selected_workflow,
        "status": run_status,
        "input": input_data,
        "agents": agent_names,
        "nodes": node_ids,
        "checkpoint_ids": checkpoint_ids,
        "approval_id": approval_id,
        "sandbox_id": sandbox_id,
        "logs": logs,
        "created_at": now,
        "updated_at": now,
    }
    for event in checkpoint_events:
        state["checkpoints"][event["checkpoint_id"]] = {
            "id": event["checkpoint_id"],
            "run_id": run_id,
            "node_id": event["node_id"],
            "event_log": [
                {
                    "node_id": event["node_id"],
                    "input": input_data or {},
                    "output": event["output"],
                    "timestamp": event["timestamp"],
                }
            ],
            "created_at": now,
        }
    save_state(state)

    click.echo(f"Starting workflow '{selected_workflow}' for project '{project.name}'")
    click.echo(f"Run ID: {run_id}")
    if requires_approval and approval_id:
        click.echo(f"Status: waiting approval ({approval_id})")
    else:
        click.echo("Status: completed")

    if cli_ctx.verbose:
        click.echo(f"Agents: {list(project.agents.keys())}")
        click.echo(f"Nodes: {list(project.workflow.nodes.keys())}")
        if input_data:
            click.echo(f"Input: {input_data}")
