import { describe, expect, it } from "vitest";
import { polishConsoleCopy, presentLifecycleGateReason } from "@/lifecycle/presentation";

describe("presentation copy polish", () => {
  it("localizes downstream lifecycle gate reasons", () => {
    expect(
      polishConsoleCopy("Development is approval-gated and must not auto-run until approval is granted."),
    ).toContain("開発は承認後にのみ開始されます");

    expect(
      polishConsoleCopy("The release exists, but no iteration feedback has been captured yet."),
    ).toContain("改善に回すフィードバック");
  });

  it("rewrites approval gate reasons for downstream locked phases", () => {
    expect(
      presentLifecycleGateReason({
        currentPhase: "deploy",
        recommendedPhase: "approval",
        reason: "Development is approval-gated and must not auto-run until approval is granted.",
      }),
    ).toContain("デプロイ は承認の判断が完了するまで開けません");

    expect(
      presentLifecycleGateReason({
        currentPhase: "iterate",
        recommendedPhase: "approval",
        reason: "Development is approval-gated and must not auto-run until approval is granted.",
      }),
    ).toContain("改善 は承認の判断が完了するまで開けません");
  });

  it("rewrites downstream run-phase reasons for later locked phases", () => {
    expect(
      presentLifecycleGateReason({
        currentPhase: "deploy",
        recommendedPhase: "development",
        reason: "Approved planning and design context is ready for implementation. workflow モードのため、このステップは phase workflow API から明示的に起動してください。",
      }),
    ).toContain("デプロイ は開発フェーズの実行が完了するまで開けません");
  });
});
