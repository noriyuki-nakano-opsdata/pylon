"""Production-grade experiment campaign orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pylon.approval import ApprovalManager
from pylon.approval.manager import ApprovalAlreadyDecidedError, ApprovalBindingMismatchError
from pylon.approval.types import ApprovalStatus, compute_approval_binding_hash
from pylon.bridges.codex import CodexBridge
from pylon.control_plane.workflow_service import WorkflowControlPlaneStore
from pylon.control_plane.adapters import StoreBackedApprovalStore, StoreBackedAuditRepository
from pylon.errors import ConcurrencyError, SandboxError
from pylon.experiments.context_bundle import (
    build_experiment_context_bundle,
    build_experiment_context_metadata,
    experiment_context_exclude_patterns,
    experiment_context_workspace_paths,
    summarize_recent_iterations_for_prompt,
)
from pylon.experiments.gitops import (
    changed_files,
    commit_all,
    create_branch_worktree,
    create_detached_worktree,
    delete_branch,
    diff_stat,
    ensure_worktree_excludes,
    force_branch_ref,
    remove_worktree,
    resolve_ref,
    resolve_repo_root,
    worktree_has_changes,
)
from pylon.experiments.metrics import (
    MetricSpec,
    extract_metric_value,
    metric_delta,
    metric_improvement_ratio,
    metric_is_better,
)
from pylon.experiments.sandboxing import ExperimentSandboxConfig, LocalPolicySandboxRunner
from pylon.repository.audit import default_hmac_key
from pylon.runtime.context_bundle import (
    materialize_context_bundle,
    mirror_context_bundle_to_workspace,
    sync_mutable_context_files_from_workspace,
)
from pylon.types import AutonomyLevel

logger = logging.getLogger(__name__)

CAMPAIGN_NAMESPACE = "experiment_campaigns"
ITERATION_NAMESPACE = "experiment_iterations"
LEASE_NAMESPACE = "experiment_worker_leases"
DEFAULT_CLEANUP_TTL_SECONDS = 21_600
EXPERIMENT_APPROVAL_TIMEOUT_SECONDS = 3_600
TERMINAL_CAMPAIGN_STATUSES = frozenset({"completed", "failed", "cancelled"})
IDLE_CAMPAIGN_STATUSES = frozenset({"draft", "paused", "waiting_approval", *TERMINAL_CAMPAIGN_STATUSES})
DEFAULT_STEP_TIMEOUT_SECONDS = 900
MAX_EVENT_HISTORY = 80
MAX_OUTPUT_CHARS = 4000
EXPERIMENT_APPROVAL_AGENT_ID = "experiment-governor"


@dataclass(frozen=True)
class PlannerSpec:
    """Normalized planner configuration."""

    type: str
    command: str = ""
    prompt: str = ""
    model: str = "codex-mini"
    approval_policy: str = "on-failure"
    sandbox_mode: str = "workspace-write"


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _slugify_identifier(value: str, *, prefix: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug:
        slug = f"{prefix}-{uuid.uuid4().hex[:6]}"
    return slug[:48]


def _trim_output(value: str, *, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...[truncated]"


def _campaign_runtime_root(campaign_id: str) -> Path:
    return Path(tempfile.gettempdir()) / "pylon-experiments" / campaign_id


def _iteration_record_id(campaign_id: str, sequence: int, *, baseline: bool) -> str:
    suffix = "baseline" if baseline else f"{sequence:03d}"
    return f"{campaign_id}:{suffix}"


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _positive_int_from_payload(value: Any, *, field_name: str, default: int) -> int:
    if value in (None, ""):
        return default
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Field '{field_name}' must be a positive integer")
    return value


def _bool_from_payload(value: Any, *, field_name: str, default: bool) -> bool:
    if value in (None, ""):
        return default
    if not isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be a boolean")
    return value


def _string_list_from_payload(value: Any, *, field_name: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"Field '{field_name}' must be a list of strings")
    normalized = [str(item).strip() for item in value if str(item).strip()]
    return normalized


def _int_list_from_payload(value: Any, *, field_name: str) -> list[int]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"Field '{field_name}' must be a list of integers")
    normalized: list[int] = []
    for item in value:
        if not isinstance(item, int):
            raise ValueError(f"Field '{field_name}' must be a list of integers")
        normalized.append(item)
    return normalized


def _sandbox_payload_from_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get("sandbox")
    source = dict(nested) if isinstance(nested, dict) else {}
    if "tier" not in source and payload.get("sandbox_tier") is not None:
        source["tier"] = payload.get("sandbox_tier")
    if "allow_internet" not in source and payload.get("sandbox_allow_internet") is not None:
        source["allow_internet"] = payload.get("sandbox_allow_internet")
    if "allowed_hosts" not in source and payload.get("sandbox_allowed_hosts") is not None:
        source["allowed_hosts"] = payload.get("sandbox_allowed_hosts")
    if "blocked_ports" not in source and payload.get("sandbox_blocked_ports") is not None:
        source["blocked_ports"] = payload.get("sandbox_blocked_ports")
    if "timeout_seconds" not in source and payload.get("sandbox_timeout_seconds") is not None:
        source["timeout_seconds"] = payload.get("sandbox_timeout_seconds")
    if "max_cpu_ms" not in source and payload.get("sandbox_max_cpu_ms") is not None:
        source["max_cpu_ms"] = payload.get("sandbox_max_cpu_ms")
    if "max_memory_bytes" not in source and payload.get("sandbox_max_memory_bytes") is not None:
        source["max_memory_bytes"] = payload.get("sandbox_max_memory_bytes")
    if "max_network_bytes" not in source and payload.get("sandbox_max_network_bytes") is not None:
        source["max_network_bytes"] = payload.get("sandbox_max_network_bytes")
    if "provider" not in source and payload.get("sandbox_provider") is not None:
        source["provider"] = payload.get("sandbox_provider")
    if "allow_internet" in source:
        source["allow_internet"] = _bool_from_payload(
            source.get("allow_internet"),
            field_name="sandbox.allow_internet",
            default=False,
        )
    if "allowed_hosts" in source:
        source["allowed_hosts"] = _string_list_from_payload(
            source.get("allowed_hosts"),
            field_name="sandbox.allowed_hosts",
        )
    if "blocked_ports" in source:
        source["blocked_ports"] = _int_list_from_payload(
            source.get("blocked_ports"),
            field_name="sandbox.blocked_ports",
        )
    return source


def _cleanup_payload_from_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get("cleanup")
    source = dict(nested) if isinstance(nested, dict) else {}
    if "runtime_ttl_seconds" not in source and payload.get("cleanup_runtime_ttl_seconds") is not None:
        source["runtime_ttl_seconds"] = payload.get("cleanup_runtime_ttl_seconds")
    if "preserve_failed_worktrees" not in source and payload.get("preserve_failed_worktrees") is not None:
        source["preserve_failed_worktrees"] = payload.get("preserve_failed_worktrees")
    return {
        "runtime_ttl_seconds": _positive_int_from_payload(
            source.get("runtime_ttl_seconds"),
            field_name="cleanup.runtime_ttl_seconds",
            default=DEFAULT_CLEANUP_TTL_SECONDS,
        ),
        "preserve_failed_worktrees": _bool_from_payload(
            source.get("preserve_failed_worktrees"),
            field_name="cleanup.preserve_failed_worktrees",
            default=False,
        ),
    }


def _approval_state_payload(
    *,
    required: bool,
    status: str,
    request_id: str | None = None,
    action: str | None = None,
    message: str | None = None,
    created_at: str | None = None,
    expires_at: str | None = None,
    decided_at: str | None = None,
    target_branch: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "required": required,
        "status": status,
        "request_id": request_id,
        "action": action,
        "message": message,
        "created_at": created_at,
        "expires_at": expires_at,
        "decided_at": decided_at,
        "target_branch": target_branch,
        "reason": reason,
    }


def _approval_tenant_id(payload: Mapping[str, Any]) -> str:
    context = dict(payload.get("context") or {})
    return str(payload.get("tenant_id") or context.get("tenant_id") or "default")


def _resource_usage_payload(resource_usage: Mapping[str, Any] | Any) -> dict[str, int]:
    if isinstance(resource_usage, Mapping):
        source = resource_usage
        return {
            "cpu_ms": int(source.get("cpu_ms", 0) or 0),
            "memory_bytes": int(source.get("memory_bytes", 0) or 0),
            "network_bytes_in": int(source.get("network_bytes_in", 0) or 0),
            "network_bytes_out": int(source.get("network_bytes_out", 0) or 0),
        }
    return {
        "cpu_ms": int(getattr(resource_usage, "cpu_ms", 0) or 0),
        "memory_bytes": int(getattr(resource_usage, "memory_bytes", 0) or 0),
        "network_bytes_in": int(getattr(resource_usage, "network_bytes_in", 0) or 0),
        "network_bytes_out": int(getattr(resource_usage, "network_bytes_out", 0) or 0),
    }


def validate_campaign_create_request(payload: Any) -> dict[str, Any]:
    """Validate and normalize a campaign creation payload."""

    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")

    objective = str(payload.get("objective", "")).strip()
    if not objective:
        raise ValueError("Field 'objective' is required")

    raw_repo_path = str(
        payload.get("repo_path")
        or payload.get("workspace")
        or payload.get("cwd")
        or ""
    ).strip()
    if not raw_repo_path:
        raise ValueError("Field 'repo_path' is required")
    repo_root = resolve_repo_root(raw_repo_path)

    benchmark_command = str(payload.get("benchmark_command", "")).strip()
    if not benchmark_command:
        raise ValueError("Field 'benchmark_command' is required")

    base_ref_input = str(payload.get("base_ref", "HEAD")).strip() or "HEAD"
    base_ref = resolve_ref(repo_root, base_ref_input)

    max_iterations = payload.get("max_iterations", 3)
    if not isinstance(max_iterations, int) or max_iterations <= 0:
        raise ValueError("Field 'max_iterations' must be a positive integer")

    planner = _parse_planner(payload)
    metric = MetricSpec.from_payload(_metric_payload_from_request(payload))

    benchmark_timeout = _validate_timeout(
        payload.get("benchmark_timeout_seconds"),
        field_name="benchmark_timeout_seconds",
    )
    checks_timeout = _validate_timeout(
        payload.get("checks_timeout_seconds"),
        field_name="checks_timeout_seconds",
    )
    planner_timeout = _validate_timeout(
        payload.get("planner_timeout_seconds"),
        field_name="planner_timeout_seconds",
    )

    checks_command = str(payload.get("checks_command", "")).strip()
    name = str(payload.get("name", "")).strip() or objective[:80]
    project_slug = str(payload.get("project_slug", "")).strip()
    promotion_branch = str(payload.get("promotion_branch", "")).strip()
    sandbox = ExperimentSandboxConfig.from_payload(_sandbox_payload_from_request(payload))
    cleanup = _cleanup_payload_from_request(payload)

    return {
        "name": name,
        "objective": objective,
        "project_slug": project_slug,
        "repo_path": str(Path(raw_repo_path).expanduser().resolve()),
        "repo_root": str(repo_root),
        "base_ref": base_ref,
        "base_ref_input": base_ref_input,
        "benchmark_command": benchmark_command,
        "benchmark_timeout_seconds": benchmark_timeout,
        "checks_command": checks_command,
        "checks_timeout_seconds": checks_timeout,
        "planner_timeout_seconds": planner_timeout,
        "planner": {
            "type": planner.type,
            "command": planner.command,
            "prompt": planner.prompt,
            "model": planner.model,
            "approval_policy": planner.approval_policy,
            "sandbox_mode": planner.sandbox_mode,
        },
        "metric": {
            "name": metric.name,
            "direction": metric.direction,
            "unit": metric.unit,
            "parser": metric.parser,
            "regex": metric.regex,
        },
        "max_iterations": max_iterations,
        "promotion_branch": promotion_branch,
        "sandbox": sandbox.to_payload(),
        "cleanup": cleanup,
    }


def build_campaign_detail_payload(
    campaign: Mapping[str, Any],
    iterations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the public campaign detail payload."""

    return {
        "campaign": dict(campaign),
        "iterations": [dict(item) for item in iterations],
        "count": len(iterations),
    }


