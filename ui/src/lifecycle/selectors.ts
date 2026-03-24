import type { AgentProgress, WorkflowRunState } from "@/hooks/useWorkflowRun";
import {
  normalizePlanningCopyList,
  normalizePlanningText,
} from "@/lifecycle/planningDisplay";
import { polishResearchCopy } from "@/lifecycle/presentation";
import {
  resolveProductIdentityForResearch,
} from "@/lifecycle/productIdentity";
import { auditResearchQuality } from "@/lifecycle/researchAudit";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type {
  AnalysisResult,
  DCSAnalysis,
  DeployCheck,
  DesignVariant,
  FeedbackItem,
  LifecycleAgentBlueprint,
  LifecycleDeliveryPlan,
  LifecyclePhase,
  LifecyclePhaseRuntimeSummary,
  MarketResearch,
  PlanEstimate,
  ReleaseRecord,
  RequirementsBundle,
  TaskDecomposition,
  TechnicalDesignBundle,
  WorkflowRunLiveTelemetry,
} from "@/types/lifecycle";

function toAgentProgressStatus(
  status: "idle" | "running" | "completed" | "failed",
): "pending" | "running" | "completed" | "failed" {
  return status === "idle" ? "pending" : status;
}

export function selectPhaseStatus(
  phaseStatuses: LifecycleWorkspaceView["phaseStatuses"],
  phase: LifecyclePhase,
): string {
  return phaseStatuses.find((item) => item.phase === phase)?.status ?? "available";
}

export function selectResearchRuntimeSummary(
  lifecycle: Pick<
    LifecycleWorkspaceView,
    "runtimeActivePhase" | "runtimeActivePhaseSummary" | "runtimePhaseSummary"
  >,
): LifecyclePhaseRuntimeSummary | null {
  if (lifecycle.runtimeActivePhase === "research") {
    return lifecycle.runtimeActivePhaseSummary;
  }
  if (lifecycle.runtimePhaseSummary?.phase === "research") {
    return lifecycle.runtimePhaseSummary;
  }
  return null;
}

export function selectResearchRuntimeTelemetry(
  lifecycle: Pick<
    LifecycleWorkspaceView,
    "runtimeActivePhase" | "runtimeLiveTelemetry"
  >,
): WorkflowRunLiveTelemetry | null {
  if (!lifecycle.runtimeLiveTelemetry) {
    return null;
  }
  if (lifecycle.runtimeLiveTelemetry.phase != null) {
    return lifecycle.runtimeLiveTelemetry.phase === "research"
      ? lifecycle.runtimeLiveTelemetry
      : null;
  }
  return lifecycle.runtimeActivePhase === "research"
    ? lifecycle.runtimeLiveTelemetry
    : null;
}

export function selectResearchProgressState(params: {
  workflow: Pick<WorkflowRunState, "status" | "agentProgress">;
  runtimeSummary: LifecyclePhaseRuntimeSummary | null;
  runtimeTelemetry: WorkflowRunLiveTelemetry | null;
  isPreparing: boolean;
  nowMs: number;
}) {
  const runtimeProgress = (params.runtimeSummary?.agents ?? []).map((agent) => ({
    nodeId: agent.agentId,
    agent: agent.label,
    status: toAgentProgressStatus(agent.status),
  }));
  const runtimeStartedAt = params.runtimeTelemetry?.run?.startedAt
    ? new Date(params.runtimeTelemetry.run.startedAt).getTime()
    : null;
  const runtimeElapsedMs = runtimeStartedAt
    ? Math.max(0, params.nowMs - runtimeStartedAt)
    : 0;
  const isRunning =
    params.isPreparing
    || params.workflow.status === "starting"
    || params.workflow.status === "running";
  const isResearchRunLive =
    params.runtimeTelemetry?.run != null
    && params.runtimeTelemetry.run.status !== "completed"
    && params.runtimeTelemetry.run.status !== "failed";
  const visibleProgress: AgentProgress[] = params.workflow.agentProgress.length > 0
    ? params.workflow.agentProgress
    : runtimeProgress;
  const totalSteps = Math.max(
    visibleProgress.length,
    params.runtimeSummary?.agents?.length ?? 0,
    1,
  );
  const completedSteps = params.runtimeTelemetry?.completedNodeCount
    ?? visibleProgress.filter((agent) => agent.status === "completed").length;

  return {
    runtimeProgress,
    runtimeElapsedMs,
    runtimeRunningNodes: params.runtimeTelemetry?.runningNodeIds ?? [],
    runtimeRecentNodes: params.runtimeTelemetry?.recentNodeIds ?? [],
    runtimeRecentEvents: params.runtimeTelemetry?.recentEvents ?? [],
    runtimeRecentActions: params.runtimeSummary?.recentActions ?? [],
    runtimeAgentCards: (params.runtimeSummary?.agents ?? []).slice(0, 6),
    isRunning,
    isResearchRunLive,
    isInitialResearchRun: isRunning || isResearchRunLive,
    visibleProgress,
    totalSteps,
    completedSteps,
    progressPercent: Math.max(
      6,
      Math.min(100, Math.round((completedSteps / totalSteps) * 100)),
    ),
  };
}

export function selectResearchReadinessState(params: {
  research: MarketResearch | null;
  phaseStatus: string;
  nextAction: LifecycleWorkspaceView["nextAction"];
  projectSpec?: string;
  seedUrls?: string[];
  productIdentity?: LifecycleWorkspaceView["productIdentity"];
}) {
  const research = params.research;
  const researchIdentity = params.productIdentity
    ? resolveProductIdentityForResearch(params.productIdentity)
    : undefined;
  const semanticAudit = research
    ? auditResearchQuality(research, {
      projectSpec: params.projectSpec,
      seedUrls: params.seedUrls,
      identityProfile: researchIdentity,
    })
    : null;
  const hasExternalSources =
    (semanticAudit?.sourceLinks.trusted.length ?? 0) > 0
    || (semanticAudit?.evidence.trusted.length ?? 0) > 0
    || (semanticAudit?.competitors.trusted.some((item) => Boolean(item.url)) ?? false);
  const hasWinningTheses = (semanticAudit?.winningTheses.trusted.length ?? 0) > 0;
  const confidenceFloor = research?.confidence_summary?.floor ?? 0;
  const criticalDissentCount =
    research?.critical_dissent_count
    ?? (research?.dissent ?? []).filter(
      (item) => item.severity === "critical" && !item.resolved,
    ).length;
  const hasFailedQualityGates = (research?.quality_gates ?? []).some((gate) => gate.passed !== true);
  const hasDegradedNodes = (research?.node_results ?? []).some((node) => node.status !== "success");
  const autonomousRemediation = research?.autonomous_remediation;
  const nextActionAutoResearch =
    params.nextAction?.phase === "research"
    && params.nextAction?.type === "run_phase"
    && params.nextAction?.canAutorun;
  const nextActionOperatorGuidance =
    params.nextAction?.payload?.operatorGuidance
    && typeof params.nextAction.payload.operatorGuidance === "object"
      ? params.nextAction.payload.operatorGuidance as Record<string, unknown>
      : null;
  const nextActionRecommendedAction =
    typeof nextActionOperatorGuidance?.recommendedAction === "string"
      ? nextActionOperatorGuidance.recommendedAction
      : undefined;
  const researchReady =
    !!research
    && params.phaseStatus === "completed"
    && hasExternalSources
    && hasWinningTheses
    && confidenceFloor >= 0.6
    && criticalDissentCount === 0
    && !hasFailedQualityGates
    && !hasDegradedNodes
    && (semanticAudit?.semanticReady ?? true);
  const conditionalHandoffAllowed =
    autonomousRemediation?.conditionalHandoffAllowed === true
    || nextActionOperatorGuidance?.conditionalHandoffAllowed === true;
  const planningHandoffUnlocked =
    conditionalHandoffAllowed
    && (
      nextActionRecommendedAction === "conditional_handoff"
      || params.nextAction?.phase === "planning"
    );
  const gateIssues = !researchReady && research
    ? [
        ...(semanticAudit?.issues ?? []),
        !hasExternalSources
          ? "外部ソースへの根拠リンクが不足しています。"
          : null,
        !hasWinningTheses
          ? "企画に渡せる有力仮説が不足しています。"
          : null,
        confidenceFloor < 0.6
          ? `信頼度下限が ${(confidenceFloor * 100).toFixed(0)}% で、企画に渡す基準の 60% を下回っています。`
          : null,
        criticalDissentCount > 0
          ? `未解決の重大な反証が ${criticalDissentCount} 件あります。`
          : null,
        hasDegradedNodes
          ? "要再確認の調査ノードが残っています。"
          : null,
      ].filter((issue): issue is string => Boolean(issue))
    : [];
  const isAutonomousRecoveryActive = !!research && !researchReady && !planningHandoffUnlocked && (
    autonomousRemediation?.status === "queued"
    || autonomousRemediation?.status === "retrying"
    || nextActionAutoResearch
  );
  const recommendedOperatorAction =
    planningHandoffUnlocked
      ? nextActionRecommendedAction || autonomousRemediation?.recommendedOperatorAction
      : autonomousRemediation?.recommendedOperatorAction || nextActionRecommendedAction;
  const rawStrategySummary =
    planningHandoffUnlocked
      ? (typeof nextActionOperatorGuidance?.strategySummary === "string"
        ? nextActionOperatorGuidance.strategySummary
        : autonomousRemediation?.strategySummary)
      : autonomousRemediation?.strategySummary
        || (typeof nextActionOperatorGuidance?.strategySummary === "string"
          ? nextActionOperatorGuidance.strategySummary
          : undefined);
  const strategySummary = rawStrategySummary ? polishResearchCopy(rawStrategySummary) : undefined;
  const rawPlanningGuardrails =
    planningHandoffUnlocked
      ? (Array.isArray(nextActionOperatorGuidance?.planningGuardrails)
        ? nextActionOperatorGuidance.planningGuardrails.filter((item): item is string => typeof item === "string")
        : autonomousRemediation?.planningGuardrails ?? [])
      : autonomousRemediation?.planningGuardrails
        ?? (Array.isArray(nextActionOperatorGuidance?.planningGuardrails)
          ? nextActionOperatorGuidance.planningGuardrails.filter((item): item is string => typeof item === "string")
          : []);
  const planningGuardrails = rawPlanningGuardrails
    .map((item) => polishResearchCopy(item))
    .filter((item) => item.length > 0);
  const rawFollowUpQuestion =
    planningHandoffUnlocked
      ? (typeof nextActionOperatorGuidance?.followUpQuestion === "string"
        ? nextActionOperatorGuidance.followUpQuestion
        : autonomousRemediation?.followUpQuestion)
      : autonomousRemediation?.followUpQuestion
        || (typeof nextActionOperatorGuidance?.followUpQuestion === "string"
          ? nextActionOperatorGuidance.followUpQuestion
          : undefined);
  const followUpQuestion = rawFollowUpQuestion ? polishResearchCopy(rawFollowUpQuestion) : undefined;

  return {
    researchReady,
    hasExternalSources,
    hasWinningTheses,
    confidenceFloor,
    criticalDissentCount,
    semanticAudit,
    semanticIssues: semanticAudit?.issues ?? [],
    autonomousRemediation,
    nextActionAutoResearch,
    isAutonomousRecoveryActive,
    conditionalHandoffAllowed,
    recommendedOperatorAction,
    strategySummary,
    planningGuardrails,
    followUpQuestion,
    gateIssues,
    warning: !researchReady && research
      ? gateIssues[0] ?? "品質ゲートを満たしていません。企画へ進む前に追加調査が必要です。"
      : null,
  };
}

