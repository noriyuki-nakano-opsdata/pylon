"""Tests for CLI command flows with local persisted state."""

from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner

from pylon.cli.main import cli
from pylon.errors import ExitCode

_PROJECT_YAML_A2 = """\
version: "1"
name: cli-test
agents:
  worker:
    role: "worker"
    autonomy: A2
workflow:
  type: graph
  nodes:
    step1:
      agent: worker
      next: END
"""


_PROJECT_YAML_A3 = """\
version: "1"
name: cli-test-approval
agents:
  reviewer:
    role: "reviewer"
    autonomy: A3
workflow:
  type: graph
  nodes:
    review:
      agent: reviewer
      next: END
policy:
  require_approval_above: A3
"""

_PROJECT_YAML_GOAL = """\
version: "1"
name: cli-goal
agents:
  writer:
    role: "writer"
    autonomy: A2
workflow:
  type: graph
  nodes:
    draft:
      agent: writer
      node_type: loop
      loop_max_iterations: 1
      loop_criterion: response_quality
      loop_threshold: 0.5
      loop_metadata:
        score: 0.9
      next: END
goal:
  objective: "produce a high-quality answer"
  success_criteria:
    - type: response_quality
      threshold: 0.5
  refinement:
    max_replans: 2
    exhaustion_policy: fail
"""

_PROJECT_YAML_BRANCH = """\
version: "1"
name: cli-branch
agents:
  router:
    role: "router"
    autonomy: A2
workflow:
  type: graph
  nodes:
    start:
      agent: router
      next:
        - target: left
          condition: "state.route == 'left'"
        - target: right
          condition: "state.route != 'left'"
    left:
      agent: router
      next: END
    right:
      agent: router
      next: END
"""

_PROJECT_YAML_JOIN = """\
version: "1"
name: cli-join
agents:
  router:
    role: "router"
    autonomy: A2
workflow:
  type: graph
  nodes:
    start:
      agent: router
      next:
        - left
        - right
    left:
      agent: router
      next: join
    right:
      agent: router
      next: join
    join:
      agent: router
      node_type: router
      join_policy: first
      next: END
"""


def _extract(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise AssertionError(f"Pattern not found: {pattern}\n{text}")
    return match.group(1)


def test_run_inspect_logs_and_replay_flow() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_A2)

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)

        inspect_result = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        assert inspect_result.exit_code == 0
        run_data = json.loads(inspect_result.output)
        assert run_data["id"] == run_id
        assert run_data["status"] == "completed"
        assert run_data["stop_reason"] == "none"
        assert run_data["suspension_reason"] == "none"
        assert run_data["execution_summary"]["total_events"] == 1
        assert run_data["execution_summary"]["node_sequence"] == ["step1"]
        assert run_data["execution_summary"]["last_node"] == "step1"
        assert run_data["execution_summary"]["critical_path"] == [
            {"node_id": "step1", "attempt_id": 1, "loop_iteration": 1}
        ]
        assert run_data["execution_summary"]["decision_points"] == [
            {
                "type": "edge_decision",
                "source_node": "step1",
                "edges": [
                    {
                        "edge_key": "step1:0",
                        "edge_index": 0,
                        "status": "taken",
                        "target": "END",
                        "condition": None,
                        "decision_source": "default",
                        "reason": "default edge selected",
                    }
                ],
            }
        ]

        checkpoint_id = run_data["checkpoint_ids"][0]
        control_plane = json.loads(
            Path(".pylon-home/control-plane.json").read_text(encoding="utf-8")
        )
        stored_run = control_plane["workflow_runs_by_id"][run_id]
        assert "approval_summary" not in stored_run
        assert "execution_summary" not in stored_run
        assert "approval_id" not in stored_run

        logs_result = runner.invoke(cli, ["logs", run_id])
        assert logs_result.exit_code == 0
        assert f"run:{run_id}" in logs_result.output

        replay_result = runner.invoke(cli, ["--output", "json", "replay", checkpoint_id])
        assert replay_result.exit_code == 0
        replay_data = json.loads(replay_result.output)
        assert replay_data["view_kind"] == "replay"
        assert replay_data["status"] == "completed"
        assert replay_data["stop_reason"] == "none"
        assert replay_data["checkpoint_id"] == checkpoint_id
        assert replay_data["source_run"] == run_id
        assert replay_data["source_status"] == "completed"
        assert replay_data["replay"] == {
            "checkpoint_id": checkpoint_id,
            "source_run": run_id,
            "source_status": "completed",
            "source_stop_reason": "none",
            "source_suspension_reason": "none",
            "state_hash_verified": True,
        }
        assert replay_data["state"]["step1_done"] is True
        assert replay_data["execution_summary"]["node_sequence"] == ["step1"]
        assert replay_data["policy_resolution"] is None
        assert replay_data["approval_summary"]["pending"] is False


