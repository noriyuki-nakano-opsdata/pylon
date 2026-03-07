"""Tests for Firecracker microVM sandbox backend."""

import pytest

from pylon.errors import SandboxError
from pylon.sandbox.manager import SandboxStatus
from pylon.sandbox.firecracker import (
    FirecrackerBackend,
    FirecrackerConfig,
    FirecrackerSandbox,
)


class TestFirecrackerConfig:
    def test_defaults(self):
        cfg = FirecrackerConfig()
        assert cfg.kernel_image == "vmlinux"
        assert cfg.rootfs_image == "rootfs.ext4"
        assert cfg.vcpu_count == 1
        assert cfg.mem_size_mib == 128
        assert cfg.network_mode == "tap"
        assert cfg.jailer_enabled is True
        assert cfg.startup_timeout_ms == 2000

    def test_custom_config(self):
        cfg = FirecrackerConfig(vcpu_count=4, mem_size_mib=512, network_mode="none")
        assert cfg.vcpu_count == 4
        assert cfg.mem_size_mib == 512
        assert cfg.network_mode == "none"


class TestFirecrackerBackend:
    def test_create_returns_vm_id(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig())
        assert vm_id.startswith("fc-")
        assert len(vm_id) == 13  # "fc-" + 10 hex chars

    def test_create_sets_running_status(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig())
        assert backend.status(vm_id) == SandboxStatus.RUNNING

    def test_create_stores_vm_metadata(self):
        backend = FirecrackerBackend()
        cfg = FirecrackerConfig(vcpu_count=2, mem_size_mib=256)
        vm_id = backend.create(cfg)
        vm = backend.get_vm(vm_id)
        assert vm is not None
        assert vm.vcpu_count == 2
        assert vm.mem_size_mib == 256
        assert vm.kernel_image == "vmlinux"

    def test_create_with_jailer_sets_nonzero_uid(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig(jailer_enabled=True))
        vm = backend.get_vm(vm_id)
        assert vm.jailer_uid >= 5000

    def test_create_without_jailer_sets_zero_uid(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig(jailer_enabled=False))
        vm = backend.get_vm(vm_id)
        assert vm.jailer_uid == 0

    def test_startup_time_within_limit(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig(startup_timeout_ms=2000))
        vm = backend.get_vm(vm_id)
        assert vm.startup_time_ms < 2000

    def test_destroy_existing_vm(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig())
        assert backend.destroy(vm_id) is True
        assert backend.get_vm(vm_id) is None

    def test_destroy_nonexistent_vm(self):
        backend = FirecrackerBackend()
        assert backend.destroy("fc-nonexistent") is False

    def test_execute_returns_resource_usage(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig(mem_size_mib=128))
        usage = backend.execute(vm_id, "echo hello")
        assert usage.cpu_ms > 0
        assert usage.memory_bytes > 0

    def test_execute_nonexistent_vm_raises(self):
        backend = FirecrackerBackend()
        with pytest.raises(SandboxError, match="not found"):
            backend.execute("fc-bad", "ls")

    def test_execute_destroyed_vm_raises(self):
        backend = FirecrackerBackend()
        vm_id = backend.create(FirecrackerConfig())
        backend.destroy(vm_id)
        with pytest.raises(SandboxError, match="not found"):
            backend.execute(vm_id, "ls")

    def test_status_nonexistent_raises(self):
        backend = FirecrackerBackend()
        with pytest.raises(SandboxError, match="not found"):
            backend.status("fc-nope")

    def test_list_vms(self):
        backend = FirecrackerBackend()
        backend.create(FirecrackerConfig())
        backend.create(FirecrackerConfig())
        assert len(backend.list_vms()) == 2

    def test_list_vms_after_destroy(self):
        backend = FirecrackerBackend()
        vm1 = backend.create(FirecrackerConfig())
        backend.create(FirecrackerConfig())
        backend.destroy(vm1)
        assert len(backend.list_vms()) == 1

    def test_get_vm_nonexistent(self):
        backend = FirecrackerBackend()
        assert backend.get_vm("fc-nope") is None

    def test_multiple_vms_independent(self):
        backend = FirecrackerBackend()
        vm1 = backend.create(FirecrackerConfig(vcpu_count=1))
        vm2 = backend.create(FirecrackerConfig(vcpu_count=4))
        assert backend.get_vm(vm1).vcpu_count == 1
        assert backend.get_vm(vm2).vcpu_count == 4
        backend.destroy(vm1)
        assert backend.status(vm2) == SandboxStatus.RUNNING
