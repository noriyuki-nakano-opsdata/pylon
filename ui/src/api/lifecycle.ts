import { apiFetch, ApiError } from "./client";
import type { WorkflowRun } from "./workflows";
import type {
  LifecyclePhase,
  LifecycleNextAction,
  MarketResearch,
  Competitor,
  AnalysisResult,
  Persona,
  UserStory,
  KanoFeature,
  FeatureSelection,
  DesignVariant,
  MilestoneResult,
  PlanEstimate,
  PlanPreset,
  Epic,
  WbsItem,
  UserJourneyMap,
  JourneyTouchpoint,
  JourneyPhase,
  JobStory,
  IAAnalysis,
  IANode,
  Actor,
  Role,
  UseCase,
  RecommendedMilestone,
  PhaseBlueprint,
  LifecycleProject,
  LifecycleOrchestrationMode,
  ApprovalComment,
  DeployCheck,
  ReleaseRecord,
  FeedbackItem,
  LifecycleRecommendation,
} from "@/types/lifecycle";

/* ── API Functions ── */

interface LifecycleProjectListResponse {
  projects: LifecycleProject[];
  count: number;
}

interface LifecyclePhasePreparation {
  project_id: string;
  phase: LifecyclePhase;
  workflow_id: string;
  blueprint: PhaseBlueprint;
  workflow: Record<string, unknown>;
}

interface LifecyclePhaseSyncResponse {
  project: LifecycleProject;
  phase_run: Record<string, unknown> | null;
}

interface LifecycleBlueprintResponse {
  project_id: string;
  tenant_id: string;
  blueprints: Record<LifecyclePhase, PhaseBlueprint>;
}

interface LifecycleDeployChecksResponse {
  checks: DeployCheck[];
  summary: {
    overallScore: number;
    releaseReady: boolean;
    passed: number;
    warnings: number;
    failed: number;
  };
  project: LifecycleProject;
}

interface LifecycleMutationResponse extends LifecycleProject {
  project: LifecycleProject;
  actions: Record<string, unknown>[];
  nextAction: LifecycleNextAction;
}

export function lifecycleWorkflowId(
  phase: LifecyclePhase,
  projectSlug: string,
): string {
  return `lifecycle-${phase}-${projectSlug}`;
}

