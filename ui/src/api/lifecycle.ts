import { apiFetch, apiStream, ApiError } from "./client";
import type { WorkflowRun } from "./workflows";
import type {
  LifecyclePhase,
  LifecycleNextAction,
  LifecycleAutonomyState,
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
  LifecycleDeliveryPlan,
  LifecycleProject,
  LifecycleOrchestrationMode,
  ApprovalComment,
  DeployCheck,
  ReleaseRecord,
  FeedbackItem,
  LifecycleRecommendation,
  LifecyclePhaseRuntimeSummary,
  PhaseStatus,
  LifecycleGovernanceMode,
  LifecycleValueContract,
  LifecycleOutcomeTelemetryContract,
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

export interface LifecycleRuntimeStreamPayload {
  updatedAt: string;
  savedAt: string;
  phaseStatuses: PhaseStatus[];
  nextAction: LifecycleNextAction | null;
  autonomyState: LifecycleAutonomyState | null;
  observedPhase?: LifecyclePhase | null;
  activePhase?: LifecyclePhase | null;
  phaseSummary?: LifecyclePhaseRuntimeSummary | null;
  activePhaseSummary?: LifecyclePhaseRuntimeSummary | null;
}

export interface LifecyclePhaseTerminalEvent {
  projectId: string;
  phase: LifecyclePhase;
  runId: string;
  status: string;
}

export function lifecycleWorkflowId(
  phase: LifecyclePhase,
  projectSlug: string,
): string {
  return `lifecycle-${phase}-${projectSlug}`;
}

export const lifecycleApi = {
  async listProjects(): Promise<LifecycleProjectListResponse> {
    const response = await apiFetch<LifecycleProjectListResponse>("/v1/lifecycle/projects");
    return {
      ...response,
      projects: asArray<LifecycleProject>(response.projects).map((project) => normalizeLifecycleProject(project)),
    };
  },

  async getProject(projectSlug: string): Promise<LifecycleProject> {
    return normalizeLifecycleProject(
      await apiFetch<LifecycleProject>(`/v1/lifecycle/projects/${projectSlug}`),
    );
  },

  deleteProject(projectSlug: string): Promise<void> {
    return apiFetch<void>(`/v1/lifecycle/projects/${projectSlug}`, {
      method: "DELETE",
    });
  },

  async saveProject(
    projectSlug: string,
    payload: Partial<LifecycleProject>,
    options: { autoRun?: boolean; maxSteps?: number } = {},
  ): Promise<LifecycleMutationResponse> {
    const body: Record<string, unknown> = { ...payload };
    if (options.autoRun !== undefined) body.auto_run = options.autoRun;
    if (options.maxSteps !== undefined) body.max_steps = options.maxSteps;
    return normalizeLifecycleMutationResponse(await apiFetch<LifecycleMutationResponse>(`/v1/lifecycle/projects/${projectSlug}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }));
  },

  async advanceProject(
    projectSlug: string,
    options: {
      orchestrationMode?: LifecycleOrchestrationMode;
      maxSteps?: number;
    } = {},
  ): Promise<LifecycleMutationResponse> {
    const body: Record<string, unknown> = {};
    if (options.orchestrationMode) body.orchestration_mode = options.orchestrationMode;
    if (options.maxSteps !== undefined) body.max_steps = options.maxSteps;
    return normalizeLifecycleMutationResponse(await apiFetch<LifecycleMutationResponse>(`/v1/lifecycle/projects/${projectSlug}/advance`, {
      method: "POST",
      body: JSON.stringify(body),
    }));
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

  async syncPhaseRun(
    projectSlug: string,
    phase: LifecyclePhase,
    runId: string,
  ): Promise<LifecyclePhaseSyncResponse> {
    const response = await apiFetch<LifecyclePhaseSyncResponse>(`/v1/lifecycle/projects/${projectSlug}/phases/${phase}/sync`, {
      method: "POST",
      body: JSON.stringify({ run_id: runId }),
    });
    return {
      ...response,
      project: normalizeLifecycleProject(response.project),
    };
  },

  async getRun(runId: string): Promise<WorkflowRun> {
    return apiFetch<WorkflowRun>(`/v1/runs/${runId}`);
  },

  streamRun(
    runId: string,
    options: {
      signal?: AbortSignal;
      onEvent: (event: { event: string; data: string; id?: string }) => void;
    },
  ): Promise<void> {
    return apiStream(`/v1/runs/${runId}/events`, options);
  },

  streamProjectEvents(
    projectSlug: string,
    phase: LifecyclePhase,
    options: {
      signal?: AbortSignal;
      onEvent: (event: { event: string; data: string; id?: string }) => void;
    },
  ): Promise<void> {
    return apiStream(
      `/v1/lifecycle/projects/${projectSlug}/events?phase=${encodeURIComponent(phase)}`,
      options,
    );
  },

  async getLatestRun(
    workflowId: string,
  ): Promise<WorkflowRun | null> {
    try {
      const res = await apiFetch<{ runs: WorkflowRun[] }>(`/v1/workflows/${workflowId}/runs`);
      if (!res.runs || res.runs.length === 0) return null;
      // Return the most recent run (first in list)
      return res.runs[0];
    } catch (err) {
      // 404 is expected when no workflow has been created yet
      if (err instanceof ApiError && err.status === 404) return null;
      // Suppress other transient errors during restore
      return null;
    }
  },

  async addApprovalComment(
    projectSlug: string,
    payload: Pick<ApprovalComment, "text" | "type">,
  ): Promise<LifecycleMutationResponse> {
    return normalizeLifecycleMutationResponse(await apiFetch<LifecycleMutationResponse>(`/v1/lifecycle/projects/${projectSlug}/approval/comments`, {
      method: "POST",
      body: JSON.stringify(payload),
    }));
  },

  async decideApproval(
    projectSlug: string,
    decision: LifecycleProject["approvalStatus"],
    comment = "",
  ): Promise<LifecycleMutationResponse> {
    return normalizeLifecycleMutationResponse(await apiFetch<LifecycleMutationResponse>(`/v1/lifecycle/projects/${projectSlug}/approval/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, comment }),
    }));
  },

  async runDeployChecks(projectSlug: string, buildCode?: string): Promise<LifecycleDeployChecksResponse> {
    const response = await apiFetch<LifecycleDeployChecksResponse>(`/v1/lifecycle/projects/${projectSlug}/deploy/checks`, {
      method: "POST",
      body: JSON.stringify(buildCode ? { buildCode } : {}),
    });
    return {
      ...response,
      project: normalizeLifecycleProject(response.project),
    };
  },

  async createRelease(projectSlug: string, note = ""): Promise<{ project: LifecycleProject; release: ReleaseRecord }> {
    const response = await apiFetch<{ project: LifecycleProject; release: ReleaseRecord }>(`/v1/lifecycle/projects/${projectSlug}/releases`, {
      method: "POST",
      body: JSON.stringify({ note }),
    });
    return { ...response, project: normalizeLifecycleProject(response.project) };
  },

  listFeedback(projectSlug: string): Promise<{ feedbackItems: FeedbackItem[]; recommendations: LifecycleRecommendation[] }> {
    return apiFetch<{ feedbackItems: FeedbackItem[]; recommendations: LifecycleRecommendation[] }>(`/v1/lifecycle/projects/${projectSlug}/feedback`);
  },

  async addFeedback(
    projectSlug: string,
    payload: Pick<FeedbackItem, "text" | "type" | "impact">,
  ): Promise<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }> {
    const response = await apiFetch<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }>(`/v1/lifecycle/projects/${projectSlug}/feedback`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    return { ...response, project: normalizeLifecycleProject(response.project) };
  },

  async voteFeedback(
    projectSlug: string,
    feedbackId: string,
    delta: number,
  ): Promise<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }> {
    const response = await apiFetch<{ project: LifecycleProject; feedbackItems: FeedbackItem[] }>(`/v1/lifecycle/projects/${projectSlug}/feedback/${feedbackId}/vote`, {
      method: "POST",
      body: JSON.stringify({ delta }),
    });
    return { ...response, project: normalizeLifecycleProject(response.project) };
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

function asBoolean(val: unknown, fallback = false): boolean {
  return typeof val === "boolean" ? val : fallback;
}

function asRecord(val: unknown): Record<string, unknown> {
  return val != null && typeof val === "object" && !Array.isArray(val)
    ? (val as Record<string, unknown>)
    : {};
}

function parseRequirementsBundle(raw: unknown): LifecycleProject["requirements"] {
  const source = asRecord(raw);
  if (Object.keys(source).length === 0) return null;
  const acceptanceCriteria = asArray(source.acceptanceCriteria ?? source.acceptance_criteria).map((item) => {
    const record = asRecord(item);
    return {
      id: asString(record.id, ""),
      requirementId: asString(record.requirementId ?? record.requirement_id, ""),
      criterion: asString(record.criterion ?? record.text, ""),
    };
  }).filter((item) => item.id || item.requirementId || item.criterion);
  const acceptanceByRequirement = new Map<string, string[]>();
  for (const criterion of acceptanceCriteria) {
    if (!criterion.requirementId || !criterion.criterion) continue;
    const bucket = acceptanceByRequirement.get(criterion.requirementId) ?? [];
    bucket.push(criterion.criterion);
    acceptanceByRequirement.set(criterion.requirementId, bucket);
  }
  const requirements = asArray(source.requirements).map((item) => {
    const record = asRecord(item);
    const requirementId = asString(record.id, "");
    const criteria = acceptanceByRequirement.get(requirementId)
      ?? asArray<string>(record.acceptanceCriteria ?? record.acceptance_criteria);
    return {
      id: requirementId,
      pattern: asString(record.pattern, "ubiquitous") as "ubiquitous" | "event-driven" | "unwanted" | "state-driven" | "optional" | "complex",
      statement: asString(record.statement, ""),
      confidence: asNumber(record.confidence, 0),
      sourceClaimIds: asArray<string>(record.sourceClaimIds ?? record.source_claim_ids),
      userStoryIds: asArray<string>(record.userStoryIds ?? record.user_story_ids),
      acceptanceCriteria: criteria,
    };
  });
  const userStories = asArray(source.userStories ?? source.user_stories).map((item) => {
    const record = asRecord(item);
    const description = asString(record.description ?? record.text, "");
    const title = asString(
      record.title,
      `${asString(record.persona, "ユーザー")}: ${asString(record.action, asString(record.requirement_id ?? record.requirementId, ""))}`,
    );
    return {
      id: asString(record.id, ""),
      title,
      description: description || title,
    };
  });
  const distribution = asRecord(source.confidenceDistribution ?? source.confidence_distribution);
  const traceabilityIndex = asRecord(source.traceabilityIndex ?? source.traceability_index);
  return {
    requirements,
    userStories,
    acceptanceCriteria,
    confidenceDistribution: {
      high: asNumber(distribution.high, 0),
      medium: asNumber(distribution.medium, 0),
      low: asNumber(distribution.low, 0),
    },
    completenessScore: asNumber(source.completenessScore ?? source.completeness_score, 0),
    traceabilityIndex: Object.fromEntries(
      Object.entries(traceabilityIndex).map(([key, value]) => [key, asArray<string>(value)]),
    ),
  };
}

function parseTaskDecomposition(raw: unknown): LifecycleProject["taskDecomposition"] {
  const source = asRecord(raw);
  if (Object.keys(source).length === 0) return null;
  return {
    tasks: asArray(source.tasks).map((item) => {
      const record = asRecord(item);
      return {
        id: asString(record.id, ""),
        title: asString(record.title, ""),
        description: asString(record.description, ""),
        phase: asString(record.phase, ""),
        milestoneId: asString(record.milestoneId ?? record.milestone_id, "") || null,
        dependsOn: asArray<string>(record.dependsOn ?? record.depends_on),
        effortHours: asNumber(record.effortHours ?? record.effort_hours, 0),
        priority: asString(record.priority, "should") as "must" | "should" | "could",
        featureId: asString(record.featureId ?? record.feature_id, "") || null,
        requirementId: asString(record.requirementId ?? record.requirement_id, "") || null,
      };
    }),
    dagEdges: asArray(source.dagEdges ?? source.dag_edges)
      .filter((entry): entry is [string, string] => Array.isArray(entry) && entry.length >= 2)
      .map((entry) => [asString(entry[0], ""), asString(entry[1], "")]),
    phaseMilestones: asArray(source.phaseMilestones ?? source.phase_milestones).map((item) => {
      const record = asRecord(item);
      return {
        phase: asString(record.phase, ""),
        milestoneIds: asArray<string>(record.milestoneIds ?? record.milestone_ids),
        taskCount: asNumber(record.taskCount ?? record.task_count, 0),
        totalHours: asNumber(record.totalHours ?? record.total_hours, 0),
        durationDays: asNumber(record.durationDays ?? record.duration_days, 0),
      };
    }),
    totalEffortHours: asNumber(source.totalEffortHours ?? source.total_effort_hours, 0),
    criticalPath: asArray<string>(source.criticalPath ?? source.critical_path),
    effortByPhase: Object.fromEntries(
      Object.entries(asRecord(source.effortByPhase ?? source.effort_by_phase)).map(([key, value]) => [key, asNumber(value, 0)]),
    ),
    hasCycles: asBoolean(source.hasCycles ?? source.has_cycles, false),
  };
}

function parseDCSAnalysis(raw: unknown): LifecycleProject["dcsAnalysis"] {
  const source = asRecord(raw);
  if (Object.keys(source).length === 0) return null;
  const rubberDuck = asRecord(source.rubberDuckPrd ?? source.rubber_duck_prd);
  const edgeCases = asRecord(source.edgeCases ?? source.edge_case_analysis);
  const impactAnalysis = asRecord(source.impactAnalysis ?? source.impact_analysis);
  const sequenceDiagrams = asRecord(source.sequenceDiagrams ?? source.sequence_diagrams);
  const stateTransitions = asRecord(source.stateTransitions ?? source.state_transitions);
  return {
    rubberDuckPrd: Object.keys(rubberDuck).length > 0 ? {
      problemStatement: asString(rubberDuck.problemStatement ?? rubberDuck.problem_statement, ""),
      targetUsers: asArray<string>(rubberDuck.targetUsers ?? rubberDuck.target_users),
      successMetrics: asArray(rubberDuck.successMetrics ?? rubberDuck.success_metrics).map((item) => asRecord(item)),
      scopeBoundaries: (() => {
        const scope = asRecord(rubberDuck.scopeBoundaries ?? rubberDuck.scope_boundaries);
        return {
          inScope: asArray<string>(scope.inScope ?? scope.in_scope),
          outOfScope: asArray<string>(scope.outOfScope ?? scope.out_of_scope),
        };
      })(),
      keyDecisions: asArray(rubberDuck.keyDecisions ?? rubberDuck.key_decisions).map((item) => asRecord(item)),
    } : null,
    edgeCases: Object.keys(edgeCases).length > 0 ? {
      edgeCases: asArray(edgeCases.edgeCases ?? edgeCases.edge_cases).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          scenario: asString(record.scenario, ""),
          severity: asString(record.severity, "low") as "critical" | "high" | "medium" | "low",
          mitigation: asString(record.mitigation, ""),
          featureId: asString(record.featureId ?? record.feature_id, ""),
        };
      }),
      riskMatrix: Object.fromEntries(
        Object.entries(asRecord(edgeCases.riskMatrix ?? edgeCases.risk_matrix)).map(([key, value]) => [key, asNumber(value, 0)]),
      ),
      coverageScore: asNumber(edgeCases.coverageScore ?? edgeCases.coverage_score, 0),
    } : null,
    impactAnalysis: Object.keys(impactAnalysis).length > 0 ? {
      layers: asArray(impactAnalysis.layers).map((item) => {
        const record = asRecord(item);
        return {
          layer: asString(record.layer, ""),
          impacts: asArray(record.impacts).map((entry) => asRecord(entry)),
        };
      }),
      blastRadius: asNumber(impactAnalysis.blastRadius ?? impactAnalysis.blast_radius, 0),
      criticalPathsAffected: asArray<string>(impactAnalysis.criticalPathsAffected ?? impactAnalysis.critical_paths_affected),
    } : null,
    sequenceDiagrams: Object.keys(sequenceDiagrams).length > 0 ? {
      diagrams: asArray(sequenceDiagrams.diagrams).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          title: asString(record.title, ""),
          mermaidCode: asString(record.mermaidCode ?? record.mermaid_code, ""),
          flowType: asString(record.flowType ?? record.flow_type, "success"),
        };
      }),
    } : null,
    stateTransitions: Object.keys(stateTransitions).length > 0 ? {
      states: asArray(stateTransitions.states).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          name: asString(record.name, ""),
          description: asString(record.description, ""),
        };
      }),
      transitions: asArray(stateTransitions.transitions).map((item) => {
        const record = asRecord(item);
        return {
          fromState: asString(record.fromState ?? record.from_state, ""),
          toState: asString(record.toState ?? record.to_state, ""),
          trigger: asString(record.trigger, ""),
          guard: asString(record.guard, ""),
          riskLevel: asString(record.riskLevel ?? record.risk_level, "low"),
        };
      }),
      riskStates: asArray(stateTransitions.riskStates ?? stateTransitions.risk_states).map((item) => asRecord(item)),
      mermaidCode: asString(stateTransitions.mermaidCode ?? stateTransitions.mermaid_code, ""),
    } : null,
  };
}

