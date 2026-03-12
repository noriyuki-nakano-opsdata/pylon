import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  LifecycleArtifact,
  LifecycleDecision,
  LifecycleDelegation,
  LifecyclePhase,
  LifecyclePhaseRuntimeSummary,
  LifecyclePhaseRun,
  MarketResearch,
  LifecycleSkillInvocation,
  WorkflowRunLiveTelemetry,
} from "@/types/lifecycle";

interface OperatorConsoleProps {
  currentPhase: LifecyclePhase | null;
  artifacts: LifecycleArtifact[];
  decisions: LifecycleDecision[];
  skillInvocations: LifecycleSkillInvocation[];
  delegations: LifecycleDelegation[];
  phaseRuns: LifecyclePhaseRun[];
  research?: MarketResearch | null;
  liveTelemetry?: WorkflowRunLiveTelemetry | null;
  phaseSummary?: LifecyclePhaseRuntimeSummary | null;
  activePhaseSummary?: LifecyclePhaseRuntimeSummary | null;
  className?: string;
}

const PHASE_LABELS: Record<LifecyclePhase, string> = {
  research: "調査",
  planning: "企画",
  design: "デザイン",
  approval: "承認",
  development: "開発",
  deploy: "デプロイ",
  iterate: "改善",
};

const RESEARCH_NODE_LABELS: Record<string, string> = {
  "competitor-analyst": "競合分析",
  "market-researcher": "市場調査",
  "user-researcher": "ユーザー調査",
  "tech-evaluator": "技術評価",
  "research-synthesizer": "統合分析",
  "evidence-librarian": "根拠整理",
  "devils-advocate-researcher": "反証レビュー",
  "cross-examiner": "相互検証",
  "research-judge": "最終判定",
};

function phaseLabel(phase: LifecyclePhase): string {
  return PHASE_LABELS[phase] ?? phase;
}

function nodeLabel(nodeId: string): string {
  return RESEARCH_NODE_LABELS[nodeId] ?? nodeId;
}

