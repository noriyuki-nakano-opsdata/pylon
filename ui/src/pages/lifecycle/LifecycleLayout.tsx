import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { lifecycleApi } from "@/api/lifecycle";
import { LifecycleOperatorConsole } from "@/components/lifecycle/LifecycleOperatorConsole";
import { PhaseNav } from "@/components/lifecycle/PhaseNav";
import { LifecycleWorkspaceHeader } from "@/components/lifecycle/LifecycleWorkspaceHeader";
import { LifecycleContext } from "./LifecycleContext";
import type {
  ApprovalComment,
  AnalysisResult,
  DeployCheck,
  DesignVariant,
  FeatureSelection,
  FeedbackItem,
  LifecycleArtifact,
  LifecycleDecision,
  LifecycleDelegation,
  LifecyclePhase,
  LifecyclePhaseRun,
  LifecycleProject,
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

const defaultStatuses = (): PhaseStatus[] => PHASE_ORDER.map((phase, index) => ({
  phase,
  status: index === 0 ? "available" : "locked",
  version: 1,
}));

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

function toProjectPatch(state: {
  spec: string;
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
  phaseRuns: LifecyclePhaseRun[];
}): Partial<LifecycleProject> {
  return {
    spec: state.spec,
    research: state.research ?? undefined,
    analysis: state.analysis ?? undefined,
    features: state.features,
    milestones: state.milestones,
    designVariants: state.designVariants,
    selectedDesignId: state.selectedDesignId ?? undefined,
    approvalStatus: state.approvalStatus,
    approvalComments: state.approvalComments,
    buildCode: state.buildCode ?? undefined,
    buildCost: state.buildCost,
    buildIteration: state.buildIteration,
    milestoneResults: state.milestoneResults,
    planEstimates: state.planEstimates,
    selectedPreset: state.selectedPreset,
    phaseStatuses: state.phaseStatuses,
    deployChecks: state.deployChecks,
    releases: state.releases,
    feedbackItems: state.feedbackItems,
    recommendations: state.recommendations,
    artifacts: state.artifacts,
    decisionLog: state.decisionLog,
    skillInvocations: state.skillInvocations,
    delegations: state.delegations,
    phaseRuns: state.phaseRuns,
  };
}

export function LifecycleLayout() {
  const { projectSlug } = useParams();
  return <LifecycleLayoutInner key={projectSlug} projectSlug={projectSlug ?? ""} />;
}

function LifecycleLayoutInner({ projectSlug }: { projectSlug: string }) {
  const basePath = `/p/${projectSlug}`;
  const location = useLocation();

  const [spec, setSpec] = useState("");
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
  const [blueprints, setBlueprints] = useState<Record<LifecyclePhase, PhaseBlueprint>>(defaultBlueprints);
  const [isHydrating, setIsHydrating] = useState(true);
  const [isMobile, setIsMobile] = useState(false);
  const [phaseNavCollapsed, setPhaseNavCollapsed] = useState(false);
  const [mobilePhaseNavOpen, setMobilePhaseNavOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const hydratedRef = useRef(false);
  const applyingRemoteRef = useRef(false);

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
  }, []);

  useEffect(() => {
    if (!isMobile) return;
    setMobilePhaseNavOpen(false);
    setConsoleOpen(false);
  }, [isMobile, location.pathname]);

  const applyProject = (project: LifecycleProject) => {
    applyingRemoteRef.current = true;
    setSpec(project.spec ?? "");
    setResearch(project.research ?? null);
    setAnalysis(project.analysis ?? null);
    setFeatures(project.features ?? []);
    setMilestones(project.milestones ?? []);
    setDesignVariants(project.designVariants ?? []);
    setSelectedDesignId(project.selectedDesignId ?? null);
    setApprovalStatus(project.approvalStatus ?? "pending");
    setApprovalComments(project.approvalComments ?? []);
    setBuildCode(project.buildCode ?? null);
    setBuildCost(project.buildCost ?? 0);
    setBuildIteration(project.buildIteration ?? 0);
    setMilestoneResults(project.milestoneResults ?? []);
    setPlanEstimates(project.planEstimates ?? []);
    setSelectedPreset(project.selectedPreset ?? "standard");
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
    setBlueprints(normalizeBlueprints(project.blueprints));
    setSaveState("idle");
    hydratedRef.current = true;
    queueMicrotask(() => {
      applyingRemoteRef.current = false;
    });
  };

  useEffect(() => {
    let cancelled = false;
    if (!projectSlug) {
      setIsHydrating(false);
      return;
    }
    setIsHydrating(true);
    hydratedRef.current = false;
    applyingRemoteRef.current = true;

    lifecycleApi.getProject(projectSlug)
      .then((project) => {
        if (cancelled) return;
        applyProject(project);
        setIsHydrating(false);
      })
      .catch(() => {
        if (cancelled) return;
        hydratedRef.current = true;
        applyingRemoteRef.current = false;
        setIsHydrating(false);
      });

    return () => {
      cancelled = true;
      clearTimeout(saveTimer.current);
    };
  }, [projectSlug]);

  useEffect(() => {
    if (!projectSlug || !hydratedRef.current || applyingRemoteRef.current) return;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      setSaveState("saving");
      void lifecycleApi.saveProject(
        projectSlug,
        toProjectPatch({
          spec,
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
        }),
      )
        .then(() => {
          setSaveState("saved");
          setLastSavedAt(new Date().toISOString());
        })
        .catch(() => {
          setSaveState("error");
        });
    }, 500);
    return () => clearTimeout(saveTimer.current);
  }, [
    projectSlug,
    spec,
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

  const ctx: LifecycleState = {
    spec,
    setSpec,
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
    blueprints,
    isHydrating,
    applyProject,
    advancePhase,
    completePhase,
  };

  const currentPhase = PHASE_ORDER.find((phase) =>
    location.pathname.endsWith(`/lifecycle/${phase}`),
  ) ?? null;

  if (isHydrating) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Lifecycle state を読み込み中...
        </div>
      </div>
    );
  }

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
            projectLabel={projectSlug}
            phaseStatuses={phaseStatuses}
            phaseNavCollapsed={phaseNavCollapsed}
            isMobile={isMobile}
            consoleOpen={consoleOpen}
            saveState={saveState}
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
                <Outlet />
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
              className={cn("h-full w-full shadow-2xl")}
            />
          </div>
        </>
      )}
    </LifecycleContext.Provider>
  );
}
