import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "@/api/client";
import { lifecycleApi, normalizeLifecycleProject } from "@/api/lifecycle";
import { useLifecycleRuntimeStream } from "@/hooks/useLifecycleRuntimeStream";
import { deriveVisiblePhaseStatuses } from "@/lifecycle/phaseStatus";
import { mergeProductIdentityFallback } from "@/lifecycle/productIdentity";
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
} from "@/lifecycle/store";
import type {
  LifecycleActions,
  LifecycleContextValue,
  LifecycleWorkspaceView,
} from "@/pages/lifecycle/LifecycleContext";
import type {
  LifecycleAutonomyState,
  LifecycleGovernanceMode,
  LifecycleNextAction,
  LifecyclePhase,
  LifecycleProject,
  PhaseStatus,
} from "@/types/lifecycle";

const lifecycleProjectCache = new Map<string, LifecycleProject>();
const LIFECYCLE_CACHE_PREFIX = "pylon:lifecycle-project:";
const LIFECYCLE_CACHE_VERSION = 6;

type LifecycleProjectCacheRecord = {
  version: number;
  project: LifecycleProject;
};

function normalizeCachedProject(
  project: LifecycleProject,
): LifecycleProject {
  return normalizeLifecycleProject(project);
}

function readLifecycleProjectCache(projectSlug: string): LifecycleProject | null {
  const inMemory = lifecycleProjectCache.get(projectSlug);
  if (inMemory) return inMemory;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(`${LIFECYCLE_CACHE_PREFIX}${projectSlug}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const cacheRecord = "version" in parsed && "project" in parsed
      ? parsed as LifecycleProjectCacheRecord
      : null;
    if (!cacheRecord || cacheRecord.version !== LIFECYCLE_CACHE_VERSION) return null;
    return normalizeCachedProject(cacheRecord.project);
  } catch {
    return null;
  }
}

function writeLifecycleProjectCache(projectSlug: string, project: LifecycleProject): void {
  const normalized = normalizeCachedProject(project);
  lifecycleProjectCache.set(projectSlug, normalized);
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      `${LIFECYCLE_CACHE_PREFIX}${projectSlug}`,
      JSON.stringify({
        version: LIFECYCLE_CACHE_VERSION,
        project: normalized,
      } satisfies LifecycleProjectCacheRecord),
    );
  } catch {
    // Ignore cache persistence failures.
  }
}

function clearLifecycleProjectCache(projectSlug: string): void {
  lifecycleProjectCache.delete(projectSlug);
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(`${LIFECYCLE_CACHE_PREFIX}${projectSlug}`);
  } catch {
    // Ignore cache cleanup failures.
  }
}

export function useLifecycleWorkspaceController(params: {
  projectSlug: string;
  basePath: string;
  currentPhase: LifecyclePhase | null;
  initialProject?: LifecycleProject | null;
}) {
  const {
    basePath,
    currentPhase,
    projectSlug,
    initialProject = null,
  } = params;
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
    governanceMode,
    autonomyLevel,
    decisionContext,
    productIdentity,
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
    deliveryPlan,
    valueContract,
    outcomeTelemetryContract,
    developmentHandoff,
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
    requirements,
    requirementsConfig,
    reverseEngineering,
    taskDecomposition,
    dcsAnalysis,
    technicalDesign,
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
  const visiblePhaseStatuses = deriveVisiblePhaseStatuses(phaseStatuses, nextAction);
  const fallbackProductIdentity = initialProject?.productIdentity ?? null;

  const applyProject = useCallback((
    project: LifecycleProject,
    options: { preserveDirtyEditable?: boolean } = {},
  ) => {
    const normalizedProject = {
      ...normalizeCachedProject(project),
      productIdentity: mergeProductIdentityFallback(
        project.productIdentity,
        editableDraftRef.current.productIdentity ?? fallbackProductIdentity,
        {
          fallbackProductName: project.name?.trim() || project.projectId,
        },
      ),
    } satisfies LifecycleProject;
    applyingRemoteRef.current = true;
    writeLifecycleProjectCache(projectSlug, normalizedProject);
    dispatch({
      type: "apply_project",
      project: normalizedProject,
      preserveDirtyEditable: options.preserveDirtyEditable,
    });
    setHasHydratedContent(true);
    queueMicrotask(() => {
      applyingRemoteRef.current = false;
    });
  }, [fallbackProductIdentity, projectSlug]);

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

  const applyCachedProject = useCallback((project: LifecycleProject) => {
    const normalizedProject = {
      ...normalizeCachedProject(project),
      productIdentity: mergeProductIdentityFallback(
        project.productIdentity,
        editableDraftRef.current.productIdentity ?? fallbackProductIdentity,
        {
          fallbackProductName: project.name?.trim() || project.projectId,
        },
      ),
    } satisfies LifecycleProject;
    applyingRemoteRef.current = true;
    writeLifecycleProjectCache(projectSlug, normalizedProject);
    dispatch({
      type: "hydrate_from_cache",
      project: normalizedProject,
    });
    setHasHydratedContent(true);
    queueMicrotask(() => {
      applyingRemoteRef.current = false;
    });
  }, [fallbackProductIdentity, projectSlug]);

  useEffect(() => {
    let cancelled = false;
    if (!projectSlug) {
      dispatch({ type: "hydrate_failed", error: "", hasCachedProject: true });
      return;
    }
    dispatch({ type: "hydrate_started" });
    setHasHydratedContent(false);
    applyingRemoteRef.current = true;

    const cachedProject = readLifecycleProjectCache(projectSlug) ?? initialProject;
    if (cachedProject) {
      applyCachedProject(cachedProject);
    }

    lifecycleApi.getProject(projectSlug)
      .then((project) => {
        if (cancelled) return;
        applyProject(project, { preserveDirtyEditable: Boolean(cachedProject) });
      })
      .catch((error) => {
        if (cancelled) return;
        const isNotFound = error instanceof ApiError && error.status === 404;
        if (isNotFound) {
          clearLifecycleProjectCache(projectSlug);
          setHasHydratedContent(false);
        } else {
          setHasHydratedContent(Boolean(cachedProject));
        }
        applyingRemoteRef.current = false;
        dispatch({
          type: "hydrate_failed",
          error: "Lifecycle state を読み込めませんでした。もう一度読み込むと復旧できる場合があります。",
          hasCachedProject: Boolean(cachedProject) && !isNotFound,
        });
      });

    return () => {
      cancelled = true;
      clearTimeout(saveTimer.current);
    };
  }, [applyCachedProject, applyProject, initialProject, projectSlug]);

  useEffect(() => {
    if (
      !projectSlug
      || !hasHydratedContent
      || applyingRemoteRef.current
      || hydrationState !== "ready"
      || isRefreshingProject
    ) {
      return;
    }
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
          const normalizedProject = {
            ...response.project,
            productIdentity: mergeProductIdentityFallback(
              response.project.productIdentity,
              currentEditable.productIdentity,
              {
                fallbackProductName: response.project.name?.trim() || response.project.projectId,
              },
            ),
          } satisfies LifecycleProject;
          writeLifecycleProjectCache(projectSlug, normalizedProject);
          const savedEditable = editableProjectFromProject(normalizedProject);
          dispatch({
            type: "mark_saved",
            editableBaseline: savedEditable,
            savedAt: normalizedProject.savedAt ?? new Date().toISOString(),
          });
          applyRuntimeProject(normalizedProject);
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
    hydrationState,
    isRefreshingProject,
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
    governanceMode,
    autonomyLevel,
    decisionContext,
    productIdentity,
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
    deliveryPlan,
    valueContract,
    outcomeTelemetryContract,
    developmentHandoff,
    planEstimates,
    selectedPreset,
    phaseStatuses: visiblePhaseStatuses,
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
    requirements,
    requirementsConfig,
    reverseEngineering,
    taskDecomposition,
    dcsAnalysis,
    technicalDesign,
    isHydrating,
  };

  const actions: LifecycleActions = {
    editSpec: (value) => dispatch({ type: "edit_spec", value }),
    selectGovernanceMode: (value: LifecycleGovernanceMode) => dispatch({ type: "update_governance_mode", value }),
    updateProductIdentity: (value) => dispatch({ type: "update_product_identity", value }),
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
