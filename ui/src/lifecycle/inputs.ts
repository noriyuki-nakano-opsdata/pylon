import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type {
  ApprovalComment,
  FeedbackItem,
  LifecycleProject,
  LifecycleResearchConfig,
} from "@/types/lifecycle";
import {
  selectSelectedDesign,
  selectSelectedFeatures,
} from "@/lifecycle/selectors";

export function buildResearchConfigInput(
  config: LifecycleResearchConfig,
): {
  competitorUrls: string[];
  depth: LifecycleResearchConfig["depth"];
  outputLanguage: string;
} {
  return {
    competitorUrls: config.competitorUrls,
    depth: config.depth,
    outputLanguage: config.outputLanguage ?? "ja",
  };
}

export function buildResearchProjectPatch(
  view: Pick<LifecycleWorkspaceView, "spec">,
  config: LifecycleResearchConfig,
): Partial<LifecycleProject> {
  const normalized = buildResearchConfigInput(config);
  return {
    spec: view.spec.trim(),
    orchestrationMode: "workflow",
    autonomyLevel: "A3",
    researchConfig: normalized,
  };
}

export function buildResearchWorkflowInput(
  view: Pick<LifecycleWorkspaceView, "spec">,
  config: LifecycleResearchConfig,
): Record<string, unknown> {
  const normalized = buildResearchConfigInput(config);
  return {
    spec: view.spec.trim(),
    competitor_urls: normalized.competitorUrls,
    depth: normalized.depth,
    output_language: normalized.outputLanguage,
  };
}

export function buildPlanningWorkflowInput(
  view: Pick<LifecycleWorkspaceView, "spec" | "research">,
): Record<string, unknown> {
  return {
    spec: view.spec,
    research: view.research,
  };
}

export function buildDesignWorkflowInput(
  view: Pick<LifecycleWorkspaceView, "spec" | "features" | "analysis">,
): Record<string, unknown> {
  return {
    spec: view.spec,
    features: selectSelectedFeatures(view),
    analysis: view.analysis,
  };
}

export function buildDevelopmentWorkflowInput(
  view: Pick<
    LifecycleWorkspaceView,
    "spec" | "features" | "analysis" | "selectedDesignId" | "designVariants" | "milestones"
  >,
): Record<string, unknown> {
  return {
    spec: view.spec,
    selected_features: selectSelectedFeatures(view).map((feature) => ({
      feature: feature.feature,
      priority: feature.priority,
      category: feature.category,
    })),
    analysis: view.analysis,
    design: selectSelectedDesign(view) ?? undefined,
    milestones: view.milestones.map((milestone) => ({
      id: milestone.id,
      name: milestone.name,
      criteria: milestone.criteria,
    })),
  };
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
