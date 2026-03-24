import { lifecycleApi } from "@/api/lifecycle";
import { completePhaseStatuses } from "@/lifecycle/phaseStatus";
import type {
  LifecyclePhase,
  LifecycleProject,
  PhaseStatus,
} from "@/types/lifecycle";

export function persistCompletedPhase(
  projectSlug: string,
  phase: LifecyclePhase,
  phaseStatuses: PhaseStatus[],
  patch: Partial<LifecycleProject> = {},
) {
  return lifecycleApi.saveProject(
    projectSlug,
    {
      ...patch,
      phaseStatuses: completePhaseStatuses(phaseStatuses, phase),
    },
    { autoRun: false },
  );
}
