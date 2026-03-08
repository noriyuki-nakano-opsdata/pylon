"""Tests for tenant management, quota enforcement, and workflow scheduler."""

from __future__ import annotations

import pytest

from pylon.control_plane.scheduler.scheduler import (
    SchedulerCapacityError,
    SchedulerDependencyError,
    TaskStatus,
    WorkflowScheduler,
    WorkflowTask,
)
from pylon.control_plane.tenant.manager import (
    TenantConfig,
    TenantError,
    TenantManager,
    TenantStatus,
)
from pylon.control_plane.tenant.quota import QuotaEnforcer, ResourceQuota

# --- TenantManager Tests ---


class TestTenantManager:
    def test_create_and_get(self):
        mgr = TenantManager()
        config = TenantConfig(id="t1", name="Tenant One")
        result = mgr.create_tenant(config)
        assert result.id == "t1"
        assert result.schema_name == "tenant_t1"
        assert mgr.get_tenant("t1") is result

    def test_create_duplicate_raises(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        with pytest.raises(TenantError):
            mgr.create_tenant(TenantConfig(id="t1", name="T1 Again"))

    def test_get_missing_returns_none(self):
        mgr = TenantManager()
        assert mgr.get_tenant("nonexistent") is None

    def test_update_tenant(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="Old Name"))
        updated = mgr.update_tenant("t1", name="New Name")
        assert updated.name == "New Name"

    def test_update_missing_raises(self):
        mgr = TenantManager()
        with pytest.raises(TenantError):
            mgr.update_tenant("nonexistent", name="X")

    def test_update_invalid_field_raises(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        with pytest.raises(TenantError, match="Invalid field"):
            mgr.update_tenant("t1", nonexistent_field="value")

    def test_delete_tenant_soft(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        assert mgr.delete_tenant("t1") is True
        assert mgr.get_tenant("t1") is None

    def test_delete_nonexistent_returns_false(self):
        mgr = TenantManager()
        assert mgr.delete_tenant("nonexistent") is False

    def test_list_excludes_deleted(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        mgr.create_tenant(TenantConfig(id="t2", name="T2"))
        mgr.delete_tenant("t1")
        tenants = mgr.list_tenants()
        assert len(tenants) == 1
        assert tenants[0].id == "t2"

    def test_suspend_tenant(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        result = mgr.suspend_tenant("t1")
        assert result.status == TenantStatus.SUSPENDED

    def test_suspend_already_suspended_raises(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        mgr.suspend_tenant("t1")
        with pytest.raises(TenantError, match="already suspended"):
            mgr.suspend_tenant("t1")

    def test_activate_tenant(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        mgr.suspend_tenant("t1")
        result = mgr.activate_tenant("t1")
        assert result.status == TenantStatus.ACTIVE

    def test_activate_already_active_raises(self):
        mgr = TenantManager()
        mgr.create_tenant(TenantConfig(id="t1", name="T1"))
        with pytest.raises(TenantError, match="already active"):
            mgr.activate_tenant("t1")


# --- QuotaEnforcer Tests ---


class TestQuotaEnforcer:
    def test_check_within_quota(self):
        enforcer = QuotaEnforcer()
        enforcer.set_quota("t1", ResourceQuota(max_cpu_cores=4.0))
        assert enforcer.check_quota("t1", "cpu_cores", 2.0) is True

    def test_check_exceeds_quota(self):
        enforcer = QuotaEnforcer()
        enforcer.set_quota("t1", ResourceQuota(max_cpu_cores=4.0))
        enforcer.record_usage("t1", "cpu_cores", 3.0)
        assert enforcer.check_quota("t1", "cpu_cores", 2.0) is False

    def test_check_at_exact_limit(self):
        enforcer = QuotaEnforcer()
        enforcer.set_quota("t1", ResourceQuota(max_cpu_cores=4.0))
        assert enforcer.check_quota("t1", "cpu_cores", 4.0) is True

    def test_check_unknown_tenant_returns_false(self):
        enforcer = QuotaEnforcer()
        assert enforcer.check_quota("unknown", "cpu_cores", 1.0) is False

    def test_check_unknown_resource_returns_false(self):
        enforcer = QuotaEnforcer()
        enforcer.set_quota("t1", ResourceQuota())
        assert enforcer.check_quota("t1", "nonexistent_resource", 1.0) is False

    def test_record_and_get_usage(self):
        enforcer = QuotaEnforcer()
        enforcer.set_quota("t1", ResourceQuota())
        enforcer.record_usage("t1", "cpu_cores", 1.5)
        enforcer.record_usage("t1", "cpu_cores", 0.5)
        usage = enforcer.get_usage("t1")
        assert usage["cpu_cores"] == 2.0

    def test_reset_daily_usage(self):
        enforcer = QuotaEnforcer()
        enforcer.set_quota("t1", ResourceQuota())
        enforcer.record_usage("t1", "cpu_cores", 3.0)
        enforcer.reset_daily_usage("t1")
        assert enforcer.get_usage("t1") == {}

    def test_llm_budget_quota(self):
        enforcer = QuotaEnforcer()
        enforcer.set_quota("t1", ResourceQuota(max_llm_budget_usd_daily=10.0))
        enforcer.record_usage("t1", "llm_budget_usd_daily", 9.0)
        assert enforcer.check_quota("t1", "llm_budget_usd_daily", 1.0) is True
        assert enforcer.check_quota("t1", "llm_budget_usd_daily", 2.0) is False


# --- WorkflowScheduler Tests ---


class TestWorkflowScheduler:
    def _make_task(
        self,
        task_id: str,
        priority: int = 5,
        dependencies: set[str] | None = None,
    ) -> WorkflowTask:
        return WorkflowTask(
            id=task_id,
            workflow_id="wf1",
            tenant_id="t1",
            priority=priority,
            dependencies=dependencies or set(),
        )

    def test_enqueue_and_dequeue(self):
        sched = WorkflowScheduler()
        task = self._make_task("task-1")
        sched.enqueue(task)
        result = sched.dequeue()
        assert result is not None
        assert result.id == "task-1"
        assert result.status == TaskStatus.RUNNING

    def test_dequeue_empty_returns_none(self):
        sched = WorkflowScheduler()
        assert sched.dequeue() is None

    def test_dequeue_priority_order(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("low", priority=9))
        sched.enqueue(self._make_task("high", priority=0))
        sched.enqueue(self._make_task("mid", priority=5))

        first = sched.dequeue()
        second = sched.dequeue()
        third = sched.dequeue()

        assert first is not None and first.id == "high"
        assert second is not None and second.id == "mid"
        assert third is not None and third.id == "low"

    def test_peek(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("t1", priority=3))
        peeked = sched.peek()
        assert peeked is not None and peeked.id == "t1"
        # peek should not remove
        assert sched.size() == 1

    def test_cancel(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("t1"))
        assert sched.cancel("t1") is True
        assert sched.size() == 0
        assert sched.dequeue() is None

    def test_cancel_nonexistent_returns_false(self):
        sched = WorkflowScheduler()
        assert sched.cancel("nonexistent") is False

    def test_list_pending(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("a", priority=5))
        sched.enqueue(self._make_task("b", priority=1))
        pending = sched.list_pending()
        assert len(pending) == 2
        assert pending[0].id == "b"  # higher priority first

    def test_size(self):
        sched = WorkflowScheduler()
        assert sched.size() == 0
        sched.enqueue(self._make_task("t1"))
        sched.enqueue(self._make_task("t2"))
        assert sched.size() == 2
        sched.dequeue()
        assert sched.size() == 1

    def test_enqueue_respects_capacity(self):
        sched = WorkflowScheduler(max_scheduled_tasks=1)
        sched.enqueue(self._make_task("t1"))
        with pytest.raises(SchedulerCapacityError, match="at capacity"):
            sched.enqueue(self._make_task("t2"))

    def test_dequeue_respects_dependencies(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("build"))
        sched.enqueue(self._make_task("test", priority=0, dependencies={"build"}))

        first = sched.dequeue()
        assert first is not None
        assert first.id == "build"
        assert sched.dequeue() is None

        assert sched.complete("build") is True
        second = sched.dequeue()
        assert second is not None
        assert second.id == "test"

    def test_dequeue_wave_returns_all_ready_tasks(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("a", priority=3))
        sched.enqueue(self._make_task("b", priority=1))
        sched.enqueue(self._make_task("c", priority=5, dependencies={"a"}))

        wave = sched.dequeue_wave()
        assert [task.id for task in wave] == ["b", "a"]
        assert all(task.status == TaskStatus.RUNNING for task in wave)

    def test_compute_waves_orders_dependency_dag(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("plan"))
        sched.enqueue(self._make_task("code", dependencies={"plan"}))
        sched.enqueue(self._make_task("test", dependencies={"code"}))
        sched.enqueue(self._make_task("docs", dependencies={"plan"}))

        waves = sched.compute_waves()
        assert [[task.id for task in wave] for wave in waves] == [
            ["plan"],
            ["code", "docs"],
            ["test"],
        ]

    def test_compute_waves_rejects_unknown_dependency(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("task", dependencies={"missing"}))

        with pytest.raises(SchedulerDependencyError, match="unknown dependencies"):
            sched.compute_waves()

    def test_compute_waves_rejects_cycles(self):
        sched = WorkflowScheduler()
        sched.enqueue(self._make_task("a", dependencies={"b"}))
        sched.enqueue(self._make_task("b", dependencies={"a"}))

        with pytest.raises(SchedulerDependencyError, match="cycle"):
            sched.compute_waves()
