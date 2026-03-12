import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { cn } from "@/lib/utils";
import { lifecycleApi } from "@/api/lifecycle";
import { LifecycleOperatorConsole } from "@/components/lifecycle/LifecycleOperatorConsole";
import { PhaseNav } from "@/components/lifecycle/PhaseNav";
import { LifecycleWorkspaceHeader } from "@/components/lifecycle/LifecycleWorkspaceHeader";
import { useLifecycleRuntimeStream } from "@/hooks/useLifecycleRuntimeStream";
import { LifecycleContext } from "./LifecycleContext";
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
  LifecyclePhaseRun,
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
import type { LifecycleState } from "./LifecycleContext";

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

const defaultStatuses = (): PhaseStatus[] => PHASE_ORDER.map((phase, index) => ({
  phase,
  status: index === 0 ? "available" : "locked",
  version: 1,
}));

const defaultResearchConfig = (): LifecycleResearchConfig => ({
  competitorUrls: [],
  depth: "standard",
  outputLanguage: "ja",
});

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

function defaultBlueprints(): Record<LifecyclePhase, PhaseBlueprint> {
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

function normalizeBlueprints(
  blueprints?: Partial<Record<LifecyclePhase, PhaseBlueprint>>,
): Record<LifecyclePhase, PhaseBlueprint> {
  return {
    ...defaultBlueprints(),
    ...(blueprints ?? {}),
  };
}

type EditableProjectPatch = {
  spec: string;
  orchestrationMode: LifecycleOrchestrationMode;
  autonomyLevel: LifecycleAutonomyLevel;
  researchConfig: LifecycleResearchConfig;
  features: FeatureSelection[];
  milestones: Milestone[];
  selectedDesignId: string | null;
  selectedPreset: PlanPreset;
};

function defaultEditableProjectPatch(): EditableProjectPatch {
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

function toEditableProjectPatch(state: EditableProjectPatch): EditableProjectPatch {
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

function editableProjectPayload(state: EditableProjectPatch): Partial<LifecycleProject> {
  return {
    ...state,
    selectedDesignId: state.selectedDesignId ?? undefined,
  };
}

function editableProjectFromProject(project: LifecycleProject): EditableProjectPatch {
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

function stableProjectSnapshot(payload: EditableProjectPatch): string {
  return JSON.stringify(payload);
}

function readLifecycleProjectCache(projectSlug: string): LifecycleProject | null {
  const inMemory = lifecycleProjectCache.get(projectSlug);
  if (inMemory) {
    return inMemory;
  }
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(`${LIFECYCLE_CACHE_PREFIX}${projectSlug}`);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return parsed as LifecycleProject;
  } catch {
    return null;
  }
}

function writeLifecycleProjectCache(projectSlug: string, project: LifecycleProject): void {
  lifecycleProjectCache.set(projectSlug, project);
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.setItem(
      `${LIFECYCLE_CACHE_PREFIX}${projectSlug}`,
      JSON.stringify(project),
    );
  } catch {
    // Ignore cache persistence failures.
  }
}

function LifecycleContentSkeleton() {
  return (
    <div className="space-y-6 px-6 py-8">
      <div className="space-y-3">
        <div className="h-3 w-28 rounded-full bg-muted/70" />
        <div className="h-9 w-80 max-w-full rounded-2xl bg-muted/60" />
        <div className="h-4 w-[32rem] max-w-full rounded-full bg-muted/40" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.95fr]">
        <div className="space-y-4 rounded-3xl border border-border/60 bg-card/60 p-6">
          <div className="h-5 w-40 rounded-full bg-muted/60" />
          <div className="space-y-3">
            <div className="h-12 rounded-2xl bg-muted/40" />
            <div className="h-28 rounded-3xl bg-muted/30" />
            <div className="h-10 w-40 rounded-2xl bg-muted/50" />
          </div>
        </div>
        <div className="space-y-4 rounded-3xl border border-border/60 bg-card/50 p-6">
          <div className="h-5 w-36 rounded-full bg-muted/60" />
          <div className="space-y-3">
            <div className="h-20 rounded-2xl bg-muted/35" />
            <div className="h-20 rounded-2xl bg-muted/35" />
            <div className="h-20 rounded-2xl bg-muted/35" />
          </div>
        </div>
      </div>
    </div>
  );
}

function editableFieldChanged<T extends keyof EditableProjectPatch>(
  key: T,
  local: EditableProjectPatch,
  saved: EditableProjectPatch,
): boolean {
  return JSON.stringify(local[key]) !== JSON.stringify(saved[key]);
}

function mergeEditableProjectPatch(
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
  const researchConfigChanged = editableFieldChanged("researchConfig", local, saved);
  const featuresChanged = editableFieldChanged("features", local, saved);
  const milestonesChanged = editableFieldChanged("milestones", local, saved);
  const designChanged = editableFieldChanged("selectedDesignId", local, saved);
  const presetChanged = editableFieldChanged("selectedPreset", local, saved);

  return {
    applied: {
      spec: specChanged ? local.spec : server.spec,
      orchestrationMode: modeChanged ? local.orchestrationMode : server.orchestrationMode,
      autonomyLevel: autonomyChanged ? local.autonomyLevel : server.autonomyLevel,
      researchConfig: researchConfigChanged ? local.researchConfig : server.researchConfig,
      features: featuresChanged ? local.features : server.features,
      milestones: milestonesChanged ? local.milestones : server.milestones,
      selectedDesignId: designChanged ? local.selectedDesignId : server.selectedDesignId,
      selectedPreset: presetChanged ? local.selectedPreset : server.selectedPreset,
    },
    baseline: {
      spec: specChanged ? saved.spec : server.spec,
      orchestrationMode: modeChanged ? saved.orchestrationMode : server.orchestrationMode,
      autonomyLevel: autonomyChanged ? saved.autonomyLevel : server.autonomyLevel,
      researchConfig: researchConfigChanged ? saved.researchConfig : server.researchConfig,
      features: featuresChanged ? saved.features : server.features,
      milestones: milestonesChanged ? saved.milestones : server.milestones,
      selectedDesignId: designChanged ? saved.selectedDesignId : server.selectedDesignId,
      selectedPreset: presetChanged ? saved.selectedPreset : server.selectedPreset,
    },
  };
}

export function LifecycleLayout() {
  const { projectSlug } = useParams();
  const { currentProject } = useTenantProject();
  const projectLabel = currentProject?.name || projectSlug || "";
  return <LifecycleLayoutInner key={projectSlug} projectSlug={projectSlug ?? ""} projectLabel={projectLabel} />;
}

function LifecycleLayoutInner({ projectSlug, projectLabel }: { projectSlug: string; projectLabel: string }) {
  const basePath = `/p/${projectSlug}`;
  const location = useLocation();
  const navigate = useNavigate();

  const [spec, setSpec] = useState("");
  const [orchestrationMode, setOrchestrationMode] = useState<LifecycleOrchestrationMode>("workflow");
  const [autonomyLevel, setAutonomyLevel] = useState<LifecycleAutonomyLevel>("A3");
  const [researchConfig, setResearchConfig] = useState<LifecycleResearchConfig>(defaultResearchConfig);
  const [research, setResearch] = useState<MarketResearch | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [features, setFeatures] = useState<FeatureSelection[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [designVariants, setDesignVariants] = useState<DesignVariant[]>([]);
  const [selectedDesignId, setSelectedDesignId] = useState<string | null>(null);
  const [approvalStatus, setApprovalStatus] = useState<LifecycleProject["approvalStatus"]>("pending");
  const [approvalComments, setApprovalComments] = useState<ApprovalComment[]>([]);
  const [buildCode, setBuildCode] = useState<string | null>(null);
  const [buildCost, setBuildCost] = useState(0);
  const [buildIteration, setBuildIteration] = useState(0);
  const [milestoneResults, setMilestoneResults] = useState<MilestoneResult[]>([]);
  const [planEstimates, setPlanEstimates] = useState<PlanEstimate[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<PlanPreset>("standard");
  const [phaseStatuses, setPhaseStatuses] = useState<PhaseStatus[]>(defaultStatuses());
  const [deployChecks, setDeployChecks] = useState<DeployCheck[]>([]);
  const [releases, setReleases] = useState<ReleaseRecord[]>([]);
  const [feedbackItems, setFeedbackItems] = useState<FeedbackItem[]>([]);
  const [recommendations, setRecommendations] = useState<LifecycleRecommendation[]>([]);
  const [artifacts, setArtifacts] = useState<LifecycleArtifact[]>([]);
  const [decisionLog, setDecisionLog] = useState<LifecycleDecision[]>([]);
  const [skillInvocations, setSkillInvocations] = useState<LifecycleSkillInvocation[]>([]);
  const [delegations, setDelegations] = useState<LifecycleDelegation[]>([]);
  const [phaseRuns, setPhaseRuns] = useState<LifecyclePhaseRun[]>([]);
  const [nextAction, setNextAction] = useState<LifecycleNextAction | null>(null);
  const [autonomyState, setAutonomyState] = useState<LifecycleAutonomyState | null>(null);
  const [blueprints, setBlueprints] = useState<Record<LifecyclePhase, PhaseBlueprint>>(defaultBlueprints);
  const [isHydrating, setIsHydrating] = useState(true);
  const [hydrateError, setHydrateError] = useState<string | null>(null);
  const [isRefreshingProject, setIsRefreshingProject] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [phaseNavCollapsed, setPhaseNavCollapsed] = useState(false);
  const [mobilePhaseNavOpen, setMobilePhaseNavOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const hydratedRef = useRef(false);
  const applyingRemoteRef = useRef(false);
  const autoAdvanceInFlightRef = useRef(false);
  const editableDraftRef = useRef<EditableProjectPatch>(defaultEditableProjectPatch());
  const lastSavedEditableProjectRef = useRef<EditableProjectPatch>(defaultEditableProjectPatch());
  const lastSavedEditableRef = useRef(stableProjectSnapshot(defaultEditableProjectPatch()));

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1024px)");
    const onChange = (event: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(event.matches);
      if (event.matches) {
        setPhaseNavCollapsed(false);
        setConsoleOpen(false);
      }
    };
    onChange(mq);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [projectSlug]);

  useEffect(() => {
    if (!isMobile) return;
    setMobilePhaseNavOpen(false);
    setConsoleOpen(false);
  }, [isMobile, location.pathname]);

  const applyProject = useCallback((
    project: LifecycleProject,
    options: { preserveDirtyEditable?: boolean } = {},
  ) => {
    applyingRemoteRef.current = true;
    writeLifecycleProjectCache(projectSlug, project);
    const serverEditable = editableProjectFromProject(project);
    const { applied: editablePatch, baseline: editableBaseline } = options.preserveDirtyEditable
      ? mergeEditableProjectPatch(
          editableDraftRef.current,
          lastSavedEditableProjectRef.current,
          serverEditable,
        )
      : { applied: serverEditable, baseline: serverEditable };

    editableDraftRef.current = editablePatch;
    lastSavedEditableProjectRef.current = editableBaseline;
    lastSavedEditableRef.current = stableProjectSnapshot(editableBaseline);

    setSpec(editablePatch.spec);
    setOrchestrationMode(editablePatch.orchestrationMode);
    setAutonomyLevel(editablePatch.autonomyLevel);
    setResearchConfig(editablePatch.researchConfig);
    setResearch(project.research ?? null);
    setAnalysis(project.analysis ?? null);
    setFeatures(editablePatch.features);
    setMilestones(editablePatch.milestones);
    setDesignVariants(project.designVariants ?? []);
    setSelectedDesignId(editablePatch.selectedDesignId);
    setApprovalStatus(project.approvalStatus ?? "pending");
    setApprovalComments(project.approvalComments ?? []);
    setBuildCode(project.buildCode ?? null);
    setBuildCost(project.buildCost ?? 0);
    setBuildIteration(project.buildIteration ?? 0);
    setMilestoneResults(project.milestoneResults ?? []);
    setPlanEstimates(project.planEstimates ?? []);
    setSelectedPreset(editablePatch.selectedPreset);
    setPhaseStatuses(project.phaseStatuses ?? defaultStatuses());
    setDeployChecks(project.deployChecks ?? []);
    setReleases(project.releases ?? []);
    setFeedbackItems(project.feedbackItems ?? []);
    setRecommendations(project.recommendations ?? []);
    setArtifacts(project.artifacts ?? []);
    setDecisionLog(project.decisionLog ?? []);
    setSkillInvocations(project.skillInvocations ?? []);
    setDelegations(project.delegations ?? []);
    setPhaseRuns(project.phaseRuns ?? []);
    setNextAction(project.nextAction ?? null);
    setAutonomyState(project.autonomyState ?? null);
    setBlueprints(normalizeBlueprints(project.blueprints));
    if (!options.preserveDirtyEditable || stableProjectSnapshot(editablePatch) === lastSavedEditableRef.current) {
      setSaveState("idle");
    }
    setLastSavedAt(project.savedAt ?? null);
    hydratedRef.current = true;
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
    if (payload.phaseStatuses) {
      setPhaseStatuses(payload.phaseStatuses);
    }
    if (payload.nextAction !== undefined) {
      setNextAction(payload.nextAction);
    }
    if (payload.autonomyState !== undefined) {
      setAutonomyState(payload.autonomyState);
    }
    if (payload.savedAt) {
      setLastSavedAt(payload.savedAt);
    }
    queueMicrotask(() => {
      applyingRemoteRef.current = false;
    });
  }, []);

  useEffect(() => {
    editableDraftRef.current = toEditableProjectPatch({
      spec,
      orchestrationMode,
      autonomyLevel,
      researchConfig,
      features,
      milestones,
      selectedDesignId,
      selectedPreset,
    });
  }, [
    spec,
    orchestrationMode,
    autonomyLevel,
    researchConfig,
    features,
    milestones,
    selectedDesignId,
    selectedPreset,
  ]);

  useEffect(() => {
    let cancelled = false;
    if (!projectSlug) {
      setIsHydrating(false);
      return;
    }
    setHydrateError(null);
    setIsHydrating(true);
    setIsRefreshingProject(false);
    hydratedRef.current = false;
    applyingRemoteRef.current = true;

    const cachedProject = readLifecycleProjectCache(projectSlug);
    if (cachedProject) {
      applyProject(cachedProject);
      setIsHydrating(false);
      setIsRefreshingProject(true);
    }

    lifecycleApi.getProject(projectSlug)
      .then((project) => {
        if (cancelled) return;
        applyProject(project, { preserveDirtyEditable: Boolean(cachedProject) });
        setIsHydrating(false);
        setIsRefreshingProject(false);
      })
      .catch(() => {
        if (cancelled) return;
        hydratedRef.current = Boolean(cachedProject);
        applyingRemoteRef.current = false;
        setIsHydrating(false);
        setIsRefreshingProject(false);
        if (!cachedProject) {
          setHydrateError("Lifecycle state を読み込めませんでした。もう一度読み込むと復旧できる場合があります。");
        }
      });

    return () => {
      cancelled = true;
      clearTimeout(saveTimer.current);
    };
  }, [applyProject, projectSlug]);

  useEffect(() => {
    if (!projectSlug || !hydratedRef.current || applyingRemoteRef.current) return;
    const editablePatch = editableDraftRef.current;
    const snapshot = stableProjectSnapshot(editablePatch);
    if (snapshot === lastSavedEditableRef.current) {
      return;
    }
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      setSaveState("saving");
      void lifecycleApi.saveProject(
        projectSlug,
        editableProjectPayload(editablePatch),
        { autoRun: false },
      )
        .then((response) => {
          const savedEditable = editableProjectFromProject(response.project);
          lastSavedEditableProjectRef.current = savedEditable;
          lastSavedEditableRef.current = stableProjectSnapshot(savedEditable);
          applyRuntimeProject(response.project);
          setSaveState("saved");
          setLastSavedAt(response.project.savedAt ?? new Date().toISOString());
        })
        .catch(() => {
          setSaveState("error");
        });
    }, 500);
    return () => clearTimeout(saveTimer.current);
  }, [
    applyRuntimeProject,
    projectSlug,
    spec,
    orchestrationMode,
    autonomyLevel,
    researchConfig,
    features,
    milestones,
    selectedDesignId,
    selectedPreset,
  ]);

  useEffect(() => {
    if (saveState !== "saved") return;
    const timer = setTimeout(() => setSaveState("idle"), 2400);
    return () => clearTimeout(timer);
  }, [saveState]);

  const advancePhase = (phase: LifecyclePhase) => {
    setPhaseStatuses((prev) => {
      const next = [...prev];
      const index = PHASE_ORDER.indexOf(phase);
      const entry = next.find((item) => item.phase === phase);
      if (entry) entry.status = "in_progress";
      if (index + 1 < PHASE_ORDER.length) {
        const nextEntry = next.find((item) => item.phase === PHASE_ORDER[index + 1]);
        if (nextEntry && nextEntry.status === "locked") nextEntry.status = "available";
      }
      return next;
    });
  };

  const completePhase = (phase: LifecyclePhase) => {
    setPhaseStatuses((prev) => {
      const next = [...prev];
      const index = PHASE_ORDER.indexOf(phase);
      const entry = next.find((item) => item.phase === phase);
      if (entry) {
        entry.status = "completed";
        entry.completedAt = new Date().toISOString();
      }
      if (index + 1 < PHASE_ORDER.length) {
        const nextEntry = next.find((item) => item.phase === PHASE_ORDER[index + 1]);
        if (nextEntry && nextEntry.status === "locked") nextEntry.status = "available";
      }
      return next;
    });
  };

  const currentPhase = PHASE_ORDER.find((phase) =>
    location.pathname.endsWith(`/lifecycle/${phase}`),
  ) ?? null;
  const shouldStreamRuntime = Boolean(projectSlug && currentPhase);
  const runtimeStream = useLifecycleRuntimeStream(
    projectSlug,
    currentPhase,
    shouldStreamRuntime,
  );

  // Phase guard: redirect locked phases to the latest accessible phase
  useEffect(() => {
    if (isHydrating || !currentPhase) return;
    const currentStatus = phaseStatuses.find((s) => s.phase === currentPhase);
    if (!currentStatus || currentStatus.status === "locked") {
      let fallbackPhase: LifecyclePhase | null = null;
      for (let i = PHASE_ORDER.length - 1; i >= 0; i--) {
        const status = phaseStatuses.find((s) => s.phase === PHASE_ORDER[i]);
        if (status && (status.status === "in_progress" || status.status === "completed" || status.status === "available")) {
          fallbackPhase = PHASE_ORDER[i];
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
        // Ignore transient terminal refresh failures; the next manual refresh recovers.
      });
  }, [applyProject, projectSlug, runtimeStream.terminalEvent]);

  const prevNextActionRef = useRef(nextAction);
  useEffect(() => {
    if (isHydrating || !projectSlug || orchestrationMode !== "autonomous" || !nextAction?.phase) return;
    if (nextAction.type === "collect_input") return;

    // Keep explicit phase URLs stable. Autonomous progression should refresh
    // the shared lifecycle state, but it should not override manual inspection
    // of a completed or in-progress phase screen.
    if (currentPhase !== null) {
      prevNextActionRef.current = nextAction;
      return;
    }

    // Only auto-redirect when nextAction actually changes, not on every route change.
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

  const ctx: LifecycleState = {
    spec,
    setSpec,
    orchestrationMode,
    setOrchestrationMode,
    autonomyLevel,
    setAutonomyLevel,
    researchConfig,
    setResearchConfig,
    research,
    setResearch,
    analysis,
    setAnalysis,
    features,
    setFeatures,
    milestones,
    setMilestones,
    designVariants,
    setDesignVariants,
    selectedDesignId,
    setSelectedDesignId,
    approvalStatus,
    setApprovalStatus,
    approvalComments,
    setApprovalComments,
    buildCode,
    setBuildCode,
    buildCost,
    setBuildCost,
    buildIteration,
    setBuildIteration,
    milestoneResults,
    setMilestoneResults,
    planEstimates,
    setPlanEstimates,
    selectedPreset,
    setSelectedPreset,
    phaseStatuses,
    setPhaseStatuses,
    deployChecks,
    setDeployChecks,
    releases,
    setReleases,
    feedbackItems,
    setFeedbackItems,
    recommendations,
    setRecommendations,
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
    applyProject,
    advancePhase,
    completePhase,
  };

  return (
    <LifecycleContext.Provider value={ctx}>
      <div className="flex h-full">
        {!isMobile && (
          <PhaseNav
            basePath={basePath}
            phaseStatuses={phaseStatuses}
            collapsed={phaseNavCollapsed}
            className="shrink-0"
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <LifecycleWorkspaceHeader
            currentPhase={currentPhase ?? "research"}
            projectLabel={projectLabel}
            phaseStatuses={phaseStatuses}
            phaseNavCollapsed={phaseNavCollapsed}
            isMobile={isMobile}
            consoleOpen={consoleOpen}
            saveState={saveState}
            runtimeConnectionState={runtimeStream.connectionState}
            lastSavedAt={lastSavedAt}
            onTogglePhaseNav={() => {
              if (isMobile) setMobilePhaseNavOpen(true);
              else setPhaseNavCollapsed((value) => !value);
            }}
            onToggleConsole={() => setConsoleOpen((value) => !value)}
          />
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <div className="min-w-0 flex-1 overflow-hidden">
              <div className="h-full overflow-y-auto">
                {isHydrating && !hydratedRef.current ? (
                  <LifecycleContentSkeleton />
                ) : hydrateError && !hydratedRef.current ? (
                  <div className="px-6 py-10">
                    <div className="rounded-3xl border border-amber-500/30 bg-amber-500/10 p-6 text-sm text-amber-100">
                      {hydrateError}
                    </div>
                  </div>
                ) : (
                  <>
                    {isRefreshingProject && (
                      <div className="sticky top-0 z-10 border-b border-border/60 bg-background/85 px-6 py-3 backdrop-blur">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          最新の lifecycle state を同期中...
                        </div>
                      </div>
                    )}
                    <Outlet />
                  </>
                )}
              </div>
            </div>
            {!isMobile && consoleOpen && (
              <LifecycleOperatorConsole
                currentPhase={currentPhase}
                artifacts={artifacts}
                decisions={decisionLog}
                skillInvocations={skillInvocations}
                delegations={delegations}
                phaseRuns={phaseRuns}
                research={research}
                liveTelemetry={runtimeStream.liveTelemetry}
                phaseSummary={runtimeStream.runtime?.phaseSummary ?? null}
                activePhaseSummary={runtimeStream.runtime?.activePhaseSummary ?? null}
                className="hidden w-[22rem] shrink-0 xl:flex"
              />
            )}
          </div>
        </div>
      </div>

      {isMobile && mobilePhaseNavOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60"
            onClick={() => setMobilePhaseNavOpen(false)}
          />
          <div className="fixed inset-y-0 left-0 z-50">
            <PhaseNav
              basePath={basePath}
              phaseStatuses={phaseStatuses}
              className="w-72 max-w-[85vw] shadow-2xl"
              onItemClick={() => setMobilePhaseNavOpen(false)}
            />
          </div>
        </>
      )}

      {isMobile && consoleOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60"
            onClick={() => setConsoleOpen(false)}
          />
          <div className="fixed inset-y-0 right-0 z-50 w-[22rem] max-w-[92vw]">
            <LifecycleOperatorConsole
              currentPhase={currentPhase}
              artifacts={artifacts}
              decisions={decisionLog}
              skillInvocations={skillInvocations}
              delegations={delegations}
              phaseRuns={phaseRuns}
              research={research}
              liveTelemetry={runtimeStream.liveTelemetry}
              phaseSummary={runtimeStream.runtime?.phaseSummary ?? null}
              activePhaseSummary={runtimeStream.runtime?.activePhaseSummary ?? null}
              className={cn("h-full w-full shadow-2xl")}
            />
          </div>
        </>
      )}
    </LifecycleContext.Provider>
  );
}
