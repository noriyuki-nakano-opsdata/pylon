import { formatElapsed } from "@/lib/time";
import type { AgentProgress, WorkflowRunState } from "@/hooks/useWorkflowRun";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type {
  LifecycleAgentBlueprint,
  LifecyclePhase,
  LifecyclePhaseRuntimeAction,
  LifecyclePhaseRuntimeAgent,
  LifecyclePhaseRuntimeSummary,
  WorkflowRunLiveEvent,
  WorkflowRunLiveTelemetry,
} from "@/types/lifecycle";
import type {
  CollaborationAction,
  CollaborationAgent,
  CollaborationEvent,
} from "@/components/lifecycle/MultiAgentCollaborationPulse";

function mapRuntimeStatus(
  status: LifecyclePhaseRuntimeAgent["status"],
): CollaborationAgent["status"] {
  return status === "idle" ? "pending" : status;
}

function formatLiveEventTimestamp(value?: string): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return parsed.toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function resolvePhaseRuntimeSummary(
  lifecycle: Pick<
    LifecycleWorkspaceView,
    "runtimeActivePhase" | "runtimeActivePhaseSummary" | "runtimePhaseSummary"
  >,
  phase: LifecyclePhase,
): LifecyclePhaseRuntimeSummary | null {
  if (lifecycle.runtimeActivePhase === phase) {
    return lifecycle.runtimeActivePhaseSummary;
  }
  if (lifecycle.runtimePhaseSummary?.phase === phase) {
    return lifecycle.runtimePhaseSummary;
  }
  return null;
}

function normalizeTelemetryPhase(
  telemetry: WorkflowRunLiveTelemetry | null,
  phase: LifecyclePhase,
): WorkflowRunLiveTelemetry | null {
  if (!telemetry) {
    return null;
  }
  return {
    ...telemetry,
    phase: telemetry.phase ?? phase,
  };
}

function telemetryHasSignal(telemetry: WorkflowRunLiveTelemetry | null): boolean {
  if (!telemetry || !telemetry.run) {
    return false;
  }
  return (
    telemetry.completedNodeCount > 0
    || telemetry.runningNodeIds.length > 0
    || telemetry.failedNodeIds.length > 0
    || telemetry.recentNodeIds.length > 0
    || telemetry.recentEvents.length > 0
    || Boolean(telemetry.activeFocusNodeId)
    || Boolean(telemetry.lastNodeId)
    || telemetry.lastEventSeq !== null
  );
}

function executionSummaryStringList(
  value: unknown,
): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item ?? "").trim())
    .filter((item) => item.length > 0);
}

function executionSummaryNumber(
  value: unknown,
): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : null;
}

function buildPersistedPhaseTelemetry(
  lifecycle: Pick<LifecycleWorkspaceView, "phaseRuns" | "phaseStatuses">,
  phase: LifecyclePhase,
  team: LifecycleAgentBlueprint[],
): WorkflowRunLiveTelemetry | null {
  const phaseStatus = lifecycle.phaseStatuses?.find((item) => item.phase === phase)?.status;
  if (phaseStatus !== "completed" && phaseStatus !== "review") {
    return null;
  }
  const latestRun = [...(lifecycle.phaseRuns ?? [])]
    .filter((run) => run.phase === phase && (run.status === "completed" || run.status === "succeeded"))
    .sort((left, right) => {
      const leftKey = left.completedAt ?? left.createdAt;
      const rightKey = right.completedAt ?? right.createdAt;
      return rightKey.localeCompare(leftKey);
    })[0];
  if (!latestRun) {
    return null;
  }

  const executionSummary = latestRun.executionSummary ?? {};
  const nodeSequence = executionSummaryStringList(
    (executionSummary as Record<string, unknown>).node_sequence
      ?? (executionSummary as Record<string, unknown>).nodeSequence,
  );
  const recentNodeIds = executionSummaryStringList(
    (executionSummary as Record<string, unknown>).recentNodeIds,
  );
  const completedNodeCount = executionSummaryNumber(
    (executionSummary as Record<string, unknown>).completedNodeCount,
  ) ?? new Set(nodeSequence).size;
  const eventCount = executionSummaryNumber(
    (executionSummary as Record<string, unknown>).eventCount
      ?? (executionSummary as Record<string, unknown>).total_events,
  ) ?? nodeSequence.length;
  const runningNodeIds = executionSummaryStringList(
    (executionSummary as Record<string, unknown>).runningNodeIds,
  );
  const failedNodeIds = executionSummaryStringList(
    (executionSummary as Record<string, unknown>).failedNodeIds,
  );
  const lastNodeId = String(
    (executionSummary as Record<string, unknown>).lastNodeId
      ?? (executionSummary as Record<string, unknown>).last_node
      ?? nodeSequence.at(-1)
      ?? "",
  ).trim() || undefined;
  const fallbackRecentNodeIds = recentNodeIds.length > 0
    ? recentNodeIds
    : Array.from(new Set([...nodeSequence].reverse())).slice(0, 3);
  const teamById = new Map(team.map((agent) => [agent.id, agent.label]));
  const recentEvents = [...nodeSequence]
    .reverse()
    .reduce<WorkflowRunLiveEvent[]>((events, nodeId, index) => {
      if (!nodeId || events.some((event) => event.nodeId === nodeId)) {
        return events;
      }
      const label = teamById.get(nodeId) ?? nodeId;
      events.push({
        seq: eventCount - index > 0 ? eventCount - index : null,
        nodeId,
        agent: label,
        status: failedNodeIds.includes(nodeId)
          ? "failed"
          : runningNodeIds.includes(nodeId)
            ? "running"
            : "completed",
        summary: `${label} が完了`,
      });
      return events;
    }, [])
    .slice(0, 5);

  if (completedNodeCount <= 0 && !lastNodeId && recentEvents.length === 0) {
    return null;
  }

  return {
    run: {
      id: latestRun.runId,
      status: latestRun.status,
      startedAt: latestRun.startedAt ?? latestRun.createdAt,
      completedAt: latestRun.completedAt ?? null,
    },
    phase,
    eventCount,
    completedNodeCount,
    runningNodeIds,
    failedNodeIds,
    lastEventSeq: eventCount > 0 ? eventCount : null,
    lastNodeId,
    recentNodeIds: fallbackRecentNodeIds,
    recentEvents,
  };
}