export const lifecycleApi = {
  listProjects(): Promise<LifecycleProjectListResponse> {
    return apiFetch<LifecycleProjectListResponse>("/v1/lifecycle/projects");
  },

  getProject(projectSlug: string): Promise<LifecycleProject> {
    return apiFetch<LifecycleProject>(`/v1/lifecycle/projects/${projectSlug}`);
  },

  saveProject(
    projectSlug: string,
    payload: Partial<LifecycleProject>,
    options: { autoRun?: boolean; maxSteps?: number } = {},
  ): Promise<LifecycleMutationResponse> {
    const body: Record<string, unknown> = { ...payload };
    if (options.autoRun !== undefined) body.auto_run = options.autoRun;
    if (options.maxSteps !== undefined) body.max_steps = options.maxSteps;
    return apiFetch<LifecycleMutationResponse>(`/v1/lifecycle/projects/${projectSlug}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  advanceProject(
    projectSlug: string,
    options: {
      orchestrationMode?: LifecycleOrchestrationMode;
      maxSteps?: number;
    } = {},
  ): Promise<LifecycleMutationResponse> {
    const body: Record<string, unknown> = {};
    if (options.orchestrationMode) body.orchestration_mode = options.orchestrationMode;
    if (options.maxSteps !== undefined) body.max_steps = options.maxSteps;
    return apiFetch<LifecycleMutationResponse>(`/v1/lifecycle/projects/${projectSlug}/advance`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  getBlueprints(projectSlug: string): Promise<LifecycleBlueprintResponse> {
    return apiFetch<LifecycleBlueprintResponse>(`/v1/lifecycle/projects/${projectSlug}/blueprint`);
  },

  async preparePhase(
    phase: LifecyclePhase,
    projectSlug: string,
  ): Promise<LifecyclePhasePreparation> {
    try {
      return await apiFetch<LifecyclePhasePreparation>(
        `/v1/lifecycle/projects/${projectSlug}/phases/${phase}/prepare`,
        { method: "POST" },
      );
    } catch (err) {
      if (err instanceof ApiError && err.body) {
        const detail = JSON.stringify(err.body, null, 2);
        throw new Error(`Lifecycle phase preparation failed (${err.status}): ${detail}`);
      }
      throw err;
    }
  },

  async startRun(
    workflowId: string,
    input: Record<string, unknown>,
  ): Promise<{ runId: string }> {
    const res = await apiFetch<{ id: string }>(
      `/v1/workflows/${workflowId}/runs`,
      {
        method: "POST",
        body: JSON.stringify({ input }),
      },
    );
    return { runId: res.id };
  },

  syncPhaseRun(
    projectSlug: string,
    phase: LifecyclePhase,
    runId: string,
  ): Promise<LifecyclePhaseSyncResponse> {
    return apiFetch<LifecyclePhaseSyncResponse>(`/v1/lifecycle/projects/${projectSlug}/phases/${phase}/sync`, {
      method: "POST",
      body: JSON.stringify({ run_id: runId }),
    });
  },

  async getRun(runId: string): Promise<WorkflowRun> {
    return apiFetch<WorkflowRun>(`/v1/runs/${runId}`);
  },

  async getLatestRun(
    workflowId: string,
  ): Promise<WorkflowRun | null> {
    try {
      const res = await apiFetch<{ runs: WorkflowRun[] }>(`/v1/workflows/${workflowId}/runs`);
      if (!res.runs || res.runs.length === 0) return null;
      // Return the most recent run (first in list)
      return res.runs[0];
    } catch {
      return null;
    }
  },

  addApprovalComment(
    projectSlug: string,
    payload: Pick<ApprovalComment, "text" | "type">,
  ): Promise<LifecycleProject> {
    return apiFetch<LifecycleProject>(`/v1/lifecycle/projects/${projectSlug}/approval/comments`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  decideApproval(
    projectSlug: string,
    decision: LifecycleProject["approvalStatus"],
    comment = "",
  ): Promise<LifecycleProject> {
    return apiFetch<LifecycleProject>(`/v1/lifecycle/projects/${projectSlug}/approval/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, comment }),
    });
  },

  runDeployChecks(projectSlug: string, buildCode?: string): Promise<LifecycleDeployChecksResponse> {
    return apiFetch<LifecycleDeployChecksResponse>(`/v1/lifecycle/projects/${projectSlug}/deploy/checks`, {
      method: "POST",
      body: JSON.stringify(buildCode ? { buildCode } : {}),
    });
  },

  createRelease(projectSlug: string, note = ""): Promise<{ project: LifecycleProject; release: ReleaseRecord }> {
    return apiFetch<{ project: LifecycleProject; release: ReleaseRecord }>(`/v1/lifecycle/projects/${projectSlug}/releases`, {
      method: "POST",
      body: JSON.stringify({ note }),
    });
  },

  listFeedback(projectSlug: string): Promise<{ feedbackItems: FeedbackItem[]; recommendations: LifecycleRecommendation[] }> {
    return apiFetch<{ feedbackItems: FeedbackItem[]; recommendations: LifecycleRecommendation[] }>(`/v1/lifecycle/projects/${projectSlug}/feedback`);
  },

  addFeedback(
    projectSlug: string,
    payload: Pick<FeedbackItem, "text" | "type" | "impact">,
  ): Promise<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }> {
    return apiFetch<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }>(`/v1/lifecycle/projects/${projectSlug}/feedback`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  voteFeedback(
    projectSlug: string,
    feedbackId: string,
    delta: number,
  ): Promise<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }> {
    return apiFetch<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }>(`/v1/lifecycle/projects/${projectSlug}/feedback/${feedbackId}/vote`, {
      method: "POST",
      body: JSON.stringify({ delta }),
    });
  },

  getRecommendations(projectSlug: string): Promise<{ recommendations: LifecycleRecommendation[] }> {
    return apiFetch<{ recommendations: LifecycleRecommendation[] }>(`/v1/lifecycle/projects/${projectSlug}/recommendations`);
  },
};

/* ── Output Parsers ── */

function asArray<T>(val: unknown): T[] {
  return Array.isArray(val) ? (val as T[]) : [];
}

function asString(val: unknown, fallback = ""): string {
  return typeof val === "string" ? val : fallback;
}

function asNumber(val: unknown, fallback = 0): number {
  return typeof val === "number" && !Number.isNaN(val)
    ? val
    : fallback;
}

function asRecord(val: unknown): Record<string, unknown> {
  return val != null && typeof val === "object" && !Array.isArray(val)
    ? (val as Record<string, unknown>)
    : {};
}

