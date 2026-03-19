import type {
  LifecycleNextAction,
  LifecyclePhase,
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

const RUN_ACTIVITY_PHASE_STATUSES: PhaseStatus["status"][] = [
  "in_progress",
];

function hasConditionalPlanningHandoff(nextAction: LifecycleNextAction | null): boolean {
  const operatorGuidance = nextAction?.payload?.operatorGuidance;
  return !!(
    nextAction?.phase === "planning"
    && operatorGuidance
    && typeof operatorGuidance === "object"
    && (operatorGuidance as Record<string, unknown>).conditionalHandoffAllowed === true
  );
}

export function completePhaseStatuses(
  phaseStatuses: PhaseStatus[],
  phase: LifecyclePhase,
  now = new Date().toISOString(),
): PhaseStatus[] {
  const normalized = phaseStatuses.map((status) => ({ ...status }));
  const phaseIndex = PHASE_ORDER.indexOf(phase);
  if (phaseIndex === -1) return normalized;

  const current = normalized.find((entry) => entry.phase === phase);
  if (current) {
    current.status = "completed";
    current.completedAt = current.completedAt ?? now;
  }

  const next = normalized.find((entry) => entry.phase === PHASE_ORDER[phaseIndex + 1]);
  if (next && next.status === "locked") {
    next.status = "available";
  }

  return normalized;
}

export function deriveVisiblePhaseStatuses(
  phaseStatuses: PhaseStatus[],
  nextAction: LifecycleNextAction | null,
  now = new Date().toISOString(),
): PhaseStatus[] {
  const normalized = phaseStatuses.map((status) => ({ ...status }));
  if (!nextAction?.phase || nextAction.type === "done") return normalized;

  const targetIndex = PHASE_ORDER.indexOf(nextAction.phase);
  if (targetIndex === -1) return normalized;

  const unlockForReview =
    nextAction.type === "review_phase"
    || hasConditionalPlanningHandoff(nextAction);
  if (!unlockForReview) return normalized;

  for (let index = 0; index < targetIndex; index += 1) {
    const current = normalized.find((entry) => entry.phase === PHASE_ORDER[index]);
    if (!current || current.status === "completed") continue;
    current.status = "completed";
    current.completedAt = current.completedAt ?? now;
  }

  const target = normalized.find((entry) => entry.phase === nextAction.phase);
  if (target && target.status === "locked") {
    target.status = "available";
  }

  return normalized;
}

export function hasRestorablePhaseRun(
  phaseStatuses: PhaseStatus[],
  phaseRuns: Array<{ phase: LifecyclePhase }>,
  runtimeActivePhase: LifecyclePhase | null | undefined,
  phase: LifecyclePhase,
): boolean {
  if (phaseRuns.some((run) => run.phase === phase)) {
    return true;
  }
  if (runtimeActivePhase === phase) {
    return true;
  }
  const phaseStatus = phaseStatuses.find((entry) => entry.phase === phase)?.status;
  return phaseStatus != null && RUN_ACTIVITY_PHASE_STATUSES.includes(phaseStatus);
}

export function findLatestReachablePhase(
  phaseStatuses: PhaseStatus[],
  targetPhase?: LifecyclePhase | null,
): LifecyclePhase | null {
  const targetIndex = targetPhase ? PHASE_ORDER.indexOf(targetPhase) : PHASE_ORDER.length - 1;
  const endIndex = targetIndex >= 0 ? Math.min(targetIndex - 1, PHASE_ORDER.length - 1) : PHASE_ORDER.length - 1;

  for (let index = endIndex; index >= 0; index -= 1) {
    const phase = PHASE_ORDER[index];
    const status = phaseStatuses.find((entry) => entry.phase === phase);
    if (!status) continue;
    if (status.status === "available" || status.status === "in_progress" || status.status === "review" || status.status === "completed") {
      return phase;
    }
  }

  const firstUnlocked = PHASE_ORDER.find((phase) => {
    const status = phaseStatuses.find((entry) => entry.phase === phase);
    return status && status.status !== "locked";
  });
  return firstUnlocked ?? null;
}
