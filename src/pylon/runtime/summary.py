"""Shared execution summary builder for public runtime surfaces."""

from __future__ import annotations

from typing import Any

from pylon.types import RunStatus, RunStopReason


def build_execution_summary(
    *,
    status: RunStatus,
    stop_reason: RunStopReason,
    suspension_reason: RunStopReason,
    state: dict[str, Any],
    event_log: list[dict[str, Any]],
    active_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable operator-facing execution summary."""
    execution_state = state.get("execution", {})
    edge_catalog = execution_state.get("edge_catalog", {})
    timeline = [
        {
            "seq": int(event.get("seq", index + 1)),
            "node_id": str(event.get("node_id", "")),
            "attempt_id": int(event.get("attempt_id", 1)),
            "loop_iteration": int(event.get("loop_iteration", 1)),
            "verification": (
                event.get("verification", {}).get("disposition")
                if isinstance(event.get("verification"), dict)
                else None
            ),
        }
        for index, event in enumerate(event_log)
    ]
    critical_path = [
        {
            "node_id": item["node_id"],
            "attempt_id": item["attempt_id"],
            "loop_iteration": item["loop_iteration"],
        }
        for item in timeline
    ]
    decision_points: list[dict[str, Any]] = []
    for event in event_log:
        raw_resolutions = event.get("edge_resolutions", [])
        if not isinstance(raw_resolutions, list) or not raw_resolutions:
            continue
        decision_points.append(
            {
                "type": "edge_decision",
                "source_node": str(event.get("node_id", "")),
                "edges": [
                    {
                        "edge_key": str(item.get("edge_key", "")),
                        "edge_index": (
                            int(str(item.get("edge_key", "")).partition(":")[2])
                            if str(item.get("edge_key", "")).partition(":")[2].isdigit()
                            else str(item.get("edge_key", "")).partition(":")[2]
                        ),
                        "status": str(item.get("status", "")),
                        "target": item.get("target"),
                        "condition": item.get("condition"),
                        "decision_source": item.get("decision_source"),
                        "reason": item.get("reason"),
                    }
                    for item in raw_resolutions
                    if isinstance(item, dict)
                ],
            }
        )
    if not any(point["type"] == "edge_decision" for point in decision_points):
        edge_status = execution_state.get("edge_status", {})
        if isinstance(edge_status, dict):
            grouped_edge_status: dict[str, list[dict[str, Any]]] = {}
            for raw_key, raw_status in edge_status.items():
                source_node, _, edge_index = str(raw_key).partition(":")
                edge_meta = (
                    edge_catalog.get(str(raw_key), {})
                    if isinstance(edge_catalog, dict)
                    else {}
                )
                grouped_edge_status.setdefault(source_node, []).append(
                    {
                        "edge_key": str(raw_key),
                        "edge_index": int(edge_index) if edge_index.isdigit() else edge_index,
                        "status": str(raw_status),
                        "target": edge_meta.get("target"),
                        "condition": edge_meta.get("condition"),
                    }
                )
            for source_node, edges in sorted(grouped_edge_status.items()):
                resolved_edges = [
                    edge for edge in sorted(edges, key=lambda item: str(item["edge_key"]))
                    if edge["status"] != "pending"
                ]
                if resolved_edges:
                    decision_points.append(
                        {
                            "type": "edge_decision",
                            "source_node": source_node,
                            "edges": resolved_edges,
                        }
                    )
    join_winners = execution_state.get("join_winners", {})
    if isinstance(join_winners, dict):
        for node_id, winner in sorted(join_winners.items()):
            edge_meta = (
                edge_catalog.get(str(winner), {})
                if isinstance(edge_catalog, dict)
                else {}
            )
            decision_points.append(
                {
                    "type": "join_selection",
                    "node_id": str(node_id),
                    "winner_edge": str(winner),
                    "winner_source": edge_meta.get("source"),
                    "winner_target": edge_meta.get("target"),
                    "winner_condition": edge_meta.get("condition"),
                }
            )
    previous_attempt = 1
    for item in timeline:
        if item["attempt_id"] > previous_attempt:
            decision_points.append(
                {
                    "type": "replan",
                    "node_id": item["node_id"],
                    "attempt_id": item["attempt_id"],
                }
            )
        previous_attempt = item["attempt_id"]
        if item["loop_iteration"] > 1:
            decision_points.append(
                {
                    "type": "loop_retry",
                    "node_id": item["node_id"],
                    "attempt_id": item["attempt_id"],
                    "loop_iteration": item["loop_iteration"],
                }
            )
        if item["verification"] not in (None, "success"):
            decision_points.append(
                {
                    "type": "verification",
                    "node_id": item["node_id"],
                    "attempt_id": item["attempt_id"],
                    "disposition": item["verification"],
                }
            )
    transition_reason = (
        state.get("termination_reason")
        or state.get("approval_reason")
        or state.get("escalation_reason")
        or state.get("error")
        or state.get("pause_reason")
    )
    if active_approval is not None or status == RunStatus.WAITING_APPROVAL:
        decision_points.append(
            {
                "type": "approval_required",
                "approval_id": (
                    active_approval.get("id") if isinstance(active_approval, dict)
                    else state.get("approval_request_id")
                ),
                "context": (
                    active_approval.get("context", {}).get("kind")
                    if isinstance(active_approval, dict)
                    else state.get("approval_context")
                ),
                "reason": (
                    active_approval.get("context", {}).get("reason")
                    if isinstance(active_approval, dict)
                    else transition_reason
                )
                or transition_reason,
            }
        )
    if stop_reason != RunStopReason.NONE or suspension_reason != RunStopReason.NONE:
        decision_points.append(
            {
                "type": "terminal_transition",
                "status": status.value,
                "stop_reason": stop_reason.value,
                "suspension_reason": suspension_reason.value,
                "reason": transition_reason,
            }
        )
    return {
        "total_events": len(event_log),
        "attempt_count": max((item["attempt_id"] for item in timeline), default=0),
        "replan_count": (
            state.get("runtime_metrics", {}).get("replan_count")
            or state.get("autonomy", {}).get("replan_count")
            or state.get("replan_count", 0)
        ),
        "last_node": event_log[-1].get("node_id") if event_log else None,
        "node_sequence": [event.get("node_id") for event in event_log],
        "timeline": timeline,
        "critical_path": critical_path,
        "decision_points": decision_points,
        "goal_satisfied": bool(state.get("goal_status", {}).get("satisfied", False)),
        "final_verification_disposition": (
            state.get("verification", {}).get("disposition")
            if isinstance(state.get("verification"), dict)
            else None
        ),
        "pending_approval": active_approval is not None or status == RunStatus.WAITING_APPROVAL,
        "transition_reason": transition_reason,
    }
