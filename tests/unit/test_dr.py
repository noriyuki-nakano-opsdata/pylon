"""Tests for DR strategy module."""

from __future__ import annotations

import time

import pytest

from pylon.infrastructure.dr import (
    BackupStatus,
    DRConfig,
    DRManager,
    DRStrategy,
    NATSMirrorConfig,
    WALGConfig,
)


class TestDRConfig:
    def test_defaults(self) -> None:
        cfg = DRConfig()
        assert cfg.strategy == DRStrategy.ACTIVE_PASSIVE
        assert cfg.rpo_minutes == 15
        assert cfg.rto_minutes == 30
        assert cfg.backup_schedule == "0 */6 * * *"
        assert cfg.backup_retention_days == 30
        assert cfg.replication_targets == []


class TestWALGConfig:
    def test_defaults(self) -> None:
        cfg = WALGConfig()
        assert cfg.storage_type == "s3"
        assert cfg.compression == "lz4"
        assert cfg.retention_full_backups == 7


class TestNATSMirrorConfig:
    def test_defaults(self) -> None:
        cfg = NATSMirrorConfig()
        assert cfg.stream_filter == ">"
        assert cfg.start_seq == 0


class TestDRManager:
    @pytest.fixture()
    def manager(self) -> DRManager:
        return DRManager(DRConfig(rpo_minutes=60))

    def test_schedule_backup(self, manager: DRManager) -> None:
        job = manager.schedule_backup("postgresql")
        assert job.source == "postgresql"
        assert job.status == BackupStatus.RUNNING
        assert job.id

    def test_complete_backup(self, manager: DRManager) -> None:
        job = manager.schedule_backup("postgresql")
        completed = manager.complete_backup(job.id, size_bytes=1024)
        assert completed.status == BackupStatus.COMPLETED
        assert completed.size_bytes == 1024
        assert completed.completed_at is not None

    def test_fail_backup(self, manager: DRManager) -> None:
        job = manager.schedule_backup("postgresql")
        failed = manager.fail_backup(job.id, error="disk full")
        assert failed.status == BackupStatus.FAILED
        assert failed.error == "disk full"

    def test_list_backups_all(self, manager: DRManager) -> None:
        manager.schedule_backup("postgresql")
        manager.schedule_backup("nats")
        assert len(manager.list_backups()) == 2

    def test_list_backups_filtered(self, manager: DRManager) -> None:
        manager.schedule_backup("postgresql")
        manager.schedule_backup("nats")
        assert len(manager.list_backups("postgresql")) == 1

    def test_get_latest_backup_none(self, manager: DRManager) -> None:
        assert manager.get_latest_backup("postgresql") is None

    def test_get_latest_backup(self, manager: DRManager) -> None:
        j1 = manager.schedule_backup("postgresql")
        manager.complete_backup(j1.id, 100)
        j2 = manager.schedule_backup("postgresql")
        manager.complete_backup(j2.id, 200)
        latest = manager.get_latest_backup("postgresql")
        assert latest is not None
        assert latest.id == j2.id

    def test_rpo_compliance_no_backups(self, manager: DRManager) -> None:
        ok, msg = manager.check_rpo_compliance()
        assert ok is False
        assert "No backups" in msg

    def test_rpo_compliance_ok(self, manager: DRManager) -> None:
        job = manager.schedule_backup("postgresql")
        manager.complete_backup(job.id, 500)
        ok, msg = manager.check_rpo_compliance()
        assert ok is True
        assert "within RPO" in msg

    def test_rpo_compliance_stale(self) -> None:
        mgr = DRManager(DRConfig(rpo_minutes=0))
        job = mgr.schedule_backup("postgresql")
        completed = mgr.complete_backup(job.id, 500)
        # Force the completed_at to be old
        completed.completed_at = time.time() - 120
        ok, msg = mgr.check_rpo_compliance()
        assert ok is False
        assert "last backup" in msg

    def test_find_job_missing(self, manager: DRManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            manager.complete_backup("nonexistent", 0)

    def test_get_dr_status(self) -> None:
        cfg = DRConfig(
            rpo_minutes=60,
            replication_targets=["us-west-2"],
        )
        mgr = DRManager(cfg)
        job = mgr.schedule_backup("postgresql")
        mgr.complete_backup(job.id, 1024)

        report = mgr.get_dr_status()
        assert report.strategy == DRStrategy.ACTIVE_PASSIVE
        assert report.rpo_minutes == 60
        assert report.rpo_compliant is True
        assert "postgresql" in report.last_backup
        assert report.replication_status == {"us-west-2": "configured"}