function parseTechnicalDesign(raw: unknown): LifecycleProject["technicalDesign"] {
  const source = asRecord(raw);
  if (Object.keys(source).length === 0) return null;
  return {
    architecture: asRecord(source.architecture),
    dataflowMermaid: asString(source.dataflowMermaid ?? source.dataflow_mermaid, ""),
    apiSpecification: asArray(source.apiSpecification ?? source.api_specification).map((item) => {
      const record = asRecord(item);
      return {
        method: asString(record.method, "GET"),
        path: asString(record.path, "/"),
        description: asString(record.description, ""),
        authRequired: asBoolean(record.authRequired ?? record.auth_required, true),
      };
    }),
    databaseSchema: asArray(source.databaseSchema ?? source.database_schema).map((item) => {
      const record = asRecord(item);
      return {
        name: asString(record.name, ""),
        columns: asArray(record.columns).map((entry) => {
          const column = asRecord(entry);
          return {
            name: asString(column.name, ""),
            type: asString(column.type, "text"),
            nullable: asBoolean(column.nullable, true),
            primaryKey: asBoolean(column.primaryKey ?? column.primary_key, false),
          };
        }),
        indexes: asArray<string>(record.indexes),
      };
    }),
    interfaceDefinitions: asArray(source.interfaceDefinitions ?? source.interface_definitions).map((item) => {
      const record = asRecord(item);
      return {
        name: asString(record.name, ""),
        properties: asArray(record.properties).map((entry) => {
          const property = asRecord(entry);
          return {
            name: asString(property.name, ""),
            type: asString(property.type, "string"),
            optional: asBoolean(property.optional, false),
          };
        }),
        extends: asArray<string>(record.extends),
      };
    }),
    componentDependencyGraph: Object.fromEntries(
      Object.entries(asRecord(source.componentDependencyGraph ?? source.component_dependency_graph)).map(([key, value]) => [key, asArray<string>(value)]),
    ),
  };
}

