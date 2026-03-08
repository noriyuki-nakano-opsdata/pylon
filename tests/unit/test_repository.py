"""Tests for repository layer (L4)."""

import pytest

from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import Checkpoint, CheckpointRepository
from pylon.repository.memory import (
    EpisodicEntry,
    MemoryRepository,
    ProceduralEntry,
    SemanticEntry,
)
from pylon.repository.workflow import (
    RunStatus,
    RunStopReason,
    WorkflowDefinition,
    WorkflowRepository,
    WorkflowRun,
)
from pylon.workflow.replay import ReplayEngine


class TestCheckpointRepository:
    @pytest.fixture
    def repo(self):
        return CheckpointRepository()

    @pytest.mark.asyncio
    async def test_create_and_get(self, repo):
        cp = Checkpoint(workflow_run_id="run-1", node_id="step1")
        cp.state_version = 1
        cp.state_hash = "abc123"
        cp.add_event(
            input_data={"x": 1},
            input_state_version=0,
            input_state_hash="prehash",
            tool_events=[{"tool": "search"}],
            artifacts=[{"kind": "report"}],
            state_patch={"y": 2},
        )
        await repo.create(cp)

        result = await repo.get(cp.id)
        assert result is not None
        assert result.node_id == "step1"
        assert len(result.event_log) == 1
        assert result.state_version == 1
        assert result.state_hash == "abc123"
        assert result.event_log[0]["state_patch"] == {"y": 2}
        assert result.event_log[0]["input_state_hash"] == "prehash"
        assert result.event_log[0]["tool_events"] == [{"tool": "search"}]

    @pytest.mark.asyncio
    async def test_list_by_run(self, repo):
        await repo.create(Checkpoint(workflow_run_id="run-1", node_id="a"))
        await repo.create(Checkpoint(workflow_run_id="run-1", node_id="b"))
        await repo.create(Checkpoint(workflow_run_id="run-2", node_id="c"))

        results = await repo.list(workflow_run_id="run-1")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_latest(self, repo):
        await repo.create(Checkpoint(workflow_run_id="run-1", node_id="first"))
        await repo.create(Checkpoint(workflow_run_id="run-1", node_id="second"))

        latest = await repo.get_latest("run-1")
        assert latest is not None
        assert latest.node_id == "second"

    @pytest.mark.asyncio
    async def test_delete(self, repo):
        cp = Checkpoint(workflow_run_id="run-1", node_id="x")
        await repo.create(cp)
        assert await repo.delete(cp.id)
        assert await repo.get(cp.id) is None

    @pytest.mark.asyncio
    async def test_secret_state_patch_is_scrubbed(self, repo):
        cp = Checkpoint(workflow_run_id="run-1", node_id="x")
        cp.add_event(input_data={}, state_patch={"api_key": "secret", "safe": "ok"})
        await repo.create(cp)

        stored = await repo.get(cp.id)
        assert stored is not None
        assert stored.event_log[0]["state_patch"] == {"api_key": "[REDACTED]", "safe": "ok"}
        assert stored.event_log[0]["state_patch_scrubbed"] is True

    def test_replay_skips_hash_verification_for_scrubbed_patch(self):
        replayed = ReplayEngine.replay_event_log(
            [
                {
                    "node_id": "x",
                    "state_patch": {"api_key": "[REDACTED]"},
                    "state_patch_scrubbed": True,
                    "state_hash": "original-secret-hash",
                    "state_version": 1,
                },
                {
                    "node_id": "y",
                    "state_patch": {"safe": "ok"},
                    "state_hash": "later-unredacted-hash",
                    "state_version": 2,
                }
            ]
        )

        assert replayed.state == {"api_key": "[REDACTED]", "safe": "ok"}
        assert replayed.state_hash_verified is False


class TestMemoryRepository:
    @pytest.fixture
    def repo(self):
        return MemoryRepository()

    @pytest.mark.asyncio
    async def test_episodic_store_and_get(self, repo):
        entry = EpisodicEntry(agent_id="agent-1", content="test memory")
        await repo.store_episodic(entry)
        result = await repo.get_episodic(entry.id)
        assert result is not None
        assert result.content == "test memory"

    @pytest.mark.asyncio
    async def test_episodic_list_by_agent(self, repo):
        await repo.store_episodic(EpisodicEntry(agent_id="a1", content="m1"))
        await repo.store_episodic(EpisodicEntry(agent_id="a1", content="m2"))
        await repo.store_episodic(EpisodicEntry(agent_id="a2", content="m3"))

        results = await repo.list_episodic("a1")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_semantic_store_and_get_by_key(self, repo):
        entry = SemanticEntry(key="auth-pattern", content="Use JWT")
        await repo.store_semantic(entry)
        result = await repo.get_semantic_by_key("auth-pattern")
        assert result is not None
        assert result.content == "Use JWT"

    @pytest.mark.asyncio
    async def test_procedural_stats_update(self, repo):
        entry = ProceduralEntry(pattern="deploy", action="git push")
        await repo.store_procedural(entry)

        await repo.update_procedural_stats(entry.id, success=True)
        await repo.update_procedural_stats(entry.id, success=True)
        await repo.update_procedural_stats(entry.id, success=False)

        updated = await repo.get_procedural(entry.id)
        assert updated is not None
        assert updated.execution_count == 3
        assert 0.6 < updated.success_rate < 0.7  # 2/3


