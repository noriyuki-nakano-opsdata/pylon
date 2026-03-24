import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import {
  formatAutonomousRemediationStatus,
  formatPhaseLabel,
  formatPhaseStatus,
  formatResearchGateTitle,
  formatResearchNodeLabel,
  formatRunStatus,
  polishConsoleCopy,
} from "@/lifecycle/presentation";
import { cn } from "@/lib/utils";
import type {
  LifecycleArtifact,
  LifecycleAutonomyState,
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
  autonomyState?: LifecycleAutonomyState | null;
  liveTelemetry?: WorkflowRunLiveTelemetry | null;
  phaseSummary?: LifecyclePhaseRuntimeSummary | null;
  activePhaseSummary?: LifecyclePhaseRuntimeSummary | null;
  className?: string;
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

function agentRuntimeStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: "待機",
    running: "実行中",
    completed: "完了",
    failed: "失敗",
  };
  return labels[status] ?? polishConsoleCopy(status);
}

function developmentMeshStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "待機",
    running: "進行中",
    completed: "完了",
    blocked: "要再実行",
    failed: "失敗",
  };
  return labels[status] ?? agentRuntimeStatusLabel(status);
}

function governanceModeLabel(mode?: string): string {
  return mode === "complete_autonomy" ? "complete autonomy" : "governed";
}

