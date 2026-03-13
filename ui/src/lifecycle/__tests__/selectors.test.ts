import { describe, expect, it } from "vitest";
import {
  defaultResearchConfig,
  defaultStatuses,
} from "@/lifecycle/store";
import {
  selectApprovalViewModel,
  selectCompletedPhaseCount,
  selectDevelopmentViewModel,
  selectDeploySummary,
  selectPhaseStatus,
  selectPlanningAnalysis,
  selectPlanningReviewViewModel,
  selectPlanningViewModel,
  selectResearchProgressState,
  selectResearchReadinessState,
  selectResearchRuntimeSummary,
  selectResearchRuntimeTelemetry,
  selectSelectedDesign,
  selectSelectedFeatureCount,
  selectSelectedFeatures,
  selectSortedFeedbackItems,
} from "@/lifecycle/selectors";
import type { WorkflowRunState } from "@/hooks/useWorkflowRun";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type { MarketResearch } from "@/types/lifecycle";

function makeLifecycleState(
  overrides: Partial<LifecycleWorkspaceView> = {},
): LifecycleWorkspaceView {
  return {
    spec: "",
    orchestrationMode: "workflow",
    autonomyLevel: "A3",
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
    phaseStatuses: defaultStatuses(),
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
    runtimeObservedPhase: "research",
    runtimeActivePhase: null,
    runtimePhaseSummary: null,
    runtimeActivePhaseSummary: null,
    runtimeLiveTelemetry: null,
    runtimeConnectionState: "inactive",
    blueprints: {
      research: { phase: "research", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      planning: { phase: "planning", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      design: { phase: "design", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      approval: { phase: "approval", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      development: { phase: "development", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      deploy: { phase: "deploy", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      iterate: { phase: "iterate", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    },
    isHydrating: false,
    ...overrides,
  };
}

describe("lifecycle selectors", () => {
  it("selects phase status and research runtime sources", () => {
    const lifecycle = makeLifecycleState({
      runtimeActivePhase: "research",
      runtimeActivePhaseSummary: {
        phase: "research",
        status: "in_progress",
        readiness: "rework",
        objective: "Collect vendor evidence",
        nextAutomaticAction: "Retry competitor analysis",
        blockingSummary: [],
        failedGateCount: 1,
        degradedNodeCount: 2,
        canAutorun: true,
        attemptCount: 1,
        maxAttempts: 2,
        agents: [],
        recentActions: [],
      },
      runtimeLiveTelemetry: {
        phase: "research",
        run: {
          id: "run_1",
          status: "running",
          startedAt: "2026-03-13T00:00:00.000Z",
          completedAt: null,
          error: undefined,
        },
        eventCount: 3,
        completedNodeCount: 1,
        runningNodeIds: ["market-researcher"],
        failedNodeIds: [],
        lastEventSeq: 3,
        activeFocusNodeId: "market-researcher",
        lastNodeId: "market-researcher",
        lastAgent: "market-researcher",
        recentNodeIds: ["market-researcher"],
        recentEvents: [],
      },
    });

    expect(selectPhaseStatus(lifecycle.phaseStatuses, "research")).toBe("available");
    expect(selectResearchRuntimeSummary(lifecycle)?.phase).toBe("research");
    expect(selectResearchRuntimeTelemetry(lifecycle)?.run?.id).toBe("run_1");
  });

  it("computes research progress from runtime summary and workflow state", () => {
    const workflow: WorkflowRunState = {
      status: "running",
      runId: "run_1",
      agentProgress: [],
      state: {},
      error: null,
      elapsedMs: 0,
    };
    const result = selectResearchProgressState({
      workflow,
      runtimeSummary: {
        phase: "research",
        status: "in_progress",
        readiness: "rework",
        objective: "Collect evidence",
        nextAutomaticAction: "Retry",
        blockingSummary: [],
        failedGateCount: 1,
        degradedNodeCount: 1,
        canAutorun: true,
        attemptCount: 1,
        maxAttempts: 2,
        agents: [
          {
            agentId: "market-researcher",
            label: "市場調査",
            role: "Researcher",
            currentTask: "Collecting evidence",
            status: "running",
          },
        ],
        recentActions: [],
      },
      runtimeTelemetry: {
        phase: "research",
        run: {
          id: "run_1",
          status: "running",
          startedAt: "2026-03-13T00:00:00.000Z",
          completedAt: null,
          error: undefined,
        },
        eventCount: 2,
        completedNodeCount: 0,
        runningNodeIds: ["market-researcher"],
        failedNodeIds: [],
        lastEventSeq: 2,
        activeFocusNodeId: "market-researcher",
        lastNodeId: "market-researcher",
        lastAgent: "market-researcher",
        recentNodeIds: ["market-researcher"],
        recentEvents: [],
      },
      isPreparing: false,
      nowMs: new Date("2026-03-13T00:00:05.000Z").getTime(),
    });

    expect(result.isRunning).toBe(true);
    expect(result.isInitialResearchRun).toBe(true);
    expect(result.totalSteps).toBe(1);
    expect(result.completedSteps).toBe(0);
    expect(result.runtimeRunningNodes).toEqual(["market-researcher"]);
  });

  it("detects research readiness and autonomous recovery", () => {
    const research: MarketResearch = {
      competitors: [],
      market_size: "large",
      trends: [],
      opportunities: [],
      threats: [],
      tech_feasibility: { score: 0.8, notes: "good" },
      winning_theses: [],
      source_links: [],
      evidence: [],
      dissent: [
        {
          id: "d1",
          claim_id: "c1",
          challenger: "judge",
          argument: "weak",
          severity: "critical",
          resolved: false,
        },
      ],
      autonomous_remediation: {
        status: "retrying",
        attemptCount: 1,
        maxAttempts: 2,
        remainingAttempts: 1,
        objective: "Recover evidence",
        retryNodeIds: ["competitor-analyst"],
        blockingGateIds: ["source-grounding"],
      },
    };

    const result = selectResearchReadinessState({
      research,
      phaseStatus: "completed",
      nextAction: {
        type: "run_phase",
        phase: "research",
        title: "retry",
        reason: "quality gate",
        canAutorun: true,
        payload: {},
      },
    });

    expect(result.researchReady).toBe(false);
    expect(result.isAutonomousRecoveryActive).toBe(true);
    expect(result.criticalDissentCount).toBe(1);
    expect(result.gateIssues.length).toBeGreaterThan(0);
  });

  it("derives selected design, selected features, completed phases, and feedback order", () => {
    const lifecycle = makeLifecycleState({
      selectedDesignId: "design_2",
      designVariants: [
        {
          id: "design_1",
          model: "model-a",
          pattern_name: "Pattern A",
          description: "A",
          preview_html: "<div />",
          tokens: { in: 10, out: 20 },
          scores: { ux_quality: 7, code_quality: 7, performance: 7, accessibility: 7 },
          cost_usd: 0.1,
        },
        {
          id: "design_2",
          model: "model-b",
          pattern_name: "Pattern B",
          description: "B",
          preview_html: "<div />",
          tokens: { in: 12, out: 22 },
          scores: { ux_quality: 9, code_quality: 8, performance: 8, accessibility: 8 },
          cost_usd: 0.2,
        },
      ],
      features: [
        { feature: "A", selected: true, rationale: "", priority: "must", category: "must-be", user_delight: 8, implementation_cost: "medium" },
        { feature: "B", selected: false, rationale: "", priority: "could", category: "attractive", user_delight: 6, implementation_cost: "low" },
      ],
      phaseStatuses: defaultStatuses().map((item, index) => ({
        ...item,
        status: index < 2 ? "completed" : item.status,
      })),
      feedbackItems: [
        { id: "f1", text: "low", type: "improvement", impact: "low", votes: 1, createdAt: "2026-03-13T00:00:00.000Z" },
        { id: "f2", text: "high", type: "feature", impact: "high", votes: 4, createdAt: "2026-03-13T00:01:00.000Z" },
      ],
    });

    expect(selectSelectedDesign(lifecycle)?.id).toBe("design_2");
    expect(selectSelectedFeatureCount(lifecycle)).toBe(1);
    expect(selectSelectedFeatures(lifecycle)).toHaveLength(1);
    expect(selectCompletedPhaseCount(lifecycle)).toBe(2);
    expect(selectSortedFeedbackItems(lifecycle).map((item) => item.id)).toEqual(["f2", "f1"]);
  });

  it("summarizes deploy state", () => {
    const lifecycle = makeLifecycleState({
      deployChecks: [
        { id: "c1", label: "A", detail: "ok", status: "pass" },
        { id: "c2", label: "B", detail: "warn", status: "warning" },
      ],
      releases: [
        {
          id: "r1",
          version: "v1.0.0",
          createdAt: "2026-03-13T00:00:00.000Z",
          note: "ship",
          artifactBytes: 2048,
          qualitySummary: { overallScore: 88, releaseReady: true, passed: 1, warnings: 1, failed: 0 },
        },
      ],
    });

    const result = selectDeploySummary(lifecycle);

    expect(result.allPassed).toBe(true);
    expect(result.deployed).toBe(true);
    expect(result.latestRelease?.version).toBe("v1.0.0");
    expect(result.passedCount).toBe(1);
    expect(result.warningCount).toBe(1);
    expect(result.failedCount).toBe(0);
  });

  it("builds planning, approval, and development view models", () => {
    const lifecycle = makeLifecycleState({
      spec: "Factory workflow",
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [],
      },
      selectedDesignId: "design_2",
      designVariants: [
        {
          id: "design_2",
          model: "model-b",
          pattern_name: "Pattern B",
          description: "B",
          preview_html: "<div />",
          tokens: { in: 12, out: 22 },
          scores: { ux_quality: 9, code_quality: 8, performance: 8, accessibility: 8 },
          cost_usd: 0.2,
        },
      ],
      features: [
        { feature: "A", selected: true, rationale: "", priority: "must", category: "must-be", user_delight: 8, implementation_cost: "medium" },
      ],
      milestones: [
        { id: "m1", name: "Release", criteria: "ship", status: "pending" },
      ],
    });

    const planning = selectPlanningAnalysis(lifecycle);
    const planningVm = selectPlanningViewModel(lifecycle);
    const planningReview = selectPlanningReviewViewModel(planning);
    const approval = selectApprovalViewModel(lifecycle);
    const development = selectDevelopmentViewModel({
      approvalStatus: "approved",
      blueprints: lifecycle.blueprints,
      designVariants: lifecycle.designVariants,
      milestones: lifecycle.milestones,
      selectedDesignId: lifecycle.selectedDesignId,
      features: lifecycle.features,
    });

    expect(planning.personas).toEqual([]);
    expect(planningVm.initialStep).toBe("review");
    expect(planningVm.canRunAnalysis).toBe(true);
    expect(planningReview.reviewTabs.find((tab) => tab.key === "journey")?.hidden).toBe(true);
    expect(planningReview.overviewStats.find((item) => item.label === "推奨事項")?.value).toBe(0);
    expect(approval.allChecked).toBe(true);
    expect(approval.completedChecklistCount).toBe(5);
    expect(development.canStartBuild).toBe(true);
    expect(development.maxIterations).toBe(5);
    expect(development.buildTeam.length).toBeGreaterThan(0);
  });
});