export function selectPhaseTeam(
  view: Pick<LifecycleWorkspaceView, "blueprints">,
  phase: LifecyclePhase,
  fallback: LifecycleAgentBlueprint[],
): LifecycleAgentBlueprint[] {
  const team = view.blueprints[phase]?.team ?? [];
  return team.length > 0 ? team : fallback;
}

export function selectSelectedFeatures(
  view: Pick<LifecycleWorkspaceView, "features">,
) {
  return view.features.filter((feature) => feature.selected);
}

export function selectSelectedFeatureCount(
  view: Pick<LifecycleWorkspaceView, "features">,
): number {
  return selectSelectedFeatures(view).length;
}

export function selectSelectedDesign(
  view: Pick<LifecycleWorkspaceView, "selectedDesignId" | "designVariants">,
): DesignVariant | null {
  if (!view.selectedDesignId) return null;
  return view.designVariants.find((variant) => variant.id === view.selectedDesignId) ?? null;
}

function selectPlanEstimateForDevelopment(
  view: Partial<Pick<LifecycleWorkspaceView, "planEstimates" | "selectedPreset">>,
): PlanEstimate | null {
  const planEstimates = view.planEstimates ?? [];
  const selectedPreset = view.selectedPreset ?? "standard";
  return planEstimates.find((estimate) => estimate.preset === selectedPreset)
    ?? planEstimates.find((estimate) => estimate.preset === "standard")
    ?? planEstimates[0]
    ?? null;
}

function resolvePreviewLaneId(text: string): string {
  const normalized = text.toLowerCase();
  if (/(security|safe|policy|threat)/.test(normalized)) return "security-reviewer";
  if (/(review|release|handoff|sign)/.test(normalized)) return "reviewer";
  if (/(qa|test|acceptance|verification|quality)/.test(normalized)) return "qa-engineer";
  if (/(integrat|merge|compose|shell|routing)/.test(normalized)) return "integrator";
  if (/(backend|api|domain|state|schema|model|service)/.test(normalized)) return "backend-builder";
  if (/(planner|define|scope|acceptance)/.test(normalized)) return "planner";
  return "frontend-builder";
}

function computeCriticalPathIds(
  workPackages: Array<{ id: string; depends_on: string[]; duration_days: number }>,
): string[] {
  const byId = new Map(workPackages.map((item) => [item.id, item]));
  const memo = new Map<string, { duration: number; path: string[] }>();
  const visiting = new Set<string>();

  const visit = (id: string): { duration: number; path: string[] } => {
    const cached = memo.get(id);
    if (cached) return cached;
    const current = byId.get(id);
    if (!current) return { duration: 0, path: [] };
    if (visiting.has(id)) return { duration: current.duration_days, path: [id] };
    visiting.add(id);
    let best = { duration: 0, path: [] as string[] };
    current.depends_on.filter((dependencyId) => byId.has(dependencyId)).forEach((dependencyId) => {
      const resolved = visit(dependencyId);
      if (resolved.duration > best.duration) best = resolved;
    });
    visiting.delete(id);
    const result = {
      duration: best.duration + current.duration_days,
      path: [...best.path, id],
    };
    memo.set(id, result);
    return result;
  };

  return workPackages.reduce<{ duration: number; path: string[] }>(
    (best, item) => {
      const resolved = visit(item.id);
      return resolved.duration > best.duration ? resolved : best;
    },
    { duration: 0, path: [] },
  ).path;
}

function selectDeliveryPlanPreview(
  view: Partial<Pick<LifecycleWorkspaceView, "deliveryPlan" | "planEstimates" | "selectedPreset">>,
  selectedDesign: DesignVariant | null,
): LifecycleDeliveryPlan | null {
  if (view.deliveryPlan) return view.deliveryPlan;
  const planEstimate = selectPlanEstimateForDevelopment(view);
  if (!planEstimate || planEstimate.wbs.length === 0) return null;
  const laneSource = selectedDesign?.implementation_brief?.agent_lanes ?? [];
  const previewLanes = laneSource.map((lane, index) => {
    const laneId = resolvePreviewLaneId(`${lane.role} ${lane.remit} ${lane.skills.join(" ")}`);
    return {
      agent: laneId,
      label: lane.role,
      remit: lane.remit,
      skills: lane.skills,
      owned_surfaces: [],
      conflict_guards: [
        `${lane.role} の担当範囲は ${lane.remit} に限定する`,
        "shared shell と routing の変更は integrator で一本化する",
      ],
      merge_order: index + 1,
    };
  });
  const workPackages = planEstimate.wbs.map((item) => {
    const lane = resolvePreviewLaneId(`${item.assignee} ${item.title} ${item.description} ${item.skills.join(" ")}`);
    return {
      id: item.id,
      title: item.title,
      lane,
      summary: item.description,
      depends_on: item.depends_on,
      start_day: item.start_day,
      duration_days: item.duration_days,
      deliverables: [item.title],
      acceptance_criteria: [item.description],
      owned_surfaces: [],
      source_epic: item.epic_id,
      status: "planned" as const,
      is_critical: false,
    };
  });
  const criticalPath = computeCriticalPathIds(workPackages);
  return {
    execution_mode: "planning_preview",
    summary: "planning で決めた WBS を development で実行する前提の preview graph です。",
    selected_preset: planEstimate.preset,
    source_plan_preset: planEstimate.preset,
    success_definition: "WBS の依存順を守って build と deploy handoff まで完了させる。",
    work_packages: workPackages.map((item) => ({ ...item, is_critical: criticalPath.includes(item.id) })),
    lanes: previewLanes,
    critical_path: criticalPath,
    gantt: workPackages.map((item) => ({
      work_package_id: item.id,
      lane: item.lane,
      start_day: item.start_day,
      duration_days: item.duration_days,
      depends_on: item.depends_on,
      is_critical: criticalPath.includes(item.id),
    })),
    merge_strategy: {
      integration_order: workPackages.map((item) => item.id),
      conflict_prevention: [
        "shared shell と routing の変更は integrator が最後に一本化する",
        "backend contract を先に固定し、frontend binding はその後に乗せる",
      ],
      shared_touchpoints: selectedDesign?.implementation_brief?.delivery_slices ?? [],
    },
  };
}

