import { useState, createContext, useContext, useEffect, useRef } from "react";
import { Outlet, useParams } from "react-router-dom";
import { PhaseNav } from "@/components/lifecycle/PhaseNav";
import type {
  LifecyclePhase, PhaseStatus, AnalysisResult, FeatureSelection,
  Milestone, DesignVariant, MarketResearch, MilestoneResult,
  PlanEstimate, PlanPreset,
} from "@/types/lifecycle";

/* ── Context for sharing state across phases ── */
interface LifecycleState {
  spec: string;
  setSpec: (s: string) => void;
  research: MarketResearch | null;
  setResearch: (r: MarketResearch | null) => void;
  analysis: AnalysisResult | null;
  setAnalysis: (a: AnalysisResult | null) => void;
  features: FeatureSelection[];
  setFeatures: (f: FeatureSelection[]) => void;
  milestones: Milestone[];
  setMilestones: (m: Milestone[]) => void;
  designVariants: DesignVariant[];
  setDesignVariants: (v: DesignVariant[]) => void;
  selectedDesignId: string | null;
  setSelectedDesignId: (id: string | null) => void;
  approvalStatus: "pending" | "approved" | "rejected" | "revision_requested";
  setApprovalStatus: (s: "pending" | "approved" | "rejected" | "revision_requested") => void;
  buildCode: string | null;
  setBuildCode: (c: string | null) => void;
  buildCost: number;
  setBuildCost: (c: number) => void;
  buildIteration: number;
  setBuildIteration: (i: number) => void;
  milestoneResults: MilestoneResult[];
  setMilestoneResults: (r: MilestoneResult[]) => void;
  planEstimates: PlanEstimate[];
  setPlanEstimates: (e: PlanEstimate[]) => void;
  selectedPreset: PlanPreset;
  setSelectedPreset: (p: PlanPreset) => void;
  phaseStatuses: PhaseStatus[];
  setPhaseStatuses: (s: PhaseStatus[]) => void;
  advancePhase: (phase: LifecyclePhase) => void;
  completePhase: (phase: LifecyclePhase) => void;
}

const LifecycleContext = createContext<LifecycleState | null>(null);

export function useLifecycle() {
  const ctx = useContext(LifecycleContext);
  if (!ctx) throw new Error("useLifecycle must be used within LifecycleLayout");
  return ctx;
}

const PHASE_ORDER: LifecyclePhase[] = [
  "research", "planning", "design", "approval", "development", "deploy", "iterate",
];

const defaultStatuses = (): PhaseStatus[] => PHASE_ORDER.map((phase, i) => ({
  phase,
  status: i === 0 ? "available" : "locked",
  version: 1,
}));

/* ── localStorage persistence per project ── */
interface PersistedState {
  spec: string;
  research: MarketResearch | null;
  analysis: AnalysisResult | null;
  features: FeatureSelection[];
  milestones: Milestone[];
  designVariants: DesignVariant[];
  selectedDesignId: string | null;
  approvalStatus: "pending" | "approved" | "rejected" | "revision_requested";
  buildCode: string | null;
  buildCost: number;
  buildIteration: number;
  milestoneResults: MilestoneResult[];
  planEstimates: PlanEstimate[];
  selectedPreset: PlanPreset;
  phaseStatuses: PhaseStatus[];
  savedAt: string;
}

function storageKey(projectSlug: string) {
  return `pylon:lifecycle:${projectSlug}`;
}

