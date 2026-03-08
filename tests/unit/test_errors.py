from __future__ import annotations

from pylon.errors import ConfigError, ExitCode, PolicyViolationError


class TestErrorExitCodes:
    def test_to_dict_includes_exit_code(self) -> None:
        error = ConfigError("bad config")
        assert error.to_dict()["error"]["exit_code"] == int(ExitCode.CONFIG_INVALID)

    def test_policy_violation_exposes_structured_exit_code(self) -> None:
        error = PolicyViolationError("blocked")
        assert error.exit_code == ExitCode.POLICY_VIOLATION