export function selectCompletedPhaseCount(
  view: Pick<LifecycleWorkspaceView, "phaseStatuses">,
): number {
  return view.phaseStatuses.filter((phase) => phase.status === "completed").length;
}

export function selectSortedFeedbackItems(
  view: Pick<LifecycleWorkspaceView, "feedbackItems">,
): FeedbackItem[] {
  return [...view.feedbackItems].sort((a, b) => b.votes - a.votes);
}

export function selectDeploySummary(
  view: Pick<LifecycleWorkspaceView, "deployChecks" | "releases">,
): {
  checks: DeployCheck[];
  allPassed: boolean;
  deployed: boolean;
  latestRelease: ReleaseRecord | undefined;
  passedCount: number;
  warningCount: number;
  failedCount: number;
  releaseReady: boolean;
  releaseSummary: string;
  blockingChecks: DeployCheck[];
  cautionChecks: DeployCheck[];
} {
  const checks = view.deployChecks;
  const failedCount = checks.filter((item) => item.status === "fail").length;
  const warningCount = checks.filter((item) => item.status === "warning").length;
  const passedCount = checks.filter((item) => item.status === "pass").length;
  const releaseReady = checks.length > 0 && failedCount === 0;
  return {
    checks,
    allPassed: releaseReady,
    deployed: view.releases.length > 0,
    latestRelease: view.releases[0],
    passedCount,
    warningCount,
    failedCount,
    releaseReady,
    releaseSummary:
      checks.length === 0
        ? "まだリリースゲートは未実行です。HTML / レスポンシブ / a11y / performance の確認から始めます。"
        : failedCount > 0
          ? `不合格が ${failedCount} 件あります。fail を解消するまでリリースは確定しません。`
          : warningCount > 0
            ? `不合格はありません。注意事項が ${warningCount} 件あるので、意図を確認してからリリースへ進みます。`
            : "すべてのリリースゲートが通過しています。記録を作成して次の改善ループへ進めます。",
    blockingChecks: checks.filter((item) => item.status === "fail"),
    cautionChecks: checks.filter((item) => item.status === "warning"),
  };
}

export function selectPlanningAnalysis(
  view: Pick<LifecycleWorkspaceView, "analysis">,
): AnalysisResult {
  const analysis = view.analysis;
  if (!analysis) {
    return {
      personas: [],
      user_stories: [],
      kano_features: [],
      recommendations: [],
    };
  }
  const localized = analysis.localized;
  if (localized && typeof localized === "object" && !Array.isArray(localized)) {
    return normalizePlanningAnalysisDisplay({
      ...analysis,
      ...(localized as Partial<AnalysisResult>),
      canonical: analysis.canonical,
      localized,
      display_language: analysis.display_language,
      localization_status: analysis.localization_status,
    });
  }
  return normalizePlanningAnalysisDisplay(analysis);
}

type PlanningRiskHighlight = {
  id: string;
  severity: string;
  title: string;
  description: string;
  owner?: string;
  mustResolveBefore?: string;
};

type PlanningRecommendationCard = {
  id: string;
  priority: string;
  target?: string;
  action: string;
  rationale?: string;
};

type PlanningDecisionSummary = {
  label: string;
  title: string;
  description: string;
  owner?: string;
  due?: string;
  emphasis?: string;
};

type PlanningCouncilCard = {
  id: string;
  agent: string;
  lens: string;
  title: string;
  summary: string;
  actionLabel: string;
  targetTab?: PlanningReviewTab;
  targetSection?: "risk" | "recommendation";
  tone?: string;
};

type PlanningHandoffBrief = {
  headline: string;
  summary: string;
  bullets: string[];
};

