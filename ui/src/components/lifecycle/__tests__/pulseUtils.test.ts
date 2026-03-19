import { describe, expect, it } from "vitest";
import { buildPhasePulseSnapshot } from "@/components/lifecycle/pulseUtils";
import { defaultProductIdentity } from "@/lifecycle/productIdentity";
import { defaultResearchConfig, defaultStatuses } from "@/lifecycle/store";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type { LifecycleAgentBlueprint, WorkflowRunLiveTelemetry } from "@/types/lifecycle";

const DESIGN_TEAM: LifecycleAgentBlueprint[] = [
  { id: "claude-designer", label: "Concept Designer A", role: "案出し", autonomy: "A2", tools: [], skills: [] },
  { id: "gemini-designer", label: "Concept Designer B (KIMI)", role: "案出し", autonomy: "A2", tools: [], skills: [] },
  { id: "claude-preview-validator", label: "Preview Validator A", role: "検証", autonomy: "A2", tools: [], skills: [] },
  { id: "gemini-preview-validator", label: "Preview Validator B", role: "検証", autonomy: "A2", tools: [], skills: [] },
  { id: "design-evaluator", label: "Design Judge", role: "評価", autonomy: "A2", tools: [], skills: [] },
];

function makeLifecycleState(
  overrides: Partial<LifecycleWorkspaceView> = {},
): LifecycleWorkspaceView {
  return {
    spec: "",
    orchestrationMode: "workflow",
    autonomyLevel: "A3",
    productIdentity: {
      ...defaultProductIdentity(),
      companyName: "Pylon Labs",
      productName: "Pylon",
    },
    researchConfig: defaultResearchConfig(),
    research: null,
    analysis: null,
    features: [],
    milestones: [],
    designVariants: [],
    selectedDesignId: null,
    approvalStatus: "pending",
    approvalComments: [],
    buildCode: null,
    buildCost: 0,
    buildIteration: 0,
    milestoneResults: [],
    planEstimates: [],
    selectedPreset: "standard",
    phaseStatuses: defaultStatuses().map((status) => (
      status.phase === "design"
        ? { ...status, status: "completed", completedAt: "2026-03-17T00:05:00Z" }
        : status
    )),
    deployChecks: [],
    releases: [],
    feedbackItems: [],
    recommendations: [],
    artifacts: [],
    decisionLog: [],
    skillInvocations: [],
    delegations: [],
    phaseRuns: [],
    nextAction: null,
    autonomyState: null,
    runtimeObservedPhase: "design",
    runtimeActivePhase: null,
    runtimePhaseSummary: null,
    runtimeActivePhaseSummary: null,
    runtimeLiveTelemetry: null,
    runtimeConnectionState: "inactive",
    blueprints: {
      research: { phase: "research", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      planning: { phase: "planning", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      design: { phase: "design", title: "", summary: "", team: DESIGN_TEAM, artifacts: [], quality_gates: [] },
      approval: { phase: "approval", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      development: { phase: "development", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      deploy: { phase: "deploy", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      iterate: { phase: "iterate", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    },
    isHydrating: false,
    ...overrides,
  };
}

describe("buildPhasePulseSnapshot", () => {
  it("reconstructs terminal telemetry from persisted phase runs using execution summary", () => {
    const lifecycle = makeLifecycleState({
      phaseRuns: [
        {
          id: "run_async_design",
          runId: "run_async_design",
          projectId: "opp-smoke",
          phase: "design",
          workflowId: "lifecycle-design-opp-smoke",
          status: "completed",
          startedAt: "2026-03-17T00:00:00Z",
          completedAt: "2026-03-17T00:05:00Z",
          createdAt: "2026-03-17T00:05:00Z",
          artifactCount: 10,
          decisionCount: 1,
          costUsd: 0.42,
          executionSummary: {
            total_events: 5,
            completedNodeCount: 5,
            lastNodeId: "design-evaluator",
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
        },
      ],
    });

    const pulse = buildPhasePulseSnapshot({
      lifecycle,
      phase: "design",
      team: DESIGN_TEAM,
      workflow: {
        agentProgress: [],
        elapsedMs: 0,
        liveTelemetry: null,
      },
      warmupTasks: [],
    });

    expect(pulse.telemetry?.completedNodeCount).toBe(5);
    expect(pulse.telemetry?.lastNodeId).toBe("design-evaluator");
    expect(pulse.telemetry?.recentEvents[0]?.summary).toBe("Design Judge が完了");
  });

  it("prefers workflow telemetry over incomplete persisted phase run summaries", () => {
    const workflowTelemetry: WorkflowRunLiveTelemetry = {
      phase: "design",
      run: {
        id: "run_async_design",
        status: "completed",
        startedAt: "2026-03-17T00:00:00Z",
        completedAt: "2026-03-17T00:05:00Z",
      },
      eventCount: 5,
      completedNodeCount: 5,
      runningNodeIds: [],
      failedNodeIds: [],
      lastEventSeq: 5,
      lastNodeId: "design-evaluator",
      recentNodeIds: ["design-evaluator", "gemini-preview-validator"],
      recentEvents: [],
    };
    const lifecycle = makeLifecycleState({
      phaseRuns: [
        {
          id: "run_async_design",
          runId: "run_async_design",
          projectId: "opp-smoke",
          phase: "design",
          workflowId: "lifecycle-design-opp-smoke",
          status: "completed",
          startedAt: "2026-03-17T00:00:00Z",
          completedAt: "2026-03-17T00:05:00Z",
          createdAt: "2026-03-17T00:05:00Z",
          artifactCount: 10,
          decisionCount: 1,
          costUsd: 0.42,
          executionSummary: {},
        },
      ],
    });

    const pulse = buildPhasePulseSnapshot({
      lifecycle,
      phase: "design",
      team: DESIGN_TEAM,
      workflow: {
        agentProgress: [],
        elapsedMs: 0,
        liveTelemetry: workflowTelemetry,
      },
      warmupTasks: [],
    });

    expect(pulse.telemetry?.completedNodeCount).toBe(5);
    expect(pulse.telemetry?.lastNodeId).toBe("design-evaluator");
  });

  it("does not apply warmup motion to completed phases while runtime details are still restoring", () => {
    const lifecycle = makeLifecycleState({
      phaseRuns: [
        {
          id: "run_async_design",
          runId: "run_async_design",
          projectId: "opp-smoke",
          phase: "design",
          workflowId: "lifecycle-design-opp-smoke",
          status: "completed",
          startedAt: "2026-03-17T00:00:00Z",
          completedAt: "2026-03-17T00:05:00Z",
          createdAt: "2026-03-17T00:05:00Z",
          artifactCount: 10,
          decisionCount: 1,
          costUsd: 0.42,
          executionSummary: {},
        },
      ],
    });

    const pulse = buildPhasePulseSnapshot({
      lifecycle,
      phase: "design",
      team: DESIGN_TEAM,
      workflow: {
        agentProgress: [],
        elapsedMs: 0,
        liveTelemetry: null,
      },
      warmupTasks: ["warmup-a", "warmup-b"],
    });

    expect(pulse.agents.every((agent) => agent.status !== "running")).toBe(true);
    expect(pulse.agents[0]?.currentTask).not.toBe("warmup-a");
  });
});