export function parseResearchOutput(
  state: Record<string, unknown>,
): MarketResearch {
  const raw = asRecord(state.research ?? state.output ?? state);

  const parseCompetitor = (c: unknown): Competitor => {
    const r = asRecord(c);
    return {
      name: asString(r.name, "Unknown"),
      url: typeof r.url === "string" ? r.url : undefined,
      strengths: asArray<string>(r.strengths),
      weaknesses: asArray<string>(r.weaknesses),
      pricing: asString(r.pricing, "N/A"),
      target: asString(r.target, "N/A"),
    };
  };

  const techRaw = asRecord(raw.tech_feasibility);
  const userResearch = asRecord(raw.user_research ?? raw.userResearch);
  const confidenceSummary = asRecord(raw.confidence_summary ?? raw.confidenceSummary);

  return {
    competitors: asArray(raw.competitors).map(parseCompetitor),
    market_size: asString(raw.market_size, "N/A"),
    trends: asArray<string>(raw.trends),
    opportunities: asArray<string>(raw.opportunities),
    threats: asArray<string>(raw.threats),
    tech_feasibility: {
      score: asNumber(techRaw.score, 0),
      notes: asString(techRaw.notes, ""),
    },
    ...(Object.keys(userResearch).length > 0 ? {
      user_research: {
        signals: asArray<string>(userResearch.signals),
        pain_points: asArray<string>(userResearch.pain_points ?? userResearch.painPoints),
        segment: asString(userResearch.segment, "N/A"),
      },
    } : {}),
    claims: asArray(raw.claims).map((item) => {
      const r = asRecord(item);
      return {
        id: asString(r.id, `claim-${Math.random().toString(36).slice(2, 6)}`),
        statement: asString(r.statement, ""),
        owner: asString(r.owner, ""),
        category: asString(r.category, ""),
        evidence_ids: asArray<string>(r.evidence_ids ?? r.evidenceIds),
        counterevidence_ids: asArray<string>(r.counterevidence_ids ?? r.counterevidenceIds),
        confidence: asNumber(r.confidence, 0),
        status: asString(r.status, "provisional"),
      };
    }),
    evidence: asArray(raw.evidence).map((item) => {
      const r = asRecord(item);
      return {
        id: asString(r.id, `evidence-${Math.random().toString(36).slice(2, 6)}`),
        source_ref: asString(r.source_ref ?? r.sourceRef, ""),
        source_type: asString(r.source_type ?? r.sourceType, ""),
        snippet: asString(r.snippet, ""),
        recency: asString(r.recency, ""),
        relevance: asString(r.relevance, ""),
      };
    }),
    dissent: asArray(raw.dissent).map((item) => {
      const r = asRecord(item);
      return {
        id: asString(r.id, `dissent-${Math.random().toString(36).slice(2, 6)}`),
        claim_id: asString(r.claim_id ?? r.claimId, ""),
        challenger: asString(r.challenger, ""),
        argument: asString(r.argument, ""),
        severity: asString(r.severity, "medium"),
        resolved: r.resolved === true,
        recommended_test: asString(r.recommended_test ?? r.recommendedTest, "") || undefined,
        resolution: asString(r.resolution, "") || undefined,
      };
    }),
    open_questions: asArray<string>(raw.open_questions ?? raw.openQuestions),
    winning_theses: asArray<string>(raw.winning_theses ?? raw.winningTheses),
    source_links: asArray<string>(raw.source_links ?? raw.sourceLinks),
    ...(Object.keys(confidenceSummary).length > 0 ? {
      confidence_summary: {
        average: asNumber(confidenceSummary.average, 0),
        floor: asNumber(confidenceSummary.floor, 0),
        accepted: asNumber(confidenceSummary.accepted, 0) || undefined,
        critical_findings: asNumber(confidenceSummary.critical_findings ?? confidenceSummary.criticalFindings, 0) || undefined,
      },
    } : {}),
    judge_summary: asString(raw.judge_summary ?? raw.judgeSummary, "") || undefined,
    model_assignments: Object.keys(asRecord(raw.model_assignments ?? raw.modelAssignments)).length > 0
      ? Object.fromEntries(Object.entries(asRecord(raw.model_assignments ?? raw.modelAssignments)).map(([key, value]) => [key, asString(value, "")]))
      : undefined,
    low_diversity_mode: raw.low_diversity_mode === true || raw.lowDiversityMode === true,
    critical_dissent_count: asNumber(raw.critical_dissent_count ?? raw.criticalDissentCount, 0) || undefined,
    resolved_dissent_count: asNumber(raw.resolved_dissent_count ?? raw.resolvedDissentCount, 0) || undefined,
  };
}

/* ── Journey / JTBD / IA parsers ── */
const JOURNEY_PHASES: JourneyPhase[] = ["awareness", "consideration", "acquisition", "usage", "advocacy"];

function parseUserJourneys(raw: Record<string, unknown>): Pick<AnalysisResult, "user_journeys"> {
  const arr = asArray(raw.user_journeys ?? raw.userJourneys);
  if (arr.length === 0) return {};
  const journeys: UserJourneyMap[] = arr.map((j) => {
    const r = asRecord(j);
    return {
      persona_name: asString(r.persona_name ?? r.personaName, "Unknown"),
      touchpoints: asArray(r.touchpoints).map((tp) => {
        const t = asRecord(tp);
        const phase = asString(t.phase, "usage");
        const emotion = asString(t.emotion, "neutral");
        return {
          phase: (JOURNEY_PHASES.includes(phase as JourneyPhase) ? phase : "usage") as JourneyPhase,
          persona: asString(t.persona, ""),
          action: asString(t.action, ""),
          touchpoint: asString(t.touchpoint, ""),
          emotion: (["positive", "neutral", "negative"].includes(emotion) ? emotion : "neutral") as JourneyTouchpoint["emotion"],
          pain_point: t.pain_point ? asString(t.pain_point, "") : undefined,
          opportunity: t.opportunity ? asString(t.opportunity, "") : undefined,
        };
      }),
    };
  });
  return { user_journeys: journeys };
}