const PLANNING_RISK_SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const PLANNING_RECOMMENDATION_PRIORITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function normalizePlanningAnalysisDisplay(analysis: AnalysisResult): AnalysisResult {
  return {
    ...analysis,
    personas: (analysis.personas ?? []).map((persona) => ({
      ...persona,
      name: normalizePlanningText(persona.name, persona.name),
      role: normalizePlanningText(persona.role, persona.role),
      age_range: normalizePlanningText(persona.age_range, persona.age_range),
      goals: normalizePlanningCopyList(persona.goals),
      frustrations: normalizePlanningCopyList(persona.frustrations),
      tech_proficiency: normalizePlanningText(persona.tech_proficiency, persona.tech_proficiency),
      context: normalizePlanningText(persona.context, persona.context),
    })),
    user_stories: (analysis.user_stories ?? []).map((story) => ({
      ...story,
      role: normalizePlanningText(story.role, story.role),
      action: normalizePlanningText(story.action, story.action),
      benefit: normalizePlanningText(story.benefit, story.benefit),
      acceptance_criteria: normalizePlanningCopyList(story.acceptance_criteria),
    })),
    kano_features: (analysis.kano_features ?? []).map((feature) => ({
      ...feature,
      feature: normalizePlanningText(feature.feature, feature.feature),
      rationale: normalizePlanningText(feature.rationale, feature.rationale),
    })),
    recommendations: analysis.recommendations ?? [],
    ...(analysis.business_model ? {
      business_model: {
        value_propositions: normalizePlanningCopyList(analysis.business_model.value_propositions),
        customer_segments: normalizePlanningCopyList(analysis.business_model.customer_segments),
        channels: normalizePlanningCopyList(analysis.business_model.channels),
        revenue_streams: normalizePlanningCopyList(analysis.business_model.revenue_streams),
      },
    } : {}),
    ...(analysis.user_journeys ? {
      user_journeys: analysis.user_journeys.map((journey) => ({
        ...journey,
        persona_name: normalizePlanningText(journey.persona_name, journey.persona_name),
        touchpoints: journey.touchpoints.map((touchpoint) => ({
          ...touchpoint,
          persona: normalizePlanningText(touchpoint.persona, touchpoint.persona),
          action: normalizePlanningText(touchpoint.action, touchpoint.action),
          touchpoint: normalizePlanningText(touchpoint.touchpoint, touchpoint.touchpoint),
          pain_point: touchpoint.pain_point ? normalizePlanningText(touchpoint.pain_point, touchpoint.pain_point) : undefined,
          opportunity: touchpoint.opportunity ? normalizePlanningText(touchpoint.opportunity, touchpoint.opportunity) : undefined,
        })),
      })),
    } : {}),
    ...(analysis.job_stories ? {
      job_stories: analysis.job_stories.map((story) => ({
        ...story,
        situation: normalizePlanningText(story.situation, story.situation),
        motivation: normalizePlanningText(story.motivation, story.motivation),
        outcome: normalizePlanningText(story.outcome, story.outcome),
        related_features: normalizePlanningCopyList(story.related_features),
      })),
    } : {}),
    ...(analysis.ia_analysis ? {
      ia_analysis: {
        ...analysis.ia_analysis,
        site_map: analysis.ia_analysis.site_map.map(function normalizeNode(node): NonNullable<AnalysisResult["ia_analysis"]>["site_map"][number] {
          return {
            ...node,
            label: normalizePlanningText(node.label, node.label),
            description: node.description ? normalizePlanningText(node.description, node.description) : undefined,
            children: node.children?.map(normalizeNode),
          };
        }),
        key_paths: analysis.ia_analysis.key_paths.map((path) => ({
          ...path,
          name: normalizePlanningText(path.name, path.name),
          steps: normalizePlanningCopyList(path.steps),
        })),
      },
    } : {}),
    ...(analysis.actors ? {
      actors: analysis.actors.map((actor) => ({
        ...actor,
        name: normalizePlanningText(actor.name, actor.name),
        description: normalizePlanningText(actor.description, actor.description),
        goals: normalizePlanningCopyList(actor.goals),
        interactions: normalizePlanningCopyList(actor.interactions),
      })),
    } : {}),
    ...(analysis.roles ? {
      roles: analysis.roles.map((role) => ({
        ...role,
        name: normalizePlanningText(role.name, role.name),
        responsibilities: normalizePlanningCopyList(role.responsibilities),
        permissions: normalizePlanningCopyList(role.permissions),
        related_actors: normalizePlanningCopyList(role.related_actors),
      })),
    } : {}),
    ...(analysis.use_cases ? {
      use_cases: analysis.use_cases.map((useCase) => ({
        ...useCase,
        title: normalizePlanningText(useCase.title, useCase.title),
        actor: normalizePlanningText(useCase.actor, useCase.actor),
        category: normalizePlanningText(useCase.category, useCase.category),
        sub_category: normalizePlanningText(useCase.sub_category, useCase.sub_category),
        preconditions: normalizePlanningCopyList(useCase.preconditions),
        main_flow: normalizePlanningCopyList(useCase.main_flow),
        alternative_flows: useCase.alternative_flows?.map((flow) => ({
          ...flow,
          condition: normalizePlanningText(flow.condition, flow.condition),
          steps: normalizePlanningCopyList(flow.steps),
        })),
        postconditions: normalizePlanningCopyList(useCase.postconditions),
        related_stories: useCase.related_stories ? normalizePlanningCopyList(useCase.related_stories) : undefined,
      })),
    } : {}),
    ...(analysis.recommended_milestones ? {
      recommended_milestones: analysis.recommended_milestones.map((milestone) => ({
        ...milestone,
        name: normalizePlanningText(milestone.name, milestone.name),
        criteria: normalizePlanningText(milestone.criteria, milestone.criteria),
        rationale: normalizePlanningText(milestone.rationale, milestone.rationale),
        depends_on_use_cases: milestone.depends_on_use_cases ? normalizePlanningCopyList(milestone.depends_on_use_cases) : undefined,
      })),
    } : {}),
    ...(analysis.design_tokens ? {
      design_tokens: {
        ...analysis.design_tokens,
        style: {
          ...analysis.design_tokens.style,
          name: normalizePlanningText(analysis.design_tokens.style.name, analysis.design_tokens.style.name),
          keywords: normalizePlanningCopyList(analysis.design_tokens.style.keywords),
          best_for: normalizePlanningText(analysis.design_tokens.style.best_for, analysis.design_tokens.style.best_for),
          performance: normalizePlanningText(analysis.design_tokens.style.performance, analysis.design_tokens.style.performance),
          accessibility: normalizePlanningText(analysis.design_tokens.style.accessibility, analysis.design_tokens.style.accessibility),
        },
        colors: {
          ...analysis.design_tokens.colors,
          notes: normalizePlanningText(analysis.design_tokens.colors.notes, analysis.design_tokens.colors.notes),
        },
        typography: {
          ...analysis.design_tokens.typography,
          mood: normalizePlanningCopyList(analysis.design_tokens.typography.mood),
        },
        effects: normalizePlanningCopyList(analysis.design_tokens.effects),
        anti_patterns: normalizePlanningCopyList(analysis.design_tokens.anti_patterns),
        rationale: normalizePlanningText(analysis.design_tokens.rationale, analysis.design_tokens.rationale),
      },
    } : {}),
    ...(analysis.feature_decisions ? {
      feature_decisions: analysis.feature_decisions.map((decision) => ({
        ...decision,
        feature: normalizePlanningText(decision.feature, decision.feature),
        counterarguments: normalizePlanningCopyList(decision.counterarguments),
        rejection_reason: normalizePlanningText(decision.rejection_reason, decision.rejection_reason),
      })),
    } : {}),
    ...(analysis.rejected_features ? {
      rejected_features: analysis.rejected_features.map((feature) => ({
        ...feature,
        feature: normalizePlanningText(feature.feature, feature.feature),
        reason: normalizePlanningText(feature.reason, feature.reason),
        counterarguments: normalizePlanningCopyList(feature.counterarguments),
      })),
    } : {}),
    ...(analysis.assumptions ? {
      assumptions: analysis.assumptions.map((assumption) => ({
        ...assumption,
        statement: normalizePlanningText(assumption.statement, assumption.statement),
      })),
    } : {}),
    ...(analysis.red_team_findings ? {
      red_team_findings: analysis.red_team_findings.map((finding) => ({
        ...finding,
        title: normalizePlanningText(finding.title, finding.title),
        impact: normalizePlanningText(finding.impact, finding.impact),
        recommendation: normalizePlanningText(finding.recommendation, finding.recommendation),
        related_feature: finding.related_feature ? normalizePlanningText(finding.related_feature, finding.related_feature) : undefined,
      })),
    } : {}),
    ...(analysis.negative_personas ? {
      negative_personas: analysis.negative_personas.map((persona) => ({
        ...persona,
        name: normalizePlanningText(persona.name, persona.name),
        scenario: normalizePlanningText(persona.scenario, persona.scenario),
        risk: normalizePlanningText(persona.risk, persona.risk),
        mitigation: normalizePlanningText(persona.mitigation, persona.mitigation),
      })),
    } : {}),
    ...(analysis.traceability ? {
      traceability: analysis.traceability.map((item) => ({
        ...item,
        claim: normalizePlanningText(item.claim, item.claim),
        use_case: normalizePlanningText(item.use_case, item.use_case),
        feature: normalizePlanningText(item.feature, item.feature),
        milestone: normalizePlanningText(item.milestone, item.milestone),
      })),
    } : {}),
    ...(analysis.kill_criteria ? {
      kill_criteria: analysis.kill_criteria.map((criterion) => ({
        ...criterion,
        condition: normalizePlanningText(criterion.condition, criterion.condition),
        rationale: normalizePlanningText(criterion.rationale, criterion.rationale),
      })),
    } : {}),
    ...(analysis.coverage_summary ? {
      coverage_summary: {
        ...analysis.coverage_summary,
        uncovered_features: normalizePlanningCopyList(analysis.coverage_summary.uncovered_features),
        use_cases_without_milestone: normalizePlanningCopyList(analysis.coverage_summary.use_cases_without_milestone),
        use_cases_without_traceability: normalizePlanningCopyList(analysis.coverage_summary.use_cases_without_traceability),
      },
    } : {}),
    ...(analysis.operator_copy ? {
      operator_copy: {
        ...(analysis.operator_copy.council_cards?.length ? {
          council_cards: analysis.operator_copy.council_cards.map((card) => ({
            ...card,
            agent: normalizePlanningText(card.agent, card.agent),
            lens: normalizePlanningText(card.lens, card.lens),
            title: normalizePlanningText(card.title, card.title),
            summary: normalizePlanningText(card.summary, card.summary),
            action_label: normalizePlanningText(card.action_label, card.action_label),
          })),
        } : {}),
        ...(analysis.operator_copy.handoff_brief ? {
          handoff_brief: {
            ...analysis.operator_copy.handoff_brief,
            headline: normalizePlanningText(
              analysis.operator_copy.handoff_brief.headline,
              analysis.operator_copy.handoff_brief.headline,
            ),
            summary: normalizePlanningText(
              analysis.operator_copy.handoff_brief.summary,
              analysis.operator_copy.handoff_brief.summary,
            ),
            bullets: normalizePlanningCopyList(analysis.operator_copy.handoff_brief.bullets),
          },
        } : {}),
      },
    } : {}),
    ...(analysis.judge_summary ? { judge_summary: analysis.judge_summary } : {}),
  };
}

function tryParseLooseStructuredValue(raw: string): unknown {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    // Continue with tolerant parsing.
  }
  let candidate = trimmed;
  if (candidate.startsWith("{") && candidate.includes("}, {")) {
    candidate = `[${candidate}]`;
  }
  candidate = candidate
    .replace(/\bNone\b/g, "null")
    .replace(/\bTrue\b/g, "true")
    .replace(/\bFalse\b/g, "false")
    .replace(/'([^'\\]*(?:\\.[^'\\]*)*)'/g, (_, content: string) => JSON.stringify(content));
  try {
    return JSON.parse(candidate);
  } catch {
    return null;
  }
}

function extractLooseStructuredRecords(raw: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(raw)) {
    return raw.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  }
  if (raw && typeof raw === "object") {
    return [raw as Record<string, unknown>];
  }
  if (typeof raw !== "string") return [];
  const parsed = tryParseLooseStructuredValue(raw);
  if (Array.isArray(parsed)) {
    return parsed.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  }
  if (parsed && typeof parsed === "object") {
    return [parsed as Record<string, unknown>];
  }
  return [];
}

function planningRiskHighlights(analysis: AnalysisResult): PlanningRiskHighlight[] {
  const merged = new Map<string, PlanningRiskHighlight>();
  const upsertRisk = (candidate: PlanningRiskHighlight) => {
    if (!candidate.title || !candidate.description) return;
    const key = candidate.title.trim().toLowerCase();
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, candidate);
      return;
    }
    const existingRank = PLANNING_RISK_SEVERITY_ORDER[existing.severity] ?? 99;
    const candidateRank = PLANNING_RISK_SEVERITY_ORDER[candidate.severity] ?? 99;
    if (candidateRank < existingRank) {
      merged.set(key, candidate);
      return;
    }
    if (!existing.mustResolveBefore && candidate.mustResolveBefore) {
      merged.set(key, { ...existing, mustResolveBefore: candidate.mustResolveBefore });
    }
  };

  extractLooseStructuredRecords(analysis.judge_summary)
    .map((item, index) => ({
      id: String(item.id ?? `risk-${index + 1}`),
      severity: normalizePlanningText(item.severity, "medium").toLowerCase(),
      title: normalizePlanningText(item.title),
      description: normalizePlanningText(item.description),
      owner: normalizePlanningText(item.owner) || undefined,
      mustResolveBefore: normalizePlanningText(item.must_resolve_before ?? item.mustResolveBefore) || undefined,
    }))
    .forEach(upsertRisk);

  (analysis.red_team_findings ?? []).forEach((finding, index) => {
    upsertRisk({
      id: finding.id || `red-team-risk-${index + 1}`,
      severity: normalizePlanningText(finding.severity, "medium").toLowerCase(),
      title: normalizePlanningText(finding.title),
      description: normalizePlanningText(finding.impact || finding.recommendation),
      owner: undefined,
    });
  });

  return Array.from(merged.values());
}