function compactText(value: string, limit = 120): string {
  const text = value.replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trimEnd()}...`;
}

function formatCompactNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return `${value}`;
}

function formatRunCost(run: LifecyclePhaseRun | null | undefined): string {
  if (!run) return "未計測";
  if (run.costMeasured ?? false) {
    return `$${run.costUsd.toFixed(3)}`;
  }
  return "未計測";
}

function formatRunVolume(run: LifecyclePhaseRun | null | undefined): string {
  if (!run) return "不明";
  const totalTokens = run.meteredTokens ?? run.totalTokens ?? 0;
  if (totalTokens > 0) {
    return `${formatCompactNumber(totalTokens)} tokens`;
  }
  return "軽量実行";
}

function modeLabel(mode: string): string {
  const labels: Record<string, string> = {
    local: "ローカル",
    a2a: "A2A",
  };
  return labels[mode] ?? polishConsoleCopy(mode);
}

function skillLabel(skill: string): string {
  const labels: Record<string, string> = {
    "market-research": "市場調査",
    "competitive-intelligence": "競争分析",
    "market-sizing": "市場規模推定",
    "persona-research": "ペルソナ分析",
    "delivery-review": "進行レビュー",
    "quality-assurance": "品質確認",
    "quality-gating": "品質ゲート判定",
    "design-critique": "デザイン批評",
    "accessibility-review": "アクセシビリティ確認",
    "responsive-review": "レスポンシブ確認",
    "frontend-implementation": "フロントエンド実装",
    "security-review": "セキュリティ確認",
    "safety-review": "安全性確認",
  };
  return labels[skill] ?? polishConsoleCopy(skill.replaceAll("-", " "));
}

function delegationSummary(delegation: LifecycleDelegation): string {
  const metadata = delegation.task?.metadata && typeof delegation.task.metadata === "object"
    ? delegation.task.metadata as Record<string, unknown>
    : {};
  const reason = typeof metadata.reason === "string" ? metadata.reason : "";
  const peer = delegation.peer ? ` ${delegation.peer}` : "";
  if (reason) {
    return compactText(polishConsoleCopy(reason), 160);
  }
  if (delegation.skill) {
    return `${skillLabel(delegation.skill)} を${peer}に委譲`;
  }
  return peer ? `${peer} と連携` : "委譲を実行";
}

function polishConsoleCopy(value: string): string {
  return value
    .replace(/\s+/g, " ")
    .replace("外部 URL に grounded された evidence が不足しています。", "外部 URL の根拠が不足しています。")
    .replace("Phase outputs did not satisfy readiness checks.", "品質ゲートを満たせなかったため、見直しが必要です。")
    .replace(/critical research dissent/gi, "重大な反証")
    .replace(/critical research nodes/gi, "重要ノード")
    .replace(/support handoff/gi, "後続フェーズへの引き継ぎ")
    .replace(/requires rework/gi, "見直しが必要")
    .replace(/project brief/gi, "プロジェクト要約")
    .replace(/public web evidence/gi, "公開 Web 根拠")
    .replace(/mix vendor pages with neutral analyst or practitioner sources before finalizing claims\./gi, "主張を確定する前に、ベンダーページだけでなく第三者ソースも混ぜて根拠を厚くしてください。")
    .replace(/call out where the result is based on public web evidence versus the project brief\./gi, "公開 Web 根拠と project brief 由来の内容を明確に分けてください。")
    .replace(/prefer source diversity over adding more snippets from the same domain\./gi, "同じドメインの断片を増やすより、異なるソースの多様性を優先してください。")
    .replace(/reviewed (\d+) grounded sources for research\./gi, "調査のために接地済みソースを $1 件確認しました。")
    .replace(/research phase skill executed by /gi, "")
    .replace(/Delegate /g, "")
    .replace(/for lifecycle phase research on project [^.:]+\.?/gi, "")
    .replace(/for research\/[a-z-]+: /gi, "")
    .replace(/current cycle/gi, "現サイクル")
    .replace(/未解決の critical dissent が (\d+) 件残っています。/g, "未解決の重大な反証が $1 件残っています。")
    .replace(/confidence floor は ([0-9.]+)、winning thesis 数は (\d+) です。/g, "信頼度下限は $1、有力仮説数は $2 です。")
    .replace(/Research Judgement/g, "調査判定")
    .replace(/Research Cross Examination/g, "相互検証")
    .replace(/Claim Ledger/g, "主張台帳")
    .replace(/Research Dissent/g, "反証レビュー")
    .replace(/Research Report/g, "調査レポート")
    .replace(/Research Swarm requires rework/g, "調査結果の見直しが必要")
    .replace(/Downstream lifecycle outputs invalidated/g, "後続成果物を再生成")
    .replace(/Research execution inputs changed; regenerate research and all downstream artifacts\./g, "調査入力が変わったため、research と後続成果物を再生成します。")
    .replace(/lineage_reset/g, "系譜リセット")
    .replace(/phase_outcome/g, "フェーズ判定")
    .replace(/Completed/g, "完了")
    .replace(/Running/g, "実行中")
    .replace(/Failed/g, "失敗")
    .replace(/deterministic-reference/g, "内部参照")
    .replace(/competitive-intelligence/gi, "競争分析")
    .replace(/market-sizing/gi, "市場規模推定")
    .replace(/market-research/gi, "市場調査")
    .replace(/persona-research/gi, "ペルソナ分析")
    .replace(/local/gi, "ローカル")
    .replace(/task:/gi, "タスク:")
    .replace(/evidence/gi, "根拠")
    .replace(/dissent/gi, "反証")
    .replace(/thesis/gi, "仮説")
    .replace(/planning/gi, "企画")
    .replace(/grounded/gi, "紐づいた")
    .replace(/confidence floor/gi, "信頼度下限")
    .replace(/\s+\./g, ".")
    .trim();
}

function runStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: "完了",
    running: "実行中",
    failed: "失敗",
    pending: "待機",
  };
  return labels[status.toLowerCase()] ?? polishConsoleCopy(status);
}

function remediationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    not_needed: "不要",
    queued: "継続予定",
    retrying: "補完中",
    resolved: "解消",
    blocked: "上限到達",
  };
  return labels[status] ?? polishConsoleCopy(status);
}

function researchGateTitle(id: string, title: string): string {
  const labels: Record<string, string> = {
    "source-grounding": "採択主張が外部根拠に紐づいている",
    "critical-dissent-resolved": "重大な反証が未解決のまま残っていない",
    "confidence-floor": "企画に渡せる信頼度を満たしている",
  };
  return labels[id] ?? polishConsoleCopy(title);
}

function phaseStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    available: "開始可能",
    in_progress: "進行中",
    completed: "完了",
    locked: "未解放",
  };
  return labels[status] ?? polishConsoleCopy(status);
}

function agentRuntimeStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: "待機",
    running: "実行中",
    completed: "完了",
    failed: "失敗",
  };
  return labels[status] ?? polishConsoleCopy(status);
}

function artifactSummaryText(artifact: LifecycleArtifact): string {
  const payload = artifact.payload ?? {};
  if (artifact.title === "Research Judgement") {
    const theses = Array.isArray(payload.winning_theses) ? payload.winning_theses.length : 0;
    const gates = Array.isArray(payload.quality_gates) ? payload.quality_gates.length : 0;
    return `有力仮説 ${theses}件 / 品質ゲート ${gates}件`;
  }
  if (artifact.title === "Claim Ledger") {
    const evidence = Array.isArray(payload.evidence) ? payload.evidence.length : 0;
    const links = Array.isArray(payload.source_links) ? payload.source_links.length : 0;
    return `根拠 ${evidence}件 / 外部リンク ${links}件`;
  }
  if (artifact.title === "Research Dissent") {
    const dissent = Array.isArray(payload.dissent) ? payload.dissent.length : 0;
    const questions = Array.isArray(payload.open_questions) ? payload.open_questions.length : 0;
    return `反証 ${dissent}件 / 未解決の問い ${questions}件`;
  }
  if (artifact.title === "Research Report") {
    const claims = Array.isArray(payload.claims) ? payload.claims.length : 0;
    const competitors = Array.isArray(payload.competitors) ? payload.competitors.length : 0;
    return `主張 ${claims}件 / 競合 ${competitors}件`;
  }
  return compactText(polishConsoleCopy(artifact.summary), 140);
}

export function LifecycleOperatorConsole({
  currentPhase,
  artifacts: allArtifacts,
  decisions: allDecisions,
  skillInvocations: allSkills,
  delegations: allDelegations,
  phaseRuns,
  research,
  liveTelemetry,
  phaseSummary,
  activePhaseSummary,
  className,
}: OperatorConsoleProps) {
  const phase = currentPhase ?? "research";
  const displayedPhaseSummary = activePhaseSummary ?? phaseSummary ?? null;
  const livePhase = displayedPhaseSummary?.phase ?? phase;
  const artifacts = allArtifacts.filter((item) => item.phase === phase).slice(0, 5);
  const decisions = allDecisions.filter((item) => item.phase === phase).slice(0, 5);
  const skills = allSkills.filter((item) => item.phase === phase).slice(0, 6);
  const delegations = allDelegations.filter((item) => item.phase === phase).slice(0, 4);
  const phasePhaseRuns = phaseRuns.filter((item) => item.phase === phase);
  const phaseRun = phasePhaseRuns[0] ?? null;
  const measuredPhaseRun = phasePhaseRuns.find((item) => (item.totalTokens ?? 0) > 0 || item.costUsd > 0) ?? phaseRun;
  const hasTelemetry =
    phaseRun != null ||
    displayedPhaseSummary != null ||
    liveTelemetry?.run != null ||
    artifacts.length > 0 ||
    decisions.length > 0 ||
    skills.length > 0 ||
    delegations.length > 0;
  const failedResearchGates = phase === "research"
    ? (research?.quality_gates ?? []).filter((item) => item.passed !== true).slice(0, 3)
    : [];
  const degradedResearchNodes = phase === "research"
    ? (research?.node_results ?? []).filter((item) => item.status !== "success")
    : [];
  const unresolvedDissent = phase === "research"
    ? (research?.critical_dissent_count
      ?? (research?.dissent ?? []).filter((item) => !item.resolved && item.severity === "critical").length)
    : 0;
  const acceptedClaims = phase === "research"
    ? (research?.claims ?? []).filter((item) => item.status === "accepted").length
    : 0;
  const sourceCount = phase === "research"
    ? ((research?.source_links ?? []).length || (research?.evidence ?? []).length)
    : 0;
  const autonomousRemediation = phase === "research" ? research?.autonomous_remediation : undefined;
  const liveFocusNode = liveTelemetry?.activeFocusNodeId ? nodeLabel(liveTelemetry.activeFocusNodeId) : null;
  const recentLiveNodes = (liveTelemetry?.recentNodeIds ?? []).map(nodeLabel);
  const runtimeAgents = displayedPhaseSummary?.agents ?? [];
  const runtimeActions = displayedPhaseSummary?.recentActions ?? [];

  return (
    <aside className={cn("flex flex-col border-l border-border bg-card/40", className)}>
      <div className="border-b border-border px-4 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">運用パネル</p>
        <h2 className="mt-1 text-sm font-bold text-foreground">{phaseLabel(phase)}</h2>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <ConsoleSection title="実行サマリー">
          {phaseRun ? (
            <div className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-foreground">{phaseRun.runId.slice(0, 8)}</span>
                <Badge variant="outline" className="text-[10px]">{runStatusLabel(phaseRun.status)}</Badge>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                <span>成果物 {phaseRun.artifactCount}</span>
                <span>判断ログ {phaseRun.decisionCount}</span>
                <span>コスト {formatRunCost(measuredPhaseRun)}</span>
                <span>規模 {formatRunVolume(measuredPhaseRun)}</span>
                <span>{phaseRun.completedAt ? new Date(phaseRun.completedAt).toLocaleTimeString("ja-JP") : "実行中"}</span>
              </div>
              {measuredPhaseRun && measuredPhaseRun.runId !== phaseRun.runId && (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  参考値は直近の計測済み実行 {measuredPhaseRun.runId.slice(0, 8)} から表示しています。
                </p>
              )}
            </div>
          ) : (
            <EmptyLine text="まだ実行履歴はありません。" />
          )}
        </ConsoleSection>

        {liveTelemetry?.run && (
          <ConsoleSection title="ライブ実行">
            <div className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-foreground">{liveTelemetry.run.id.slice(0, 8)}</span>
                <Badge variant="outline" className="text-[10px]">{runStatusLabel(liveTelemetry.run.status)}</Badge>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                <span>イベント {liveTelemetry.eventCount}</span>
                <span>完了ノード {liveTelemetry.completedNodeCount}</span>
                <span>実行中 {liveTelemetry.runningNodeIds.length}</span>
                <span>失敗 {liveTelemetry.failedNodeIds.length}</span>
              </div>
              {liveTelemetry.phase && liveTelemetry.phase !== phase && (
                <p className="mt-2 text-muted-foreground">実行フェーズ: {phaseLabel(liveTelemetry.phase)}</p>
              )}
              {liveFocusNode && (
                <p className="mt-2 text-foreground">現在地: {liveFocusNode}</p>
              )}
              {liveTelemetry.runningNodeIds.length > 0 && (
                <p className="mt-2 text-muted-foreground">
                  実行中: {liveTelemetry.runningNodeIds.map(nodeLabel).join(" / ")}
                </p>
              )}
              {recentLiveNodes.length > 0 && (
                <p className="mt-1 text-muted-foreground">
                  直近の流れ: {recentLiveNodes.join(" → ")}
                </p>
              )}
              {liveTelemetry.lastAgent && (
                <p className="mt-1 text-muted-foreground">最新担当: {liveTelemetry.lastAgent}</p>
              )}
              {liveTelemetry.failedNodeIds.length > 0 && (
                <p className="mt-1 text-muted-foreground">
                  失敗: {liveTelemetry.failedNodeIds.map(nodeLabel).join(" / ")}
                </p>
              )}
              {liveTelemetry.lastEventSeq !== null && (
                <p className="mt-1 text-muted-foreground">最新イベント #{liveTelemetry.lastEventSeq}</p>
              )}
            </div>
          </ConsoleSection>
        )}

        {displayedPhaseSummary && (
          <ConsoleSection title="AIの現在地">
            <div className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{phaseLabel(displayedPhaseSummary.phase)}</span>
                <Badge variant="outline" className="text-[10px]">{phaseStatusLabel(displayedPhaseSummary.status)}</Badge>
              </div>
              {displayedPhaseSummary.phase !== phase && (
                <p className="mt-2 text-muted-foreground">
                  表示中は {phaseLabel(phase)}、AI がいま動かしているのは {phaseLabel(livePhase)} です。
                </p>
              )}
              {displayedPhaseSummary.objective && (
                <p className="mt-2 text-muted-foreground">{compactText(polishConsoleCopy(displayedPhaseSummary.objective), 170)}</p>
              )}
              {displayedPhaseSummary.nextAutomaticAction && (
                <p className="mt-1 text-muted-foreground">
                  次の自動処理: {compactText(polishConsoleCopy(displayedPhaseSummary.nextAutomaticAction), 170)}
                </p>
              )}
              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                {displayedPhaseSummary.readiness && <span>準備状態 {displayedPhaseSummary.readiness === "ready" ? "通過" : "要見直し"}</span>}
                {typeof displayedPhaseSummary.failedGateCount === "number" && <span>未達ゲート {displayedPhaseSummary.failedGateCount}</span>}
                {typeof displayedPhaseSummary.degradedNodeCount === "number" && <span>要再確認ノード {displayedPhaseSummary.degradedNodeCount}</span>}
                {typeof displayedPhaseSummary.attemptCount === "number" && typeof displayedPhaseSummary.maxAttempts === "number" && (
                  <span>自動補完 {displayedPhaseSummary.attemptCount}/{displayedPhaseSummary.maxAttempts}</span>
                )}
                {displayedPhaseSummary.canAutorun && <span>次の処理は自動で継続</span>}
              </div>
              {displayedPhaseSummary.blockingSummary.length > 0 && (
                <div className="mt-2 space-y-1 text-muted-foreground">
                  {displayedPhaseSummary.blockingSummary.slice(0, 3).map((item) => (
                    <p key={item}>• {compactText(polishConsoleCopy(item), 150)}</p>
                  ))}
                </div>
              )}
            </div>
          </ConsoleSection>
        )}

        {runtimeAgents.length > 0 && (
          <ConsoleSection title="担当エージェント">
            {runtimeAgents.map((agent) => (
              <div key={agent.agentId} className="rounded-lg border border-border bg-card p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{agent.label}</span>
                  <Badge variant="outline" className="text-[10px]">{agentRuntimeStatusLabel(agent.status)}</Badge>
                </div>
                <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(agent.role), 150)}</p>
                <p className="mt-2 text-foreground">{compactText(polishConsoleCopy(agent.currentTask), 170)}</p>
                {agent.delegatedTo && (
                  <p className="mt-1 text-muted-foreground">連携先: {agent.delegatedTo}</p>
                )}
                {agent.lastArtifactTitle && (
                  <p className="mt-1 text-muted-foreground">直近成果物: {polishConsoleCopy(agent.lastArtifactTitle)}</p>
                )}
              </div>
            ))}
          </ConsoleSection>
        )}

        {runtimeActions.length > 0 && (
          <ConsoleSection title="直近の自動処理">
            {runtimeActions.map((action) => (
              <div key={`${action.nodeId}:${action.summary}`} className="rounded-lg border border-border bg-card p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{action.label}</span>
                  <Badge variant="outline" className="text-[10px]">{agentRuntimeStatusLabel(action.status)}</Badge>
                </div>
                <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(action.summary), 170)}</p>
                {action.agentLabel && <p className="mt-1 text-muted-foreground">担当: {action.agentLabel}</p>}
                {action.nodeLabel && <p className="mt-1 text-muted-foreground">ノード: {action.nodeLabel}</p>}
              </div>
            ))}
          </ConsoleSection>
        )}

        {phase === "research" && research && (
          <>
            <ConsoleSection title="今回の判断材料">
              <div className="grid grid-cols-2 gap-2">
                <MetricCard label="準備状態" value={research.readiness === "ready" ? "通過" : "要見直し"} />
                <MetricCard label="外部根拠" value={`${sourceCount}件`} />
                <MetricCard label="採択主張" value={`${acceptedClaims}件`} />
                <MetricCard label="重大反証" value={`${unresolvedDissent}件`} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <MetricCard label="要再確認ノード" value={`${degradedResearchNodes.length}件`} />
                <MetricCard
                  label="有力仮説"
                  value={`${(research.winning_theses ?? []).length}件`}
                />
              </div>
            </ConsoleSection>

            <ConsoleSection title="いま止まっている理由">
              {failedResearchGates.length > 0 ? failedResearchGates.map((gate) => (
                <div key={gate.id} className="rounded-lg border border-border bg-card p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">{researchGateTitle(gate.id, gate.title)}</span>
                    <Badge variant="secondary" className="text-[10px]">未達</Badge>
                  </div>
                  <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(gate.reason), 140)}</p>
                  {gate.blockingNodeIds.length > 0 && (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      関連: {gate.blockingNodeIds.map(nodeLabel).join(" / ")}
                    </p>
                  )}
                </div>
              )) : (
                <EmptyLine text="現在、主要なブロッカーはありません。" />
              )}
            </ConsoleSection>

            {research.remediation_plan && (
              <ConsoleSection title="次にやること">
                <div className="rounded-lg border border-border bg-card p-3 text-xs">
                  <p className="font-medium text-foreground">{compactText(research.remediation_plan.objective, 160)}</p>
                  {research.remediation_plan.retryNodeIds.length > 0 && (
                    <p className="mt-2 text-muted-foreground">
                      再調査対象: {research.remediation_plan.retryNodeIds.map(nodeLabel).join(" / ")}
                    </p>
                  )}
                </div>
              </ConsoleSection>
            )}

            {autonomousRemediation && (
              <ConsoleSection title="AI 自動補完">
                <div className="rounded-lg border border-border bg-card p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">{remediationStatusLabel(autonomousRemediation.status)}</span>
                    <Badge variant={autonomousRemediation.status === "blocked" ? "secondary" : "outline"} className="text-[10px]">
                      {autonomousRemediation.attemptCount}/{autonomousRemediation.maxAttempts || 0}
                    </Badge>
                  </div>
                  {autonomousRemediation.objective && (
                    <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(autonomousRemediation.objective), 170)}</p>
                  )}
                  {autonomousRemediation.retryNodeIds.length > 0 && (
                    <p className="mt-2 text-muted-foreground">
                      補完対象: {autonomousRemediation.retryNodeIds.map(nodeLabel).join(" / ")}
                    </p>
                  )}
                  {autonomousRemediation.blockingSummary && autonomousRemediation.blockingSummary.length > 0 && (
                    <div className="mt-2 space-y-1 text-muted-foreground">
                      {autonomousRemediation.blockingSummary.slice(0, 3).map((item) => (
                        <p key={item}>• {compactText(polishConsoleCopy(item), 150)}</p>
                      ))}
                    </div>
                  )}
                  {autonomousRemediation.stopReason && (
                    <p className="mt-2 text-muted-foreground">
                      停止条件: {compactText(polishConsoleCopy(autonomousRemediation.stopReason), 150)}
                    </p>
                  )}
                </div>
              </ConsoleSection>
            )}
          </>
        )}

        {!hasTelemetry && (
          <EmptyLine text="このフェーズの運用テレメトリはまだありません。ワークフロー実行後に成果物、判断、委譲がここに集約されます。" />
        )}

        {artifacts.length > 0 && (
          <ConsoleSection title="主要成果物">
            {artifacts.map((artifact) => (
            <div key={artifact.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{polishConsoleCopy(artifact.title)}</span>
                <Badge variant="outline" className="text-[10px]">{polishConsoleCopy(artifact.kind)}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{artifactSummaryText(artifact)}</p>
              {artifact.skillIds.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {artifact.skillIds.slice(0, 3).map((skillId) => (
                    <Badge key={skillId} variant="secondary" className="text-[10px]">{skillId}</Badge>
                  ))}
                </div>
              )}
            </div>
            ))}
          </ConsoleSection>
        )}

        {decisions.length > 0 && (
          <ConsoleSection title="直近の判断">
            {decisions.map((decision) => (
            <div key={decision.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{polishConsoleCopy(decision.title)}</span>
                <Badge variant="outline" className="text-[10px]">{polishConsoleCopy(decision.kind)}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(decision.rationale), 180)}</p>
            </div>
            ))}
          </ConsoleSection>
        )}

        {skills.length > 0 && (
          <ConsoleSection title="使われたスキル">
            {skills.map((skill) => (
            <div key={skill.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{skillLabel(skill.skill)}</span>
                <Badge variant="outline" className="text-[10px]">{modeLabel(skill.mode)}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{skill.agentLabel}</p>
              <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(skill.summary), 150)}</p>
              {skill.delegatedTo && <p className="mt-1 text-primary">委譲先: {skill.delegatedTo}</p>}
            </div>
            ))}
          </ConsoleSection>
        )}

        {delegations.length > 0 && (
          <ConsoleSection title="エージェント間委譲">
            {delegations.map((delegation) => (
            <div key={delegation.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{delegation.peer}</span>
                <Badge variant="outline" className="text-[10px]">{skillLabel(delegation.skill)}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{nodeLabel(delegation.agentId)} {"→"} {delegation.peer}</p>
              <p className="mt-1 text-muted-foreground">{delegationSummary(delegation)}</p>
            </div>
            ))}
          </ConsoleSection>
        )}
      </div>
    </aside>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-1 font-medium text-foreground">{value}</p>
    </div>
  );
}

function ConsoleSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-border px-3 py-3 text-xs text-muted-foreground">{text}</div>;
}