function parseJobStories(raw: Record<string, unknown>): Pick<AnalysisResult, "job_stories"> {
  const arr = asArray(raw.job_stories ?? raw.jobStories);
  if (arr.length === 0) return {};
  const stories: JobStory[] = arr.map((s) => {
    const r = asRecord(s);
    const priority = asString(r.priority, "supporting");
    return {
      situation: asString(r.situation, ""),
      motivation: asString(r.motivation, ""),
      outcome: asString(r.outcome, ""),
      priority: (["core", "supporting", "aspirational"].includes(priority) ? priority : "supporting") as JobStory["priority"],
      related_features: asArray<string>(r.related_features ?? r.relatedFeatures),
    };
  });
  return { job_stories: stories };
}

function parseIAAnalysis(raw: Record<string, unknown>): Pick<AnalysisResult, "ia_analysis"> {
  const ia = asRecord(raw.ia_analysis ?? raw.iaAnalysis);
  if (Object.keys(ia).length === 0) return {};
  const parseNode = (n: unknown): IANode => {
    const r = asRecord(n);
    const prio = asString(r.priority, "secondary");
    return {
      id: asString(r.id, `ia-${Math.random().toString(36).slice(2, 6)}`),
      label: asString(r.label, ""),
      description: r.description ? asString(r.description, "") : undefined,
      children: asArray(r.children).length > 0 ? asArray(r.children).map(parseNode) : undefined,
      priority: (["primary", "secondary", "utility"].includes(prio) ? prio : "secondary") as IANode["priority"],
    };
  };
  const navModel = asString(ia.navigation_model ?? ia.navigationModel, "hierarchical");
  return {
    ia_analysis: {
      site_map: asArray(ia.site_map ?? ia.siteMap).map(parseNode),
      navigation_model: (["hierarchical", "flat", "hub-and-spoke", "matrix"].includes(navModel) ? navModel : "hierarchical") as IAAnalysis["navigation_model"],
      key_paths: asArray(ia.key_paths ?? ia.keyPaths).map((p) => {
        const r = asRecord(p);
        return { name: asString(r.name, ""), steps: asArray<string>(r.steps) };
      }),
    },
  };
}

function parseActors(raw: Record<string, unknown>): Pick<AnalysisResult, "actors"> {
  const arr = asArray(raw.actors);
  if (arr.length === 0) return {};
  const actors: Actor[] = arr.map((a) => {
    const r = asRecord(a);
    const type = asString(r.type, "primary");
    return {
      name: asString(r.name, ""),
      type: (["primary", "secondary", "external_system"].includes(type) ? type : "primary") as Actor["type"],
      description: asString(r.description, ""),
      goals: asArray<string>(r.goals),
      interactions: asArray<string>(r.interactions),
    };
  });
  return { actors };
}

function parseRoles(raw: Record<string, unknown>): Pick<AnalysisResult, "roles"> {
  const arr = asArray(raw.roles);
  if (arr.length === 0) return {};
  const roles: Role[] = arr.map((rl) => {
    const r = asRecord(rl);
    return {
      name: asString(r.name, ""),
      responsibilities: asArray<string>(r.responsibilities),
      permissions: asArray<string>(r.permissions),
      related_actors: asArray<string>(r.related_actors ?? r.relatedActors),
    };
  });
  return { roles };
}

function parseUseCases(raw: Record<string, unknown>): Pick<AnalysisResult, "use_cases"> {
  const arr = asArray(raw.use_cases ?? raw.useCases);
  if (arr.length === 0) return {};
  const useCases: UseCase[] = arr.map((uc) => {
    const r = asRecord(uc);
    const prio = asString(r.priority, "should");
    return {
      id: asString(r.id, `uc-${Math.random().toString(36).slice(2, 6)}`),
      title: asString(r.title, ""),
      actor: asString(r.actor, ""),
      category: asString(r.category, "未分類"),
      sub_category: asString(r.sub_category ?? r.subCategory, "その他"),
      preconditions: asArray<string>(r.preconditions),
      main_flow: asArray<string>(r.main_flow ?? r.mainFlow),
      alternative_flows: asArray(r.alternative_flows ?? r.alternativeFlows).length > 0
        ? asArray(r.alternative_flows ?? r.alternativeFlows).map((af) => {
            const a = asRecord(af);
            return { condition: asString(a.condition, ""), steps: asArray<string>(a.steps) };
          })
        : undefined,
      postconditions: asArray<string>(r.postconditions),
      priority: (["must", "should", "could"].includes(prio) ? prio : "should") as UseCase["priority"],
      related_stories: asArray<string>(r.related_stories ?? r.relatedStories).length > 0
        ? asArray<string>(r.related_stories ?? r.relatedStories)
        : undefined,
    };
  });
  return { use_cases: useCases };
}

