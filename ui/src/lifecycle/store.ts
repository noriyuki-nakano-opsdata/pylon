import type {
  ApprovalComment,
  AnalysisResult,
  DeployCheck,
  DesignVariant,
  FeatureSelection,
  FeedbackItem,
  LifecycleArtifact,
  LifecycleAutonomyLevel,
  LifecycleAutonomyState,
  LifecycleDecision,
  LifecycleDelegation,
  LifecycleNextAction,
  LifecycleOrchestrationMode,
  LifecyclePhase,
  LifecycleProject,
  LifecycleResearchConfig,
  LifecycleRecommendation,
  LifecycleSkillInvocation,
  MarketResearch,
  Milestone,
  MilestoneResult,
  PhaseBlueprint,
  PhaseStatus,
  PlanEstimate,
  PlanPreset,
  ReleaseRecord,
} from "@/types/lifecycle";

export type EditableProjectPatch = {
  spec: string;
  orchestrationMode: LifecycleOrchestrationMode;
  autonomyLevel: LifecycleAutonomyLevel;
  researchConfig: LifecycleResearchConfig;
  features: FeatureSelection[];
  milestones: Milestone[];
  selectedDesignId: string | null;
  selectedPreset: PlanPreset;
};

const PHASE_ORDER: LifecyclePhase[] = [
  "research",
  "planning",
  "design",
  "approval",
  "development",
  "deploy",
  "iterate",
];

export function defaultResearchConfig(): LifecycleResearchConfig {
  return {
    competitorUrls: [],
    depth: "standard",
    outputLanguage: "ja",
  };
}

export function defaultStatuses(): PhaseStatus[] {
  return PHASE_ORDER.map((phase, index) => ({
    phase,
    status: index === 0 ? "available" : "locked",
    version: 1,
  }));
}

function emptyBlueprint(phase: LifecyclePhase): PhaseBlueprint {
  return {
    phase,
    title: phase,
    summary: "",
    team: [],
    artifacts: [],
    quality_gates: [],
  };
}

export function defaultBlueprints(): Record<LifecyclePhase, PhaseBlueprint> {
  return {
    research: emptyBlueprint("research"),
    planning: emptyBlueprint("planning"),
    design: emptyBlueprint("design"),
    approval: emptyBlueprint("approval"),
    development: emptyBlueprint("development"),
    deploy: emptyBlueprint("deploy"),
    iterate: emptyBlueprint("iterate"),
  };
}

export function normalizeBlueprints(
  blueprints?: Partial<Record<LifecyclePhase, PhaseBlueprint>>,
): Record<LifecyclePhase, PhaseBlueprint> {
  return {
    ...defaultBlueprints(),
    ...(blueprints ?? {}),
  };
}

export function defaultEditableProjectPatch(): EditableProjectPatch {
  return {
    spec: "",
    orchestrationMode: "workflow",
    autonomyLevel: "A3",
    researchConfig: defaultResearchConfig(),
    features: [],
    milestones: [],
    selectedDesignId: null,
    selectedPreset: "standard",
  };
}

export function toEditableProjectPatch(
  state: EditableProjectPatch,
): EditableProjectPatch {
  return {
    spec: state.spec,
    orchestrationMode: state.orchestrationMode,
    autonomyLevel: state.autonomyLevel,
    researchConfig: state.researchConfig,
    features: state.features,
    milestones: state.milestones,
    selectedDesignId: state.selectedDesignId ?? null,
    selectedPreset: state.selectedPreset,
  };
}

export function editableProjectPayload(
  state: EditableProjectPatch,
): Partial<LifecycleProject> {
  return {
    ...state,
    selectedDesignId: state.selectedDesignId ?? undefined,
  };
}

export function editableProjectFromProject(
  project: LifecycleProject,
): EditableProjectPatch {
  return {
    spec: project.spec || project.description || "",
    orchestrationMode: project.orchestrationMode ?? "workflow",
    autonomyLevel: project.autonomyLevel ?? "A3",
    researchConfig: project.researchConfig ?? defaultResearchConfig(),
    features: project.features ?? [],
    milestones: project.milestones ?? [],
    selectedDesignId: project.selectedDesignId ?? null,
    selectedPreset: project.selectedPreset ?? "standard",
  };
}

export function stableProjectSnapshot(payload: EditableProjectPatch): string {
  return JSON.stringify(payload);
}

function editableFieldChanged<T extends keyof EditableProjectPatch>(
  key: T,
  local: EditableProjectPatch,
  saved: EditableProjectPatch,
): boolean {
  return JSON.stringify(local[key]) !== JSON.stringify(saved[key]);
}