function resolvePhaseTelemetry(
  lifecycle: Pick<
    LifecycleWorkspaceView,
    "runtimeActivePhase" | "runtimeLiveTelemetry" | "phaseRuns" | "phaseStatuses"
  >,
  phase: LifecyclePhase,
  team: LifecycleAgentBlueprint[],
  workflowTelemetry?: WorkflowRunLiveTelemetry | null,
): WorkflowRunLiveTelemetry | null {
  const rawRuntimeTelemetry = lifecycle.runtimeLiveTelemetry;
  const runtimeTelemetry = normalizeTelemetryPhase(lifecycle.runtimeLiveTelemetry, phase);
  const runtimeTelemetryMatchesPhase = runtimeTelemetry != null && (
    rawRuntimeTelemetry?.phase != null
      ? rawRuntimeTelemetry.phase === phase
      : lifecycle.runtimeActivePhase === phase
  );
  if (runtimeTelemetryMatchesPhase) {
    if (runtimeTelemetry?.phase === phase) {
      if (telemetryHasSignal(runtimeTelemetry)) {
        return runtimeTelemetry;
      }
    }
  }

  const workflowScopedTelemetry = normalizeTelemetryPhase(workflowTelemetry ?? null, phase);
  if (telemetryHasSignal(workflowScopedTelemetry)) {
    return workflowScopedTelemetry;
  }

  return buildPersistedPhaseTelemetry(lifecycle, phase, team);
}

function buildAgentsFromRuntimeSummary(
  runtimeSummary: LifecyclePhaseRuntimeSummary,
): CollaborationAgent[] {
  return (runtimeSummary.agents ?? []).map((agent) => ({
    id: agent.agentId,
    label: agent.label,
    status: mapRuntimeStatus(agent.status),
    currentTask: agent.currentTask,
    delegatedTo: agent.delegatedTo,
  }));
}

function buildAgentsFromWorkflow(
  team: LifecycleAgentBlueprint[],
  progress: AgentProgress[],
): CollaborationAgent[] {
  return team.map((agent) => {
    const progressItem = progress.find((item) => item.nodeId === agent.id || item.agent === agent.id);
    return {
      id: agent.id,
      label: agent.label,
      status: progressItem?.status ?? "pending",
      currentTask: progressItem?.status === "running"
        ? `${agent.label} が現在の担当レーンを進行中`
        : progressItem?.status === "completed"
          ? `${agent.label} が担当アウトプットを提出済み`
          : progressItem?.status === "failed"
            ? `${agent.label} の結果を再確認中`
            : `${agent.label} が dispatch を待機中`,
    };
  });
}