function parseRecommendedMilestones(raw: Record<string, unknown>): Pick<AnalysisResult, "recommended_milestones"> {
  const arr = asArray(raw.recommended_milestones ?? raw.recommendedMilestones);
  if (arr.length === 0) return {};
  const milestones: RecommendedMilestone[] = arr.map((m) => {
    const r = asRecord(m);
    const phase = asString(r.phase, "beta");
    return {
      id: asString(r.id, `rm-${Math.random().toString(36).slice(2, 6)}`),
      name: asString(r.name, ""),
      criteria: asString(r.criteria, ""),
      rationale: asString(r.rationale, ""),
      phase: (["alpha", "beta", "release"].includes(phase) ? phase : "beta") as RecommendedMilestone["phase"],
      depends_on_use_cases: asArray<string>(r.depends_on_use_cases ?? r.dependsOnUseCases).length > 0
        ? asArray<string>(r.depends_on_use_cases ?? r.dependsOnUseCases)
        : undefined,
    };
  });
  return { recommended_milestones: milestones };
}

function parseDesignTokens(raw: Record<string, unknown>): Pick<AnalysisResult, "design_tokens"> {
  const dt = asRecord(raw.design_tokens ?? raw.designTokens);
  if (!dt.style && !dt.colors) return {};
  const style = asRecord(dt.style);
  const colors = asRecord(dt.colors);
  const typo = asRecord(dt.typography);
  return {
    design_tokens: {
      style: {
        name: asString(style.name, "Default"),
        keywords: asArray<string>(style.keywords),
        best_for: asString(style.best_for ?? style.bestFor, ""),
        performance: asString(style.performance, ""),
        accessibility: asString(style.accessibility, ""),
      },
      colors: {
        primary: asString(colors.primary, "#0F172A"),
        secondary: asString(colors.secondary, "#1E293B"),
        cta: asString(colors.cta, "#22C55E"),
        background: asString(colors.background, "#020617"),
        text: asString(colors.text, "#F8FAFC"),
        notes: asString(colors.notes, ""),
      },
      typography: {
        heading: asString(typo.heading, "Inter"),
        body: asString(typo.body, "Inter"),
        mood: asArray<string>(typo.mood),
        google_fonts_url: asString(typo.google_fonts_url ?? typo.googleFontsUrl, "") || undefined,
      },
      effects: asArray<string>(dt.effects),
      anti_patterns: asArray<string>(dt.anti_patterns ?? dt.antiPatterns),
      rationale: asString(dt.rationale, ""),
    },
  };
}

function parseFeatureDecisions(raw: Record<string, unknown>): Pick<AnalysisResult, "feature_decisions"> {
  const arr = asArray(raw.feature_decisions ?? raw.featureDecisions);
  if (arr.length === 0) return {};
  return {
    feature_decisions: arr.map((item) => {
      const r = asRecord(item);
      return {
        feature: asString(r.feature, ""),
        selected: r.selected === true,
        supporting_claim_ids: asArray<string>(r.supporting_claim_ids ?? r.supportingClaimIds),
        counterarguments: asArray<string>(r.counterarguments),
        rejection_reason: asString(r.rejection_reason ?? r.rejectionReason, ""),
        uncertainty: asNumber(r.uncertainty, 0),
      };
    }),
  };
}

function parseRejectedFeatures(raw: Record<string, unknown>): Pick<AnalysisResult, "rejected_features"> {
  const arr = asArray(raw.rejected_features ?? raw.rejectedFeatures);
  if (arr.length === 0) return {};
  return {
    rejected_features: arr.map((item) => {
      const r = asRecord(item);
      return {
        feature: asString(r.feature, ""),
        reason: asString(r.reason, ""),
        counterarguments: asArray<string>(r.counterarguments),
      };
    }),
  };
}

function parsePlanningAssumptions(raw: Record<string, unknown>): Pick<AnalysisResult, "assumptions"> {
  const arr = asArray(raw.assumptions);
  if (arr.length === 0) return {};
  return {
    assumptions: arr.map((item, index) => {
      const r = asRecord(item);
      return {
        id: asString(r.id, `assumption-${index + 1}`),
        statement: asString(r.statement, ""),
        severity: asString(r.severity, "medium"),
      };
    }),
  };
}

function parseRedTeamFindings(raw: Record<string, unknown>): Pick<AnalysisResult, "red_team_findings"> {
  const arr = asArray(raw.red_team_findings ?? raw.redTeamFindings);
  if (arr.length === 0) return {};
  return {
    red_team_findings: arr.map((item, index) => {
      const r = asRecord(item);
      return {
        id: asString(r.id, `finding-${index + 1}`),
        title: asString(r.title, ""),
        challenger: asString(r.challenger, ""),
        severity: asString(r.severity, "medium"),
        impact: asString(r.impact, ""),
        recommendation: asString(r.recommendation, ""),
        related_feature: asString(r.related_feature ?? r.relatedFeature, "") || undefined,
      };
    }),
  };
}