function parseReverseEngineering(raw: unknown): LifecycleProject["reverseEngineering"] {
  const source = asRecord(raw);
  if (Object.keys(source).length === 0) return null;
  return {
    extractedRequirements: asArray(source.extractedRequirements ?? source.extracted_requirements).map((item) => asRecord(item)),
    architectureDoc: asRecord(source.architectureDoc ?? source.architecture_doc),
    dataflowMermaid: asString(source.dataflowMermaid ?? source.dataflow_mermaid, ""),
    apiEndpoints: asArray(source.apiEndpoints ?? source.api_endpoints).map((item) => {
      const record = asRecord(item);
      return {
        method: asString(record.method, "GET"),
        path: asString(record.path, "/"),
        handler: asString(record.handler, ""),
        filePath: asString(record.filePath ?? record.file_path, ""),
      };
    }),
    databaseSchema: asArray(source.databaseSchema ?? source.database_schema).map((item) => {
      const record = asRecord(item);
      return {
        name: asString(record.name, ""),
        columns: asArray(record.columns).map((entry) => asRecord(entry)),
        source: asString(record.source, ""),
      };
    }),
    interfaces: asArray(source.interfaces).map((item) => {
      const record = asRecord(item);
      return {
        name: asString(record.name, ""),
        kind: asString(record.kind, "interface"),
        properties: asArray(record.properties).map((entry) => asRecord(entry)),
        filePath: asString(record.filePath ?? record.file_path, ""),
      };
    }),
    taskStructure: asArray(source.taskStructure ?? source.task_structure).map((item) => asRecord(item)),
    testSpecs: asArray(source.testSpecs ?? source.test_specs).map((item) => asRecord(item)),
    coverageScore: asNumber(source.coverageScore ?? source.coverage_score, 0),
    languagesDetected: asArray<string>(source.languagesDetected ?? source.languages_detected),
    sourceType: asString(source.sourceType ?? source.source_type, "") || undefined,
  };
}

