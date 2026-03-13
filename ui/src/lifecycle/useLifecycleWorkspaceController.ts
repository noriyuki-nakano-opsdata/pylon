import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { lifecycleApi } from "@/api/lifecycle";
import { useLifecycleRuntimeStream } from "@/hooks/useLifecycleRuntimeStream";
import {
  createWorkspaceProjectState,
  defaultEditableProjectPatch,
  editableProjectFromProject,
  editableProjectPayload,
  lifecycleWorkspaceReducer,
  selectEditableProjectPatch,
  stableProjectSnapshot,
} from "@/lifecycle/store";
import type {
  EditableProjectPatch,
  LifecycleWorkspaceProjectState,
} from "@/lifecycle/store";
import type {
  LifecycleActions,
  LifecycleContextValue,
  LifecycleWorkspaceView,
} from "@/pages/lifecycle/LifecycleContext";
import type {
  LifecycleAutonomyState,
  LifecycleNextAction,
  LifecyclePhase,
  LifecycleProject,
  PhaseStatus,
} from "@/types/lifecycle";

const PHASE_ORDER: LifecyclePhase[] = [
  "research",
  "planning",
  "design",
  "approval",
  "development",
  "deploy",
  "iterate",
];

const lifecycleProjectCache = new Map<string, LifecycleProject>();
const LIFECYCLE_CACHE_PREFIX = "pylon:lifecycle-project:";

