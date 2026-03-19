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
import {
  defaultProductIdentity,
  mergeProductIdentityFallback,
} from "@/lifecycle/productIdentity";
import { defaultResearchConfig } from "@/lifecycle/store";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";

function makeView(overrides: Partial<LifecycleWorkspaceView> = {}): LifecycleWorkspaceView {
  return {
    spec: "Spec",
    orchestrationMode: "workflow",
    governanceMode: "governed",
    autonomyLevel: "A3",
    decisionContext: null,
    productIdentity: defaultProductIdentity(),
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
    const view = makeView({
      spec: "  Brief  ",
      productIdentity: {
        companyName: "Pylon Labs",
        productName: "Pylon",
        officialWebsite: "https://pylon.example.com",
        officialDomains: ["pylon.example.com"],
        aliases: ["Pylon Platform"],
        excludedEntityNames: ["Basler pylon"],
      },
    });
    const config = {
      competitorUrls: ["https://example.com"],
      depth: "deep" as const,
      outputLanguage: "ja",
      recoveryMode: "reframe_research" as const,
    };

    expect(buildResearchProjectPatch(view, config)).toEqual({
      spec: "Brief",
      orchestrationMode: "workflow",
      governanceMode: "governed",
      autonomyLevel: "A3",
      productIdentity: {
        companyName: "Pylon Labs",
        productName: "Pylon",
        officialWebsite: "https://pylon.example.com",
        officialDomains: ["pylon.example.com"],
        aliases: ["Pylon Platform"],
        excludedEntityNames: ["Basler pylon"],
      },
      researchConfig: config,
    });
    expect(buildResearchWorkflowInput(view, config)).toEqual({
      spec: "Brief",
      competitor_urls: ["https://example.com"],
      depth: "deep",
      output_language: "ja",
      recovery_mode: "reframe_research",
      identity_profile: {
        companyName: "Pylon Labs",
        productName: "Pylon",
        officialWebsite: "https://pylon.example.com",
        officialDomains: ["pylon.example.com"],
        aliases: ["Pylon Platform"],
        excludedEntityNames: ["Basler pylon"],
      },
    });
  });

  it("builds planning, design, and development workflow inputs", () => {
    const analysis = {
      personas: [],
      user_stories: [],
      kano_features: [],
      recommendations: [],
      canonical: { personas: [], user_stories: [], kano_features: [], recommendations: ["canonical analysis"] },
      localized: { personas: [], user_stories: [], kano_features: [], recommendations: ["localized analysis"] },
    };
    const research = {
      competitors: [],
      market_size: "",
      trends: [],
      opportunities: [],
      threats: [],
      tech_feasibility: { score: 0.8, notes: "" },
      canonical: { market_size: "TAM", winning_theses: ["canonical research"] },
      localized: { market_size: "市場規模", winning_theses: ["localized research"] },
    };
    const view = makeView({
      research,
      analysis,
      decisionContext: {
        fingerprint: "ctx-1",
        project_frame: {
          lead_thesis: "Trust is the differentiator",
        },
      },
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
      githubRepo: "/tmp/local-repo",
    });

    expect(buildPlanningWorkflowInput(view)).toEqual({ spec: "Spec", research: research.canonical });
    expect(buildDesignWorkflowInput(view)).toEqual({
      spec: "Spec",
      features: [view.features[0]],
      analysis: analysis.canonical,
      decision_context: view.decisionContext,
    });
    expect(buildDevelopmentWorkflowInput(view)).toEqual({
      spec: "Spec",
      githubRepo: "/tmp/local-repo",
      selected_features: [{ feature: "A", priority: "must", category: "must-be" }],
      analysis: analysis.canonical,
      design: view.designVariants[0],
      planEstimates: [],
      selectedPreset: "standard",
      milestones: [{ id: "m1", name: "Milestone", criteria: "done" }],
      requirements: undefined,
      requirementsConfig: undefined,
      reverseEngineering: undefined,
      taskDecomposition: undefined,
      dcsAnalysis: undefined,
      technicalDesign: undefined,
      decision_context: view.decisionContext,
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

  it("fills missing project identity fields from a trusted fallback", () => {
    expect(mergeProductIdentityFallback(
      defaultProductIdentity(),
      {
        companyName: "Pylon Labs",
        productName: "Pylon",
        officialWebsite: "https://pylon.example.com",
        aliases: ["Pylon Platform"],
      },
      { fallbackProductName: "Pylon" },
    )).toEqual({
      companyName: "Pylon Labs",
      productName: "Pylon",
      officialWebsite: "https://pylon.example.com",
      officialDomains: ["pylon.example.com"],
      aliases: ["Pylon Platform"],
      excludedEntityNames: [],
    });
  });
});
