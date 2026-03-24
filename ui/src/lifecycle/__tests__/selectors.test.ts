import { describe, expect, it } from "vitest";
import { defaultProductIdentity } from "@/lifecycle/productIdentity";
import {
  defaultResearchConfig,
  defaultStatuses,
} from "@/lifecycle/store";
import {
  selectApprovalViewModel,
  selectCompletedPhaseCount,
  selectDevelopmentViewModel,
  selectDeploySummary,
  selectPhaseStatus,
  selectPlanningAnalysis,
  selectPlanningReviewViewModel,
  selectPlanningViewModel,
  selectResearchProgressState,
  selectResearchReadinessState,
  selectResearchRuntimeSummary,
  selectResearchRuntimeTelemetry,
  selectSelectedDesign,
  selectSelectedFeatureCount,
  selectSelectedFeatures,
  selectSortedFeedbackItems,
} from "@/lifecycle/selectors";
import type { WorkflowRunState } from "@/hooks/useWorkflowRun";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type { MarketResearch } from "@/types/lifecycle";

function makeLifecycleState(
  overrides: Partial<LifecycleWorkspaceView> = {},
): LifecycleWorkspaceView {
  return {
    spec: "",
    orchestrationMode: "workflow",
    autonomyLevel: "A3",
    productIdentity: {
      ...defaultProductIdentity(),
      companyName: "Pylon Labs",
      productName: "Pylon",
      officialWebsite: "https://pylon.example.com",
      officialDomains: ["pylon.example.com"],
    },
    researchConfig: defaultResearchConfig(),
    research: null,
    analysis: null,
    features: [],
    milestones: [],
    designVariants: [],
    selectedDesignId: null,
    approvalStatus: "pending",
    approvalComments: [],
    buildCode: null,
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
    nextAction: null,
    autonomyState: null,
    runtimeObservedPhase: "research",
    runtimeActivePhase: null,
    runtimePhaseSummary: null,
    runtimeActivePhaseSummary: null,
    runtimeLiveTelemetry: null,
    runtimeConnectionState: "inactive",
    blueprints: {
      research: { phase: "research", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      planning: { phase: "planning", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      design: { phase: "design", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      approval: { phase: "approval", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      development: { phase: "development", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      deploy: { phase: "deploy", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      iterate: { phase: "iterate", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    },
    isHydrating: false,
    ...overrides,
  };
}

describe("lifecycle selectors", () => {
  it("selects phase status and research runtime sources", () => {
    const lifecycle = makeLifecycleState({
      runtimeActivePhase: "research",
      runtimeActivePhaseSummary: {
        phase: "research",
        status: "in_progress",
        readiness: "rework",
        objective: "Collect vendor evidence",
        nextAutomaticAction: "Retry competitor analysis",
        blockingSummary: [],
        failedGateCount: 1,
        degradedNodeCount: 2,
        canAutorun: true,
        attemptCount: 1,
        maxAttempts: 2,
        agents: [],
        recentActions: [],
      },
      runtimeLiveTelemetry: {
        phase: "research",
        run: {
          id: "run_1",
          status: "running",
          startedAt: "2026-03-13T00:00:00.000Z",
          completedAt: null,
          error: undefined,
        },
        eventCount: 3,
        completedNodeCount: 1,
        runningNodeIds: ["market-researcher"],
        failedNodeIds: [],
        lastEventSeq: 3,
        activeFocusNodeId: "market-researcher",
        lastNodeId: "market-researcher",
        lastAgent: "market-researcher",
        recentNodeIds: ["market-researcher"],
        recentEvents: [],
      },
    });

    expect(selectPhaseStatus(lifecycle.phaseStatuses, "research")).toBe("available");
    expect(selectResearchRuntimeSummary(lifecycle)?.phase).toBe("research");
    expect(selectResearchRuntimeTelemetry(lifecycle)?.run?.id).toBe("run_1");
  });

  it("ignores mismatched runtime telemetry even when the active phase is stale", () => {
    const lifecycle = makeLifecycleState({
      runtimeActivePhase: "research",
      runtimeLiveTelemetry: {
        phase: "design",
        run: {
          id: "run_design",
          status: "running",
          startedAt: "2026-03-13T00:00:00.000Z",
          completedAt: null,
          error: undefined,
        },
        eventCount: 1,
        completedNodeCount: 0,
        runningNodeIds: ["designer"],
        failedNodeIds: [],
        lastEventSeq: 1,
        activeFocusNodeId: "designer",
        lastNodeId: "designer",
        lastAgent: "designer",
        recentNodeIds: ["designer"],
        recentEvents: [],
      },
    });

    expect(selectResearchRuntimeTelemetry(lifecycle)).toBeNull();
  });

  it("computes research progress from runtime summary and workflow state", () => {
    const workflow: WorkflowRunState = {
      status: "running",
      runId: "run_1",
      agentProgress: [],
      state: {},
      error: null,
      elapsedMs: 0,
    };
    const result = selectResearchProgressState({
      workflow,
      runtimeSummary: {
        phase: "research",
        status: "in_progress",
        readiness: "rework",
        objective: "Collect evidence",
        nextAutomaticAction: "Retry",
        blockingSummary: [],
        failedGateCount: 1,
        degradedNodeCount: 1,
        canAutorun: true,
        attemptCount: 1,
        maxAttempts: 2,
        agents: [
          {
            agentId: "market-researcher",
            label: "市場調査",
            role: "Researcher",
            currentTask: "Collecting evidence",
            status: "running",
          },
        ],
        recentActions: [],
      },
      runtimeTelemetry: {
        phase: "research",
        run: {
          id: "run_1",
          status: "running",
          startedAt: "2026-03-13T00:00:00.000Z",
          completedAt: null,
          error: undefined,
        },
        eventCount: 2,
        completedNodeCount: 0,
        runningNodeIds: ["market-researcher"],
        failedNodeIds: [],
        lastEventSeq: 2,
        activeFocusNodeId: "market-researcher",
        lastNodeId: "market-researcher",
        lastAgent: "market-researcher",
        recentNodeIds: ["market-researcher"],
        recentEvents: [],
      },
      isPreparing: false,
      nowMs: new Date("2026-03-13T00:00:05.000Z").getTime(),
    });

    expect(result.isRunning).toBe(true);
    expect(result.isInitialResearchRun).toBe(true);
    expect(result.totalSteps).toBe(1);
    expect(result.completedSteps).toBe(0);
    expect(result.runtimeRunningNodes).toEqual(["market-researcher"]);
  });

  it("detects research readiness and autonomous recovery", () => {
    const research: MarketResearch = {
      competitors: [],
      market_size: "large",
      trends: [],
      opportunities: [],
      threats: [],
      tech_feasibility: { score: 0.8, notes: "good" },
      winning_theses: [],
      source_links: [],
      evidence: [],
      dissent: [
        {
          id: "d1",
          claim_id: "c1",
          challenger: "judge",
          argument: "weak",
          severity: "critical",
          resolved: false,
        },
      ],
      autonomous_remediation: {
        status: "retrying",
        attemptCount: 1,
        maxAttempts: 2,
        remainingAttempts: 1,
        objective: "Recover evidence",
        retryNodeIds: ["competitor-analyst"],
        blockingGateIds: ["source-grounding"],
        recoveryMode: "reframe_research",
        recommendedOperatorAction: "conditional_handoff",
        conditionalHandoffAllowed: true,
        strategySummary: "Shift the research angle before retrying.",
        planningGuardrails: ["Carry open questions into planning."],
      },
    };

    const result = selectResearchReadinessState({
      research,
      phaseStatus: "completed",
      nextAction: {
        type: "run_phase",
        phase: "research",
        title: "retry",
        reason: "quality gate",
        canAutorun: true,
        payload: {},
      },
    });

    expect(result.researchReady).toBe(false);
    expect(result.isAutonomousRecoveryActive).toBe(true);
    expect(result.criticalDissentCount).toBe(1);
    expect(result.gateIssues.length).toBeGreaterThan(0);
    expect(result.conditionalHandoffAllowed).toBe(true);
    expect(result.recommendedOperatorAction).toBe("conditional_handoff");
  });

  it("allows research readiness without identity when evidence is otherwise healthy", () => {
    const research: MarketResearch = {
      competitors: [],
      market_size: "large",
      trends: [],
      opportunities: [],
      threats: [],
      tech_feasibility: { score: 0.8, notes: "good" },
      winning_theses: ["One strong thesis"],
      source_links: ["https://example.com/vendor"],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://example.com/vendor",
          source_type: "url",
          snippet: "Grounded evidence",
          recency: "current",
          relevance: "high",
        },
      ],
      dissent: [],
      confidence_summary: { average: 0.82, floor: 0.78, accepted: 1 },
      quality_gates: [],
      node_results: [],
    };

    const result = selectResearchReadinessState({
      research,
      phaseStatus: "completed",
      nextAction: null,
      productIdentity: defaultProductIdentity(),
    });

    expect(result.researchReady).toBe(true);
    expect(result.gateIssues).toEqual([]);
  });

  it("prioritizes guarded planning handoff over stale recovery state", () => {
    const research: MarketResearch = {
      competitors: [],
      market_size: "large",
      trends: [],
      opportunities: [],
      threats: [],
      tech_feasibility: { score: 0.8, notes: "good" },
      winning_theses: ["One strong thesis"],
      source_links: ["https://example.com/vendor"],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://example.com/vendor",
          source_type: "url",
          snippet: "Grounded evidence",
          recency: "current",
          relevance: "high",
        },
      ],
      dissent: [
        {
          id: "d1",
          claim_id: "c1",
          challenger: "judge",
          argument: "weak",
          severity: "critical",
          resolved: false,
        },
      ],
      quality_gates: [
        {
          id: "confidence-floor",
          title: "confidence floor",
          passed: false,
          reason: "too low",
          blockingNodeIds: ["research-judge"],
        },
      ],
      node_results: [
        {
          nodeId: "research-judge",
          status: "degraded",
          parseStatus: "strict",
          degradationReasons: ["critical_dissent_unresolved"],
          sourceClassesSatisfied: [],
          missingSourceClasses: [],
          artifact: {},
          retryCount: 2,
        },
      ],
      confidence_summary: { average: 0.48, floor: 0.28, accepted: 1 },
      autonomous_remediation: {
        status: "retrying",
        attemptCount: 2,
        maxAttempts: 2,
        remainingAttempts: 0,
        objective: "Recover evidence",
        retryNodeIds: [],
        blockingGateIds: ["confidence-floor"],
        recoveryMode: "reframe_research",
        recommendedOperatorAction: "conditional_handoff",
        conditionalHandoffAllowed: true,
        strategySummary: "Shift the research angle before retrying.",
        planningGuardrails: ["Carry open questions into planning."],
      },
    };

    const result = selectResearchReadinessState({
      research,
      phaseStatus: "completed",
      nextAction: {
        type: "review_phase",
        phase: "planning",
        title: "条件付きで企画へ進めます",
        reason: "未解決の前提を明示して企画へ進みます。",
        canAutorun: false,
        payload: {
          operatorGuidance: {
            recommendedAction: "conditional_handoff",
            conditionalHandoffAllowed: true,
            strategySummary: "自動回復の予算を使い切ったため、前提を明示して企画へ進めます。",
            planningGuardrails: ["未解決の前提を企画に持ち込む"],
            followUpQuestion: "低信頼論点を kill criteria に落とし込んでください。",
          },
        },
      },
    });

    expect(result.researchReady).toBe(false);
    expect(result.isAutonomousRecoveryActive).toBe(false);
    expect(result.conditionalHandoffAllowed).toBe(true);
    expect(result.recommendedOperatorAction).toBe("conditional_handoff");
    expect(result.strategySummary).toContain("前提");
    expect(result.planningGuardrails).toEqual(["未解決の前提を企画に持ち込む"]);
  });

  it("blocks research readiness when semantic integrity is broken", () => {
    const research: MarketResearch = {
      competitors: [
        {
          name: "【要約】競合調査記事",
          url: "https://note.com/example/n/demo",
          strengths: ["記事の要約テキスト"],
          weaknesses: ["プロダクトではない"],
          pricing: "非公開",
          target: "B2C",
        },
      ],
      market_size: "76%,#000 99",
      trends: ["チュートリアル：Basler AG: @charset ..."],
      opportunities: ["https://docs.baslerweb.com/tutorial"],
      threats: [],
      tech_feasibility: { score: 0.82, notes: "実装可能" },
      winning_theses: ["運用品質が差別化になる"],
      claims: [
        {
          id: "claim-bad",
          statement: "【要約】競合調査記事",
          owner: "research-judge",
          category: "market",
          evidence_ids: ["ev-1"],
          counterevidence_ids: [],
          confidence: 0.95,
          status: "accepted",
        },
      ],
      source_links: [
        "https://note.com/example/n/demo",
        "https://docs.baslerweb.com/tutorial",
      ],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://note.com/example/n/demo",
          source_type: "url",
          snippet: "記事の要約です",
          recency: "current",
          relevance: "medium",
        },
      ],
      quality_gates: [
        {
          id: "source-grounding",
          title: "source grounding",
          passed: true,
          reason: "grounded",
          blockingNodeIds: [],
        },
      ],
      node_results: [
        {
          nodeId: "research-judge",
          status: "success",
          parseStatus: "strict",
          degradationReasons: [],
          sourceClassesSatisfied: [],
          missingSourceClasses: [],
          artifact: {},
          retryCount: 0,
        },
      ],
      confidence_summary: { average: 0.92, floor: 0.9, accepted: 1 },
      dissent: [
        {
          id: "d1",
          claim_id: "claim-bad",
          challenger: "judge",
          argument: "Basler AG: pylon Software Suite - コンピュータービジョン向け統合ソフトウェアパッケージ",
          severity: "high",
          resolved: false,
        },
      ],
      open_questions: ["【要約】競合調査記事"],
    };

    const result = selectResearchReadinessState({
      research,
      phaseStatus: "completed",
      nextAction: null,
      projectSpec: "AI エージェントが自律的に開発工程を実行する開発プラットフォーム",
    });

    expect(result.researchReady).toBe(false);
    expect(result.semanticIssues).toContain("市場規模の値が崩れており、数値根拠として扱えません。");
    expect(result.semanticIssues).toContain("主張台帳と残課題に対象外の文章が混ざっており、企画に渡す論点の再整理が必要です。");
    expect(result.semanticAudit?.quarantinedCount).toBeGreaterThan(0);
    expect(result.semanticAudit?.claims.quarantined).toHaveLength(1);
    expect(result.gateIssues[0]).toContain("市場規模");
  });

  it("uses seed url context to quarantine role-like competitors even when spec is thin", () => {
    const research: MarketResearch = {
      competitors: [
        {
          name: "Kuroha HR Product Manager",
          strengths: ["採用ワークフローを管理"],
          weaknesses: ["評価機能は限定的"],
          pricing: "要問い合わせ",
          target: "人事部門",
        },
      ],
      market_size: "国内 SaaS 市場は拡大傾向",
      trends: ["自律実行型の開発基盤への需要が高まっている"],
      opportunities: ["運用ガードレールを内蔵した開発基盤への需要が伸びる"],
      threats: [],
      tech_feasibility: { score: 0.84, notes: "実装可能" },
      winning_theses: ["自律実行の品質保証が差別化要因になる"],
      source_links: ["https://example.com/autonomous-dev-platform"],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://example.com/autonomous-dev-platform",
          source_type: "url",
          snippet: "Autonomous development platform with built-in quality controls.",
          recency: "current",
          relevance: "high",
        },
      ],
      quality_gates: [
        {
          id: "source-grounding",
          title: "source grounding",
          passed: true,
          reason: "grounded",
          blockingNodeIds: [],
        },
      ],
      node_results: [
        {
          nodeId: "research-judge",
          status: "success",
          parseStatus: "strict",
          degradationReasons: [],
          sourceClassesSatisfied: [],
          missingSourceClasses: [],
          artifact: {},
          retryCount: 0,
        },
      ],
      confidence_summary: { average: 0.91, floor: 0.88, accepted: 1 },
      dissent: [],
    };

    const result = selectResearchReadinessState({
      research,
      phaseStatus: "completed",
      nextAction: null,
      projectSpec: "",
      seedUrls: ["https://example.com/autonomous-dev-platform"],
    });

    expect(result.researchReady).toBe(false);
    expect(result.semanticAudit?.competitors.quarantined).toHaveLength(1);
    expect(result.semanticAudit?.competitors.quarantined[0]?.reason).toContain("役職名");
    expect(result.semanticIssues).toContain("企画判断に使える一次根拠が不足しています。");
  });

  it("parses structured planning risks and recommendations from string payloads", () => {
    const analysis = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [
          "{'id': 'rec-1', 'priority': 'critical', 'target': 'milestone-1 and milestone-2', 'action': 'Add explicit failure conditions to both milestones before design begins.', 'rationale': 'Milestones without stop conditions create false progress.'}",
          "主要状態と次アクションを常に明示して、利用中の迷いを減らす",
        ],
        judge_summary: "{'id': 'risk-1', 'severity': 'critical', 'title': 'Milestones lack stop conditions', 'description': 'Neither M1 nor M2 has a defined failure signal or halt threshold.', 'owner': 'product lead', 'must_resolve_before': 'design kickoff'}",
      },
    }));

    const reviewVm = selectPlanningReviewViewModel(analysis);

    expect(reviewVm.riskHighlights).toHaveLength(1);
    expect(reviewVm.riskHighlights[0]?.title).toBe("マイルストーンに中止条件がありません");
    expect(reviewVm.riskHighlights[0]?.owner).toBe("プロダクト責任者");
    expect(reviewVm.focusSummary).toContain("マイルストーンに中止条件がありません");
    expect(reviewVm.decisionSummary?.label).toBe("最優先リスク");
    expect(reviewVm.decisionSummary?.due).toBe("デザイン着手前");
    expect(reviewVm.structuredRecommendations).toHaveLength(1);
    expect(reviewVm.structuredRecommendations[0]?.target).toBe("マイルストーン 1 と 2");
    expect(reviewVm.structuredRecommendations[0]?.priority).toBe("critical");
    expect(reviewVm.recommendationNotes).toContain("主要状態と次アクションを常に明示して、利用中の迷いを減らす");
  });

  it("prefers localized planning analysis while preserving canonical metadata", () => {
    const analysis = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [
          "{'id': 'rec-1', 'priority': 'critical', 'action': 'Add explicit failure conditions to both milestones before design begins.', 'rationale': 'Milestones without stop conditions create false progress.'}",
        ],
        judge_summary: "{'id': 'risk-1', 'severity': 'critical', 'title': 'Milestones lack stop conditions', 'description': 'Neither M1 nor M2 has a defined failure signal or halt threshold.', 'owner': 'product lead', 'must_resolve_before': 'design kickoff'}",
        canonical: {
          judge_summary: "{'id': 'risk-1', 'severity': 'critical', 'title': 'Milestones lack stop conditions'}",
        },
        localized: {
          personas: [],
          user_stories: [],
          kano_features: [],
          recommendations: [
            "{\"id\": \"rec-1\", \"priority\": \"critical\", \"action\": \"デザイン着手前に、両方のマイルストーンへ明示的な失敗条件を追加します。\", \"rationale\": \"中止条件のないマイルストーンは、進捗しているように見えるだけの誤学習を生みます。\"}",
          ],
          judge_summary: "{\"id\": \"risk-1\", \"severity\": \"critical\", \"title\": \"マイルストーンに中止条件がありません\", \"description\": \"M1 と M2 のどちらにも、失敗シグナルや中止閾値が定義されていません。\", \"owner\": \"プロダクト責任者\", \"must_resolve_before\": \"デザイン着手前\"}",
        },
        display_language: "ja",
        localization_status: "strict",
      },
    }));

    const reviewVm = selectPlanningReviewViewModel(analysis);

    expect(reviewVm.decisionSummary?.title).toBe("マイルストーンに中止条件がありません");
    expect(reviewVm.structuredRecommendations[0]?.action).toBe("デザイン着手前に、両方のマイルストーンへ明示的な失敗条件を追加します。");
    expect(analysis.canonical?.judge_summary).toContain("Milestones lack stop conditions");
    expect(analysis.display_language).toBe("ja");
  });

  it("normalizes mixed-language planning fields when localized payload is missing", () => {
    const analysis = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [{
          name: "Naoki",
          role: "エンタープライズ向け導入責任者 Product Owner",
          age_range: "28-42",
          goals: ["Complete the primary workflow"],
          frustrations: ["Impatient Evaluator"],
          tech_proficiency: "high",
          context: "企画と実装の橋渡しを担う。",
        }],
        user_stories: [],
        kano_features: [{
          feature: "guided onboarding",
          category: "one-dimensional",
          user_delight: 0.7,
          implementation_cost: "medium",
          rationale: "subtle entry fades",
        }],
        recommendations: [],
        use_cases: [{
          id: "uc-1",
          title: "Complete the primary workflow",
          actor: "Primary User",
          category: "主要体験",
          sub_category: "実行",
          preconditions: [],
          main_flow: ["Adjust settings"],
          postconditions: [],
          priority: "must",
        }],
        negative_personas: [{
          id: "neg-1",
          name: "Impatient Evaluator",
          scenario: "Judges the product after one incomplete run.",
          risk: "Leaves before the core loop demonstrates value.",
          mitigation: "Make the first successful workflow obvious and measurable.",
        }],
        design_tokens: {
          style: {
            name: "Balanced Product",
            keywords: ["clear", "adaptive", "modern"],
            best_for: "general-purpose digital products with mixed audiences",
            performance: "progressive disclosure and responsive content grouping",
            accessibility: "clear semantic hierarchy and keyboard-safe interactions",
          },
          colors: {
            primary: "#1d4ed8",
            secondary: "#14b8a6",
            cta: "#f97316",
            background: "#f8fafc",
            text: "#0f172a",
            notes: "Keep the palette restrained so feature priority and content hierarchy carry the UI.",
          },
          typography: {
            heading: "IBM Plex Sans",
            body: "Noto Sans JP",
            mood: ["balanced", "practical", "modern"],
          },
          effects: ["subtle entry fades", "hover elevation", "clear focus rings"],
          anti_patterns: ["generic dashboard filler", "weak empty states", "low-information hero sections"],
          rationale: "The product should stay adaptable while preserving clear task hierarchy and predictable interactions.",
        },
      },
    }));

    expect(analysis.personas[0]?.role).toContain("プロダクトオーナー");
    expect(analysis.personas[0]?.goals[0]).toBe("主要ワークフローを完了する");
    expect(analysis.kano_features[0]?.feature).toBe("ガイド付きオンボーディング");
    expect(analysis.kano_features[0]?.rationale).toBe("穏やかなフェードイン");
    expect(analysis.use_cases?.[0]?.title).toBe("主要ワークフローを完了する");
    expect(analysis.use_cases?.[0]?.actor).toBe("主要ユーザー");
    expect(analysis.negative_personas?.[0]?.name).toBe("すぐ離脱する評価者");
    expect(analysis.design_tokens?.style.name).toBe("バランス型プロダクト");
    expect(analysis.design_tokens?.style.keywords).toEqual(["明快", "適応的", "モダン"]);
    expect(analysis.design_tokens?.effects).toEqual(["穏やかなフェードイン", "hover 時の浮き上がり", "明確なフォーカスリング"]);
  });

  it("builds multi-agent council cards and a design handoff brief", () => {
    const analysis = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [{
          name: "Naoki",
          role: "導入責任者",
          age_range: "28-42",
          goals: ["主要ワークフローを完了する"],
          frustrations: ["要求が広がりやすい"],
          tech_proficiency: "high",
          context: "企画と実装の橋渡しを担う。",
        }],
        user_stories: [],
        kano_features: [{
          feature: "guided onboarding",
          category: "attractive",
          user_delight: 0.8,
          implementation_cost: "medium",
          rationale: "最初の成功体験を早く見せる",
        }],
        recommendations: [
          "{'id': 'rec-1', 'priority': 'critical', 'target': 'milestone-1', 'action': 'Add explicit failure conditions to both milestones before design begins.', 'rationale': 'Milestones without stop conditions create false progress.'}",
        ],
        judge_summary: "{'id': 'risk-1', 'severity': 'critical', 'title': 'Milestones lack stop conditions', 'description': 'Neither M1 nor M2 has a defined failure signal or halt threshold.', 'owner': 'product lead', 'must_resolve_before': 'design kickoff'}",
        use_cases: [{
          id: "uc-1",
          title: "主要ワークフローを完了する",
          actor: "主要ユーザー",
          category: "主要体験",
          sub_category: "実行",
          preconditions: [],
          main_flow: ["開始する", "結果を確認する"],
          postconditions: [],
          priority: "must",
        }],
        kill_criteria: [{
          id: "kill-1",
          milestone_id: "ms-1",
          condition: "コアワークフローの完了証跡が見えない場合はスコープ拡張を止める",
          rationale: "反証可能なマイルストーンにする",
        }],
        design_tokens: {
          style: {
            name: "バランス型プロダクト",
            keywords: ["明快", "適応的", "モダン"],
            best_for: "複数案件の同時レビュー",
            performance: "段階的な情報開示",
            accessibility: "キーボードでも迷わない操作",
          },
          colors: {
            primary: "#1d4ed8",
            secondary: "#14b8a6",
            cta: "#f97316",
            background: "#f8fafc",
            text: "#0f172a",
            notes: "",
          },
          typography: {
            heading: "IBM Plex Sans",
            body: "Noto Sans JP",
            mood: ["均衡", "実務的", "モダン"],
          },
          effects: ["穏やかなフェードイン"],
          anti_patterns: ["弱い空状態"],
          rationale: "主要判断を先に見せる",
        },
      },
    }));

    const reviewVm = selectPlanningReviewViewModel(analysis);

    expect(reviewVm.councilCards).toHaveLength(4);
    expect(reviewVm.councilCards.map((card) => card.agent)).toEqual([
      "プロダクト評議",
      "リサーチ評議",
      "デザイン評議",
      "デリバリー評議",
    ]);
    expect(reviewVm.councilCards[2]?.targetTab).toBe("design-tokens");
    expect(reviewVm.handoffBrief.headline).toContain("デザイン着手前");
    expect(reviewVm.handoffBrief.bullets).toContain("UI の方向性: バランス型プロダクト");
    expect(reviewVm.handoffBrief.bullets.some((item) => item.includes("ガイド付きオンボーディング"))).toBe(true);
  });

  it("prefers backend-generated operator copy for council and handoff UI", () => {
    const analysis = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [],
        operator_copy: {
          council_cards: [
            {
              id: "product-council",
              agent: "プロダクト評議",
              lens: "価値判断",
              title: "先に停止条件を固定する",
              summary: "backend が生成した表示文言をそのまま使う。",
              action_label: "推奨アクションへ",
              target_section: "recommendation",
              tone: "critical",
            },
          ],
          handoff_brief: {
            headline: "条件付き handoff を準備しました",
            summary: "backend 生成の handoff brief を優先表示する。",
            bullets: ["UI の方向性: バランス型プロダクト"],
          },
        },
      },
    }));

    const reviewVm = selectPlanningReviewViewModel(analysis);

    expect(reviewVm.councilCards).toHaveLength(1);
    expect(reviewVm.councilCards[0]?.title).toBe("先に停止条件を固定する");
    expect(reviewVm.handoffBrief.headline).toBe("条件付き handoff を準備しました");
    expect(reviewVm.handoffBrief.summary).toBe("backend 生成の handoff 要約 を優先表示する。");
  });

  it("prioritizes the most severe planning risk before less urgent items", () => {
    const analysis = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [
          "{'id': 'rec-2', 'priority': 'medium', 'action': 'Later action', 'rationale': 'Secondary follow-up.'}",
          "{'id': 'rec-1', 'priority': 'critical', 'action': 'Primary action', 'rationale': 'Critical follow-up.'}",
        ],
        judge_summary: "{'id': 'risk-2', 'severity': 'medium', 'title': 'Lower risk', 'description': 'Less urgent.', 'owner': 'product lead', 'must_resolve_before': 'M1 user testing'}, {'id': 'risk-1', 'severity': 'critical', 'title': 'Top risk', 'description': 'Most urgent.', 'owner': 'research lead', 'must_resolve_before': 'design kickoff'}",
      },
    }));

    const reviewVm = selectPlanningReviewViewModel(analysis);

    expect(reviewVm.riskHighlights[0]?.title).toBe("Top risk");
    expect(reviewVm.decisionSummary?.title).toBe("Top risk");
    expect(reviewVm.structuredRecommendations[0]?.action).toBe("Primary action");
  });

  it("falls back to red-team findings when structured planning risks are missing", () => {
    const analysis = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [],
        red_team_findings: [
          {
            id: "finding-1",
            challenger: "scope-skeptic",
            severity: "high",
            title: "History and recovery scope is unbounded",
            impact: "Selected without a size constraint, history and recovery can silently consume M1 capacity.",
            recommendation: "Add explicit failure conditions to both milestones before design begins.",
          },
        ],
      },
    }));

    const reviewVm = selectPlanningReviewViewModel(analysis);

    expect(reviewVm.heroStats.find((item) => item.label === "重要リスク")?.value).toBe(1);
    expect(reviewVm.riskHighlights[0]?.title).toBe("履歴と復旧のスコープが膨らみやすい状態です");
    expect(reviewVm.decisionSummary?.title).toBe("履歴と復旧のスコープが膨らみやすい状態です");
  });

  it("derives selected design, selected features, completed phases, and feedback order", () => {
    const lifecycle = makeLifecycleState({
      selectedDesignId: "design_2",
      designVariants: [
        {
          id: "design_1",
          model: "model-a",
          pattern_name: "Pattern A",
          description: "A",
          preview_html: "<div />",
          tokens: { in: 10, out: 20 },
          scores: { ux_quality: 7, code_quality: 7, performance: 7, accessibility: 7 },
          cost_usd: 0.1,
        },
        {
          id: "design_2",
          model: "model-b",
          pattern_name: "Pattern B",
          description: "B",
          preview_html: "<div />",
          tokens: { in: 12, out: 22 },
          scores: { ux_quality: 9, code_quality: 8, performance: 8, accessibility: 8 },
          cost_usd: 0.2,
        },
      ],
      features: [
        { feature: "A", selected: true, rationale: "", priority: "must", category: "must-be", user_delight: 8, implementation_cost: "medium" },
        { feature: "B", selected: false, rationale: "", priority: "could", category: "attractive", user_delight: 6, implementation_cost: "low" },
      ],
      phaseStatuses: defaultStatuses().map((item, index) => ({
        ...item,
        status: index < 2 ? "completed" : item.status,
      })),
      feedbackItems: [
        { id: "f1", text: "low", type: "improvement", impact: "low", votes: 1, createdAt: "2026-03-13T00:00:00.000Z" },
        { id: "f2", text: "high", type: "feature", impact: "high", votes: 4, createdAt: "2026-03-13T00:01:00.000Z" },
      ],
    });

    expect(selectSelectedDesign(lifecycle)?.id).toBe("design_2");
    expect(selectSelectedFeatureCount(lifecycle)).toBe(1);
    expect(selectSelectedFeatures(lifecycle)).toHaveLength(1);
    expect(selectCompletedPhaseCount(lifecycle)).toBe(2);
    expect(selectSortedFeedbackItems(lifecycle).map((item) => item.id)).toEqual(["f2", "f1"]);
  });

  it("summarizes deploy state", () => {
    const lifecycle = makeLifecycleState({
      deployChecks: [
        { id: "c1", label: "A", detail: "ok", status: "pass" },
        { id: "c2", label: "B", detail: "warn", status: "warning" },
      ],
      releases: [
        {
          id: "r1",
          version: "v1.0.0",
          createdAt: "2026-03-13T00:00:00.000Z",
          note: "ship",
          artifactBytes: 2048,
          qualitySummary: { overallScore: 88, releaseReady: true, passed: 1, warnings: 1, failed: 0 },
        },
      ],
    });

    const result = selectDeploySummary(lifecycle);

    expect(result.allPassed).toBe(true);
    expect(result.deployed).toBe(true);
    expect(result.latestRelease?.version).toBe("v1.0.0");
    expect(result.passedCount).toBe(1);
    expect(result.warningCount).toBe(1);
    expect(result.failedCount).toBe(0);
  });

  it("builds planning, approval, and development view models", () => {
    const lifecycle = makeLifecycleState({
      spec: "Factory workflow",
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [],
        roles: [
          {
            name: "Operator",
            responsibilities: ["approve delivery"],
            permissions: ["approve_delivery"],
            related_actors: ["Lifecycle Operator"],
          },
        ],
        design_tokens: {
          style: {
            name: "Operator Studio",
            keywords: ["structured"],
            best_for: "operator workspaces",
            performance: "light transitions",
            accessibility: "high contrast",
          },
          colors: {
            primary: "#2563eb",
            secondary: "#0f172a",
            cta: "#f97316",
            background: "#f8fafc",
            text: "#0f172a",
            notes: "calm control room palette",
          },
          typography: {
            heading: "IBM Plex Sans",
            body: "Noto Sans JP",
            mood: ["precise"],
          },
          effects: ["state changes fade without losing focus"],
          anti_patterns: ["avoid decorative motion"],
          rationale: "Keep operators oriented during approvals.",
        },
      },
      selectedDesignId: "design_2",
      designVariants: [
        {
          id: "design_2",
          model: "model-b",
          pattern_name: "Pattern B",
          description: "B",
          preview_html: "<div />",
          tokens: { in: 12, out: 22 },
          scores: { ux_quality: 0.9, code_quality: 0.8, performance: 0.8, accessibility: 0.8 },
          cost_usd: 0.2,
          scorecard: {
            overall_score: 0.86,
            summary: "summary",
            dimensions: [],
          },
          approval_packet: {
            operator_promise: "promise",
            must_keep: ["keep"],
            guardrails: ["guardrail"],
            review_checklist: ["review"],
            handoff_summary: "handoff",
          },
          primary_workflows: [
            { id: "wf-1", name: "Primary", goal: "ship", steps: ["A", "B"] },
          ],
          screen_specs: [
            { id: "scr-1", title: "Screen", purpose: "Purpose", layout: "panel", primary_actions: ["Open"], module_count: 1, route_path: "/" },
          ],
          artifact_completeness: {
            score: 1,
            status: "complete",
            present: ["preview_html", "scorecard", "approval_packet"],
            missing: [],
            screen_count: 1,
            workflow_count: 1,
            route_count: 1,
          },
          freshness: {
            status: "fresh",
            can_handoff: true,
            current_fingerprint: "fp-1",
            variant_fingerprint: "fp-1",
            reasons: [],
          },
          preview_meta: {
            source: "llm",
            extraction_ok: true,
            validation_ok: true,
            html_size: 800,
            screen_count_estimate: 1,
            interactive_features: ["tabs"],
            validation_issues: [],
          },
        },
      ],
      features: [
        { feature: "A", selected: true, rationale: "", priority: "must", category: "must-be", user_delight: 8, implementation_cost: "medium" },
      ],
      milestones: [
        { id: "m1", name: "Release", criteria: "ship", status: "pending" },
      ],
    });

    const planning = selectPlanningAnalysis(lifecycle);
    const planningVm = selectPlanningViewModel(lifecycle);
    const planningReview = selectPlanningReviewViewModel(planning);
    const approval = selectApprovalViewModel(lifecycle);
    const development = selectDevelopmentViewModel({
      approvalStatus: "approved",
      analysis: lifecycle.analysis,
      blueprints: lifecycle.blueprints,
      designVariants: lifecycle.designVariants,
      milestones: lifecycle.milestones,
      selectedDesignId: lifecycle.selectedDesignId,
      features: lifecycle.features,
      requirements: {
        requirements: [{ id: "REQ-1", pattern: "ubiquitous", statement: "The system shall support authorized approval delivery.", confidence: 0.9, sourceClaimIds: [], userStoryIds: [], acceptanceCriteria: ["Show approval packet within an authorization boundary"] }],
        userStories: [],
        acceptanceCriteria: [],
        confidenceDistribution: { high: 1, medium: 0, low: 0 },
        completenessScore: 0.9,
        traceabilityIndex: { "REQ-1": ["claim-1"] },
      },
      taskDecomposition: {
        tasks: [{ id: "TASK-1", title: "Approval workspace", description: "Build access-controlled approval workspace", phase: "development", milestoneId: "ms-1", dependsOn: [], effortHours: 8, priority: "must", featureId: "feature-1", requirementId: "REQ-1" }],
        dagEdges: [],
        phaseMilestones: [],
        totalEffortHours: 8,
        criticalPath: ["TASK-1"],
        effortByPhase: { development: 8 },
        hasCycles: false,
      },
      dcsAnalysis: {
        rubberDuckPrd: null,
        edgeCases: { edgeCases: [], riskMatrix: {}, coverageScore: 0.8 },
        impactAnalysis: { layers: [], blastRadius: 1, criticalPathsAffected: [] },
        sequenceDiagrams: { diagrams: [{ id: "seq-1", title: "Approval", mermaidCode: "sequenceDiagram\nA->>B: ok", flowType: "core" }] },
        stateTransitions: { states: [{ id: "s1", name: "Ready", description: "ready" }], transitions: [], riskStates: [], mermaidCode: "stateDiagram-v2\n[*] --> Ready" },
      },
      technicalDesign: {
        architecture: { style: "nextjs" },
        dataflowMermaid: "flowchart LR\nUI-->API",
        apiSpecification: [{ method: "POST", path: "/api/approval/decision", description: "Approve", authRequired: true }],
        databaseSchema: [{ name: "approval_decisions", columns: [{ name: "id", type: "uuid", primaryKey: true }], indexes: [] }],
        interfaceDefinitions: [{ name: "ApprovalDecision", properties: [{ name: "id", type: "string" }], extends: [] }],
        componentDependencyGraph: {},
      },
      reverseEngineering: {
        extractedRequirements: [],
        architectureDoc: {},
        dataflowMermaid: "flowchart LR\nUI-->API",
        apiEndpoints: [{ method: "POST", path: "/api/approval/decision", handler: "approve", filePath: "server/api/approval.ts" }],
        databaseSchema: [],
        interfaces: [],
        taskStructure: [],
        testSpecs: [],
        coverageScore: 0.7,
        languagesDetected: ["typescript"],
      },
      deliveryPlan: {
        execution_mode: "autonomous_delivery",
        summary: "dependency-aware delivery graph",
        selected_preset: "standard",
        source_plan_preset: "standard",
        success_definition: "ship a deploy-ready build",
        work_packages: [
          {
            id: "wp-1",
            title: "UI shell",
            lane: "frontend-builder",
            summary: "build the shell",
            depends_on: [],
            start_day: 0,
            duration_days: 2,
            deliverables: ["UI shell"],
            acceptance_criteria: ["ship"],
            owned_surfaces: ["workspace shell"],
            status: "planned",
            is_critical: true,
          },
        ],
        lanes: [
          {
            agent: "frontend-builder",
            label: "Frontend Builder",
            remit: "UI shell",
            skills: ["responsive-ui"],
            owned_surfaces: ["workspace shell"],
            conflict_guards: ["UI shell is single-owned"],
            merge_order: 1,
          },
        ],
        critical_path: ["wp-1"],
        gantt: [
          {
            work_package_id: "wp-1",
            lane: "frontend-builder",
            start_day: 0,
            duration_days: 2,
            depends_on: [],
            is_critical: true,
          },
        ],
        merge_strategy: {
          integration_order: ["wp-1"],
          conflict_prevention: ["UI shell changes merge through integrator"],
          shared_touchpoints: ["approval gate"],
        },
        spec_audit: {
          status: "ready_for_autonomous_build",
          completeness_score: 0.92,
          requirements_count: 1,
          task_count: 1,
          api_surface_count: 1,
          database_table_count: 1,
          interface_count: 1,
          route_binding_count: 1,
          workspace_file_count: 3,
          behavior_gate_count: 1,
          feature_coverage: [{ feature: "research workspace", requirement_covered: true, task_covered: true, api_covered: true, route_covered: true }],
          unresolved_gaps: [],
          closing_actions: [],
        },
        code_workspace: {
          framework: "nextjs",
          router: "app",
          preview_entry: "/",
          entrypoints: ["app/page.tsx"],
          install_command: "npm install",
          dev_command: "npm run dev",
          build_command: "npm run build",
          package_tree: [{ id: "app-routes", label: "App Routes", path: "app", lane: "frontend-builder", kind: "generated", file_count: 3 }],
          files: [
            { path: "app/page.tsx", kind: "tsx", package_id: "app-routes", package_label: "App Routes", package_path: "app", lane: "frontend-builder", route_paths: ["/"], entrypoint: true, generated_from: "prototype_app", line_count: 12, content_preview: "export default function Page() {}", content: "export default function Page() {}" },
          ],
          package_graph: [],
          route_bindings: [{ route_path: "/", screen_id: "screen-1", file_paths: ["app/page.tsx"] }],
          artifact_summary: { package_count: 1, file_count: 1, route_binding_count: 1, entrypoint_count: 1 },
        },
        repo_execution: {
          mode: "temp_workspace",
          workspace_path: "/tmp/pylon-workspace",
          worktree_path: null,
          repo_root: null,
          materialized_file_count: 1,
          install: { status: "passed", command: "npm install", exit_code: 0, duration_ms: 1200, stdout_tail: "", stderr_tail: "" },
          build: { status: "passed", command: "npm run build", exit_code: 0, duration_ms: 2400, stdout_tail: "", stderr_tail: "" },
          test: { status: "skipped", command: "", exit_code: null, duration_ms: 0, stdout_tail: "", stderr_tail: "" },
          ready: true,
          errors: [],
        },
      },
      developmentHandoff: {
        readiness_status: "ready_for_deploy",
        release_candidate: "candidate",
        operator_summary: "deploy ready",
        deploy_checklist: [{ id: "critical-path-integrated", label: "critical path integrated", category: "integration", required: true }],
        evidence: [{ category: "milestone", label: "Alpha satisfied", value: "Alpha", unit: "id" }],
        blocking_issues: [],
        review_focus: [{ area: "review", description: "approval gate", priority: "high" as const }],
      },
    });

    expect(planning.personas).toEqual([]);
    expect(planningVm.initialStep).toBe("review");
    expect(planningVm.canRunAnalysis).toBe(true);
    expect(planningReview.reviewTabs.find((tab) => tab.key === "journey")?.hidden).toBe(true);
    expect(planningReview.overviewStats.find((item) => item.label === "高優先アクション")?.value).toBe(0);
    expect(approval.allChecked).toBe(true);
    expect(approval.completedChecklistCount).toBe(7);
    expect(development.canStartBuild).toBe(true);
    expect(development.maxIterations).toBe(5);
    expect(development.buildTeam.length).toBeGreaterThan(0);
    expect(development.workPackageCount).toBe(1);
    expect(development.conflictGuardCount).toBe(1);
    expect(development.packageCount).toBe(1);
    expect(development.routeBindingCount).toBe(1);
    expect(development.unresolvedGapCount).toBe(0);
    expect(development.repoExecution?.ready).toBe(true);
  });

  it("blocks development start when design and auth contracts are missing", () => {
    const development = selectDevelopmentViewModel({
      approvalStatus: "approved",
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [],
        roles: [],
      },
      blueprints: makeLifecycleState().blueprints,
      designVariants: [
        {
          id: "design_2",
          model: "model-b",
          pattern_name: "Pattern B",
          description: "B",
          preview_html: "<div />",
          tokens: { in: 12, out: 22 },
          scores: { ux_quality: 0.9, code_quality: 0.8, performance: 0.8, accessibility: 0.8 },
          cost_usd: 0.2,
          scorecard: { overall_score: 0.86, summary: "summary", dimensions: [] },
          approval_packet: {
            operator_promise: "promise",
            must_keep: ["keep"],
            guardrails: ["guardrail"],
            review_checklist: ["review"],
            handoff_summary: "handoff",
          },
          primary_workflows: [{ id: "wf-1", name: "Primary", goal: "ship", steps: ["A", "B"] }],
          screen_specs: [{ id: "scr-1", title: "Screen", purpose: "Purpose", layout: "panel", primary_actions: ["Open"], module_count: 1, route_path: "/" }],
          artifact_completeness: { score: 1, status: "complete", present: ["preview_html"], missing: [], screen_count: 1, workflow_count: 1, route_count: 1 },
          freshness: { status: "fresh", can_handoff: true, current_fingerprint: "fp-1", variant_fingerprint: "fp-1", reasons: [] },
          preview_meta: { source: "llm", extraction_ok: true, validation_ok: true, html_size: 800, screen_count_estimate: 1, interactive_features: [], validation_issues: [] },
        },
      ],
      milestones: [{ id: "m1", name: "Release", criteria: "ship", status: "pending" }],
      selectedDesignId: "design_2",
      features: [{ feature: "A", selected: true, rationale: "", priority: "must", category: "must-be", user_delight: 8, implementation_cost: "medium" }],
      requirements: {
        requirements: [{ id: "REQ-1", pattern: "ubiquitous", statement: "The system shall support approval delivery.", confidence: 0.9, sourceClaimIds: [], userStoryIds: [], acceptanceCriteria: ["Show approval packet"] }],
        userStories: [],
        acceptanceCriteria: [],
        confidenceDistribution: { high: 1, medium: 0, low: 0 },
        completenessScore: 0.9,
        traceabilityIndex: { "REQ-1": ["claim-1"] },
      },
      taskDecomposition: {
        tasks: [{ id: "TASK-1", title: "Approval workspace", description: "Build approval workspace", phase: "development", milestoneId: "ms-1", dependsOn: [], effortHours: 8, priority: "must", featureId: "feature-1", requirementId: "REQ-1" }],
        dagEdges: [],
        phaseMilestones: [],
        totalEffortHours: 8,
        criticalPath: ["TASK-1"],
        effortByPhase: { development: 8 },
        hasCycles: false,
      },
      dcsAnalysis: {
        rubberDuckPrd: null,
        edgeCases: { edgeCases: [], riskMatrix: {}, coverageScore: 0.8 },
        impactAnalysis: { layers: [], blastRadius: 1, criticalPathsAffected: [] },
        sequenceDiagrams: { diagrams: [{ id: "seq-1", title: "Approval", mermaidCode: "sequenceDiagram\nA->>B: ok", flowType: "core" }] },
        stateTransitions: { states: [{ id: "s1", name: "Ready", description: "ready" }], transitions: [], riskStates: [], mermaidCode: "stateDiagram-v2\n[*] --> Ready" },
      },
      technicalDesign: {
        architecture: { style: "nextjs" },
        dataflowMermaid: "flowchart LR\nUI-->API",
        apiSpecification: [{ method: "POST", path: "/api/approval/decision", description: "Approve", authRequired: true }],
        databaseSchema: [],
        interfaceDefinitions: [],
        componentDependencyGraph: {},
      },
      reverseEngineering: {
        extractedRequirements: [],
        architectureDoc: {},
        dataflowMermaid: "flowchart LR\nUI-->API",
        apiEndpoints: [],
        databaseSchema: [],
        interfaces: [],
        taskStructure: [],
        testSpecs: [],
        coverageScore: 0.7,
        languagesDetected: ["typescript"],
      },
    });

    expect(development.canStartBuild).toBe(false);
    expect(development.preflightItems.some((item) => item.label.includes("デザイントークン") && !item.done)).toBe(true);
    expect(development.preflightItems.some((item) => item.label.includes("認証・認可") && !item.done)).toBe(true);
  });

  it("surfaces planning coverage summary when richer planning payload is present", () => {
    const planning = selectPlanningAnalysis(makeLifecycleState({
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [],
        feature_decisions: [
          { feature: "research workspace", selected: true, supporting_claim_ids: ["claim-1"], counterarguments: [], rejection_reason: "", uncertainty: 0.2 },
          { feature: "planning synthesis", selected: true, supporting_claim_ids: ["claim-2"], counterarguments: [], rejection_reason: "", uncertainty: 0.2 },
        ],
        coverage_summary: {
          selected_feature_count: 2,
          job_story_count: 4,
          use_case_count: 6,
          actor_count: 3,
          role_count: 3,
          traceability_count: 2,
          milestone_count: 3,
          uncovered_features: [],
          use_cases_without_milestone: ["Review release readiness and publish outcome"],
          use_cases_without_traceability: [],
          preset_breakdown: [
            { preset: "standard", epic_count: 4, wbs_count: 14, total_effort_hours: 118 },
          ],
        },
      },
    }));

    const review = selectPlanningReviewViewModel(planning);

    expect(review.coverageSummary?.tiles.find((item) => item.label === "ユースケース")?.value).toBe(6);
    expect(review.coverageSummary?.notes[0]).toContain("4 エピック / 14 タスク / 118h");
    expect(review.coverageSummary?.notes[2]).toContain("リリース準備を確認して結果を記録する");
  });
});
