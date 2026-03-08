"""Tests for doctor --fix auto-repair functionality."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from pylon.cli.commands.doctor import RepairAction
from pylon.cli.main import cli


def test_fix_flag_is_accepted() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        result = runner.invoke(cli, ["doctor", "--fix"])
        # Should not fail due to unrecognized option
        assert "no such option: --fix" not in result.output


def test_fix_creates_missing_pylon_yaml() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        assert not Path("pylon.yaml").exists()

        result = runner.invoke(cli, ["--output", "json", "doctor", "--fix"])
        assert result.exit_code == 0
        assert Path("pylon.yaml").exists()
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert len(payload["repaired"]) == 1
        assert "scaffold" in payload["repaired"][0].lower()


def test_fix_skips_checks_without_repair_actions() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner = CliRunner(env={"PYLON_HOME": ".pylon-home"})
        Path("pylon.yaml").write_text(
            "version: '1'\nname: t\nagents:\n  w:\n    role: worker\n"
            "    autonomy: A2\nworkflow:\n  type: graph\n  nodes:\n"
            "    s:\n      agent: w\n      next: END\n",
            encoding="utf-8",
        )
        # Docker check may fail but has no repair action - should stay failed
        result = runner.invoke(cli, ["doctor", "--fix"])
        # No "FIXED" for Docker since there's no repair action
        assert "Docker: FIXED" not in result.output


def test_repair_action_dataclass() -> None:
    action = RepairAction(
        check_name="test",
        description="test repair",
        repair_fn=lambda: True,
    )
    assert action.check_name == "test"
    assert action.description == "test repair"
    assert action.repair_fn() is True
