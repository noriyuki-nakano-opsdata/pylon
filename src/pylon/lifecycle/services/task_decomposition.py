"""Tsumiki-style task decomposition for lifecycle planning.

Breaks features and milestones into TASK-XXXX formatted items with DAG
dependencies, phase-based milestone planning, and effort estimation.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_VALID_TASK_ID_RE = re.compile(r"^TASK-\d{4}$")
_VALID_PRIORITIES = ("must", "should", "could")
_DEFAULT_PHASE_DURATION_DAYS = 20
_DEFAULT_PHASE_HOUR_TARGET = 180.0
_PHASE_HOUR_TOLERANCE = 0.3  # ±30%
_TASK_KINDS = {"design": 0.25, "implement": 0.55, "integrate": 0.2}


@dataclass(frozen=True)
class TaskItem:
    id: str
    title: str
    description: str = ""
    phase: str = ""
    milestone_id: str | None = None
    depends_on: tuple[str, ...] = ()
    effort_hours: float = 0.0
    priority: str = "should"
    feature_id: str | None = None
    requirement_id: str | None = None


@dataclass(frozen=True)
class TaskDecomposition:
    tasks: tuple[TaskItem, ...] = ()
    dag_edges: tuple[tuple[str, str], ...] = ()
    phase_milestones: tuple[dict[str, Any], ...] = ()
    total_effort_hours: float = 0.0
    critical_path: tuple[str, ...] = ()
    effort_by_phase: dict[str, float] = field(default_factory=dict)
    has_cycles: bool = False


def _ns(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _al(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _ad(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _tid(index: int) -> str:
    return f"TASK-{index:04d}"


def _complexity(feature: dict[str, Any]) -> int:
    subs = len(_al(feature.get("sub_features")))
    deps = len(_al(feature.get("depends_on")))
    return 3 if subs >= 4 else 2 if subs >= 2 or deps >= 2 else 1


def _effort(feature: dict[str, Any], kind: str) -> float:
    base = float(feature.get("effort_hours", 0) or 0) or 8.0
    if _complexity(feature) == 1 and kind == "implement":
        return round(base, 1)
    return round(base * _TASK_KINDS.get(kind, 0.55), 1)


def _generate_tasks(
    feature: dict[str, Any], counter: int, req_map: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    fid = _ns(feature.get("id") or feature.get("feature"))
    title = _ns(feature.get("feature") or feature.get("title") or fid)
    pri = _ns(feature.get("priority")) or "should"
    if pri not in _VALID_PRIORITIES:
        pri = "should"
    mid = _ns(feature.get("milestone_id")) or None
    rid = req_map.get(fid) if fid else None
    c = _complexity(feature)
    plan: list[tuple[str, str, str]] = (
        [("implement", title, f"Implement {title}")] if c == 1
        else [("design", f"Design: {title}", f"Design specification for {title}"),
              ("implement", f"Implement: {title}", f"Implement {title}")]
        + ([("integrate", f"Integrate: {title}", f"Integration testing for {title}")] if c >= 3 else [])
    )
    tasks: list[dict[str, Any]] = []
    for kind, label, desc in plan:
        t = _tid(counter)
        counter += 1
        tasks.append({
            "id": t, "title": label, "description": desc, "phase": "",
            "milestone_id": mid, "depends_on": (tasks[-1]["id"],) if tasks else (),
            "effort_hours": _effort(feature, kind), "priority": pri,
            "feature_id": fid, "requirement_id": rid,
        })
    return tasks, counter


def build_task_dag(tasks: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build adjacency list from task depends_on fields."""
    adj: dict[str, list[str]] = {str(t.get("id", "")): [] for t in tasks}
    for t in tasks:
        for dep in _al(list(t.get("depends_on") or ())):
            if str(dep) in adj:
                adj[str(dep)].append(str(t.get("id", "")))
    return adj


def _in_degrees(adj: dict[str, list[str]]) -> dict[str, int]:
    deg: dict[str, int] = {n: 0 for n in adj}
    for neighbours in adj.values():
        for n in neighbours:
            deg[n] = deg.get(n, 0) + 1
    return deg


def detect_dag_cycles(adjacency: dict[str, list[str]]) -> bool:
    """Detect cycles using Kahn's algorithm. Returns True if cycles exist."""
    deg = _in_degrees(adjacency)
    q: deque[str] = deque(n for n, d in deg.items() if d == 0)
    visited = 0
    while q:
        cur = q.popleft()
        visited += 1
        for nb in adjacency.get(cur, []):
            deg[nb] -= 1
            if deg[nb] == 0:
                q.append(nb)
    return visited < len(deg)