export function mergeEditableProjectPatch(
  local: EditableProjectPatch,
  saved: EditableProjectPatch,
  server: EditableProjectPatch,
): {
  applied: EditableProjectPatch;
  baseline: EditableProjectPatch;
} {
  const specChanged = editableFieldChanged("spec", local, saved);
  const modeChanged = editableFieldChanged("orchestrationMode", local, saved);
  const autonomyChanged = editableFieldChanged("autonomyLevel", local, saved);
  const researchConfigChanged = editableFieldChanged(
    "researchConfig",
    local,
    saved,
  );
  const featuresChanged = editableFieldChanged("features", local, saved);
  const milestonesChanged = editableFieldChanged("milestones", local, saved);
  const designChanged = editableFieldChanged("selectedDesignId", local, saved);
  const presetChanged = editableFieldChanged("selectedPreset", local, saved);

  return {
    applied: {
      spec: specChanged ? local.spec : server.spec,
      orchestrationMode: modeChanged
        ? local.orchestrationMode
        : server.orchestrationMode,
      autonomyLevel: autonomyChanged ? local.autonomyLevel : server.autonomyLevel,
      researchConfig: researchConfigChanged
        ? local.researchConfig
        : server.researchConfig,
      features: featuresChanged ? local.features : server.features,
      milestones: milestonesChanged ? local.milestones : server.milestones,
      selectedDesignId: designChanged
        ? local.selectedDesignId
        : server.selectedDesignId,
      selectedPreset: presetChanged ? local.selectedPreset : server.selectedPreset,
    },
    baseline: {
      spec: specChanged ? saved.spec : server.spec,
      orchestrationMode: modeChanged
        ? saved.orchestrationMode
        : server.orchestrationMode,
      autonomyLevel: autonomyChanged ? saved.autonomyLevel : server.autonomyLevel,
      researchConfig: researchConfigChanged
        ? saved.researchConfig
        : server.researchConfig,
      features: featuresChanged ? saved.features : server.features,
      milestones: milestonesChanged ? saved.milestones : server.milestones,
      selectedDesignId: designChanged
        ? saved.selectedDesignId
        : server.selectedDesignId,
      selectedPreset: presetChanged ? saved.selectedPreset : server.selectedPreset,
    },
  };
}

export interface LifecycleWorkspaceProjectState {
  spec: string;
  orchestrationMode: LifecycleOrchestrationMode;
  autonomyLevel: LifecycleAutonomyLevel;
  researchConfig: LifecycleResearchConfig;
  research: MarketResearch | null;
  analysis: AnalysisResult | null;
  features: FeatureSelection[];
  milestones: Milestone[];
  designVariants: DesignVariant[];
  selectedDesignId: string | null;
  approvalStatus: LifecycleProject["approvalStatus"];
  approvalComments: ApprovalComment[];
  buildCode: string | null;
  buildCost: number;
  buildIteration: number;
  milestoneResults: MilestoneResult[];
  planEstimates: PlanEstimate[];
  selectedPreset: PlanPreset;
  phaseStatuses: PhaseStatus[];
  deployChecks: DeployCheck[];
  releases: ReleaseRecord[];
  feedbackItems: FeedbackItem[];
  recommendations: LifecycleRecommendation[];
  artifacts: LifecycleArtifact[];
  decisionLog: LifecycleDecision[];
  skillInvocations: LifecycleSkillInvocation[];
  delegations: LifecycleDelegation[];
  phaseRuns: LifecycleProject["phaseRuns"];
  nextAction: LifecycleNextAction | null;
  autonomyState: LifecycleAutonomyState | null;
  blueprints: Record<LifecyclePhase, PhaseBlueprint>;
  lastSavedAt: string | null;
  editableBaseline: EditableProjectPatch;
  hydrationState: "idle" | "loading" | "ready" | "error";
  hydrateError: string | null;
  isRefreshingProject: boolean;
  saveState: "idle" | "saving" | "saved" | "error";
}

export function createWorkspaceProjectState(): LifecycleWorkspaceProjectState {
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
    blueprints: defaultBlueprints(),
    lastSavedAt: null,
    editableBaseline: defaultEditableProjectPatch(),
    hydrationState: "idle",
    hydrateError: null,
    isRefreshingProject: false,
    saveState: "idle",
  };
}

type RuntimeProjectPatch = {
  phaseStatuses?: PhaseStatus[];
  nextAction?: LifecycleNextAction | null;
  autonomyState?: LifecycleAutonomyState | null;
  savedAt?: string;
};