def test_replay_reconstructs_state_up_to_selected_checkpoint() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(
                """\
version: "1"
name: cli-replay-multi
agents:
  worker:
    role: "worker"
    autonomy: A2
workflow:
  type: graph
  nodes:
    a:
      agent: worker
      next: b
    b:
      agent: worker
      next: END
"""
            )

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)
        inspect_result = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        run_data = json.loads(inspect_result.output)

        replay_result = runner.invoke(
            cli, ["--output", "json", "replay", run_data["checkpoint_ids"][-1]]
        )
        assert replay_result.exit_code == 0
        replay_data = json.loads(replay_result.output)
        assert replay_data["state"]["a_done"] is True
        assert replay_data["state"]["b_done"] is True
        assert replay_data["replay"]["state_hash_verified"] is True


def test_approval_flow() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_A3)

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)
        approval_id = _extract(r"Status: waiting approval \((apr_[a-f0-9]+)\)", run_result.output)

        inspect_before = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        run_before = json.loads(inspect_before.output)
        assert run_before["status"] == "waiting_approval"
        assert run_before["suspension_reason"] == "approval_required"
        assert run_before["execution_summary"]["pending_approval"] is True
        assert run_before["execution_summary"]["transition_reason"] == (
            "agent 'reviewer' requires approval"
        )
        assert run_before["execution_summary"]["decision_points"] == [
            {
                "type": "edge_decision",
                "source_node": "review",
                "edges": [
                    {
                        "edge_key": "review:0",
                        "edge_index": 0,
                        "status": "taken",
                        "target": "END",
                        "condition": None,
                        "decision_source": "default",
                        "reason": "default edge selected",
                    }
                ],
            },
            {
                "type": "approval_required",
                "approval_id": approval_id,
                "context": "node",
                "reason": "agent 'reviewer' requires approval",
            },
            {
                "type": "terminal_transition",
                "status": "waiting_approval",
                "stop_reason": "none",
                "suspension_reason": "approval_required",
                "reason": "agent 'reviewer' requires approval",
            },
        ]
        assert run_before["active_approval"]["id"] == approval_id
        assert run_before["active_approval"]["context"]["kind"] == "node"
        assert run_before["active_approval"]["context"]["binding_plan"]["node_id"] == "review"
        assert (
            run_before["active_approval"]["context"]["binding_effect_envelope"]["autonomy"]
            == "A3"
        )
        assert run_before["approval_summary"] == {
            "pending": True,
            "active_request_id": approval_id,
            "active_status": "pending",
            "action": "workflow.node:review",
            "autonomy_level": "A3",
            "context_kind": "node",
            "context_reason": None,
            "binding_plan": run_before["active_approval"]["context"]["binding_plan"],
            "binding_effect_envelope": run_before["active_approval"]["context"][
                "binding_effect_envelope"
            ],
            "plan_hash": run_before["active_approval"]["plan_hash"],
            "effect_hash": run_before["active_approval"]["effect_hash"],
            "pending_request_ids": [approval_id],
            "approved_request_ids": [],
            "rejected_request_ids": [],
        }

        approve_result = runner.invoke(cli, ["approve", approval_id])
        assert approve_result.exit_code == 0

        inspect_after = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        run_after = json.loads(inspect_after.output)
        assert run_after["status"] == "completed"
        assert run_after["suspension_reason"] == "none"
        assert run_after["approval_id"] is None
        assert run_after["approval_summary"]["pending"] is False
        assert run_after["approval_summary"]["approved_request_ids"] == [approval_id]
        assert len(run_after["event_log"]) == 1