function parseNegativePersonas(raw: Record<string, unknown>): Pick<AnalysisResult, "negative_personas"> {
  const arr = asArray(raw.negative_personas ?? raw.negativePersonas);
  if (arr.length === 0) return {};
  return {
    negative_personas: arr.map((item, index) => {
      const r = asRecord(item);
      return {
        id: asString(r.id, `negative-persona-${index + 1}`),
        name: asString(r.name, ""),
        scenario: asString(r.scenario, ""),
        risk: asString(r.risk, ""),
        mitigation: asString(r.mitigation, ""),
      };
    }),
  };
}

function parseTraceability(raw: Record<string, unknown>): Pick<AnalysisResult, "traceability"> {
  const arr = asArray(raw.traceability);
  if (arr.length === 0) return {};
  return {
    traceability: arr.map((item) => {
      const r = asRecord(item);
      return {
        claim_id: asString(r.claim_id ?? r.claimId, ""),
        claim: asString(r.claim, ""),
        use_case_id: asString(r.use_case_id ?? r.useCaseId, ""),
        use_case: asString(r.use_case ?? r.useCase, ""),
        feature: asString(r.feature, ""),
        milestone_id: asString(r.milestone_id ?? r.milestoneId, ""),
        milestone: asString(r.milestone, ""),
        confidence: asNumber(r.confidence, 0),
      };
    }),
  };
}

function parseKillCriteria(raw: Record<string, unknown>): Pick<AnalysisResult, "kill_criteria"> {
  const arr = asArray(raw.kill_criteria ?? raw.killCriteria);
  if (arr.length === 0) return {};
  return {
    kill_criteria: arr.map((item, index) => {
      const r = asRecord(item);
      return {
        id: asString(r.id, `kill-${index + 1}`),
        milestone_id: asString(r.milestone_id ?? r.milestoneId, ""),
        condition: asString(r.condition, ""),
        rationale: asString(r.rationale, ""),
      };
    }),
  };
}

function parseConfidenceSummary(raw: Record<string, unknown>): Pick<AnalysisResult, "confidence_summary"> {
  const summary = asRecord(raw.confidence_summary ?? raw.confidenceSummary);
  if (Object.keys(summary).length === 0) return {};
  return {
    confidence_summary: {
      average: asNumber(summary.average, 0),
      floor: asNumber(summary.floor, 0),
      accepted: asNumber(summary.accepted, 0) || undefined,
      critical_findings: asNumber(summary.critical_findings ?? summary.criticalFindings, 0) || undefined,
    },
  };
}