function applyWarmupMotion(
  agents: CollaborationAgent[],
  warmupTasks: string[],
): CollaborationAgent[] {
  if (agents.some((agent) => agent.status !== "pending")) {
    return agents;
  }
  return agents.map((agent, index) => ({
    ...agent,
    status: index < 2 ? "running" : "pending",
    currentTask: warmupTasks[index] ?? agent.currentTask,
  }));
}

function shouldApplyWarmupMotion(
  lifecycle: Pick<LifecycleWorkspaceView, "phaseStatuses">,
  phase: LifecyclePhase,
  runtimeSummary: LifecyclePhaseRuntimeSummary | null,
  telemetry: WorkflowRunLiveTelemetry | null,
): boolean {
  const phaseStatus = lifecycle.phaseStatuses.find((item) => item.phase === phase)?.status ?? null;
  if (phaseStatus === "completed" || phaseStatus === "review") {
    return false;
  }
  if (runtimeSummary?.status === "completed" || runtimeSummary?.status === "review") {
    return false;
  }
  if (telemetry?.run?.status === "completed" || telemetry?.run?.status === "failed") {
    return false;
  }
  return true;
}

function buildActionsFromRuntimeSummary(
  runtimeSummary: LifecyclePhaseRuntimeSummary | null,
): CollaborationAction[] {
  return (runtimeSummary?.recentActions ?? []).slice(0, 6).map((action: LifecyclePhaseRuntimeAction, index) => ({
    id: `${action.nodeId}:${index}`,
    label: action.nodeLabel ?? action.label,
    summary: action.summary,
    status: action.status,
    from: action.agentLabel ?? action.agent,
    to: action.nodeLabel ?? action.label,
  }));
}

function buildEventsFromTelemetry(
  telemetry: WorkflowRunLiveTelemetry | null,
): CollaborationEvent[] {
  return (telemetry?.recentEvents ?? []).slice(0, 6).map((event: WorkflowRunLiveEvent, index) => ({
    id: `${event.nodeId}:${event.seq ?? index}`,
    label: event.agent ?? event.nodeId,
    summary: event.summary,
    timestamp: formatLiveEventTimestamp(event.timestamp),
  }));
}

function resolveElapsedLabel(
  workflow: Pick<WorkflowRunState, "elapsedMs">,
  telemetry: WorkflowRunLiveTelemetry | null,
): string {
  if (workflow.elapsedMs > 0) {
    return formatElapsed(workflow.elapsedMs);
  }
  const startedAt = telemetry?.run?.startedAt ? new Date(telemetry.run.startedAt).getTime() : null;
  if (startedAt && !Number.isNaN(startedAt)) {
    const completedAt = telemetry?.run?.completedAt
      ? new Date(telemetry.run.completedAt).getTime()
      : null;
    const endedAt = completedAt && !Number.isNaN(completedAt)
      ? completedAt
      : Date.now();
    return formatElapsed(Math.max(0, endedAt - startedAt));
  }
  return "Starting";
}

export function buildPhasePulseSnapshot(params: {
  lifecycle: Pick<
    LifecycleWorkspaceView,
    "runtimeActivePhase" | "runtimeActivePhaseSummary" | "runtimePhaseSummary" | "runtimeLiveTelemetry" | "phaseRuns" | "phaseStatuses"
  >;
  phase: LifecyclePhase;
  team: LifecycleAgentBlueprint[];
  workflow: Pick<WorkflowRunState, "agentProgress" | "elapsedMs"> & {
    liveTelemetry?: WorkflowRunLiveTelemetry | null;
  };
  warmupTasks: string[];
}) {
  const runtimeSummary = resolvePhaseRuntimeSummary(params.lifecycle, params.phase);
  const telemetry = resolvePhaseTelemetry(
    params.lifecycle,
    params.phase,
    params.team,
    params.workflow.liveTelemetry,
  );
  const baseAgents = runtimeSummary?.agents?.length
    ? buildAgentsFromRuntimeSummary(runtimeSummary)
    : buildAgentsFromWorkflow(params.team, params.workflow.agentProgress);
  const agents = shouldApplyWarmupMotion(
    params.lifecycle,
    params.phase,
    runtimeSummary,
    telemetry,
  )
    ? applyWarmupMotion(baseAgents, params.warmupTasks)
    : baseAgents;
  return {
    agents,
    actions: buildActionsFromRuntimeSummary(runtimeSummary),
    events: buildEventsFromTelemetry(telemetry),
    elapsedLabel: resolveElapsedLabel(params.workflow, telemetry),
    runtimeSummary,
    telemetry,
  };
}