export function normalizeLifecycleProject(project: LifecycleProject | Record<string, unknown>): LifecycleProject {
  const raw = asRecord(project);
  const decisionContext = raw.decisionContext ?? raw.decision_context ?? undefined;
  const parseValueContract = (value: unknown): LifecycleValueContract | undefined => {
    const source = asRecord(value);
    if (Object.keys(source).length === 0) return undefined;
    return {
      id: asString(source.id, "value-contract"),
      schema_version: asNumber(source.schema_version ?? source.schemaVersion, 1),
      summary: asString(source.summary, ""),
      primary_personas: asArray(source.primary_personas ?? source.primaryPersonas).map((item) => {
        const record = asRecord(item);
        return {
          name: asString(record.name, ""),
          role: asString(record.role, undefined),
          context: asString(record.context, undefined),
          goals: asArray<string>(record.goals),
          frustrations: asArray<string>(record.frustrations),
        };
      }),
      selected_features: asArray(source.selected_features ?? source.selectedFeatures).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          name: asString(record.name, ""),
          priority: asString(record.priority, undefined),
          category: asString(record.category, undefined),
          rationale: asString(record.rationale, undefined),
        };
      }),
      required_use_cases: asArray(source.required_use_cases ?? source.requiredUseCases).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          title: asString(record.title, ""),
          priority: asString(record.priority, undefined),
          actor: asString(record.actor, undefined),
          summary: asString(record.summary, undefined),
          feature_names: asArray<string>(record.feature_names ?? record.featureNames),
          milestone_names: asArray<string>(record.milestone_names ?? record.milestoneNames),
        };
      }),
      job_stories: asArray(source.job_stories ?? source.jobStories).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          title: asString(record.title, ""),
          situation: asString(record.situation, undefined),
          motivation: asString(record.motivation, undefined),
          outcome: asString(record.outcome, undefined),
          priority: asString(record.priority, undefined),
          related_features: asArray<string>(record.related_features ?? record.relatedFeatures),
        };
      }),
      user_journeys: asArray(source.user_journeys ?? source.userJourneys).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          persona_name: asString(record.persona_name ?? record.personaName, ""),
          critical_touchpoints: asArray(record.critical_touchpoints ?? record.criticalTouchpoints).map((entry) => {
            const point = asRecord(entry);
            return {
              phase: asString(point.phase, undefined),
              action: asString(point.action, undefined),
              touchpoint: asString(point.touchpoint, undefined),
              emotion: asString(point.emotion, undefined),
              pain_point: asString(point.pain_point ?? point.painPoint, undefined),
              opportunity: asString(point.opportunity, undefined),
            };
          }),
          failure_moments: asArray<string>(record.failure_moments ?? record.failureMoments),
        };
      }),
      kano_focus: (() => {
        const focus = asRecord(source.kano_focus ?? source.kanoFocus);
        return Object.keys(focus).length > 0 ? {
          must_be: asArray<string>(focus.must_be ?? focus.mustBe),
          performance: asArray<string>(focus.performance),
          attractive: asArray<string>(focus.attractive),
        } : undefined;
      })(),
      information_architecture: (() => {
        const ia = asRecord(source.information_architecture ?? source.informationArchitecture);
        return Object.keys(ia).length > 0 ? {
          navigation_model: asString(ia.navigation_model ?? ia.navigationModel, undefined),
          top_level_nodes: asArray(ia.top_level_nodes ?? ia.topLevelNodes).map((entry) => {
            const node = asRecord(entry);
            return {
              id: asString(node.id, ""),
              label: asString(node.label, ""),
              priority: asString(node.priority, undefined),
              description: asString(node.description, undefined),
            };
          }),
          key_paths: asArray(ia.key_paths ?? ia.keyPaths).map((entry) => {
            const path = asRecord(entry);
            return {
              name: asString(path.name, ""),
              steps: asArray<string>(path.steps),
            };
          }),
          top_tasks: asArray<string>(ia.top_tasks ?? ia.topTasks),
        } : undefined;
      })(),
      success_metrics: asArray(source.success_metrics ?? source.successMetrics).map((item) => {
        const metric = asRecord(item);
        return {
          id: asString(metric.id, ""),
          name: asString(metric.name, ""),
          signal: asString(metric.signal, ""),
          target: asString(metric.target, ""),
          source: asString(metric.source, ""),
          leading_indicator: asString(metric.leading_indicator ?? metric.leadingIndicator, undefined),
        };
      }),
      kill_criteria: asArray<string>(source.kill_criteria ?? source.killCriteria),
      release_readiness_signals: asArray<string>(source.release_readiness_signals ?? source.releaseReadinessSignals),
      decision_context_fingerprint: asString(
        source.decision_context_fingerprint ?? source.decisionContextFingerprint,
        undefined,
      ),
    };
  };
  const parseOutcomeTelemetryContract = (value: unknown): LifecycleOutcomeTelemetryContract | undefined => {
    const source = asRecord(value);
    if (Object.keys(source).length === 0) return undefined;
    return {
      id: asString(source.id, "outcome-telemetry-contract"),
      schema_version: asNumber(source.schema_version ?? source.schemaVersion, 1),
      summary: asString(source.summary, ""),
      success_metrics: asArray(source.success_metrics ?? source.successMetrics).map((item) => {
        const metric = asRecord(item);
        return {
          id: asString(metric.id, ""),
          name: asString(metric.name, ""),
          signal: asString(metric.signal, ""),
          target: asString(metric.target, ""),
          source: asString(metric.source, ""),
          leading_indicator: asString(metric.leading_indicator ?? metric.leadingIndicator, undefined),
        };
      }),
      kill_criteria: asArray<string>(source.kill_criteria ?? source.killCriteria),
      telemetry_events: asArray(source.telemetry_events ?? source.telemetryEvents).map((item) => {
        const event = asRecord(item);
        return {
          id: asString(event.id, ""),
          name: asString(event.name, ""),
          purpose: asString(event.purpose, undefined),
          properties: asArray<string>(event.properties),
          success_metric_ids: asArray<string>(event.success_metric_ids ?? event.successMetricIds),
        };
      }),
      workspace_artifacts: asArray<string>(source.workspace_artifacts ?? source.workspaceArtifacts),
      release_checks: asArray(source.release_checks ?? source.releaseChecks).map((item) => {
        const record = asRecord(item);
        return {
          id: asString(record.id, ""),
          title: asString(record.title, ""),
          detail: asString(record.detail, undefined),
        };
      }),
      instrumentation_requirements: asArray<string>(
        source.instrumentation_requirements ?? source.instrumentationRequirements,
      ),
      experiment_questions: asArray<string>(source.experiment_questions ?? source.experimentQuestions),
      decision_context_fingerprint: asString(
        source.decision_context_fingerprint ?? source.decisionContextFingerprint,
        undefined,
      ),
    };
  };
  const existingDeliveryPlan = asRecord(raw.deliveryPlan);
  const normalizedValueContract = parseValueContract(
    raw.valueContract ?? existingDeliveryPlan.value_contract ?? existingDeliveryPlan.valueContract,
  );
  const normalizedOutcomeTelemetryContract = parseOutcomeTelemetryContract(
    raw.outcomeTelemetryContract
      ?? existingDeliveryPlan.outcome_telemetry_contract
      ?? existingDeliveryPlan.outcomeTelemetryContract,
  );
  const normalizedDeliveryPlan = Object.keys(existingDeliveryPlan).length > 0
    ? {
        ...(existingDeliveryPlan as unknown as LifecycleDeliveryPlan),
        value_contract: normalizedValueContract ?? null,
        outcome_telemetry_contract: normalizedOutcomeTelemetryContract ?? null,
      }
    : undefined;
  const normalized = {
    ...(project as LifecycleProject),
    governanceMode: asString(raw.governanceMode, "governed") as LifecycleGovernanceMode,
    decisionContext,
    decision_context: decisionContext,
    valueContract: normalizedValueContract,
    outcomeTelemetryContract: normalizedOutcomeTelemetryContract,
    deliveryPlan: normalizedDeliveryPlan,
    requirements: parseRequirementsBundle(raw.requirements),
    requirementsConfig: (() => {
      const config = asRecord(raw.requirementsConfig);
      return Object.keys(config).length > 0
        ? {
            earsEnabled: asBoolean(config.earsEnabled, true),
            interactiveClarification: asBoolean(config.interactiveClarification, true),
            confidenceFloor: asNumber(config.confidenceFloor, 0.6),
          }
        : undefined;
    })(),
    reverseEngineering: parseReverseEngineering(raw.reverseEngineering),
    taskDecomposition: parseTaskDecomposition(raw.taskDecomposition),
    dcsAnalysis: parseDCSAnalysis(raw.dcsAnalysis),
    technicalDesign: parseTechnicalDesign(raw.technicalDesign),
  } satisfies LifecycleProject;
  return normalized;
}

