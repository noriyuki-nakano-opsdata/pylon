import { describe, expect, it } from "vitest";
import {
  createWorkspaceProjectState,
  defaultResearchConfig,
  defaultStatuses,
  lifecycleWorkspaceReducer,
  selectEditableProjectPatch,
} from "@/lifecycle/store";
import type { LifecycleProject } from "@/types/lifecycle";

function makeProject(overrides: Partial<LifecycleProject> = {}): LifecycleProject {
  const timestamp = "2026-03-13T00:00:00.000Z";
  return {
    id: "lp_1",
    projectId: "manu",
    name: "manu",
    spec: "Initial spec",
    orchestrationMode: "workflow",
    autonomyLevel: "A3",
    researchConfig: defaultResearchConfig(),
    features: [],
    milestones: [],
    designVariants: [],
    approvalStatus: "pending",
    approvalComments: [],
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
    createdAt: timestamp,
    updatedAt: timestamp,
    savedAt: timestamp,
    ...overrides,
  };
}

describe("lifecycleWorkspaceReducer", () => {
  it("hydrates from cache and marks the workspace as refreshing", () => {
    const project = makeProject();
    const state = lifecycleWorkspaceReducer(
      createWorkspaceProjectState(),
      { type: "hydrate_from_cache", project },
    );

    expect(state.spec).toBe("Initial spec");
    expect(state.hydrationState).toBe("ready");
    expect(state.isRefreshingProject).toBe(true);
    expect(state.saveState).toBe("idle");
  });

  it("preserves dirty editable fields during server refresh", () => {
    const hydrated = lifecycleWorkspaceReducer(
      createWorkspaceProjectState(),
      { type: "apply_project", project: makeProject() },
    );
    const locallyEdited = lifecycleWorkspaceReducer(
      hydrated,
      { type: "edit_spec", value: "Locally edited spec" },
    );
    const refreshed = lifecycleWorkspaceReducer(
      locallyEdited,
      {
        type: "apply_project",
        project: makeProject({
          spec: "Server spec",
          updatedAt: "2026-03-13T00:05:00.000Z",
          savedAt: "2026-03-13T00:05:00.000Z",
        }),
        preserveDirtyEditable: true,
      },
    );

    expect(refreshed.spec).toBe("Locally edited spec");
    expect(refreshed.editableBaseline.spec).toBe("Initial spec");
    expect(selectEditableProjectPatch(refreshed).spec).toBe("Locally edited spec");
  });

  it("tracks save lifecycle in reducer state", () => {
    const project = makeProject();
    const hydrated = lifecycleWorkspaceReducer(
      createWorkspaceProjectState(),
      { type: "apply_project", project },
    );
    const saving = lifecycleWorkspaceReducer(hydrated, { type: "save_started" });
    const saved = lifecycleWorkspaceReducer(saving, {
      type: "mark_saved",
      editableBaseline: {
        ...selectEditableProjectPatch(saving),
        spec: "Saved spec",
      },
      savedAt: "2026-03-13T00:10:00.000Z",
    });
    const reset = lifecycleWorkspaceReducer(saved, { type: "save_reset" });

    expect(saving.saveState).toBe("saving");
    expect(saved.saveState).toBe("saved");
    expect(saved.lastSavedAt).toBe("2026-03-13T00:10:00.000Z");
    expect(reset.saveState).toBe("idle");
  });

  it("stores hydrate error only when no cached project is available", () => {
    const errored = lifecycleWorkspaceReducer(
      createWorkspaceProjectState(),
      {
        type: "hydrate_failed",
        error: "failed to load",
        hasCachedProject: false,
      },
    );
    const cachedRecovery = lifecycleWorkspaceReducer(
      createWorkspaceProjectState(),
      {
        type: "hydrate_failed",
        error: "failed to load",
        hasCachedProject: true,
      },
    );

    expect(errored.hydrationState).toBe("error");
    expect(errored.hydrateError).toBe("failed to load");
    expect(cachedRecovery.hydrationState).toBe("ready");
    expect(cachedRecovery.hydrateError).toBeNull();
  });
});
