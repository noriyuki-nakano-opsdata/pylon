"""Experiment-specific advisory context bundles for agent iterations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from pylon.runtime.context_bundle import ContextBundleFile, ContextBundleLayout

_BRIEF_FILE = "brief.md"
_HISTORY_MD_FILE = "history.md"
_HISTORY_JSON_FILE = "history.json"
_BENCHMARK_FILE = "benchmark.sh"
_CHECKS_FILE = "checks.sh"
_IDEAS_FILE = "ideas.md"


@dataclass(frozen=True)
class ExperimentContextBundle:
    """Materialized experiment context payload."""

    layout: ContextBundleLayout
    files: tuple[ContextBundleFile, ...]
    metadata: dict[str, Any]


def build_experiment_context_bundle(
    campaign: Mapping[str, Any],
    iterations: Sequence[Mapping[str, Any]],
) -> ExperimentContextBundle:
    """Build the advisory context bundle for a campaign."""

    layout = _bundle_layout(campaign)
    benchmark_command = str(campaign.get("benchmark_command", "")).strip()
    checks_command = str(campaign.get("checks_command", "")).strip()
    files: list[ContextBundleFile] = [
        ContextBundleFile(_BRIEF_FILE, _render_brief(campaign)),
        ContextBundleFile(_HISTORY_MD_FILE, _render_history_markdown(campaign, iterations)),
        ContextBundleFile(_HISTORY_JSON_FILE, _render_history_json(campaign, iterations)),
        ContextBundleFile(_BENCHMARK_FILE, _render_shell_script(benchmark_command), executable=True),
        ContextBundleFile(
            _IDEAS_FILE,
            _load_existing_ideas(layout) or _default_ideas_markdown(campaign),
            mutable=True,
        ),
    ]
    if checks_command:
        files.append(
            ContextBundleFile(
                _CHECKS_FILE,
                _render_shell_script(checks_command),
                executable=True,
            )
        )
    return ExperimentContextBundle(
        layout=layout,
        files=tuple(files),
        metadata=build_experiment_context_metadata(campaign),
    )


def build_experiment_context_metadata(campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Build stable metadata describing where the context bundle lives."""

    layout = _bundle_layout(campaign)
    workspace_root = layout.normalized_workspace_root().as_posix()
    file_map: dict[str, str] = {
        "brief": f"{workspace_root}/{_BRIEF_FILE}",
        "history_markdown": f"{workspace_root}/{_HISTORY_MD_FILE}",
        "history_json": f"{workspace_root}/{_HISTORY_JSON_FILE}",
        "benchmark_script": f"{workspace_root}/{_BENCHMARK_FILE}",
        "ideas": f"{workspace_root}/{_IDEAS_FILE}",
    }
    checks_command = str(campaign.get("checks_command", "")).strip()
    if checks_command:
        file_map["checks_script"] = f"{workspace_root}/{_CHECKS_FILE}"
    return {
        "runtime_root": str(layout.runtime_root),
        "workspace_root": workspace_root,
        "files": file_map,
        "mutable_files": [_IDEAS_FILE],
    }


def experiment_context_workspace_paths(
    campaign: Mapping[str, Any],
    *,
    worktree_path: Path,
) -> dict[str, Path]:
    """Resolve absolute context bundle paths for a specific worktree."""

    metadata = dict(campaign.get("context_bundle") or {})
    workspace_root = str(metadata.get("workspace_root", "")).strip() or _bundle_layout(campaign).normalized_workspace_root().as_posix()
    root = worktree_path / workspace_root
    return {
        "root": root,
        "brief": root / _BRIEF_FILE,
        "history_markdown": root / _HISTORY_MD_FILE,
        "history_json": root / _HISTORY_JSON_FILE,
        "benchmark_script": root / _BENCHMARK_FILE,
        "checks_script": root / _CHECKS_FILE,
        "ideas": root / _IDEAS_FILE,
    }


def experiment_context_exclude_patterns(campaign: Mapping[str, Any]) -> list[str]:
    """Return git exclude patterns for mirrored bundle files."""

    metadata = dict(campaign.get("context_bundle") or {})
    workspace_root = str(metadata.get("workspace_root", "")).strip() or _bundle_layout(campaign).normalized_workspace_root().as_posix()
    normalized = workspace_root.strip("/")
    return [f"/{normalized}/"]


def summarize_recent_iterations_for_prompt(
    iterations: Sequence[Mapping[str, Any]],
    *,
    limit: int = 5,
) -> str:
    """Produce a compact iteration summary for planner prompts."""

    summarized = [
        _summarize_iteration(item)
        for item in iterations
        if _iteration_should_appear(item)
    ]
    if not summarized:
        return "No prior candidate iterations yet."
    return "\n".join(f"- {line}" for line in summarized[-limit:])