function planningDeadlineRank(value?: string): number {
  if (!value) return 99;
  const normalized = normalizePlanningText(value);
  const orderedLabels = [
    "デザイン着手前",
    "M1 計測仕様確定前",
    "M1 デザイン仕様確定前",
    "M1 技術設計レビュー前",
    "M1 ユーザーテスト終了前",
  ];
  const index = orderedLabels.indexOf(normalized);
  return index === -1 ? orderedLabels.length : index;
}

function sortPlanningRisks(risks: PlanningRiskHighlight[]): PlanningRiskHighlight[] {
  return [...risks].sort((left, right) => {
    const severityGap =
      (PLANNING_RISK_SEVERITY_ORDER[left.severity] ?? 99)
      - (PLANNING_RISK_SEVERITY_ORDER[right.severity] ?? 99);
    if (severityGap !== 0) return severityGap;

    const deadlineGap = planningDeadlineRank(left.mustResolveBefore) - planningDeadlineRank(right.mustResolveBefore);
    if (deadlineGap !== 0) return deadlineGap;

    return left.title.localeCompare(right.title, "ja");
  });
}

function planningRecommendationCards(analysis: AnalysisResult): {
  cards: PlanningRecommendationCard[];
  notes: string[];
} {
  const cards: PlanningRecommendationCard[] = [];
  const notes: string[] = [];
  analysis.recommendations.forEach((entry, index) => {
    const parsed = extractLooseStructuredRecords(entry)[0];
    if (parsed && (parsed.action || parsed.rationale || parsed.target)) {
      cards.push({
        id: String(parsed.id ?? `rec-${index + 1}`),
        priority: normalizePlanningText(parsed.priority, "medium").toLowerCase(),
        target: normalizePlanningText(parsed.target) || undefined,
        action: normalizePlanningText(parsed.action),
        rationale: normalizePlanningText(parsed.rationale) || undefined,
      });
      return;
    }
    const note = normalizePlanningText(entry);
    if (note) notes.push(note);
  });
  return { cards, notes };
}

function sortPlanningRecommendations(cards: PlanningRecommendationCard[]): PlanningRecommendationCard[] {
  return [...cards].sort((left, right) => {
    const priorityGap =
      (PLANNING_RECOMMENDATION_PRIORITY_ORDER[left.priority] ?? 99)
      - (PLANNING_RECOMMENDATION_PRIORITY_ORDER[right.priority] ?? 99);
    if (priorityGap !== 0) return priorityGap;
    return left.action.localeCompare(right.action, "ja");
  });
}

function summarizePlanningFocus(
  risks: PlanningRiskHighlight[],
  recommendationCards: PlanningRecommendationCard[],
  recommendationNotes: string[],
): string | null {
  if (risks.length > 0) {
    const top = risks[0];
    return `${top.title}${top.mustResolveBefore ? `。${top.mustResolveBefore}までに解消が必要です。` : ""}`;
  }
  if (recommendationCards.length > 0) {
    return recommendationCards[0].action;
  }
  return recommendationNotes[0] ?? null;
}

function buildPlanningDecisionSummary(
  risks: PlanningRiskHighlight[],
  recommendationCards: PlanningRecommendationCard[],
  recommendationNotes: string[],
): PlanningDecisionSummary | null {
  if (risks.length > 0) {
    const topRisk = risks[0];
    return {
      label: "最優先リスク",
      title: topRisk.title,
      description: topRisk.description,
      owner: topRisk.owner,
      due: topRisk.mustResolveBefore,
      emphasis: topRisk.severity,
    };
  }
  if (recommendationCards.length > 0) {
    const topRecommendation = recommendationCards[0];
    return {
      label: "最優先アクション",
      title: topRecommendation.action,
      description: topRecommendation.rationale ?? "この論点を先に固めると、次フェーズの判断が安定します。",
      due: topRecommendation.target,
      emphasis: topRecommendation.priority,
    };
  }
  if (recommendationNotes.length > 0) {
    return {
      label: "確認事項",
      title: recommendationNotes[0],
      description: "この論点を planning の前提として扱い、デザインへ渡す判断材料にします。",
    };
  }
  return null;
}

export type PlanningStep =
  | "analyze"
  | "analyzing"
  | "review"
  | "features"
  | "milestones"
  | "epics"
  | "gantt";

export type PlanningReviewTab =
  | "overview"
  | "persona"
  | "kano"
  | "stories"
  | "journey"
  | "jtbd"
  | "ia"
  | "actors"
  | "usecases"
  | "design-tokens";

const PLANNING_REVIEW_TAB_SET = new Set<PlanningReviewTab>([
  "overview",
  "persona",
  "kano",
  "stories",
  "journey",
  "jtbd",
  "ia",
  "actors",
  "usecases",
  "design-tokens",
]);

function backendPlanningCouncilCards(analysis: AnalysisResult): PlanningCouncilCard[] {
  return (analysis.operator_copy?.council_cards ?? []).map((card) => ({
    id: card.id,
    agent: card.agent,
    lens: card.lens,
    title: card.title,
    summary: card.summary,
    actionLabel: card.action_label,
    targetTab: card.target_tab && PLANNING_REVIEW_TAB_SET.has(card.target_tab as PlanningReviewTab)
      ? card.target_tab as PlanningReviewTab
      : undefined,
    targetSection: card.target_section,
    tone: card.tone,
  })).filter((card) => card.agent || card.title || card.summary);
}

function isMalformedPlanningOperatorCopy(value: string | undefined): boolean {
  if (!value) return true;
  const normalized = value.trim();
  return (
    normalized.length < 2
    || /^[をがにでと、]/.test(normalized)
    || /\b(?:design|build|release|readiness|first-class|workflow|milestone|evidence|falsifiability)\b/i.test(normalized)
  );
}

function backendPlanningHandoffBrief(analysis: AnalysisResult): PlanningHandoffBrief | null {
  const brief = analysis.operator_copy?.handoff_brief;
  if (!brief) return null;
  if (!brief.headline && !brief.summary && brief.bullets.length === 0) return null;
  return {
    headline: brief.headline,
    summary: brief.summary,
    bullets: brief.bullets,
  };
}

function pickPlanningKanoFocus(analysis: AnalysisResult) {
  const categoryRank: Record<string, number> = {
    attractive: 0,
    "one-dimensional": 1,
    "must-be": 2,
    indifferent: 3,
    reverse: 4,
  };
  return [...analysis.kano_features]
    .sort((left, right) => {
      const categoryGap = (categoryRank[left.category] ?? 99) - (categoryRank[right.category] ?? 99);
      if (categoryGap !== 0) return categoryGap;
      return right.user_delight - left.user_delight;
    })[0] ?? null;
}

function buildPlanningCouncilCards(
  analysis: AnalysisResult,
  risks: PlanningRiskHighlight[],
  recommendationCards: PlanningRecommendationCard[],
  recommendationNotes: string[],
): PlanningCouncilCard[] {
  const topRisk = risks[0] ?? null;
  const topRecommendation = recommendationCards[0] ?? null;
  const topPersona = analysis.personas[0] ?? null;
  const topKano = pickPlanningKanoFocus(analysis);
  const topKillCriterion = analysis.kill_criteria?.[0] ?? null;
  const topMilestone = analysis.recommended_milestones?.[0] ?? null;
  const designStyle = analysis.design_tokens?.style?.name ?? "";
  const cards: PlanningCouncilCard[] = [];

  if (topRecommendation) {
    cards.push({
      id: "product-council",
      agent: "プロダクト評議",
      lens: "価値判断",
      title: topRecommendation.action,
      summary: topRecommendation.rationale ?? "価値仮説を崩さずに次フェーズへ渡すための最優先判断です。",
      actionLabel: "推奨アクションへ",
      targetSection: "recommendation",
      tone: topRecommendation.priority,
    });
  }

  if (topRisk) {
    cards.push({
      id: "research-council",
      agent: "リサーチ評議",
      lens: "検証リスク",
      title: topRisk.title,
      summary: topRisk.description,
      actionLabel: "主要リスクへ",
      targetSection: "risk",
      tone: topRisk.severity,
    });
  } else if (recommendationNotes[0]) {
    cards.push({
      id: "research-council",
      agent: "リサーチ評議",
      lens: "未解決前提",
      title: "企画に持ち込む前提があります",
      summary: recommendationNotes[0],
      actionLabel: "確認事項へ",
      targetSection: "recommendation",
      tone: "medium",
    });
  }

  if (designStyle || topKano) {
    cards.push({
      id: "design-council",
      agent: "デザイン評議",
      lens: "体験の軸",
      title: designStyle || `${topKano?.feature ?? "主要機能"}を体験の核に据える`,
      summary: designStyle
        ? `${designStyle}を基調に、${topKano?.feature ? `「${topKano.feature}」を主体験として強調します。` : "次フェーズの比較軸を揃えます。"}`
        : `${topKano?.feature ?? "主要機能"}は ${topKano ? `${topKano.user_delight.toFixed(1)} の満足度` : "高い価値仮説"}を持つため、デザインの主導線として扱います。`,
      actionLabel: designStyle ? "デザイントークンへ" : "KANO へ",
      targetTab: designStyle ? "design-tokens" : "kano",
      tone: "high",
    });
  }

  if (topKillCriterion || topMilestone || topPersona) {
    cards.push({
      id: "delivery-council",
      agent: "デリバリー評議",
      lens: "実行条件",
      title: topKillCriterion?.condition || topMilestone?.name || `${topPersona?.name ?? "主要ユーザー"}の体験を先に固める`,
      summary:
        topKillCriterion?.rationale
        || topMilestone?.criteria
        || `${topPersona?.name ?? "主要ユーザー"}の文脈と主要ユースケースを先に固定すると、開発の手戻りが減ります。`,
      actionLabel: topKillCriterion ? "中止基準へ" : topMilestone ? "ユースケースへ" : "ペルソナへ",
      targetTab: topKillCriterion ? "overview" : topMilestone ? "usecases" : "persona",
      tone: topKillCriterion ? "high" : "medium",
    });
  }

  return cards;
}

