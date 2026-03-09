"""Tests for pylon.autonomy.approval."""

from pylon.autonomy.approval import ApprovalGate, ApprovalPolicy
from pylon.types import AutonomyLevel


class TestApprovalPolicy:
    def test_from_autonomy_level_mapping(self) -> None:
        assert ApprovalPolicy.from_autonomy_level(AutonomyLevel.A0) == ApprovalPolicy.UNTRUSTED
        assert ApprovalPolicy.from_autonomy_level(AutonomyLevel.A1) == ApprovalPolicy.UNTRUSTED
        assert ApprovalPolicy.from_autonomy_level(AutonomyLevel.A2) == ApprovalPolicy.ON_FAILURE
        assert ApprovalPolicy.from_autonomy_level(AutonomyLevel.A3) == ApprovalPolicy.ON_REQUEST
        assert ApprovalPolicy.from_autonomy_level(AutonomyLevel.A4) == ApprovalPolicy.AUTO_APPROVE

    def test_approval_gate_auto_approve(self) -> None:
        gate = ApprovalGate(default_policy=ApprovalPolicy.AUTO_APPROVE)
        request = gate.check("file_write", "Write to output.txt")
        assert request.auto_approved is True
        assert request.operation == "file_write"
        assert request.request_id not in gate._pending

    def test_approval_gate_untrusted(self) -> None:
        gate = ApprovalGate(default_policy=ApprovalPolicy.UNTRUSTED)
        request = gate.check("shell_exec", "Run rm -rf /tmp/data")
        assert request.auto_approved is False
        assert request.policy == ApprovalPolicy.UNTRUSTED
        assert request.request_id in gate._pending

        gate.approve(request.request_id)
        assert request.request_id not in gate._pending
