"""Tests for CLI command flows with local persisted state."""

from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner

from pylon.cli.main import cli

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

        checkpoint_id = run_data["checkpoint_ids"][0]

        logs_result = runner.invoke(cli, ["logs", run_id])
        assert logs_result.exit_code == 0
        assert f"run:{run_id}" in logs_result.output

        replay_result = runner.invoke(cli, ["--output", "json", "replay", checkpoint_id])
        assert replay_result.exit_code == 0
        replay_data = json.loads(replay_result.output)
        assert replay_data["status"] == "completed"
        assert replay_data["checkpoint_id"] == checkpoint_id


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

        approve_result = runner.invoke(cli, ["approve", approval_id])
        assert approve_result.exit_code == 0

        inspect_after = runner.invoke(cli, ["--output", "json", "inspect", run_id])
        run_after = json.loads(inspect_after.output)
        assert run_after["status"] == "completed"


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
        assert replay_result.exit_code == 1
        assert "Checkpoint not found: cp_missing" in replay_result.output


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

        state = json.loads((pylon_home / "state.json").read_text(encoding="utf-8"))
        assert run_id in state["runs"]


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