function applyServerProject(
  state: LifecycleWorkspaceProjectState,
  project: LifecycleProject,
  preserveDirtyEditable: boolean,
): LifecycleWorkspaceProjectState {
  const serverEditable = editableProjectFromProject(project);
  const localEditable = selectEditableProjectPatch(state);
  const { applied: editablePatch, baseline: editableBaseline } = preserveDirtyEditable
    ? mergeEditableProjectPatch(localEditable, state.editableBaseline, serverEditable)
    : { applied: serverEditable, baseline: serverEditable };

  return {
    ...state,
    spec: editablePatch.spec,
    orchestrationMode: editablePatch.orchestrationMode,
    autonomyLevel: editablePatch.autonomyLevel,
    researchConfig: editablePatch.researchConfig,
    research: project.research ?? null,
    analysis: project.analysis ?? null,
    features: editablePatch.features,
    milestones: editablePatch.milestones,
    designVariants: project.designVariants ?? [],
    selectedDesignId: editablePatch.selectedDesignId,
    approvalStatus: project.approvalStatus ?? "pending",
    approvalComments: project.approvalComments ?? [],
    buildCode: project.buildCode ?? null,
    buildCost: project.buildCost ?? 0,
    buildIteration: project.buildIteration ?? 0,
    milestoneResults: project.milestoneResults ?? [],
    planEstimates: project.planEstimates ?? [],
    selectedPreset: editablePatch.selectedPreset,
    phaseStatuses: project.phaseStatuses ?? defaultStatuses(),
    deployChecks: project.deployChecks ?? [],
    releases: project.releases ?? [],
    feedbackItems: project.feedbackItems ?? [],
    recommendations: project.recommendations ?? [],
    artifacts: project.artifacts ?? [],
    decisionLog: project.decisionLog ?? [],
    skillInvocations: project.skillInvocations ?? [],
    delegations: project.delegations ?? [],
    phaseRuns: project.phaseRuns ?? [],
    nextAction: project.nextAction ?? null,
    autonomyState: project.autonomyState ?? null,
    blueprints: normalizeBlueprints(project.blueprints),
    lastSavedAt: project.savedAt ?? null,
    editableBaseline,
    hydrationState: "ready",
    hydrateError: null,
    isRefreshingProject: false,
    saveState:
      preserveDirtyEditable
      && stableProjectSnapshot(editablePatch) !== stableProjectSnapshot(editableBaseline)
        ? state.saveState
        : "idle",
  };
}

export type LifecycleWorkspaceAction =
  | {
      type: "hydrate_started";
    }
  | {
      type: "hydrate_from_cache";
      project: LifecycleProject;
    }
  | {
      type: "apply_project";
      project: LifecycleProject;
      preserveDirtyEditable?: boolean;
    }
  | {
      type: "apply_runtime";
      payload: RuntimeProjectPatch;
    }
  | {
      type: "hydrate_failed";
      error: string;
      hasCachedProject: boolean;
    }
  | {
      type: "save_started";
    }
  | {
      type: "edit_spec";
      value: string;
    }
  | {
      type: "update_research_config";
      value: LifecycleResearchConfig;
    }
  | {
      type: "replace_features";
      value: FeatureSelection[];
    }
  | {
      type: "replace_milestones";
      value: Milestone[];
    }
  | {
      type: "select_design";
      value: string | null;
    }
  | {
      type: "select_preset";
      value: PlanPreset;
    }
  | {
      type: "record_build_iteration";
      value: number;
    }
  | {
      type: "record_milestone_results";
      value: MilestoneResult[];
    }
  | {
      type: "mark_saved";
      editableBaseline: EditableProjectPatch;
      savedAt: string | null;
    }
  | {
      type: "save_reset";
    }
  | {
      type: "save_failed";
    }
  | {
      type: "set";
      key: keyof LifecycleWorkspaceProjectState;
      value: LifecycleWorkspaceProjectState[keyof LifecycleWorkspaceProjectState];
    }
  | {
      type: "advance_phase";
      phase: LifecyclePhase;
    }
  | {
      type: "complete_phase";
      phase: LifecyclePhase;
    };