def _bundle_layout(campaign: Mapping[str, Any]) -> ContextBundleLayout:
    campaign_id = str(campaign.get("id", "")).strip()
    runtime_root = Path(str(campaign.get("runtime_root", "")).strip()) / "context-bundle"
    return ContextBundleLayout(
        runtime_root=runtime_root,
        workspace_relative_root=f".pylon/experiments/{campaign_id}",
    )


def _render_brief(campaign: Mapping[str, Any]) -> str:
    metric = dict(campaign.get("metric") or {})
    planner = dict(campaign.get("planner") or {})
    baseline = dict(campaign.get("baseline") or {})
    best = dict(campaign.get("best") or {})
    promotion = dict(campaign.get("promotion") or {})
    context_metadata = build_experiment_context_metadata(campaign)
    lines = [
        "# Experiment Brief",
        "",
        f"- Campaign: {campaign.get('id', '')}",
        f"- Name: {campaign.get('name', '')}",
        f"- Objective: {campaign.get('objective', '')}",
        f"- Status: {campaign.get('status', '')}",
        f"- Repository: {campaign.get('repo_root', '')}",
        f"- Base ref: {campaign.get('base_ref', '')}",
        f"- Metric: {metric.get('name', 'value')} ({metric.get('direction', 'minimize')})",
        f"- Metric unit: {metric.get('unit', '') or 'n/a'}",
        f"- Planner: {planner.get('type', 'command')}",
        f"- Max iterations: {campaign.get('max_iterations', 0)}",
        f"- Baseline value: {_format_metric_value(baseline.get('value'), metric.get('unit'))}",
        f"- Best value: {_format_metric_value(best.get('value'), metric.get('unit'))}",
        f"- Stable branch: {campaign.get('stable_branch', '')}",
        f"- Promotion branch: {promotion.get('branch', '')}",
        "",
        "## Agent Contract",
        "",
        "- Read `brief.md` and `history.md` before editing.",
        "- Use `ideas.md` to capture promising follow-up experiments and lessons learned.",
        "- Do not run the benchmark or checks directly unless the operator explicitly changes the workflow.",
        "- Focus on code changes that improve the tracked metric while preserving quality gates.",
        "",
        "## Bundle Paths",
        "",
        f"- Workspace root: `{context_metadata['workspace_root']}`",
        f"- Benchmark script: `{context_metadata['files']['benchmark_script']}`",
        f"- History summary: `{context_metadata['files']['history_markdown']}`",
        f"- Ideas backlog: `{context_metadata['files']['ideas']}`",
    ]
    if "checks_script" in context_metadata["files"]:
        lines.append(f"- Checks script: `{context_metadata['files']['checks_script']}`")
    return "\n".join(lines).strip() + "\n"


def _render_history_markdown(
    campaign: Mapping[str, Any],
    iterations: Sequence[Mapping[str, Any]],
) -> str:
    metric = dict(campaign.get("metric") or {})
    lines = [
        "# Iteration History",
        "",
        f"- Campaign: {campaign.get('id', '')}",
        f"- Objective: {campaign.get('objective', '')}",
        f"- Metric: {metric.get('name', 'value')} ({metric.get('direction', 'minimize')})",
        "",
    ]
    if not iterations:
        lines.extend(
            [
                "No iterations have been recorded yet.",
                "",
            ]
        )
        return "\n".join(lines)
    for item in iterations:
        summary = _summarize_iteration(item)
        lines.append(f"- {summary}")
        diff_stat = str(item.get("diff_stat", "")).strip()
        if diff_stat:
            lines.append(f"  diff: {diff_stat}")
        changed_files = [str(path) for path in item.get("changed_files", []) if str(path).strip()]
        if changed_files:
            lines.append(f"  files: {', '.join(changed_files[:8])}")
        decision = dict(item.get("decision") or {})
        if decision.get("reason"):
            lines.append(f"  note: {decision['reason']}")
    lines.append("")
    return "\n".join(lines)


def _render_history_json(
    campaign: Mapping[str, Any],
    iterations: Sequence[Mapping[str, Any]],
) -> str:
    metric = dict(campaign.get("metric") or {})
    payload = {
        "campaign_id": str(campaign.get("id", "")),
        "objective": str(campaign.get("objective", "")),
        "status": str(campaign.get("status", "")),
        "metric": {
            "name": str(metric.get("name", "value")),
            "direction": str(metric.get("direction", "minimize")),
            "unit": str(metric.get("unit", "")),
        },
        "baseline": dict(campaign.get("baseline") or {}),
        "best": dict(campaign.get("best") or {}),
        "iterations": [_iteration_json_payload(item) for item in iterations],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _render_shell_script(command: str) -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            command.strip(),
            "",
        ]
    )