export function parsePlanningOutput(
  state: Record<string, unknown>,
): { analysis: AnalysisResult; features: FeatureSelection[]; planEstimates: PlanEstimate[] } {
  const raw = asRecord(state.planning ?? state.output ?? state);

  const parsePersona = (p: unknown): Persona => {
    const r = asRecord(p);
    return {
      name: asString(r.name, "Unknown"),
      role: asString(r.role, ""),
      age_range: asString(r.age_range, "N/A"),
      goals: asArray<string>(r.goals),
      frustrations: asArray<string>(r.frustrations),
      tech_proficiency: asString(r.tech_proficiency, "N/A"),
      context: asString(r.context, ""),
    };
  };

  const parseUserStory = (s: unknown): UserStory => {
    const r = asRecord(s);
    const priority = asString(r.priority, "could");
    return {
      role: asString(r.role, "User"),
      action: asString(r.action, ""),
      benefit: asString(r.benefit, ""),
      acceptance_criteria: asArray<string>(r.acceptance_criteria),
      priority: (["must", "should", "could", "wont"].includes(priority)
        ? priority
        : "could") as UserStory["priority"],
    };
  };

  const parseKanoFeature = (f: unknown): KanoFeature => {
    const r = asRecord(f);
    const category = asString(r.category, "indifferent");
    const cost = asString(r.implementation_cost, "medium");
    return {
      feature: asString(r.feature, ""),
      category: (
        [
          "must-be",
          "one-dimensional",
          "attractive",
          "indifferent",
          "reverse",
        ].includes(category)
          ? category
          : "indifferent"
      ) as KanoFeature["category"],
      user_delight: asNumber(r.user_delight, 0),
      implementation_cost: (["low", "medium", "high"].includes(cost)
        ? cost
        : "medium") as KanoFeature["implementation_cost"],
      rationale: asString(r.rationale, ""),
    };
  };

  const personas = asArray(raw.personas).map(parsePersona);
  const userStories = asArray(
    raw.user_stories ?? raw.userStories,
  ).map(parseUserStory);
  const kanoFeatures = asArray(
    raw.kano_features ?? raw.kanoFeatures,
  ).map(parseKanoFeature);

  const bm = asRecord(raw.business_model ?? raw.businessModel);
  const hasBm = Object.keys(bm).length > 0;

  const analysis: AnalysisResult = {
    personas,
    user_stories: userStories,
    kano_features: kanoFeatures,
    recommendations: asArray<string>(raw.recommendations),
    ...(hasBm
      ? {
          business_model: {
            value_propositions: asArray<string>(bm.value_propositions),
            customer_segments: asArray<string>(bm.customer_segments),
            channels: asArray<string>(bm.channels),
            revenue_streams: asArray<string>(bm.revenue_streams),
          },
        }
      : {}),
    ...parseUserJourneys(raw),
    ...parseJobStories(raw),
    ...parseIAAnalysis(raw),
    ...parseActors(raw),
    ...parseRoles(raw),
    ...parseUseCases(raw),
    ...parseRecommendedMilestones(raw),
    ...parseDesignTokens(raw),
    ...parseFeatureDecisions(raw),
    ...parseRejectedFeatures(raw),
    ...parsePlanningAssumptions(raw),
    ...parseRedTeamFindings(raw),
    ...parseNegativePersonas(raw),
    ...parseTraceability(raw),
    ...parseKillCriteria(raw),
    ...parseConfidenceSummary(raw),
    ...(asString(raw.judge_summary ?? raw.judgeSummary, "") ? { judge_summary: asString(raw.judge_summary ?? raw.judgeSummary, "") } : {}),
    ...(Object.keys(asRecord(raw.model_assignments ?? raw.modelAssignments)).length > 0 ? {
      model_assignments: Object.fromEntries(Object.entries(asRecord(raw.model_assignments ?? raw.modelAssignments)).map(([key, value]) => [key, asString(value, "")])),
    } : {}),
    ...(raw.low_diversity_mode === true || raw.lowDiversityMode === true ? { low_diversity_mode: true } : {}),
  };

  const features: FeatureSelection[] = asArray(
    raw.features ?? raw.feature_selections,
  ).map((f) => {
    const r = asRecord(f);
    const priority = asString(r.priority, "could");
    const cost = asString(r.implementation_cost, "medium");
    return {
      feature: asString(r.feature, ""),
      category: asString(r.category, ""),
      selected: r.selected === true,
      priority: (["must", "should", "could", "wont"].includes(priority)
        ? priority
        : "could") as FeatureSelection["priority"],
      user_delight: asNumber(r.user_delight, 0),
      implementation_cost: cost,
      rationale: asString(r.rationale, ""),
    };
  });

  // Parse plan estimates (3 presets: minimal, standard, full)
  const parseEpic = (e: unknown): Epic => {
    const r = asRecord(e);
    const prio = asString(r.priority, "should");
    return {
      id: asString(r.id, `epic-${Math.random().toString(36).slice(2, 6)}`),
      name: asString(r.name, ""),
      description: asString(r.description, ""),
      use_cases: asArray<string>(r.use_cases),
      priority: (["must", "should", "could"].includes(prio) ? prio : "should") as Epic["priority"],
      stories: asArray<string>(r.stories),
    };
  };

  const parseWbsItem = (w: unknown): WbsItem => {
    const r = asRecord(w);
    return {
      id: asString(r.id, `wbs-${Math.random().toString(36).slice(2, 6)}`),
      epic_id: asString(r.epic_id, ""),
      title: asString(r.title, ""),
      description: asString(r.description, ""),
      assignee_type: asString(r.assignee_type, "agent") as WbsItem["assignee_type"],
      assignee: asString(r.assignee, ""),
      skills: asArray<string>(r.skills),
      depends_on: asArray<string>(r.depends_on),
      effort_hours: asNumber(r.effort_hours, 1),
      start_day: asNumber(r.start_day, 0),
      duration_days: asNumber(r.duration_days, 1),
      status: "pending",
    };
  };

  const parsePlanEstimate = (pe: unknown): PlanEstimate => {
    const r = asRecord(pe);
    const preset = asString(r.preset, "standard");
    return {
      preset: (["minimal", "standard", "full"].includes(preset) ? preset : "standard") as PlanPreset,
      label: asString(r.label, preset),
      description: asString(r.description, ""),
      total_effort_hours: asNumber(r.total_effort_hours, 0),
      total_cost_usd: asNumber(r.total_cost_usd, 0),
      duration_weeks: asNumber(r.duration_weeks, 1),
      epics: asArray(r.epics).map(parseEpic),
      wbs: asArray(r.wbs).map(parseWbsItem),
      agents_used: asArray<string>(r.agents_used),
      skills_used: asArray<string>(r.skills_used),
    };
  };

  const planEstimates: PlanEstimate[] = asArray(
    raw.plan_estimates ?? raw.planEstimates,
  ).map(parsePlanEstimate);

  return { analysis, features, planEstimates };
}