function buildPlanningHandoffBrief(
  analysis: AnalysisResult,
  risks: PlanningRiskHighlight[],
  recommendationCards: PlanningRecommendationCard[],
  recommendationNotes: string[],
): PlanningHandoffBrief {
  const topRisk = risks[0] ?? null;
  const topRecommendation = recommendationCards[0] ?? null;
  const topPersona = analysis.personas[0] ?? null;
  const topUseCase = analysis.use_cases?.[0] ?? null;
  const topKano = pickPlanningKanoFocus(analysis);
  const designStyle = analysis.design_tokens?.style?.name ?? "";
  const topKillCriterion = analysis.kill_criteria?.[0] ?? null;
  const bullets = [
    topRecommendation ? `最初に固める判断: ${topRecommendation.action}` : null,
    topRisk ? `未解決リスク: ${topRisk.title}${topRisk.mustResolveBefore ? `（${topRisk.mustResolveBefore}まで）` : ""}` : null,
    (topPersona || topUseCase) ? `中心体験: ${(topPersona?.name ?? "主要ユーザー")} / ${topUseCase?.title ?? "主要ユースケースを設計基準にする"}` : null,
    topKano ? `価値の主導線: ${topKano.feature}を ${topKano.user_delight.toFixed(1)} の満足度仮説で優先する` : null,
    designStyle ? `UI の方向性: ${designStyle}` : null,
    topKillCriterion ? `停止条件: ${topKillCriterion.condition}` : null,
    recommendationNotes[0] ? `持ち込む前提: ${recommendationNotes[0]}` : null,
  ].filter((item): item is string => Boolean(item)).slice(0, 5);

  return {
    headline: topRecommendation?.action || topRisk?.title || "デザインへ渡す判断パケットを整理しました。",
    summary: topRisk
      ? `${topRisk.title} を未解決の前提として管理しつつ、デザインでは中心体験と判断基準を先に比較できるようにします。`
      : "デザインでは主導線、判断基準、停止条件が先に分かる状態で比較を始めます。",
    bullets,
  };
}

export function selectPlanningReviewViewModel(analysis: AnalysisResult) {
  const riskHighlights = sortPlanningRisks(planningRiskHighlights(analysis));
  const recommendationResult = planningRecommendationCards(analysis);
  const structuredRecommendations = sortPlanningRecommendations(recommendationResult.cards);
  const recommendationNotes = recommendationResult.notes;
  const heroRiskCount = riskHighlights.length;
  const highPriorityRecommendationCount = structuredRecommendations.filter(
    (item) => (PLANNING_RECOMMENDATION_PRIORITY_ORDER[item.priority] ?? 99) <= 1,
  ).length;
  const killCriteriaCount = analysis.kill_criteria?.length ?? 0;
  const negativePersonaCount = analysis.negative_personas?.length ?? 0;
  const traceabilityCount = analysis.traceability?.length ?? 0;
  const decisionSummary = buildPlanningDecisionSummary(
    riskHighlights,
    structuredRecommendations,
    recommendationNotes,
  );
  const localizedCouncilCards = backendPlanningCouncilCards(analysis);
  const localizedHandoffBrief = backendPlanningHandoffBrief(analysis);
  const localizedCouncilCardsUsable =
    localizedCouncilCards.length > 0
    && localizedCouncilCards.every((card) => (
      !isMalformedPlanningOperatorCopy(card.agent)
      && !isMalformedPlanningOperatorCopy(card.title)
      && !isMalformedPlanningOperatorCopy(card.summary)
      && !isMalformedPlanningOperatorCopy(card.actionLabel)
    ));
  const councilCards = localizedCouncilCardsUsable
    ? localizedCouncilCards
    : buildPlanningCouncilCards(
      analysis,
      riskHighlights,
      structuredRecommendations,
      recommendationNotes,
    );
  const handoffBrief = localizedHandoffBrief
    ?? buildPlanningHandoffBrief(
      analysis,
      riskHighlights,
      structuredRecommendations,
      recommendationNotes,
    );
  const coverageSummary = analysis.coverage_summary ?? null;
  const selectedFeatureCount = coverageSummary?.selected_feature_count ?? analysis.feature_decisions?.filter((item) => item.selected).length ?? 0;
  const traceabilityCoverage = selectedFeatureCount > 0
    ? Math.min(100, Math.round(((coverageSummary?.traceability_count ?? 0) / selectedFeatureCount) * 100))
    : null;
  const standardPreset = coverageSummary?.preset_breakdown.find((item) => item.preset === "standard")
    ?? coverageSummary?.preset_breakdown[0]
    ?? null;
  return {
    reviewTabs: [
      { key: "overview" as const, label: "概要", hidden: false },
      { key: "persona" as const, label: "ペルソナ", hidden: false },
      { key: "journey" as const, label: "ジャーニー", hidden: !analysis.user_journeys?.length },
      { key: "jtbd" as const, label: "ジョブストーリー", hidden: !analysis.job_stories?.length },
      { key: "kano" as const, label: "価値分類", hidden: false },
      { key: "stories" as const, label: "ストーリー", hidden: false },
      { key: "actors" as const, label: "アクター/ロール", hidden: !analysis.actors?.length && !analysis.roles?.length },
      { key: "usecases" as const, label: "ユースケース", hidden: !analysis.use_cases?.length },
      { key: "ia" as const, label: "IA分析", hidden: !analysis.ia_analysis },
      { key: "design-tokens" as const, label: "デザイントークン", hidden: !analysis.design_tokens },
    ],
    heroStats: [
      { label: "重要リスク", value: heroRiskCount },
      { label: "高優先アクション", value: highPriorityRecommendationCount },
      { label: "中止基準", value: killCriteriaCount },
      { label: "持ち込む前提", value: recommendationNotes.length },
    ],
    overviewStats: [
      { label: "重要リスク", value: heroRiskCount },
      { label: "高優先アクション", value: highPriorityRecommendationCount },
      { label: "却下済み", value: analysis.rejected_features?.length ?? 0 },
      { label: "トレーサビリティ", value: traceabilityCount },
      { label: "負のペルソナ", value: negativePersonaCount },
      { label: "中止基準", value: killCriteriaCount },
    ],
    kanoDistribution: [
      {
        label: "当たり前品質",
        count: analysis.kano_features.filter((feature) => feature.category === "must-be").length,
        color: "bg-destructive/10 text-destructive",
      },
      {
        label: "一元的品質",
        count: analysis.kano_features.filter((feature) => feature.category === "one-dimensional").length,
        color: "bg-primary/10 text-primary",
      },
      {
        label: "魅力品質",
        count: analysis.kano_features.filter((feature) => feature.category === "attractive").length,
        color: "bg-success/10 text-success",
      },
    ],
    focusSummary: summarizePlanningFocus(riskHighlights, structuredRecommendations, recommendationNotes),
    decisionSummary,
    coverageSummary: coverageSummary
      ? {
          tiles: [
            { label: "選択機能", value: coverageSummary.selected_feature_count },
            { label: "ユースケース", value: coverageSummary.use_case_count },
            { label: "ジョブ", value: coverageSummary.job_story_count },
            { label: "接続率", value: traceabilityCoverage === null ? "—" : `${traceabilityCoverage}%` },
          ],
          notes: [
            standardPreset
              ? `標準構成は ${standardPreset.epic_count} エピック / ${standardPreset.wbs_count} タスク / ${standardPreset.total_effort_hours}h です。`
              : "",
            coverageSummary.uncovered_features.length > 0
              ? `未接続の機能: ${coverageSummary.uncovered_features.slice(0, 3).join("、")}`
              : "主要機能はトレーサビリティに接続されています。",
            coverageSummary.use_cases_without_milestone.length > 0
              ? `マイルストーン未接続: ${coverageSummary.use_cases_without_milestone.slice(0, 2).join("、")}`
              : "主要ユースケースはマイルストーンに割り当て済みです。",
            coverageSummary.use_cases_without_traceability.length > 0
              ? `根拠未接続: ${coverageSummary.use_cases_without_traceability.slice(0, 2).join("、")}`
              : "主要ユースケースは根拠トレース済みです。",
          ].filter((item): item is string => Boolean(item)),
        }
      : null,
    councilCards,
    handoffBrief,
    riskHighlights,
    structuredRecommendations,
    recommendationNotes,
  };
}

