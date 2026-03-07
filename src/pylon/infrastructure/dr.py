"""Disaster Recovery strategy, backup lifecycle, and RPO compliance."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class DRStrategy(str, Enum):
    """Disaster recovery strategy."""

    ACTIVE_PASSIVE = "active_passive"
    ACTIVE_ACTIVE = "active_active"
    BACKUP_RESTORE = "backup_restore"


class BackupStatus(str, Enum):
    """Backup job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DRConfig:
    """DR configuration."""

    strategy: DRStrategy = DRStrategy.ACTIVE_PASSIVE
    rpo_minutes: int = 15
    rto_minutes: int = 30
    backup_schedule: str = "0 */6 * * *"
    backup_retention_days: int = 30
    replication_targets: list[str] = field(default_factory=list)


@dataclass
class BackupJob:
    """A single backup job."""

    id: str
    source: str
    destination: str
    started_at: float
    completed_at: float | None = None
    status: BackupStatus = BackupStatus.PENDING
    size_bytes: int = 0
    error: str = ""


@dataclass
class WALGConfig:
    """PostgreSQL WAL-G archival configuration."""

    storage_type: str = "s3"
    bucket: str = ""
    prefix: str = "pylon-wal"
    compression: str = "lz4"
    retention_full_backups: int = 7
    retention_wal_days: int = 30


@dataclass
class NATSMirrorConfig:
    """NATS JetStream mirror configuration."""

    source_cluster: str = ""
    mirror_cluster: str = ""
    stream_filter: str = ">"
    start_seq: int = 0


@dataclass
class DRStatusReport:
    """Current DR status."""

    strategy: DRStrategy
    rpo_minutes: int
    rto_minutes: int
    last_backup: dict[str, BackupJob | None]
    rpo_compliant: bool
    replication_status: dict[str, str]


class DRManager:
    """Manages backup lifecycle and RPO compliance."""

    def __init__(self, config: DRConfig) -> None:
        self._config = config
        self._backups: list[BackupJob] = []

    @property
    def config(self) -> DRConfig:
        return self._config

    def schedule_backup(self, source: str) -> BackupJob:
        job = BackupJob(
            id=uuid.uuid4().hex[:12],
            source=source,
            destination=f"backup://{source}",
            started_at=time.time(),
            status=BackupStatus.RUNNING,
        )
        self._backups.append(job)
        return job

    def complete_backup(self, job_id: str, size_bytes: int) -> BackupJob:
        job = self._find_job(job_id)
        job.status = BackupStatus.COMPLETED
        job.completed_at = time.time()
        job.size_bytes = size_bytes
        return job

    def fail_backup(self, job_id: str, error: str) -> BackupJob:
        job = self._find_job(job_id)
        job.status = BackupStatus.FAILED
        job.completed_at = time.time()
        job.error = error
        return job

    def list_backups(self, source: str | None = None) -> list[BackupJob]:
        if source is None:
            return list(self._backups)
        return [b for b in self._backups if b.source == source]

    def get_latest_backup(self, source: str) -> BackupJob | None:
        completed = [
            b
            for b in self._backups
            if b.source == source and b.status == BackupStatus.COMPLETED
        ]
        if not completed:
            return None
        return max(completed, key=lambda b: b.completed_at or 0)

    def check_rpo_compliance(self) -> tuple[bool, str]:
        sources = {b.source for b in self._backups}
        if not sources:
            return False, "No backups recorded"

        now = time.time()
        rpo_seconds = self._config.rpo_minutes * 60

        for source in sources:
            latest = self.get_latest_backup(source)
            if latest is None:
                return False, f"No completed backup for source '{source}'"
            age = now - (latest.completed_at or latest.started_at)
            if age > rpo_seconds:
                mins = int(age / 60)
                return (
                    False,
                    f"Source '{source}' last backup {mins}m ago, RPO is {self._config.rpo_minutes}m",
                )

        return True, "All sources within RPO"

    def get_dr_status(self) -> DRStatusReport:
        sources = {b.source for b in self._backups}
        last_backup: dict[str, BackupJob | None] = {}
        for source in sources:
            last_backup[source] = self.get_latest_backup(source)

        rpo_ok, _ = self.check_rpo_compliance()

        replication_status: dict[str, str] = {}
        for target in self._config.replication_targets:
            replication_status[target] = "configured"

        return DRStatusReport(
            strategy=self._config.strategy,
            rpo_minutes=self._config.rpo_minutes,
            rto_minutes=self._config.rto_minutes,
            last_backup=last_backup,
            rpo_compliant=rpo_ok,
            replication_status=replication_status,
        )

    def _find_job(self, job_id: str) -> BackupJob:
        for job in self._backups:
            if job.id == job_id:
                return job
        raise ValueError(f"Backup job '{job_id}' not found")