export function parseDesignOutput(
  state: Record<string, unknown>,
): DesignVariant[] {
  const raw = asRecord(state.design ?? state.output ?? state);
  const variants = asArray(raw.variants ?? raw.designs ?? state.variants);

  return variants.map((v, idx) => {
    const r = asRecord(v);
    const scores = asRecord(r.scores);
    const tokens = asRecord(r.tokens);
    const prototype = asRecord(r.prototype);
    const appShell = asRecord(prototype.app_shell);

    return {
      id: asString(r.id, `variant-${idx}`),
      model: asString(r.model, "unknown"),
      pattern_name: asString(
        r.pattern_name ?? r.patternName,
        "Untitled",
      ),
      description: asString(r.description, ""),
      preview_html: asString(
        r.preview_html ?? r.previewHtml ?? r.html,
        "",
      ),
      primary_color: asString(r.primary_color ?? r.primaryColor, undefined),
      accent_color: asString(r.accent_color ?? r.accentColor, undefined),
      quality_focus: asArray<string>(r.quality_focus ?? r.qualityFocus),
      prototype: prototype && Object.keys(prototype).length > 0 ? {
        kind: asString(prototype.kind, "product-workspace"),
        app_shell: {
          layout: asString(appShell.layout, "sidebar"),
          density: asString(appShell.density, "medium"),
          primary_navigation: asArray(appShell.primary_navigation ?? appShell.primaryNavigation).map((item, navIdx) => {
            const nav = asRecord(item);
            return {
              id: asString(nav.id, `nav-${navIdx}`),
              label: asString(nav.label, "Section"),
              priority: asString(nav.priority, "primary"),
            };
          }),
          status_badges: asArray<string>(appShell.status_badges ?? appShell.statusBadges),
        },
        screens: asArray(prototype.screens).map((item, screenIdx) => {
          const screen = asRecord(item);
          return {
            id: asString(screen.id, `screen-${screenIdx}`),
            title: asString(screen.title, "Screen"),
            purpose: asString(screen.purpose, ""),
            layout: asString(screen.layout, "workspace"),
            headline: asString(screen.headline, ""),
            supporting_text: asString(screen.supporting_text ?? screen.supportingText, ""),
            primary_actions: asArray<string>(screen.primary_actions ?? screen.primaryActions),
            modules: asArray(screen.modules).map((module, moduleIdx) => {
              const mod = asRecord(module);
              return {
                name: asString(mod.name, `Module ${moduleIdx + 1}`),
                type: asString(mod.type, "panel"),
                items: asArray<string>(mod.items),
              };
            }),
            success_state: asString(screen.success_state ?? screen.successState, ""),
          };
        }),
        flows: asArray(prototype.flows).map((item, flowIdx) => {
          const flow = asRecord(item);
          return {
            id: asString(flow.id, `flow-${flowIdx}`),
            name: asString(flow.name, "Flow"),
            steps: asArray<string>(flow.steps),
            goal: asString(flow.goal, ""),
          };
        }),
        interaction_principles: asArray<string>(prototype.interaction_principles ?? prototype.interactionPrinciples),
        design_anchor: (() => {
          const anchor = asRecord(prototype.design_anchor ?? prototype.designAnchor);
          return Object.keys(anchor).length > 0 ? {
            pattern_name: asString(anchor.pattern_name ?? anchor.patternName, undefined),
            description: asString(anchor.description, undefined),
            style_name: asString(anchor.style_name ?? anchor.styleName, undefined),
          } : undefined;
        })(),
      } : undefined,
      tokens: {
        in: asNumber(tokens.in ?? tokens.input, 0),
        out: asNumber(tokens.out ?? tokens.output, 0),
      },
      cost_usd: asNumber(r.cost_usd ?? r.costUsd, 0),
      scores: {
        ux_quality: asNumber(scores.ux_quality ?? scores.uxQuality, 0),
        code_quality: asNumber(
          scores.code_quality ?? scores.codeQuality,
          0,
        ),
        performance: asNumber(scores.performance, 0),
        accessibility: asNumber(scores.accessibility, 0),
      },
    };
  });
}

export function parseDevelopmentOutput(
  state: Record<string, unknown>,
): { code: string; milestoneResults: MilestoneResult[] } {
  const raw = asRecord(state.development ?? state.output ?? state);

  const code = asString(raw.code ?? state.code, "");

  const milestoneResults: MilestoneResult[] = asArray(
    raw.milestone_results ??
      raw.milestoneResults ??
      raw.milestones,
  ).map((m) => {
    const r = asRecord(m);
    const status = asString(r.status, "not_satisfied");
    return {
      id: asString(r.id, ""),
      name: asString(r.name, ""),
      status: (
        status === "satisfied" ? "satisfied" : "not_satisfied"
      ) as MilestoneResult["status"],
      reason:
        typeof r.reason === "string" ? r.reason : undefined,
    };
  });

  return { code, milestoneResults };
}