class TestWorkflowRepository:
    @pytest.fixture
    def repo(self):
        return WorkflowRepository()

    @pytest.mark.asyncio
    async def test_create_definition(self, repo):
        defn = WorkflowDefinition(name="test-wf", graph={"nodes": {}})
        await repo.create_definition(defn)
        result = await repo.get_definition(defn.id)
        assert result is not None
        assert result.name == "test-wf"

    @pytest.mark.asyncio
    async def test_create_and_update_run(self, repo):
        run = WorkflowRun(workflow_id="wf-1")
        await repo.create_run(run)
        run.start()
        run.state_version = 2
        run.state_hash = "hash-2"
        await repo.update_run(run)

        result = await repo.get_run(run.id)
        assert result is not None
        assert result.status == RunStatus.RUNNING
        assert result.state_version == 2
        assert result.state_hash == "hash-2"

    @pytest.mark.asyncio
    async def test_list_runs_by_status(self, repo):
        r1 = WorkflowRun(workflow_id="wf-1", status=RunStatus.COMPLETED)
        r2 = WorkflowRun(workflow_id="wf-1", status=RunStatus.RUNNING)
        await repo.create_run(r1)
        await repo.create_run(r2)

        completed = await repo.list_runs(status=RunStatus.COMPLETED)
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_wait_for_approval_sets_shared_runtime_state(self, repo):
        run = WorkflowRun(workflow_id="wf-1")
        await repo.create_run(run)

        run.start()
        run.wait_for_approval("apr-1")
        await repo.update_run(run)

        result = await repo.get_run(run.id)
        assert result is not None
        assert result.status == RunStatus.WAITING_APPROVAL
        assert result.suspension_reason == RunStopReason.APPROVAL_REQUIRED
        assert result.approval_request_id == "apr-1"

    @pytest.mark.asyncio
    async def test_cancel_records_stop_reason(self, repo):
        run = WorkflowRun(workflow_id="wf-1")
        await repo.create_run(run)

        run.start()
        run.cancel(RunStopReason.APPROVAL_DENIED)
        await repo.update_run(run)

        result = await repo.get_run(run.id)
        assert result is not None
        assert result.status == RunStatus.CANCELLED
        assert result.stop_reason == RunStopReason.APPROVAL_DENIED

    @pytest.mark.asyncio
    async def test_resume_clears_suspension_state(self, repo):
        run = WorkflowRun(workflow_id="wf-1")
        await repo.create_run(run)

        run.start()
        run.wait_for_approval("apr-1")
        run.resume()
        await repo.update_run(run)

        result = await repo.get_run(run.id)
        assert result is not None
        assert result.status == RunStatus.RUNNING
        assert result.suspension_reason == RunStopReason.NONE
        assert result.approval_request_id is None


class TestAuditRepository:
    @pytest.fixture
    def repo(self):
        return AuditRepository(hmac_key=b"test-key-at-least-16-bytes")

    @pytest.mark.asyncio
    async def test_hmac_key_required(self):
        with pytest.raises(ValueError, match="hmac_key must be at least 16 bytes"):
            AuditRepository(hmac_key=b"short")

    @pytest.mark.asyncio
    async def test_hmac_key_empty_rejected(self):
        with pytest.raises(ValueError, match="hmac_key must be at least 16 bytes"):
            AuditRepository(hmac_key=b"")

    @pytest.mark.asyncio
    async def test_append(self, repo):
        entry = await repo.append(
            event_type="agent.created",
            actor="admin",
            action="create",
            details={"agent_name": "planner"},
        )
        assert entry.id == 1
        assert entry.entry_hash != ""
        assert entry.hmac_signature != ""
        assert entry.prev_hash == ""

    @pytest.mark.asyncio
    async def test_hash_chain(self, repo):
        e1 = await repo.append(event_type="a", actor="x", action="1")
        e2 = await repo.append(event_type="b", actor="x", action="2")
        assert e2.prev_hash == e1.entry_hash

    @pytest.mark.asyncio
    async def test_verify_chain_valid(self, repo):
        await repo.append(event_type="a", actor="x", action="1")
        await repo.append(event_type="b", actor="x", action="2")
        await repo.append(event_type="c", actor="x", action="3")

        valid, msg = await repo.verify_chain()
        assert valid
        assert "verified" in msg

    @pytest.mark.asyncio
    async def test_verify_chain_tampered(self, repo):
        await repo.append(event_type="a", actor="x", action="1")
        await repo.append(event_type="b", actor="x", action="2")

        # Tamper with chain
        repo._entries[0].entry_hash = "tampered"

        valid, msg = await repo.verify_chain()
        assert not valid

    @pytest.mark.asyncio
    async def test_verify_chain_detects_tampered_details(self, repo):
        await repo.append(event_type="a", actor="x", action="1", details={"ok": True})
        repo._entries[0].details["ok"] = False

        valid, msg = await repo.verify_chain()
        assert not valid
        assert "mismatch" in msg
        assert "mismatch" in msg

    @pytest.mark.asyncio
    async def test_list_by_type(self, repo):
        await repo.append(event_type="agent.created", actor="x", action="1")
        await repo.append(event_type="kill_switch", actor="x", action="2")
        await repo.append(event_type="agent.created", actor="x", action="3")

        results = await repo.list(event_type="agent.created")
        assert len(results) == 2