export function selectPlanningViewModel(
  view: Pick<LifecycleWorkspaceView, "analysis" | "spec">,
) {
  const analysis = selectPlanningAnalysis(view);
  return {
    analysis,
    hasAnalysis: view.analysis != null,
    initialStep: (view.analysis ? "review" : "analyze") as Exclude<PlanningStep, "analyzing">,
    canRunAnalysis: !!view.spec.trim(),
    review: selectPlanningReviewViewModel(analysis),
  };
}

const DEFAULT_DEVELOPMENT_TEAM: LifecycleAgentBlueprint[] = [
  { id: "planner", label: "ビルド設計", role: "作業分解", autonomy: "A2", tools: [], skills: [] },
  { id: "frontend-builder", label: "フロントエンド", role: "UI 実装", autonomy: "A2", tools: [], skills: [] },
  { id: "backend-builder", label: "バックエンド", role: "Domain 設計", autonomy: "A2", tools: [], skills: [] },
  { id: "integrator", label: "インテグレーター", role: "統合", autonomy: "A2", tools: [], skills: [] },
  { id: "repo-executor", label: "Repo Executor", role: "実行検証", autonomy: "A2", tools: [], skills: [] },
  { id: "reviewer", label: "リリースレビュー", role: "品質判定", autonomy: "A2", tools: [], skills: [] },
];

const DEVELOPMENT_AUTH_SCOPE_HINTS = [
  "auth",
  "authentication",
  "authorization",
  "login",
  "logout",
  "log in",
  "log out",
  "sign in",
  "sign out",
  "signin",
  "signout",
  "session",
  "sso",
  "oauth",
  "permission",
  "permissions",
  "role",
  "roles",
  "access control",
  "forbidden",
  "認証",
  "認可",
  "ログイン",
  "ログアウト",
  "セッション",
  "権限",
  "ロール",
  "アクセス制御",
] as const;

function containsDevelopmentHint(text: string | null | undefined, hints: readonly string[]): boolean {
  const normalized = (text ?? "").trim().toLowerCase();
  return normalized.length > 0 && hints.some((hint) => normalized.includes(hint));
}

function hasDesignTokenContract(analysis: AnalysisResult | null | undefined): boolean {
  const tokens = analysis?.design_tokens;
  if (!tokens) return false;
  return Boolean(
    tokens.style?.name
    && tokens.colors?.primary
    && tokens.colors?.secondary
    && tokens.colors?.cta
    && tokens.colors?.background
    && tokens.colors?.text
    && tokens.typography?.heading
    && tokens.typography?.body,
  );
}

function interactionSpecCount(analysis: AnalysisResult | null | undefined, selectedDesign: DesignVariant | null): number {
  const direct = selectedDesign?.prototype?.interaction_principles ?? [];
  const effects = analysis?.design_tokens?.effects ?? [];
  return new Set([...direct, ...effects].filter((item) => item.trim().length > 0)).size;
}

function rolePermissionCount(analysis: AnalysisResult | null | undefined): number {
  return (analysis?.roles ?? []).reduce((sum, role) => (
    sum + role.permissions.filter((permission) => permission.trim().length > 0).length
  ), 0);
}

function developmentSurfaceTexts(selectedDesign: DesignVariant | null): string[] {
  const screenSpecTexts = (selectedDesign?.screen_specs ?? []).flatMap((screen) => [
    screen.id,
    screen.title,
    screen.purpose,
    screen.layout,
    screen.route_path ?? "",
    ...screen.primary_actions,
  ]);
  const prototypeScreenTexts = (selectedDesign?.prototype?.screens ?? []).flatMap((screen) => [
    screen.id,
    screen.title,
    screen.purpose,
    screen.headline,
    screen.supporting_text,
    ...screen.primary_actions,
  ]);
  const routeTexts = (selectedDesign?.prototype_spec?.routes ?? []).flatMap((route) => [
    route.id,
    route.screen_id,
    route.path,
    route.title,
    route.headline,
    route.layout,
    ...route.primary_actions,
    ...route.states,
  ]);
  return [...screenSpecTexts, ...prototypeScreenTexts, ...routeTexts].filter((item) => item.trim().length > 0);
}

function hasExplicitAccessBoundary(params: {
  analysis: AnalysisResult | null | undefined;
  requirements: RequirementsBundle | null | undefined;
  taskDecomposition: TaskDecomposition | null | undefined;
  technicalDesign: TechnicalDesignBundle | null | undefined;
  selectedDesign: DesignVariant | null;
  selectedFeatures: ReturnType<typeof selectSelectedFeatures>;
}): boolean {
  const requirementTexts = (params.requirements?.requirements ?? []).flatMap((requirement) => [
    requirement.statement,
    ...requirement.acceptanceCriteria,
  ]);
  const taskTexts = (params.taskDecomposition?.tasks ?? []).flatMap((task) => [
    task.title,
    task.description,
  ]);
  const apiTexts = (params.technicalDesign?.apiSpecification ?? []).flatMap((endpoint) => [
    endpoint.path,
    endpoint.description,
  ]);
  const featureTexts = params.selectedFeatures.map((feature) => feature.feature);
  const candidateTexts = [
    ...featureTexts,
    ...requirementTexts,
    ...taskTexts,
    ...apiTexts,
    ...developmentSurfaceTexts(params.selectedDesign),
  ];
  return candidateTexts.some((text) => containsDevelopmentHint(text, DEVELOPMENT_AUTH_SCOPE_HINTS));
}