function loadState(projectSlug: string): Partial<PersistedState> | null {
  try {
    const raw = localStorage.getItem(storageKey(projectSlug));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveState(projectSlug: string, state: PersistedState) {
  try {
    localStorage.setItem(storageKey(projectSlug), JSON.stringify(state));
  } catch {
    // storage full — silently ignore
  }
}

export type { PersistedState };

/** List all projects that have saved lifecycle data */
export function listSavedProjects(): { slug: string; data: PersistedState }[] {
  const results: { slug: string; data: PersistedState }[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key?.startsWith("pylon:lifecycle:")) continue;
    try {
      const data = JSON.parse(localStorage.getItem(key)!) as PersistedState;
      results.push({ slug: key.replace("pylon:lifecycle:", ""), data });
    } catch { /* skip corrupted */ }
  }
  return results.sort((a, b) => b.data.savedAt.localeCompare(a.data.savedAt));
}

/** Load full lifecycle data for a specific project */
export { loadState as loadLifecycleState };

/** Wrapper that remounts inner layout when projectSlug changes */
export function LifecycleLayout() {
  const { projectSlug } = useParams();
  return <LifecycleLayoutInner key={projectSlug} projectSlug={projectSlug ?? ""} />;
}

function LifecycleLayoutInner({ projectSlug }: { projectSlug: string }) {
  const basePath = `/p/${projectSlug}`;
  const saved = projectSlug ? loadState(projectSlug) : null;

  const [spec, setSpec] = useState(saved?.spec ?? "");
  const [research, setResearch] = useState<MarketResearch | null>(saved?.research ?? null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(saved?.analysis ?? null);
  const [features, setFeatures] = useState<FeatureSelection[]>(saved?.features ?? []);
  const [milestones, setMilestones] = useState<Milestone[]>(saved?.milestones ?? []);
  const [designVariants, setDesignVariants] = useState<DesignVariant[]>(saved?.designVariants ?? []);
  const [selectedDesignId, setSelectedDesignId] = useState<string | null>(saved?.selectedDesignId ?? null);
  const [approvalStatus, setApprovalStatus] = useState<"pending" | "approved" | "rejected" | "revision_requested">(saved?.approvalStatus ?? "pending");
  const [buildCode, setBuildCode] = useState<string | null>(saved?.buildCode ?? null);
  const [buildCost, setBuildCost] = useState(saved?.buildCost ?? 0);
  const [buildIteration, setBuildIteration] = useState(saved?.buildIteration ?? 0);
  const [milestoneResults, setMilestoneResults] = useState<MilestoneResult[]>(saved?.milestoneResults ?? []);
  const [planEstimates, setPlanEstimates] = useState<PlanEstimate[]>(saved?.planEstimates ?? []);
  const [selectedPreset, setSelectedPreset] = useState<PlanPreset>(saved?.selectedPreset ?? "standard");
  const [phaseStatuses, setPhaseStatuses] = useState<PhaseStatus[]>(saved?.phaseStatuses ?? defaultStatuses());

  // Auto-save to localStorage on state changes (debounced)
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const isInitialMount = useRef(true);
  useEffect(() => {
    if (!projectSlug) return;
    // Skip saving on initial mount (state came from localStorage already)
    if (isInitialMount.current) { isInitialMount.current = false; return; }
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveState(projectSlug, {
        spec, research, analysis, features, milestones,
        designVariants, selectedDesignId, approvalStatus,
        buildCode, buildCost, buildIteration, milestoneResults,
        planEstimates, selectedPreset,
        phaseStatuses, savedAt: new Date().toISOString(),
      });
    }, 500);
    return () => clearTimeout(saveTimer.current);
  }, [
    projectSlug, spec, research, analysis, features, milestones,
    designVariants, selectedDesignId, approvalStatus,
    buildCode, buildCost, buildIteration, milestoneResults,
    planEstimates, selectedPreset, phaseStatuses,
  ]);

  const advancePhase = (phase: LifecyclePhase) => {
    setPhaseStatuses((prev) => {
      const next = [...prev];
      const idx = PHASE_ORDER.indexOf(phase);
      const ps = next.find((s) => s.phase === phase);
      if (ps) ps.status = "in_progress";
      // unlock next
      if (idx + 1 < PHASE_ORDER.length) {
        const nextPs = next.find((s) => s.phase === PHASE_ORDER[idx + 1]);
        if (nextPs && nextPs.status === "locked") nextPs.status = "available";
      }
      return next;
    });
  };

  const completePhase = (phase: LifecyclePhase) => {
    setPhaseStatuses((prev) => {
      const next = [...prev];
      const idx = PHASE_ORDER.indexOf(phase);
      const ps = next.find((s) => s.phase === phase);
      if (ps) {
        ps.status = "completed";
        ps.completedAt = new Date().toISOString();
      }
      // unlock next
      if (idx + 1 < PHASE_ORDER.length) {
        const nextPs = next.find((s) => s.phase === PHASE_ORDER[idx + 1]);
        if (nextPs && nextPs.status === "locked") nextPs.status = "available";
      }
      return next;
    });
  };

  const ctx: LifecycleState = {
    spec, setSpec, research, setResearch, analysis, setAnalysis,
    features, setFeatures, milestones, setMilestones,
    designVariants, setDesignVariants, selectedDesignId, setSelectedDesignId,
    approvalStatus, setApprovalStatus,
    buildCode, setBuildCode, buildCost, setBuildCost,
    buildIteration, setBuildIteration, milestoneResults, setMilestoneResults,
    planEstimates, setPlanEstimates, selectedPreset, setSelectedPreset,
    phaseStatuses, setPhaseStatuses, advancePhase, completePhase,
  };

  return (
    <LifecycleContext.Provider value={ctx}>
      <div className="flex h-full">
        <PhaseNav basePath={basePath} phaseStatuses={phaseStatuses} />
        <div className="flex-1 overflow-hidden">
          <Outlet />
        </div>
      </div>
    </LifecycleContext.Provider>
  );
}