def test_inspect_exposes_goal_and_policy_resolution() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_GOAL)

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)

        inspect_result = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        assert inspect_result.exit_code == 0
        run_data = json.loads(inspect_result.output)

        assert run_data["goal"]["objective"] == "produce a high-quality answer"
        assert run_data["goal"]["refinement_policy"]["max_replans"] == 2
        assert run_data["runtime_metrics"]["iterations"] == 1
        assert run_data["verification"]["disposition"] == "success"
        assert run_data["execution_summary"]["goal_satisfied"] is True
        assert run_data["execution_summary"]["final_verification_disposition"] == "success"
        assert run_data["execution_summary"]["node_sequence"] == ["draft"]
        assert run_data["execution_summary"]["critical_path"] == [
            {"node_id": "draft", "attempt_id": 1, "loop_iteration": 1}
        ]
        assert run_data["execution_summary"]["decision_points"] == [
            {
                "type": "edge_decision",
                "source_node": "draft",
                "edges": [
                    {
                        "edge_key": "draft:0",
                        "edge_index": 0,
                        "status": "taken",
                        "target": "END",
                        "condition": None,
                        "decision_source": "default",
                        "reason": "default edge selected",
                    }
                ],
            },
            {
                "type": "terminal_transition",
                "status": "completed",
                "stop_reason": "quality_reached",
                "suspension_reason": "none",
                "reason": None,
            },
        ]
        assert run_data["policy_resolution"] == {
            "goal_failure_policy": "escalate",
            "refinement_exhaustion_policy": "fail",
            "completion_policy": "require_workflow_end",
            "resolved_max_replans": 2,
            "goal_termination_policy": None,
            "effective_termination_policy": None,
            "external_stop_requested": False,
            "refinement_context": None,
            "approval_context": None,
        }


def test_execution_summary_includes_edge_decisions() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_BRANCH)

        run_result = runner.invoke(cli, ["run", "--input", '{"route":"left"}'])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)

        inspect_result = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        assert inspect_result.exit_code == 0
        run_data = json.loads(inspect_result.output)

        assert run_data["execution_summary"]["node_sequence"] == ["start", "left"]
        assert run_data["execution_summary"]["decision_points"] == [
            {
                "type": "edge_decision",
                "source_node": "start",
                "edges": [
                    {
                        "edge_key": "start:0",
                        "edge_index": 0,
                        "status": "taken",
                        "target": "left",
                        "condition": "state.route == 'left'",
                        "decision_source": "condition",
                        "reason": "condition evaluated to true",
                    },
                    {
                        "edge_key": "start:1",
                        "edge_index": 1,
                        "status": "not_taken",
                        "target": "right",
                        "condition": "state.route != 'left'",
                        "decision_source": "condition",
                        "reason": "condition evaluated to false",
                    },
                ],
            },
            {
                "type": "edge_decision",
                "source_node": "left",
                "edges": [
                    {
                        "edge_key": "left:0",
                        "edge_index": 0,
                        "status": "taken",
                        "target": "END",
                        "condition": None,
                        "decision_source": "default",
                        "reason": "default edge selected",
                    }
                ],
            },
        ]


def test_execution_summary_includes_join_selection() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_JOIN)

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)

        inspect_result = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        assert inspect_result.exit_code == 0
        run_data = json.loads(inspect_result.output)

        assert run_data["execution_summary"]["node_sequence"] == [
            "start",
            "left",
            "right",
            "join",
        ]
        assert {
            "type": "join_selection",
            "node_id": "join",
            "winner_edge": "left:0",
            "winner_source": "left",
            "winner_target": "join",
            "winner_condition": None,
        } in run_data["execution_summary"]["decision_points"]


def test_login_and_config_commands() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})

        login_result = runner.invoke(
            cli,
            [
                "login",
                "--token",
                "token-123",
                "--provider",
                "oidc",
                "--llm-api-key",
                "sk-test",
            ],
        )
        assert login_result.exit_code == 0

        get_provider = runner.invoke(cli, ["config", "get", "auth.provider"])
        assert get_provider.exit_code == 0
        assert "oidc" in get_provider.output

        set_result = runner.invoke(cli, ["config", "set", "limits.max_cost", "5"])
        assert set_result.exit_code == 0

        get_cost = runner.invoke(cli, ["config", "get", "limits.max_cost"])
        assert get_cost.exit_code == 0
        assert "5" in get_cost.output


