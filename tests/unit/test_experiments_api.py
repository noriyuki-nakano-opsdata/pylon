"""Experiment campaign API integration tests."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pylon.api.middleware import TenantMiddleware
from pylon.api.routes import register_routes
from pylon.api.server import APIServer, StreamingBody
from pylon.experiments import ExperimentCampaignManager
from pylon.experiments.service import PlannerSpec, _build_codex_prompt


def _make_server() -> tuple[APIServer, object]:
    server = APIServer()
    server.add_middleware(TenantMiddleware(require_tenant=True))
    store = register_routes(server)
    return server, store


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "experiment-repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main")
    _run(repo, "git", "config", "user.name", "Test User")
    _run(repo, "git", "config", "user.email", "test@example.com")
    (repo / "score.txt").write_text("10\n", encoding="utf-8")
    (repo / "README.md").write_text("# benchmark repo\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-m", "initial state")
    return repo


def _run(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _wait_for_campaign(server: APIServer, campaign_id: str, *, tenant_id: str, timeout: float = 10.0) -> dict[str, object]:
    deadline = time.time() + timeout
    last_body: dict[str, object] | None = None
    while time.time() < deadline:
        response = server.handle_request(
            "GET",
            f"/api/v1/experiments/{campaign_id}",
            headers={"X-Tenant-ID": tenant_id},
        )
        assert response.status_code == 200
        assert isinstance(response.body, dict)
        last_body = response.body
        campaign = response.body["campaign"]
        if campaign["status"] in {"completed", "failed", "cancelled", "paused"}:
            return response.body
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for campaign {campaign_id}: {last_body}")


def test_experiment_campaign_runs_iterations_and_promotes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    server, _ = _make_server()
    tenant_id = "tenant-a"

    create = server.handle_request(
        "POST",
        "/api/v1/experiments",
        headers={"X-Tenant-ID": tenant_id},
        body={
            "name": "latency-sweep",
            "objective": "Reduce benchmark latency",
            "project_slug": "pylon",
            "repo_path": str(repo),
            "benchmark_command": "printf 'METRIC latency='; tr -d '\\n' < score.txt; printf '\\n'",
            "planner_command": (
                "if [ \"$PYLON_EXPERIMENT_SEQUENCE\" = \"1\" ]; then "
                "printf '9\\n' > score.txt; "
                "elif [ \"$PYLON_EXPERIMENT_SEQUENCE\" = \"2\" ]; then "
                "printf '7\\n' > score.txt; "
                "else printf '8\\n' > score.txt; fi"
            ),
            "checks_command": "test -f README.md",
            "metric_name": "latency",
            "metric_direction": "minimize",
            "metric_unit": "ms",
            "max_iterations": 2,
            "promotion_branch": "pylon/experiments/promoted/test-campaign",
        },
    )
    assert create.status_code == 201
    campaign_id = create.body["campaign"]["id"]
    assert create.body["campaign"]["status"] == "draft"

    features = server.handle_request("GET", "/api/v1/features", headers={"X-Tenant-ID": tenant_id})
    assert features.status_code == 200
    assert features.body["surfaces"]["project"]["experiments"] is True

    start = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/start",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert start.status_code == 200
    assert start.body["campaign"]["status"] == "running"

    detail = _wait_for_campaign(server, campaign_id, tenant_id=tenant_id)
    campaign = detail["campaign"]
    assert campaign["status"] == "completed"
    assert campaign["baseline"]["value"] == 10.0
    assert campaign["best"]["value"] == 7.0
    assert campaign["progress"]["completed_iterations"] == 2
    assert len(detail["iterations"]) == 3
    assert detail["iterations"][0]["outcome"] == "baseline"
    assert detail["iterations"][-1]["outcome"] == "kept"

    stable_ref = _run(repo, "git", "rev-parse", "pylon/experiments/" + campaign_id + "/best")
    assert stable_ref == campaign["best"]["ref"]

    events = server.handle_request(
        "GET",
        f"/api/v1/experiments/{campaign_id}/events?once=1",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert events.status_code == 200
    assert isinstance(events.body, StreamingBody)
    chunks = "".join(str(chunk) for chunk in events.body.chunks)
    assert "event: snapshot" in chunks
    assert "event: terminal" in chunks

    promote = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/promote",
        headers={"X-Tenant-ID": tenant_id},
        body={"branch": "pylon/experiments/promoted/test-campaign"},
    )
    assert promote.status_code == 202
    assert promote.body["campaign"]["promotion"]["status"] == "approval_pending"
    approval_id = promote.body["campaign"]["approval"]["request_id"]
    approved = server.handle_request(
        "POST",
        f"/api/v1/approvals/{approval_id}/approve",
        headers={"X-Tenant-ID": tenant_id},
        body={"reason": "ship"},
    )
    assert approved.status_code == 200
    assert approved.body["campaign"]["promotion"]["status"] == "promoted"
    promoted_ref = _run(repo, "git", "rev-parse", "pylon/experiments/promoted/test-campaign")
    assert promoted_ref == campaign["best"]["ref"]

    contract = server.handle_request("GET", "/api/v1/contract", headers={"X-Tenant-ID": tenant_id})
    assert contract.status_code == 200
    route_paths = {
        (route["method"], route["path"])
        for route in contract.body["routes"]
    }
    assert ("POST", "/api/v1/experiments") in route_paths
    assert ("GET", "/api/v1/experiments/{campaign_id}/events") in route_paths

    server.shutdown()


def test_experiment_campaign_pause_and_resume(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    server, _ = _make_server()
    tenant_id = "tenant-b"

    create = server.handle_request(
        "POST",
        "/api/v1/experiments",
        headers={"X-Tenant-ID": tenant_id},
        body={
            "objective": "Pause and resume coverage",
            "repo_path": str(repo),
            "benchmark_command": "printf 'METRIC latency='; tr -d '\\n' < score.txt; printf '\\n'",
            "planner_command": (
                "sleep 0.2; "
                "if [ \"$PYLON_EXPERIMENT_SEQUENCE\" = \"1\" ]; then "
                "printf '9\\n' > score.txt; "
                "else printf '8\\n' > score.txt; fi"
            ),
            "metric_name": "latency",
            "metric_direction": "minimize",
            "max_iterations": 2,
        },
    )
    campaign_id = create.body["campaign"]["id"]

    server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/start",
        headers={"X-Tenant-ID": tenant_id},
    )
    pause = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/pause",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert pause.status_code == 200

    paused = _wait_for_campaign(server, campaign_id, tenant_id=tenant_id)
    assert paused["campaign"]["status"] == "paused"

    resume = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/resume",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resume.status_code == 200

    completed = _wait_for_campaign(server, campaign_id, tenant_id=tenant_id, timeout=30.0)
    assert completed["campaign"]["status"] == "completed"
    assert completed["campaign"]["best"]["value"] in {8.0, 9.0}

    server.shutdown()


def test_experiment_campaign_start_requires_approval(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    server, _ = _make_server()
    tenant_id = "tenant-approval-start"

    create = server.handle_request(
        "POST",
        "/api/v1/experiments",
        headers={"X-Tenant-ID": tenant_id},
        body={
            "objective": "Require approval for risky sandbox",
            "repo_path": str(repo),
            "benchmark_command": "printf 'METRIC latency='; tr -d '\\n' < score.txt; printf '\\n'",
            "planner_command": "printf '9\\n' > score.txt",
            "metric_name": "latency",
            "metric_direction": "minimize",
            "max_iterations": 1,
            "sandbox": {
                "tier": "none",
                "allow_internet": False,
            },
        },
    )
    assert create.status_code == 201
    campaign_id = create.body["campaign"]["id"]

    start = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/start",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert start.status_code == 202
    assert start.body["campaign"]["status"] == "waiting_approval"
    assert start.body["campaign"]["approval"]["status"] == "pending"

    approvals = server.handle_request(
        "GET",
        "/api/v1/approvals",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert approvals.status_code == 200
    assert approvals.body["count"] == 1
    approval_id = approvals.body["approvals"][0]["id"]
    assert approvals.body["approvals"][0]["resource_type"] == "experiment_campaign"

    approved = server.handle_request(
        "POST",
        f"/api/v1/approvals/{approval_id}/approve",
        headers={"X-Tenant-ID": tenant_id},
        body={"reason": "host sandbox approved"},
    )
    assert approved.status_code == 200

    detail = _wait_for_campaign(server, campaign_id, tenant_id=tenant_id)
    assert detail["campaign"]["status"] == "completed"
    assert detail["campaign"]["approval"]["status"] == "approved"
    assert detail["campaign"]["best"]["value"] == 9.0

    server.shutdown()


def test_experiment_campaign_promote_requires_approval_and_can_be_rejected(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    server, _ = _make_server()
    tenant_id = "tenant-approval-promote"

    create = server.handle_request(
        "POST",
        "/api/v1/experiments",
        headers={"X-Tenant-ID": tenant_id},
        body={
            "objective": "Promotion approval coverage",
            "repo_path": str(repo),
            "benchmark_command": "printf 'METRIC latency='; tr -d '\\n' < score.txt; printf '\\n'",
            "planner_command": "printf '8\\n' > score.txt",
            "metric_name": "latency",
            "metric_direction": "minimize",
            "max_iterations": 1,
            "promotion_branch": "pylon/experiments/promoted/approval-branch",
        },
    )
    campaign_id = create.body["campaign"]["id"]
    server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/start",
        headers={"X-Tenant-ID": tenant_id},
    )
    detail = _wait_for_campaign(server, campaign_id, tenant_id=tenant_id)
    assert detail["campaign"]["status"] == "completed"

    promote = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/promote",
        headers={"X-Tenant-ID": tenant_id},
        body={"branch": "pylon/experiments/promoted/approval-branch"},
    )
    assert promote.status_code == 202
    assert promote.body["campaign"]["promotion"]["status"] == "approval_pending"
    approval_id = promote.body["campaign"]["approval"]["request_id"]

    rejected = server.handle_request(
        "POST",
        f"/api/v1/approvals/{approval_id}/reject",
        headers={"X-Tenant-ID": tenant_id},
        body={"reason": "not yet"},
    )
    assert rejected.status_code == 200
    assert rejected.body["campaign"]["approval"]["status"] == "rejected"
    assert rejected.body["campaign"]["promotion"]["status"] == "rejected"

    promote_again = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/promote",
        headers={"X-Tenant-ID": tenant_id},
        body={"branch": "pylon/experiments/promoted/approval-branch"},
    )
    assert promote_again.status_code == 202
    new_approval_id = promote_again.body["campaign"]["approval"]["request_id"]
    assert new_approval_id != approval_id

    approved = server.handle_request(
        "POST",
        f"/api/v1/approvals/{new_approval_id}/approve",
        headers={"X-Tenant-ID": tenant_id},
        body={"reason": "ship it"},
    )
    assert approved.status_code == 200
    assert approved.body["campaign"]["promotion"]["status"] == "promoted"
    promoted_ref = _run(repo, "git", "rev-parse", "pylon/experiments/promoted/approval-branch")
    assert promoted_ref == approved.body["campaign"]["best"]["ref"]

    server.shutdown()


def test_experiment_campaign_cleanup_scavenges_runtime_roots(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    server, store = _make_server()
    tenant_id = "tenant-cleanup"

    create = server.handle_request(
        "POST",
        "/api/v1/experiments",
        headers={"X-Tenant-ID": tenant_id},
        body={
            "objective": "Cleanup stale runtime roots",
            "repo_path": str(repo),
            "benchmark_command": "printf 'METRIC latency='; tr -d '\\n' < score.txt; printf '\\n'",
            "planner_command": "printf '9\\n' > score.txt",
            "metric_name": "latency",
            "metric_direction": "minimize",
            "max_iterations": 1,
            "cleanup": {
                "runtime_ttl_seconds": 1,
                "preserve_failed_worktrees": True,
            },
        },
    )
    campaign = create.body["campaign"]
    campaign_id = campaign["id"]
    runtime_root = Path(campaign["runtime_root"])
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "debug.txt").write_text("stale runtime", encoding="utf-8")

    stale_campaign = dict(store.get_surface_record("experiment_campaigns", campaign_id))
    old_iso = (
        datetime.now(UTC) - timedelta(seconds=120)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    stale_campaign["status"] = "completed"
    stale_campaign["updated_at"] = old_iso
    stale_campaign["completed_at"] = old_iso
    store.put_surface_record(
        "experiment_campaigns",
        campaign_id,
        stale_campaign,
        expected_record_version=int(stale_campaign.get("record_version", 0) or 0),
    )
    store.put_surface_record(
        "experiment_worker_leases",
        campaign_id,
        {
            "id": campaign_id,
            "tenant_id": tenant_id,
            "owner": "stale-worker",
            "thread_name": "stale-thread",
            "status": "completed",
            "heartbeat_at": old_iso,
            "updated_at": old_iso,
            "created_at": old_iso,
        },
    )

    orphan_root = runtime_root.parent / "orphan-runtime"
    orphan_root.mkdir(parents=True, exist_ok=True)
    (orphan_root / "orphan.txt").write_text("orphan", encoding="utf-8")
    old_epoch = time.time() - 50_000
    os.utime(orphan_root, (old_epoch, old_epoch))

    manager = ExperimentCampaignManager(store.control_plane_store)
    stats = manager.cleanup_stale_resources()
    assert stats["cleared_leases"] >= 1
    assert stats["removed_runtime_roots"] >= 1
    assert stats["removed_orphan_runtime_roots"] >= 1
    assert not runtime_root.exists()
    assert not orphan_root.exists()

    server.shutdown()


def test_experiment_campaign_materializes_context_bundle_and_persists_ideas(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    server, _ = _make_server()
    tenant_id = "tenant-context-bundle"

    create = server.handle_request(
        "POST",
        "/api/v1/experiments",
        headers={"X-Tenant-ID": tenant_id},
        body={
            "objective": "Persist experiment context for the planner",
            "repo_path": str(repo),
            "benchmark_command": "printf 'METRIC latency='; tr -d '\\n' < score.txt; printf '\\n'",
            "planner_command": (
                "test -f \"$PYLON_EXPERIMENT_BRIEF_PATH\"; "
                "test -f \"$PYLON_EXPERIMENT_HISTORY_MD_PATH\"; "
                "test -f \"$PYLON_EXPERIMENT_BENCHMARK_SCRIPT\"; "
                "test -d \"$PYLON_EXPERIMENT_CONTEXT_DIR\"; "
                "printf '%s\\n' '- [ ] try a larger cache size' >> \"$PYLON_EXPERIMENT_IDEAS_PATH\"; "
                "printf '9\\n' > score.txt"
            ),
            "checks_command": (
                "test -f README.md && "
                "test -f \"$PYLON_EXPERIMENT_HISTORY_JSON_PATH\" && "
                "test -f \"$PYLON_EXPERIMENT_CHECKS_SCRIPT\""
            ),
            "metric_name": "latency",
            "metric_direction": "minimize",
            "max_iterations": 1,
        },
    )
    assert create.status_code == 201
    campaign = create.body["campaign"]
    campaign_id = campaign["id"]
    context_bundle = campaign["context_bundle"]
    bundle_root = Path(context_bundle["runtime_root"])

    assert context_bundle["workspace_root"] == f".pylon/experiments/{campaign_id}"
    assert bundle_root.joinpath("brief.md").exists()
    assert bundle_root.joinpath("ideas.md").exists()
    assert bundle_root.joinpath("benchmark.sh").exists()
    assert bundle_root.joinpath("checks.sh").exists()

    start = server.handle_request(
        "POST",
        f"/api/v1/experiments/{campaign_id}/start",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert start.status_code == 200

    detail = _wait_for_campaign(server, campaign_id, tenant_id=tenant_id)
    assert detail["campaign"]["status"] == "completed"
    assert detail["iterations"][-1]["changed_files"] == ["score.txt"]

    assert bundle_root.joinpath("brief.md").exists()
    assert bundle_root.joinpath("history.md").exists()
    assert bundle_root.joinpath("history.json").exists()
    assert bundle_root.joinpath("benchmark.sh").exists()
    assert bundle_root.joinpath("ideas.md").exists()
    assert bundle_root.joinpath("checks.sh").exists()

    ideas_content = bundle_root.joinpath("ideas.md").read_text(encoding="utf-8")
    assert "try a larger cache size" in ideas_content

    history_payload = json.loads(bundle_root.joinpath("history.json").read_text(encoding="utf-8"))
    assert history_payload["campaign_id"] == campaign_id
    assert len(history_payload["iterations"]) == 2
    assert history_payload["iterations"][-1]["changed_files"] == ["score.txt"]

    server.shutdown()


def test_build_codex_prompt_mentions_context_bundle_and_recent_history() -> None:
    campaign = {
        "id": "exp_prompt",
        "objective": "Reduce benchmark latency",
        "runtime_root": "/tmp/pylon-experiments/exp_prompt",
        "metric": {
            "name": "latency",
            "direction": "minimize",
            "unit": "ms",
        },
    }
    prompt = _build_codex_prompt(
        campaign,
        planner=PlannerSpec(type="codex", prompt="Focus on high-leverage changes."),
        worktree_path=Path("/tmp/worktree"),
        sequence=2,
        iterations=[
            {
                "sequence": 0,
                "kind": "baseline",
                "status": "completed",
                "outcome": "baseline",
                "metric": {"value": 10.0, "unit": "ms"},
                "decision": {"reason": "Captured baseline metric."},
            },
            {
                "sequence": 1,
                "kind": "candidate",
                "status": "completed",
                "outcome": "discarded",
                "metric": {"value": 11.0, "unit": "ms"},
                "decision": {"reason": "Metric regressed."},
            },
        ],
    )

    assert "/tmp/worktree/.pylon/experiments/exp_prompt/brief.md" in prompt
    assert "/tmp/worktree/.pylon/experiments/exp_prompt/history.md" in prompt
    assert "/tmp/worktree/.pylon/experiments/exp_prompt/ideas.md" in prompt
    assert "Recent iteration history:" in prompt
    assert "baseline; status=completed" in prompt
    assert "iteration 1; status=completed" in prompt
