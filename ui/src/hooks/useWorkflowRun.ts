import { useState, useRef, useCallback, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { lifecycleApi, lifecycleWorkflowId } from "@/api/lifecycle";
import type { WorkflowRun } from "@/api/workflows";
import type { LifecyclePhase, WorkflowRunLiveEvent, WorkflowRunLiveTelemetry } from "@/types/lifecycle";

export interface AgentProgress {
  nodeId: string;
  agent: string;
  status: "pending" | "running" | "completed" | "failed";
  output?: unknown;
}

export interface WorkflowRunState {
  status: "idle" | "starting" | "running" | "completed" | "failed";
  runId: string | null;
  agentProgress: AgentProgress[];
  state: Record<string, unknown>;
  error: string | null;
  elapsedMs: number;
}

interface UseWorkflowRunOptions {
  enabled?: boolean;
  observeOnly?: boolean;
  knownRunExists?: boolean;
}

const RUN_RECONCILE_INTERVAL_MS = 5000;
const START_GRACE_PERIOD_MS = 10000;

function executionSummaryRecord(
  run: WorkflowRun | null | undefined,
): Record<string, unknown> {
  return run?.execution_summary && typeof run.execution_summary === "object"
    ? run.execution_summary as Record<string, unknown>
    : {};
}

function executionSummaryStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item ?? "").trim())
    .filter((item) => item.length > 0);
}

function executionSummaryNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : null;
}

function runNodeSequence(run: WorkflowRun | null | undefined): string[] {
  const summary = executionSummaryRecord(run);
  return executionSummaryStringList(summary.node_sequence ?? summary.nodeSequence);
}

function extractAgentProgress(data: WorkflowRun): AgentProgress[] {
  const nodeMap = new Map<string, AgentProgress>();

  if (data.event_log) {
    for (const evt of data.event_log) {
      nodeMap.set(evt.node_id, {
        nodeId: evt.node_id,
        agent: evt.agent,
        status: "completed",
        output: evt.output,
      });
    }
  }

  const nodeStatus =
    data.node_status ??
    (
      (data.state?.execution as Record<string, unknown> | undefined)
        ?.node_status as Record<string, string> | undefined
    );

  if (nodeStatus) {
    for (const [nodeId, status] of Object.entries(nodeStatus)) {
      const mapped: AgentProgress["status"] =
        status === "succeeded"
          ? "completed"
          : status === "failed"
            ? "failed"
            : status === "running"
              ? "running"
              : "pending";
      if (!nodeMap.has(nodeId)) {
        nodeMap.set(nodeId, { nodeId, agent: nodeId, status: mapped });
      } else {
        nodeMap.get(nodeId)!.status = mapped;
      }
    }
  }

  for (const nodeId of runNodeSequence(data)) {
    if (!nodeMap.has(nodeId)) {
      nodeMap.set(nodeId, {
        nodeId,
        agent: nodeId,
        status: "completed",
      });
    }
  }

  return Array.from(nodeMap.values());
}

function isTerminal(status: string): boolean {
  return status === "completed" || status === "failed";
}

function extractRunError(run: WorkflowRun): string | null {
  if (typeof run.error === "string" && run.error.trim()) {
    return run.error;
  }
  const stateError = (run.state as Record<string, unknown> | undefined)?.error;
  return typeof stateError === "string" && stateError.trim()
    ? stateError
    : null;
}

function runTimestampMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? null : timestamp;
}

function computeElapsedMs(run: WorkflowRun): number {
  const startedAt = runTimestampMs(run.started_at);
  if (startedAt === null) return 0;
  const endedAt = isTerminal(run.status)
    ? runTimestampMs(run.completed_at) ?? startedAt
    : Date.now();
  return Math.max(0, endedAt - startedAt);
}

function isNewerRun(candidate: WorkflowRun, current: WorkflowRun | null): boolean {
  if (!current) return true;
  const candidateStartedAt = runTimestampMs(candidate.started_at) ?? 0;
  const currentStartedAt = runTimestampMs(current.started_at) ?? 0;
  if (candidateStartedAt !== currentStartedAt) {
    return candidateStartedAt > currentStartedAt;
  }
  return candidate.id !== current.id;
}