function readLifecycleProjectCache(projectSlug: string): LifecycleProject | null {
  const inMemory = lifecycleProjectCache.get(projectSlug);
  if (inMemory) return inMemory;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(`${LIFECYCLE_CACHE_PREFIX}${projectSlug}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed as LifecycleProject : null;
  } catch {
    return null;
  }
}

function writeLifecycleProjectCache(projectSlug: string, project: LifecycleProject): void {
  lifecycleProjectCache.set(projectSlug, project);
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      `${LIFECYCLE_CACHE_PREFIX}${projectSlug}`,
      JSON.stringify(project),
    );
  } catch {
    // Ignore cache persistence failures.
  }
}

export function useLifecycleWorkspaceController(params: {
  projectSlug: string;
  basePath: string;
  currentPhase: LifecyclePhase | null;
}) {
  const { basePath, currentPhase, projectSlug } = params;
  const navigate = useNavigate();
  const [workspace, dispatch] = useReducer(
    lifecycleWorkspaceReducer,
    undefined,
    createWorkspaceProjectState,
  );
  const [hasHydratedContent, setHasHydratedContent] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const applyingRemoteRef = useRef(false);
  const autoAdvanceInFlightRef = useRef(false);
  const editableDraftRef = useRef<EditableProjectPatch>(defaultEditableProjectPatch());
  const prevNextActionRef = useRef(workspace.nextAction);

  const {
    spec,
    orchestrationMode,
    autonomyLevel,
    researchConfig,
    research,
    analysis,
    features,
    milestones,
    designVariants,
    selectedDesignId,
    approvalStatus,
    approvalComments,
    buildCode,
    buildCost,
    buildIteration,
    milestoneResults,
    planEstimates,
    selectedPreset,
    phaseStatuses,
    deployChecks,
    releases,
    feedbackItems,
    recommendations,
    artifacts,
    decisionLog,
    skillInvocations,
    delegations,
    phaseRuns,
    nextAction,
    autonomyState,
    blueprints,
    lastSavedAt,
    editableBaseline,
    hydrationState,
    hydrateError,
    isRefreshingProject,
    saveState,
  } = workspace;

  const editableDraft = selectEditableProjectPatch(workspace);
  const editableDraftSnapshot = stableProjectSnapshot(editableDraft);
  const editableBaselineSnapshot = stableProjectSnapshot(editableBaseline);
  editableDraftRef.current = editableDraft;
  const isHydrating = hydrationState === "loading";

  const applyProject = useCallback((
    project: LifecycleProject,
    options: { preserveDirtyEditable?: boolean } = {},
  ) => {
    applyingRemoteRef.current = true;
    writeLifecycleProjectCache(projectSlug, project);
    dispatch({
      type: "apply_project",
      project,
      preserveDirtyEditable: options.preserveDirtyEditable,
    });
    setHasHydratedContent(true);
    queueMicrotask(() => {
      applyingRemoteRef.current = false;
    });
  }, [projectSlug]);

  const applyRuntimeProject = useCallback((payload: {
    phaseStatuses?: PhaseStatus[];
    nextAction?: LifecycleNextAction | null;
    autonomyState?: LifecycleAutonomyState | null;
    updatedAt?: string;
    savedAt?: string;
  }) => {
    applyingRemoteRef.current = true;
    dispatch({ type: "apply_runtime", payload });
    queueMicrotask(() => {
      applyingRemoteRef.current = false;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!projectSlug) {
      dispatch({ type: "hydrate_failed", error: "", hasCachedProject: true });
      return;
    }
    dispatch({ type: "hydrate_started" });
    setHasHydratedContent(false);
    applyingRemoteRef.current = true;

    const cachedProject = readLifecycleProjectCache(projectSlug);
    if (cachedProject) {
      dispatch({ type: "hydrate_from_cache", project: cachedProject });
      setHasHydratedContent(true);
      applyingRemoteRef.current = false;
    }

    lifecycleApi.getProject(projectSlug)
      .then((project) => {
        if (cancelled) return;
        applyProject(project, { preserveDirtyEditable: Boolean(cachedProject) });
      })
      .catch(() => {
        if (cancelled) return;
        setHasHydratedContent(Boolean(cachedProject));
        applyingRemoteRef.current = false;
        dispatch({
          type: "hydrate_failed",
          error: "Lifecycle state を読み込めませんでした。もう一度読み込むと復旧できる場合があります。",
          hasCachedProject: Boolean(cachedProject),
        });
      });

    return () => {
      cancelled = true;
      clearTimeout(saveTimer.current);
    };
  }, [applyProject, projectSlug]);

  useEffect(() => {
    if (!projectSlug || !hasHydratedContent || applyingRemoteRef.current) return;
    if (editableDraftSnapshot === editableBaselineSnapshot) return;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const currentEditable = editableDraftRef.current;
      dispatch({ type: "save_started" });
      void lifecycleApi.saveProject(
        projectSlug,
        editableProjectPayload(currentEditable),
        { autoRun: false },
      )
        .then((response) => {
          const savedEditable = editableProjectFromProject(response.project);
          dispatch({
            type: "mark_saved",
            editableBaseline: savedEditable,
            savedAt: response.project.savedAt ?? new Date().toISOString(),
          });
          applyRuntimeProject(response.project);
        })
        .catch(() => {
          dispatch({ type: "save_failed" });
        });
    }, 500);
    return () => clearTimeout(saveTimer.current);
  }, [
    applyRuntimeProject,
    editableBaselineSnapshot,
    editableDraftSnapshot,
    hasHydratedContent,
    projectSlug,
  ]);

  useEffect(() => {
    if (saveState !== "saved") return;
    const timer = setTimeout(() => dispatch({ type: "save_reset" }), 2400);
    return () => clearTimeout(timer);
  }, [saveState]);

  const shouldStreamRuntime = Boolean(projectSlug && currentPhase);
  const runtimeStream = useLifecycleRuntimeStream(
    projectSlug,
    currentPhase,
    shouldStreamRuntime,
  );

  useEffect(() => {
    if (isHydrating || !currentPhase) return;
    const currentStatus = phaseStatuses.find((item) => item.phase === currentPhase);
    if (!currentStatus || currentStatus.status === "locked") {
      let fallbackPhase: LifecyclePhase | null = null;
      for (let index = PHASE_ORDER.length - 1; index >= 0; index -= 1) {
        const status = phaseStatuses.find((item) => item.phase === PHASE_ORDER[index]);
        if (status && (status.status === "in_progress" || status.status === "completed" || status.status === "available")) {
          fallbackPhase = PHASE_ORDER[index];
          break;
        }
      }
      if (fallbackPhase) {
        navigate(`${basePath}/lifecycle/${fallbackPhase}`, { replace: true });
      }
    }
  }, [basePath, currentPhase, isHydrating, navigate, phaseStatuses]);

  useEffect(() => {
    if (!runtimeStream.runtime) return;
    applyRuntimeProject(runtimeStream.runtime);
  }, [applyRuntimeProject, runtimeStream.runtime]);

  useEffect(() => {
    if (!runtimeStream.terminalEvent || !projectSlug) return;
    void lifecycleApi.getProject(projectSlug)
      .then((project) => {
        applyProject(project, { preserveDirtyEditable: true });
      })
      .catch(() => {
        // Ignore transient terminal refresh failures.
      });
  }, [applyProject, projectSlug, runtimeStream.terminalEvent]);

  useEffect(() => {
    if (isHydrating || !projectSlug || orchestrationMode !== "autonomous" || !nextAction?.phase) return;
    if (nextAction.type === "collect_input") return;
    if (currentPhase !== null) {
      prevNextActionRef.current = nextAction;
      return;
    }
    const changed = prevNextActionRef.current?.phase !== nextAction.phase
      || prevNextActionRef.current?.type !== nextAction.type;
    prevNextActionRef.current = nextAction;
    if (!changed) return;
    if (nextAction.type === "done") {
      if (currentPhase !== "iterate") navigate(`${basePath}/lifecycle/iterate`, { replace: true });
      return;
    }
    if (currentPhase !== nextAction.phase) {
      navigate(`${basePath}/lifecycle/${nextAction.phase}`, { replace: true });
    }
  }, [basePath, currentPhase, isHydrating, navigate, nextAction, orchestrationMode, projectSlug]);

  useEffect(() => {
    const remediationPayload = nextAction?.payload?.remediation;
    const selfHealingResearchRecovery = Boolean(
      nextAction?.canAutorun
      && nextAction?.type === "run_phase"
      && nextAction?.phase === "research"
      && remediationPayload
      && typeof remediationPayload === "object"
      && (remediationPayload as Record<string, unknown>).trigger === "quality_gate_recovery",
    );
    if (
      isHydrating
      || !projectSlug
      || !nextAction?.canAutorun
      || (orchestrationMode !== "autonomous" && !selfHealingResearchRecovery)
      || autoAdvanceInFlightRef.current
    ) {
      return;
    }
    autoAdvanceInFlightRef.current = true;
    void lifecycleApi.advanceProject(projectSlug, {
      orchestrationMode,
      maxSteps: 8,
    })
      .then((response) => {
        applyProject(response.project);
      })
      .catch(() => {
        autoAdvanceInFlightRef.current = false;
      })
      .finally(() => {
        autoAdvanceInFlightRef.current = false;
      });
  }, [applyProject, isHydrating, nextAction, orchestrationMode, projectSlug]);

  const state: LifecycleWorkspaceView = {
    spec,
    orchestrationMode,
    autonomyLevel,
    researchConfig,
    research,
    analysis,
    features,
    milestones,
    designVariants,
    selectedDesignId,
    approvalStatus,
    approvalComments,
    buildCode,
    buildCost,
    buildIteration,
    milestoneResults,
    planEstimates,
    selectedPreset,
    phaseStatuses,
    deployChecks,
    releases,
    feedbackItems,
    recommendations,
    artifacts,
    decisionLog,
    skillInvocations,
    delegations,
    phaseRuns,
    nextAction,
    autonomyState,
    runtimeObservedPhase: runtimeStream.runtime?.observedPhase ?? currentPhase,
    runtimeActivePhase: runtimeStream.runtime?.activePhase ?? null,
    runtimePhaseSummary: runtimeStream.runtime?.phaseSummary ?? null,
    runtimeActivePhaseSummary: runtimeStream.runtime?.activePhaseSummary ?? null,
    runtimeLiveTelemetry: runtimeStream.liveTelemetry,
    runtimeConnectionState: runtimeStream.connectionState,
    blueprints,
    isHydrating,
  };

  const actions: LifecycleActions = {
    editSpec: (value) => dispatch({ type: "edit_spec", value }),
    updateResearchConfig: (value) => dispatch({ type: "update_research_config", value }),
    replaceFeatures: (value) => dispatch({ type: "replace_features", value }),
    replaceMilestones: (value) => dispatch({ type: "replace_milestones", value }),
    selectDesign: (value) => dispatch({ type: "select_design", value }),
    recordBuildIteration: (value) => dispatch({ type: "record_build_iteration", value }),
    recordMilestoneResults: (value) => dispatch({ type: "record_milestone_results", value }),
    selectPreset: (value) => dispatch({ type: "select_preset", value }),
    applyProject,
    advancePhase: (phase) => dispatch({ type: "advance_phase", phase }),
    completePhase: (phase) => dispatch({ type: "complete_phase", phase }),
  };

  return {
    workspace,
    contextValue: { state, actions } satisfies LifecycleContextValue,
    runtimeStream,
    hasHydratedContent,
    isHydrating,
    hydrateError,
    isRefreshingProject,
    saveState,
    lastSavedAt,
  };
}
