import { describe, expect, it } from "vitest";
import {
  buildApprovalPayload,
  buildDesignWorkflowInput,
  buildDevelopmentWorkflowInput,
  buildFeedbackPayload,
  buildPlanningWorkflowInput,
  buildResearchProjectPatch,
  buildResearchWorkflowInput,
} from "@/lifecycle/inputs";
import { defaultResearchConfig } from "@/lifecycle/store";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";

function makeView(overrides: Partial<LifecycleWorkspaceView> = {}): LifecycleWorkspaceView {
  return {
    spec: "Spec",
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
    phaseStatuses: [],
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
    runtimeObservedPhase: null,
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

describe("lifecycle input builders", () => {
  it("builds research save and workflow payloads from normalized config", () => {
    const view = makeView({ spec: "  Brief  " });
    const config = {
      competitorUrls: ["https://example.com"],
      depth: "deep" as const,
      outputLanguage: "ja",
    };

    expect(buildResearchProjectPatch(view, config)).toEqual({
      spec: "Brief",
      orchestrationMode: "workflow",
      autonomyLevel: "A3",
      researchConfig: config,
    });
    expect(buildResearchWorkflowInput(view, config)).toEqual({
      spec: "Brief",
      competitor_urls: ["https://example.com"],
      depth: "deep",
      output_language: "ja",
    });
  });

  it("builds planning, design, and development workflow inputs", () => {
    const analysis = { personas: [], user_stories: [], kano_features: [], recommendations: [] };
    const research = { competitors: [], market_size: "", trends: [], opportunities: [], threats: [], tech_feasibility: { score: 0.8, notes: "" } };
    const view = makeView({
      research,
      analysis,
      features: [
        { feature: "A", selected: true, rationale: "", priority: "must", category: "must-be", user_delight: 8, implementation_cost: "medium" },
        { feature: "B", selected: false, rationale: "", priority: "could", category: "attractive", user_delight: 6, implementation_cost: "low" },
      ],
      milestones: [{ id: "m1", name: "Milestone", criteria: "done", status: "pending" }],
      selectedDesignId: "d1",
      designVariants: [
        {
          id: "d1",
          model: "model",
          pattern_name: "Pattern",
          description: "desc",
          preview_html: "<div />",
          tokens: { in: 1, out: 2 },
          cost_usd: 0.1,
          scores: { ux_quality: 8, code_quality: 7, performance: 7, accessibility: 8 },
        },
      ],
    });

    expect(buildPlanningWorkflowInput(view)).toEqual({ spec: "Spec", research });
    expect(buildDesignWorkflowInput(view)).toEqual({
      spec: "Spec",
      features: [view.features[0]],
      analysis,
    });
    expect(buildDevelopmentWorkflowInput(view)).toEqual({
      spec: "Spec",
      selected_features: [{ feature: "A", priority: "must", category: "must-be" }],
      analysis,
      design: view.designVariants[0],
      milestones: [{ id: "m1", name: "Milestone", criteria: "done" }],
    });
  });

  it("builds approval and feedback payloads", () => {
    expect(buildApprovalPayload("approve", "")).toEqual({
      text: "承認しました",
      type: "approve",
    });
    expect(buildFeedbackPayload("bug", "Broken")).toEqual({
      text: "Broken",
      type: "bug",
      impact: "high",
    });
  });
});
