from __future__ import annotations

from pylon.dsl.parser import PylonProject
from pylon.runtime.planning import plan_project_dispatch


def _linear_project() -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": "planning-demo",
            "agents": {
                "researcher": {"role": "research"},
                "writer": {"role": "write"},
            },
            "workflow": {
                "nodes": {
                    "start": {"agent": "researcher", "next": "finish"},
                    "finish": {"agent": "writer", "next": "END"},
                }
            },
        }
    )


def _join_project() -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": "planning-join",
            "agents": {
                "router": {"role": "route"},
            },
            "workflow": {
                "nodes": {
                    "start": {"agent": "router", "next": ["left", "right"]},
                    "left": {"agent": "router", "next": "join"},
                    "right": {"agent": "router", "next": "join"},
                    "join": {
                        "agent": "router",
                        "node_type": "router",
                        "join_policy": "first",
                        "next": "END",
                    },
                }
            },
        }
    )


def test_plan_project_dispatch_linear_workflow() -> None:
    plan = plan_project_dispatch(
        _linear_project(),
        workflow_id="wf1",
        tenant_id="tenant-a",
    ).to_dict()

    assert plan["workflow_id"] == "wf1"
    assert plan["tenant_id"] == "tenant-a"
    assert plan["execution_mode"] == "distributed_wave_plan"
    assert plan["entry_nodes"] == ["start"]
    assert plan["wave_count"] == 2
    assert plan["waves"] == [
        {"index": 0, "node_ids": ["start"], "task_ids": ["wf1:start"]},
        {"index": 1, "node_ids": ["finish"], "task_ids": ["wf1:finish"]},
    ]
    assert plan["tasks"] == [
        {
            "task_id": "wf1:start",
            "node_id": "start",
            "wave_index": 0,
            "depends_on": [],
            "dependency_task_ids": [],
            "node_type": "agent",
            "join_policy": "all_resolved",
            "conditional_inbound": False,
            "conditional_outbound": False,
        },
        {
            "task_id": "wf1:finish",
            "node_id": "finish",
            "wave_index": 1,
            "depends_on": ["start"],
            "dependency_task_ids": ["wf1:start"],
            "node_type": "agent",
            "join_policy": "all_resolved",
            "conditional_inbound": False,
            "conditional_outbound": False,
        },
    ]


def test_plan_project_dispatch_join_workflow_groups_parallel_wave() -> None:
    plan = plan_project_dispatch(_join_project(), workflow_id="wf-join").to_dict()

    assert plan["waves"] == [
        {"index": 0, "node_ids": ["start"], "task_ids": ["wf-join:start"]},
        {
            "index": 1,
            "node_ids": ["left", "right"],
            "task_ids": ["wf-join:left", "wf-join:right"],
        },
        {"index": 2, "node_ids": ["join"], "task_ids": ["wf-join:join"]},
    ]
    join_task = next(task for task in plan["tasks"] if task["node_id"] == "join")
    assert join_task["depends_on"] == ["left", "right"]
    assert join_task["dependency_task_ids"] == ["wf-join:left", "wf-join:right"]
    assert join_task["node_type"] == "router"
    assert join_task["join_policy"] == "first"