export function lifecycleWorkspaceReducer(
  state: LifecycleWorkspaceProjectState,
  action: LifecycleWorkspaceAction,
): LifecycleWorkspaceProjectState {
  if (action.type === "hydrate_started") {
    return {
      ...state,
      hydrationState: "loading",
      hydrateError: null,
      isRefreshingProject: false,
    };
  }

  if (action.type === "hydrate_from_cache") {
    return {
      ...applyServerProject(state, action.project, false),
      isRefreshingProject: true,
    };
  }

  if (action.type === "apply_project") {
    return applyServerProject(
      state,
      action.project,
      action.preserveDirtyEditable ?? false,
    );
  }

  if (action.type === "apply_runtime") {
    return {
      ...state,
      phaseStatuses: action.payload.phaseStatuses ?? state.phaseStatuses,
      nextAction:
        action.payload.nextAction !== undefined
          ? action.payload.nextAction
          : state.nextAction,
      autonomyState:
        action.payload.autonomyState !== undefined
          ? action.payload.autonomyState
          : state.autonomyState,
      lastSavedAt: action.payload.savedAt ?? state.lastSavedAt,
    };
  }

  if (action.type === "hydrate_failed") {
    return {
      ...state,
      hydrationState: action.hasCachedProject ? "ready" : "error",
      hydrateError: action.hasCachedProject ? null : action.error,
      isRefreshingProject: false,
    };
  }

  if (action.type === "save_started") {
    return {
      ...state,
      saveState: "saving",
    };
  }

  if (action.type === "set") {
    return {
      ...state,
      [action.key]: action.value,
    };
  }

  if (action.type === "edit_spec") {
    return {
      ...state,
      spec: action.value,
    };
  }

  if (action.type === "update_research_config") {
    return {
      ...state,
      researchConfig: action.value,
    };
  }

  if (action.type === "replace_features") {
    return {
      ...state,
      features: action.value,
    };
  }

  if (action.type === "replace_milestones") {
    return {
      ...state,
      milestones: action.value,
    };
  }

  if (action.type === "select_design") {
    return {
      ...state,
      selectedDesignId: action.value,
    };
  }

  if (action.type === "select_preset") {
    return {
      ...state,
      selectedPreset: action.value,
    };
  }

  if (action.type === "record_build_iteration") {
    return {
      ...state,
      buildIteration: action.value,
    };
  }

  if (action.type === "record_milestone_results") {
    return {
      ...state,
      milestoneResults: action.value,
    };
  }

  if (action.type === "mark_saved") {
    return {
      ...state,
      editableBaseline: action.editableBaseline,
      lastSavedAt: action.savedAt,
      saveState: "saved",
    };
  }

  if (action.type === "save_reset") {
    return {
      ...state,
      saveState: "idle",
    };
  }

  if (action.type === "save_failed") {
    return {
      ...state,
      saveState: "error",
    };
  }

  if (action.type === "advance_phase") {
    const phaseStatuses = state.phaseStatuses.map((entry) => ({ ...entry }));
    const index = PHASE_ORDER.indexOf(action.phase);
    const current = phaseStatuses.find((item) => item.phase === action.phase);
    if (current) {
      current.status = "in_progress";
    }
    if (index + 1 < PHASE_ORDER.length) {
      const nextEntry = phaseStatuses.find(
        (item) => item.phase === PHASE_ORDER[index + 1],
      );
      if (nextEntry && nextEntry.status === "locked") {
        nextEntry.status = "available";
      }
    }
    return {
      ...state,
      phaseStatuses,
    };
  }

  if (action.type === "complete_phase") {
    const phaseStatuses = state.phaseStatuses.map((entry) => ({ ...entry }));
    const index = PHASE_ORDER.indexOf(action.phase);
    const current = phaseStatuses.find((item) => item.phase === action.phase);
    if (current) {
      current.status = "completed";
      current.completedAt = new Date().toISOString();
    }
    if (index + 1 < PHASE_ORDER.length) {
      const nextEntry = phaseStatuses.find(
        (item) => item.phase === PHASE_ORDER[index + 1],
      );
      if (nextEntry && nextEntry.status === "locked") {
        nextEntry.status = "available";
      }
    }
    return {
      ...state,
      phaseStatuses,
    };
  }

  return state;
}

export function selectEditableProjectPatch(
  state: LifecycleWorkspaceProjectState,
): EditableProjectPatch {
  return toEditableProjectPatch({
    spec: state.spec,
    orchestrationMode: state.orchestrationMode,
    autonomyLevel: state.autonomyLevel,
    researchConfig: state.researchConfig,
    features: state.features,
    milestones: state.milestones,
    selectedDesignId: state.selectedDesignId,
    selectedPreset: state.selectedPreset,
  });
}

export function isEditableProjectDirty(
  state: LifecycleWorkspaceProjectState,
): boolean {
  return (
    stableProjectSnapshot(selectEditableProjectPatch(state))
    !== stableProjectSnapshot(state.editableBaseline)
  );
}