def test_sandbox_list_and_clean() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_A2)

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0

        list_result = runner.invoke(cli, ["--output", "json", "sandbox", "list"])
        assert list_result.exit_code == 0
        entries = json.loads(list_result.output)
        assert len(entries) >= 1

        clean_result = runner.invoke(cli, ["sandbox", "clean"])
        assert clean_result.exit_code == 0

        list_after = runner.invoke(cli, ["--output", "json", "sandbox", "list"])
        entries_after = json.loads(list_after.output)
        assert entries_after == []


def test_replay_missing_checkpoint_fails() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        replay_result = runner.invoke(cli, ["replay", "cp_missing"])
        assert replay_result.exit_code == int(ExitCode.WORKFLOW_ERROR)
        assert "Checkpoint not found: cp_missing" in replay_result.output


def test_doctor_missing_project_uses_config_invalid_exit_code() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        doctor_result = runner.invoke(cli, ["doctor"])
        assert doctor_result.exit_code == int(ExitCode.CONFIG_INVALID)
        assert "pylon.yaml: NOT FOUND" in doctor_result.output


def test_doctor_invalid_project_uses_config_invalid_exit_code() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(
                "version: '1'\n"
                "name: bad\n"
                "agents:\n"
                "  worker:\n"
                "    role: invalid\n"
                "    autonomy: A9\n"
                "workflow:\n"
                "  type: graph\n"
                "  nodes:\n"
                "    step:\n"
                "      agent: worker\n"
                "      next: END\n"
            )

        doctor_result = runner.invoke(cli, ["doctor"])
        assert doctor_result.exit_code == int(ExitCode.CONFIG_INVALID)
        assert "pylon.yaml: INVALID" in doctor_result.output


def test_doctor_json_output_includes_validation_report() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_A2)

        doctor_result = runner.invoke(cli, ["--output", "json", "doctor"])
        assert doctor_result.exit_code == 0
        payload = json.loads(doctor_result.output)
        assert isinstance(payload["ok"], bool)
        assert payload["validation"]["valid"] is True
        assert payload["validation"]["source"] == "project_definition"
        assert payload["checks"][1]["message"] == "pylon.yaml: OK (valid)"


def test_validate_command_accepts_explicit_project_path() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        project_dir = Path("examples/demo")
        project_dir.mkdir(parents=True)
        (project_dir / "pylon.yaml").write_text(_PROJECT_YAML_A2, encoding="utf-8")

        validate_result = runner.invoke(
            cli,
            ["--output", "json", "validate", "examples/demo/pylon.yaml"],
        )
        assert validate_result.exit_code == 0
        payload = json.loads(validate_result.output)
        assert payload["ok"] is True
        assert payload["path"] == "examples/demo/pylon.yaml"


def test_validate_command_accepts_deprecated_file_option() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        project_dir = Path("examples/demo")
        project_dir.mkdir(parents=True)
        (project_dir / "pylon.yaml").write_text(_PROJECT_YAML_A2, encoding="utf-8")

        validate_result = runner.invoke(
            cli,
            ["validate", "--file", "examples/demo/pylon.yaml"],
        )
        assert validate_result.exit_code == 0
        assert "Warning: --file is deprecated" in validate_result.output
        assert '"ok": true' in validate_result.output


def test_run_accepts_project_path_and_key_value_input() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        project_dir = Path("examples/demo")
        project_dir.mkdir(parents=True)
        (project_dir / "pylon.yaml").write_text(_PROJECT_YAML_BRANCH, encoding="utf-8")

        run_result = runner.invoke(
            cli,
            ["run", "examples/demo/pylon.yaml", "--input", "route=left"],
        )
        assert run_result.exit_code == 0
        assert "Starting workflow 'cli-branch'" in run_result.output
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)

        inspect_result = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        assert inspect_result.exit_code == 0
        payload = json.loads(inspect_result.output)
        assert payload["workflow_id"] == "cli-branch"
        assert payload["input"] == {"route": "left"}
        assert payload["project_path"].endswith("examples/demo")
        assert payload["state"]["left_done"] is True
        assert "right_done" not in payload["state"]


