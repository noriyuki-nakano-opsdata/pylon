"""Route definitions for the Pylon API.

Each route handler follows HandlerFunc protocol: (Request) -> Response.
Routes project API concerns over a pluggable workflow control-plane backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import MutableMapping
from datetime import UTC, datetime, timedelta
from typing import Any

from pylon.api.authz import require_scopes
from pylon.api.health import build_default_checker, build_default_readiness_checker
from pylon.api.observability import APIObservabilityBundle
from pylon.api.public_contract import (
    PublicContractRegistry,
    build_feature_manifest,
    register_public_route,
    v1,
)
from pylon.api.schemas import (
    APPROVAL_DECISION_SCHEMA,
    CREATE_AGENT_SCHEMA,
    KILL_SWITCH_SCHEMA,
    SKILL_EXECUTE_SCHEMA,
    WORKFLOW_DEFINITION_SCHEMA,
    WORKFLOW_RUN_SCHEMA,
    validate,
)
from pylon.api.server import APIServer, HandlerFunc, Request, Response
from pylon.approval import ApprovalManager
from pylon.approval.manager import (
    ApprovalAlreadyDecidedError,
    ApprovalBindingMismatchError,
    ApprovalNotFoundError,
)
from pylon.approval.types import compute_approval_binding_hash
from pylon.control_plane import (
    ControlPlaneBackend,
    ControlPlaneStoreConfig,
    WorkflowControlPlaneStore,
    build_workflow_control_plane_store,
)
from pylon.control_plane.adapters import (
    StoreBackedApprovalStore,
    StoreBackedAuditRepository,
)
from pylon.control_plane.workflow_service import WorkflowRunService
from pylon.dsl.parser import PylonProject
from pylon.lifecycle import (
    PHASE_ORDER,
    build_deploy_checks,
    build_lifecycle_approval_binding,
    build_lifecycle_autonomy_projection,
    build_lifecycle_invalidation_patch,
    build_lifecycle_phase_blueprints,
    build_lifecycle_skill_catalog,
    build_lifecycle_workflow_definition,
    build_lifecycle_workflow_handlers,
    build_release_record,
    default_lifecycle_project_record,
    derive_lifecycle_next_action,
    lifecycle_action_execution_budget,
    lifecycle_artifact,
    lifecycle_decision,
    lifecycle_phase_input,
    merge_lifecycle_project_record,
    merge_operator_records,
    refresh_lifecycle_recommendations,
    resolve_lifecycle_autonomy_level,
    resolve_lifecycle_orchestration_mode,
    sync_lifecycle_project_with_run,
)
from pylon.providers.base import Message, TokenUsage
from pylon.repository.audit import default_hmac_key
from pylon.runtime.llm import ProviderRegistry
from pylon.types import AutonomyLevel

logger = logging.getLogger(__name__)


MISSION_TASK_STATUSES = {"backlog", "in_progress", "review", "done"}
MISSION_TASK_PRIORITIES = {"low", "medium", "high", "critical"}
MISSION_ASSIGNEE_TYPES = {"human", "ai"}
MISSION_MEMORY_CATEGORIES = {"sessions", "patterns", "learnings", "decisions"}
MISSION_CONTENT_STAGES = {
    "idea",
    "research",
    "draft",
    "script",
    "review",
    "ready",
    "published",
}
DEFAULT_AUDIT_AGENTS = (
    "audit-google",
    "audit-meta",
    "audit-creative",
    "audit-tracking",
    "audit-budget",
    "audit-compliance",
)
ADS_PLATFORMS = ("google", "meta", "linkedin", "tiktok", "microsoft")
DEFAULT_TEAM_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "id": "development",
        "name": "Engineering",
        "nameJa": "エンジニアリング",
        "icon": "Code2",
        "color": "text-blue-400",
        "bg": "bg-blue-600",
    },
    {
        "id": "design",
        "name": "Design",
        "nameJa": "デザイン",
        "icon": "Palette",
        "color": "text-purple-400",
        "bg": "bg-pink-600",
    },
    {
        "id": "research",
        "name": "Research & Writing",
        "nameJa": "リサーチ & ライティング",
        "icon": "PenTool",
        "color": "text-emerald-400",
        "bg": "bg-violet-600",
    },
    {
        "id": "data",
        "name": "Data & AI",
        "nameJa": "データ & AI",
        "icon": "Zap",
        "color": "text-cyan-400",
        "bg": "bg-cyan-600",
    },
    {
        "id": "security",
        "name": "Security",
        "nameJa": "セキュリティ",
        "icon": "Shield",
        "color": "text-red-400",
        "bg": "bg-red-600",
    },
    {
        "id": "product",
        "name": "Product & Ops",
        "nameJa": "プロダクト & 運用",
        "icon": "Network",
        "color": "text-orange-400",
        "bg": "bg-orange-600",
    },
)
ADS_INDUSTRY_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "id": "saas",
        "name": "SaaS",
        "description": "B2B SaaSプロダクト向け。リード獲得とデモ予約を最適化",
        "platforms": {"google": 40, "linkedin": 35, "meta": 25},
        "min_monthly": 5000,
        "primary_kpi": "CAC",
        "time_to_profit": "3-6ヶ月",
    },
    {
        "id": "ecommerce",
        "name": "E-commerce",
        "description": "オンラインストア向け。ROAS最大化と新規顧客獲得",
        "platforms": {"google": 35, "meta": 40, "tiktok": 25},
        "min_monthly": 3000,
        "primary_kpi": "ROAS",
        "time_to_profit": "1-3ヶ月",
    },
    {
        "id": "local-service",
        "name": "ローカルサービス",
        "description": "地域密着型ビジネス向け。来店と問合せを最適化",
        "platforms": {"google": 60, "meta": 30, "microsoft": 10},
        "min_monthly": 1000,
        "primary_kpi": "CPL",
        "time_to_profit": "1-2ヶ月",
    },
    {
        "id": "b2b-enterprise",
        "name": "B2B Enterprise",
        "description": "大企業向けソリューション。ABMとリードナーチャリング",
        "platforms": {"linkedin": 45, "google": 35, "meta": 20},
        "min_monthly": 10000,
        "primary_kpi": "SQL",
        "time_to_profit": "6-12ヶ月",
    },
    {
        "id": "info-products",
        "name": "情報商材",
        "description": "オンラインコース、電子書籍等。ファネル最適化",
        "platforms": {"meta": 45, "google": 30, "tiktok": 25},
        "min_monthly": 2000,
        "primary_kpi": "CPA",
        "time_to_profit": "1-3ヶ月",
    },
    {
        "id": "mobile-app",
        "name": "モバイルアプリ",
        "description": "アプリインストールとエンゲージメント最適化",
        "platforms": {"google": 35, "meta": 35, "tiktok": 30},
        "min_monthly": 5000,
        "primary_kpi": "CPI",
        "time_to_profit": "3-6ヶ月",
    },
    {
        "id": "real-estate",
        "name": "不動産",
        "description": "物件問合せとリード獲得を最適化",
        "platforms": {"google": 50, "meta": 35, "microsoft": 15},
        "min_monthly": 3000,
        "primary_kpi": "CPL",
        "time_to_profit": "2-4ヶ月",
    },
    {
        "id": "healthcare",
        "name": "ヘルスケア",
        "description": "医療・健康サービス向け。予約とコンプライアンス対応",
        "platforms": {"google": 55, "meta": 30, "microsoft": 15},
        "min_monthly": 3000,
        "primary_kpi": "CPA",
        "time_to_profit": "2-4ヶ月",
    },
    {
        "id": "finance",
        "name": "金融",
        "description": "金融サービス向け。リード獲得と規制対応",
        "platforms": {"google": 45, "linkedin": 30, "meta": 25},
        "min_monthly": 8000,
        "primary_kpi": "CAC",
        "time_to_profit": "3-6ヶ月",
    },
    {
        "id": "agency",
        "name": "代理店",
        "description": "マーケティング代理店向け。クライアント獲得",
        "platforms": {"google": 35, "linkedin": 35, "meta": 30},
        "min_monthly": 5000,
        "primary_kpi": "CAC",
        "time_to_profit": "2-4ヶ月",
    },
    {
        "id": "generic",
        "name": "汎用",
        "description": "業種を問わない標準テンプレート",
        "platforms": {"google": 40, "meta": 35, "microsoft": 25},
        "min_monthly": 2000,
        "primary_kpi": "CPA",
        "time_to_profit": "2-4ヶ月",
    },
)
ADS_BENCHMARKS: dict[str, dict[str, Any]] = {
    "google": {"avg_ctr": 4.9, "avg_cvr": 5.8, "avg_cpc": 3.4, "benchmark_mer": 3.5},
    "meta": {"avg_ctr": 1.6, "avg_cvr": 3.2, "avg_cpc": 1.8, "benchmark_mer": 3.1},
    "linkedin": {"avg_ctr": 0.8, "avg_cvr": 2.4, "avg_cpc": 6.7, "benchmark_mer": 2.6},
    "tiktok": {"avg_ctr": 1.9, "avg_cvr": 2.8, "avg_cpc": 1.4, "benchmark_mer": 2.9},
    "microsoft": {"avg_ctr": 2.6, "avg_cvr": 4.4, "avg_cpc": 2.1, "benchmark_mer": 3.2},
}


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso_plus_minutes(value: str, minutes: int) -> str:
    return (
        (_parse_iso_datetime(value) + timedelta(minutes=minutes))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _stable_seed(*parts: object) -> int:
    total = 0
    for index, part in enumerate(parts, start=1):
        total += index * sum(ord(ch) for ch in str(part))
    return total


def _grade_from_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _normalize_weight_map(raw_weights: dict[str, float]) -> dict[str, float]:
    filtered = {key: float(value) for key, value in raw_weights.items() if float(value) > 0}
    total = sum(filtered.values())
    if total <= 0:
        return {}
    normalized = {key: value / total for key, value in filtered.items()}
    return dict(sorted(normalized.items(), key=lambda item: item[1], reverse=True))


def _allocate_budget(raw_weights: dict[str, float], total_budget: int) -> dict[str, int]:
    weights = _normalize_weight_map(raw_weights)
    if not weights:
        return {}
    remaining = total_budget
    allocation: dict[str, int] = {}
    ordered = list(weights.items())
    for index, (platform, weight) in enumerate(ordered):
        if index == len(ordered) - 1:
            amount = max(remaining, 0)
        else:
            amount = max(int(round(total_budget * weight)), 0)
            remaining -= amount
        allocation[platform] = amount
    return allocation


def _team_store_key(tenant_id: str, team_id: str) -> str:
    return f"{tenant_id}:{team_id}"


def _model_policy_store_key(tenant_id: str, provider_name: str) -> str:
    return f"{tenant_id}:{provider_name}"


def _kill_switch_store_key(tenant_id: str, scope: str) -> str:
    if scope == "global":
        return scope
    return f"{tenant_id}:{scope}"


def _slugify_identifier(value: str, *, prefix: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug:
        slug = f"{prefix}-{uuid.uuid4().hex[:6]}"
    return slug[:48]


class SurfaceNamespaceMap(MutableMapping[str, dict[str, Any]]):
    """Mutable mapping facade over durable control-plane surface records."""

    def __init__(self, store: WorkflowControlPlaneStore, namespace: str) -> None:
        self._store = store
        self._namespace = namespace

    def _normalize_key(self, key: object) -> str:
        return str(key)

    def __getitem__(self, key: object) -> dict[str, Any]:
        normalized = self._normalize_key(key)
        payload = self._store.get_surface_record(self._namespace, normalized)
        if payload is None:
            raise KeyError(normalized)
        return payload

    def __setitem__(self, key: object, value: dict[str, Any]) -> None:
        normalized = self._normalize_key(key)
        payload = dict(value)
        if "id" not in payload and normalized:
            payload["id"] = normalized
        self._store.put_surface_record(self._namespace, normalized, payload)

    def __delitem__(self, key: object) -> None:
        normalized = self._normalize_key(key)
        if not self._store.delete_surface_record(self._namespace, normalized):
            raise KeyError(normalized)

    def __iter__(self):
        for payload in self._store.list_surface_records(self._namespace):
            yield self._normalize_key(payload.get("id", payload.get("entry_id", "")))

    def __len__(self) -> int:
        return len(self._store.list_surface_records(self._namespace))

    def get(self, key: object, default: Any = None) -> dict[str, Any] | Any:
        payload = self._store.get_surface_record(self._namespace, self._normalize_key(key))
        return default if payload is None else payload

    def values(self):  # type: ignore[override]
        return list(self._store.list_surface_records(self._namespace))

    def items(self):  # type: ignore[override]
        return [
            (self._normalize_key(payload.get("id", payload.get("entry_id", ""))), payload)
            for payload in self._store.list_surface_records(self._namespace)
        ]



class RouteStore:
    """API facade over the shared workflow control-plane store."""

    def __init__(
        self,
        *,
        control_plane_store: WorkflowControlPlaneStore | None = None,
        control_plane_backend: ControlPlaneBackend | str = ControlPlaneBackend.MEMORY,
        control_plane_path: str | None = None,
    ) -> None:
        if control_plane_store is None:
            backend = (
                control_plane_backend
                if isinstance(control_plane_backend, ControlPlaneBackend)
                else ControlPlaneBackend(str(control_plane_backend))
            )
            control_plane_store = build_workflow_control_plane_store(
                ControlPlaneStoreConfig(
                    backend=backend,
                    path=control_plane_path,
                )
            )
        self._control_plane_store = control_plane_store
        self.agents = SurfaceNamespaceMap(self._control_plane_store, "agents")
        self.skills = SurfaceNamespaceMap(self._control_plane_store, "skills")
        self.model_policies = SurfaceNamespaceMap(self._control_plane_store, "model_policies")
        self.kill_switches = SurfaceNamespaceMap(self._control_plane_store, "kill_switches")
        self.tasks = SurfaceNamespaceMap(self._control_plane_store, "tasks")
        self.memories = SurfaceNamespaceMap(self._control_plane_store, "memories")
        self.events = SurfaceNamespaceMap(self._control_plane_store, "events")
        self.content_items = SurfaceNamespaceMap(self._control_plane_store, "content_items")
        self.teams = SurfaceNamespaceMap(self._control_plane_store, "teams")
        self.ads_audit_runs = SurfaceNamespaceMap(self._control_plane_store, "ads_audit_runs")
        self.ads_reports = SurfaceNamespaceMap(self._control_plane_store, "ads_reports")
        self._workflow_index: dict[str, set[str]] = {}
        self._rebuild_workflow_index()

    @property
    def control_plane_store(self) -> WorkflowControlPlaneStore:
        return self._control_plane_store

    @property
    def workflow_runs_by_id(self) -> dict[str, dict[str, Any]]:
        return {
            str(run["id"]): run
            for run in self._control_plane_store.list_all_run_records()
        }

    @property
    def checkpoints(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for run in self._control_plane_store.list_all_run_records():
            run_id = str(run.get("id", ""))
            for checkpoint in self._control_plane_store.list_run_checkpoints(run_id):
                records[str(checkpoint["id"])] = checkpoint
        return records

    @property
    def approvals(self) -> dict[str, dict[str, Any]]:
        return {
            str(approval["id"]): approval
            for approval in self._control_plane_store.list_all_approval_records()
        }

    def _rebuild_workflow_index(self) -> None:
        self._workflow_index.clear()
        for tenant_id, workflow_id, _ in self._control_plane_store.list_all_workflow_projects():
            self._workflow_index.setdefault(workflow_id, set()).add(tenant_id)

    def register_workflow_project(
        self,
        workflow_id: str,
        project: PylonProject | dict[str, Any],
        *,
        tenant_id: str = "default",
    ) -> PylonProject:
        """Register a canonical workflow definition for API execution."""
        resolved = self._control_plane_store.register_workflow_project(
            workflow_id,
            project,
            tenant_id=tenant_id,
        )
        self._workflow_index.setdefault(workflow_id, set()).add(tenant_id)
        return resolved

    def remove_workflow_project(self, workflow_id: str, *, tenant_id: str) -> None:
        self._control_plane_store.remove_workflow_project(workflow_id, tenant_id=tenant_id)
        tenants = self._workflow_index.get(workflow_id)
        if tenants is not None:
            tenants.discard(tenant_id)
            if not tenants:
                self._workflow_index.pop(workflow_id, None)

    def get_workflow_project(self, workflow_id: str, *, tenant_id: str) -> PylonProject | None:
        return self._control_plane_store.get_workflow_project(workflow_id, tenant_id=tenant_id)

    def get_run_record(self, run_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_run_record(run_id)

    def put_run_record(
        self,
        run_record: dict[str, Any],
        *,
        workflow_id: str,
        tenant_id: str = "default",
        parameters: dict[str, Any] | None = None,
        expected_record_version: int | None = None,
    ) -> dict[str, Any]:
        return self._control_plane_store.put_run_record(
            run_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=parameters,
            expected_record_version=expected_record_version,
        )

    def get_checkpoint_record(self, checkpoint_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_checkpoint_record(checkpoint_id)

    def put_checkpoint_record(self, checkpoint_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_checkpoint_record(checkpoint_payload)

    def list_workflow_projects(self, *, tenant_id: str) -> list[tuple[str, PylonProject]]:
        return self._control_plane_store.list_workflow_projects(tenant_id=tenant_id)

    def workflow_exists(self, workflow_id: str) -> bool:
        return workflow_id in self._workflow_index

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return self._control_plane_store.list_run_checkpoints(run_id)

    def get_approval_record(self, approval_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_approval_record(approval_id)

    def put_approval_record(self, approval_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_approval_record(approval_payload)

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]:
        return self._control_plane_store.list_run_approvals(run_id)

    def get_node_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_node_handlers(workflow_id)

    def get_agent_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_agent_handlers(workflow_id)

    def list_all_run_records(self) -> list[dict[str, Any]]:
        return self._control_plane_store.list_all_run_records()

    def get_run_record_by_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return self._control_plane_store.get_run_record_by_idempotency_key(
            workflow_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )

    def put_run_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
        run_id: str,
    ) -> None:
        self._control_plane_store.put_run_idempotency_key(
            workflow_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            run_id=run_id,
        )

    def list_all_approval_records(self) -> list[dict[str, Any]]:
        return self._control_plane_store.list_all_approval_records()

    def get_audit_record(self, entry_id: int) -> dict[str, Any] | None:
        return self._control_plane_store.get_audit_record(entry_id)

    def get_last_audit_record(self) -> dict[str, Any] | None:
        return self._control_plane_store.get_last_audit_record()

    def put_audit_record(self, audit_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_audit_record(audit_payload)

    def list_audit_records(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._control_plane_store.list_audit_records(
            tenant_id=tenant_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )

    def get_queue_task_record(self, task_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_queue_task_record(task_id)

    def put_queue_task_record(self, task_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_queue_task_record(task_payload)

    def delete_queue_task_record(self, task_id: str) -> bool:
        return self._control_plane_store.delete_queue_task_record(task_id)

    def list_queue_task_records(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._control_plane_store.list_queue_task_records(status=status)

    def get_surface_record(
        self,
        namespace: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        return self._control_plane_store.get_surface_record(namespace, record_id)

    def put_surface_record(
        self,
        namespace: str,
        record_id: str,
        payload: dict[str, Any],
    ) -> None:
        self._control_plane_store.put_surface_record(namespace, record_id, payload)

    def delete_surface_record(
        self,
        namespace: str,
        record_id: str,
    ) -> bool:
        return self._control_plane_store.delete_surface_record(namespace, record_id)

    def list_surface_records(
        self,
        namespace: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._control_plane_store.list_surface_records(namespace, tenant_id=tenant_id)

    def allocate_sequence_value(self, name: str) -> int:
        return self._control_plane_store.allocate_sequence_value(name)

    def get_run_record_for_workflow(
        self,
        workflow_id: str,
        run_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        run = self.get_run_record(run_id)
        if run is None:
            return None
        if str(run.get("workflow_id", run.get("workflow", ""))) != workflow_id:
            return None
        if run.get("tenant_id") != tenant_id:
            return None
        return run


def _require_tenant_id(request: Request) -> str | None:
    """Extract tenant_id from request context; return None if missing."""
    return request.context.get("tenant_id")


def _tenant_required_response() -> Response:
    return Response(status_code=401, body={"error": "Tenant context required"})


def register_routes(
    server: APIServer,
    store: RouteStore | None = None,
    *,
    control_plane_store: WorkflowControlPlaneStore | None = None,
    control_plane_backend: ControlPlaneBackend | str = ControlPlaneBackend.MEMORY,
    control_plane_path: str | None = None,
    observability: APIObservabilityBundle | None = None,
    readiness_route_enabled: bool = True,
    metrics_route_enabled: bool = True,
    provider_registry: ProviderRegistry | None = None,
) -> RouteStore:
    """Register all API routes on the server. Returns the store."""
    s = store or RouteStore(
        control_plane_store=control_plane_store,
        control_plane_backend=control_plane_backend,
        control_plane_path=control_plane_path,
    )
    public_contract = PublicContractRegistry()
    if observability is not None:
        setattr(s, "_observability", observability)
    workflow_service = WorkflowRunService(s, provider_registry=provider_registry)

    def _workflow_summary(
        workflow_id: str,
        project: PylonProject,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        return {
            "id": workflow_id,
            "project_name": project.name,
            "tenant_id": tenant_id,
            "agent_count": len(project.agents),
            "node_count": len(project.workflow.nodes),
            "goal_enabled": project.goal is not None,
        }

    def _ensure_workflow_access(
        workflow_id: str,
        tenant_id: str,
    ) -> Response | None:
        if s.get_workflow_project(workflow_id, tenant_id=tenant_id) is not None:
            return None
        if not s.workflow_exists(workflow_id):
            return Response(
                status_code=404,
                body={"error": f"Workflow not found: {workflow_id}"},
            )
        return Response(status_code=403, body={"error": "Forbidden"})

    checker = observability.health_checker if observability is not None else build_default_checker()
    readiness_checker = (
        observability.readiness_checker
        if observability is not None
        else build_default_readiness_checker()
    )

    def _scoped(
        handler: HandlerFunc,
        *,
        any_of: tuple[str, ...] = (),
        all_of: tuple[str, ...] = (),
    ) -> HandlerFunc:
        def wrapped(request: Request) -> Response:
            auth_error = require_scopes(request, any_of=any_of, all_of=all_of)
            if auth_error is not None:
                return auth_error
            return handler(request)

        return wrapped

    def _public(
        method: str,
        path: str,
        handler: HandlerFunc,
        *,
        aliases: tuple[str, ...] = (),
        any_of: tuple[str, ...] = (),
        all_of: tuple[str, ...] = (),
    ) -> None:
        register_public_route(
            server,
            method,
            path,
            _scoped(handler, any_of=any_of, all_of=all_of),
            aliases=aliases,
            any_of_scopes=any_of,
            all_of_scopes=all_of,
            registry=public_contract,
        )

    def health(request: Request) -> Response:
        report = checker.run_all_sync()
        status_code = 200 if report["status"] != "unhealthy" else 503
        report["timestamp"] = time.time()
        return Response(status_code=status_code, body=report)

    def ready(request: Request) -> Response:
        report = readiness_checker.run_all_sync()
        ready_flag = report["status"] == "healthy"
        report["timestamp"] = time.time()
        report["ready"] = ready_flag
        report["status"] = "ready" if ready_flag else "not_ready"
        return Response(status_code=200 if ready_flag else 503, body=report)

    def metrics(request: Request) -> Response:
        if observability is None or observability.prometheus_exporter is None:
            return Response(
                status_code=404,
                body={"error": "Metrics exporter not configured"},
            )
        observability.prometheus_exporter.export_metrics(observability.metrics.get_metrics())
        return Response(
            headers={"content-type": "text/plain; version=0.0.4; charset=utf-8"},
            body=observability.prometheus_exporter.render_latest(),
        )

    def _normalize_autonomy(value: str | int) -> str:
        if isinstance(value, int):
            return f"A{value}"
        upper = value.upper()
        if upper in {"A0", "A1", "A2", "A3", "A4"}:
            return upper
        if upper in {"0", "1", "2", "3", "4"}:
            return f"A{upper}"
        return upper

    def _validate_agent_payload(
        body: Any,
        *,
        partial: bool,
    ) -> list[str]:
        if not isinstance(body, dict):
            return ["Request body must be a JSON object"]

        allowed_fields = {
            "name",
            "model",
            "role",
            "autonomy",
            "tools",
            "skills",
            "sandbox",
            "status",
            "team",
        }
        errors: list[str] = []
        for field_name in body:
            if field_name not in allowed_fields:
                errors.append(f"Unknown field '{field_name}'")

        if not partial:
            valid, schema_errors = validate(body, CREATE_AGENT_SCHEMA)
            if not valid:
                errors.extend(schema_errors)

        str_fields = {"name", "model", "role", "sandbox", "status", "team"}
        for field_name in str_fields:
            if field_name in body and not isinstance(body[field_name], str):
                errors.append(f"Field '{field_name}' must be of type str")

        if "autonomy" in body:
            autonomy = body["autonomy"]
            if not isinstance(autonomy, (str, int)):
                errors.append("Field 'autonomy' must be of type str | int")
            elif _normalize_autonomy(autonomy) not in {"A0", "A1", "A2", "A3", "A4"}:
                errors.append("Field 'autonomy' must be one of ['A0', 'A1', 'A2', 'A3', 'A4', 0, 1, 2, 3, 4]")

        for field_name in ("tools", "skills"):
            if field_name in body:
                value = body[field_name]
                if not isinstance(value, list):
                    errors.append(f"Field '{field_name}' must be of type list")
                elif any(not isinstance(item, str) for item in value):
                    errors.append(f"Field '{field_name}' must contain only strings")

        return errors

    def _agent_skill_payload(skill_id: str) -> dict[str, Any]:
        if skill_id in s.skills:
            return dict(s.skills[skill_id])
        return {
            "id": skill_id,
            "name": skill_id,
            "description": "",
            "category": "uncategorized",
            "risk": "unknown",
            "source": "local",
            "tags": [],
        }

    def _collect_model_catalog(tenant_id: str) -> dict[str, dict[str, Any]]:
        catalog: dict[str, dict[str, Any]] = {}
        tenant_policies = {
            str(policy.get("provider", "")): dict(policy)
            for policy in s.model_policies.values()
            if policy.get("tenant_id") == tenant_id and policy.get("provider")
        }

        if provider_registry is not None:
            for provider_name in provider_registry.provider_names():
                policy = tenant_policies.get(provider_name, {})
                catalog[provider_name] = {
                    "models": [],
                    "status": "available",
                    "default_model": "",
                    "policy": policy.get("policy", "balanced") or "balanced",
                    "pin": policy.get("pin"),
                }

        for provider_name, policy in tenant_policies.items():
            catalog.setdefault(
                provider_name,
                {
                    "models": [],
                    "status": "available",
                    "default_model": str(policy.get("pin", "") or ""),
                    "policy": policy.get("policy", "balanced") or "balanced",
                    "pin": policy.get("pin"),
                },
            )

        for project_tenant_id, _workflow_id, project in s.control_plane_store.list_all_workflow_projects():
            if not isinstance(project, PylonProject):
                continue
            for agent in project.agents.values():
                model_ref = agent.resolve_model()
                if "/" in model_ref:
                    provider_name, model_id = model_ref.split("/", 1)
                else:
                    provider_name, model_id = "unknown", model_ref
                info = catalog.setdefault(
                    provider_name,
                    {
                        "models": [],
                        "status": "available" if project_tenant_id else "unavailable",
                        "default_model": "",
                        "policy": tenant_policies.get(provider_name, {}).get("policy", "balanced") or "balanced",
                        "pin": tenant_policies.get(provider_name, {}).get("pin"),
                    },
                )
                if model_id and model_id not in {entry["id"] for entry in info["models"]}:
                    info["models"].append({"id": model_id, "name": model_id})
                    if not info["default_model"]:
                        info["default_model"] = model_id

        for provider_name, info in catalog.items():
            if not info["default_model"] and info["models"]:
                info["default_model"] = info["models"][0]["id"]

        return dict(sorted(catalog.items()))

    def _query_string(request: Request, name: str, default: str = "") -> str:
        value = request.query_params.get(name, default)
        if isinstance(value, list):
            return str(value[-1] if value else default)
        return str(value)

    def _list_tenant_records(
        records: dict[object, dict[str, Any]],
        *,
        tenant_id: str,
        sort_key: str,
        reverse: bool = True,
    ) -> list[dict[str, Any]]:
        return sorted(
            [dict(record) for record in records.values() if record.get("tenant_id") == tenant_id],
            key=lambda record: str(record.get(sort_key, "")),
            reverse=reverse,
        )

    def _lifecycle_project_key(tenant_id: str, project_id: str) -> str:
        return f"{tenant_id}:{project_id}"

    def _lifecycle_workflow_id(project_id: str, phase: str) -> str:
        return f"lifecycle-{phase}-{project_id}"

    def _phase_index(phase: str) -> int:
        try:
            return PHASE_ORDER.index(phase)
        except ValueError:
            return -1

    def _set_phase_status(
        project: dict[str, Any],
        phase: str,
        status: str,
    ) -> None:
        phase_statuses = project.get("phaseStatuses")
        if not isinstance(phase_statuses, list):
            return
        phase_index = _phase_index(phase)
        for entry in phase_statuses:
            if not isinstance(entry, dict):
                continue
            if entry.get("phase") == phase:
                entry["status"] = status
                if status == "completed":
                    entry["completedAt"] = _utc_now_iso()
                break
        if status not in {"in_progress", "completed"}:
            return
        if phase_index >= 0 and phase_index + 1 < len(PHASE_ORDER):
            next_phase = PHASE_ORDER[phase_index + 1]
            for entry in phase_statuses:
                if isinstance(entry, dict) and entry.get("phase") == next_phase and entry.get("status") == "locked":
                    entry["status"] = "available"
                    break

    def _lifecycle_project_payload(project: dict[str, Any]) -> dict[str, Any]:
        payload = dict(project)
        payload.setdefault("orchestrationMode", "workflow")
        payload.setdefault("autonomyLevel", "A3")
        payload.setdefault("researchConfig", {"competitorUrls": [], "depth": "standard"})
        payload["blueprints"] = build_lifecycle_phase_blueprints(str(project.get("id", "")))
        payload["recommendations"] = refresh_lifecycle_recommendations(payload)
        approval_request_id = str(payload.get("approvalRequestId") or "")
        approval_record = s.get_approval_record(approval_request_id) if approval_request_id else None
        if str(payload.get("approvalStatus", "pending") or "pending") == "approved":
            if approval_record is None or approval_record.get("status") != "approved":
                payload["approvalStatus"] = "pending"
                payload["approvalRequestId"] = None
                approval_record = None
            else:
                binding = build_lifecycle_approval_binding(payload)
                manager = _lifecycle_approval_manager()
                try:
                    _run_coro(
                        manager.validate_binding(
                            approval_request_id,
                            plan=binding["plan"],
                            effect_envelope=binding["effect_envelope"],
                        )
                    )
                except (ApprovalAlreadyDecidedError, ApprovalBindingMismatchError, ApprovalNotFoundError):
                    payload["approvalStatus"] = "pending"
                    payload["approvalRequestId"] = None
                    approval_record = None
        payload["approvalRequest"] = dict(approval_record) if approval_record is not None else None
        payload["activeApproval"] = (
            dict(approval_record)
            if isinstance(approval_record, dict) and approval_record.get("status") == "pending"
            else None
        )
        autonomy = build_lifecycle_autonomy_projection(payload)
        payload["phaseContracts"] = autonomy["contracts"]
        payload["phaseReadiness"] = autonomy["phaseReadiness"]
        payload["nextAction"] = autonomy["nextAction"]
        payload["autonomyState"] = {
            "orchestrationMode": autonomy["orchestrationMode"],
            "completedExecutablePhases": autonomy["completedExecutablePhases"],
            "blockedPhases": autonomy["blockedPhases"],
            "approvalRequired": autonomy["approvalRequired"],
            "canAdvanceAutonomously": autonomy["canAdvanceAutonomously"],
        }
        return payload

    def _seed_lifecycle_skills() -> None:
        for skill_id, skill_payload in build_lifecycle_skill_catalog().items():
            if skill_id not in s.skills:
                s.skills[skill_id] = dict(skill_payload)

    def _persist_lifecycle_project(
        tenant_id: str,
        project_id: str,
        project: dict[str, Any],
    ) -> dict[str, Any]:
        project["recommendations"] = refresh_lifecycle_recommendations(project)
        s.put_surface_record("lifecycle_projects", _lifecycle_project_key(tenant_id, project_id), project)
        return project

    def _lifecycle_mutation_response(
        project: dict[str, Any],
        *,
        actions: list[dict[str, Any]] | None = None,
        next_action: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        payload = _lifecycle_project_payload(project)
        response = dict(payload)
        response["project"] = payload
        response["actions"] = list(actions or [])
        response["nextAction"] = dict(next_action or payload.get("nextAction") or {})
        response.update(extra)
        return response

    def _run_coro(coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _lifecycle_approval_manager() -> ApprovalManager:
        return ApprovalManager(
            StoreBackedApprovalStore(s.control_plane_store),
            StoreBackedAuditRepository(s.control_plane_store, hmac_key=default_hmac_key()),
        )

    def _current_lifecycle_approval(project: dict[str, Any]) -> dict[str, Any] | None:
        approval_request_id = str(project.get("approvalRequestId") or "")
        if not approval_request_id:
            return None
        approval = s.get_approval_record(approval_request_id)
        return dict(approval) if approval is not None else None

    def _ensure_lifecycle_approval_request(
        tenant_id: str,
        project_id: str,
        *,
        project: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        binding = build_lifecycle_approval_binding(project)
        plan_hash = compute_approval_binding_hash(binding["plan"])
        effect_hash = compute_approval_binding_hash(binding["effect_envelope"])
        current_approval = _current_lifecycle_approval(project)
        if (
            current_approval is not None
            and current_approval.get("status") == "pending"
            and current_approval.get("plan_hash") == plan_hash
            and current_approval.get("effect_hash") == effect_hash
        ):
            return project, current_approval

        manager = _lifecycle_approval_manager()
        request = _run_coro(
            manager.submit_request(
                agent_id="lifecycle-coordinator",
                action=binding["action"],
                autonomy_level=AutonomyLevel.A3,
                context={
                    **binding["context"],
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "run_id": f"lifecycle:{project_id}",
                },
                plan=binding["plan"],
                effect_envelope=binding["effect_envelope"],
            )
        )
        approval = s.get_approval_record(request.id) or request.to_dict()
        merged = merge_lifecycle_project_record(
            project,
            {
                "approvalStatus": "pending",
                "approvalRequestId": request.id,
            },
        )
        persisted = _persist_lifecycle_project(tenant_id, project_id, merged)
        return persisted, dict(approval)

    def _parse_lifecycle_max_steps(
        body: dict[str, Any] | None,
        *,
        default: int,
    ) -> int:
        raw_value = default if not isinstance(body, dict) else body.get("max_steps", default)
        try:
            steps = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Field 'max_steps' must be an integer") from exc
        if steps < 1 or steps > 8:
            raise ValueError("Field 'max_steps' must be between 1 and 8")
        return steps

    def _append_lifecycle_approval_comment(
        project: dict[str, Any],
        *,
        text: str,
        comment_type: str,
    ) -> dict[str, Any]:
        comments = list(project.get("approvalComments", []))
        comment_record = {
            "id": f"approval-{uuid.uuid4().hex[:8]}",
            "text": text,
            "type": comment_type,
            "time": _utc_now_iso(),
        }
        comments.append(comment_record)
        return merge_lifecycle_project_record(
            project,
            {
                "approvalComments": comments,
                **merge_operator_records(
                    project,
                    artifacts=[
                        lifecycle_artifact(
                            artifact_id=f"approval-thread:{comment_record['id']}",
                            phase="approval",
                            kind="approval_thread",
                            title="Approval comment",
                            summary=text,
                            created_at=comment_record["time"],
                            payload=comment_record,
                        )
                    ],
                    decisions=[
                        lifecycle_decision(
                            decision_id=f"approval-decision:{comment_record['id']}",
                            phase="approval",
                            kind="approval_comment",
                            title="Approval thread updated",
                            rationale=text,
                            created_at=comment_record["time"],
                            status=(
                                "approved"
                                if comment_type == "approve"
                                else "revision_requested"
                                if comment_type == "reject"
                                else "comment"
                            ),
                            details={"type": comment_type},
                        )
                    ],
                ),
            },
        )

    def _record_lifecycle_approval_state(
        project: dict[str, Any],
        *,
        project_id: str,
        decision: str,
        note: str,
    ) -> dict[str, Any]:
        return merge_lifecycle_project_record(
            project,
            merge_operator_records(
                project,
                decisions=[
                    lifecycle_decision(
                        decision_id=f"approval-state:{project_id}:{decision}:{uuid.uuid4().hex[:8]}",
                        phase="approval",
                        kind="approval_state",
                        title="Approval state changed",
                        rationale=note or f"Approval state set to {decision}.",
                        status=decision,
                        details={"decision": decision},
                    )
                ],
            ),
        )

    def _apply_lifecycle_lineage_reset(
        project: dict[str, Any],
        *,
        project_id: str,
        changed_fields: set[str],
    ) -> dict[str, Any]:
        invalidation = build_lifecycle_invalidation_patch(project, changed_fields=changed_fields)
        patch = dict(invalidation["patch"])
        reset_from = str(invalidation["reset_from"])
        reason = str(invalidation["reason"])
        if not patch:
            return project

        patch.update(
            merge_operator_records(
                merge_lifecycle_project_record(project, patch),
                decisions=[
                    lifecycle_decision(
                        decision_id=f"lineage-reset:{project_id}:{uuid.uuid4().hex[:8]}",
                        phase=reset_from,
                        kind="lineage_reset",
                        title="Downstream lifecycle outputs invalidated",
                        rationale=reason,
                        status="review",
                        details={
                            "changedFields": sorted(changed_fields),
                            "resetFrom": reset_from,
                        },
                    )
                ],
            )
        )
        return merge_lifecycle_project_record(project, patch)

    def _preserve_explicit_lifecycle_overrides(
        project: dict[str, Any],
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        explicit_fields = {
            field_name: body[field_name]
            for field_name in {
                "research",
                "analysis",
                "features",
                "milestones",
                "planEstimates",
                "designVariants",
                "selectedDesignId",
                "buildCode",
                "buildCost",
                "buildIteration",
                "milestoneResults",
                "deployChecks",
                "releases",
                "feedbackItems",
                "selectedPreset",
                "orchestrationMode",
                "autonomyLevel",
                "researchConfig",
            }
            if field_name in body
        }
        if not explicit_fields:
            return project
        return merge_lifecycle_project_record(project, explicit_fields)

    def _reconcile_lifecycle_approval_state(
        tenant_id: str,
        project_id: str,
        *,
        project: dict[str, Any],
        persist: bool,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        approval_status = str(project.get("approvalStatus", "pending") or "pending")
        approval = _current_lifecycle_approval(project)
        if approval_status != "approved":
            return project, approval

        if approval is None:
            normalized = merge_lifecycle_project_record(
                project,
                {
                    "approvalStatus": "pending",
                    "approvalRequestId": None,
                },
            )
            _set_phase_status(normalized, "approval", "review")
            if persist:
                normalized = _persist_lifecycle_project(tenant_id, project_id, normalized)
            return normalized, None

        binding = build_lifecycle_approval_binding(project)
        manager = _lifecycle_approval_manager()
        try:
            _run_coro(
                manager.validate_binding(
                    str(approval.get("id", "")),
                    plan=binding["plan"],
                    effect_envelope=binding["effect_envelope"],
                )
            )
        except (ApprovalAlreadyDecidedError, ApprovalBindingMismatchError, ApprovalNotFoundError):
            normalized = merge_lifecycle_project_record(
                project,
                {
                    "approvalStatus": "pending",
                    "approvalRequestId": None,
                },
            )
            _set_phase_status(normalized, "approval", "review")
            if persist:
                normalized = _persist_lifecycle_project(tenant_id, project_id, normalized)
            return normalized, None
        return project, approval

    def _apply_lifecycle_approval_decision(
        tenant_id: str,
        project_id: str,
        *,
        project: dict[str, Any],
        decision: str,
        note: str,
        requested_steps: int,
        mode_override: str | None = None,
        record_comment: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        current, approval = _reconcile_lifecycle_approval_state(
            tenant_id,
            project_id,
            project=project,
            persist=False,
        )
        manager = _lifecycle_approval_manager()
        comment_type = "comment"

        if decision == "pending":
            current, approval = _ensure_lifecycle_approval_request(
                tenant_id,
                project_id,
                project=current,
            )
            current = merge_lifecycle_project_record(current, {"approvalStatus": "pending"})
            _set_phase_status(current, "approval", "review")
        elif decision == "approved":
            if approval is None or approval.get("status") != "pending":
                current, approval = _ensure_lifecycle_approval_request(
                    tenant_id,
                    project_id,
                    project=current,
                )
            approval_id = str(current.get("approvalRequestId") or approval.get("id", ""))
            binding = build_lifecycle_approval_binding(current)
            _run_coro(manager.approve(approval_id, "lifecycle-api", comment=note))
            _run_coro(
                manager.validate_binding(
                    approval_id,
                    plan=binding["plan"],
                    effect_envelope=binding["effect_envelope"],
                )
            )
            current = merge_lifecycle_project_record(
                current,
                {
                    "approvalStatus": "approved",
                    "approvalRequestId": approval_id,
                },
            )
            _set_phase_status(current, "approval", "completed")
            comment_type = "approve"
        else:
            approval_id = str(current.get("approvalRequestId") or "")
            if approval is not None and approval.get("status") == "pending" and approval_id:
                _run_coro(manager.reject(approval_id, "lifecycle-api", note or decision))
            current = merge_lifecycle_project_record(
                current,
                {
                    "approvalStatus": decision,
                    "approvalRequestId": approval_id if approval_id and approval is not None and approval.get("status") == "pending" else None,
                },
            )
            _set_phase_status(current, "approval", "review")
            comment_type = "reject"

        current = _record_lifecycle_approval_state(
            current,
            project_id=project_id,
            decision=decision,
            note=note,
        )
        if record_comment and note:
            current = _append_lifecycle_approval_comment(
                current,
                text=note,
                comment_type=comment_type,
            )
        current = _persist_lifecycle_project(tenant_id, project_id, current)

        resolved_mode = resolve_lifecycle_orchestration_mode(current, override=mode_override)
        if decision == "approved" and resolved_mode == "autonomous":
            return _execute_lifecycle_progression(
                tenant_id,
                project_id,
                project=current,
                requested_steps=requested_steps,
                mode_override=resolved_mode,
            )
        return current, [], derive_lifecycle_next_action(current, mode_override=resolved_mode)

    def _prepare_lifecycle_phase_internal(
        tenant_id: str,
        project_id: str,
        phase: str,
        *,
        project_record: dict[str, Any] | None = None,
    ) -> tuple[str, PylonProject, dict[str, Any]]:
        _seed_lifecycle_skills()
        definition = build_lifecycle_workflow_definition(project_id, phase)
        workflow_id = _lifecycle_workflow_id(project_id, phase)
        workflow_project = s.register_workflow_project(workflow_id, definition["project"], tenant_id=tenant_id)
        raw_store = s.control_plane_store
        if hasattr(raw_store, "set_handlers"):
            raw_store.set_handlers(
                workflow_id,
                node_handlers=build_lifecycle_workflow_handlers(
                    phase,
                    provider_registry=provider_registry,
                ),
            )
        lifecycle_project = project_record or _get_lifecycle_project(tenant_id, project_id, create=True)
        if lifecycle_project is None:
            raise KeyError(f"Lifecycle project not found: {project_id}")
        _set_phase_status(lifecycle_project, phase, "in_progress")
        persisted = merge_lifecycle_project_record(lifecycle_project, {"phaseStatuses": lifecycle_project.get("phaseStatuses", [])})
        return workflow_id, workflow_project, _persist_lifecycle_project(tenant_id, project_id, persisted)

    def _sync_lifecycle_phase_run_internal(
        tenant_id: str,
        project_id: str,
        phase: str,
        *,
        project_record: dict[str, Any],
        run_record: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        checkpoints = workflow_service.list_checkpoint_payloads(tenant_id=tenant_id, run_id=str(run_record["id"]))
        patch = sync_lifecycle_project_with_run(project_record, phase=phase, run_record=run_record, checkpoints=checkpoints)
        merged = merge_lifecycle_project_record(project_record, patch)
        persisted = _persist_lifecycle_project(tenant_id, project_id, merged)
        latest_phase_run = next((item for item in persisted.get("phaseRuns", []) if item.get("runId") == run_record.get("id")), None)
        return persisted, latest_phase_run

    def _run_lifecycle_deploy_checks_internal(
        tenant_id: str,
        project_id: str,
        *,
        project: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        checks_payload = build_deploy_checks(project)
        merged = merge_lifecycle_project_record(
            project,
            {
                "deployChecks": checks_payload["checks"],
                **merge_operator_records(
                    project,
                    artifacts=[
                        lifecycle_artifact(
                            artifact_id=f"deploy-checks:{project_id}:{uuid.uuid4().hex[:8]}",
                            phase="deploy",
                            kind="deploy_checks",
                            title="Release gate summary",
                            summary=f"Score {checks_payload['summary']['overallScore']} with {checks_payload['summary']['failed']} failing checks.",
                            payload=checks_payload,
                        )
                    ],
                    decisions=[
                        lifecycle_decision(
                            decision_id=f"deploy-gate:{project_id}:{uuid.uuid4().hex[:8]}",
                            phase="deploy",
                            kind="release_gate",
                            title="Release gate evaluated",
                            rationale="Release is ready." if checks_payload["summary"]["releaseReady"] else "Release remains blocked until failing checks are cleared.",
                            status="approved" if checks_payload["summary"]["releaseReady"] else "blocked",
                            details=checks_payload["summary"],
                        )
                    ],
                ),
            },
        )
        _set_phase_status(merged, "deploy", "review")
        return _persist_lifecycle_project(tenant_id, project_id, merged), checks_payload

    def _create_lifecycle_release_internal(
        tenant_id: str,
        project_id: str,
        *,
        project: dict[str, Any],
        note: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        release_record = build_release_record(project, note=note)
        releases = list(project.get("releases", []))
        releases.insert(0, release_record)
        merged = merge_lifecycle_project_record(
            project,
            {
                "releases": releases,
                **merge_operator_records(
                    project,
                    artifacts=[
                        lifecycle_artifact(
                            artifact_id=f"release-record:{release_record['id']}",
                            phase="deploy",
                            kind="release_record",
                            title=f"Release {release_record['version']}",
                            summary=note or "Release record created.",
                            created_at=release_record["createdAt"],
                            payload=release_record,
                        )
                    ],
                    decisions=[
                        lifecycle_decision(
                            decision_id=f"release-decision:{release_record['id']}",
                            phase="deploy",
                            kind="release_creation",
                            title="Release created",
                            rationale=note or f"Created {release_record['version']} after passing release gates.",
                            created_at=release_record["createdAt"],
                            status="approved",
                            details=release_record["qualitySummary"],
                        )
                    ],
                ),
            },
        )
        _set_phase_status(merged, "deploy", "completed")
        return _persist_lifecycle_project(tenant_id, project_id, merged), release_record

    def _execute_lifecycle_progression(
        tenant_id: str,
        project_id: str,
        *,
        project: dict[str, Any],
        requested_steps: int,
        mode_override: str | None = None,
        release_note: str = "",
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        orchestration_mode = resolve_lifecycle_orchestration_mode(project, override=mode_override)
        resolve_lifecycle_autonomy_level(project)
        if requested_steps <= 0:
            return project, [], derive_lifecycle_next_action(project, mode_override=orchestration_mode)
        step_budget = lifecycle_action_execution_budget(
            project,
            requested_steps=requested_steps,
            mode_override=mode_override,
        )
        actions: list[dict[str, Any]] = []
        current, _ = _reconcile_lifecycle_approval_state(
            tenant_id,
            project_id,
            project=project,
            persist=True,
        )

        if step_budget == 0:
            next_action = derive_lifecycle_next_action(current, mode_override=orchestration_mode)
            actions.append(
                {
                    "action": next_action,
                    "executed": False,
                    "reason": "Workflow mode does not auto-execute lifecycle steps. Use explicit phase workflow endpoints or switch orchestration mode.",
                }
            )
            return current, actions, next_action

        for _ in range(step_budget):
            next_action = derive_lifecycle_next_action(current, mode_override=orchestration_mode)
            action_record: dict[str, Any] = {"action": next_action}
            actions.append(action_record)

            if next_action["type"] == "run_phase":
                phase = str(next_action.get("phase", ""))
                workflow_id, _, current = _prepare_lifecycle_phase_internal(
                    tenant_id,
                    project_id,
                    phase,
                    project_record=current,
                )
                stored_run = workflow_service.start_run(
                    workflow_id=workflow_id,
                    tenant_id=tenant_id,
                    input_data=next_action.get("payload", {}).get("input") or lifecycle_phase_input(current, phase),
                    parameters={},
                    execution_mode="inline",
                )
                action_record["workflow_id"] = workflow_id
                action_record["run_id"] = stored_run["id"]
                action_record["run_status"] = stored_run["status"]
                if stored_run["status"] == "completed":
                    current, latest_phase_run = _sync_lifecycle_phase_run_internal(
                        tenant_id,
                        project_id,
                        phase,
                        project_record=current,
                        run_record=stored_run,
                    )
                    action_record["phase_run"] = latest_phase_run
                    continue
                break

            if next_action["type"] == "request_approval":
                current, approval = _ensure_lifecycle_approval_request(
                    tenant_id,
                    project_id,
                    project=current,
                )
                action_record["approval"] = approval
                break

            if next_action["type"] == "auto_approve":
                current, nested_actions, nested_next_action = _apply_lifecycle_approval_decision(
                    tenant_id,
                    project_id,
                    project=current,
                    decision="approved",
                    note="Auto-approved by the lifecycle A4 full-autonomy policy.",
                    requested_steps=0,
                    mode_override=orchestration_mode,
                    record_comment=True,
                )
                action_record["approval"] = _current_lifecycle_approval(current)
                action_record["approval_status"] = current.get("approvalStatus")
                action_record["nested_actions"] = nested_actions
                action_record["resulting_next_action"] = nested_next_action
                continue

            if next_action["type"] == "run_deploy_checks":
                current, checks_payload = _run_lifecycle_deploy_checks_internal(
                    tenant_id,
                    project_id,
                    project=current,
                )
                action_record["checks_summary"] = checks_payload["summary"]
                continue

            if next_action["type"] == "create_release":
                current, release_record = _create_lifecycle_release_internal(
                    tenant_id,
                    project_id,
                    project=current,
                    note=release_note,
                )
                action_record["release"] = release_record
                continue

            break

        return current, actions, derive_lifecycle_next_action(current, mode_override=orchestration_mode)

    def _get_lifecycle_project(
        tenant_id: str,
        project_id: str,
        *,
        create: bool,
    ) -> dict[str, Any] | None:
        key = _lifecycle_project_key(tenant_id, project_id)
        existing = s.get_surface_record("lifecycle_projects", key)
        if existing is not None:
            return dict(existing)
        if not create:
            return None
        created = default_lifecycle_project_record(project_id, tenant_id=tenant_id)
        s.put_surface_record("lifecycle_projects", key, created)
        return created

    def list_lifecycle_projects(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        records = s.list_surface_records("lifecycle_projects", tenant_id=tenant_id)
        records.sort(key=lambda record: str(record.get("updatedAt", record.get("createdAt", ""))), reverse=True)
        return Response(body={"projects": [_lifecycle_project_payload(record) for record in records], "count": len(records)})

    def get_lifecycle_project(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        return Response(body=_lifecycle_project_payload(project))

    def update_lifecycle_project(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        operator_patch: dict[str, Any] = {}
        selected_design = body.get("selectedDesignId")
        if isinstance(selected_design, str) and selected_design and selected_design != project.get("selectedDesignId"):
            operator_patch = merge_operator_records(
                project,
                decisions=[
                    lifecycle_decision(
                        decision_id=f"design-selection:{project_id}:{selected_design}",
                        phase="design",
                        kind="design_selection",
                        title="Operator selected a design direction",
                        rationale=f"Selected design variant {selected_design} as the build baseline.",
                        details={"selectedDesignId": selected_design},
                    )
                ],
            )
        merged = merge_lifecycle_project_record(project, body)
        if operator_patch:
            merged = merge_lifecycle_project_record(merged, operator_patch)
        changed_fields = {
            field_name
            for field_name in {
                "spec",
                "researchConfig",
                "research",
                "analysis",
                "features",
                "milestones",
                "planEstimates",
                "designVariants",
                "selectedDesignId",
                "selectedPreset",
            }
            if field_name in body and body.get(field_name) != project.get(field_name)
        }
        if changed_fields:
            merged = _apply_lifecycle_lineage_reset(
                merged,
                project_id=project_id,
                changed_fields=changed_fields,
            )
            merged = _preserve_explicit_lifecycle_overrides(merged, body=body)
        merged = _persist_lifecycle_project(tenant_id, project_id, merged)

        auto_run = bool(body.get("auto_run", True))
        try:
            mode = resolve_lifecycle_orchestration_mode(merged)
            resolve_lifecycle_autonomy_level(merged)
        except ValueError as exc:
            return Response(status_code=422, body={"errors": [str(exc)]})

        actions: list[dict[str, Any]] = []
        next_action = derive_lifecycle_next_action(merged, mode_override=mode)
        if auto_run and mode == "autonomous":
            try:
                merged, actions, next_action = _execute_lifecycle_progression(
                    tenant_id,
                    project_id,
                    project=merged,
                    requested_steps=_parse_lifecycle_max_steps(body, default=8),
                    mode_override=mode,
                )
            except ValueError as exc:
                return Response(status_code=422, body={"errors": [str(exc)]})
            except KeyError as exc:
                return Response(status_code=404, body={"error": str(exc)})
        return Response(body=_lifecycle_mutation_response(merged, actions=actions, next_action=next_action))

    def get_lifecycle_blueprints(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        return Response(body={"project_id": project_id, "tenant_id": tenant_id, "blueprints": build_lifecycle_phase_blueprints(project_id)})

    def prepare_lifecycle_phase(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        phase = request.path_params.get("phase", "")
        if phase not in {"research", "planning", "design", "development"}:
            return Response(status_code=422, body={"errors": [f"Unsupported executable lifecycle phase: {phase}"]})
        workflow_id, project, _ = _prepare_lifecycle_phase_internal(tenant_id, project_id, phase)
        blueprints = build_lifecycle_phase_blueprints(project_id)
        return Response(
            status_code=201,
            body={
                "project_id": project_id,
                "phase": phase,
                "workflow_id": workflow_id,
                "blueprint": blueprints[phase],
                "workflow": _workflow_summary(workflow_id, project, tenant_id=tenant_id),
            },
        )

    def sync_lifecycle_phase_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        phase = request.path_params.get("phase", "")
        if phase not in {"research", "planning", "design", "development"}:
            return Response(status_code=422, body={"errors": [f"Unsupported executable lifecycle phase: {phase}"]})
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        run_id = str(body.get("run_id", "")).strip()
        if not run_id:
            return Response(status_code=422, body={"errors": ["Field 'run_id' is required"]})
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id", tenant_id) != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        expected_workflow_id = _lifecycle_workflow_id(project_id, phase)
        if run.get("workflow_id") != expected_workflow_id:
            return Response(
                status_code=409,
                body={"error": f"Run {run_id} does not belong to lifecycle phase {phase} for project {project_id}"},
            )
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        merged, latest_phase_run = _sync_lifecycle_phase_run_internal(
            tenant_id,
            project_id,
            phase,
            project_record=project,
            run_record=run,
        )
        return Response(body={"project": _lifecycle_project_payload(merged), "phase_run": latest_phase_run})

    def advance_lifecycle_project(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        body = request.body or {}
        if body not in ({}, None) and not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        execution_mode = str(body.get("execution_mode", "inline") or "inline") if isinstance(body, dict) else "inline"
        release_note = str(body.get("release_note", "") or "") if isinstance(body, dict) else ""
        mode_override = str(body.get("orchestration_mode", "") or "").strip().lower() if isinstance(body, dict) and body.get("orchestration_mode") else None
        try:
            max_steps = _parse_lifecycle_max_steps(body if isinstance(body, dict) else None, default=1)
        except ValueError as exc:
            return Response(status_code=422, body={"errors": [str(exc)]})
        if execution_mode != "inline":
            return Response(status_code=422, body={"errors": ["Lifecycle auto-advance currently supports only inline execution"]})
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        try:
            current, actions, next_action = _execute_lifecycle_progression(
                tenant_id,
                project_id,
                project=project,
                requested_steps=max_steps,
                mode_override=mode_override,
                release_note=release_note,
            )
        except ValueError as exc:
            return Response(status_code=422, body={"errors": [str(exc)]})
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})

        return Response(
            body={
                "project": _lifecycle_project_payload(current),
                "actions": actions,
                "nextAction": next_action,
            }
        )

    def add_lifecycle_approval_comment(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        text = str(body.get("text", "")).strip()
        comment_type = str(body.get("type", "comment") or "comment")
        if comment_type not in {"comment", "approve", "reject"}:
            return Response(status_code=422, body={"errors": ["Field 'type' must be one of ['comment', 'approve', 'reject']"]})
        if not text:
            text = "承認しました" if comment_type == "approve" else "差し戻しました" if comment_type == "reject" else ""
        if not text:
            return Response(status_code=422, body={"errors": ["Field 'text' is required"]})
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        try:
            max_steps = _parse_lifecycle_max_steps(body, default=8)
        except ValueError as exc:
            return Response(status_code=422, body={"errors": [str(exc)]})

        if comment_type == "comment":
            merged = _append_lifecycle_approval_comment(project, text=text, comment_type=comment_type)
            merged = _persist_lifecycle_project(tenant_id, project_id, merged)
            return Response(
                body=_lifecycle_mutation_response(
                    merged,
                    actions=[],
                    next_action=derive_lifecycle_next_action(merged),
                )
            )

        decision = "approved" if comment_type == "approve" else "revision_requested"
        try:
            merged, actions, next_action = _apply_lifecycle_approval_decision(
                tenant_id,
                project_id,
                project=project,
                decision=decision,
                note=text,
                requested_steps=max_steps,
                record_comment=True,
            )
        except ApprovalNotFoundError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except (ApprovalAlreadyDecidedError, ApprovalBindingMismatchError, ValueError) as exc:
            return Response(status_code=409, body={"error": str(exc)})
        return Response(body=_lifecycle_mutation_response(merged, actions=actions, next_action=next_action))

    def decide_lifecycle_approval(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        decision = str(body.get("decision", ""))
        if decision not in {"approved", "rejected", "revision_requested", "pending"}:
            return Response(status_code=422, body={"errors": ["Field 'decision' must be a valid approval state"]})
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        note = str(body.get("comment", "")).strip()
        try:
            max_steps = _parse_lifecycle_max_steps(body, default=8)
        except ValueError as exc:
            return Response(status_code=422, body={"errors": [str(exc)]})
        try:
            merged, actions, next_action = _apply_lifecycle_approval_decision(
                tenant_id,
                project_id,
                project=project,
                decision=decision,
                note=note,
                requested_steps=max_steps,
                record_comment=bool(note),
            )
        except ApprovalNotFoundError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except (ApprovalAlreadyDecidedError, ApprovalBindingMismatchError, ValueError) as exc:
            return Response(status_code=409, body={"error": str(exc)})
        return Response(body=_lifecycle_mutation_response(merged, actions=actions, next_action=next_action))

    def run_lifecycle_deploy_checks(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        body = request.body or {}
        if isinstance(body, dict) and body.get("buildCode"):
            project = merge_lifecycle_project_record(project, {"buildCode": body.get("buildCode")})
        if not project.get("buildCode"):
            return Response(status_code=422, body={"errors": ["Lifecycle project has no buildCode to validate"]})
        merged, checks_payload = _run_lifecycle_deploy_checks_internal(tenant_id, project_id, project=project)
        return Response(body={"project": _lifecycle_project_payload(merged), **checks_payload})

    def create_lifecycle_release(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        body = request.body or {}
        note = str(body.get("note", "")).strip() if isinstance(body, dict) else ""
        try:
            merged, release_record = _create_lifecycle_release_internal(tenant_id, project_id, project=project, note=note)
        except ValueError as exc:
            return Response(status_code=422, body={"errors": [str(exc)]})
        return Response(status_code=201, body={"project": _lifecycle_project_payload(merged), "release": release_record})

    def list_lifecycle_feedback(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        return Response(body={"feedbackItems": list(project.get("feedbackItems", [])), "recommendations": refresh_lifecycle_recommendations(project)})

    def create_lifecycle_feedback(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        text = str(body.get("text", "")).strip()
        feedback_type = str(body.get("type", "improvement") or "improvement")
        impact = str(body.get("impact", "medium") or "medium")
        if not text:
            return Response(status_code=422, body={"errors": ["Field 'text' is required"]})
        if feedback_type not in {"bug", "feature", "improvement", "praise"}:
            return Response(status_code=422, body={"errors": ["Field 'type' must be a valid feedback type"]})
        if impact not in {"low", "medium", "high"}:
            return Response(status_code=422, body={"errors": ["Field 'impact' must be one of ['low', 'medium', 'high']"]})
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        feedbacks = list(project.get("feedbackItems", []))
        feedbacks.insert(
            0,
            {
                "id": f"fb-{uuid.uuid4().hex[:8]}",
                "type": feedback_type,
                "text": text,
                "impact": impact,
                "votes": 0,
                "createdAt": _utc_now_iso(),
            },
        )
        feedback_record = feedbacks[0]
        merged = merge_lifecycle_project_record(
            project,
            {
                "feedbackItems": feedbacks,
                **merge_operator_records(
                    project,
                    artifacts=[
                        lifecycle_artifact(
                            artifact_id=f"feedback-item:{feedback_record['id']}",
                            phase="iterate",
                            kind="feedback_item",
                            title="Feedback captured",
                            summary=feedback_record["text"],
                            created_at=feedback_record["createdAt"],
                            payload=feedback_record,
                        )
                    ],
                    decisions=[
                        lifecycle_decision(
                            decision_id=f"feedback-ingest:{feedback_record['id']}",
                            phase="iterate",
                            kind="feedback_ingest",
                            title="Feedback entered the backlog",
                            rationale=feedback_record["text"],
                            created_at=feedback_record["createdAt"],
                            details={"type": feedback_record["type"], "impact": feedback_record["impact"]},
                        )
                    ],
                ),
            },
        )
        _set_phase_status(merged, "iterate", "in_progress")
        merged["recommendations"] = refresh_lifecycle_recommendations(merged)
        s.put_surface_record("lifecycle_projects", _lifecycle_project_key(tenant_id, project_id), merged)
        return Response(status_code=201, body={"project": _lifecycle_project_payload(merged), "feedbackItems": feedbacks})

    def vote_lifecycle_feedback(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        feedback_id = request.path_params.get("feedback_id", "")
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        delta = body.get("delta", 0)
        if not isinstance(delta, int):
            return Response(status_code=422, body={"errors": ["Field 'delta' must be an integer"]})
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        feedbacks = list(project.get("feedbackItems", []))
        updated = False
        for item in feedbacks:
            if isinstance(item, dict) and item.get("id") == feedback_id:
                item["votes"] = max(0, int(item.get("votes", 0)) + delta)
                updated = True
                break
        if not updated:
            return Response(status_code=404, body={"error": f"Feedback not found: {feedback_id}"})
        merged = merge_lifecycle_project_record(
            project,
            {
                "feedbackItems": feedbacks,
                **merge_operator_records(
                    project,
                    decisions=[
                        lifecycle_decision(
                            decision_id=f"feedback-priority:{feedback_id}:{max(0, delta)}:{len(feedbacks)}",
                            phase="iterate",
                            kind="feedback_reprioritized",
                            title="Feedback priority changed",
                            rationale=f"Feedback {feedback_id} vote delta {delta}.",
                            details={"feedbackId": feedback_id, "delta": delta},
                        )
                    ],
                ),
            },
        )
        merged["recommendations"] = refresh_lifecycle_recommendations(merged)
        s.put_surface_record("lifecycle_projects", _lifecycle_project_key(tenant_id, project_id), merged)
        return Response(body={"project": _lifecycle_project_payload(merged), "feedbackItems": feedbacks})

    def get_lifecycle_recommendations(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        project_id = request.path_params.get("project_id", "")
        project = _get_lifecycle_project(tenant_id, project_id, create=True)
        if project is None:
            return Response(status_code=404, body={"error": f"Lifecycle project not found: {project_id}"})
        recommendations = refresh_lifecycle_recommendations(project)
        merged = merge_lifecycle_project_record(project, {"recommendations": recommendations})
        s.put_surface_record("lifecycle_projects", _lifecycle_project_key(tenant_id, project_id), merged)
        return Response(body={"recommendations": recommendations})

    def _ensure_default_teams(tenant_id: str) -> list[dict[str, Any]]:
        existing = [
            dict(team)
            for team in s.teams.values()
            if team.get("tenant_id") == tenant_id
        ]
        if existing:
            return sorted(existing, key=lambda team: str(team.get("name", "")))
        for definition in DEFAULT_TEAM_DEFINITIONS:
            payload = dict(definition)
            payload["tenant_id"] = tenant_id
            payload["created_at"] = _utc_now_iso()
            s.teams[_team_store_key(tenant_id, payload["id"])] = payload
        return _ensure_default_teams(tenant_id)

    def _team_record(tenant_id: str, team_id: str) -> dict[str, Any] | None:
        _ensure_default_teams(tenant_id)
        return s.teams.get(_team_store_key(tenant_id, team_id))

    def _default_team_id(tenant_id: str) -> str:
        teams = _ensure_default_teams(tenant_id)
        for team in teams:
            if team.get("id") == "product":
                return str(team["id"])
        return str(teams[0]["id"]) if teams else "product"

    def _task_matches_agent(task: dict[str, Any], agent: dict[str, Any]) -> bool:
        assignee = str(task.get("assignee", ""))
        return assignee in {str(agent.get("id", "")), str(agent.get("name", ""))}

    def _current_task_for_agent(tenant_id: str, agent: dict[str, Any]) -> dict[str, Any] | None:
        active = [
            task for task in s.tasks.values()
            if task.get("tenant_id") == tenant_id
            and task.get("status") in {"backlog", "in_progress", "review"}
            and _task_matches_agent(task, agent)
        ]
        if not active:
            return None
        active.sort(key=lambda task: str(task.get("updated_at", task.get("created_at", ""))), reverse=True)
        return dict(active[0])

    def _agent_activity_payload(tenant_id: str, agent: dict[str, Any]) -> dict[str, Any]:
        created_at = str(agent.get("created_at") or _utc_now_iso())
        uptime_seconds = max(
            0,
            int((datetime.now(UTC) - _parse_iso_datetime(created_at)).total_seconds()),
        )
        return {
            "id": str(agent.get("id", "")),
            "name": str(agent.get("name", "")),
            "model": str(agent.get("model", "")),
            "role": str(agent.get("role", "")),
            "autonomy": str(agent.get("autonomy", "A2")),
            "tools": list(agent.get("tools", [])),
            "sandbox": str(agent.get("sandbox", "gvisor")),
            "status": str(agent.get("status", "ready")),
            "team": agent.get("team") or _default_team_id(tenant_id),
            "tenant_id": tenant_id,
            "current_task": _current_task_for_agent(tenant_id, agent),
            "uptime_seconds": uptime_seconds,
        }

    def _industry_template(industry_type: str) -> dict[str, Any]:
        for template in ADS_INDUSTRY_TEMPLATES:
            if template["id"] == industry_type:
                return dict(template)
        return dict(ADS_INDUSTRY_TEMPLATES[-1])

    def _build_ads_check(
        *,
        platform: str,
        category: str,
        name: str,
        severity: str,
        result: str,
        finding: str,
        remediation: str,
        estimated_fix_time_min: int,
        is_quick_win: bool,
    ) -> dict[str, Any]:
        return {
            "id": f"{platform}-{_slugify_identifier(category, prefix='cat')}-{_slugify_identifier(name, prefix='check')}",
            "category": category,
            "name": name,
            "severity": severity,
            "result": result,
            "finding": finding,
            "remediation": remediation,
            "estimated_fix_time_min": estimated_fix_time_min,
            "is_quick_win": is_quick_win,
        }

    def _build_ads_report(
        *,
        tenant_id: str,
        platforms: list[str],
        industry_type: str,
        monthly_budget: int | None,
        account_data: dict[str, str],
    ) -> dict[str, Any]:
        template = _industry_template(industry_type)
        recommended_weights = _normalize_weight_map(
            {platform: float(weight) for platform, weight in template["platforms"].items()}
        )
        selected_platforms = platforms or list(recommended_weights.keys()) or list(ADS_PLATFORMS)
        selection_weights: dict[str, float] = {}
        for platform in selected_platforms:
            selection_weights[platform] = recommended_weights.get(platform, 1.0)
        selection_weights = _normalize_weight_map(selection_weights)
        effective_budget = int(monthly_budget or template["min_monthly"])
        score_by_result = {"pass": 100, "warning": 68, "fail": 38, "na": 55}
        report_platforms: list[dict[str, Any]] = []
        all_checks: list[dict[str, Any]] = []

        for platform in selected_platforms:
            benchmark = ADS_BENCHMARKS.get(platform, {})
            expected_share = float(selection_weights.get(platform, 0.0))
            platform_budget = int(round(effective_budget * expected_share))
            minimum_share_budget = int(round(template["min_monthly"] * expected_share))
            seed = _stable_seed(platform, industry_type, platform_budget)
            tracking_ready = bool(account_data.get(platform))
            budget_ratio = (
                platform_budget / minimum_share_budget
                if minimum_share_budget > 0 else 1.0
            )
            targeting_strength = template["platforms"].get(platform, 0)

            budget_result = "pass" if budget_ratio >= 1 else "warning" if budget_ratio >= 0.7 else "fail"
            tracking_result = "pass" if tracking_ready else "warning"
            creative_result = "pass" if seed % 7 not in {0, 1} else "warning"
            targeting_result = "pass" if targeting_strength >= 25 else "warning"
            compliance_result = "pass"
            if industry_type in {"finance", "healthcare"} and platform in {"meta", "tiktok"}:
                compliance_result = "warning" if tracking_ready else "fail"

            checks = [
                _build_ads_check(
                    platform=platform,
                    category="budget",
                    name="Budget concentration",
                    severity="high" if budget_result == "fail" else "medium",
                    result=budget_result,
                    finding=(
                        f"{platform} receives ${platform_budget:,} against a reference floor of ${minimum_share_budget:,}."
                    ),
                    remediation="Concentrate spend on the top two channels until each core campaign is fully funded.",
                    estimated_fix_time_min=25,
                    is_quick_win=budget_result != "pass",
                ),
                _build_ads_check(
                    platform=platform,
                    category="tracking",
                    name="Tracking integrity",
                    severity="critical" if tracking_result == "fail" else "high",
                    result=tracking_result,
                    finding=(
                        "Account-level data is present and conversion tracking can be validated."
                        if tracking_ready
                        else "No account export was supplied, so tracking health cannot be fully verified."
                    ),
                    remediation="Export the last 30 days of campaign data and verify conversion events before scaling spend.",
                    estimated_fix_time_min=35,
                    is_quick_win=tracking_result != "pass",
                ),
                _build_ads_check(
                    platform=platform,
                    category="creative",
                    name="Creative freshness",
                    severity="medium",
                    result=creative_result,
                    finding=(
                        "Creative rotation cadence looks healthy for the selected channel."
                        if creative_result == "pass"
                        else "Refresh cadence appears light for this channel; ad fatigue risk is rising."
                    ),
                    remediation="Launch one new concept and two variant hooks to refresh CTR before scaling.",
                    estimated_fix_time_min=45,
                    is_quick_win=creative_result == "warning",
                ),
                _build_ads_check(
                    platform=platform,
                    category="targeting",
                    name="Audience-platform fit",
                    severity="medium",
                    result=targeting_result,
                    finding=(
                        f"{platform} is a strong fit for the {industry_type} motion."
                        if targeting_result == "pass"
                        else f"{platform} is a secondary channel for {industry_type}; keep it in a learning budget."
                    ),
                    remediation="Tighten audience intent and keep secondary channels on a controlled experiment budget.",
                    estimated_fix_time_min=20,
                    is_quick_win=targeting_result == "warning",
                ),
                _build_ads_check(
                    platform=platform,
                    category="compliance",
                    name="Policy and compliance posture",
                    severity="critical" if compliance_result == "fail" else "high",
                    result=compliance_result,
                    finding=(
                        "No obvious compliance friction was detected for the selected setup."
                        if compliance_result == "pass"
                        else "This channel requires stricter creative and data hygiene for the selected industry."
                    ),
                    remediation="Review regulated-claim copy, disclosure language, and landing-page proof before the next launch.",
                    estimated_fix_time_min=60,
                    is_quick_win=False,
                ),
            ]
            category_scores: dict[str, int] = {}
            for check in checks:
                category_scores.setdefault(check["category"], 0)
                category_scores[check["category"]] += score_by_result[check["result"]]
            category_scores = {
                category: int(round(total / len([check for check in checks if check["category"] == category])))
                for category, total in category_scores.items()
            }
            raw_score = int(round(sum(score_by_result[check["result"]] for check in checks) / len(checks)))
            raw_score = min(max(raw_score + int(round(benchmark.get("benchmark_mer", 3.0) * 2)) - 6, 0), 100)
            platform_payload = {
                "platform": platform,
                "score": raw_score,
                "grade": _grade_from_score(raw_score),
                "budget_share": round(expected_share, 3),
                "checks": checks,
                "category_scores": category_scores,
            }
            report_platforms.append(platform_payload)
            all_checks.extend(checks)

        aggregate_score = int(round(sum(platform["score"] for platform in report_platforms) / max(len(report_platforms), 1)))
        quick_wins = [
            check for check in all_checks
            if check["is_quick_win"] and check["result"] in {"warning", "fail"}
        ]
        quick_wins.sort(key=lambda check: (check["estimated_fix_time_min"], check["severity"]))
        critical_issues = [
            check for check in all_checks
            if check["severity"] == "critical" and check["result"] == "fail"
        ]
        passed_checks = sum(1 for check in all_checks if check["result"] == "pass")
        warning_checks = sum(1 for check in all_checks if check["result"] == "warning")
        failed_checks = sum(1 for check in all_checks if check["result"] == "fail")
        report_id = uuid.uuid4().hex[:12]
        return {
            "id": report_id,
            "tenant_id": tenant_id,
            "created_at": _utc_now_iso(),
            "industry_type": industry_type,
            "aggregate_score": aggregate_score,
            "aggregate_grade": _grade_from_score(aggregate_score),
            "platforms": report_platforms,
            "quick_wins": quick_wins[:8],
            "critical_issues": critical_issues[:8],
            "cross_platform": {
                "budget_assessment": (
                    "Budget is below the reference floor; prioritize the top one or two channels."
                    if effective_budget < int(template["min_monthly"])
                    else "Budget concentration is healthy enough to support a stable test-and-scale motion."
                ),
                "tracking_consistency": (
                    "Tracking evidence was supplied for every audited channel."
                    if all(account_data.get(platform) for platform in selected_platforms)
                    else "Tracking coverage is partial; align naming, pixel events, and offline conversion uploads."
                ),
                "creative_consistency": (
                    "Creative strategy is reasonably aligned across platforms."
                    if len(quick_wins) <= 2
                    else "Creative refresh cadence is uneven across channels; align hooks and landing-page proof."
                ),
                "attribution_overlap": (
                    "Cross-platform overlap looks contained because the plan is concentrated."
                    if len(selected_platforms) <= 2
                    else "Audit assisted attribution overlap on branded and retargeting traffic before scaling."
                ),
            },
            "total_checks": len(all_checks),
            "passed_checks": passed_checks,
            "warning_checks": warning_checks,
            "failed_checks": failed_checks,
        }

    def _audit_run_payload(run: dict[str, Any]) -> dict[str, Any]:
        elapsed = max(0.0, time.time() - float(run.get("created_at_epoch", time.time())))
        progress: dict[str, str] = {}
        completed = min(len(DEFAULT_AUDIT_AGENTS), int(elapsed / 0.45))
        for index, node_id in enumerate(DEFAULT_AUDIT_AGENTS):
            if completed >= len(DEFAULT_AUDIT_AGENTS):
                progress[node_id] = "completed"
            elif index < completed:
                progress[node_id] = "completed"
            elif index == completed:
                progress[node_id] = "running"
            else:
                progress[node_id] = "pending"
        status = "completed" if completed >= len(DEFAULT_AUDIT_AGENTS) else "running"
        payload = {
            "run_id": str(run.get("id", "")),
            "status": status,
            "progress": progress,
        }
        if status == "completed":
            report = s.ads_reports.get(str(run.get("report_id", "")))
            if report is not None:
                payload["report"] = dict(report)
        return payload

    def list_tasks(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        status = _query_string(request, "status")
        if status and status not in MISSION_TASK_STATUSES:
            return Response(status_code=422, body={"errors": [f"Unsupported task status: {status}"]})
        tasks = _list_tenant_records(s.tasks, tenant_id=tenant_id, sort_key="updated_at")
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        return Response(body=tasks)

    def get_task(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        task_id = request.path_params.get("task_id", "")
        task = s.tasks.get(task_id)
        if task is None:
            return Response(status_code=404, body={"error": f"Task not found: {task_id}"})
        if task.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=dict(task))

    def create_task(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        errors: list[str] = []
        for field_name in ("title", "description", "status", "priority", "assignee", "assigneeType"):
            if not isinstance(body.get(field_name), str) or not str(body.get(field_name, "")).strip():
                errors.append(f"Field '{field_name}' is required")
        if body.get("status") not in MISSION_TASK_STATUSES:
            errors.append("Field 'status' must be one of ['backlog', 'in_progress', 'review', 'done']")
        if body.get("priority") not in MISSION_TASK_PRIORITIES:
            errors.append("Field 'priority' must be one of ['low', 'medium', 'high', 'critical']")
        if body.get("assigneeType") not in MISSION_ASSIGNEE_TYPES:
            errors.append("Field 'assigneeType' must be one of ['human', 'ai']")
        if "payload" in body and not isinstance(body["payload"], dict):
            errors.append("Field 'payload' must be of type dict")
        if errors:
            return Response(status_code=422, body={"errors": errors})
        now = _utc_now_iso()
        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "title": str(body["title"]).strip(),
            "name": str(body.get("name", body["title"])).strip(),
            "description": str(body["description"]).strip(),
            "status": body["status"],
            "priority": body["priority"],
            "assignee": str(body["assignee"]).strip(),
            "assigneeType": body["assigneeType"],
            "payload": dict(body.get("payload", {})),
            "created_at": now,
            "updated_at": now,
            "tenant_id": tenant_id,
        }
        s.tasks[task_id] = task
        return Response(status_code=201, body=dict(task))

    def update_task(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        task_id = request.path_params.get("task_id", "")
        task = s.tasks.get(task_id)
        if task is None:
            return Response(status_code=404, body={"error": f"Task not found: {task_id}"})
        if task.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        errors: list[str] = []
        if "status" in body and body["status"] not in MISSION_TASK_STATUSES:
            errors.append("Field 'status' must be one of ['backlog', 'in_progress', 'review', 'done']")
        if "priority" in body and body["priority"] not in MISSION_TASK_PRIORITIES:
            errors.append("Field 'priority' must be one of ['low', 'medium', 'high', 'critical']")
        if "assigneeType" in body and body["assigneeType"] not in MISSION_ASSIGNEE_TYPES:
            errors.append("Field 'assigneeType' must be one of ['human', 'ai']")
        if "payload" in body and not isinstance(body["payload"], dict):
            errors.append("Field 'payload' must be of type dict")
        for field_name in ("title", "name", "description", "assignee"):
            if field_name in body and not isinstance(body[field_name], str):
                errors.append(f"Field '{field_name}' must be of type str")
        if errors:
            return Response(status_code=422, body={"errors": errors})
        updated = dict(task)
        for field_name in ("title", "name", "description", "status", "priority", "assignee", "assigneeType"):
            if field_name in body:
                updated[field_name] = body[field_name]
        if "payload" in body:
            updated["payload"] = dict(body["payload"])
        updated["updated_at"] = _utc_now_iso()
        s.tasks[task_id] = updated
        return Response(body=dict(updated))

    def delete_task(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        task_id = request.path_params.get("task_id", "")
        task = s.tasks.get(task_id)
        if task is None:
            return Response(status_code=404, body={"error": f"Task not found: {task_id}"})
        if task.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        del s.tasks[task_id]
        return Response(status_code=204, body=None)

    def list_memories(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        return Response(body=_list_tenant_records(s.memories, tenant_id=tenant_id, sort_key="timestamp"))

    def create_memory(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        errors: list[str] = []
        for field_name in ("title", "content", "category", "actor"):
            if not isinstance(body.get(field_name), str) or not str(body.get(field_name, "")).strip():
                errors.append(f"Field '{field_name}' is required")
        if body.get("category") not in MISSION_MEMORY_CATEGORIES:
            errors.append("Field 'category' must be one of ['sessions', 'patterns', 'learnings', 'decisions']")
        details = body.get("details", {})
        if "details" in body and not isinstance(details, dict):
            errors.append("Field 'details' must be of type dict")
        tags = body.get("tags", [])
        if "tags" in body and (not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)):
            errors.append("Field 'tags' must contain only strings")
        if errors:
            return Response(status_code=422, body={"errors": errors})
        entry_id = s.control_plane_store.allocate_sequence_value("memories")
        memory = {
            "id": entry_id,
            "entry_id": entry_id,
            "tenant_id": tenant_id,
            "event_type": "memory.created",
            "actor": str(body["actor"]).strip(),
            "category": body["category"],
            "title": str(body["title"]).strip(),
            "content": str(body["content"]).strip(),
            "details": {
                **dict(details),
                "tags": list(tags if isinstance(tags, list) else details.get("tags", [])),
            },
            "timestamp": _utc_now_iso(),
        }
        s.memories[str(entry_id)] = memory
        return Response(status_code=201, body=dict(memory))

    def delete_memory(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        raw_entry_id = request.path_params.get("entry_id", "")
        if not raw_entry_id.isdigit():
            return Response(status_code=404, body={"error": f"Memory not found: {raw_entry_id}"})
        entry_id = int(raw_entry_id)
        memory = s.memories.get(str(entry_id))
        if memory is None:
            return Response(status_code=404, body={"error": f"Memory not found: {entry_id}"})
        if memory.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        del s.memories[str(entry_id)]
        return Response(status_code=204, body=None)

    def list_agents_activity(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agents = [
            _agent_activity_payload(tenant_id, agent)
            for agent in s.agents.values()
            if agent.get("tenant_id") == tenant_id
        ]
        agents.sort(key=lambda agent: (agent["team"], agent["name"]))
        return Response(body=agents)

    def get_agent_activity(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=_agent_activity_payload(tenant_id, agent))

    def list_events(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        return Response(body=_list_tenant_records(s.events, tenant_id=tenant_id, sort_key="start", reverse=False))

    def create_event(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        errors: list[str] = []
        for field_name in ("title", "start", "type", "agentId"):
            if not isinstance(body.get(field_name), str) or not str(body.get(field_name, "")).strip():
                errors.append(f"Field '{field_name}' is required")
        end = str(body.get("end", "") or "")
        try:
            _parse_iso_datetime(str(body.get("start", "")))
            if end:
                _parse_iso_datetime(end)
        except ValueError:
            errors.append("Fields 'start' and 'end' must be ISO-8601 timestamps")
        if errors:
            return Response(status_code=422, body={"errors": errors})
        start = str(body["start"])
        event_id = uuid.uuid4().hex[:12]
        event = {
            "id": event_id,
            "title": str(body["title"]).strip(),
            "description": str(body.get("description", "") or ""),
            "start": start,
            "end": end or _iso_plus_minutes(start, 60),
            "type": str(body["type"]).strip(),
            "agentId": str(body["agentId"]).strip(),
            "created_at": _utc_now_iso(),
            "tenant_id": tenant_id,
        }
        s.events[event_id] = event
        return Response(status_code=201, body=dict(event))

    def delete_event(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        event_id = request.path_params.get("event_id", "")
        event = s.events.get(event_id)
        if event is None:
            return Response(status_code=404, body={"error": f"Event not found: {event_id}"})
        if event.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        del s.events[event_id]
        return Response(status_code=204, body=None)

    def list_content(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        return Response(body=_list_tenant_records(s.content_items, tenant_id=tenant_id, sort_key="updated_at"))

    def create_content(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        errors: list[str] = []
        for field_name in ("title", "description", "type", "stage", "assignee", "assigneeType"):
            if not isinstance(body.get(field_name), str) or not str(body.get(field_name, "")).strip():
                errors.append(f"Field '{field_name}' is required")
        if body.get("stage") not in MISSION_CONTENT_STAGES:
            errors.append("Field 'stage' must be a supported content stage")
        if body.get("assigneeType") not in MISSION_ASSIGNEE_TYPES:
            errors.append("Field 'assigneeType' must be one of ['human', 'ai']")
        if errors:
            return Response(status_code=422, body={"errors": errors})
        now = _utc_now_iso()
        content_id = uuid.uuid4().hex[:12]
        item = {
            "id": content_id,
            "title": str(body["title"]).strip(),
            "description": str(body["description"]).strip(),
            "type": str(body["type"]).strip(),
            "stage": body["stage"],
            "assignee": str(body["assignee"]).strip(),
            "assigneeType": body["assigneeType"],
            "created_at": now,
            "updated_at": now,
            "tenant_id": tenant_id,
        }
        s.content_items[content_id] = item
        return Response(status_code=201, body=dict(item))

    def update_content(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        content_id = request.path_params.get("content_id", "")
        item = s.content_items.get(content_id)
        if item is None:
            return Response(status_code=404, body={"error": f"Content not found: {content_id}"})
        if item.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        errors: list[str] = []
        if "stage" in body and body["stage"] not in MISSION_CONTENT_STAGES:
            errors.append("Field 'stage' must be a supported content stage")
        if "assigneeType" in body and body["assigneeType"] not in MISSION_ASSIGNEE_TYPES:
            errors.append("Field 'assigneeType' must be one of ['human', 'ai']")
        for field_name in ("title", "description", "type", "assignee"):
            if field_name in body and not isinstance(body[field_name], str):
                errors.append(f"Field '{field_name}' must be of type str")
        if errors:
            return Response(status_code=422, body={"errors": errors})
        updated = dict(item)
        for field_name in ("title", "description", "type", "stage", "assignee", "assigneeType"):
            if field_name in body:
                updated[field_name] = body[field_name]
        updated["updated_at"] = _utc_now_iso()
        s.content_items[content_id] = updated
        return Response(body=dict(updated))

    def delete_content(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        content_id = request.path_params.get("content_id", "")
        item = s.content_items.get(content_id)
        if item is None:
            return Response(status_code=404, body={"error": f"Content not found: {content_id}"})
        if item.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        del s.content_items[content_id]
        return Response(status_code=204, body=None)

    def list_teams(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        teams = _ensure_default_teams(tenant_id)
        return Response(body=[{key: value for key, value in team.items() if key != "tenant_id"} for team in teams])

    def create_team(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        _ensure_default_teams(tenant_id)
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        name = str(body.get("name", "")).strip()
        if not name:
            return Response(status_code=422, body={"errors": ["Field 'name' is required"]})
        team_id = str(body.get("id", "")).strip() or _slugify_identifier(name, prefix="team")
        store_key = _team_store_key(tenant_id, team_id)
        if store_key in s.teams:
            return Response(status_code=409, body={"error": f"Team already exists: {team_id}"})
        payload = {
            "id": team_id,
            "name": name,
            "nameJa": str(body.get("nameJa", name)).strip() or name,
            "icon": str(body.get("icon", "Users")).strip() or "Users",
            "color": str(body.get("color", "text-slate-400")).strip() or "text-slate-400",
            "bg": str(body.get("bg", "bg-slate-600")).strip() or "bg-slate-600",
            "tenant_id": tenant_id,
            "created_at": _utc_now_iso(),
        }
        s.teams[store_key] = payload
        return Response(status_code=201, body={key: value for key, value in payload.items() if key != "tenant_id"})

    def update_team(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        team_id = request.path_params.get("id", "")
        team = _team_record(tenant_id, team_id)
        if team is None:
            return Response(status_code=404, body={"error": f"Team not found: {team_id}"})
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        updated = dict(team)
        for field_name in ("name", "nameJa", "icon", "color", "bg"):
            if field_name in body and isinstance(body[field_name], str) and str(body[field_name]).strip():
                updated[field_name] = str(body[field_name]).strip()
        s.teams[_team_store_key(tenant_id, team_id)] = updated
        return Response(body={key: value for key, value in updated.items() if key != "tenant_id"})

    def delete_team(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        team_id = request.path_params.get("id", "")
        store_key = _team_store_key(tenant_id, team_id)
        team = s.teams.get(store_key)
        if team is None:
            return Response(status_code=404, body={"error": f"Team not found: {team_id}"})
        del s.teams[store_key]
        remaining_team_id = _default_team_id(tenant_id)
        for agent_id, agent in list(s.agents.items()):
            if agent.get("tenant_id") == tenant_id and agent.get("team") == team_id:
                updated_agent = dict(agent)
                updated_agent["team"] = remaining_team_id
                s.agents[agent_id] = updated_agent
        return Response(status_code=204, body=None)

    def run_ads_audit(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        platforms = body.get("platforms", [])
        if not isinstance(platforms, list) or not platforms or any(platform not in ADS_PLATFORMS for platform in platforms):
            return Response(status_code=422, body={"errors": ["Field 'platforms' must contain supported ads platforms"]})
        industry_type = str(body.get("industry_type", "")).strip()
        if industry_type not in {template["id"] for template in ADS_INDUSTRY_TEMPLATES}:
            return Response(status_code=422, body={"errors": ["Field 'industry_type' must be a supported industry template"]})
        monthly_budget = body.get("monthly_budget")
        if monthly_budget is not None and not isinstance(monthly_budget, (int, float)):
            return Response(status_code=422, body={"errors": ["Field 'monthly_budget' must be numeric"]})
        account_data = body.get("account_data", {})
        if account_data is None:
            account_data = {}
        if not isinstance(account_data, dict):
            return Response(status_code=422, body={"errors": ["Field 'account_data' must be of type dict"]})
        report = _build_ads_report(
            tenant_id=tenant_id,
            platforms=[str(platform) for platform in platforms],
            industry_type=industry_type,
            monthly_budget=int(monthly_budget) if monthly_budget is not None else None,
            account_data={str(key): str(value) for key, value in account_data.items()},
        )
        s.ads_reports[report["id"]] = report
        run_id = uuid.uuid4().hex[:12]
        run = {
            "id": run_id,
            "tenant_id": tenant_id,
            "report_id": report["id"],
            "platforms": [str(platform) for platform in platforms],
            "industry_type": industry_type,
            "created_at_epoch": time.time(),
        }
        s.ads_audit_runs[run_id] = run
        return Response(status_code=201, body={"run_id": run_id})

    def get_ads_audit_status(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.ads_audit_runs.get(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Audit run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=_audit_run_payload(run))

    def list_ads_reports(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        reports = _list_tenant_records(s.ads_reports, tenant_id=tenant_id, sort_key="created_at")
        for report in reports:
            report.pop("tenant_id", None)
        return Response(body=reports)

    def get_ads_report(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        report_id = request.path_params.get("report_id", "")
        report = s.ads_reports.get(report_id)
        if report is None:
            return Response(status_code=404, body={"error": f"Ads report not found: {report_id}"})
        if report.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        payload = dict(report)
        payload.pop("tenant_id", None)
        return Response(body=payload)

    def generate_ads_plan(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        industry_type = str(body.get("industry_type", "")).strip()
        template = _industry_template(industry_type)
        monthly_budget = body.get("monthly_budget")
        if monthly_budget is not None and not isinstance(monthly_budget, (int, float)):
            return Response(status_code=422, body={"errors": ["Field 'monthly_budget' must be numeric"]})
        weights = _normalize_weight_map({platform: float(weight) for platform, weight in template["platforms"].items()})
        recommended_platforms = list(weights.keys())
        plan_budget = max(int(monthly_budget or template["min_monthly"]), int(template["min_monthly"]))
        campaign_architecture = []
        for platform, weight in weights.items():
            campaign_architecture.append(
                {
                    "platform": platform,
                    "campaign_name": f"{template['name']} {platform.title()} Core",
                    "objective": (
                        "Lead generation"
                        if template["primary_kpi"] in {"CAC", "CPL", "SQL"}
                        else "Revenue optimization"
                    ),
                    "budget_share": round(weight, 3),
                    "targeting_summary": (
                        f"Focus on the highest-intent segments for {template['name']} and keep remarketing isolated."
                    ),
                    "creative_requirements": [
                        "One proof-led control",
                        "Two hook variants",
                        "Dedicated landing page alignment",
                    ],
                }
            )
        return Response(body={
            "industry_type": template["id"],
            "recommended_platforms": recommended_platforms,
            "campaign_architecture": campaign_architecture,
            "monthly_budget_min": max(int(template["min_monthly"]), int(round(plan_budget * 0.6))),
            "primary_kpi": template["primary_kpi"],
            "time_to_profit": template["time_to_profit"],
        })

    def optimize_ads_budget(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        if not isinstance(body, dict):
            return Response(status_code=422, body={"errors": ["Request body must be a JSON object"]})
        current_spend = body.get("current_spend", {})
        if not isinstance(current_spend, dict):
            return Response(status_code=422, body={"errors": ["Field 'current_spend' must be of type dict"]})
        target_mer = body.get("target_mer", 3.0)
        if not isinstance(target_mer, (int, float)):
            return Response(status_code=422, body={"errors": ["Field 'target_mer' must be numeric"]})
        monthly_budget = body.get("monthly_budget")
        if monthly_budget is not None and not isinstance(monthly_budget, (int, float)):
            return Response(status_code=422, body={"errors": ["Field 'monthly_budget' must be numeric"]})
        budget_total = int(monthly_budget or sum(float(value) for value in current_spend.values()) or 10000)
        weights: dict[str, float] = {}
        for platform in ADS_PLATFORMS:
            benchmark = ADS_BENCHMARKS[platform]
            current = float(current_spend.get(platform, 0.0) or 0.0)
            current_share = current / budget_total if budget_total > 0 else 0.0
            weights[platform] = (
                benchmark["benchmark_mer"] * float(target_mer)
                + benchmark["avg_cvr"] * 0.8
                + current_share * 6
            )
        normalized = _normalize_weight_map(weights)
        allocation = _allocate_budget(normalized, budget_total)
        for platform in ADS_PLATFORMS:
            allocation.setdefault(platform, 0)
        return Response(body={
            "proven": int(round(budget_total * 0.7)),
            "growth": int(round(budget_total * 0.2)),
            "experiment": int(budget_total - int(round(budget_total * 0.7)) - int(round(budget_total * 0.2))),
            "platform_mix": allocation,
            "monthly_budget": budget_total,
            "mer_target": float(target_mer),
        })

    def get_ads_benchmarks(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        platform = request.path_params.get("platform", "")
        benchmark = ADS_BENCHMARKS.get(platform)
        if benchmark is None:
            return Response(status_code=404, body={"error": f"Benchmarks not found for platform: {platform}"})
        return Response(body={
            "platform": platform,
            **benchmark,
        })

    def list_ads_templates(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        return Response(body=[dict(template) for template in ADS_INDUSTRY_TEMPLATES])

    def create_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        _ensure_default_teams(tenant_id)
        body = request.body or {}
        errors = _validate_agent_payload(body, partial=False)
        if errors:
            return Response(status_code=422, body={"errors": errors})
        agent_id = uuid.uuid4().hex[:12]
        now = _utc_now_iso()
        agent = {
            "id": agent_id,
            "name": body["name"],
            "model": body.get("model", ""),
            "role": body.get("role", ""),
            "autonomy": _normalize_autonomy(body.get("autonomy", "A2")),
            "tools": body.get("tools", []),
            "skills": body.get("skills", []),
            "sandbox": body.get("sandbox", "gvisor"),
            "status": "ready",
            "tenant_id": tenant_id,
            "team": body.get("team"),
            "created_at": now,
            "updated_at": now,
        }
        s.agents[agent_id] = agent
        return Response(status_code=201, body=agent)

    def list_agents(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agents = [a for a in s.agents.values() if a.get("tenant_id") == tenant_id]
        return Response(body={"agents": agents, "count": len(agents)})

    def get_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=agent)

    def update_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        body = request.body or {}
        errors = _validate_agent_payload(body, partial=True)
        if errors:
            return Response(status_code=422, body={"errors": errors})

        updated = dict(agent)
        for field_name in ("name", "model", "role", "sandbox", "status", "team"):
            if field_name in body:
                updated[field_name] = body[field_name]
        if "autonomy" in body:
            updated["autonomy"] = _normalize_autonomy(body["autonomy"])
        if "tools" in body:
            updated["tools"] = list(body["tools"])
        if "skills" in body:
            updated["skills"] = list(body["skills"])
        updated["updated_at"] = _utc_now_iso()
        s.agents[agent_id] = updated
        return Response(body=updated)

    def get_agent_skills(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})

        skill_ids = list(agent.get("skills", []))
        return Response(body={
            "agent_id": agent_id,
            "agent_name": agent.get("name", ""),
            "skills": [_agent_skill_payload(skill_id) for skill_id in skill_ids],
        })

    def update_agent_skills(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        body = request.body or {}
        errors = _validate_agent_payload(body, partial=True)
        if errors:
            return Response(status_code=422, body={"errors": errors})
        if "skills" not in body:
            return Response(status_code=422, body={"errors": ["Field 'skills' is required"]})

        updated = dict(agent)
        updated["skills"] = list(body["skills"])
        s.agents[agent_id] = updated
        return Response(body=updated)

    def delete_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        del s.agents[agent_id]
        return Response(status_code=204, body=None)

    def list_skills(request: Request) -> Response:
        _tenant_id = _require_tenant_id(request)
        if _tenant_id is None:
            return _tenant_required_response()
        category = request.query_params.get("category")
        source = request.query_params.get("source")
        search = request.query_params.get("search")

        skills = list(s.skills.values())
        if category:
            skills = [item for item in skills if item.get("category") == category]
        if source:
            skills = [item for item in skills if item.get("source") == source]
        if search:
            lowered = str(search).lower()
            skills = [
                item for item in skills
                if lowered in str(item.get("name", "")).lower()
                or lowered in str(item.get("description", "")).lower()
            ]

        categories: dict[str, int] = {}
        sources: dict[str, int] = {}
        for skill in skills:
            categories[str(skill.get("category", "uncategorized"))] = (
                categories.get(str(skill.get("category", "uncategorized")), 0) + 1
            )
            sources[str(skill.get("source", "local"))] = (
                sources.get(str(skill.get("source", "local")), 0) + 1
            )
        return Response(body={
            "skills": skills,
            "total": len(skills),
            "categories": categories,
            "sources": sources,
        })

    def list_skill_categories(request: Request) -> Response:
        response = list_skills(request)
        if response.status_code != 200:
            return response
        return Response(body=response.body["categories"])

    def scan_skills(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        return Response(body={"total": len(s.skills), "new": 0, "removed": 0})

    def get_skill(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        skill_id = request.path_params.get("id", "")
        skill = s.skills.get(skill_id)
        if skill is None:
            return Response(status_code=404, body={"error": f"Skill not found: {skill_id}"})
        return Response(body=skill)

    def _skill_execution_preview_payload(
        skill: dict[str, Any],
        *,
        input_text: str,
        context: dict[str, Any],
        note: str,
    ) -> dict[str, Any]:
        lines = [f"# Skill: {skill.get('name', skill.get('id', 'unknown-skill'))}"]
        description = str(skill.get("description", "")).strip()
        if description:
            lines.extend(["", description])
        instructions = str(skill.get("content", skill.get("content_preview", ""))).strip()
        if instructions:
            lines.extend(["", "Instructions:", instructions])
        if input_text:
            lines.extend(["", "Input:", input_text])
        if context:
            lines.extend([
                "",
                "Context:",
                json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True),
            ])
        lines.extend(["", f"Note: {note}"])
        result = "\n".join(lines).strip()
        serialized_context = json.dumps(context, ensure_ascii=False, sort_keys=True) if context else ""
        tokens_in = len(f"{input_text} {serialized_context}".strip().split())
        tokens_out = len(result.split())
        return {
            "skill_id": str(skill.get("id", "")),
            "result": result,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": "builtin-skill-preview",
            "provider": "local",
        }

    def execute_skill(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        skill_id = request.path_params.get("id", "")
        skill = s.skills.get(skill_id)
        if skill is None:
            return Response(status_code=404, body={"error": f"Skill not found: {skill_id}"})

        body = request.body or {}
        valid, errors = validate(body, SKILL_EXECUTE_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        input_text = str(body.get("input", ""))
        context = dict(body.get("context", {}))
        requested_provider = str(body.get("provider", "") or "")
        requested_model = str(body.get("model", "") or "")
        available_providers = (
            provider_registry.provider_names() if provider_registry is not None else ()
        )
        if not available_providers:
            return Response(body=_skill_execution_preview_payload(
                skill,
                input_text=input_text,
                context=context,
                note="No provider runtime is configured, so a deterministic local preview was returned instead of a live execution.",
            ))

        provider_name = requested_provider
        model_name = requested_model
        skill_model = str(skill.get("model", "") or "")
        if not provider_name and "/" in skill_model:
            provider_name, inferred_model = skill_model.split("/", 1)
            if not model_name:
                model_name = inferred_model
        elif not provider_name and skill_model and len(available_providers) == 1:
            provider_name = available_providers[0]
            if not model_name:
                model_name = skill_model

        if not provider_name:
            provider_name = available_providers[0]
        if provider_name not in available_providers:
            logger.warning(
                "Requested skill execution provider %s is unavailable; falling back to %s",
                provider_name,
                available_providers[0],
            )
            provider_name = available_providers[0]

        if not model_name:
            catalog = _collect_model_catalog(tenant_id)
            provider_info = catalog.get(provider_name, {})
            model_name = str(provider_info.get("default_model", "") or "")

        if not model_name:
            return Response(body=_skill_execution_preview_payload(
                skill,
                input_text=input_text,
                context=context,
                note=f"No default model is configured for provider '{provider_name}', so a deterministic local preview was returned instead of a live execution.",
            ))

        system_sections = [
            f"You are executing the '{skill.get('name', skill_id)}' skill.",
        ]
        description = str(skill.get("description", "")).strip()
        if description:
            system_sections.append(f"Skill description:\n{description}")
        instructions = str(skill.get("content", skill.get("content_preview", ""))).strip()
        if instructions:
            system_sections.append(f"Skill instructions:\n{instructions}")

        messages = [
            Message(role="system", content="\n\n".join(system_sections)),
        ]
        if context:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "Execution context:\n"
                        f"{json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)}"
                    ),
                )
            )
        messages.append(
            Message(
                role="user",
                content=input_text or "Execute the skill with the available instructions.",
            )
        )

        try:
            provider = provider_registry.resolve(provider_name, model_name)
            provider_response = asyncio.run(provider.chat(messages, model=model_name))
        except Exception:  # pragma: no cover - exercised via route-level behavior
            logger.exception(
                "Skill execution failed for %s via %s/%s",
                skill_id,
                provider_name,
                model_name,
            )
            return Response(body=_skill_execution_preview_payload(
                skill,
                input_text=input_text,
                context=context,
                note=f"Provider execution failed for {provider_name}/{model_name}, so a deterministic local preview was returned instead.",
            ))

        usage = provider_response.usage or TokenUsage()
        return Response(body={
            "skill_id": skill_id,
            "result": provider_response.content,
            "tokens_in": int(usage.input_tokens),
            "tokens_out": int(usage.output_tokens),
            "model": provider_response.model or model_name,
            "provider": provider_name,
        })

    def list_models(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        catalog = _collect_model_catalog(tenant_id)
        return Response(body={
            "providers": catalog,
            "fallback_chain": list(catalog.keys()),
            "policies": {
                provider_name: {
                    "policy": info.get("policy", "balanced"),
                    "pin": info.get("pin"),
                }
                for provider_name, info in catalog.items()
            },
        })

    def refresh_models(request: Request) -> Response:
        return list_models(request)

    def update_model_policy(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        provider_name = body.get("provider")
        policy = body.get("policy")
        if not isinstance(provider_name, str) or not provider_name:
            return Response(status_code=422, body={"errors": ["Field 'provider' is required"]})
        if not isinstance(policy, str) or not policy:
            return Response(status_code=422, body={"errors": ["Field 'policy' is required"]})
        s.model_policies[_model_policy_store_key(tenant_id, provider_name)] = {
            "policy": policy,
            "pin": body.get("pin") if isinstance(body.get("pin"), str) else None,
            "tenant_id": tenant_id,
            "provider": provider_name,
        }
        return Response(body={"ok": True})

    def health_models(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        catalog = _collect_model_catalog(tenant_id)
        return Response(body={
            provider_name: {
                "status": "ok" if info.get("status") == "available" else "error",
                "latency_ms": 0,
                "model": info.get("default_model", ""),
            }
            for provider_name, info in catalog.items()
        })

    def get_features(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        manifest = build_feature_manifest()
        manifest["tenant_id"] = tenant_id
        return Response(body=manifest)

    def get_contract(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        manifest = public_contract.manifest()
        manifest["tenant_id"] = tenant_id
        return Response(body=manifest)

    def create_workflow(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        valid, errors = validate(body, WORKFLOW_DEFINITION_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        workflow_id = str(body["id"])
        if s.get_workflow_project(workflow_id, tenant_id=tenant_id) is not None:
            return Response(
                status_code=409,
                body={"error": f"Workflow already exists: {workflow_id}"},
            )
        from pylon.config.pipeline import build_validation_report, validate_project_definition

        validation_result = validate_project_definition(body["project"])
        validation_report = build_validation_report(validation_result)
        if not validation_result.valid:
            return Response(
                status_code=422,
                body={
                    "error": "Workflow project validation failed",
                    "validation": validation_report,
                    "issues": [issue.to_dict() for issue in validation_result.issues],
                    "stages_passed": validation_result.stages_passed,
                },
            )
        try:
            project = s.register_workflow_project(
                workflow_id,
                body["project"],
                tenant_id=tenant_id,
            )
        except Exception as exc:
            return Response(status_code=422, body={"error": str(exc)})

        payload = {
            **_workflow_summary(workflow_id, project, tenant_id=tenant_id),
            "project": project.model_dump(mode="json"),
            "validation": validation_report,
        }
        if validation_result.warnings:
            payload["validation_warnings"] = [
                issue.to_dict() for issue in validation_result.warnings
            ]
        return Response(status_code=201, body=payload)

    def list_workflows(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflows = [
            _workflow_summary(workflow_id, project, tenant_id=tenant_id)
            for workflow_id, project in s.list_workflow_projects(tenant_id=tenant_id)
        ]
        return Response(body={"workflows": workflows, "count": len(workflows)})

    def get_workflow(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        project = s.get_workflow_project(workflow_id, tenant_id=tenant_id)
        assert project is not None
        return Response(
            body={
                **_workflow_summary(workflow_id, project, tenant_id=tenant_id),
                "project": project.model_dump(mode="json"),
            }
        )

    def get_workflow_plan(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        return Response(
            body=workflow_service.get_workflow_plan(
                workflow_id,
                tenant_id=tenant_id,
            )
        )

    def list_workflow_runs(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        runs = workflow_service.list_run_payloads(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
        )
        return Response(body={"runs": runs, "count": len(runs)})

    def delete_workflow(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        s.remove_workflow_project(workflow_id, tenant_id=tenant_id)
        return Response(status_code=204, body=None)

    def start_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        body = request.body or {}
        raw_input = body.get("input")
        valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        try:
            stored_run = workflow_service.start_run(
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                input_data=raw_input,
                parameters=body.get("parameters", {}),
                idempotency_key=body.get("idempotency_key"),
                execution_mode=body.get("execution_mode", "inline"),
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=400, body={"error": str(exc)})
        run_id = stored_run["id"]
        location = v1(f"/runs/{run_id}")
        return Response(
            status_code=202,
            headers={"content-type": "application/json", "location": location},
            body=workflow_service.get_run_payload(run_id),
        )

    def get_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record_for_workflow(workflow_id, run_id, tenant_id=tenant_id)
        if run is None:
            existing_run = s.get_run_record(run_id)
            if (
                existing_run is not None
                and str(existing_run.get("workflow_id", existing_run.get("workflow", "")))
                == workflow_id
                and existing_run.get("tenant_id") != tenant_id
            ):
                return Response(status_code=403, body={"error": "Forbidden"})
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        return Response(body=workflow_service.get_run_payload(run_id))

    def get_workflow_run_by_id(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=workflow_service.get_run_payload(run_id))

    def list_runs(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        runs = workflow_service.list_run_payloads(tenant_id=tenant_id)
        return Response(body={"runs": runs, "count": len(runs)})

    def list_approvals(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approvals = workflow_service.list_approval_payloads(tenant_id=tenant_id)
        return Response(body={"approvals": approvals, "count": len(approvals)})

    def list_run_approvals(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        approvals = workflow_service.list_approval_payloads(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        return Response(body={"approvals": approvals, "count": len(approvals)})

    def list_checkpoints(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        checkpoints = workflow_service.list_checkpoint_payloads(tenant_id=tenant_id)
        return Response(body={"checkpoints": checkpoints, "count": len(checkpoints)})

    def list_run_checkpoints(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        checkpoints = workflow_service.list_checkpoint_payloads(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        return Response(body={"checkpoints": checkpoints, "count": len(checkpoints)})

    def resume_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        body = request.body or {}
        valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        raw_input = body.get("input", run.get("input"))
        try:
            stored_run = workflow_service.resume_run(
                run_id,
                tenant_id=tenant_id,
                input_data=raw_input,
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=409, body={"error": str(exc)})
        return Response(body=workflow_service.get_run_payload(str(stored_run["id"])))

    def approve_request(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approval_id = request.path_params.get("approval_id", "")
        approval = s.get_approval_record(approval_id)
        if approval is None:
            return Response(
                status_code=404,
                body={"error": f"Approval request not found: {approval_id}"},
            )
        run_id = str(approval.get("run_id", ""))
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        if approval.get("status") != "pending":
            return Response(
                status_code=409,
                body={"error": f"Approval request already decided: {approval_id}"},
            )
        body = request.body or {}
        valid, errors = validate(body, APPROVAL_DECISION_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        reason = body.get("reason")

        try:
            stored_run = workflow_service.approve_request(
                approval_id,
                tenant_id=tenant_id,
                actor="api",
                reason=reason,
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=409, body={"error": str(exc)})
        except Exception:
            logger.exception("Failed to resume run %s after approval", run_id)
            return Response(
                status_code=500,
                body={"error": f"Failed to resume run after approval: {run_id}"},
            )
        return Response(body=workflow_service.get_run_payload(str(stored_run["id"])))

    def reject_request(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approval_id = request.path_params.get("approval_id", "")
        approval = s.get_approval_record(approval_id)
        if approval is None:
            return Response(
                status_code=404,
                body={"error": f"Approval request not found: {approval_id}"},
            )
        run_id = str(approval.get("run_id", ""))
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        if approval.get("status") != "pending":
            return Response(
                status_code=409,
                body={"error": f"Approval request already decided: {approval_id}"},
            )
        body = request.body or {}
        valid, errors = validate(body, APPROVAL_DECISION_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        reason = body.get("reason")

        try:
            updated = workflow_service.reject_request(
                approval_id,
                tenant_id=tenant_id,
                actor="api",
                reason=reason,
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=409, body={"error": str(exc)})
        return Response(body=workflow_service.get_run_payload(str(updated["id"])))

    def replay_checkpoint(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        checkpoint_id = request.path_params.get("checkpoint_id", "")
        checkpoint = s.get_checkpoint_record(checkpoint_id)
        if checkpoint is None:
            return Response(
                status_code=404,
                body={"error": f"Checkpoint not found: {checkpoint_id}"},
            )
        source_run_id = str(checkpoint.get("run_id", ""))
        source_run = s.get_run_record(source_run_id)
        if source_run is None:
            return Response(
                status_code=404,
                body={"error": f"Run not found: {source_run_id}"},
            )
        if source_run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        try:
            payload = workflow_service.replay_checkpoint(checkpoint_id)
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        return Response(body=payload)

    def activate_kill_switch(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        valid, errors = validate(body, KILL_SWITCH_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        scope: str = body["scope"]

        # Authorization: global scope requires admin tenant
        if scope == "global" and tenant_id != "admin":
            return Response(
                status_code=403,
                body={"error": "Only admin tenant can activate global kill switch"},
            )

        # Authorization: tenant-scoped switches only for own tenant
        if scope.startswith("tenant:"):
            scope_tenant = scope[len("tenant:"):]
            if scope_tenant != tenant_id:
                return Response(
                    status_code=403,
                    body={"error": "Cannot activate kill switch for another tenant"},
                )

        event = {
            "scope": scope,
            "reason": body["reason"],
            "issued_by": body["issued_by"],
            "parent_scope": body.get("parent_scope", ""),
            "activated_at": time.time(),
            "tenant_id": tenant_id,
        }
        s.kill_switches[_kill_switch_store_key(tenant_id, scope)] = event
        return Response(status_code=201, body=event)

    def costs_summary(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        period = request.query_params.get("period", "mtd")
        runs = [
            r for r in s.list_all_run_records()
            if r.get("tenant_id") == tenant_id and r.get("status") == "completed"
        ]
        total_usd = 0.0
        by_provider: dict[str, float] = {}
        by_model: dict[str, float] = {}
        total_tokens_in = 0
        total_tokens_out = 0
        for run in runs:
            state = run.get("state") or {}
            cost = state.get("estimated_cost_usd", 0.0) or 0.0
            total_usd += cost
            # Aggregate by provider/model from project agents
            wf_id = str(run.get("workflow_id", run.get("workflow", "")))
            project = s.get_workflow_project(wf_id, tenant_id=tenant_id)
            if project:
                for agent in project.agents.values():
                    model_str = agent.model or "unknown"
                    provider = model_str.split("/")[0] if "/" in model_str else "unknown"
                    by_provider[provider] = by_provider.get(provider, 0.0) + cost / max(len(project.agents), 1)
                    by_model[model_str] = by_model.get(model_str, 0.0) + cost / max(len(project.agents), 1)
            total_tokens_in += int(state.get("plan_tokens_in", 0) or 0) + int(state.get("implement_tokens_in", 0) or 0)
            total_tokens_out += int(state.get("plan_tokens_out", 0) or 0) + int(state.get("implement_tokens_out", 0) or 0)
        policy_budget = 5.0
        if runs:
            wf_id = str(runs[0].get("workflow_id", runs[0].get("workflow", "")))
            project = s.get_workflow_project(wf_id, tenant_id=tenant_id)
            if project and project.policy and project.policy.max_cost_usd:
                policy_budget = project.policy.max_cost_usd
        return Response(body={
            "period": period,
            "total_usd": round(total_usd, 6),
            "budget_usd": policy_budget,
            "run_count": len(runs),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "by_provider": {k: round(v, 6) for k, v in by_provider.items()},
            "by_model": {k: round(v, 6) for k, v in by_model.items()},
        })

    server.add_route("GET", "/health", health)
    if readiness_route_enabled:
        server.add_route("GET", "/ready", ready)
    if metrics_route_enabled:
        server.add_route(
            "GET",
            "/metrics",
            _scoped(metrics, all_of=("observability:read",)),
        )
    _public("POST", v1("/agents"), create_agent, aliases=("/agents",), all_of=("agents:write",))
    _public("GET", v1("/agents"), list_agents, aliases=("/agents",), all_of=("agents:read",))
    _public("GET", v1("/agents/activity"), list_agents_activity, all_of=("agents:read",))
    _public("GET", v1("/agents/{id}"), get_agent, aliases=("/agents/{id}",), all_of=("agents:read",))
    _public("PATCH", v1("/agents/{id}"), update_agent, aliases=("/agents/{id}",), all_of=("agents:write",))
    _public("GET", v1("/agents/{id}/activity"), get_agent_activity, all_of=("agents:read",))
    _public("GET", v1("/agents/{id}/skills"), get_agent_skills, all_of=("agents:read",))
    _public("PATCH", v1("/agents/{id}/skills"), update_agent_skills, all_of=("agents:write",))
    _public("DELETE", v1("/agents/{id}"), delete_agent, aliases=("/agents/{id}",), all_of=("agents:write",))

    _public("POST", v1("/workflows"), create_workflow, aliases=("/workflows",), all_of=("workflows:write",))
    _public("GET", v1("/workflows"), list_workflows, aliases=("/workflows",), all_of=("workflows:read",))
    _public("GET", v1("/workflows/{id}"), get_workflow, aliases=("/workflows/{id}",), all_of=("workflows:read",))
    _public("GET", v1("/workflows/{id}/plan"), get_workflow_plan, aliases=("/workflows/{id}/plan",), all_of=("workflows:read",))
    _public("DELETE", v1("/workflows/{id}"), delete_workflow, aliases=("/workflows/{id}",), all_of=("workflows:write",))
    _public("GET", v1("/workflows/{id}/runs"), list_workflow_runs, aliases=("/workflows/{id}/runs",), all_of=("runs:read",))
    _public("POST", v1("/workflows/{id}/runs"), start_workflow_run, aliases=("/workflows/{id}/run",), all_of=("runs:write",))
    _public("GET", v1("/workflows/{id}/runs/{run_id}"), get_workflow_run, aliases=("/workflows/{id}/runs/{run_id}",), all_of=("runs:read",))
    _public("GET", v1("/runs"), list_runs, aliases=("/api/v1/workflow-runs",), all_of=("runs:read",))
    _public("GET", v1("/runs/{run_id}"), get_workflow_run_by_id, aliases=("/api/v1/workflow-runs/{run_id}",), all_of=("runs:read",))
    _public("GET", v1("/runs/{run_id}/approvals"), list_run_approvals, aliases=("/api/v1/workflow-runs/{run_id}/approvals",), all_of=("approvals:read",))
    _public("GET", v1("/runs/{run_id}/checkpoints"), list_run_checkpoints, aliases=("/api/v1/workflow-runs/{run_id}/checkpoints",), all_of=("checkpoints:read",))
    _public("POST", v1("/runs/{run_id}/resume"), resume_workflow_run, aliases=("/api/v1/workflow-runs/{run_id}/resume",), all_of=("runs:write",))
    _public("GET", v1("/approvals"), list_approvals, all_of=("approvals:read",))
    _public("POST", v1("/approvals/{approval_id}/approve"), approve_request, all_of=("approvals:write",))
    _public("POST", v1("/approvals/{approval_id}/reject"), reject_request, all_of=("approvals:write",))
    _public("GET", v1("/checkpoints"), list_checkpoints, all_of=("checkpoints:read",))
    _public("GET", v1("/checkpoints/{checkpoint_id}/replay"), replay_checkpoint, all_of=("checkpoints:read",))
    _public("GET", v1("/skills"), list_skills, all_of=("agents:read",))
    _public("GET", v1("/skills/categories"), list_skill_categories, all_of=("agents:read",))
    _public("POST", v1("/skills/scan"), scan_skills, all_of=("agents:read",))
    _public("GET", v1("/skills/{id}"), get_skill, all_of=("agents:read",))
    _public("POST", v1("/skills/{id}/execute"), execute_skill, all_of=("agents:write",))
    _public("GET", v1("/models"), list_models, all_of=("agents:read",))
    _public("POST", v1("/models/refresh"), refresh_models, all_of=("agents:read",))
    _public("POST", v1("/models/policy"), update_model_policy, all_of=("agents:write",))
    _public("GET", v1("/models/health"), health_models, all_of=("agents:read",))
    _public("GET", v1("/lifecycle/projects"), list_lifecycle_projects, all_of=("runs:read",))
    _public("GET", v1("/lifecycle/projects/{project_id}"), get_lifecycle_project, all_of=("runs:read",))
    _public("PATCH", v1("/lifecycle/projects/{project_id}"), update_lifecycle_project, all_of=("runs:write",))
    _public("GET", v1("/lifecycle/projects/{project_id}/blueprint"), get_lifecycle_blueprints, all_of=("runs:read",))
    _public("POST", v1("/lifecycle/projects/{project_id}/phases/{phase}/prepare"), prepare_lifecycle_phase, all_of=("runs:write",))
    _public("POST", v1("/lifecycle/projects/{project_id}/phases/{phase}/sync"), sync_lifecycle_phase_run, all_of=("runs:write",))
    _public("POST", v1("/lifecycle/projects/{project_id}/advance"), advance_lifecycle_project, all_of=("runs:write",))
    _public("POST", v1("/lifecycle/projects/{project_id}/approval/comments"), add_lifecycle_approval_comment, all_of=("runs:write",))
    _public("POST", v1("/lifecycle/projects/{project_id}/approval/decision"), decide_lifecycle_approval, all_of=("runs:write",))
    _public("POST", v1("/lifecycle/projects/{project_id}/deploy/checks"), run_lifecycle_deploy_checks, all_of=("runs:write",))
    _public("POST", v1("/lifecycle/projects/{project_id}/releases"), create_lifecycle_release, all_of=("runs:write",))
    _public("GET", v1("/lifecycle/projects/{project_id}/feedback"), list_lifecycle_feedback, all_of=("runs:read",))
    _public("POST", v1("/lifecycle/projects/{project_id}/feedback"), create_lifecycle_feedback, all_of=("runs:write",))
    _public("POST", v1("/lifecycle/projects/{project_id}/feedback/{feedback_id}/vote"), vote_lifecycle_feedback, all_of=("runs:write",))
    _public("GET", v1("/lifecycle/projects/{project_id}/recommendations"), get_lifecycle_recommendations, all_of=("runs:read",))
    _public("GET", v1("/tasks"), list_tasks, all_of=("runs:read",))
    _public("POST", v1("/tasks"), create_task, all_of=("runs:write",))
    _public("GET", v1("/tasks/{task_id}"), get_task, all_of=("runs:read",))
    _public("PATCH", v1("/tasks/{task_id}"), update_task, all_of=("runs:write",))
    _public("DELETE", v1("/tasks/{task_id}"), delete_task, all_of=("runs:write",))
    _public("GET", v1("/memories"), list_memories, all_of=("runs:read",))
    _public("POST", v1("/memories"), create_memory, all_of=("runs:write",))
    _public("DELETE", v1("/memories/{entry_id}"), delete_memory, all_of=("runs:write",))
    _public("GET", v1("/events"), list_events, all_of=("runs:read",))
    _public("POST", v1("/events"), create_event, all_of=("runs:write",))
    _public("DELETE", v1("/events/{event_id}"), delete_event, all_of=("runs:write",))
    _public("GET", v1("/content"), list_content, all_of=("runs:read",))
    _public("POST", v1("/content"), create_content, all_of=("runs:write",))
    _public("PATCH", v1("/content/{content_id}"), update_content, all_of=("runs:write",))
    _public("DELETE", v1("/content/{content_id}"), delete_content, all_of=("runs:write",))
    _public("GET", v1("/teams"), list_teams, all_of=("agents:read",))
    _public("POST", v1("/teams"), create_team, all_of=("agents:write",))
    _public("PATCH", v1("/teams/{id}"), update_team, all_of=("agents:write",))
    _public("DELETE", v1("/teams/{id}"), delete_team, all_of=("agents:write",))
    _public("POST", v1("/ads/audit"), run_ads_audit, all_of=("runs:write",))
    _public("GET", v1("/ads/audit/{run_id}"), get_ads_audit_status, all_of=("runs:read",))
    _public("GET", v1("/ads/reports"), list_ads_reports, all_of=("runs:read",))
    _public("GET", v1("/ads/reports/{report_id}"), get_ads_report, all_of=("runs:read",))
    _public("POST", v1("/ads/plan"), generate_ads_plan, all_of=("runs:write",))
    _public("POST", v1("/ads/budget/optimize"), optimize_ads_budget, all_of=("runs:write",))
    _public("GET", v1("/ads/benchmarks/{platform}"), get_ads_benchmarks, all_of=("runs:read",))
    _public("GET", v1("/ads/templates"), list_ads_templates, all_of=("runs:read",))
    _public("GET", v1("/contract"), get_contract, all_of=("agents:read",))
    _public("GET", v1("/features"), get_features, all_of=("agents:read",))
    _public("POST", "/kill-switch", activate_kill_switch, all_of=("kill-switch:write",))
    _public("GET", v1("/costs/summary"), costs_summary, aliases=("/api/v1/costs/realtime",), all_of=("runs:read",))

    return s