function normalizeLifecycleMutationResponse(
  response: LifecycleMutationResponse,
): LifecycleMutationResponse {
  const normalizedProject = normalizeLifecycleProject(response.project ?? response);
  return {
    ...response,
    ...normalizedProject,
    project: normalizedProject,
  };
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

function parsePlanningCoverageSummary(raw: Record<string, unknown>): Pick<AnalysisResult, "coverage_summary"> {
  const summary = asRecord(raw.coverage_summary ?? raw.coverageSummary);
  if (Object.keys(summary).length === 0) return {};
  const presetBreakdown = asArray(summary.preset_breakdown ?? summary.presetBreakdown).map((entry) => {
    const record = asRecord(entry);
    const preset = asString(record.preset, "standard");
    return {
      preset: (["minimal", "standard", "full"].includes(preset) ? preset : "standard") as "minimal" | "standard" | "full",
      epic_count: asNumber(record.epic_count ?? record.epicCount, 0),
      wbs_count: asNumber(record.wbs_count ?? record.wbsCount, 0),
      total_effort_hours: asNumber(record.total_effort_hours ?? record.totalEffortHours, 0),
    };
  });
  return {
    coverage_summary: {
      selected_feature_count: asNumber(summary.selected_feature_count ?? summary.selectedFeatureCount, 0),
      job_story_count: asNumber(summary.job_story_count ?? summary.jobStoryCount, 0),
      use_case_count: asNumber(summary.use_case_count ?? summary.useCaseCount, 0),
      actor_count: asNumber(summary.actor_count ?? summary.actorCount, 0),
      role_count: asNumber(summary.role_count ?? summary.roleCount, 0),
      traceability_count: asNumber(summary.traceability_count ?? summary.traceabilityCount, 0),
      milestone_count: asNumber(summary.milestone_count ?? summary.milestoneCount, 0),
      uncovered_features: asArray<string>(summary.uncovered_features ?? summary.uncoveredFeatures),
      use_cases_without_milestone: asArray<string>(summary.use_cases_without_milestone ?? summary.useCasesWithoutMilestone),
      use_cases_without_traceability: asArray<string>(summary.use_cases_without_traceability ?? summary.useCasesWithoutTraceability),
      preset_breakdown: presetBreakdown,
    },
  };
}

function parsePlanningOperatorCopy(raw: Record<string, unknown>): Pick<AnalysisResult, "operator_copy"> {
  const operatorCopy = asRecord(raw.operator_copy ?? raw.operatorCopy);
  if (Object.keys(operatorCopy).length === 0) return {};

  const councilCards = asArray(operatorCopy.council_cards ?? operatorCopy.councilCards).map((entry, index) => {
    const card = asRecord(entry);
    return {
      id: asString(card.id, `council-${index + 1}`),
      agent: asString(card.agent, ""),
      lens: asString(card.lens, ""),
      title: asString(card.title, ""),
      summary: asString(card.summary, ""),
      action_label: asString(card.action_label ?? card.actionLabel, ""),
      target_tab: asString(card.target_tab ?? card.targetTab, "") || undefined,
      target_section: ((): "risk" | "recommendation" | undefined => {
        const targetSection = asString(card.target_section ?? card.targetSection, "");
        return targetSection === "risk" || targetSection === "recommendation" ? targetSection : undefined;
      })(),
      tone: asString(card.tone, "") || undefined,
    };
  }).filter((card) => card.agent || card.title || card.summary);

  const handoffRaw = asRecord(operatorCopy.handoff_brief ?? operatorCopy.handoffBrief);
  const handoffBrief = Object.keys(handoffRaw).length > 0
    ? {
        headline: asString(handoffRaw.headline, ""),
        summary: asString(handoffRaw.summary, ""),
        bullets: asArray<string>(handoffRaw.bullets),
      }
    : undefined;

  if (councilCards.length === 0 && !handoffBrief) return {};
  return {
    operator_copy: {
      ...(councilCards.length > 0 ? { council_cards: councilCards } : {}),
      ...(handoffBrief ? { handoff_brief: handoffBrief } : {}),
    },
  };
}

export function parsePlanningOutput(
  state: Record<string, unknown>,
): { analysis: AnalysisResult; features: FeatureSelection[]; planEstimates: PlanEstimate[] } {
  const raw = asRecord(state.planning ?? state.output ?? state);
  const localized = asRecord(raw.localized);
  const source = Object.keys(localized).length > 0 ? localized : raw;

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

  const personas = asArray(source.personas).map(parsePersona);
  const userStories = asArray(
    source.user_stories ?? source.userStories,
  ).map(parseUserStory);
  const kanoFeatures = asArray(
    source.kano_features ?? source.kanoFeatures,
  ).map(parseKanoFeature);

  const bm = asRecord(source.business_model ?? source.businessModel);
  const hasBm = Object.keys(bm).length > 0;

  const analysis: AnalysisResult = {
    personas,
    user_stories: userStories,
    kano_features: kanoFeatures,
    recommendations: asArray<string>(source.recommendations),
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
    ...parseUserJourneys(source),
    ...parseJobStories(source),
    ...parseIAAnalysis(source),
    ...parseActors(source),
    ...parseRoles(source),
    ...parseUseCases(source),
    ...parseRecommendedMilestones(source),
    ...parseDesignTokens(source),
    ...parseFeatureDecisions(source),
    ...parseRejectedFeatures(source),
    ...parsePlanningAssumptions(source),
    ...parseRedTeamFindings(source),
    ...parseNegativePersonas(source),
    ...parseTraceability(source),
    ...parseKillCriteria(source),
    ...parseConfidenceSummary(source),
    ...parsePlanningCoverageSummary(source),
    ...parsePlanningOperatorCopy(source),
    ...(asString(source.judge_summary ?? source.judgeSummary, "") ? { judge_summary: asString(source.judge_summary ?? source.judgeSummary, "") } : {}),
    ...(Object.keys(asRecord(source.model_assignments ?? source.modelAssignments)).length > 0 ? {
      model_assignments: Object.fromEntries(Object.entries(asRecord(source.model_assignments ?? source.modelAssignments)).map(([key, value]) => [key, asString(value, "")])),
    } : {}),
    ...(source.low_diversity_mode === true || source.lowDiversityMode === true ? { low_diversity_mode: true } : {}),
    ...(Object.keys(asRecord(raw.canonical)).length > 0 ? { canonical: asRecord(raw.canonical) } : {}),
    ...(Object.keys(localized).length > 0 ? { localized } : {}),
    ...(asString(raw.display_language ?? raw.displayLanguage, "") ? { display_language: asString(raw.display_language ?? raw.displayLanguage, "") } : {}),
    ...(asString(raw.localization_status ?? raw.localizationStatus, "") ? { localization_status: asString(raw.localization_status ?? raw.localizationStatus, "") } : {}),
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
    const localized = asRecord(r.localized);
    const source = Object.keys(localized).length > 0 ? { ...r, ...localized } : r;
    const scores = asRecord(source.scores ?? r.scores);
    const tokens = asRecord(source.tokens ?? r.tokens);
    const prototype = asRecord(source.prototype ?? r.prototype);
    const prototypeSpec = asRecord(r.prototype_spec ?? r.prototypeSpec ?? source.prototype_spec ?? source.prototypeSpec);
    const prototypeApp = asRecord(r.prototype_app ?? r.prototypeApp ?? source.prototype_app ?? source.prototypeApp);
    const appShell = asRecord(prototype.app_shell);
    const implementationBrief = asRecord(source.implementation_brief ?? source.implementationBrief);

    return {
      id: asString(r.id, `variant-${idx}`),
      model: asString(source.model ?? r.model, "unknown"),
      pattern_name: asString(
        source.pattern_name ?? source.patternName ?? r.pattern_name ?? r.patternName,
        "Untitled",
      ),
      description: asString(source.description ?? r.description, ""),
      preview_html: asString(
        source.preview_html ?? source.previewHtml ?? source.html ?? r.preview_html ?? r.previewHtml ?? r.html,
        "",
      ),
      primary_color: asString(source.primary_color ?? source.primaryColor ?? r.primary_color ?? r.primaryColor, undefined),
      accent_color: asString(source.accent_color ?? source.accentColor ?? r.accent_color ?? r.accentColor, undefined),
      prototype_spec: prototypeSpec && Object.keys(prototypeSpec).length > 0 ? {
        schema_version: asString(prototypeSpec.schema_version ?? prototypeSpec.schemaVersion, "1.0"),
        framework_target: asString(prototypeSpec.framework_target ?? prototypeSpec.frameworkTarget, "nextjs-app-router"),
        title: asString(prototypeSpec.title, ""),
        subtitle: asString(prototypeSpec.subtitle, ""),
        shell: (() => {
          const shell = asRecord(prototypeSpec.shell);
          return {
            kind: asString(shell.kind, "product-workspace"),
            layout: asString(shell.layout, "sidebar"),
            density: asString(shell.density, "medium"),
            status_badges: asArray<string>(shell.status_badges ?? shell.statusBadges),
            primary_navigation: asArray(shell.primary_navigation ?? shell.primaryNavigation).map((item, navIdx) => {
              const nav = asRecord(item);
              return {
                id: asString(nav.id, `nav-${navIdx}`),
                label: asString(nav.label, "Section"),
                priority: asString(nav.priority, "primary"),
              };
            }),
          };
        })(),
        theme: (() => {
          const theme = asRecord(prototypeSpec.theme);
          return {
            primary: asString(theme.primary, "#2563eb"),
            accent: asString(theme.accent, "#f59e0b"),
            background: asString(theme.background, "#0b1020"),
            surface: asString(theme.surface, "#111827"),
            text: asString(theme.text, "#f8fafc"),
            heading_font: asString(theme.heading_font ?? theme.headingFont, "IBM Plex Sans"),
            body_font: asString(theme.body_font ?? theme.bodyFont, "Noto Sans JP"),
          };
        })(),
        selected_features: asArray<string>(prototypeSpec.selected_features ?? prototypeSpec.selectedFeatures),
        screens: asArray(prototypeSpec.screens).map((item, screenIdx) => {
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
        routes: asArray(prototypeSpec.routes).map((item, routeIdx) => {
          const route = asRecord(item);
          return {
            id: asString(route.id, `route-${routeIdx}`),
            screen_id: asString(route.screen_id ?? route.screenId, ""),
            path: asString(route.path, "/"),
            segment: asString(route.segment, ""),
            title: asString(route.title, "Route"),
            headline: asString(route.headline, ""),
            layout: asString(route.layout, "workspace"),
            primary_actions: asArray<string>(route.primary_actions ?? route.primaryActions),
            states: asArray<string>(route.states),
          };
        }),
        components: asArray(prototypeSpec.components).map((item, componentIdx) => {
          const component = asRecord(item);
          return {
            id: asString(component.id, `component-${componentIdx}`),
            screen_id: asString(component.screen_id ?? component.screenId, ""),
            kind: asString(component.kind, "panel"),
            title: asString(component.title, "Component"),
            purpose: asString(component.purpose, ""),
            data_keys: asArray<string>(component.data_keys ?? component.dataKeys),
          };
        }),
        mock_data: asRecord(prototypeSpec.mock_data ?? prototypeSpec.mockData),
        state_matrix: Object.fromEntries(
          Object.entries(asRecord(prototypeSpec.state_matrix ?? prototypeSpec.stateMatrix)).map(([screenId, states]) => [
            screenId,
            asArray(states).map((item) => {
              const state = asRecord(item);
              return {
                state: asString(state.state, "default"),
                trigger: asString(state.trigger, ""),
                summary: asString(state.summary, ""),
              };
            }),
          ]),
        ),
        interaction_map: asArray(prototypeSpec.interaction_map ?? prototypeSpec.interactionMap).map((item) => {
          const interaction = asRecord(item);
          return {
            screen_id: asString(interaction.screen_id ?? interaction.screenId, ""),
            action: asString(interaction.action, ""),
            result: asString(interaction.result, ""),
          };
        }),
        acceptance_flows: asArray(prototypeSpec.acceptance_flows ?? prototypeSpec.acceptanceFlows).map((item, flowIdx) => {
          const flow = asRecord(item);
          return {
            id: asString(flow.id, `flow-${flowIdx}`),
            name: asString(flow.name, "Flow"),
            steps: asArray<string>(flow.steps),
            goal: asString(flow.goal, ""),
          };
        }),
        quality_targets: asArray<string>(prototypeSpec.quality_targets ?? prototypeSpec.qualityTargets),
        decision_scope: (() => {
          const scope = asRecord(prototypeSpec.decision_scope ?? prototypeSpec.decisionScope);
          return Object.keys(scope).length > 0 ? {
            phase: asString(scope.phase, undefined),
            fingerprint: asString(scope.fingerprint, undefined),
            lead_thesis: asString(scope.lead_thesis ?? scope.leadThesis, undefined),
            thesis_ids: asArray<string>(scope.thesis_ids ?? scope.thesisIds),
            risk_ids: asArray<string>(scope.risk_ids ?? scope.riskIds),
            primary_use_case_ids: asArray<string>(scope.primary_use_case_ids ?? scope.primaryUseCaseIds),
            selected_features: asArray<string>(scope.selected_features ?? scope.selectedFeatures),
            milestone_ids: asArray<string>(scope.milestone_ids ?? scope.milestoneIds),
            selected_design_id: asString(scope.selected_design_id ?? scope.selectedDesignId, undefined),
            selected_design_name: asString(scope.selected_design_name ?? scope.selectedDesignName, undefined),
          } : undefined;
        })(),
      } : undefined,
      prototype_app: prototypeApp && Object.keys(prototypeApp).length > 0 ? {
        artifact_kind: asString(prototypeApp.artifact_kind ?? prototypeApp.artifactKind, "runnable-prototype"),
        framework: asString(prototypeApp.framework, "nextjs"),
        router: asString(prototypeApp.router, "app"),
        entry_routes: asArray<string>(prototypeApp.entry_routes ?? prototypeApp.entryRoutes),
        dependencies: asRecord(prototypeApp.dependencies) as Record<string, string>,
        dev_dependencies: asRecord(prototypeApp.dev_dependencies ?? prototypeApp.devDependencies) as Record<string, string>,
        install_command: asString(prototypeApp.install_command ?? prototypeApp.installCommand, "npm install"),
        dev_command: asString(prototypeApp.dev_command ?? prototypeApp.devCommand, "npm run dev"),
        build_command: asString(prototypeApp.build_command ?? prototypeApp.buildCommand, "npm run build"),
        mock_api: asArray<string>(prototypeApp.mock_api ?? prototypeApp.mockApi),
        files: asArray(prototypeApp.files).map((item) => {
          const file = asRecord(item);
          return {
            path: asString(file.path, ""),
            kind: asString(file.kind, "txt"),
            content: asString(file.content, ""),
          };
        }),
        artifact_summary: (() => {
          const summary = asRecord(prototypeApp.artifact_summary ?? prototypeApp.artifactSummary);
          return Object.keys(summary).length > 0 ? {
            screen_count: asNumber(summary.screen_count ?? summary.screenCount, 0),
            route_count: asNumber(summary.route_count ?? summary.routeCount, 0),
            file_count: asNumber(summary.file_count ?? summary.fileCount, 0),
          } : undefined;
        })(),
      } : undefined,
      quality_focus: asArray<string>(source.quality_focus ?? source.qualityFocus ?? r.quality_focus ?? r.qualityFocus),
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
      implementation_brief: implementationBrief && Object.keys(implementationBrief).length > 0 ? {
        architecture_thesis: asString(
          implementationBrief.architecture_thesis ?? implementationBrief.architectureThesis,
          "",
        ),
        system_shape: asArray<string>(implementationBrief.system_shape ?? implementationBrief.systemShape),
        technical_choices: asArray(implementationBrief.technical_choices ?? implementationBrief.technicalChoices).map((item) => {
          const choice = asRecord(item);
          return {
            area: asString(choice.area, ""),
            decision: asString(choice.decision, ""),
            rationale: asString(choice.rationale, ""),
          };
        }),
        agent_lanes: asArray(implementationBrief.agent_lanes ?? implementationBrief.agentLanes).map((item) => {
          const lane = asRecord(item);
          return {
            role: asString(lane.role, ""),
            remit: asString(lane.remit, ""),
            skills: asArray<string>(lane.skills),
          };
        }),
        delivery_slices: asArray<string>(implementationBrief.delivery_slices ?? implementationBrief.deliverySlices),
      } : undefined,
      scorecard: (() => {
        const scorecard = asRecord(source.scorecard ?? r.scorecard);
        return Object.keys(scorecard).length > 0 ? {
          overall_score: asNumber(scorecard.overall_score ?? scorecard.overallScore, 0),
          summary: asString(scorecard.summary, ""),
          dimensions: asArray(scorecard.dimensions).map((item, dimensionIdx) => {
            const dimension = asRecord(item);
            return {
              id: asString(dimension.id, `dimension-${dimensionIdx}`),
              label: asString(dimension.label, "Dimension"),
              score: asNumber(dimension.score, 0),
              evidence: asString(dimension.evidence, ""),
            };
          }),
        } : undefined;
      })(),
      selection_rationale: (() => {
        const rationale = asRecord(source.selection_rationale ?? source.selectionRationale ?? r.selection_rationale ?? r.selectionRationale);
        return Object.keys(rationale).length > 0 ? {
          summary: asString(rationale.summary, ""),
          reasons: asArray<string>(rationale.reasons),
          tradeoffs: asArray<string>(rationale.tradeoffs),
          approval_focus: asArray<string>(rationale.approval_focus ?? rationale.approvalFocus),
          confidence: asNumber(rationale.confidence, 0),
          verdict: asString(rationale.verdict, "candidate") as "selected" | "candidate",
        } : undefined;
      })(),
      approval_packet: (() => {
        const packet = asRecord(source.approval_packet ?? source.approvalPacket ?? r.approval_packet ?? r.approvalPacket);
        return Object.keys(packet).length > 0 ? {
          operator_promise: asString(packet.operator_promise ?? packet.operatorPromise, ""),
          must_keep: asArray<string>(packet.must_keep ?? packet.mustKeep),
          guardrails: asArray<string>(packet.guardrails),
          review_checklist: asArray<string>(packet.review_checklist ?? packet.reviewChecklist),
          handoff_summary: asString(packet.handoff_summary ?? packet.handoffSummary, ""),
        } : undefined;
      })(),
      primary_workflows: asArray(source.primary_workflows ?? source.primaryWorkflows ?? r.primary_workflows ?? r.primaryWorkflows).map((item, workflowIdx) => {
        const workflow = asRecord(item);
        return {
          id: asString(workflow.id, `workflow-${workflowIdx}`),
          name: asString(workflow.name, "Workflow"),
          goal: asString(workflow.goal, ""),
          steps: asArray<string>(workflow.steps),
        };
      }),
      screen_specs: asArray(source.screen_specs ?? source.screenSpecs ?? r.screen_specs ?? r.screenSpecs).map((item, screenIdx) => {
        const screen = asRecord(item);
        return {
          id: asString(screen.id, `screen-spec-${screenIdx}`),
          title: asString(screen.title, "Screen"),
          purpose: asString(screen.purpose, ""),
          layout: asString(screen.layout, "workspace"),
          primary_actions: asArray<string>(screen.primary_actions ?? screen.primaryActions),
          module_count: asNumber(screen.module_count ?? screen.moduleCount, 0),
          route_path: asString(screen.route_path ?? screen.routePath, undefined),
        };
      }),
      artifact_completeness: (() => {
        const completeness = asRecord(source.artifact_completeness ?? source.artifactCompleteness ?? r.artifact_completeness ?? r.artifactCompleteness);
        return Object.keys(completeness).length > 0 ? {
          score: asNumber(completeness.score, 0),
          status: asString(completeness.status, "partial") as "complete" | "partial" | "incomplete",
          present: asArray<string>(completeness.present),
          missing: asArray<string>(completeness.missing),
          screen_count: asNumber(completeness.screen_count ?? completeness.screenCount, 0),
          workflow_count: asNumber(completeness.workflow_count ?? completeness.workflowCount, 0),
          route_count: asNumber(completeness.route_count ?? completeness.routeCount, 0),
        } : undefined;
      })(),
      freshness: (() => {
        const freshness = asRecord(source.freshness ?? r.freshness);
        return Object.keys(freshness).length > 0 ? {
          status: asString(freshness.status, "unknown") as "fresh" | "stale" | "unknown",
          can_handoff: asBoolean(freshness.can_handoff ?? freshness.canHandoff, false),
          current_fingerprint: asString(freshness.current_fingerprint ?? freshness.currentFingerprint, undefined),
          variant_fingerprint: asString(freshness.variant_fingerprint ?? freshness.variantFingerprint, undefined),
          reasons: asArray<string>(freshness.reasons),
        } : undefined;
      })(),
      preview_meta: (() => {
        const meta = asRecord(source.preview_meta ?? source.previewMeta ?? r.preview_meta ?? r.previewMeta);
        return Object.keys(meta).length > 0 ? {
          source: asString(meta.source, "template"),
          extraction_ok: asBoolean(meta.extraction_ok ?? meta.extractionOk, false),
          validation_ok: asBoolean(meta.validation_ok ?? meta.validationOk, false),
          fallback_reason: asString(meta.fallback_reason ?? meta.fallbackReason, undefined),
          html_size: asNumber(meta.html_size ?? meta.htmlSize, 0),
          screen_count_estimate: asNumber(meta.screen_count_estimate ?? meta.screenCountEstimate, 0),
          interactive_features: asArray<string>(meta.interactive_features ?? meta.interactiveFeatures),
          validation_issues: asArray<string>(meta.validation_issues ?? meta.validationIssues),
          copy_issues: asArray<string>(meta.copy_issues ?? meta.copyIssues),
          copy_issue_examples: asArray<string>(meta.copy_issue_examples ?? meta.copyIssueExamples),
          copy_quality_score: asNumber(meta.copy_quality_score ?? meta.copyQualityScore, 0),
        } : undefined;
      })(),
      decision_context_fingerprint: asString(
        source.decision_context_fingerprint ?? source.decisionContextFingerprint ?? r.decision_context_fingerprint ?? r.decisionContextFingerprint,
        undefined,
      ),
      rationale: asString(source.rationale ?? r.rationale, undefined),
      provider_note: asString(source.provider_note ?? source.providerNote ?? r.provider_note ?? r.providerNote, undefined),
      decision_scope: (() => {
        const scope = asRecord(source.decision_scope ?? source.decisionScope ?? r.decision_scope ?? r.decisionScope);
        return Object.keys(scope).length > 0 ? {
          phase: asString(scope.phase, undefined),
          fingerprint: asString(scope.fingerprint, undefined),
          lead_thesis: asString(scope.lead_thesis ?? scope.leadThesis, undefined),
          thesis_ids: asArray<string>(scope.thesis_ids ?? scope.thesisIds),
          risk_ids: asArray<string>(scope.risk_ids ?? scope.riskIds),
          primary_use_case_ids: asArray<string>(scope.primary_use_case_ids ?? scope.primaryUseCaseIds),
          selected_features: asArray<string>(scope.selected_features ?? scope.selectedFeatures),
          milestone_ids: asArray<string>(scope.milestone_ids ?? scope.milestoneIds),
          selected_design_id: asString(scope.selected_design_id ?? scope.selectedDesignId, undefined),
          selected_design_name: asString(scope.selected_design_name ?? scope.selectedDesignName, undefined),
        } : undefined;
      })(),
      narrative: (() => {
        const narrative = asRecord(source.narrative ?? r.narrative);
        return Object.keys(narrative).length > 0 ? {
          experience_thesis: asString(narrative.experience_thesis ?? narrative.experienceThesis, ""),
          operational_bet: asString(narrative.operational_bet ?? narrative.operationalBet, ""),
          signature_moments: asArray<string>(narrative.signature_moments ?? narrative.signatureMoments),
          handoff_note: asString(narrative.handoff_note ?? narrative.handoffNote, ""),
        } : undefined;
      })(),
      canonical: asRecord(r.canonical),
      localized,
      display_language: asString(r.display_language ?? r.displayLanguage, undefined),
      localization_status: asString(r.localization_status ?? r.localizationStatus, undefined),
      tokens: {
        in: asNumber(tokens.in ?? tokens.input, 0),
        out: asNumber(tokens.out ?? tokens.output, 0),
      },
      cost_usd: asNumber(source.cost_usd ?? source.costUsd ?? r.cost_usd ?? r.costUsd, 0),
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
