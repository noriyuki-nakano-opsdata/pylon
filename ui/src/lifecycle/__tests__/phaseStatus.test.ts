import { describe, expect, it } from "vitest";
import {
  completePhaseStatuses,
  deriveVisiblePhaseStatuses,
  findLatestReachablePhase,
  hasRestorablePhaseRun,
} from "@/lifecycle/phaseStatus";
import { defaultStatuses } from "@/lifecycle/store";
import type { LifecycleNextAction } from "@/types/lifecycle";

describe("deriveVisiblePhaseStatuses", () => {
  it("unlocks planning review when the next action hands off from research", () => {
    const statuses = deriveVisiblePhaseStatuses(
      defaultStatuses(),
      {
        type: "review_phase",
        phase: "planning",
        title: "条件付きで企画へ進めます",
        reason: "handoff",
        canAutorun: false,
        payload: {
          operatorGuidance: {
            conditionalHandoffAllowed: true,
          },
        },
      } satisfies LifecycleNextAction,
      "2026-03-14T00:00:00.000Z",
    );

    expect(statuses.find((entry) => entry.phase === "research")?.status).toBe("completed");
    expect(statuses.find((entry) => entry.phase === "research")?.completedAt).toBe("2026-03-14T00:00:00.000Z");
    expect(statuses.find((entry) => entry.phase === "planning")?.status).toBe("available");
  });

  it("keeps later phases locked when no review handoff exists", () => {
    const statuses = deriveVisiblePhaseStatuses(
      defaultStatuses(),
      {
        type: "run_phase",
        phase: "research",
        title: "調査を継続します",
        reason: "continue research",
        canAutorun: true,
        payload: {},
      } satisfies LifecycleNextAction,
    );

    expect(statuses.find((entry) => entry.phase === "research")?.status).toBe("available");
    expect(statuses.find((entry) => entry.phase === "planning")?.status).toBe("locked");
  });

  it("finds the nearest reachable phase before a locked destination", () => {
    const statuses = defaultStatuses().map((entry, index) => ({
      ...entry,
      status:
        index === 0 ? "completed"
        : index === 1 ? "available"
        : "locked",
    })) as ReturnType<typeof defaultStatuses>;

    expect(findLatestReachablePhase(statuses, "development")).toBe("planning");
  });

  it("marks a phase completed and unlocks the next phase for persistence", () => {
    const statuses = completePhaseStatuses(
      defaultStatuses(),
      "planning",
      "2026-03-15T00:00:00.000Z",
    );

    expect(statuses.find((entry) => entry.phase === "planning")).toMatchObject({
      status: "completed",
      completedAt: "2026-03-15T00:00:00.000Z",
    });
    expect(statuses.find((entry) => entry.phase === "design")?.status).toBe("available");
  });

  it("treats an in-progress phase status as enough to restore a run", () => {
    const statuses = defaultStatuses().map((entry) => (
      entry.phase === "design"
        ? { ...entry, status: "in_progress" as const }
        : entry
    ));

    expect(hasRestorablePhaseRun(statuses, [], null, "design")).toBe(true);
  });

  it("does not restore a completed phase without a synced run record", () => {
    const statuses = defaultStatuses().map((entry) => (
      entry.phase === "design"
        ? { ...entry, status: "completed" as const, completedAt: "2026-03-15T00:00:00.000Z" }
        : entry
    ));

    expect(hasRestorablePhaseRun(statuses, [], null, "design")).toBe(false);
  });

  it("restores a completed phase when a synced phase run exists", () => {
    const statuses = defaultStatuses().map((entry) => (
      entry.phase === "design"
        ? { ...entry, status: "completed" as const, completedAt: "2026-03-15T00:00:00.000Z" }
        : entry
    ));

    expect(hasRestorablePhaseRun(statuses, [{ phase: "design" }], null, "design")).toBe(true);
  });
});
