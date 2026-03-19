import { describe, expect, it } from "vitest";
import {
  localizePreviewHtmlForDisplay,
  presentDecisionCoreLoop,
  presentDecisionLeadThesis,
  presentDecisionReviewItems,
  presentDecisionNorthStar,
  presentDecisionSummary,
  presentFeatureLabel,
  presentScreenText,
  presentVariantApprovalPacket,
  presentVariantEstimatedCost,
  presentVariantExperienceThesis,
  presentVariantHandoffNote,
  presentVariantModelLabel,
  presentVariantSelectionReasons,
  presentVariantSelectionSummary,
  presentVariantTradeoffs,
} from "@/lifecycle/designDecisionPresentation";
import type { LifecycleDecisionFrame } from "@/types/lifecycle";

describe("designDecisionPresentation", () => {
  const frame: LifecycleDecisionFrame = {
    summary: "The plan keeps only features that remain traceable to research claims and falsifiable milestones.",
    north_star: "Operator trust: every phase decision should remain explainable, reviewable, and recoverable.",
    core_loop: "Turn grounded evidence into a governed plan, then carry the same decision context into design and build.",
    lead_thesis: "公開ソースでは導入判断時の不安が繰り返し現れており、信頼形成が主要な UX 論点になります。",
    thesis_snapshot: [],
    key_risks: [],
    key_assumptions: [],
    selected_features: [],
    primary_use_cases: [],
    milestones: [],
    primary_personas: [],
  };

  it("localizes canonical decision frame copy for design display", () => {
    expect(presentDecisionSummary(frame)).toContain("調査根拠にさかのぼれ");
    expect(presentDecisionNorthStar(frame)).toContain("説明できて");
    expect(presentDecisionCoreLoop(frame)).toContain("判断文脈");
  });

  it("localizes feature and screen labels", () => {
    expect(presentFeatureLabel("research workspace")).toBe("調査ワークスペース");
    expect(presentScreenText("Artifact Lineage — Provenance Drawer")).toContain("成果物系譜");
  });

  it("recomputes displayed cost from current lane policy", () => {
    expect(
      presentVariantEstimatedCost({
        id: "gemini-designer",
        model: "Gemini 3 Pro",
        tokens: { in: 4200, out: 3100 },
        cost_usd: 0.28,
      }),
    ).toBe(0.036);
    expect(
      presentVariantModelLabel({
        id: "gemini-designer",
        model: "Gemini 3 Pro",
      }),
    ).toBe("Gemini 3 Pro");
  });

  it("synthesizes a Japanese experience thesis when legacy variants lack narrative", () => {
    const thesis = presentVariantExperienceThesis(
      {
        id: "claude-designer",
        description: "A precision-engineered operator shell.",
        pattern_name: "Obsidian Control Atelier",
        provider_note: "",
        rationale: "",
        narrative: undefined,
        decision_scope: {},
      },
      frame,
    );

    expect(thesis).toContain("成果物の系譜と承認根拠");
    expect(thesis).toContain("情報を圧縮せずに並べ");
  });

  it("avoids exposing raw implementation notes as handoff copy", () => {
    const handoff = presentVariantHandoffNote({
      id: "claude-designer",
      narrative: undefined,
      rationale: "",
      provider_note: "三ゾーンレイアウトはCSS Grid `grid-template-columns: 240px 1fr 360px` で実装し、CSS Custom Propertiesで管理する。",
    });

    expect(handoff).toContain("承認パケット");
    expect(handoff).not.toContain("grid-template-columns");
  });

  it("presents structured selection rationale and approval packet copy", () => {
    expect(
      presentVariantSelectionSummary({
        id: "claude-designer",
        pattern_name: "Obsidian Control Atelier",
        description: "dense operator workspace",
        selection_rationale: {
          summary: "承認、根拠、差し戻しを一枚の判断面で扱えるため採用する。",
          reasons: ["承認理由と evidence が同じビューに残る。"],
          tradeoffs: ["高密度なため、視線誘導の質を落とせない。"],
          approval_focus: ["承認理由と根拠リンクを同じ面に残す。"],
          confidence: 0.91,
          verdict: "selected",
        },
      }),
    ).toContain("承認、根拠、差し戻し");

    expect(
      presentVariantSelectionReasons({
        id: "claude-designer",
        pattern_name: "Obsidian Control Atelier",
        description: "dense operator workspace",
        decision_scope: {},
        narrative: undefined,
        provider_note: "",
        rationale: "",
        selection_rationale: {
          summary: "承認、根拠、差し戻しを一枚の判断面で扱えるため採用する。",
          reasons: ["承認理由と evidence が同じビューに残る。"],
          tradeoffs: ["高密度なため、視線誘導の質を落とせない。"],
          approval_focus: ["承認理由と根拠リンクを同じ面に残す。"],
          confidence: 0.91,
          verdict: "selected",
        },
      })[0],
    ).toContain("根拠");

    expect(
      presentVariantTradeoffs({
        id: "claude-designer",
        selection_rationale: {
          summary: "",
          reasons: [],
          tradeoffs: ["高密度なため、視線誘導の質を落とせない。"],
          approval_focus: [],
          confidence: 0.8,
          verdict: "selected",
        },
      })[0],
    ).toContain("高密度");

    expect(
      presentVariantApprovalPacket({
        id: "claude-designer",
        pattern_name: "Obsidian Control Atelier",
        description: "dense operator workspace",
        decision_scope: {},
        narrative: undefined,
        provider_note: "",
        rationale: "",
        approval_packet: {
          operator_promise: "判断材料と次の一手が離れない operator workspace。",
          must_keep: ["主要フローと承認理由を同じ文脈で確認できること。"],
          guardrails: ["visible UI に内部用語を残さないこと。"],
          review_checklist: ["承認または差し戻し理由を、その場で根拠と照合できる。"],
          handoff_summary: "主要 4 画面と 2 フローを承認パケットへ束ねる。",
        },
      }).guardrails[0],
    ).toContain("内部用語");
  });

  it("turns risky planning headlines into approval-ready design copy", () => {
    expect(presentDecisionLeadThesis(frame)).toContain("成果物の系譜と承認根拠");
    expect(presentDecisionSummary({
      ...frame,
      summary: frame.lead_thesis,
    })).toContain("操作密度と判断リズムの異なる 2 案");
  });

  it("rewrites planning risks and assumptions into design review prompts", () => {
    const items = presentDecisionReviewItems({
      ...frame,
      key_risks: [{ id: "risk-1", title: "運用コンソールまわりのスコープ圧力が高い状態です" }],
      key_assumptions: [{ id: "assumption-1", title: "承認前に根拠をその場で読める必要がある" }],
    });

    expect(items[0]).toContain("初回リリースでは運用コンソールの範囲を固定");
    expect(items[1]).toContain("承認前に根拠をその場で読み返せること");
  });

  it("localizes preview html text nodes without mutating scripts", () => {
    const localized = localizePreviewHtmlForDisplay(
      "<!doctype html><html lang='en'><body>"
      + "<button aria-label='Open an artifact'>Open an artifact</button>"
      + "<p>Product Platform Lead</p>"
      + "<p>Start research</p>"
      + "<p>Team routing</p>"
      + "<p>Build artifacts and phase history are recorded</p>"
      + "<script>const label = 'Policies';</script>"
      + "</body></html>",
    );

    expect(localized).toContain("成果物を開く");
    expect(localized).toContain("プロダクト基盤責任者");
    expect(localized).toContain("調査を開始する");
    expect(localized).toContain("チームルーティング");
    expect(localized).toContain("成果物とフェーズ履歴が記録される");
    expect(localized).toContain("const label = 'Policies'");
    expect(localized).toContain("<html lang=\"ja\">");
  });

  it("cleans up prototype and workflow copy that would otherwise read as raw machine output", () => {
    const localized = localizePreviewHtmlForDisplay(
      "<!doctype html><html lang='en'><body>"
      + "<p>prototype app</p>"
      + "<p>research から development まで</p>"
      + "<p>approval と rework</p>"
      + "<p>phase deep link 付き</p>"
      + "</body></html>",
    );

    expect(localized).toContain("試作アプリ");
    expect(localized).toContain("調査から開発まで");
    expect(localized).toContain("承認と差し戻し");
    expect(localized).toContain("フェーズ直通リンク付き");
  });
});