export function selectDevelopmentViewModel(
  view:
    Pick<
      LifecycleWorkspaceView,
      "approvalStatus" | "blueprints" | "designVariants" | "milestones" | "selectedDesignId" | "features"
      | "requirements" | "taskDecomposition" | "dcsAnalysis" | "technicalDesign" | "reverseEngineering" | "analysis"
    >
    & Partial<
      Pick<LifecycleWorkspaceView, "deliveryPlan" | "developmentHandoff" | "planEstimates" | "selectedPreset">
    >,
) {
  const buildTeam = selectPhaseTeam(view, "development", DEFAULT_DEVELOPMENT_TEAM);
  const selectedFeatures = selectSelectedFeatures(view);
  const selectedFeatureCount = selectSelectedFeatureCount(view);
  const selectedDesign = selectSelectedDesign(view);
  const deliveryPlan = selectDeliveryPlanPreview(view, selectedDesign);
  const developmentHandoff = view.developmentHandoff ?? null;
  const specAudit = deliveryPlan?.spec_audit ?? null;
  const codeWorkspace = deliveryPlan?.code_workspace ?? null;
  const repoExecution = deliveryPlan?.repo_execution ?? null;
  const milestoneCount = view.milestones.length;
  const screenCount = selectedDesign?.screen_specs?.length
    ?? selectedDesign?.prototype?.screens?.length
    ?? selectedDesign?.artifact_completeness?.screen_count
    ?? 0;
  const workflowCount = selectedDesign?.primary_workflows?.length
    ?? selectedDesign?.prototype?.flows?.length
    ?? selectedDesign?.artifact_completeness?.workflow_count
    ?? 0;
  const routeCount = selectedDesign?.prototype_app?.artifact_summary?.route_count
    ?? selectedDesign?.prototype_spec?.routes?.length
    ?? selectedDesign?.artifact_completeness?.route_count
    ?? 0;
  const fileCount = selectedDesign?.prototype_app?.artifact_summary?.file_count
    ?? selectedDesign?.prototype_app?.files?.length
    ?? 0;
  const packageCount = codeWorkspace?.artifact_summary?.package_count
    ?? codeWorkspace?.package_tree.length
    ?? 0;
  const workspaceFileCount = codeWorkspace?.artifact_summary?.file_count
    ?? codeWorkspace?.files.length
    ?? 0;
  const routeBindingCount = codeWorkspace?.artifact_summary?.route_binding_count
    ?? codeWorkspace?.route_bindings.length
    ?? 0;
  const unresolvedGapCount = specAudit?.unresolved_gaps.length ?? 0;
  const protectedApiCount = (view.technicalDesign?.apiSpecification ?? []).filter((endpoint) => endpoint.authRequired).length;
  const designContractReady = hasDesignTokenContract(view.analysis);
  const motionContractReady = interactionSpecCount(view.analysis, selectedDesign) > 0;
  const declaredRoleCount = view.analysis?.roles?.length ?? 0;
  const declaredPermissionCount = rolePermissionCount(view.analysis);
  const accessBoundaryReady = protectedApiCount === 0 || (
    hasExplicitAccessBoundary({
      analysis: view.analysis,
      requirements: view.requirements,
      taskDecomposition: view.taskDecomposition,
      technicalDesign: view.technicalDesign,
      selectedDesign,
      selectedFeatures,
    })
    && (declaredRoleCount === 0 || declaredPermissionCount > 0)
  );
  const hasSpecFoundation = Boolean(
    view.requirements
    && view.taskDecomposition
    && view.technicalDesign
    && view.dcsAnalysis,
  );
  const preflightItems = [
    { label: "承認ゲートを通過している", done: view.approvalStatus === "approved" },
    { label: "比較済みのデザインが選択されている", done: selectedDesign != null },
    {
      label: "選択案の引き継ぎ情報が最新かつ完全である",
      done:
        selectedDesign != null
        && selectedDesign.freshness?.can_handoff !== false
        && selectedDesign.freshness?.status !== "stale"
        && selectedDesign.artifact_completeness?.status === "complete"
        && selectedDesign.preview_meta?.validation_ok === true,
    },
    {
      label: "requirements / task DAG / technical design が揃っている",
      done: hasSpecFoundation,
    },
    {
      label: "デザイントークンとマイクロインタラクションが定義されている",
      done: designContractReady && motionContractReady,
    },
    {
      label: "認証・認可の境界が仕様化されている",
      done: accessBoundaryReady,
    },
    { label: "選択機能が存在する", done: selectedFeatureCount > 0 },
    { label: "マイルストーンが定義されている", done: milestoneCount > 0 },
  ];
  const completedPreflightCount = preflightItems.filter((item) => item.done).length;
  const workPackageCount = deliveryPlan?.work_packages.length ?? 0;
  const dependencyEdgeCount = deliveryPlan?.work_packages.reduce(
    (sum, item) => sum + item.depends_on.length,
    0,
  ) ?? 0;
  const criticalPathCount = deliveryPlan?.critical_path.length ?? 0;
  const conflictGuardCount = deliveryPlan?.lanes.reduce(
    (sum, lane) => sum + lane.conflict_guards.length,
    0,
  ) ?? 0;
  const deployChecklistCount = developmentHandoff?.deploy_checklist.length ?? 0;
  const selectedPlanEstimate = selectPlanEstimateForDevelopment(view);

  return {
    buildTeam,
    selectedFeatureCount,
    selectedDesign,
    deliveryPlan,
    developmentHandoff,
    selectedPlanEstimate,
    milestoneCount,
    screenCount,
    workflowCount,
    routeCount,
    fileCount,
    packageCount,
    workspaceFileCount,
    routeBindingCount,
    unresolvedGapCount,
    workPackageCount,
    dependencyEdgeCount,
    criticalPathCount,
    conflictGuardCount,
    deployChecklistCount,
    specAudit,
    codeWorkspace,
    repoExecution,
    preflightItems,
    completedPreflightCount,
    readinessProgressPercent: (completedPreflightCount / preflightItems.length) * 100,
    maxIterations: milestoneCount > 0 ? 5 : 1,
    canStartBuild:
      view.approvalStatus === "approved"
      && selectedFeatureCount > 0
      && selectedDesign != null
      && completedPreflightCount === preflightItems.length,
  };
}

export function selectApprovalViewModel(
  view: Pick<
    LifecycleWorkspaceView,
    "analysis" | "approvalStatus" | "features" | "milestones" | "research" | "selectedDesignId" | "designVariants" | "spec"
  >,
) {
  const selectedFeatures = selectSelectedFeatures(view);
  const selectedFeatureCount = selectSelectedFeatureCount(view);
  const selectedDesign = selectSelectedDesign(view);
  const milestoneCount = view.milestones.length;
  const selectedScreenCount = selectedDesign?.screen_specs?.length
    ?? selectedDesign?.prototype?.screens?.length
    ?? selectedDesign?.artifact_completeness?.screen_count
    ?? 0;
  const selectedWorkflowCount = selectedDesign?.primary_workflows?.length
    ?? selectedDesign?.prototype?.flows?.length
    ?? selectedDesign?.artifact_completeness?.workflow_count
    ?? 0;
  const selectedRouteCount = selectedDesign?.prototype_app?.artifact_summary?.route_count
    ?? selectedDesign?.prototype_spec?.routes?.length
    ?? selectedDesign?.artifact_completeness?.route_count
    ?? 0;
  const designIntegrityReady =
    selectedDesign != null
    && selectedDesign.preview_meta?.validation_ok === true
    && selectedDesign.freshness?.can_handoff !== false
    && selectedDesign.freshness?.status !== "stale"
    && selectedDesign.artifact_completeness?.status === "complete";
  const approvalPacketReady =
    selectedDesign != null
    && Boolean(selectedDesign.approval_packet)
    && Boolean(selectedDesign.scorecard)
    && (selectedDesign.primary_workflows?.length ?? 0) > 0
    && (selectedDesign.screen_specs?.length ?? 0) > 0;
  const checkItems = [
    { label: "プロダクト仕様が明確", done: !!view.spec.trim(), phase: "research" as const },
    { label: "UX分析が完了", done: !!view.analysis, phase: "planning" as const },
    { label: "機能スコープが確定", done: selectedFeatureCount > 0, phase: "planning" as const },
    { label: "デザインパターンが選択済み", done: !!view.selectedDesignId, phase: "design" as const },
    { label: "選択案の鮮度とプレビュー契約が有効", done: designIntegrityReady, phase: "design" as const },
    { label: "承認パケットと判断シートが揃っている", done: approvalPacketReady, phase: "design" as const },
    { label: "マイルストーンが定義済み", done: milestoneCount > 0, phase: "planning" as const },
  ];
  const completedChecklistCount = checkItems.filter((item) => item.done).length;

  return {
    selectedFeatures,
    selectedFeatureCount,
    selectedDesign,
    milestoneCount,
    selectedScreenCount,
    selectedWorkflowCount,
    selectedRouteCount,
    designIntegrityReady,
    approvalPacketReady,
    reviewLinks: [
      { label: "調査を確認", phase: "research" as const, ready: !!view.research },
      { label: "企画を修正", phase: "planning" as const, ready: !!view.analysis },
      { label: "デザインを修正", phase: "design" as const, ready: !!view.selectedDesignId },
    ],
    checkItems,
    allChecked: completedChecklistCount === checkItems.length,
    completedChecklistCount,
    checklistProgressPercent: (completedChecklistCount / checkItems.length) * 100,
  };
}

export function selectIterateViewModel(
  view: Pick<
    LifecycleWorkspaceView,
    "feedbackItems" | "recommendations" | "releases" | "phaseStatuses"
  >,
) {
  const sortedFeedback = selectSortedFeedbackItems(view);
  const byType = {
    bug: view.feedbackItems.filter((item) => item.type === "bug").length,
    feature: view.feedbackItems.filter((item) => item.type === "feature").length,
    improvement: view.feedbackItems.filter((item) => item.type === "improvement").length,
    praise: view.feedbackItems.filter((item) => item.type === "praise").length,
  };
  const priorityRank: Record<string, number> = { critical: 0, high: 1, medium: 2 };
  const sortedRecommendations = [...view.recommendations].sort(
    (left, right) => (priorityRank[left.priority] ?? 9) - (priorityRank[right.priority] ?? 9),
  );

  return {
    latestRelease: view.releases[0],
    feedbackCount: view.feedbackItems.length,
    sortedFeedback,
    topFeedback: sortedFeedback[0] ?? null,
    byType,
    sortedRecommendations,
    completedPhaseCount: selectCompletedPhaseCount(view),
  };
}

export function selectRequirementsState(view: Pick<LifecycleWorkspaceView, "requirements">): RequirementsBundle | null {
  return view.requirements ?? null;
}

export function selectTaskDecompositionState(view: Pick<LifecycleWorkspaceView, "taskDecomposition">): TaskDecomposition | null {
  return view.taskDecomposition ?? null;
}

export function selectDCSAnalysisState(view: Pick<LifecycleWorkspaceView, "dcsAnalysis">): DCSAnalysis | null {
  return view.dcsAnalysis ?? null;
}

export function selectTechnicalDesignState(view: Pick<LifecycleWorkspaceView, "technicalDesign">): TechnicalDesignBundle | null {
  return view.technicalDesign ?? null;
}