function shouldAdoptLatestRun(
  candidate: WorkflowRun,
  current: WorkflowRun | null,
  hookStatus: WorkflowRunState["status"],
): boolean {
  if (!current) {
    return true;
  }
  if (!isNewerRun(candidate, current)) {
    return false;
  }
  if (hookStatus === "running" || hookStatus === "starting") {
    return true;
  }
  if (candidate.status === "running") {
    return true;
  }
  return isTerminal(candidate.status);
}

function runSignature(run: WorkflowRun | null | undefined): string {
  if (!run) return "";
  const execution = (run.state?.execution as Record<string, unknown> | undefined) ?? {};
  const summary = executionSummaryRecord(run);
  return JSON.stringify({
    status: run.status,
    completedAt: run.completed_at ?? null,
    error: extractRunError(run),
    eventCount:
      run.event_log?.length
      ?? executionSummaryNumber(summary.eventCount)
      ?? executionSummaryNumber(summary.total_events)
      ?? 0,
    lastEventSeq:
      executionSummaryNumber(summary.lastEventSeq)
      ?? executionSummaryNumber(summary.eventCount)
      ?? executionSummaryNumber(summary.total_events)
      ?? null,
    lastNode: String(summary.lastNodeId ?? summary.last_node ?? ""),
    nodeStatus:
      run.node_status
      ?? (execution.node_status as Record<string, unknown> | undefined)
      ?? {},
  });
}

function hasMeaningfulRunUpdate(
  candidate: WorkflowRun,
  current: WorkflowRun | null,
): boolean {
  if (!current) return true;
  return runSignature(candidate) !== runSignature(current);
}

function toLiveTelemetry(run: WorkflowRun | null, agentProgress: AgentProgress[]): WorkflowRunLiveTelemetry {
  const summary = executionSummaryRecord(run);
  const nodeSequence = runNodeSequence(run);
  const fallbackRecentNodeIds = executionSummaryStringList(summary.recentNodeIds);
  const lastEventSeq = run?.event_log && run.event_log.length > 0
    ? run.event_log[run.event_log.length - 1]?.seq ?? null
    : executionSummaryNumber(summary.lastEventSeq)
      ?? executionSummaryNumber(summary.eventCount)
      ?? executionSummaryNumber(summary.total_events);
  const recentNodeIds = run?.event_log && run.event_log.length > 0
    ? Array.from(new Set(
        [...run.event_log]
          .reverse()
          .map((event) => event.node_id)
          .filter(Boolean),
      )).slice(0, 3)
    : fallbackRecentNodeIds.length > 0
      ? fallbackRecentNodeIds
      : Array.from(new Set([...nodeSequence].reverse())).slice(0, 3);
  const lastEvent = run?.event_log && run.event_log.length > 0
    ? run.event_log[run.event_log.length - 1]
    : null;
  const summaryLastNodeId = String(
    summary.lastNodeId
      ?? summary.last_node
      ?? nodeSequence.at(-1)
      ?? "",
  ).trim() || undefined;
  const activeFocusNodeId = agentProgress.find((item) => item.status === "running")?.nodeId
    ?? lastEvent?.node_id
    ?? summaryLastNodeId;
  const recentEvents: WorkflowRunLiveEvent[] = [...(run?.event_log ?? [])]
    .slice(-5)
    .reverse()
    .map((event) => ({
      seq: typeof event.seq === "number" ? event.seq : null,
      timestamp: typeof event.timestamp === "string" ? event.timestamp : undefined,
      nodeId: event.node_id,
      agent: typeof event.agent === "string" ? event.agent : undefined,
      status:
        agentProgress.find((item) => item.nodeId === event.node_id)?.status
        ?? "completed",
      summary: typeof event.agent === "string" && event.agent.trim()
        ? `${event.agent} finished ${event.node_id}`
        : `${event.node_id} finished`,
    }));
  const fallbackRecentEvents = recentEvents.length > 0
    ? recentEvents
    : [...nodeSequence]
      .reverse()
      .reduce<WorkflowRunLiveEvent[]>((events, nodeId, index) => {
        if (!nodeId || events.some((event) => event.nodeId === nodeId)) {
          return events;
        }
        events.push({
          seq: lastEventSeq !== null ? Math.max(lastEventSeq - index, 1) : null,
          nodeId,
          status:
            agentProgress.find((item) => item.nodeId === nodeId)?.status
            ?? "completed",
          summary: `${nodeId} finished ${nodeId}`,
        });
        return events;
      }, [])
      .slice(0, 5);
  const completedNodeCount = agentProgress.filter((item) => item.status === "completed").length
    || executionSummaryNumber(summary.completedNodeCount)
    || new Set(nodeSequence).size;
  const eventCount = run?.event_log?.length
    ?? executionSummaryNumber(summary.eventCount)
    ?? executionSummaryNumber(summary.total_events)
    ?? nodeSequence.length;
  return {
    run: run
      ? {
          id: run.id,
          status: run.status,
          startedAt: run.started_at,
          completedAt: run.completed_at,
          error: run.error,
        }
      : null,
    eventCount,
    completedNodeCount,
    runningNodeIds: agentProgress.filter((item) => item.status === "running").map((item) => item.nodeId),
    failedNodeIds: agentProgress.filter((item) => item.status === "failed").map((item) => item.nodeId),
    lastEventSeq,
    activeFocusNodeId,
    lastNodeId: lastEvent?.node_id ?? summaryLastNodeId,
    lastAgent: lastEvent?.agent,
    recentNodeIds,
    recentEvents: fallbackRecentEvents,
  };
}

