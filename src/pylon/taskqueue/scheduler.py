"""Task scheduling with datetime and simple cron expressions."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pylon.errors import PylonError
from pylon.taskqueue.queue import Task


class SchedulerError(PylonError):
    """Error raised by the scheduler."""

    code = "SCHEDULER_ERROR"
    status_code = 400


class ScheduleType(enum.Enum):
    ONCE = "once"
    RECURRING = "recurring"


class CronExpression:
    """Simplified cron expression parser.

    Supports:
      "* * * * *"   -> every minute
      "0 * * * *"   -> every hour (at minute 0)
      "0 0 * * *"   -> every day at midnight
      "*/5 * * * *" -> every 5 minutes
      "30 2 * * *"  -> daily at 02:30
    """

    def __init__(self, expr: str) -> None:
        parts = expr.strip().split()
        if len(parts) != 5:
            raise SchedulerError(
                f"Invalid cron expression: '{expr}' (expected 5 fields)",
                details={"expression": expr},
            )
        self.expr = expr
        self._minute = parts[0]
        self._hour = parts[1]
        self._day = parts[2]
        self._month = parts[3]
        self._weekday = parts[4]

    def next_run_after(self, after: datetime) -> datetime:
        """Calculate the next run time after the given datetime."""
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        for _ in range(60 * 24 * 366):  # search up to ~1 year
            if self._matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)

        raise SchedulerError(
            f"Could not find next run for cron '{self.expr}'",
            details={"expression": self.expr},
        )

    def _matches(self, dt: datetime) -> bool:
        return (
            self._field_matches(self._minute, dt.minute)
            and self._field_matches(self._hour, dt.hour)
            and self._field_matches(self._day, dt.day)
            and self._field_matches(self._month, dt.month)
            and self._field_matches(self._weekday, dt.weekday())
        )

    @staticmethod
    def _field_matches(field: str, value: int) -> bool:
        if field == "*":
            return True
        if field.startswith("*/"):
            step = int(field[2:])
            return value % step == 0
        return int(field) == value

    def __repr__(self) -> str:
        return f"CronExpression('{self.expr}')"


@dataclass
class ScheduledTask:
    """A task scheduled for future execution."""

    task: Task
    schedule_type: ScheduleType
    run_at: datetime | None = None
    cron: CronExpression | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    enabled: bool = True
    last_run: datetime | None = None


class TaskScheduler:
    """Scheduling engine for one-time and recurring tasks."""

    def __init__(self) -> None:
        self._scheduled: dict[str, ScheduledTask] = {}

    def schedule(self, task: Task, run_at: datetime) -> ScheduledTask:
        """Schedule a task to run at a specific time."""
        entry = ScheduledTask(
            task=task,
            schedule_type=ScheduleType.ONCE,
            run_at=run_at,
        )
        self._scheduled[entry.id] = entry
        return entry

    def schedule_recurring(self, task: Task, cron_expr: str) -> ScheduledTask:
        """Schedule a recurring task with a cron expression."""
        cron = CronExpression(cron_expr)
        entry = ScheduledTask(
            task=task,
            schedule_type=ScheduleType.RECURRING,
            cron=cron,
        )
        self._scheduled[entry.id] = entry
        return entry

    def get_due_tasks(self, now: datetime | None = None) -> list[ScheduledTask]:
        """Return all tasks that are due for execution."""
        now = now or datetime.now(UTC)
        due: list[ScheduledTask] = []

        for entry in self._scheduled.values():
            if not entry.enabled:
                continue
            if entry.schedule_type == ScheduleType.ONCE:
                if entry.run_at is not None and entry.run_at <= now and entry.last_run is None:
                    due.append(entry)
            elif entry.schedule_type == ScheduleType.RECURRING:
                if entry.cron is not None:
                    ref = entry.last_run or (now - timedelta(minutes=1))
                    next_run = entry.cron.next_run_after(ref)
                    if next_run <= now:
                        due.append(entry)

        return due

    def mark_run(self, scheduled_id: str, run_time: datetime | None = None) -> None:
        """Mark a scheduled task as having been run."""
        entry = self._scheduled.get(scheduled_id)
        if entry is None:
            return
        entry.last_run = run_time or datetime.now(UTC)
        if entry.schedule_type == ScheduleType.ONCE:
            entry.enabled = False

    def cancel(self, scheduled_id: str) -> bool:
        entry = self._scheduled.get(scheduled_id)
        if entry is None:
            return False
        entry.enabled = False
        return True

    def get(self, scheduled_id: str) -> ScheduledTask | None:
        return self._scheduled.get(scheduled_id)

    def list(self) -> list[ScheduledTask]:
        return list(self._scheduled.values())