class ExperimentCampaignManager:
    """Owns experiment campaign lifecycle, execution, and promotion."""

    def __init__(
        self,
        store: WorkflowControlPlaneStore,
        *,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._logger = logger_ or logger
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._owner = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._sandbox_runner = LocalPolicySandboxRunner()
        self._approval_manager = ApprovalManager(
            StoreBackedApprovalStore(store),
            StoreBackedAuditRepository(store, hmac_key=default_hmac_key()),
            timeout_seconds=EXPERIMENT_APPROVAL_TIMEOUT_SECONDS,
        )

    def create_campaign(
        self,
        payload: Any,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        normalized = validate_campaign_create_request(payload)
        now = _utc_now_iso()
        campaign_id = f"exp_{uuid.uuid4().hex[:24]}"
        runtime_root = _campaign_runtime_root(campaign_id)
        stable_branch = f"pylon/experiments/{campaign_id}/best"
        promotion_branch = (
            normalized["promotion_branch"]
            or f"pylon/experiments/promoted/{campaign_id}"
        )
        campaign = {
            "id": campaign_id,
            "tenant_id": tenant_id,
            "project_slug": normalized["project_slug"],
            "name": normalized["name"],
            "objective": normalized["objective"],
            "status": "draft",
            "repo_path": normalized["repo_path"],
            "repo_root": normalized["repo_root"],
            "base_ref": normalized["base_ref"],
            "base_ref_input": normalized["base_ref_input"],
            "metric": dict(normalized["metric"]),
            "planner": dict(normalized["planner"]),
            "benchmark_command": normalized["benchmark_command"],
            "benchmark_timeout_seconds": normalized["benchmark_timeout_seconds"],
            "checks_command": normalized["checks_command"],
            "checks_timeout_seconds": normalized["checks_timeout_seconds"],
            "planner_timeout_seconds": normalized["planner_timeout_seconds"],
            "max_iterations": normalized["max_iterations"],
            "sandbox": dict(normalized["sandbox"]),
            "cleanup": dict(normalized["cleanup"]),
            "progress": {
                "baseline_measured": False,
                "completed_iterations": 0,
                "failed_iterations": 0,
                "max_iterations": normalized["max_iterations"],
            },
            "baseline": None,
            "best": None,
            "stable_branch": stable_branch,
            "promotion": {
                "branch": promotion_branch,
                "status": "not_promoted",
                "promoted_ref": None,
                "promoted_at": None,
                "approval_request_id": None,
            },
            "control": {
                "pause_requested": False,
                "cancel_requested": False,
            },
            "approval": _approval_state_payload(
                required=False,
                status="not_required",
            ),
            "runtime_root": str(runtime_root),
            "context_bundle": build_experiment_context_metadata(
                {
                    "id": campaign_id,
                    "runtime_root": str(runtime_root),
                    "checks_command": normalized["checks_command"],
                }
            ),
            "current_iteration_id": None,
            "runner": None,
            "events": [
                {
                    "timestamp": now,
                    "level": "info",
                    "kind": "campaign_created",
                    "message": "Experiment campaign created.",
                }
            ],
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "last_error": None,
        }
        stored = self._store.put_surface_record(
            CAMPAIGN_NAMESPACE,
            campaign_id,
            campaign,
        )
        self._refresh_context_bundle(stored, iterations=[])
        return build_campaign_detail_payload(stored, [])

    def list_campaigns(
        self,
        *,
        tenant_id: str,
        project_slug: str = "",
    ) -> list[dict[str, Any]]:
        campaigns = [
            dict(record)
            for record in self._store.list_surface_records(CAMPAIGN_NAMESPACE, tenant_id=tenant_id)
        ]
        if project_slug:
            campaigns = [
                record
                for record in campaigns
                if str(record.get("project_slug", "")) == project_slug
            ]
        campaigns.sort(
            key=lambda item: (
                str(item.get("updated_at", item.get("created_at", ""))),
                str(item.get("id", "")),
            ),
            reverse=True,
        )
        return campaigns

    def get_campaign_detail(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            return None
        return build_campaign_detail_payload(
            campaign,
            self.list_iterations(campaign_id, tenant_id=tenant_id),
        )

    def list_iterations(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        iterations = [
            dict(record)
            for record in self._store.list_surface_records(ITERATION_NAMESPACE, tenant_id=tenant_id)
            if str(record.get("campaign_id", "")) == campaign_id
        ]
        iterations.sort(
            key=lambda item: (
                int(item.get("sequence", 0)),
                str(item.get("created_at", "")),
                str(item.get("id", "")),
            )
        )
        return iterations

    def start_campaign(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            raise KeyError(campaign_id)
        status = str(campaign.get("status", "draft"))
        if status == "running":
            return build_campaign_detail_payload(
                campaign,
                self.list_iterations(campaign_id, tenant_id=tenant_id),
            )
        if status not in {"draft", "paused", "waiting_approval"}:
            msg = f"Campaign cannot be started from status {status}"
            raise ValueError(msg)

        approval_required = (
            status != "paused" or not campaign.get("started_at")
        ) and self._approval_required_for_action(campaign, action="start")
        if approval_required:
            campaign, awaiting_approval = self._ensure_campaign_approval(
                campaign,
                tenant_id=tenant_id,
                action="start",
            )
            if awaiting_approval:
                return build_campaign_detail_payload(
                    campaign,
                    self.list_iterations(campaign_id, tenant_id=tenant_id),
                )

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            now = _utc_now_iso()
            current["status"] = "running"
            current["started_at"] = current.get("started_at") or now
            current["completed_at"] = None
            current["last_error"] = None
            control = dict(current.get("control") or {})
            control["pause_requested"] = False
            control["cancel_requested"] = False
            current["control"] = control
            current["approval"] = self._campaign_approval_state(
                current,
                required=approval_required,
                status="approved" if approval_required else "not_required",
                action="start" if approval_required else None,
                message=(
                    self._approval_message(current, action="start")
                    if approval_required
                    else None
                ),
                request_id=str((current.get("approval") or {}).get("request_id") or "") or None,
                target_branch=None,
                decided_at=_utc_now_iso() if approval_required else None,
                reason=None,
            )
            current["events"] = _append_event(
                current.get("events"),
                kind="campaign_started",
                message="Experiment campaign started.",
            )
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        self._ensure_thread(campaign_id)
        return build_campaign_detail_payload(
            updated,
            self.list_iterations(campaign_id, tenant_id=tenant_id),
        )

    def pause_campaign(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            raise KeyError(campaign_id)
        if str(campaign.get("status", "")) != "running":
            return build_campaign_detail_payload(
                campaign,
                self.list_iterations(campaign_id, tenant_id=tenant_id),
            )

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            control = dict(current.get("control") or {})
            control["pause_requested"] = True
            current["control"] = control
            current["events"] = _append_event(
                current.get("events"),
                kind="pause_requested",
                message="Pause requested. Campaign will pause after the active iteration.",
            )
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        return build_campaign_detail_payload(
            updated,
            self.list_iterations(campaign_id, tenant_id=tenant_id),
        )

    def resume_campaign(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        return self.start_campaign(campaign_id, tenant_id=tenant_id)

    def cancel_campaign(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            raise KeyError(campaign_id)
        if str(campaign.get("status", "")) in TERMINAL_CAMPAIGN_STATUSES:
            return build_campaign_detail_payload(
                campaign,
                self.list_iterations(campaign_id, tenant_id=tenant_id),
            )

        if str(campaign.get("status", "")) in {"draft", "waiting_approval"}:
            self._reject_pending_approval_if_needed(
                campaign,
                actor="system",
                reason="Experiment campaign cancelled before execution started.",
            )
            updated = self._mutate_campaign(
                campaign_id,
                tenant_id=tenant_id,
                mutate=(
                    lambda current: self._set_campaign_approval_outcome(
                        self._transition_campaign(
                            current,
                            status="cancelled",
                            message="Experiment campaign cancelled before execution started.",
                        ),
                        action="start",
                        status="rejected",
                        message="Start approval was rejected because the campaign was cancelled.",
                        target_branch="",
                        reason="Experiment campaign cancelled before execution started.",
                        next_status="cancelled",
                    )
                    if str(campaign.get("status", "")) == "waiting_approval"
                    else self._transition_campaign(
                        current,
                        status="cancelled",
                        message="Experiment campaign cancelled before execution started.",
                    )
                ),
            )
            return build_campaign_detail_payload(
                updated,
                self.list_iterations(campaign_id, tenant_id=tenant_id),
            )

        if str(campaign.get("status", "")) == "paused":
            updated = self._mutate_campaign(
                campaign_id,
                tenant_id=tenant_id,
                mutate=lambda current: self._transition_campaign(
                    current,
                    status="cancelled",
                    message="Experiment campaign cancelled.",
                ),
            )
            self._clear_lease(campaign_id)
            return build_campaign_detail_payload(
                updated,
                self.list_iterations(campaign_id, tenant_id=tenant_id),
            )

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            control = dict(current.get("control") or {})
            control["cancel_requested"] = True
            current["control"] = control
            current["events"] = _append_event(
                current.get("events"),
                kind="cancel_requested",
                message="Cancellation requested. Campaign will stop after the active iteration.",
            )
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        return build_campaign_detail_payload(
            updated,
            self.list_iterations(campaign_id, tenant_id=tenant_id),
        )

    def promote_campaign(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
        branch_name: str = "",
    ) -> dict[str, Any]:
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            raise KeyError(campaign_id)
        best = campaign.get("best")
        if not isinstance(best, dict) or not best.get("ref"):
            raise ValueError("Campaign has no promotable best candidate")
        target_branch = branch_name.strip() or str(campaign.get("promotion", {}).get("branch", "")).strip()
        if not target_branch:
            raise ValueError("Promotion branch is not configured")
        campaign, awaiting_approval = self._ensure_campaign_approval(
            campaign,
            tenant_id=tenant_id,
            action="promote",
            target_branch=target_branch,
        )
        if awaiting_approval:
            return build_campaign_detail_payload(
                campaign,
                self.list_iterations(campaign_id, tenant_id=tenant_id),
            )
        force_branch_ref(str(campaign.get("repo_root", "")), target_branch, str(best["ref"]))

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            promotion = dict(current.get("promotion") or {})
            promotion["branch"] = target_branch
            promotion["status"] = "promoted"
            promotion["promoted_ref"] = str(best["ref"])
            promotion["promoted_at"] = _utc_now_iso()
            promotion["approval_request_id"] = str((current.get("approval") or {}).get("request_id") or "") or None
            current["promotion"] = promotion
            current["approval"] = self._campaign_approval_state(
                current,
                required=True,
                status="approved",
                action="promote",
                message=self._approval_message(current, action="promote"),
                request_id=str((current.get("approval") or {}).get("request_id") or "") or None,
                target_branch=target_branch,
                decided_at=_utc_now_iso(),
            )
            current["events"] = _append_event(
                current.get("events"),
                kind="campaign_promoted",
                message=f"Promoted best candidate to branch {target_branch}.",
            )
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        return build_campaign_detail_payload(
            updated,
            self.list_iterations(campaign_id, tenant_id=tenant_id),
        )

    def approve_pending_approval(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        approval_payload = self._store.get_approval_record(approval_id)
        if approval_payload is None:
            raise KeyError(f"Approval request not found: {approval_id}")
        if approval_payload.get("status") != ApprovalStatus.PENDING.value:
            raise ValueError(f"Approval request already decided: {approval_id}")
        approval_tenant_id = _approval_tenant_id(approval_payload)
        if approval_tenant_id != tenant_id:
            raise KeyError(f"Approval request not found: {approval_id}")
        context = dict(approval_payload.get("context") or {})
        campaign_id = str(context.get("campaign_id") or context.get("resource_id") or "")
        action = str(context.get("action_scope") or "")
        target_branch = str(context.get("target_branch") or "")
        if not campaign_id or action not in {"start", "promote"}:
            raise ValueError(f"Unsupported experiment approval context: {approval_id}")
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            raise KeyError(f"Experiment campaign not found: {campaign_id}")
        binding = self._build_campaign_approval_binding(
            campaign,
            action=action,
            target_branch=target_branch,
        )
        self._validate_pending_approval_binding(approval_payload, binding=binding)
        self._run_approval_coro(self._approval_manager.approve(approval_id, actor, comment=reason or ""))
        self._annotate_approval_record(approval_id, tenant_id=tenant_id, reason=reason, decided=True)
        if action == "start":
            detail = self.start_campaign(campaign_id, tenant_id=tenant_id)
            return detail
        detail = self._promote_campaign_after_approval(
            campaign_id,
            tenant_id=tenant_id,
            branch_name=target_branch,
        )
        return detail

    def reject_pending_approval(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        approval_payload = self._store.get_approval_record(approval_id)
        if approval_payload is None:
            raise KeyError(f"Approval request not found: {approval_id}")
        if approval_payload.get("status") != ApprovalStatus.PENDING.value:
            raise ValueError(f"Approval request already decided: {approval_id}")
        approval_tenant_id = _approval_tenant_id(approval_payload)
        if approval_tenant_id != tenant_id:
            raise KeyError(f"Approval request not found: {approval_id}")
        context = dict(approval_payload.get("context") or {})
        campaign_id = str(context.get("campaign_id") or context.get("resource_id") or "")
        action = str(context.get("action_scope") or "")
        target_branch = str(context.get("target_branch") or "")
        if not campaign_id or action not in {"start", "promote"}:
            raise ValueError(f"Unsupported experiment approval context: {approval_id}")
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            raise KeyError(f"Experiment campaign not found: {campaign_id}")
        self._run_approval_coro(self._approval_manager.reject(approval_id, actor, reason or ""))
        self._annotate_approval_record(approval_id, tenant_id=tenant_id, reason=reason, decided=True)
        if action == "start":
            updated = self._mutate_campaign(
                campaign_id,
                tenant_id=tenant_id,
                mutate=lambda current: self._set_campaign_approval_outcome(
                    current,
                    action="start",
                    status="rejected",
                    message="Start approval was rejected.",
                    target_branch=target_branch,
                    reason=reason,
                    next_status="draft",
                ),
            )
        else:
            updated = self._mutate_campaign(
                campaign_id,
                tenant_id=tenant_id,
                mutate=lambda current: self._set_campaign_approval_outcome(
                    current,
                    action="promote",
                    status="rejected",
                    message="Promotion approval was rejected.",
                    target_branch=target_branch,
                    reason=reason,
                    next_status=str(current.get("status", "")),
                    promotion_status="rejected",
                ),
            )
        return build_campaign_detail_payload(
            updated,
            self.list_iterations(campaign_id, tenant_id=tenant_id),
        )

    def cleanup_stale_resources(self) -> dict[str, int]:
        campaigns = [
            dict(record)
            for record in self._store.list_surface_records(CAMPAIGN_NAMESPACE)
        ]
        campaign_by_id = {
            str(record.get("id", "")): record
            for record in campaigns
            if str(record.get("id", ""))
        }
        stats = {
            "cleared_leases": 0,
            "removed_runtime_roots": 0,
            "removed_orphan_runtime_roots": 0,
            "removed_worktrees": 0,
            "removed_branches": 0,
        }
        now = time.time()

        for lease in self._store.list_surface_records(LEASE_NAMESPACE):
            campaign_id = str(lease.get("id", ""))
            campaign = campaign_by_id.get(campaign_id)
            if campaign is None or str(campaign.get("status", "")) != "running":
                if self._store.delete_surface_record(LEASE_NAMESPACE, campaign_id):
                    stats["cleared_leases"] += 1

        for campaign in campaigns:
            campaign_id = str(campaign.get("id", ""))
            status = str(campaign.get("status", ""))
            if status not in IDLE_CAMPAIGN_STATUSES:
                continue
            cleanup = dict(campaign.get("cleanup") or {})
            ttl_seconds = _positive_int_from_payload(
                cleanup.get("runtime_ttl_seconds"),
                field_name="cleanup.runtime_ttl_seconds",
                default=DEFAULT_CLEANUP_TTL_SECONDS,
            )
            updated_at = _parse_iso_datetime(
                campaign.get("updated_at")
                or campaign.get("completed_at")
                or campaign.get("created_at")
            )
            if updated_at is None or (now - updated_at.timestamp()) < ttl_seconds:
                continue
            repo_root = str(campaign.get("repo_root", ""))
            stable_branch = str(campaign.get("stable_branch", ""))
            promotion_branch = str((campaign.get("promotion") or {}).get("branch", ""))
            for iteration in self.list_iterations(
                campaign_id,
                tenant_id=str(campaign.get("tenant_id", "default") or "default"),
            ):
                worktree_path = str(iteration.get("worktree_path", "")).strip()
                branch_name = str(iteration.get("branch", "")).strip()
                if worktree_path and Path(worktree_path).exists():
                    try:
                        remove_worktree(repo_root, Path(worktree_path))
                        stats["removed_worktrees"] += 1
                    except Exception:
                        self._logger.exception(
                            "experiment_campaign_cleanup_worktree_failed campaign_id=%s path=%s",
                            campaign_id,
                            worktree_path,
                        )
                if (
                    branch_name
                    and branch_name != stable_branch
                    and branch_name != promotion_branch
                ):
                    try:
                        delete_branch(repo_root, branch_name)
                        stats["removed_branches"] += 1
                    except Exception:
                        self._logger.debug(
                            "experiment_campaign_cleanup_branch_skipped campaign_id=%s branch=%s",
                            campaign_id,
                            branch_name,
                        )
            runtime_root = Path(str(campaign.get("runtime_root", "")).strip())
            if runtime_root.exists():
                try:
                    shutil.rmtree(runtime_root)
                    stats["removed_runtime_roots"] += 1
                except FileNotFoundError:
                    pass
                except Exception:
                    self._logger.exception(
                        "experiment_campaign_cleanup_runtime_failed campaign_id=%s path=%s",
                        campaign_id,
                        runtime_root,
                    )

        runtime_base = Path(tempfile.gettempdir()) / "pylon-experiments"
        if runtime_base.exists():
            for child in runtime_base.iterdir():
                if not child.is_dir():
                    continue
                if child.name in campaign_by_id:
                    continue
                if (now - child.stat().st_mtime) < DEFAULT_CLEANUP_TTL_SECONDS:
                    continue
                try:
                    shutil.rmtree(child)
                    stats["removed_orphan_runtime_roots"] += 1
                except FileNotFoundError:
                    pass
                except Exception:
                    self._logger.exception(
                        "experiment_campaign_cleanup_orphan_runtime_failed path=%s",
                        child,
                    )
        return stats

    def _refresh_context_bundle(
        self,
        campaign: Mapping[str, Any],
        *,
        iterations: list[dict[str, Any]] | None = None,
    ) -> Any | None:
        campaign_id = str(campaign.get("id", "")).strip()
        if not campaign_id:
            return None
        tenant_id = str(campaign.get("tenant_id", "default") or "default")
        iteration_records = (
            iterations
            if iterations is not None
            else self.list_iterations(campaign_id, tenant_id=tenant_id)
        )
        try:
            bundle = build_experiment_context_bundle(campaign, iteration_records)
            materialize_context_bundle(bundle.layout, bundle.files)
            return bundle
        except Exception:
            self._logger.exception(
                "experiment_campaign_context_bundle_refresh_failed campaign_id=%s",
                campaign_id,
            )
            return None

    def _prepare_context_bundle_workspace(
        self,
        campaign: Mapping[str, Any],
        *,
        worktree_path: Path,
    ) -> None:
        bundle = self._refresh_context_bundle(campaign)
        if bundle is None:
            return
        try:
            ensure_worktree_excludes(
                worktree_path,
                experiment_context_exclude_patterns(campaign),
            )
            mirror_context_bundle_to_workspace(
                bundle.layout,
                workspace_root=worktree_path,
            )
        except Exception:
            self._logger.exception(
                "experiment_campaign_context_bundle_workspace_failed campaign_id=%s path=%s",
                campaign.get("id", ""),
                worktree_path,
            )

    def _sync_context_bundle_from_workspace(
        self,
        campaign: Mapping[str, Any],
        *,
        worktree_path: Path,
    ) -> None:
        bundle = self._refresh_context_bundle(campaign)
        if bundle is None:
            return
        try:
            sync_mutable_context_files_from_workspace(
                bundle.layout,
                workspace_root=worktree_path,
                files=bundle.files,
            )
        except Exception:
            self._logger.exception(
                "experiment_campaign_context_bundle_sync_failed campaign_id=%s path=%s",
                campaign.get("id", ""),
                worktree_path,
            )

    def _approval_required_for_action(
        self,
        campaign: Mapping[str, Any],
        *,
        action: str,
    ) -> bool:
        return bool(self._approval_reasons(campaign, action=action))

    def _approval_reasons(
        self,
        campaign: Mapping[str, Any],
        *,
        action: str,
    ) -> list[str]:
        if action == "promote":
            return ["promotion writes a persistent git branch"]
        if action != "start":
            return []
        sandbox = ExperimentSandboxConfig.from_payload(dict(campaign.get("sandbox") or {}))
        planner = PlannerSpec(**dict(campaign.get("planner") or {}))
        reasons: list[str] = []
        if sandbox.tier.value == "none":
            reasons.append("sandbox tier is host-level")
        if sandbox.allow_internet:
            reasons.append("sandbox allows internet egress")
        if planner.type == "codex":
            reasons.append("planner delegates code changes to Codex")
        return reasons

    def _approval_message(
        self,
        campaign: Mapping[str, Any],
        *,
        action: str,
    ) -> str:
        reasons = self._approval_reasons(campaign, action=action)
        if action == "promote":
            return "Promotion requires approval because it updates a persistent branch."
        if not reasons:
            return "Approval required."
        return "Approval required because " + "; ".join(reasons) + "."

    def _campaign_approval_state(
        self,
        campaign: Mapping[str, Any],
        *,
        required: bool,
        status: str,
        action: str | None,
        message: str | None,
        request_id: str | None,
        target_branch: str | None = None,
        decided_at: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        approval_record = self._store.get_approval_record(request_id) if request_id else None
        created_at = str((approval_record or {}).get("created_at") or "") or None
        expires_at = str((approval_record or {}).get("expires_at") or "") or None
        decided_value = decided_at or (str((approval_record or {}).get("decided_at") or "") or None)
        return _approval_state_payload(
            required=required,
            status=status,
            request_id=request_id,
            action=action,
            message=message,
            created_at=created_at,
            expires_at=expires_at,
            decided_at=decided_value,
            target_branch=target_branch,
            reason=reason,
        )

    def _ensure_campaign_approval(
        self,
        campaign: Mapping[str, Any],
        *,
        tenant_id: str,
        action: str,
        target_branch: str = "",
    ) -> tuple[dict[str, Any], bool]:
        campaign_id = str(campaign.get("id", ""))
        binding = self._build_campaign_approval_binding(
            campaign,
            action=action,
            target_branch=target_branch,
        )
        current_approval = self._current_campaign_approval_record(campaign)
        pending_status = "waiting_approval" if action == "start" else str(campaign.get("status", "draft"))
        if current_approval is not None and self._approval_matches_binding(current_approval, binding=binding):
            current_status = str(current_approval.get("status", ""))
            if current_status == ApprovalStatus.PENDING.value:
                updated = self._mutate_campaign(
                    campaign_id,
                    tenant_id=tenant_id,
                    mutate=lambda current: self._set_campaign_approval_pending(
                        current,
                        action=action,
                        message=self._approval_message(current, action=action),
                        target_branch=target_branch,
                        request_id=str(current_approval.get("id", "")),
                        next_status=pending_status,
                    ),
                )
                return updated, True
            if current_status == ApprovalStatus.APPROVED.value:
                updated = self._mutate_campaign(
                    campaign_id,
                    tenant_id=tenant_id,
                    mutate=lambda current: self._set_campaign_approval_cached(
                        current,
                        action=action,
                        status="approved",
                        message=self._approval_message(current, action=action),
                        target_branch=target_branch,
                        request_id=str(current_approval.get("id", "")),
                    ),
                )
                return updated, False

        request = self._run_approval_coro(
            self._approval_manager.submit_request(
                agent_id=EXPERIMENT_APPROVAL_AGENT_ID,
                action=f"experiment.{action}",
                autonomy_level=AutonomyLevel.A3,
                context={
                    **binding["context"],
                    "binding_plan": binding["plan"],
                    "binding_effect_envelope": binding["effect_envelope"],
                },
                plan=binding["plan"],
                effect_envelope=binding["effect_envelope"],
            )
        )
        self._annotate_approval_record(request.id, tenant_id=tenant_id)
        updated = self._mutate_campaign(
            campaign_id,
            tenant_id=tenant_id,
            mutate=lambda current: self._set_campaign_approval_pending(
                current,
                action=action,
                message=self._approval_message(current, action=action),
                target_branch=target_branch,
                request_id=request.id,
                next_status=pending_status,
            ),
        )
        return updated, True

    def _promote_campaign_after_approval(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
        branch_name: str,
    ) -> dict[str, Any]:
        campaign = self._get_campaign(campaign_id, tenant_id=tenant_id)
        if campaign is None:
            raise KeyError(campaign_id)
        best = campaign.get("best")
        if not isinstance(best, dict) or not best.get("ref"):
            raise ValueError("Campaign has no promotable best candidate")
        target_branch = branch_name.strip() or str((campaign.get("promotion") or {}).get("branch", "")).strip()
        if not target_branch:
            raise ValueError("Promotion branch is not configured")
        force_branch_ref(str(campaign.get("repo_root", "")), target_branch, str(best["ref"]))
        updated = self._mutate_campaign(
            campaign_id,
            tenant_id=tenant_id,
            mutate=lambda current: self._set_campaign_approval_outcome(
                current,
                action="promote",
                status="approved",
                message=f"Promoted best candidate to branch {target_branch}.",
                target_branch=target_branch,
                reason=None,
                next_status=str(current.get("status", "")),
                promotion_status="promoted",
                promoted_ref=str(best["ref"]),
            ),
        )
        return build_campaign_detail_payload(
            updated,
            self.list_iterations(campaign_id, tenant_id=tenant_id),
        )

    def _build_campaign_approval_binding(
        self,
        campaign: Mapping[str, Any],
        *,
        action: str,
        target_branch: str = "",
    ) -> dict[str, Any]:
        campaign_id = str(campaign.get("id", ""))
        tenant_id = str(campaign.get("tenant_id", "default") or "default")
        if action == "start":
            sandbox = dict(campaign.get("sandbox") or {})
            planner = dict(campaign.get("planner") or {})
            return {
                "action": "experiment.start",
                "context": {
                    "resource_type": "experiment_campaign",
                    "resource_id": campaign_id,
                    "campaign_id": campaign_id,
                    "tenant_id": tenant_id,
                    "project_slug": str(campaign.get("project_slug", "")),
                    "action_scope": "start",
                },
                "plan": {
                    "campaign_id": campaign_id,
                    "repo_root": str(campaign.get("repo_root", "")),
                    "base_ref": str(campaign.get("base_ref", "")),
                    "objective": str(campaign.get("objective", "")),
                    "planner": planner,
                    "sandbox": sandbox,
                    "benchmark_command": str(campaign.get("benchmark_command", "")),
                    "checks_command": str(campaign.get("checks_command", "")),
                },
                "effect_envelope": {
                    "resource_type": "experiment_campaign",
                    "resource_id": campaign_id,
                    "tenant_id": tenant_id,
                    "sandbox_tier": str(sandbox.get("tier", "")),
                    "allow_internet": bool(sandbox.get("allow_internet", False)),
                },
            }
        if action != "promote":
            raise ValueError(f"Unsupported experiment approval action: {action}")
        best = campaign.get("best")
        best_ref = str((best or {}).get("ref", ""))
        branch = target_branch.strip() or str((campaign.get("promotion") or {}).get("branch", "")).strip()
        return {
            "action": "experiment.promote",
            "context": {
                "resource_type": "experiment_campaign",
                "resource_id": campaign_id,
                "campaign_id": campaign_id,
                "tenant_id": tenant_id,
                "project_slug": str(campaign.get("project_slug", "")),
                "action_scope": "promote",
                "target_branch": branch,
            },
            "plan": {
                "campaign_id": campaign_id,
                "best_ref": best_ref,
                "target_branch": branch,
                "stable_branch": str(campaign.get("stable_branch", "")),
            },
            "effect_envelope": {
                "resource_type": "experiment_campaign",
                "resource_id": campaign_id,
                "tenant_id": tenant_id,
                "target_branch": branch,
                "promoted_ref": best_ref,
            },
        }

    def _current_campaign_approval_record(
        self,
        campaign: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        approval_id = str((campaign.get("approval") or {}).get("request_id") or "")
        if not approval_id:
            return None
        record = self._store.get_approval_record(approval_id)
        return None if record is None else dict(record)

    def _approval_matches_binding(
        self,
        approval_payload: Mapping[str, Any],
        *,
        binding: Mapping[str, Any],
    ) -> bool:
        expected_plan_hash = compute_approval_binding_hash(binding["plan"])
        expected_effect_hash = compute_approval_binding_hash(binding["effect_envelope"])
        return (
            str(approval_payload.get("plan_hash", "")) == expected_plan_hash
            and str(approval_payload.get("effect_hash", "")) == expected_effect_hash
        )

    def _validate_pending_approval_binding(
        self,
        approval_payload: Mapping[str, Any],
        *,
        binding: Mapping[str, Any],
    ) -> None:
        if self._approval_matches_binding(approval_payload, binding=binding):
            return
        raise ApprovalBindingMismatchError(
            "Experiment approval invalidated by campaign drift",
            details={
                "approval_id": str(approval_payload.get("id", "")),
                "expected_plan_hash": str(approval_payload.get("plan_hash", "")),
                "actual_plan_hash": compute_approval_binding_hash(binding["plan"]),
                "expected_effect_hash": str(approval_payload.get("effect_hash", "")),
                "actual_effect_hash": compute_approval_binding_hash(binding["effect_envelope"]),
            },
        )

    def _annotate_approval_record(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        reason: str | None = None,
        decided: bool = False,
    ) -> None:
        approval_payload = self._store.get_approval_record(approval_id)
        if approval_payload is None:
            return
        approval_payload = dict(approval_payload)
        approval_payload["tenant_id"] = tenant_id
        approval_payload["resource_type"] = "experiment_campaign"
        approval_payload["resource_id"] = str((approval_payload.get("context") or {}).get("campaign_id") or "")
        if decided:
            approval_payload["decided_at"] = approval_payload.get("decided_at") or _utc_now_iso()
            if reason:
                approval_payload["reason"] = reason
        self._store.put_approval_record(approval_payload)

    def _run_approval_coro(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def _reject_pending_approval_if_needed(
        self,
        campaign: Mapping[str, Any],
        *,
        actor: str,
        reason: str,
    ) -> None:
        approval_payload = self._current_campaign_approval_record(campaign)
        if approval_payload is None or approval_payload.get("status") != ApprovalStatus.PENDING.value:
            return
        try:
            self._run_approval_coro(
                self._approval_manager.reject(
                    str(approval_payload.get("id", "")),
                    actor,
                    reason,
                )
            )
            self._annotate_approval_record(
                str(approval_payload.get("id", "")),
                tenant_id=str(campaign.get("tenant_id", "default") or "default"),
                reason=reason,
                decided=True,
            )
        except ApprovalAlreadyDecidedError:
            return

    def _set_campaign_approval_pending(
        self,
        current: dict[str, Any],
        *,
        action: str,
        message: str,
        target_branch: str,
        request_id: str,
        next_status: str,
    ) -> dict[str, Any]:
        current["approval"] = self._campaign_approval_state(
            current,
            required=True,
            status="pending",
            action=action,
            message=message,
            request_id=request_id,
            target_branch=target_branch or None,
        )
        current["status"] = next_status
        if action == "promote":
            promotion = dict(current.get("promotion") or {})
            promotion["branch"] = target_branch or str(promotion.get("branch", ""))
            promotion["status"] = "approval_pending"
            promotion["approval_request_id"] = request_id
            current["promotion"] = promotion
        current["events"] = _append_event(
            current.get("events"),
            kind="approval_requested",
            message=message,
        )
        return current

    def _set_campaign_approval_cached(
        self,
        current: dict[str, Any],
        *,
        action: str,
        status: str,
        message: str,
        target_branch: str,
        request_id: str,
    ) -> dict[str, Any]:
        current["approval"] = self._campaign_approval_state(
            current,
            required=True,
            status=status,
            action=action,
            message=message,
            request_id=request_id,
            target_branch=target_branch or None,
        )
        return current

    def _set_campaign_approval_outcome(
        self,
        current: dict[str, Any],
        *,
        action: str,
        status: str,
        message: str,
        target_branch: str,
        reason: str | None,
        next_status: str,
        promotion_status: str | None = None,
        promoted_ref: str | None = None,
    ) -> dict[str, Any]:
        request_id = str((current.get("approval") or {}).get("request_id") or "") or None
        current["approval"] = self._campaign_approval_state(
            current,
            required=True,
            status=status,
            action=action,
            message=self._approval_message(current, action=action),
            request_id=request_id,
            target_branch=target_branch or None,
            decided_at=_utc_now_iso(),
            reason=reason,
        )
        current["status"] = next_status
        if action == "promote":
            promotion = dict(current.get("promotion") or {})
            promotion["branch"] = target_branch or str(promotion.get("branch", ""))
            promotion["approval_request_id"] = request_id
            if promotion_status is not None:
                promotion["status"] = promotion_status
            if promoted_ref is not None:
                promotion["promoted_ref"] = promoted_ref
                promotion["promoted_at"] = _utc_now_iso()
            current["promotion"] = promotion
        current["last_error"] = reason if status == "rejected" else None
        current["events"] = _append_event(
            current.get("events"),
            kind=f"approval_{status}",
            message=message,
            level="error" if status == "rejected" else "info",
        )
        return current

    def reconcile_orphaned_campaigns(self) -> int:
        recovered = 0
        for record in self._store.list_surface_records(CAMPAIGN_NAMESPACE):
            if str(record.get("status", "")) != "running":
                continue
            campaign_id = str(record.get("id", ""))
            with self._lock:
                thread = self._threads.get(campaign_id)
            if thread is not None and thread.is_alive():
                continue
            tenant_id = str(record.get("tenant_id", "default") or "default")
            recovered += 1
            self._mutate_campaign(
                campaign_id,
                tenant_id=tenant_id,
                mutate=lambda current: self._transition_campaign(
                    current,
                    status="failed",
                    message=(
                        "Campaign worker was no longer running. "
                        "Marked failed during orphan reconciliation."
                    ),
                    error=(
                        "Experiment campaign worker exited before a terminal "
                        "state was persisted."
                    ),
                ),
            )
            self._clear_lease(campaign_id)
        return recovered

    def shutdown(self) -> None:
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=0.2)

    def _ensure_thread(self, campaign_id: str) -> None:
        with self._lock:
            existing = self._threads.get(campaign_id)
            if existing is not None and existing.is_alive():
                return
            thread = threading.Thread(
                target=self._execute_campaign,
                kwargs={"campaign_id": campaign_id},
                name=f"pylon-exp-{campaign_id[-8:]}",
                daemon=True,
            )
            self._threads[campaign_id] = thread
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._threads.pop(campaign_id, None)
            raise

    def _execute_campaign(self, *, campaign_id: str) -> None:
        try:
            while True:
                campaign = self._get_campaign(campaign_id)
                if campaign is None:
                    return
                tenant_id = str(campaign.get("tenant_id", "default") or "default")
                status = str(campaign.get("status", "draft"))
                if status != "running":
                    return
                self._heartbeat(campaign_id, tenant_id=tenant_id)
                control = dict(campaign.get("control") or {})
                if control.get("cancel_requested"):
                    updated = self._mutate_campaign(
                        campaign_id,
                        tenant_id=tenant_id,
                        mutate=lambda current: self._transition_campaign(
                            current,
                            status="cancelled",
                            message="Experiment campaign cancelled.",
                        ),
                    )
                    self._refresh_context_bundle(updated)
                    self._clear_lease(campaign_id)
                    return
                if control.get("pause_requested"):
                    updated = self._mutate_campaign(
                        campaign_id,
                        tenant_id=tenant_id,
                        mutate=lambda current: self._transition_campaign(
                            current,
                            status="paused",
                            message="Experiment campaign paused.",
                        ),
                    )
                    self._refresh_context_bundle(updated)
                    self._clear_lease(campaign_id)
                    return

                progress = dict(campaign.get("progress") or {})
                if not progress.get("baseline_measured"):
                    self._run_iteration(campaign, baseline=True, sequence=0)
                    continue

                completed_iterations = int(progress.get("completed_iterations", 0) or 0)
                max_iterations = int(campaign.get("max_iterations", 0) or 0)
                if completed_iterations >= max_iterations:
                    updated = self._mutate_campaign(
                        campaign_id,
                        tenant_id=tenant_id,
                        mutate=lambda current: self._transition_campaign(
                            current,
                            status="completed",
                            message="Experiment campaign completed.",
                        ),
                    )
                    self._refresh_context_bundle(updated)
                    self._clear_lease(campaign_id)
                    return

                self._run_iteration(campaign, baseline=False, sequence=completed_iterations + 1)
        except Exception as exc:
            current = self._get_campaign(campaign_id)
            if current is not None:
                tenant_id = str(current.get("tenant_id", "default") or "default")
                self._logger.exception("experiment_campaign_failed id=%s", campaign_id)
                updated = self._mutate_campaign(
                    campaign_id,
                    tenant_id=tenant_id,
                    mutate=lambda payload: self._transition_campaign(
                        payload,
                        status="failed",
                        message="Experiment campaign failed.",
                        error=str(exc),
                    ),
                )
                self._refresh_context_bundle(updated)
                self._clear_lease(campaign_id)
        finally:
            with self._lock:
                self._threads.pop(campaign_id, None)

    def _run_iteration(
        self,
        campaign: Mapping[str, Any],
        *,
        baseline: bool,
        sequence: int,
    ) -> None:
        campaign_id = str(campaign.get("id", ""))
        tenant_id = str(campaign.get("tenant_id", "default") or "default")
        repo_root = str(campaign.get("repo_root", ""))
        metric_spec = MetricSpec.from_payload(dict(campaign.get("metric") or {}))
        kind = "baseline" if baseline else "candidate"
        iteration_id = _iteration_record_id(campaign_id, sequence, baseline=baseline)
        runtime_root = Path(str(campaign.get("runtime_root", "")))
        worktrees_dir = runtime_root / "worktrees"
        worktree_path = worktrees_dir / (kind if baseline else f"iter-{sequence:03d}")
        runtime_root.mkdir(parents=True, exist_ok=True)
        base_ref = (
            str(campaign.get("base_ref", ""))
            if baseline
            else str((campaign.get("best") or {}).get("ref") or campaign.get("base_ref", ""))
        )
        branch_name = "" if baseline else f"pylon/experiments/{campaign_id}/iter-{sequence:03d}"

        started_iteration = {
            "id": iteration_id,
            "campaign_id": campaign_id,
            "tenant_id": tenant_id,
            "sequence": sequence,
            "kind": kind,
            "status": "running",
            "outcome": None,
            "base_ref": base_ref,
            "branch": branch_name,
            "worktree_path": str(worktree_path),
            "started_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "planner": None,
            "benchmark": None,
            "checks": None,
            "metric": None,
            "decision": None,
            "commit_ref": None,
            "diff_stat": "",
            "changed_files": [],
        }
        self._store.put_surface_record(ITERATION_NAMESPACE, iteration_id, started_iteration)
        self._mutate_campaign(
            campaign_id,
            tenant_id=tenant_id,
            mutate=lambda current: _set_current_iteration(
                current,
                iteration_id=iteration_id,
                message=f"Started {kind} iteration {sequence}.",
            ),
        )

        committed_ref = ""
        keep_candidate = False
        candidate_value: float | None = None
        planner_result: dict[str, Any] | None = None
        benchmark_result: dict[str, Any] | None = None
        checks_result: dict[str, Any] | None = None
        changed_paths: list[str] = []
        diff_summary = ""
        iteration_failed = False
        preserve_failed_worktrees = bool(
            (campaign.get("cleanup") or {}).get("preserve_failed_worktrees", False)
        )

        try:
            if baseline:
                create_detached_worktree(repo_root, worktree_path=worktree_path, ref=base_ref)
            else:
                create_branch_worktree(
                    repo_root,
                    worktree_path=worktree_path,
                    branch=branch_name,
                    ref=base_ref,
                )
            current_campaign = self._get_campaign(campaign_id, tenant_id=tenant_id) or dict(campaign)
            self._prepare_context_bundle_workspace(
                current_campaign,
                worktree_path=worktree_path,
            )

            if not baseline:
                planner_result = self._execute_planner(
                    current_campaign,
                    worktree_path=worktree_path,
                    sequence=sequence,
                )
                self._sync_context_bundle_from_workspace(
                    current_campaign,
                    worktree_path=worktree_path,
                )
                self._update_iteration(
                    iteration_id,
                    tenant_id=tenant_id,
                    mutate=lambda current: _update_iteration_step(current, "planner", planner_result),
                )
                if planner_result["exit_code"] != 0:
                    iteration_failed = True
                    self._fail_iteration(
                        iteration_id,
                        tenant_id=tenant_id,
                        outcome="planner_failed",
                        message=f"Planner failed during iteration {sequence}.",
                    )
                    self._mark_iteration_attempt_complete(campaign_id, tenant_id=tenant_id)
                    return

            benchmark_result = self._execute_command_step(
                command=str(campaign.get("benchmark_command", "")),
                timeout_seconds=int(campaign.get("benchmark_timeout_seconds", DEFAULT_STEP_TIMEOUT_SECONDS) or DEFAULT_STEP_TIMEOUT_SECONDS),
                worktree_path=worktree_path,
                campaign=campaign,
                sequence=sequence,
                metric=metric_spec,
                step_name="benchmark",
            )
            self._update_iteration(
                iteration_id,
                tenant_id=tenant_id,
                mutate=lambda current: _update_iteration_step(current, "benchmark", benchmark_result),
            )
            if benchmark_result["exit_code"] != 0:
                iteration_failed = True
                self._fail_iteration(
                    iteration_id,
                    tenant_id=tenant_id,
                    outcome="benchmark_failed",
                    message=f"Benchmark failed during iteration {sequence}.",
                )
                if baseline:
                    raise RuntimeError(f"Baseline benchmark failed during iteration {sequence}")
                self._mark_iteration_attempt_complete(campaign_id, tenant_id=tenant_id)
                return

            candidate_value, evidence = extract_metric_value(
                str(benchmark_result.get("stdout", "")),
                spec=metric_spec,
            )
            metric_payload = {
                "name": metric_spec.name,
                "direction": metric_spec.direction,
                "unit": metric_spec.unit,
                "value": candidate_value,
                "evidence": evidence,
            }
            self._update_iteration(
                iteration_id,
                tenant_id=tenant_id,
                mutate=lambda current: _update_iteration_metric(current, metric_payload),
            )

            checks_command = str(campaign.get("checks_command", "")).strip()
            if checks_command:
                checks_result = self._execute_command_step(
                    command=checks_command,
                    timeout_seconds=int(campaign.get("checks_timeout_seconds", DEFAULT_STEP_TIMEOUT_SECONDS) or DEFAULT_STEP_TIMEOUT_SECONDS),
                    worktree_path=worktree_path,
                    campaign=campaign,
                    sequence=sequence,
                    metric=metric_spec,
                    step_name="checks",
                )
                self._update_iteration(
                    iteration_id,
                    tenant_id=tenant_id,
                    mutate=lambda current: _update_iteration_step(current, "checks", checks_result),
                )
                if checks_result["exit_code"] != 0:
                    iteration_failed = True
                    self._fail_iteration(
                        iteration_id,
                        tenant_id=tenant_id,
                        outcome="checks_failed",
                        message=f"Checks failed during iteration {sequence}.",
                    )
                    if baseline:
                        raise RuntimeError(f"Baseline checks failed during iteration {sequence}")
                    self._mark_iteration_attempt_complete(campaign_id, tenant_id=tenant_id)
                    return

            if baseline:
                self._complete_baseline_iteration(
                    campaign_id,
                    tenant_id=tenant_id,
                    iteration_id=iteration_id,
                    metric_value=candidate_value,
                    metric=metric_payload,
                )
                return

            if worktree_has_changes(worktree_path):
                committed_ref = commit_all(
                    worktree_path,
                    message=f"Experiment iteration {sequence}: {campaign.get('objective', 'Optimize metric')}",
                )
            else:
                committed_ref = resolve_ref(worktree_path, "HEAD")

            reference_value = _best_or_baseline_value(campaign)
            keep_candidate = metric_is_better(metric_spec, candidate_value, reference_value)
            delta = metric_delta(metric_spec, candidate_value, reference_value)
            improvement = metric_improvement_ratio(metric_spec, candidate_value, reference_value)
            diff_summary = diff_stat(repo_root, base_ref, committed_ref)
            changed_paths = changed_files(repo_root, base_ref, committed_ref)
            if keep_candidate:
                force_branch_ref(repo_root, str(campaign.get("stable_branch", "")), committed_ref)

            decision = {
                "kept": keep_candidate,
                "reason": (
                    "Metric improved and candidate was retained."
                    if keep_candidate
                    else "Metric did not improve on the incumbent candidate."
                ),
                "reference_value": reference_value,
                "delta": delta,
                "improvement_ratio": improvement,
            }
            self._update_iteration(
                iteration_id,
                tenant_id=tenant_id,
                mutate=lambda current: _complete_iteration(
                    current,
                    outcome="kept" if keep_candidate else "discarded",
                    commit_ref=committed_ref,
                    decision=decision,
                    diff_summary=diff_summary,
                    changed_paths=changed_paths,
                ),
            )
            self._finalize_candidate_iteration(
                campaign_id,
                tenant_id=tenant_id,
                iteration_id=iteration_id,
                metric_value=candidate_value,
                commit_ref=committed_ref,
                keep_candidate=keep_candidate,
                diff_summary=diff_summary,
                changed_paths=changed_paths,
                sequence=sequence,
            )
        except Exception as exc:
            iteration_failed = True
            self._fail_iteration(
                iteration_id,
                tenant_id=tenant_id,
                outcome="failed",
                message=f"Iteration {sequence} failed: {exc}",
            )
            if not baseline:
                self._mark_iteration_attempt_complete(campaign_id, tenant_id=tenant_id)
            raise
        finally:
            if branch_name and not keep_candidate:
                if not (iteration_failed and preserve_failed_worktrees):
                    try:
                        delete_branch(repo_root, branch_name)
                    except Exception:
                        self._logger.exception(
                            "experiment_campaign_branch_cleanup_failed campaign_id=%s branch=%s",
                            campaign_id,
                            branch_name,
                        )
            if iteration_failed and preserve_failed_worktrees:
                self._logger.info(
                    "experiment_campaign_preserved_failed_worktree campaign_id=%s iteration_id=%s path=%s",
                    campaign_id,
                    iteration_id,
                    worktree_path,
                )
            else:
                try:
                    remove_worktree(repo_root, worktree_path)
                except Exception:
                    self._logger.exception(
                        "experiment_campaign_worktree_cleanup_failed campaign_id=%s path=%s",
                        campaign_id,
                        worktree_path,
                    )
            if branch_name and keep_candidate:
                try:
                    delete_branch(repo_root, branch_name)
                except Exception:
                    self._logger.exception(
                        "experiment_campaign_branch_cleanup_failed campaign_id=%s branch=%s",
                        campaign_id,
                        branch_name,
                    )

    def _execute_planner(
        self,
        campaign: Mapping[str, Any],
        *,
        worktree_path: Path,
        sequence: int,
    ) -> dict[str, Any]:
        planner = PlannerSpec(**dict(campaign.get("planner") or {}))
        if planner.type == "command":
            return self._execute_command_step(
                command=planner.command,
                timeout_seconds=int(campaign.get("planner_timeout_seconds", DEFAULT_STEP_TIMEOUT_SECONDS) or DEFAULT_STEP_TIMEOUT_SECONDS),
                worktree_path=worktree_path,
                campaign=campaign,
                sequence=sequence,
                metric=MetricSpec.from_payload(dict(campaign.get("metric") or {})),
                step_name="planner",
                sync_back=True,
            )
        if planner.type != "codex":
            msg = f"Unsupported planner type: {planner.type}"
            raise ValueError(msg)
        started = time.monotonic()
        response_text = ""
        session_id = ""
        exit_code = 0
        error = ""
        campaign_id = str(campaign.get("id", ""))
        tenant_id = str(campaign.get("tenant_id", "default") or "default")
        iterations = self.list_iterations(campaign_id, tenant_id=tenant_id)
        try:
            response_text, session_id = asyncio.run(
                self._run_codex_planner(
                    campaign,
                    planner=planner,
                    worktree_path=worktree_path,
                    sequence=sequence,
                    iterations=iterations,
                )
            )
        except Exception as exc:
            exit_code = 1
            error = str(exc)
            response_text = str(exc)
        return {
            "command": planner.prompt,
            "planner_type": planner.type,
            "exit_code": exit_code,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout": _trim_output(response_text),
            "stderr": _trim_output(error),
            "session_id": session_id,
            "completed_at": _utc_now_iso(),
        }

    async def _run_codex_planner(
        self,
        campaign: Mapping[str, Any],
        *,
        planner: PlannerSpec,
        worktree_path: Path,
        sequence: int,
        iterations: list[dict[str, Any]],
    ) -> tuple[str, str]:
        bridge = CodexBridge(
            model=planner.model,
            approval_policy=planner.approval_policy,
            sandbox_mode=planner.sandbox_mode,
        )
        await bridge.start()
        try:
            session_id = await bridge.start_session(str(worktree_path))
            response = await bridge.send_turn(
                _build_codex_prompt(
                    campaign,
                    planner=planner,
                    worktree_path=worktree_path,
                    sequence=sequence,
                    iterations=iterations,
                )
            )
            return response, session_id
        finally:
            await bridge.stop()

    def _execute_command_step(
        self,
        *,
        command: str,
        timeout_seconds: int,
        worktree_path: Path,
        campaign: Mapping[str, Any],
        sequence: int,
        metric: MetricSpec,
        step_name: str,
        sync_back: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        sandbox_config = ExperimentSandboxConfig.from_payload(dict(campaign.get("sandbox") or {}))
        env = {
            **_experiment_step_env(
                campaign,
                worktree_path=worktree_path,
                sequence=sequence,
                metric=metric,
            ),
        }
        try:
            result = self._sandbox_runner.execute(
                sandbox_config=sandbox_config,
                command=command,
                cwd=worktree_path,
                timeout_seconds=timeout_seconds,
                env=env,
                agent_id=f"experiment:{campaign.get('id', '')}:{step_name}",
                sync_back=sync_back,
            )
            return {
                "command": command,
                "step": step_name,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "stdout": _trim_output(result.stdout),
                "stderr": _trim_output(result.stderr),
                "timed_out": result.timed_out,
                "sandbox": dict(result.sandbox),
                "resource_usage": _resource_usage_payload(result.resource_usage),
                "completed_at": _utc_now_iso(),
            }
        except SandboxError as exc:
            return {
                "command": command,
                "step": step_name,
                "exit_code": 126,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "stdout": "",
                "stderr": _trim_output(str(exc)),
                "timed_out": False,
                "sandbox": {
                    **sandbox_config.to_payload(),
                    "id": None,
                    "status": "blocked",
                },
                "resource_usage": _resource_usage_payload({}),
                "policy_blocked": True,
                "completed_at": _utc_now_iso(),
            }

    def _heartbeat(self, campaign_id: str, *, tenant_id: str) -> None:
        thread_name = threading.current_thread().name

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            current["runner"] = {
                "owner": self._owner,
                "thread_name": thread_name,
                "heartbeat_at": _utc_now_iso(),
            }
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        self._store.put_surface_record(
            LEASE_NAMESPACE,
            campaign_id,
            {
                "id": campaign_id,
                "tenant_id": tenant_id,
                "owner": self._owner,
                "thread_name": thread_name,
                "status": str(updated.get("status", "")),
                "heartbeat_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "created_at": (
                    str((self._store.get_surface_record(LEASE_NAMESPACE, campaign_id) or {}).get("created_at", ""))
                    or _utc_now_iso()
                ),
            },
        )

    def _clear_lease(self, campaign_id: str) -> None:
        self._store.delete_surface_record(LEASE_NAMESPACE, campaign_id)

    def _get_campaign(
        self,
        campaign_id: str,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        record = self._store.get_surface_record(CAMPAIGN_NAMESPACE, campaign_id)
        if record is None:
            return None
        if tenant_id is not None and str(record.get("tenant_id", "")) != tenant_id:
            return None
        return dict(record)

    def _mutate_campaign(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
        mutate: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        for _ in range(8):
            current = self._get_campaign(campaign_id, tenant_id=tenant_id)
            if current is None:
                raise KeyError(campaign_id)
            expected_version = int(current.get("record_version", 0) or 0)
            updated = mutate(dict(current))
            updated["updated_at"] = _utc_now_iso()
            updated.setdefault("tenant_id", tenant_id)
            updated.setdefault("id", campaign_id)
            try:
                return self._store.put_surface_record(
                    CAMPAIGN_NAMESPACE,
                    campaign_id,
                    updated,
                    expected_record_version=expected_version,
                )
            except ConcurrencyError:
                continue
        raise ConcurrencyError(f"Failed to update experiment campaign {campaign_id}")

    def _update_iteration(
        self,
        iteration_id: str,
        *,
        tenant_id: str,
        mutate: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        for _ in range(8):
            current = self._store.get_surface_record(ITERATION_NAMESPACE, iteration_id)
            if current is None:
                raise KeyError(iteration_id)
            if str(current.get("tenant_id", "")) != tenant_id:
                raise KeyError(iteration_id)
            expected_version = int(current.get("record_version", 0) or 0)
            updated = mutate(dict(current))
            updated["updated_at"] = _utc_now_iso()
            try:
                return self._store.put_surface_record(
                    ITERATION_NAMESPACE,
                    iteration_id,
                    updated,
                    expected_record_version=expected_version,
                )
            except ConcurrencyError:
                continue
        raise ConcurrencyError(f"Failed to update experiment iteration {iteration_id}")

    def _complete_baseline_iteration(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
        iteration_id: str,
        metric_value: float,
        metric: dict[str, Any],
    ) -> None:
        self._update_iteration(
            iteration_id,
            tenant_id=tenant_id,
            mutate=lambda current: _complete_iteration(
                current,
                outcome="baseline",
                commit_ref=None,
                decision={"kept": True, "reason": "Captured baseline metric."},
                diff_summary="",
                changed_paths=[],
            ),
        )

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            current["baseline"] = {
                "iteration_id": iteration_id,
                "value": metric_value,
                "captured_at": _utc_now_iso(),
            }
            progress = dict(current.get("progress") or {})
            progress["baseline_measured"] = True
            current["progress"] = progress
            current["current_iteration_id"] = None
            current["events"] = _append_event(
                current.get("events"),
                kind="baseline_completed",
                message=f"Baseline captured at {metric_value:g}{metric.get('unit', '')}.",
            )
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        self._refresh_context_bundle(updated)

    def _finalize_candidate_iteration(
        self,
        campaign_id: str,
        *,
        tenant_id: str,
        iteration_id: str,
        metric_value: float,
        commit_ref: str,
        keep_candidate: bool,
        diff_summary: str,
        changed_paths: list[str],
        sequence: int,
    ) -> None:
        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            progress = dict(current.get("progress") or {})
            progress["completed_iterations"] = int(progress.get("completed_iterations", 0) or 0) + 1
            current["progress"] = progress
            current["current_iteration_id"] = None
            if keep_candidate:
                baseline_value = _best_or_baseline_value(current)
                current["best"] = {
                    "iteration_id": iteration_id,
                    "value": metric_value,
                    "ref": commit_ref,
                    "branch": str(current.get("stable_branch", "")),
                    "delta": metric_delta(MetricSpec.from_payload(dict(current.get("metric") or {})), metric_value, baseline_value),
                    "improvement_ratio": metric_improvement_ratio(
                        MetricSpec.from_payload(dict(current.get("metric") or {})),
                        metric_value,
                        baseline_value,
                    ),
                    "diff_stat": diff_summary,
                    "changed_files": changed_paths,
                    "updated_at": _utc_now_iso(),
                }
            else:
                progress["failed_iterations"] = int(progress.get("failed_iterations", 0) or 0)
            message = (
                f"Iteration {sequence} produced a new best candidate."
                if keep_candidate
                else f"Iteration {sequence} was discarded."
            )
            current["events"] = _append_event(
                current.get("events"),
                kind="iteration_completed",
                message=message,
            )
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        self._refresh_context_bundle(updated)

    def _mark_iteration_attempt_complete(self, campaign_id: str, *, tenant_id: str) -> None:
        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            progress = dict(current.get("progress") or {})
            progress["completed_iterations"] = int(progress.get("completed_iterations", 0) or 0) + 1
            progress["failed_iterations"] = int(progress.get("failed_iterations", 0) or 0) + 1
            current["progress"] = progress
            current["current_iteration_id"] = None
            return current

        updated = self._mutate_campaign(campaign_id, tenant_id=tenant_id, mutate=mutate)
        self._refresh_context_bundle(updated)

    def _fail_iteration(
        self,
        iteration_id: str,
        *,
        tenant_id: str,
        outcome: str,
        message: str,
    ) -> None:
        self._update_iteration(
            iteration_id,
            tenant_id=tenant_id,
            mutate=lambda current: _complete_iteration(
                current,
                outcome=outcome,
                commit_ref=None,
                decision={"kept": False, "reason": message},
                diff_summary="",
                changed_paths=[],
                failed=True,
            ),
        )
        campaign_id = str((self._store.get_surface_record(ITERATION_NAMESPACE, iteration_id) or {}).get("campaign_id", ""))
        if campaign_id:
            updated = self._mutate_campaign(
                campaign_id,
                tenant_id=tenant_id,
                mutate=lambda current: _mark_iteration_error(current, message=message),
            )
            self._refresh_context_bundle(updated)

    def _transition_campaign(
        self,
        current: dict[str, Any],
        *,
        status: str,
        message: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        current["status"] = status
        current["runner"] = None
        current["current_iteration_id"] = None
        current["completed_at"] = (
            _utc_now_iso()
            if status in TERMINAL_CAMPAIGN_STATUSES
            else None
        )
        if error:
            current["last_error"] = error
        current["events"] = _append_event(
            current.get("events"),
            kind=f"campaign_{status}",
            message=message,
            level="error" if error else "info",
        )
        return current


def _metric_payload_from_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get("metric")
    if isinstance(nested, dict):
        source = dict(nested)
    else:
        source = {}
    if "name" not in source and payload.get("metric_name") is not None:
        source["name"] = payload.get("metric_name")
    if "direction" not in source and payload.get("metric_direction") is not None:
        source["direction"] = payload.get("metric_direction")
    if "unit" not in source and payload.get("metric_unit") is not None:
        source["unit"] = payload.get("metric_unit")
    if "parser" not in source and payload.get("metric_parser") is not None:
        source["parser"] = payload.get("metric_parser")
    if "regex" not in source and payload.get("metric_regex") is not None:
        source["regex"] = payload.get("metric_regex")
    return source


def _parse_planner(payload: Mapping[str, Any]) -> PlannerSpec:
    nested = payload.get("planner")
    if isinstance(nested, dict):
        planner_type = str(nested.get("type", "command")).strip().lower() or "command"
        command = str(nested.get("command", "")).strip()
        prompt = str(nested.get("prompt", "")).strip()
        model = str(nested.get("model", "codex-mini")).strip() or "codex-mini"
        approval_policy = str(nested.get("approval_policy", "on-failure")).strip() or "on-failure"
        sandbox_mode = str(nested.get("sandbox_mode", "workspace-write")).strip() or "workspace-write"
    else:
        planner_type = "command"
        command = str(payload.get("planner_command", "")).strip()
        prompt = str(payload.get("planner_prompt", "")).strip()
        model = "codex-mini"
        approval_policy = "on-failure"
        sandbox_mode = "workspace-write"
    if planner_type not in {"command", "codex"}:
        raise ValueError("Planner type must be 'command' or 'codex'")
    if planner_type == "command" and not command:
        raise ValueError("Field 'planner_command' is required for command planners")
    if planner_type == "codex" and not prompt:
        raise ValueError("Planner prompt is required for Codex planners")
    return PlannerSpec(
        type=planner_type,
        command=command,
        prompt=prompt,
        model=model,
        approval_policy=approval_policy,
        sandbox_mode=sandbox_mode,
    )


def _validate_timeout(value: Any, *, field_name: str) -> int:
    if value in (None, ""):
        return DEFAULT_STEP_TIMEOUT_SECONDS
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Field '{field_name}' must be a positive integer")
    return value


def _experiment_step_env(
    campaign: Mapping[str, Any],
    *,
    worktree_path: Path,
    sequence: int,
    metric: MetricSpec,
) -> dict[str, str]:
    best = campaign.get("best")
    baseline = campaign.get("baseline")
    context_paths = experiment_context_workspace_paths(
        campaign,
        worktree_path=worktree_path,
    )
    return {
        "PYLON_EXPERIMENT_CAMPAIGN_ID": str(campaign.get("id", "")),
        "PYLON_EXPERIMENT_OBJECTIVE": str(campaign.get("objective", "")),
        "PYLON_EXPERIMENT_SEQUENCE": str(sequence),
        "PYLON_EXPERIMENT_WORKTREE": str(worktree_path),
        "PYLON_EXPERIMENT_REPO_ROOT": str(campaign.get("repo_root", "")),
        "PYLON_EXPERIMENT_CONTEXT_DIR": str(context_paths["root"]),
        "PYLON_EXPERIMENT_BRIEF_PATH": str(context_paths["brief"]),
        "PYLON_EXPERIMENT_HISTORY_MD_PATH": str(context_paths["history_markdown"]),
        "PYLON_EXPERIMENT_HISTORY_JSON_PATH": str(context_paths["history_json"]),
        "PYLON_EXPERIMENT_IDEAS_PATH": str(context_paths["ideas"]),
        "PYLON_EXPERIMENT_BENCHMARK_SCRIPT": str(context_paths["benchmark_script"]),
        "PYLON_EXPERIMENT_CHECKS_SCRIPT": (
            str(context_paths["checks_script"])
            if str(campaign.get("checks_command", "")).strip()
            else ""
        ),
        "PYLON_EXPERIMENT_METRIC_NAME": metric.name,
        "PYLON_EXPERIMENT_METRIC_DIRECTION": metric.direction,
        "PYLON_EXPERIMENT_BASELINE_VALUE": (
            str((baseline or {}).get("value", ""))
            if isinstance(baseline, dict)
            else ""
        ),
        "PYLON_EXPERIMENT_BEST_VALUE": (
            str((best or {}).get("value", ""))
            if isinstance(best, dict)
            else ""
        ),
    }


def _append_event(
    events: Any,
    *,
    kind: str,
    message: str,
    level: str = "info",
) -> list[dict[str, Any]]:
    history = list(events or [])
    history.append(
        {
            "timestamp": _utc_now_iso(),
            "level": level,
            "kind": kind,
            "message": message,
        }
    )
    if len(history) > MAX_EVENT_HISTORY:
        history = history[-MAX_EVENT_HISTORY:]
    return history


def _set_current_iteration(
    current: dict[str, Any],
    *,
    iteration_id: str,
    message: str,
) -> dict[str, Any]:
    current["current_iteration_id"] = iteration_id
    current["last_error"] = None
    current["events"] = _append_event(
        current.get("events"),
        kind="iteration_started",
        message=message,
    )
    return current


def _update_iteration_step(
    current: dict[str, Any],
    step_name: str,
    step_payload: dict[str, Any],
) -> dict[str, Any]:
    current[step_name] = dict(step_payload)
    return current


def _update_iteration_metric(current: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any]:
    current["metric"] = dict(metric)
    return current


def _complete_iteration(
    current: dict[str, Any],
    *,
    outcome: str,
    commit_ref: str | None,
    decision: dict[str, Any],
    diff_summary: str,
    changed_paths: list[str],
    failed: bool = False,
) -> dict[str, Any]:
    current["status"] = "failed" if failed else "completed"
    current["outcome"] = outcome
    current["decision"] = dict(decision)
    current["commit_ref"] = commit_ref
    current["diff_stat"] = diff_summary
    current["changed_files"] = list(changed_paths)
    current["completed_at"] = _utc_now_iso()
    return current


def _mark_iteration_error(current: dict[str, Any], *, message: str) -> dict[str, Any]:
    current["last_error"] = message
    current["events"] = _append_event(
        current.get("events"),
        kind="iteration_error",
        message=message,
        level="error",
    )
    return current


def _best_or_baseline_value(campaign: Mapping[str, Any]) -> float | None:
    best = campaign.get("best")
    if isinstance(best, dict) and isinstance(best.get("value"), (int, float)):
        return float(best["value"])
    baseline = campaign.get("baseline")
    if isinstance(baseline, dict) and isinstance(baseline.get("value"), (int, float)):
        return float(baseline["value"])
    return None


def _build_codex_prompt(
    campaign: Mapping[str, Any],
    *,
    planner: PlannerSpec,
    worktree_path: Path,
    sequence: int,
    iterations: list[dict[str, Any]],
) -> str:
    context_paths = experiment_context_workspace_paths(
        campaign,
        worktree_path=worktree_path,
    )
    recent_history = summarize_recent_iterations_for_prompt(iterations)
    return "\n".join(
        [
            "You are optimizing a local git worktree for an automated experiment campaign.",
            f"Objective: {campaign.get('objective', '')}",
            f"Iteration: {sequence}",
            f"Workspace: {worktree_path}",
            f"Metric: {campaign.get('metric', {}).get('name', 'value')} "
            f"({campaign.get('metric', {}).get('direction', 'minimize')})",
            "Read the experiment context bundle before editing:",
            f"- Brief: {context_paths['brief']}",
            f"- History: {context_paths['history_markdown']}",
            f"- Ideas backlog: {context_paths['ideas']}",
            "Capture promising follow-up ideas in ideas.md so they survive discarded worktrees.",
            "Modify the code in the workspace to improve the metric.",
            "Do not run the benchmark or checks yourself; the experiment runner will do that.",
            "",
            "Recent iteration history:",
            recent_history,
            "",
            planner.prompt,
        ]
    )
