"""Tests for task decomposition engine."""

from pylon.lifecycle.services.task_decomposition import (
    assign_phase_buckets,
    build_task_dag,
    compute_critical_path,
    decompose_features_to_tasks,
    detect_dag_cycles,
    topological_sort,
    validate_task_decomposition,
)


def test_decompose_simple_features():
    features = [{"id": "feat-1", "name": "Dashboard", "priority": "must"}]
    milestones = [{"id": "ms-1", "name": "MVP"}]
    result = decompose_features_to_tasks(features, milestones)
    assert len(result["tasks"]) >= 1
    assert result["tasks"][0]["id"] == "TASK-0001"
    assert result["tasks"][0]["feature_id"] == "feat-1"


def test_decompose_complex_feature_produces_multiple_tasks():
    features = [
        {
            "id": "feat-1",
            "name": "Auth System",
            "priority": "must",
            "sub_features": ["login", "register", "password-reset", "2fa"],
        },
    ]
    milestones = [{"id": "ms-1", "name": "MVP"}]
    result = decompose_features_to_tasks(features, milestones)
    assert len(result["tasks"]) >= 2


def test_decompose_preserves_cross_feature_dependencies():
    features = [
        {"id": "feat-1", "name": "Auth", "priority": "must"},
        {"id": "feat-2", "name": "Dashboard", "priority": "must", "depends_on": ["feat-1"]},
    ]
    milestones = [{"id": "ms-1", "name": "MVP"}]
    result = decompose_features_to_tasks(features, milestones)
    dashboard_tasks = [t for t in result["tasks"] if t["feature_id"] == "feat-2"]
    auth_tasks = [t for t in result["tasks"] if t["feature_id"] == "feat-1"]
    assert any(
        any(dep in [a["id"] for a in auth_tasks] for dep in dt["depends_on"])
        for dt in dashboard_tasks
    )


def test_decompose_links_requirements():
    features = [{"id": "feat-1", "name": "Dashboard", "priority": "must"}]
    milestones = [{"id": "ms-1", "name": "MVP"}]
    requirements = [{"id": "REQ-0001", "feature_ids": ["feat-1"]}]
    result = decompose_features_to_tasks(features, milestones, requirements=requirements)
    assert any(t.get("requirement_id") == "REQ-0001" for t in result["tasks"])


def test_decompose_empty_features():
    result = decompose_features_to_tasks([], [])
    assert result["tasks"] == []
    assert result["total_effort_hours"] == 0.0


def test_build_task_dag_adjacency():
    tasks = [
        {"id": "TASK-0001", "depends_on": []},
        {"id": "TASK-0002", "depends_on": ["TASK-0001"]},
        {"id": "TASK-0003", "depends_on": ["TASK-0001"]},
    ]
    dag = build_task_dag(tasks)
    assert "TASK-0002" in dag.get("TASK-0001", [])
    assert "TASK-0003" in dag.get("TASK-0001", [])


def test_detect_dag_cycles_no_cycle():
    adjacency = {"A": ["B"], "B": ["C"], "C": []}
    assert detect_dag_cycles(adjacency) is False


def test_detect_dag_cycles_with_cycle():
    adjacency = {"A": ["B"], "B": ["C"], "C": ["A"]}
    assert detect_dag_cycles(adjacency) is True


def test_detect_dag_cycles_empty():
    assert detect_dag_cycles({}) is False


def test_topological_sort_linear():
    adjacency = {"A": ["B"], "B": ["C"], "C": []}
    result = topological_sort(adjacency)
    assert result.index("A") < result.index("B") < result.index("C")


def test_topological_sort_diamond():
    adjacency = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
    result = topological_sort(adjacency)
    assert result.index("A") < result.index("B")
    assert result.index("A") < result.index("C")
    assert result.index("B") < result.index("D")
    assert result.index("C") < result.index("D")


def test_compute_critical_path_linear():
    tasks = [
        {"id": "A", "effort_hours": 10, "depends_on": []},
        {"id": "B", "effort_hours": 20, "depends_on": ["A"]},
        {"id": "C", "effort_hours": 5, "depends_on": ["B"]},
    ]
    adjacency = {"A": ["B"], "B": ["C"], "C": []}
    path = compute_critical_path(tasks, adjacency)
    assert path == ["A", "B", "C"]


def test_compute_critical_path_selects_longest():
    tasks = [
        {"id": "A", "effort_hours": 10, "depends_on": []},
        {"id": "B", "effort_hours": 50, "depends_on": ["A"]},
        {"id": "C", "effort_hours": 5, "depends_on": ["A"]},
        {"id": "D", "effort_hours": 10, "depends_on": ["B", "C"]},
    ]
    adjacency = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
    path = compute_critical_path(tasks, adjacency)
    assert "B" in path
    assert "A" in path
    assert "D" in path


def test_assign_phase_buckets_respects_target():
    tasks = [
        {"id": "TASK-0001", "effort_hours": 100, "depends_on": []},
        {"id": "TASK-0002", "effort_hours": 100, "depends_on": []},
        {"id": "TASK-0003", "effort_hours": 100, "depends_on": []},
    ]
    sorted_ids = ["TASK-0001", "TASK-0002", "TASK-0003"]
    phases, effort = assign_phase_buckets(tasks, sorted_ids, phase_hour_target=180.0)
    unique_phases = set(phases.values())
    assert len(unique_phases) >= 2


def test_assign_phase_buckets_respects_dependencies():
    tasks = [
        {"id": "TASK-0001", "effort_hours": 50, "depends_on": []},
        {"id": "TASK-0002", "effort_hours": 50, "depends_on": ["TASK-0001"]},
    ]
    sorted_ids = ["TASK-0001", "TASK-0002"]
    phases, _ = assign_phase_buckets(tasks, sorted_ids, phase_hour_target=180.0)
    assert phases["TASK-0002"] >= phases["TASK-0001"]


def _task(id: str = "TASK-0001", depends_on: list | None = None,
          priority: str = "must", effort_hours: float = 10) -> dict:
    return {"id": id, "depends_on": depends_on or [], "priority": priority,
            "effort_hours": effort_hours}


def _decomp(tasks: list, has_cycles: bool = False) -> dict:
    return {"tasks": tasks, "has_cycles": has_cycles}


def test_validate_task_decomposition_valid():
    decomp = _decomp([_task(), _task("TASK-0002", ["TASK-0001"], "should", 5)])
    assert validate_task_decomposition(decomp) == []


def test_validate_task_decomposition_invalid_id():
    issues = validate_task_decomposition(_decomp([_task(id="BAD")]))
    assert any("Invalid task ID" in i or "BAD" in i for i in issues)


def test_validate_task_decomposition_duplicate_ids():
    issues = validate_task_decomposition(_decomp([_task(), _task(effort_hours=5)]))
    assert any("duplicate" in i.lower() for i in issues)


def test_validate_task_decomposition_missing_dependency():
    issues = validate_task_decomposition(_decomp([_task(depends_on=["TASK-9999"])]))
    assert any("TASK-9999" in i for i in issues)


def test_validate_task_decomposition_invalid_priority():
    issues = validate_task_decomposition(_decomp([_task(priority="critical")]))
    assert any("priority" in i.lower() for i in issues)


def test_validate_task_decomposition_negative_effort():
    issues = validate_task_decomposition(_decomp([_task(effort_hours=-5)]))
    assert any("effort" in i.lower() or "negative" in i.lower() for i in issues)
