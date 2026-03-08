from __future__ import annotations

from pylon.errors import (
    ERROR_REGISTRY,
    ConfigError,
    ErrorSpec,
    ExitCode,
    PolicyViolationError,
    ProviderError,
    PylonError,
    SandboxError,
    WorkflowError,
    _build_registry,
    _collect_subclasses,
    resolve_error,
)


class TestErrorExitCodes:
    def test_to_dict_includes_exit_code(self) -> None:
        error = ConfigError("bad config")
        assert error.to_dict()["error"]["exit_code"] == int(ExitCode.CONFIG_INVALID)

    def test_policy_violation_exposes_structured_exit_code(self) -> None:
        error = PolicyViolationError("blocked")
        assert error.exit_code == ExitCode.POLICY_VIOLATION


class TestRetryableAndCategory:
    def test_provider_error_is_retryable(self) -> None:
        error = ProviderError("timeout")
        assert error.retryable is True
        assert error.category == "infrastructure"

    def test_policy_violation_not_retryable(self) -> None:
        error = PolicyViolationError("blocked")
        assert error.retryable is False
        assert error.category == "safety"

    def test_config_error_category(self) -> None:
        error = ConfigError("bad")
        assert error.retryable is False
        assert error.category == "validation"

    def test_workflow_error_category(self) -> None:
        error = WorkflowError("fail")
        assert error.retryable is False
        assert error.category == "lifecycle"

    def test_sandbox_error_category(self) -> None:
        error = SandboxError("fail")
        assert error.retryable is False
        assert error.category == "safety"

    def test_to_dict_includes_retryable_and_category(self) -> None:
        error = ProviderError("timeout")
        d = error.to_dict()["error"]
        assert d["retryable"] is True
        assert d["category"] == "infrastructure"

    def test_to_dict_base_class_defaults(self) -> None:
        error = PylonError("generic")
        d = error.to_dict()["error"]
        assert d["retryable"] is False
        assert d["category"] == "general"


class TestErrorRegistry:
    def test_registry_contains_all_subclasses(self) -> None:
        _build_registry()
        all_subclasses = _collect_subclasses(PylonError)
        # Every subclass code should be in the registry
        for cls in all_subclasses:
            assert cls.code in ERROR_REGISTRY, f"{cls.__name__} ({cls.code}) missing from registry"

    def test_registry_entries_are_error_specs(self) -> None:
        for spec in ERROR_REGISTRY.values():
            assert isinstance(spec, ErrorSpec)

    def test_provider_error_in_registry(self) -> None:
        spec = ERROR_REGISTRY["PROVIDER_ERROR"]
        assert spec.retryable is True
        assert spec.category == "infrastructure"
        assert spec.status_code == 502

    def test_policy_violation_in_registry(self) -> None:
        spec = ERROR_REGISTRY["POLICY_VIOLATION"]
        assert spec.retryable is False
        assert spec.category == "safety"

    def test_resolve_error_returns_spec(self) -> None:
        spec = resolve_error("CONFIG_INVALID")
        assert spec is not None
        assert spec.code == "CONFIG_INVALID"
        assert spec.retryable is False
        assert spec.category == "validation"

    def test_resolve_error_returns_none_for_unknown(self) -> None:
        assert resolve_error("NONEXISTENT_CODE") is None