function executionPolicyLabel(policy: string): string {
  const labels: Record<string, string> = {
    auto_with_human_override: "自律実行 + 人の上書き",
    human_required: "人の判断必須",
    autonomous_work_unit_loops: "WU 自律ループ",
    auto_release_candidate_with_optional_hold: "自動 release + hold 可",
    auto_synthesis_with_human_prioritization: "自動合成 + 人の優先付け",
    continuous_autonomous_iteration: "継続自律 iteration",
  };
  return labels[policy] ?? polishConsoleCopy(policy.replaceAll("_", " "));
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
  autonomyState,
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
  const liveFocusNode = liveTelemetry?.activeFocusNodeId
    ? formatResearchNodeLabel(liveTelemetry.activeFocusNodeId)
    : null;
  const recentLiveNodes = (liveTelemetry?.recentNodeIds ?? []).map(formatResearchNodeLabel);
  const runtimeAgents = displayedPhaseSummary?.agents ?? [];
  const runtimeActions = displayedPhaseSummary?.recentActions ?? [];
  const runtimeWaves = displayedPhaseSummary?.executionWaves ?? [];
  const pendingHumanDecisions = autonomyState?.requiredHumanDecisions ?? [];
  const phasePolicy = autonomyState?.phasePolicies?.[phase];
  const runtimeWorkUnits = [...(displayedPhaseSummary?.workUnits ?? [])].sort((left, right) => {
    const statusRank = (status: string) => ({
      blocked: 0,
      failed: 1,
      running: 2,
      pending: 3,
      completed: 4,
    }[status] ?? 9);
    const leftWave = left.waveIndex ?? 0;
    const rightWave = right.waveIndex ?? 0;
    if (leftWave !== rightWave) return leftWave - rightWave;
    const leftStatus = statusRank(left.status);
    const rightStatus = statusRank(right.status);
    if (leftStatus !== rightStatus) return leftStatus - rightStatus;
    return left.title.localeCompare(right.title, "ja-JP");
  });

  return (
    <aside className={cn("flex flex-col border-l border-border bg-card/40", className)}>
      <div className="border-b border-border px-4 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">運用パネル</p>
        <h2 className="mt-1 text-sm font-bold text-foreground">{formatPhaseLabel(phase)}</h2>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <ConsoleSection title="実行サマリー">
          {phaseRun ? (
            <div className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-foreground">{phaseRun.runId.slice(0, 8)}</span>
                <Badge variant="outline" className="text-[10px]">{formatRunStatus(phaseRun.status)}</Badge>
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

        {autonomyState && (
          <ConsoleSection title="Governance">
            <div className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{governanceModeLabel(autonomyState.governanceMode)}</span>
                <Badge variant="outline" className="text-[10px]">
                  {autonomyState.orchestrationMode}
                </Badge>
              </div>
              {phasePolicy && (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  {executionPolicyLabel(phasePolicy.executionPolicy)} · {compactText(phasePolicy.summary, 120)}
                </p>
              )}
              <div className="mt-3 space-y-2">
                {pendingHumanDecisions.length > 0 ? pendingHumanDecisions.slice(0, 3).map((decision) => (
                  <div key={`${decision.phase}:${decision.decisionId}`} className="rounded-md border border-border/70 bg-background/80 px-2.5 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium text-foreground">{decision.title}</span>
                      <Badge variant="secondary" className="text-[10px]">{formatPhaseLabel(decision.phase)}</Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">{compactText(decision.reason, 120)}</p>
                  </div>
                )) : (
                  <EmptyLine text="現在、必須の human gate はありません。" />
                )}
              </div>
            </div>
          </ConsoleSection>
        )}

        {liveTelemetry?.run && (
          <ConsoleSection title="ライブ実行">
            <div className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-foreground">{liveTelemetry.run.id.slice(0, 8)}</span>
                <Badge variant="outline" className="text-[10px]">{formatRunStatus(liveTelemetry.run.status)}</Badge>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                <span>イベント {liveTelemetry.eventCount}</span>
                <span>完了ノード {liveTelemetry.completedNodeCount}</span>
                <span>実行中 {liveTelemetry.runningNodeIds.length}</span>
                <span>失敗 {liveTelemetry.failedNodeIds.length}</span>
              </div>
              {liveTelemetry.phase && liveTelemetry.phase !== phase && (
                <p className="mt-2 text-muted-foreground">実行フェーズ: {formatPhaseLabel(liveTelemetry.phase)}</p>
              )}
              {liveFocusNode && (
                <p className="mt-2 text-foreground">現在地: {liveFocusNode}</p>
              )}
              {liveTelemetry.runningNodeIds.length > 0 && (
                <p className="mt-2 text-muted-foreground">
                  実行中: {liveTelemetry.runningNodeIds.map(formatResearchNodeLabel).join(" / ")}
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
                  失敗: {liveTelemetry.failedNodeIds.map(formatResearchNodeLabel).join(" / ")}
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
                <span className="font-medium text-foreground">{formatPhaseLabel(displayedPhaseSummary.phase)}</span>
                <Badge variant="outline" className="text-[10px]">{formatPhaseStatus(displayedPhaseSummary.status)}</Badge>
              </div>
              {displayedPhaseSummary.phase !== phase && (
                <p className="mt-2 text-muted-foreground">
                  表示中は {formatPhaseLabel(phase)}、AI がいま動かしているのは {formatPhaseLabel(livePhase)} です。
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
                {phase === "development" && typeof displayedPhaseSummary.waveCount === "number" && (
                  <span>wave {displayedPhaseSummary.waveCount}件</span>
                )}
                {phase === "development" && typeof displayedPhaseSummary.workUnitCount === "number" && (
                  <span>WU {displayedPhaseSummary.workUnitCount}件</span>
                )}
                {phase === "development" && typeof displayedPhaseSummary.currentWaveIndex === "number" && (
                  <span>現在 wave {displayedPhaseSummary.currentWaveIndex + 1}</span>
                )}
                {phase === "development" && displayedPhaseSummary.topologyFresh === false && (
                  <span>topology 要再生成</span>
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
              {phase === "development" && (displayedPhaseSummary.retryNodeIds?.length ?? 0) > 0 && (
                <p className="mt-2 text-muted-foreground">
                  再試行ノード: {(displayedPhaseSummary.retryNodeIds ?? []).slice(0, 4).join(" / ")}
                </p>
              )}
              {phase === "development" && (displayedPhaseSummary.focusWorkUnitIds?.length ?? 0) > 0 && (
                <p className="mt-1 text-muted-foreground">
                  注力 WU: {(displayedPhaseSummary.focusWorkUnitIds ?? []).slice(0, 4).join(" / ")}
                </p>
              )}
            </div>
          </ConsoleSection>
        )}

        {phase === "development" && displayedPhaseSummary && (
          <ConsoleSection title="Delivery Mesh" defaultOpen>
            <div className="grid grid-cols-2 gap-2">
              {typeof displayedPhaseSummary.waveCount === "number" ? (
                <MetricCard
                  label="wave"
                  value={`${typeof displayedPhaseSummary.currentWaveIndex === "number" ? displayedPhaseSummary.currentWaveIndex + 1 : 0}/${displayedPhaseSummary.waveCount}`}
                />
              ) : null}
              {typeof displayedPhaseSummary.workUnitCount === "number" ? (
                <MetricCard label="work unit" value={`${displayedPhaseSummary.workUnitCount}件`} />
              ) : null}
              <MetricCard label="retry nodes" value={`${displayedPhaseSummary.retryNodeIds?.length ?? 0}件`} />
              <MetricCard label="focus WU" value={`${displayedPhaseSummary.focusWorkUnitIds?.length ?? 0}件`} />
            </div>
            {(displayedPhaseSummary.retryNodeIds?.length ?? 0) > 0 && (
              <div className="rounded-lg border border-border bg-card px-3 py-2 text-[11px] text-muted-foreground">
                再試行ノード: {(displayedPhaseSummary.retryNodeIds ?? []).slice(0, 4).join(" / ")}
              </div>
            )}
            {(displayedPhaseSummary.focusWorkUnitIds?.length ?? 0) > 0 && (
              <div className="rounded-lg border border-border bg-card px-3 py-2 text-[11px] text-muted-foreground">
                注力 WU: {(displayedPhaseSummary.focusWorkUnitIds ?? []).slice(0, 4).join(" / ")}
              </div>
            )}
          </ConsoleSection>
        )}

        {runtimeAgents.length > 0 && (
          <ConsoleSection title="担当エージェント" defaultOpen={phase !== "development"}>
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
          <ConsoleSection title="直近の自動処理" defaultOpen={phase !== "development"}>
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

        {phase === "development" && runtimeWaves.length > 0 && (
          <ConsoleSection title="Execution Waves" defaultOpen={false}>
            {runtimeWaves.map((wave) => (
              <div key={wave.waveIndex} className="rounded-lg border border-border bg-card p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-foreground">Wave {wave.waveIndex + 1}</span>
                  <Badge variant="outline" className="text-[10px]">{developmentMeshStatusLabel(wave.status)}</Badge>
                </div>
                <p className="mt-1 text-muted-foreground">
                  WU {wave.completedWorkUnitCount}/{wave.workUnitCount}
                  {wave.ready ? " / exit ready" : ""}
                </p>
                {wave.laneIds.length > 0 && (
                  <p className="mt-1 text-muted-foreground">担当 lane: {wave.laneIds.join(" / ")}</p>
                )}
                {wave.blockedWorkUnitIds.length > 0 && (
                  <p className="mt-1 text-muted-foreground">
                    ブロック中: {wave.blockedWorkUnitIds.slice(0, 3).join(" / ")}
                  </p>
                )}
                {wave.activeNodeIds.length > 0 && (
                  <p className="mt-1 text-muted-foreground">
                    稼働ノード: {wave.activeNodeIds.slice(0, 3).join(" / ")}
                  </p>
                )}
              </div>
            ))}
          </ConsoleSection>
        )}

        {phase === "development" && runtimeWorkUnits.length > 0 && (
          <ConsoleSection title="Work Unit 状態" defaultOpen={false}>
            {runtimeWorkUnits.slice(0, 8).map((workUnit) => (
              <div key={workUnit.id} className="rounded-lg border border-border bg-card p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{compactText(polishConsoleCopy(workUnit.title), 120)}</span>
                  <Badge variant="outline" className="text-[10px]">{developmentMeshStatusLabel(workUnit.status)}</Badge>
                </div>
                <p className="mt-1 text-muted-foreground">
                  Wave {workUnit.waveIndex + 1} / {polishConsoleCopy(workUnit.lane || "unassigned")}
                </p>
                {(workUnit.builderStatus || workUnit.qaStatus || workUnit.securityStatus) && (
                  <p className="mt-1 text-muted-foreground">
                    build {workUnit.builderStatus ?? "pending"} / qa {workUnit.qaStatus ?? "pending"} / security {workUnit.securityStatus ?? "pending"}
                  </p>
                )}
                {(workUnit.blockedBy?.length ?? 0) > 0 && (
                  <p className="mt-1 text-muted-foreground">
                    原因: {workUnit.blockedBy?.join(" / ")}
                  </p>
                )}
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
                    <span className="font-medium text-foreground">{formatResearchGateTitle(gate.id, gate.title)}</span>
                    <Badge variant="secondary" className="text-[10px]">未達</Badge>
                  </div>
                  <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(gate.reason), 140)}</p>
                  {gate.blockingNodeIds.length > 0 && (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      関連: {gate.blockingNodeIds.map(formatResearchNodeLabel).join(" / ")}
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
                      再調査対象: {research.remediation_plan.retryNodeIds.map(formatResearchNodeLabel).join(" / ")}
                    </p>
                  )}
                </div>
              </ConsoleSection>
            )}

            {autonomousRemediation && (
              <ConsoleSection title="AI 自動補完">
                <div className="rounded-lg border border-border bg-card p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">{formatAutonomousRemediationStatus(autonomousRemediation.status)}</span>
                    <Badge variant={autonomousRemediation.status === "blocked" ? "secondary" : "outline"} className="text-[10px]">
                      {autonomousRemediation.attemptCount}/{autonomousRemediation.maxAttempts || 0}
                    </Badge>
                  </div>
                  {autonomousRemediation.objective && (
                    <p className="mt-1 text-muted-foreground">{compactText(polishConsoleCopy(autonomousRemediation.objective), 170)}</p>
                  )}
                  {autonomousRemediation.retryNodeIds.length > 0 && (
                    <p className="mt-2 text-muted-foreground">
                      補完対象: {autonomousRemediation.retryNodeIds.map(formatResearchNodeLabel).join(" / ")}
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
          <ConsoleSection title="主要成果物" defaultOpen={phase !== "development"}>
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
          <ConsoleSection title="直近の判断" defaultOpen={phase !== "development"}>
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
          <ConsoleSection title="使われたスキル" defaultOpen={phase !== "development"}>
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
          <ConsoleSection title="エージェント間委譲" defaultOpen={phase !== "development"}>
            {delegations.map((delegation) => (
            <div key={delegation.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{delegation.peer}</span>
                <Badge variant="outline" className="text-[10px]">{skillLabel(delegation.skill)}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{formatResearchNodeLabel(delegation.agentId)} {"→"} {delegation.peer}</p>
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

function ConsoleSection({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="rounded-[1rem] border border-border/60 bg-card/30 px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
        <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          section
        </span>
      </summary>
      <div className="mt-3 space-y-2">
        {children}
      </div>
    </details>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-border px-3 py-3 text-xs text-muted-foreground">{text}</div>;
}
