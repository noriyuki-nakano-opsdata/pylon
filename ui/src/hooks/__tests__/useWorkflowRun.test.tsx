import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { lifecycleApi } from "@/api/lifecycle";
import type { WorkflowRun } from "@/api/workflows";
import { useWorkflowRun } from "../useWorkflowRun";

vi.mock("@/api/lifecycle", () => ({
  lifecycleApi: {
    preparePhase: vi.fn(),
    startRun: vi.fn(),
    getRun: vi.fn(),
    streamRun: vi.fn(),
    getLatestRun: vi.fn(),
  },
  lifecycleWorkflowId: (phase: string, projectSlug: string) => `lifecycle-${phase}-${projectSlug}`,
}));

describe("useWorkflowRun", () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );

  beforeEach(() => {
    vi.useRealTimers();
    vi.mocked(lifecycleApi.preparePhase).mockReset();
    vi.mocked(lifecycleApi.startRun).mockReset();
    vi.mocked(lifecycleApi.getRun).mockReset();
    vi.mocked(lifecycleApi.streamRun).mockReset();
    vi.mocked(lifecycleApi.getLatestRun).mockReset();
  });

  function makeRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
    return {
      id: "run_async_default",
      workflow_id: "lifecycle-development-opp-smoke",
      execution_mode: "async",
      project: "lifecycle-development",
      status: "completed",
      started_at: "2026-03-17T00:00:00Z",
      completed_at: "2026-03-17T00:05:00Z",
      event_log: [],
      execution_summary: {},
      ...overrides,
    };
  }

  it("reconstructs terminal telemetry from execution_summary when event_log is absent", async () => {
    vi.mocked(lifecycleApi.getLatestRun).mockResolvedValue({
      id: "run_async_design",
      workflow_id: "lifecycle-design-opp-smoke",
      execution_mode: "async",
      project: "lifecycle-design",
      status: "completed",
      started_at: "2026-03-17T00:00:00Z",
      completed_at: "2026-03-17T00:05:00Z",
      execution_summary: {
        total_events: 5,
        completedNodeCount: 5,
        last_node: "design-evaluator",
        recentNodeIds: [
          "design-evaluator",
          "gemini-preview-validator",
          "claude-preview-validator",
        ],
        node_sequence: [
          "claude-designer",
          "gemini-designer",
          "claude-preview-validator",
          "gemini-preview-validator",
          "design-evaluator",
        ],
      },
    });

    const { result } = renderHook(
      () => useWorkflowRun("design", "opp-smoke", { knownRunExists: true }),
      { wrapper },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.status).toBe("completed");
    expect(result.current.agentProgress).toHaveLength(5);
    expect(result.current.liveTelemetry.completedNodeCount).toBe(5);
    expect(result.current.liveTelemetry.lastNodeId).toBe("design-evaluator");
    expect(result.current.liveTelemetry.recentNodeIds[0]).toBe("design-evaluator");
  });

  it("adopts a newer running run even when the current run is already completed", async () => {
    vi.useFakeTimers();
    vi.mocked(lifecycleApi.streamRun).mockImplementation(() => new Promise(() => {}));

    const completedRun = makeRun({
      id: "run_async_completed",
      started_at: "2026-03-17T00:00:00Z",
      completed_at: "2026-03-17T00:05:00Z",
      status: "completed",
      execution_summary: {
        total_events: 2,
        completedNodeCount: 2,
        last_node: "integrator",
        node_sequence: ["planner", "integrator"],
      },
    });
    const newerRunningRun = makeRun({
      id: "run_async_running",
      started_at: "2026-03-17T00:06:00Z",
      completed_at: null,
      status: "running",
      execution_summary: {
        total_events: 1,
        completedNodeCount: 1,
        last_node: "planner",
        node_sequence: ["planner"],
      },
      node_status: {
        planner: "succeeded",
        "frontend-builder": "running",
      },
    });

    vi.mocked(lifecycleApi.getLatestRun).mockResolvedValue(completedRun);

    const { result } = renderHook(
      () => useWorkflowRun("development", "opp-smoke", { knownRunExists: true }),
      { wrapper },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.status).toBe("completed");
    expect(result.current.runId).toBe("run_async_completed");

    vi.mocked(lifecycleApi.getLatestRun).mockResolvedValue(newerRunningRun);

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.status).toBe("running");
    expect(result.current.runId).toBe("run_async_running");
    expect(result.current.liveTelemetry.lastNodeId).toBe("planner");
    expect(result.current.liveTelemetry.completedNodeCount).toBe(1);
  });
});