def test_run_accepts_yaml_mapping_input_and_deprecated_project_option() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        project_dir = Path("examples/demo")
        project_dir.mkdir(parents=True)
        project_file = project_dir / "pylon.yaml"
        project_file.write_text(_PROJECT_YAML_A2, encoding="utf-8")

        run_result = runner.invoke(
            cli,
            [
                "run",
                "--project",
                str(project_file),
                "--input",
                "topic: Large Language Model Alignment",
            ],
        )
        assert run_result.exit_code == 0
        assert "Warning: --project is deprecated" in run_result.output
        assert "Starting workflow 'cli-test'" in run_result.output
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)

        inspect_result = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        assert inspect_result.exit_code == 0
        payload = json.loads(inspect_result.output)
        assert payload["input"] == {"topic": "Large Language Model Alignment"}
        assert payload["project_path"].endswith("examples/demo")


def test_approval_deny_updates_run_status_and_logs() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_A3)

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)
        approval_id = _extract(r"Status: waiting approval \((apr_[a-f0-9]+)\)", run_result.output)

        deny_result = runner.invoke(
            cli,
            ["approve", approval_id, "--deny", "--reason", "policy violation"],
        )
        assert deny_result.exit_code == 0

        inspect_after = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        run_after = json.loads(inspect_after.output)
        assert run_after["status"] == "cancelled"
        assert run_after["stop_reason"] == "approval_denied"
        assert run_after["approval_summary"]["pending"] is False
        assert run_after["approval_summary"]["rejected_request_ids"] == [approval_id]
        assert run_after["active_approval"] is None
        assert run_after["execution_summary"]["pending_approval"] is False
        assert run_after["execution_summary"]["decision_points"][-1] == {
            "type": "terminal_transition",
            "status": "cancelled",
            "stop_reason": "approval_denied",
            "suspension_reason": "none",
            "reason": "agent 'reviewer' requires approval",
        }

        logs_result = runner.invoke(cli, ["logs", run_id])
        assert logs_result.exit_code == 0
        assert f"approval_rejected:{approval_id}" in logs_result.output


def test_corrupted_state_file_is_recovered() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        with open("pylon.yaml", "w", encoding="utf-8") as f:
            f.write(_PROJECT_YAML_A2)

        pylon_home = Path(".pylon-home")
        pylon_home.mkdir(parents=True, exist_ok=True)
        with open(pylon_home / "state.json", "w", encoding="utf-8") as f:
            f.write("{broken json")

        run_result = runner.invoke(cli, ["run"])
        assert run_result.exit_code == 0
        run_id = _extract(r"Run ID: (run_[a-f0-9]+)", run_result.output)

        control_plane = json.loads(
            (pylon_home / "control-plane.json").read_text(encoding="utf-8")
        )
        assert run_id in control_plane["workflow_runs_by_id"]


def test_corrupted_config_file_is_recovered() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})

        pylon_home = Path(".pylon-home")
        pylon_home.mkdir(parents=True, exist_ok=True)
        with open(pylon_home / "config.yaml", "w", encoding="utf-8") as f:
            f.write("key: [broken")

        set_result = runner.invoke(cli, ["config", "set", "auth.provider", "oidc"])
        assert set_result.exit_code == 0

        get_result = runner.invoke(cli, ["config", "get", "auth.provider"])
        assert get_result.exit_code == 0
        assert "oidc" in get_result.output


def test_config_list_json_output_shape() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        runner.invoke(cli, ["config", "set", "auth.provider", "oidc"])
        runner.invoke(cli, ["config", "set", "limits.max_cost", "7"])

        list_result = runner.invoke(cli, ["--output", "json", "config", "list"])
        assert list_result.exit_code == 0
        payload = json.loads(list_result.output)
        assert payload["auth"]["provider"] == "oidc"
        assert payload["limits"]["max_cost"] == 7