def _load_existing_ideas(layout: ContextBundleLayout) -> str:
    ideas_path = Path(layout.runtime_root) / _IDEAS_FILE
    if not ideas_path.is_file():
        return ""
    return ideas_path.read_text(encoding="utf-8")


def _default_ideas_markdown(campaign: Mapping[str, Any]) -> str:
    metric = dict(campaign.get("metric") or {})
    return "\n".join(
        [
            "# Experiment Ideas",
            "",
            f"- Objective: {campaign.get('objective', '')}",
            f"- Metric: {metric.get('name', 'value')} ({metric.get('direction', 'minimize')})",
            "",
            "Use this file for ideas worth revisiting after the current iteration.",
            "",
            "## Queue",
            "- [ ]",
            "",
            "## Notes",
            "",
        ]
    )


def _iteration_should_appear(iteration: Mapping[str, Any]) -> bool:
    kind = str(iteration.get("kind", "")).strip()
    status = str(iteration.get("status", "")).strip()
    return kind == "baseline" or status in {"completed", "failed", "running"}


def _summarize_iteration(iteration: Mapping[str, Any]) -> str:
    label = "baseline" if str(iteration.get("kind", "")) == "baseline" else f"iteration {iteration.get('sequence', 0)}"
    metric = dict(iteration.get("metric") or {})
    decision = dict(iteration.get("decision") or {})
    parts = [
        label,
        f"status={iteration.get('status', '')}",
    ]
    if iteration.get("outcome"):
        parts.append(f"outcome={iteration.get('outcome')}")
    if metric.get("value") is not None:
        parts.append(
            f"metric={_format_metric_value(metric.get('value'), metric.get('unit'))}"
        )
    if decision.get("delta") is not None:
        parts.append(f"delta={_format_numeric(decision.get('delta'))}")
    if decision.get("improvement_ratio") is not None:
        ratio = float(decision.get("improvement_ratio", 0.0) or 0.0) * 100.0
        parts.append(f"improvement={ratio:.2f}%")
    benchmark = dict(iteration.get("benchmark") or {})
    if benchmark:
        parts.append(f"benchmark_exit={benchmark.get('exit_code', '')}")
    checks = dict(iteration.get("checks") or {})
    if checks:
        parts.append(f"checks_exit={checks.get('exit_code', '')}")
    if decision.get("reason"):
        parts.append(f"reason={decision['reason']}")
    return "; ".join(str(part) for part in parts if str(part).strip())


def _iteration_json_payload(iteration: Mapping[str, Any]) -> dict[str, Any]:
    planner = dict(iteration.get("planner") or {})
    benchmark = dict(iteration.get("benchmark") or {})
    checks = dict(iteration.get("checks") or {})
    metric = dict(iteration.get("metric") or {})
    decision = dict(iteration.get("decision") or {})
    return {
        "id": str(iteration.get("id", "")),
        "sequence": int(iteration.get("sequence", 0) or 0),
        "kind": str(iteration.get("kind", "")),
        "status": str(iteration.get("status", "")),
        "outcome": str(iteration.get("outcome", "") or ""),
        "metric": {
            "name": str(metric.get("name", "")),
            "direction": str(metric.get("direction", "")),
            "unit": str(metric.get("unit", "")),
            "value": metric.get("value"),
            "evidence": str(metric.get("evidence", "")),
        },
        "planner": {
            "exit_code": planner.get("exit_code"),
            "duration_ms": planner.get("duration_ms"),
            "planner_type": planner.get("planner_type"),
        },
        "benchmark": {
            "exit_code": benchmark.get("exit_code"),
            "duration_ms": benchmark.get("duration_ms"),
        },
        "checks": {
            "exit_code": checks.get("exit_code"),
            "duration_ms": checks.get("duration_ms"),
        },
        "decision": {
            "kept": decision.get("kept"),
            "reason": str(decision.get("reason", "")),
            "reference_value": decision.get("reference_value"),
            "delta": decision.get("delta"),
            "improvement_ratio": decision.get("improvement_ratio"),
        },
        "commit_ref": str(iteration.get("commit_ref", "") or ""),
        "changed_files": [
            str(path)
            for path in iteration.get("changed_files", [])
            if str(path).strip()
        ],
        "diff_stat": str(iteration.get("diff_stat", "") or ""),
    }


def _format_metric_value(value: Any, unit: Any) -> str:
    if value is None or value == "":
        return "n/a"
    suffix = str(unit or "").strip()
    rendered = _format_numeric(value)
    return f"{rendered}{suffix}" if suffix else rendered


def _format_numeric(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