export function useWorkflowRun(
  phase: LifecyclePhase,
  projectSlug: string,
  options: UseWorkflowRunOptions = {},
) {
  const workflowId = lifecycleWorkflowId(phase, projectSlug);
  const enabled = options.enabled ?? true;
  const observeOnly = options.observeOnly ?? false;
  const knownRunExists = options.knownRunExists ?? true;
  const [runId, setRunId] = useState<string | null>(null);
  const [hookStatus, setHookStatus] = useState<WorkflowRunState["status"]>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [liveRun, setLiveRun] = useState<WorkflowRun | null>(null);

  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const restoredRef = useRef(false);
  const pendingStartAtRef = useRef<number | null>(null);

  useEffect(() => {
    restoredRef.current = false;
    pendingStartAtRef.current = null;
    setRunId(null);
    setHookStatus("idle");
    setError(null);
    setElapsedMs(0);
    setLiveRun(null);
  }, [enabled, workflowId]);

  const applyRunSnapshot = useCallback((run: WorkflowRun) => {
    setLiveRun(run);
    setRunId(run.id);
    if (run.status === "running") {
      startTimeRef.current = runTimestampMs(run.started_at) ?? Date.now();
      setHookStatus("running");
      setError(null);
      setElapsedMs(computeElapsedMs(run));
      return;
    }
    if (isTerminal(run.status)) {
      pendingStartAtRef.current = null;
      startTimeRef.current = 0;
      setHookStatus(run.status as "completed" | "failed");
      setError(run.status === "failed" ? extractRunError(run) : null);
      setElapsedMs(computeElapsedMs(run));
      return;
    }
    setHookStatus("idle");
    setError(null);
    setElapsedMs(0);
  }, []);

  useEffect(() => {
    const shouldRestoreLatestRun =
      knownRunExists
      || observeOnly
      || runId !== null
      || hookStatus === "starting"
      || hookStatus === "running";
    if (restoredRef.current || !projectSlug || !enabled || !shouldRestoreLatestRun) return;
    restoredRef.current = true;
    let cancelled = false;

    lifecycleApi.getLatestRun(workflowId).then((run) => {
      if (cancelled || !run) return;
      applyRunSnapshot(run);
    });

    return () => {
      cancelled = true;
    };
  }, [applyRunSnapshot, enabled, hookStatus, knownRunExists, observeOnly, projectSlug, runId, workflowId]);

  useEffect(() => {
    if (hookStatus !== "running") {
      clearInterval(timerRef.current);
      return;
    }
    timerRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startTimeRef.current);
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, [hookStatus]);

  useEffect(() => {
    if (!enabled || !runId) return;
    if (!observeOnly && hookStatus !== "running") return;
    let active = true;
    let reconnectTimer: number | null = null;
    let controller: AbortController | null = null;

    const connect = async () => {
      while (active) {
        controller = new AbortController();
        try {
          await lifecycleApi.streamRun(runId, {
            signal: controller.signal,
            onEvent: ({ event, data }) => {
              if ((event !== "snapshot" && event !== "run") || !data) return;
              const payload = JSON.parse(data) as WorkflowRun;
              setLiveRun(payload);
            },
          });
        } catch (streamError) {
          if (!active || controller.signal.aborted) break;
          console.debug("Workflow run stream disconnected", streamError);
        }
        if (!active) break;
        try {
          const refreshedRun = await lifecycleApi.getRun(runId);
          setLiveRun(refreshedRun);
          if (isTerminal(refreshedRun.status)) {
            break;
          }
        } catch {
          // Ignore transient fallback fetch failures and retry the stream.
        }
        await new Promise<void>((resolve) => {
          reconnectTimer = window.setTimeout(resolve, 1000);
        });
      }
    };

    void connect();
    return () => {
      active = false;
      controller?.abort();
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
    };
  }, [enabled, hookStatus, observeOnly, runId]);

  useEffect(() => {
    if (!enabled || !projectSlug) return;
    const shouldLookupLatestRun =
      knownRunExists
      || observeOnly
      || runId !== null
      || hookStatus === "starting"
      || hookStatus === "running";
    if (!shouldLookupLatestRun) return;
    let cancelled = false;

    const reconcile = async () => {
      const pendingStartAt = pendingStartAtRef.current;
      if (
        pendingStartAt !== null
        && runId === null
        && Date.now() - pendingStartAt < START_GRACE_PERIOD_MS
      ) {
        return;
      }
      const latestRun = await lifecycleApi.getLatestRun(workflowId);
      if (cancelled || !latestRun) return;
      if (runId === null) {
        applyRunSnapshot(latestRun);
        return;
      }
      if (latestRun.id === runId) {
        if (!liveRun || hasMeaningfulRunUpdate(latestRun, liveRun)) {
          applyRunSnapshot(latestRun);
        }
        return;
      }
      if (shouldAdoptLatestRun(latestRun, liveRun, hookStatus)) {
        applyRunSnapshot(latestRun);
      }
    };

    void reconcile();
    const timer = window.setInterval(() => {
      void reconcile();
    }, RUN_RECONCILE_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [applyRunSnapshot, enabled, hookStatus, knownRunExists, liveRun, observeOnly, projectSlug, runId, workflowId]);

  const agentProgress = liveRun ? extractAgentProgress(liveRun) : [];
  const state = (liveRun?.state ?? {}) as Record<string, unknown>;

  useEffect(() => {
    if (!liveRun) return;
    if (liveRun.status === "running") {
      pendingStartAtRef.current = null;
      startTimeRef.current = runTimestampMs(liveRun.started_at) ?? Date.now();
      setHookStatus("running");
      setElapsedMs(computeElapsedMs(liveRun));
      return;
    }
    if (!isTerminal(liveRun.status)) return;
    pendingStartAtRef.current = null;
    startTimeRef.current = 0;
    setHookStatus(liveRun.status as "completed" | "failed");
    setError(liveRun.status === "failed" ? extractRunError(liveRun) : null);
    setElapsedMs(computeElapsedMs(liveRun));
  }, [liveRun]);

  const startMutation = useMutation({
    mutationFn: async (input: Record<string, unknown>) => {
      const preparation = await lifecycleApi.preparePhase(phase, projectSlug);
      return lifecycleApi.startRun(preparation.workflow_id, input);
    },
    onMutate: () => {
      if (observeOnly) return;
      pendingStartAtRef.current = Date.now();
      setHookStatus("starting");
      setRunId(null);
      setError(null);
      setElapsedMs(0);
      setLiveRun(null);
    },
    onSuccess: ({ runId: newRunId }) => {
      if (observeOnly) return;
      startTimeRef.current = Date.now();
      setRunId(newRunId);
      setHookStatus("running");
    },
    onError: (err: unknown) => {
      if (observeOnly) return;
      pendingStartAtRef.current = null;
      setHookStatus("failed");
      setError(
        err instanceof Error ? err.message : "Failed to start workflow",
      );
    },
  });

  const start = useCallback(
    (input: Record<string, unknown>) => {
      if (observeOnly) return;
      startMutation.mutate(input);
    },
    [observeOnly, startMutation],
  );

  const reset = useCallback(() => {
    clearInterval(timerRef.current);
    pendingStartAtRef.current = null;
    startTimeRef.current = 0;
    setHookStatus("idle");
    setRunId(null);
    setError(null);
    setElapsedMs(0);
    setLiveRun(null);
  }, []);

  return {
    status: hookStatus,
    runId,
    agentProgress,
    state,
    error,
    elapsedMs,
    liveTelemetry: toLiveTelemetry(liveRun, agentProgress),
    start,
    reset,
  };
}