def topological_sort(adjacency: dict[str, list[str]]) -> list[str]:
    """Topological sort using Kahn's algorithm."""
    deg = _in_degrees(adjacency)
    q: deque[str] = deque(sorted(n for n, d in deg.items() if d == 0))
    result: list[str] = []
    while q:
        cur = q.popleft()
        result.append(cur)
        for nb in sorted(adjacency.get(cur, [])):
            deg[nb] -= 1
            if deg[nb] == 0:
                q.append(nb)
    return result


def compute_critical_path(tasks: list[dict[str, Any]], adjacency: dict[str, list[str]]) -> list[str]:
    """Compute critical path (longest path by cumulative effort) via DP."""
    eff = {str(t.get("id", "")): float(t.get("effort_hours", 0) or 0) for t in tasks}
    order = topological_sort(adjacency)
    if not order:
        return []
    dist = {n: eff.get(n, 0.0) for n in order}
    pred: dict[str, str | None] = {n: None for n in order}
    for n in order:
        for nb in adjacency.get(n, []):
            cand = dist[n] + eff.get(nb, 0.0)
            if cand > dist.get(nb, 0.0):
                dist[nb] = cand
                pred[nb] = n
    end = max(dist, key=lambda x: dist[x])
    path: list[str] = []
    cur: str | None = end
    while cur is not None:
        path.append(cur)
        cur = pred.get(cur)
    path.reverse()
    return path


def assign_phase_buckets(
    tasks: list[dict[str, Any]], sorted_ids: list[str],
    *, phase_hour_target: float = _DEFAULT_PHASE_HOUR_TARGET,
) -> tuple[dict[str, str], dict[str, float]]:
    """Assign tasks to phase buckets by topological order and effort budget."""
    eff = {str(t.get("id", "")): float(t.get("effort_hours", 0) or 0) for t in tasks}
    deps = {str(t.get("id", "")): tuple(str(d) for d in _al(list(t.get("depends_on") or ()))) for t in tasks}
    tp: dict[str, str] = {}
    ph: dict[str, float] = {}
    cur_num, cur_hrs = 1, 0.0
    for tid in sorted_ids:
        min_p = max((int(tp[d].split()[-1]) for d in deps.get(tid, ()) if d in tp), default=1)
        if min_p > cur_num:
            cur_num, cur_hrs = min_p, ph.get(f"Phase {min_p}", 0.0)
        e = eff.get(tid, 0.0)
        if cur_hrs + e > phase_hour_target and cur_hrs > 0 and cur_num == min_p:
            cur_num += 1
            cur_hrs = ph.get(f"Phase {cur_num}", 0.0)
        label = f"Phase {cur_num}"
        tp[tid] = label
        cur_hrs += e
        ph[label] = ph.get(label, 0.0) + e
    return tp, ph


def decompose_features_to_tasks(
    features: list[dict[str, Any]], milestones: list[dict[str, Any]], *,
    requirements: list[dict[str, Any]] | None = None,
    phase_duration_days: int = _DEFAULT_PHASE_DURATION_DAYS,
    phase_hour_target: float = _DEFAULT_PHASE_HOUR_TARGET,
) -> dict[str, Any]:
    """Decompose features and milestones into a task DAG."""
    req_map: dict[str, str] = {}
    for req in _al(requirements or []):
        rd = _ad(req)
        rid = _ns(rd.get("id"))
        for fid in _al(rd.get("feature_ids")):
            if _ns(fid) and rid:
                req_map[_ns(fid)] = rid
    all_tasks: list[dict[str, Any]] = []
    ranges: dict[str, tuple[str, str]] = {}
    counter = 1
    for f in features:
        fid = _ns(f.get("id") or f.get("feature"))
        tasks, counter = _generate_tasks(f, counter, req_map)
        if tasks and fid:
            ranges[fid] = (tasks[0]["id"], tasks[-1]["id"])
        all_tasks.extend(tasks)
    for f in features:
        fid = _ns(f.get("id") or f.get("feature"))
        if not fid:
            continue
        for dep_fid in _al(f.get("depends_on")):
            dfid = _ns(dep_fid)
            if dfid in ranges and fid in ranges:
                last, first = ranges[dfid][1], ranges[fid][0]
                for t in all_tasks:
                    if t["id"] == first:
                        existing = tuple(t.get("depends_on") or ())
                        if last not in existing:
                            t["depends_on"] = (*existing, last)
                        break
    adj = build_task_dag(all_tasks)
    cycles = detect_dag_cycles(adj)
    order = topological_sort(adj) if not cycles else list(adj.keys())
    tp, ph = assign_phase_buckets(all_tasks, order, phase_hour_target=phase_hour_target)
    for t in all_tasks:
        t["phase"] = tp.get(t["id"], "")
    edges = [(str(d), t["id"]) for t in all_tasks for d in (t.get("depends_on") or ())]
    cpath = compute_critical_path(all_tasks, adj) if not cycles else []
    ms_lookup = {_ns(m.get("id") or m.get("name")): m for m in milestones if _ns(m.get("id") or m.get("name"))}
    pm: list[dict[str, Any]] = []
    for label in sorted(ph, key=lambda x: int(x.split()[-1])):
        pts = [t for t in all_tasks if t.get("phase") == label]
        linked = {t.get("milestone_id") for t in pts if t.get("milestone_id") in ms_lookup}
        pm.append({"phase": label, "milestone_ids": sorted(linked), "task_count": len(pts),
                    "total_hours": ph[label], "duration_days": phase_duration_days})
    total = round(sum(float(t.get("effort_hours", 0) or 0) for t in all_tasks), 1)
    return task_decomposition_to_dict(TaskDecomposition(
        tasks=tuple(TaskItem(**t) for t in all_tasks), dag_edges=tuple(edges),
        phase_milestones=tuple(pm), total_effort_hours=total,
        critical_path=tuple(cpath), effort_by_phase=dict(ph), has_cycles=cycles))


