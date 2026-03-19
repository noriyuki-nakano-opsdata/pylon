import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLifecycleRuntimeStream } from "../useLifecycleRuntimeStream";
import { lifecycleApi } from "@/api/lifecycle";

vi.mock("@/api/lifecycle", () => ({
  lifecycleApi: {
    streamProjectEvents: vi.fn(),
  },
}));

describe("useLifecycleRuntimeStream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(lifecycleApi.streamProjectEvents).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops reconnecting after a terminal phase event", async () => {
    vi.mocked(lifecycleApi.streamProjectEvents).mockImplementation(
      async (_projectSlug, _phase, options) => {
        options.onEvent({
          event: "project-runtime",
          data: JSON.stringify({
            updatedAt: "2026-03-17T00:05:00Z",
            savedAt: "2026-03-17T00:05:00Z",
            phaseStatuses: [],
            nextAction: null,
            autonomyState: null,
            observedPhase: "design",
            activePhase: "design",
            phaseSummary: {
              phase: "design",
              status: "completed",
              blockingSummary: [],
              agents: [],
              recentActions: [],
            },
            activePhaseSummary: {
              phase: "design",
              status: "completed",
              blockingSummary: [],
              agents: [],
              recentActions: [],
            },
          }),
        });
        options.onEvent({
          event: "run-live",
          data: JSON.stringify({
            run: {
              id: "run_1",
              status: "completed",
              startedAt: "2026-03-17T00:00:00Z",
              completedAt: "2026-03-17T00:05:00Z",
            },
            phase: "design",
            eventCount: 5,
            completedNodeCount: 5,
            runningNodeIds: [],
            failedNodeIds: [],
            lastEventSeq: 5,
            lastNodeId: "design-evaluator",
            recentNodeIds: ["design-evaluator"],
            recentEvents: [],
          }),
        });
        options.onEvent({
          event: "phase-terminal",
          data: JSON.stringify({
            projectId: "opp-smoke",
            phase: "design",
            runId: "run_1",
            status: "completed",
          }),
        });
      },
    );

    const { result } = renderHook(() => useLifecycleRuntimeStream("opp-smoke", "design", true));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.terminalEvent?.runId).toBe("run_1");

    await act(async () => {
      vi.advanceTimersByTime(2500);
      await Promise.resolve();
    });

    expect(lifecycleApi.streamProjectEvents).toHaveBeenCalledTimes(1);
    expect(result.current.connectionState).toBe("live");
    expect(result.current.liveTelemetry?.completedNodeCount).toBe(5);
  });
});
