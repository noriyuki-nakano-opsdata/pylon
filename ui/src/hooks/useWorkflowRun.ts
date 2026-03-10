import { useState, useRef, useCallback, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { lifecycleApi } from "@/api/lifecycle";
import type { WorkflowRun } from "@/api/workflows";
import type { LifecyclePhase } from "@/types/lifecycle";

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

function extractAgentProgress(data: WorkflowRun): AgentProgress[] {
  const nodeMap = new Map<string, AgentProgress>();

  // Extract from event_log
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

  // Extract from node_status (top-level) or state.execution.node_status
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

  return Array.from(nodeMap.values());
}

function isTerminal(status: string): boolean {
  return status === "completed" || status === "failed";
}

export function useWorkflowRun(phase: LifecyclePhase, projectSlug: string) {
  const [runId, setRunId] = useState<string | null>(null);
  const [hookStatus, setHookStatus] = useState<
    WorkflowRunState["status"]
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [restoredState, setRestoredState] = useState<Record<string, unknown> | null>(null);
  const [restoredProgress, setRestoredProgress] = useState<AgentProgress[] | null>(null);

  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const restoredRef = useRef(false);

  // Restore latest completed run on mount
  useEffect(() => {
    if (restoredRef.current || !projectSlug) return;
    restoredRef.current = true;

    lifecycleApi.getLatestRun(phase, projectSlug).then((run) => {
      if (!run) return;
      if (run.status === "completed" || run.status === "failed") {
        setRunId(run.id);
        setHookStatus(run.status as "completed" | "failed");
        setRestoredState((run.state ?? {}) as Record<string, unknown>);
        setRestoredProgress(extractAgentProgress(run));
      } else if (run.status === "running") {
        // Resume polling an in-progress run
        startTimeRef.current = new Date(run.started_at).getTime();
        setRunId(run.id);
        setHookStatus("running");
        setElapsedMs(Date.now() - startTimeRef.current);
      }
    });
  }, [phase, projectSlug]);

  // Elapsed-time ticker (independent of polling)
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

  // Poll the run status via react-query
  const { data: runData } = useQuery<WorkflowRun>({
    queryKey: ["workflow-run", runId],
    queryFn: () => lifecycleApi.getRun(runId!),
    enabled: runId !== null && hookStatus === "running",
    refetchInterval: 2000,
    refetchIntervalInBackground: false,
  });

  // Derive agent progress and state from the latest poll data
  const agentProgress = restoredProgress ?? (runData ? extractAgentProgress(runData) : []);
  const state = restoredState ?? ((runData?.state ?? {}) as Record<string, unknown>);

  // React to terminal status from poll data
  useEffect(() => {
    if (!runData || hookStatus !== "running") return;
    if (isTerminal(runData.status)) {
      setHookStatus(runData.status as "completed" | "failed");
      setElapsedMs(Date.now() - startTimeRef.current);
      // Clear restored data so live data takes over
      setRestoredState(null);
      setRestoredProgress(null);
    }
  }, [runData, hookStatus]);

  // Start mutation: ensure workflow + start run
  const startMutation = useMutation({
    mutationFn: async (input: Record<string, unknown>) => {
      await lifecycleApi.ensureWorkflow(phase, projectSlug);
      return lifecycleApi.startRun(phase, projectSlug, input);
    },
    onMutate: () => {
      setHookStatus("starting");
      setRunId(null);
      setError(null);
      setElapsedMs(0);
      setRestoredState(null);
      setRestoredProgress(null);
    },
    onSuccess: ({ runId: newRunId }) => {
      startTimeRef.current = Date.now();
      setRunId(newRunId);
      setHookStatus("running");
    },
    onError: (err: unknown) => {
      setHookStatus("failed");
      setError(
        err instanceof Error ? err.message : "Failed to start workflow",
      );
    },
  });

  const start = useCallback(
    (input: Record<string, unknown>) => {
      startMutation.mutate(input);
    },
    [startMutation],
  );

  const reset = useCallback(() => {
    clearInterval(timerRef.current);
    setHookStatus("idle");
    setRunId(null);
    setError(null);
    setElapsedMs(0);
    setRestoredState(null);
    setRestoredProgress(null);
  }, []);

  return {
    status: hookStatus,
    runId,
    agentProgress,
    state,
    error,
    elapsedMs,
    start,
    reset,
  };
}