def validate_task_decomposition(decomposition: dict[str, Any]) -> list[str]:
    """Validate a task decomposition. Returns list of issue strings."""
    issues: list[str] = []
    tasks = _al(decomposition.get("tasks"))
    seen: set[str] = set()
    all_ids = {str(_ad(t).get("id", "")) for t in tasks}
    for task in tasks:
        t = _ad(task)
        tid = str(t.get("id", ""))
        if not _VALID_TASK_ID_RE.match(tid):
            issues.append(f"Invalid task ID format: {tid}")
        if tid in seen:
            issues.append(f"Duplicate task ID: {tid}")
        seen.add(tid)
        for dep in _al(list(t.get("depends_on") or ())):
            if str(dep) not in all_ids:
                issues.append(f"Task {tid} depends on unknown task {dep}")
        if str(t.get("priority", "")) not in _VALID_PRIORITIES:
            issues.append(f"Task {tid} has invalid priority: {t.get('priority')}")
        if float(t.get("effort_hours", 0) or 0) < 0:
            issues.append(f"Task {tid} has negative effort: {t.get('effort_hours')}")
    if detect_dag_cycles(build_task_dag([_ad(t) for t in tasks])):
        issues.append("Task DAG contains cycles")
    return issues


_TASK_FIELDS = ("id", "title", "description", "phase", "milestone_id",
                "depends_on", "effort_hours", "priority", "feature_id", "requirement_id")


def task_decomposition_to_dict(decomposition: TaskDecomposition) -> dict[str, Any]:
    """Serialize TaskDecomposition to dict for state storage."""
    def _task(t: TaskItem) -> dict[str, Any]:
        d = {f: getattr(t, f) for f in _TASK_FIELDS}
        d["depends_on"] = list(t.depends_on)
        return d
    return {
        "tasks": [_task(t) for t in decomposition.tasks],
        "dag_edges": [list(e) for e in decomposition.dag_edges],
        "phase_milestones": [dict(m) for m in decomposition.phase_milestones],
        "total_effort_hours": decomposition.total_effort_hours,
        "critical_path": list(decomposition.critical_path),
        "effort_by_phase": dict(decomposition.effort_by_phase),
        "has_cycles": decomposition.has_cycles,
    }


def task_decomposition_from_dict(data: dict[str, Any]) -> TaskDecomposition:
    """Deserialize TaskDecomposition from dict."""
    raw = _ad(data)
    tasks = tuple(
        TaskItem(
            id=str(_ad(t).get("id", "")), title=str(_ad(t).get("title", "")),
            description=str(_ad(t).get("description", "")), phase=str(_ad(t).get("phase", "")),
            milestone_id=_ad(t).get("milestone_id"),
            depends_on=tuple(str(d) for d in _al(_ad(t).get("depends_on"))),
            effort_hours=float(_ad(t).get("effort_hours", 0) or 0),
            priority=str(_ad(t).get("priority", "should")),
            feature_id=_ad(t).get("feature_id"), requirement_id=_ad(t).get("requirement_id"),
        ) for t in _al(raw.get("tasks")))
    edges = tuple((str(e[0]), str(e[1])) for e in _al(raw.get("dag_edges"))
                  if isinstance(e, (list, tuple)) and len(e) >= 2)
    return TaskDecomposition(
        tasks=tasks, dag_edges=edges,
        phase_milestones=tuple(_ad(m) for m in _al(raw.get("phase_milestones"))),
        total_effort_hours=float(raw.get("total_effort_hours", 0) or 0),
        critical_path=tuple(str(i) for i in _al(raw.get("critical_path"))),
        effort_by_phase={str(k): float(v or 0) for k, v in _ad(raw.get("effort_by_phase")).items()},
        has_cycles=bool(raw.get("has_cycles")))
