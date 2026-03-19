import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type {
  ApprovalComment,
  FeedbackItem,
  LifecycleProject,
  LifecycleResearchConfig,
} from "@/types/lifecycle";
import {
  hasProductIdentity,
  normalizeProductIdentity,
  resolveProductIdentityForResearch,
} from "@/lifecycle/productIdentity";
import {
  selectSelectedDesign,
  selectSelectedFeatures,
} from "@/lifecycle/selectors";

function canonicalWorkflowValue<T extends { canonical?: Record<string, unknown> }>(
  value: T | null | undefined,
): T | Record<string, unknown> | null {
  if (!value) return null;
  const canonical = value.canonical;
  return canonical && Object.keys(canonical).length > 0 ? canonical : value;
}

export function buildResearchConfigInput(
  config: LifecycleResearchConfig,
): {
  competitorUrls: string[];
  depth: LifecycleResearchConfig["depth"];
  outputLanguage: string;
  recoveryMode: LifecycleResearchConfig["recoveryMode"];
} {
  return {
    competitorUrls: config.competitorUrls,
    depth: config.depth,
    outputLanguage: config.outputLanguage ?? "ja",
    recoveryMode: config.recoveryMode ?? "auto",
  };
}

export function buildResearchProjectPatch(
  view: Pick<LifecycleWorkspaceView, "spec" | "productIdentity" | "orchestrationMode" | "governanceMode" | "autonomyLevel">,
  config: LifecycleResearchConfig,
): Partial<LifecycleProject> {
  const normalized = buildResearchConfigInput(config);
  const productIdentity = normalizeProductIdentity(view.productIdentity);
  return {
    spec: view.spec.trim(),
    orchestrationMode: view.orchestrationMode,
    governanceMode: view.governanceMode ?? "governed",
    autonomyLevel: view.autonomyLevel,
    productIdentity,
    researchConfig: normalized,
  };
}

export function buildResearchWorkflowInput(
  view: Pick<LifecycleWorkspaceView, "spec" | "productIdentity">,
  config: LifecycleResearchConfig,
): Record<string, unknown> {
  const normalized = buildResearchConfigInput(config);
  const payload: Record<string, unknown> = {
    spec: view.spec.trim(),
    competitor_urls: normalized.competitorUrls,
    depth: normalized.depth,
    output_language: normalized.outputLanguage,
    recovery_mode: normalized.recoveryMode,
  };
  if (hasProductIdentity(view.productIdentity)) {
    payload.identity_profile = resolveProductIdentityForResearch(view.productIdentity);
  }
  return payload;
}

export function buildPlanningWorkflowInput(
  view: Pick<LifecycleWorkspaceView, "spec" | "research">,
): Record<string, unknown> {
  return {
    spec: view.spec,
    research: canonicalWorkflowValue(view.research),
  };
}

export function buildDesignWorkflowInput(
  view: Pick<LifecycleWorkspaceView, "spec" | "features" | "analysis" | "decisionContext">,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    spec: view.spec,
    features: selectSelectedFeatures(view),
    analysis: canonicalWorkflowValue(view.analysis),
  };
  if (view.decisionContext) {
    payload.decision_context = view.decisionContext;
  }
  return payload;
}

export function buildDevelopmentWorkflowInput(
  view: Pick<
    LifecycleWorkspaceView,
    "spec" | "features" | "analysis" | "selectedDesignId" | "designVariants" | "milestones" | "planEstimates" | "selectedPreset" | "decisionContext"
    | "requirements" | "requirementsConfig" | "reverseEngineering" | "taskDecomposition" | "dcsAnalysis" | "technicalDesign" | "githubRepo"
  >,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    spec: view.spec,
    githubRepo: view.githubRepo ?? undefined,
    selected_features: selectSelectedFeatures(view).map((feature) => ({
      feature: feature.feature,
      priority: feature.priority,
      category: feature.category,
    })),
    analysis: canonicalWorkflowValue(view.analysis),
    design: selectSelectedDesign(view) ?? undefined,
    planEstimates: view.planEstimates,
    selectedPreset: view.selectedPreset,
    milestones: view.milestones.map((milestone) => ({
      id: milestone.id,
      name: milestone.name,
      criteria: milestone.criteria,
    })),
    requirements: view.requirements ?? undefined,
    requirementsConfig: view.requirementsConfig ?? undefined,
    reverseEngineering: view.reverseEngineering ?? undefined,
    taskDecomposition: view.taskDecomposition ?? undefined,
    dcsAnalysis: view.dcsAnalysis ?? undefined,
    technicalDesign: view.technicalDesign ?? undefined,
  };
  if (view.decisionContext) {
    payload.decision_context = view.decisionContext;
  }
  return payload;
}

export function buildApprovalPayload(
  type: "comment" | "approve" | "reject",
  text: string,
): Pick<ApprovalComment, "text" | "type"> {
  return {
    text: text || (type === "approve" ? "承認しました" : "差し戻しました"),
    type,
  };
}

export function buildFeedbackPayload(
  type: FeedbackItem["type"],
  text: string,
): Pick<FeedbackItem, "text" | "type" | "impact"> {
  return {
    text,
    type,
    impact: type === "bug" ? "high" : type === "feature" ? "medium" : "low",
  };
}
