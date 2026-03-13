import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Search, Check, ArrowRight, Globe, TrendingUp,
  ShieldAlert, Lightbulb, BarChart3, Zap, Plus, X, AlertCircle, Loader2,
  ChevronDown, ChevronUp, Route, Briefcase, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { lifecycleApi } from "@/api/lifecycle";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import {
  formatAutonomousRemediationStatus,
  formatClaimCategory,
  formatClaimStatus,
  formatDissentSeverity,
  formatNodeStatus,
  formatParseStatus,
  formatResearchDegradationReason,
  formatResearchGateTitle,
  formatResearchNodeLabel,
  formatSourceClassLabel,
  polishResearchCopy,
} from "@/lifecycle/presentation";
import {
  selectPhaseStatus,
  selectResearchProgressState,
  selectResearchReadinessState,
  selectResearchRuntimeSummary,
  selectResearchRuntimeTelemetry,
} from "@/lifecycle/selectors";
import {
  buildResearchProjectPatch,
  buildResearchWorkflowInput,
} from "@/lifecycle/inputs";
import type {
  MarketResearch,
  ResearchNodeResult,
  ResearchQualityGateResult,
  WorkflowRunLiveEvent,
} from "@/types/lifecycle";

const RESEARCH_AGENTS = [
  { id: "competitor-analyst", label: "競合分析" },
  { id: "market-researcher", label: "市場調査" },
  { id: "user-researcher", label: "ユーザー調査" },
  { id: "tech-evaluator", label: "技術評価" },
  { id: "research-synthesizer", label: "統合分析" },
];

const STRUCTURED_TEXT_KEYS = [
  "question",
  "statement",
  "thesis",
  "claim_statement",
  "core_claim",
  "primary",
  "signal",
  "pain_point",
  "segment",
  "summary",
  "title",
  "name",
  "text",
  "draft",
  "argument",
  "recommendation",
  "rationale",
  "target",
  "notes",
] as const;

function formatCompetitorHost(raw: string): string {
  try {
    return new URL(raw).hostname || raw;
  } catch {
    return raw;
  }
}

function buildResearchFallback(): MarketResearch {
  return {
    competitors: [],
    market_size: "調査結果を取得できませんでした",
    trends: [],
    opportunities: [],
    threats: [],
    tech_feasibility: {
      score: 0,
      notes: "データが不完全なため、調査結果を再取得してください。",
    },
    claims: [],
    evidence: [],
    dissent: [],
    open_questions: [],
    winning_theses: [],
    confidence_summary: {
      average: 0,
      floor: 0,
      accepted: 0,
    },
    source_links: [],
    user_research: undefined,
    judge_summary: undefined,
    autonomous_remediation: undefined,
  };
}

function truncateText(value: string, limit = 220): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) return normalized;
  const clipped = normalized.slice(0, limit).trimEnd();
  return `${clipped}...`;
}

function parseStructuredString(raw: string): unknown {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    // Legacy payloads sometimes persisted Python-style dict strings.
  }
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return trimmed;
  const keyedValues = STRUCTURED_TEXT_KEYS.flatMap((key) => {
    const pattern = new RegExp(`['"]${key}['"]\\s*:\\s*['"]([^'"]+)['"]`, "g");
    return Array.from(trimmed.matchAll(pattern), (match) => match[1]?.trim() ?? "").filter(Boolean);
  });
  if (keyedValues.length > 0) return keyedValues;
  const quoted = Array.from(trimmed.matchAll(/['"]([^'"]+)['"]/g), (match) => match[1]?.trim() ?? "")
    .filter((value) => value && !STRUCTURED_TEXT_KEYS.includes(value as typeof STRUCTURED_TEXT_KEYS[number]));
  return quoted.length > 0 ? quoted : trimmed;
}

function extractStructuredText(value: unknown, limit = 6): string[] {
  const results: string[] = [];

  const visit = (current: unknown) => {
    if (results.length >= limit || current == null) return;
    if (Array.isArray(current)) {
      current.forEach(visit);
      return;
    }
    if (typeof current === "object") {
      const record = current as Record<string, unknown>;
      const preferred = STRUCTURED_TEXT_KEYS.flatMap((key) => extractStructuredText(record[key], 1));
      if (preferred.length > 0) {
        preferred.forEach((item) => {
          if (results.length < limit && !results.includes(item)) results.push(item);
        });
        return;
      }
      Object.values(record).forEach(visit);
      return;
    }
    if (typeof current === "string") {
      const parsed = parseStructuredString(current);
      if (parsed !== current) {
        visit(parsed);
        return;
      }
      const trimmed = current.trim();
      if (trimmed && !results.includes(trimmed)) results.push(trimmed);
      return;
    }
    if (typeof current === "number") {
      const text = String(current);
      if (!results.includes(text)) results.push(text);
    }
  };

  visit(value);
  return results.slice(0, limit);
}

function normalizeTextList(value: unknown, limit = 3, charLimit = 180): string[] {
  return extractStructuredText(value, limit)
    .map((item) => truncateText(item, charLimit))
    .filter(Boolean)
    .slice(0, limit);
}

function normalizeTextValue(value: unknown, fallback = "", charLimit = 180): string {
  const [first] = normalizeTextList(value, 1, charLimit);
  return first ?? fallback;
}

function normalizeCopyList(value: unknown, limit = 3, charLimit = 180): string[] {
  return extractStructuredText(value, limit)
    .map((item) => polishResearchCopy(item))
    .map((item) => truncateText(item, charLimit))
    .filter(Boolean)
    .slice(0, limit);
}

function normalizeCopyValue(value: unknown, fallback = "", charLimit = 180): string {
  const [first] = normalizeCopyList(value, 1, charLimit);
  return first ?? fallback;
}

function formatRuntimeConnectionState(
  state: "inactive" | "connecting" | "live" | "reconnecting",
): string {
  if (state === "live") return "ライブ接続";
  if (state === "reconnecting") return "再接続中";
  if (state === "connecting") return "接続中";
  return "ライブ停止";
}

function formatElapsedCompact(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) return `${minutes}分 ${seconds}秒`;
  return `${seconds}秒`;
}

function formatRuntimeAgentStatus(status: "idle" | "running" | "completed" | "failed"): string {
  if (status === "running") return "実行中";
  if (status === "completed") return "完了";
  if (status === "failed") return "失敗";
  return "待機";
}

function formatLiveEventTimestamp(value?: string): string {
  if (!value) return "たった今";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "たった今";
  return parsed.toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatLiveEventStatus(status: WorkflowRunLiveEvent["status"]): string {
  if (status === "running") return "進行中";
  if (status === "failed") return "失敗";
  if (status === "completed") return "完了";
  return "待機";
}

function resolveResearchPayload(value: unknown): unknown {
  if (!value || typeof value !== "object") return value;
  const research = value as Record<string, unknown>;
  if (research.view_model && typeof research.view_model === "object") {
    return research.view_model;
  }
  return value;
}

function hasResearchContent(value: unknown): boolean {
  const resolved = resolveResearchPayload(value);
  if (!resolved || typeof resolved !== "object") return false;
  const research = resolved as Record<string, unknown>;
  return [
    research.market_size,
    research.user_research,
    ...(Array.isArray(research.competitors) ? research.competitors : []),
    ...(Array.isArray(research.trends) ? research.trends : []),
    ...(Array.isArray(research.opportunities) ? research.opportunities : []),
    ...(Array.isArray(research.threats) ? research.threats : []),
    ...(Array.isArray(research.claims) ? research.claims : []),
    ...(Array.isArray(research.evidence) ? research.evidence : []),
    ...(Array.isArray(research.winning_theses) ? research.winning_theses : []),
    ...(Array.isArray(research.source_links) ? research.source_links : []),
  ].some((item) => {
    if (typeof item === "string") return item.trim().length > 0;
    return Boolean(item);
  });
}

function normalizeResearch(value: unknown): MarketResearch {
  const fallback = buildResearchFallback();
  const fallbackConfidence = fallback.confidence_summary ?? {
    average: 0,
    floor: 0,
    accepted: 0,
  };
  const resolved = resolveResearchPayload(value);
  const research = resolved && typeof resolved === "object"
    ? resolved as Record<string, unknown>
    : {};
  const technical = research.tech_feasibility && typeof research.tech_feasibility === "object"
    ? research.tech_feasibility as Record<string, unknown>
    : {};
  const confidence = research.confidence_summary && typeof research.confidence_summary === "object"
    ? research.confidence_summary as Record<string, unknown>
    : {};
  const userResearch = research.user_research && typeof research.user_research === "object"
    ? research.user_research as Record<string, unknown>
    : null;
  return {
    ...fallback,
    ...research,
    competitors: Array.isArray(research.competitors)
      ? research.competitors.reduce<MarketResearch["competitors"]>((items, entry) => {
          if (!entry || typeof entry !== "object") return items;
          const competitor = entry as Record<string, unknown>;
          const name = normalizeTextValue(competitor.name, "", 64);
          if (!name) return items;
          items.push({
            name,
            url: typeof competitor.url === "string" ? competitor.url : undefined,
            strengths: normalizeCopyList(competitor.strengths, 2, 150),
            weaknesses: normalizeCopyList(competitor.weaknesses, 2, 150),
            pricing: normalizeCopyValue(competitor.pricing, "非公開", 80),
            target: normalizeCopyValue(competitor.target, "", 80),
          });
          return items;
        }, [])
      : fallback.competitors,
    market_size: typeof research.market_size === "string" && research.market_size.trim()
      ? polishResearchCopy(research.market_size)
      : fallback.market_size,
    trends: normalizeCopyList(research.trends, 3),
    opportunities: normalizeCopyList(research.opportunities, 3),
    threats: normalizeCopyList(research.threats, 3),
    tech_feasibility: {
      score: typeof technical.score === "number" ? technical.score : fallback.tech_feasibility.score,
      notes: normalizeCopyValue(technical.notes, fallback.tech_feasibility.notes, 280)
        ? normalizeCopyValue(technical.notes, fallback.tech_feasibility.notes, 280)
        : fallback.tech_feasibility.notes,
    },
    claims: Array.isArray(research.claims)
      ? research.claims
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const claim = item as Record<string, unknown>;
          const id = normalizeTextValue(claim.id, "", 64);
          const statement = normalizeCopyValue(claim.statement, "", 220);
          if (!id || !statement) return null;
          return {
            id,
            statement,
            owner: normalizeTextValue(claim.owner, "research", 64),
            category: normalizeTextValue(claim.category, "research", 48),
            evidence_ids: Array.isArray(claim.evidence_ids) ? claim.evidence_ids.filter((entry): entry is string => typeof entry === "string") : [],
            counterevidence_ids: Array.isArray(claim.counterevidence_ids) ? claim.counterevidence_ids.filter((entry): entry is string => typeof entry === "string") : [],
            confidence: typeof claim.confidence === "number" ? claim.confidence : 0,
            status: normalizeTextValue(claim.status, "contested", 24),
          };
        })
        .filter((item): item is NonNullable<MarketResearch["claims"]>[number] => Boolean(item))
      : fallback.claims,
    evidence: Array.isArray(research.evidence) ? research.evidence : fallback.evidence,
    dissent: Array.isArray(research.dissent)
      ? research.dissent.reduce<NonNullable<MarketResearch["dissent"]>>((items, entry) => {
          if (!entry || typeof entry !== "object") return items;
          const dissent = entry as Record<string, unknown>;
          const id = normalizeTextValue(dissent.id, "", 64);
          const claimId = normalizeTextValue(dissent.claim_id, "", 64);
          const argument = normalizeCopyValue(dissent.argument, "", 220);
          if (!id || !claimId || !argument) return items;
          items.push({
            id,
            claim_id: claimId,
            challenger: normalizeTextValue(dissent.challenger, "reviewer", 64),
            argument,
            severity: normalizeTextValue(dissent.severity, "medium", 24),
            resolved: dissent.resolved === true,
            recommended_test: normalizeCopyValue(dissent.recommended_test, "", 220) || undefined,
            resolution: normalizeCopyValue(dissent.resolution, "", 220) || undefined,
          });
          return items;
        }, [])
      : fallback.dissent,
    open_questions: normalizeCopyList(research.open_questions, 8, 220),
    winning_theses: normalizeCopyList(research.winning_theses, 3, 220),
    confidence_summary: {
      average: typeof confidence.average === "number" ? confidence.average : fallbackConfidence.average,
      floor: typeof confidence.floor === "number" ? confidence.floor : fallbackConfidence.floor,
      accepted: typeof confidence.accepted === "number" ? confidence.accepted : fallbackConfidence.accepted,
    },
    source_links: Array.isArray(research.source_links)
      ? research.source_links.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : fallback.source_links,
    user_research: userResearch
      ? {
          signals: normalizeCopyList(userResearch.signals, 3, 220),
          pain_points: normalizeCopyList(userResearch.pain_points, 3, 220),
          segment: normalizeCopyValue(userResearch.segment, "", 80),
        }
      : undefined,
    judge_summary: normalizeCopyValue(research.judge_summary, "", 280) || undefined,
    critical_dissent_count: typeof research.critical_dissent_count === "number" ? research.critical_dissent_count : undefined,
    resolved_dissent_count: typeof research.resolved_dissent_count === "number" ? research.resolved_dissent_count : undefined,
    node_results: Array.isArray(research.node_results)
      ? research.node_results.reduce<ResearchNodeResult[]>((items, entry) => {
          if (!entry || typeof entry !== "object") return items;
          const node = entry as Record<string, unknown>;
          const nodeId = normalizeTextValue(node.nodeId, "", 64);
          if (!nodeId) return items;
          items.push({
            nodeId,
            status: (normalizeTextValue(node.status, "degraded", 24) as ResearchNodeResult["status"]),
            parseStatus: (normalizeTextValue(node.parseStatus, "fallback", 24) as ResearchNodeResult["parseStatus"]),
            degradationReasons: normalizeTextList(node.degradationReasons, 6, 220),
            sourceClassesSatisfied: normalizeTextList(node.sourceClassesSatisfied, 6, 80),
            missingSourceClasses: normalizeTextList(node.missingSourceClasses, 6, 80),
            artifact: node.artifact && typeof node.artifact === "object" ? node.artifact as Record<string, unknown> : {},
            rawPreview: normalizeTextValue(node.rawPreview, "", 400) || undefined,
            llmModel: normalizeTextValue(node.llmModel, "", 80) || undefined,
            llmProvider: normalizeTextValue(node.llmProvider, "", 80) || undefined,
            retryCount: typeof node.retryCount === "number" ? node.retryCount : 0,
          });
          return items;
        }, [])
      : undefined,
    quality_gates: Array.isArray(research.quality_gates)
      ? research.quality_gates.reduce<ResearchQualityGateResult[]>((items, entry) => {
          if (!entry || typeof entry !== "object") return items;
          const gate = entry as Record<string, unknown>;
          const id = normalizeTextValue(gate.id, "", 64);
          const title = normalizeTextValue(gate.title, "", 120);
          if (!id || !title) return items;
          items.push({
            id,
            title,
            passed: gate.passed === true,
            reason: normalizeCopyValue(gate.reason, "", 220),
            blockingNodeIds: normalizeTextList(gate.blockingNodeIds, 6, 80),
          });
          return items;
        }, [])
      : undefined,
    readiness: (normalizeTextValue(research.readiness, "", 24) as MarketResearch["readiness"]) || undefined,
    remediation_plan: research.remediation_plan && typeof research.remediation_plan === "object"
      ? {
          objective: normalizeTextValue((research.remediation_plan as Record<string, unknown>).objective, "", 220),
          retryNodeIds: normalizeTextList((research.remediation_plan as Record<string, unknown>).retryNodeIds, 6, 80),
          maxIterations: typeof (research.remediation_plan as Record<string, unknown>).maxIterations === "number"
            ? (research.remediation_plan as Record<string, unknown>).maxIterations as number
            : 0,
        }
      : undefined,
    autonomous_remediation: research.autonomous_remediation && typeof research.autonomous_remediation === "object"
      ? {
          status: (normalizeTextValue(
            (research.autonomous_remediation as Record<string, unknown>).status,
            "not_needed",
            24,
          ) as NonNullable<MarketResearch["autonomous_remediation"]>["status"]),
          attemptCount: typeof (research.autonomous_remediation as Record<string, unknown>).attemptCount === "number"
            ? (research.autonomous_remediation as Record<string, unknown>).attemptCount as number
            : 0,
          maxAttempts: typeof (research.autonomous_remediation as Record<string, unknown>).maxAttempts === "number"
            ? (research.autonomous_remediation as Record<string, unknown>).maxAttempts as number
            : 0,
          remainingAttempts: typeof (research.autonomous_remediation as Record<string, unknown>).remainingAttempts === "number"
            ? (research.autonomous_remediation as Record<string, unknown>).remainingAttempts as number
            : 0,
          autoRunnable: (research.autonomous_remediation as Record<string, unknown>).autoRunnable === true,
          objective: normalizeCopyValue((research.autonomous_remediation as Record<string, unknown>).objective, "", 220),
          retryNodeIds: normalizeTextList((research.autonomous_remediation as Record<string, unknown>).retryNodeIds, 6, 80),
          blockingGateIds: normalizeTextList((research.autonomous_remediation as Record<string, unknown>).blockingGateIds, 6, 80),
          blockingNodeIds: normalizeTextList((research.autonomous_remediation as Record<string, unknown>).blockingNodeIds, 6, 80),
          missingSourceClasses: normalizeTextList((research.autonomous_remediation as Record<string, unknown>).missingSourceClasses, 8, 80),
          blockingSummary: normalizeCopyList((research.autonomous_remediation as Record<string, unknown>).blockingSummary, 4, 180),
          stopReason: normalizeCopyValue((research.autonomous_remediation as Record<string, unknown>).stopReason, "", 180) || undefined,
        }
      : undefined,
  };
}

export function ResearchPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const workflow = useWorkflowRun("research", projectSlug ?? "");
  const researchAgents = lc.blueprints.research.team.length > 0
    ? lc.blueprints.research.team.map((agent) => ({ id: agent.id, label: agent.label }))
    : RESEARCH_AGENTS;
  const [newUrl, setNewUrl] = useState("");
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [liveNow, setLiveNow] = useState(() => Date.now());
  const syncedRunRef = useRef<string | null>(null);
  const competitorUrls = lc.researchConfig.competitorUrls;
  const depth = lc.researchConfig.depth;
  const outputLanguage = lc.researchConfig.outputLanguage ?? "ja";

  useEffect(() => {
    if (competitorUrls.length > 0 || depth !== "standard") {
      setShowAdvanced(true);
    }
  }, [competitorUrls.length, depth]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setLiveNow(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if ((workflow.status !== "completed" && workflow.status !== "failed") || !workflow.runId || !projectSlug) return;
    if (syncedRunRef.current === workflow.runId) return;
    syncedRunRef.current = workflow.runId;
    void lifecycleApi.syncPhaseRun(projectSlug, "research", workflow.runId).then(({ project }) => {
      actions.applyProject(project);
    });
  }, [actions, workflow.runId, workflow.status, projectSlug]);

  const runResearch = async () => {
    if (!lc.spec.trim() || !projectSlug) return;
    setLaunchError(null);
    setIsPreparing(true);
    const researchConfig = {
      competitorUrls,
      depth,
      outputLanguage,
    };
    try {
      const response = await lifecycleApi.saveProject(
        projectSlug,
        buildResearchProjectPatch(lc, researchConfig),
        { autoRun: false },
      );
      actions.applyProject(response.project);
      actions.advancePhase("research");
      workflow.start(buildResearchWorkflowInput(lc, researchConfig));
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : "調査の開始に失敗しました");
    } finally {
      setIsPreparing(false);
    }
  };

  const addUrl = () => {
    const trimmed = newUrl.trim();
    if (!trimmed) return;
    const normalized = trimmed.toLowerCase();
    const isDuplicate = competitorUrls.some(
      (url) => url.trim().toLowerCase() === normalized,
    );
    if (isDuplicate) {
      setNewUrl("");
      return;
    }
    actions.updateResearchConfig({
      ...lc.researchConfig,
      competitorUrls: [...competitorUrls, trimmed],
    });
    setNewUrl("");
  };

  const goNext = () => {
    if (!researchReady) return;
    actions.completePhase("research");
    navigate(`/p/${projectSlug}/lifecycle/planning`);
  };

  const hasStoredResearch = hasResearchContent(lc.research);
  const research = hasStoredResearch ? normalizeResearch(lc.research) : null;
  const completionGapMessage =
    workflow.status === "completed" && !research
      ? "調査 run は完了しましたが、保存済みの調査結果を読み込めませんでした。再同期または再実行が必要です。"
      : null;
  const errorMessage =
    launchError
    ?? (workflow.status === "failed" ? workflow.error : null)
    ?? completionGapMessage;
  const researchPhaseStatus = selectPhaseStatus(lc.phaseStatuses, "research");
  const runtimeResearchSummary = selectResearchRuntimeSummary(lc);
  const runtimeResearchTelemetry = selectResearchRuntimeTelemetry(lc);
  const {
    runtimeElapsedMs: runtimeResearchElapsedMs,
    runtimeRunningNodes,
    runtimeRecentNodes,
    runtimeRecentEvents,
    runtimeRecentActions,
    runtimeAgentCards,
    isRunning,
    isResearchRunLive,
    isInitialResearchRun: shouldShowInitialResearchRun,
    visibleProgress,
    totalSteps: runtimeTotalSteps,
    completedSteps: runtimeCompletedSteps,
    progressPercent: runtimeProgressPercent,
  } = selectResearchProgressState({
    workflow,
    runtimeSummary: runtimeResearchSummary,
    runtimeTelemetry: runtimeResearchTelemetry,
    isPreparing,
    nowMs: liveNow,
  });

  const r = research ?? buildResearchFallback();
  const {
    researchReady,
    confidenceFloor,
    criticalDissentCount,
    autonomousRemediation,
    isAutonomousRecoveryActive,
    gateIssues: researchGateIssues,
    warning: researchWarning,
  } = selectResearchReadinessState({
    research,
    phaseStatus: researchPhaseStatus,
    nextAction: lc.nextAction,
  });
  const researchWarningTitle = isAutonomousRecoveryActive
    ? "AI が不足している根拠を自動補完しています"
    : "追加調査または見直しが必要です";
  const researchWarningDescription = isAutonomousRecoveryActive
    ? autonomousRemediation?.objective || "不足している根拠、品質ゲート、未達ノードを順に補い、企画へ渡せる状態まで自律的に再調査します。"
    : researchWarning;

  // Input state
  const isResearchRefreshRunning = !!research && (isRunning || isResearchRunLive);

  if (!research && !shouldShowInitialResearchRun) {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-6 py-4">
          <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
            <Search className="h-5 w-5 text-primary" />
            調査の開始
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            ここで必要なのは brief だけです。競合 URL や深度は任意で追加し、planning に渡す前提を固めます。
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto grid max-w-5xl gap-6 xl:grid-cols-[minmax(0,1.15fr)_0.85fr]">
            <div className="space-y-6 rounded-2xl border border-border bg-card p-5">
              {errorMessage && (
                <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                  <p className="font-medium">前回の research は失敗しました。</p>
                  <p className="mt-1">{errorMessage}</p>
                </div>
              )}
              <div className="rounded-xl border border-primary/15 bg-primary/5 p-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-primary/10 p-2 text-primary">
                    <Sparkles className="h-4 w-4" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-foreground">最初に必要なのは brief だけです。</p>
                    <p className="text-sm text-muted-foreground">
                      競合 URL や調査深度は任意です。planning に必要な前提を research で固めてから次へ渡します。
                    </p>
                  </div>
                </div>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-medium text-foreground">プロダクト概要</label>
                <p className="mb-3 text-xs text-muted-foreground">
                  誰のどんな課題をどう解決したいかを 3-5 文で書いてください。後で planning の判断材料になります。
                </p>
                <textarea
                  value={lc.spec}
                  onChange={(e) => actions.editSpec(e.target.value)}
                  placeholder="例: タスク整理が苦手なチーム向けに、優先度と進捗を可視化する ToDo ツールを作りたい。複数人での進行管理と振り返りを簡単にしたい。"
                  rows={6}
                  className="w-full rounded-lg border border-border bg-background p-4 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  autoFocus
                />
              </div>

              <div className="rounded-xl border border-border bg-background p-4">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((value) => !value)}
                  className="flex w-full items-center justify-between gap-3 text-left"
                >
                  <div>
                    <p className="text-sm font-medium text-foreground">調査条件を追加する</p>
                    <p className="text-xs text-muted-foreground">
                      任意。競合 URL と調査深度を指定したいときだけ開いてください。
                    </p>
                  </div>
                  {showAdvanced ? (
                    <ChevronUp className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  )}
                </button>

                {showAdvanced && (
                  <div className="mt-4 space-y-4">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-foreground">競合 URL</label>
                      <div className="flex gap-2">
                        <input
                          value={newUrl}
                          onChange={(e) => setNewUrl(e.target.value)}
                          placeholder="https://competitor.com"
                          className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                          onKeyDown={(e) => e.key === "Enter" && addUrl()}
                        />
                        <button onClick={addUrl} className="rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                          <Plus className="h-4 w-4" />
                        </button>
                      </div>
                      {competitorUrls.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {competitorUrls.map((url, i) => (
                            <Badge key={i} variant="secondary" className="gap-1 pr-1">
                              <Globe className="h-3 w-3" />{formatCompetitorHost(url)}
                              <button
                                onClick={() => actions.updateResearchConfig({
                                  ...lc.researchConfig,
                                  competitorUrls: competitorUrls.filter((_, j) => j !== i),
                                })}
                                className="ml-0.5 rounded-full hover:bg-foreground/10 p-0.5"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>

                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-foreground">調査深度</label>
                      <div className="grid gap-2 sm:grid-cols-3">
                          {([["quick", "簡易", "競合 2-3 社の基本分析"], ["standard", "標準", "競合 + 市場 + 技術評価"], ["deep", "詳細", "包括的な機会 / 脅威整理と提言"]] as const).map(([val, label, desc]) => (
                          <button
                            key={val}
                            onClick={() => actions.updateResearchConfig({ ...lc.researchConfig, depth: val })}
                            className={cn(
                              "rounded-lg border p-3 text-left transition-colors",
                              depth === val ? "border-primary bg-primary/5" : "border-border hover:bg-accent/50",
                            )}
                          >
                            <p className="text-sm font-medium text-foreground">{label}</p>
                            <p className="text-[11px] text-muted-foreground">{desc}</p>
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <Button
                onClick={() => void runResearch()}
                disabled={!lc.spec.trim() || isPreparing}
                className="w-full gap-2"
                size="lg"
              >
                <Search className="h-4 w-4" />
                この内容で調査を開始
              </Button>
            </div>

            <div className="space-y-4">
              <div className="rounded-2xl border border-border bg-card p-5">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground/70">調査で揃うもの</p>
                <div className="mt-4 space-y-3">
                  {[
                    "市場と競合の概況",
                    "ユーザー課題の仮説",
                    "技術実現性とリスク",
                    "企画に渡す有力仮説",
                  ].map((item) => (
                    <div key={item} className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
                      <Search className="h-3.5 w-3.5 text-primary" />
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-border bg-card p-5">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground/70">企画で生成される分析</p>
                <div className="mt-4 space-y-3">
                  {[
                    { label: "ユーザージャーニー", icon: Route },
                    { label: "ユーザーストーリー", icon: Lightbulb },
                    { label: "ジョブストーリー / JTBD", icon: Briefcase },
                    { label: "KANO 分析", icon: BarChart3 },
                  ].map((item) => (
                    <div key={item.label} className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
                      <item.icon className="h-3.5 w-3.5 text-primary" />
                      <span>{item.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Running state
  if (shouldShowInitialResearchRun) {
    const progress = visibleProgress.length > 0
      ? visibleProgress
      : researchAgents.map((agent) => ({
        nodeId: agent.id,
        agent: agent.label,
        status: "running" as const,
      }));
    return (
      <AgentProgressView
        agents={researchAgents}
        progress={progress}
        elapsedMs={workflow.elapsedMs}
        title="調査を実行中..."
        subtitle="市場、競合、ユーザー、技術の前提を整理し、企画に渡す根拠を組み立てています"
      />
    );
  }

  // Results
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col gap-3 border-b border-border px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
          {researchReady ? <Check className="h-5 w-5 text-success" /> : <AlertCircle className="h-5 w-5 text-amber-500" />}
          調査結果
        </h1>
        <button
          onClick={goNext}
          disabled={!researchReady}
          className={cn(
            "flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            researchReady
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "cursor-not-allowed bg-muted text-muted-foreground",
          )}
        >
          企画へ進む <ArrowRight className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-5xl space-y-6">
          {errorMessage && (
            <div className="flex flex-col gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-destructive sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold">前回の research は失敗しました。</p>
                  <p className="mt-1 text-sm">{errorMessage}</p>
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => void runResearch()}
                disabled={isPreparing || workflow.status === "running" || workflow.status === "starting"}
                className="border-destructive/30 bg-white text-destructive hover:bg-destructive/10"
              >
                調査を再実行
              </Button>
            </div>
          )}
          {researchWarning && (
            <div className={cn(
              "flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:items-center sm:justify-between",
              isAutonomousRecoveryActive
                ? "border border-primary/25 bg-primary/5 text-primary"
                : "border border-amber-300 bg-amber-50 text-amber-950",
            )}>
              <div className="flex items-start gap-3">
                {isAutonomousRecoveryActive
                  ? <Sparkles className="mt-0.5 h-5 w-5 shrink-0" />
                  : <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />}
                <div>
                  <p className="text-sm font-semibold">{researchWarningTitle}</p>
                  <p className="mt-1 text-sm">{researchWarningDescription}</p>
                  {autonomousRemediation && (
                    <p className="mt-2 text-xs opacity-90">
                      状態: {formatAutonomousRemediationStatus(autonomousRemediation.status)}
                      {autonomousRemediation.maxAttempts > 0
                        ? ` · 自動補完 ${autonomousRemediation.attemptCount}/${autonomousRemediation.maxAttempts} 回`
                        : ""}
                    </p>
                  )}
                  {researchGateIssues.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {researchGateIssues.map((issue) => (
                        <p
                          key={issue}
                          className={cn(
                            "text-xs",
                            isAutonomousRecoveryActive ? "text-primary/90" : "text-amber-950/90",
                          )}
                        >
                          • {issue}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => void runResearch()}
                disabled={isPreparing || workflow.status === "running" || workflow.status === "starting"}
                className={cn(
                  "bg-white",
                  isAutonomousRecoveryActive
                    ? "border-primary/30 text-primary hover:bg-primary/10"
                    : "border-amber-300 text-amber-950 hover:bg-amber-100",
                )}
              >
                {isAutonomousRecoveryActive ? "手動で再実行" : "調査を再実行"}
              </Button>
            </div>
          )}
          {isResearchRefreshRunning && (
            <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-primary">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <p className="text-sm font-semibold">再調査を実行中です</p>
                  </div>
                  <p className="text-sm text-primary/90">
                    以前の結果を保持したまま、新しい根拠と判定に更新しています。完了するとこの画面が自動で最新結果に切り替わります。
                  </p>
                  {runtimeResearchSummary?.objective && (
                    <p className="text-xs text-primary/80">
                      目的: {runtimeResearchSummary.objective}
                    </p>
                  )}
                  {runtimeResearchSummary?.nextAutomaticAction && (
                    <p className="text-xs text-primary/80">
                      次の処理: {runtimeResearchSummary.nextAutomaticAction}
                    </p>
                  )}
                  {!!runtimeResearchSummary?.blockingSummary?.length && (
                    <div className="space-y-1">
                      {runtimeResearchSummary.blockingSummary.slice(0, 3).map((item) => (
                        <p key={item} className="text-xs text-primary/80">
                          • {item}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
                <div className="grid gap-2 rounded-xl border border-primary/20 bg-white/80 p-3 text-xs text-muted-foreground sm:grid-cols-2 lg:min-w-[260px]">
                  <div>
                    <p className="font-medium text-foreground">接続状態</p>
                    <p>{formatRuntimeConnectionState(lc.runtimeConnectionState)}</p>
                  </div>
                  <div>
                    <p className="font-medium text-foreground">経過時間</p>
                    <p>{runtimeResearchElapsedMs > 0 ? formatElapsedCompact(runtimeResearchElapsedMs) : "開始待ち"}</p>
                  </div>
                  <div>
                    <p className="font-medium text-foreground">イベント</p>
                    <p>{runtimeResearchTelemetry?.eventCount ?? 0}</p>
                  </div>
                  <div>
                    <p className="font-medium text-foreground">完了ノード</p>
                    <p>{runtimeResearchTelemetry?.completedNodeCount ?? 0}</p>
                  </div>
                  <div>
                    <p className="font-medium text-foreground">最新担当</p>
                    <p>{runtimeResearchTelemetry?.lastAgent ?? "待機中"}</p>
                  </div>
                </div>
              </div>
              <div className="mt-4">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <p className="font-medium text-foreground">進捗</p>
                  <p className="text-muted-foreground">
                    {runtimeCompletedSteps}/{runtimeTotalSteps} ステップ
                  </p>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-primary/10">
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-500"
                    style={{ width: `${runtimeProgressPercent}%` }}
                  />
                </div>
              </div>
              {!!runtimeRunningNodes.length && (
                <div className="mt-4 rounded-xl border border-primary/20 bg-white/70 p-3">
                  <p className="text-xs font-medium text-foreground">いま実行中のノード</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {runtimeRunningNodes.map((nodeId) => (
                      <Badge key={nodeId} variant="secondary" className="gap-1 border border-primary/20 bg-primary/10 text-primary">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {formatResearchNodeLabel(nodeId)}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {!!runtimeRecentActions.length && (
                <div className="mt-4 grid gap-3 xl:grid-cols-2">
                  {runtimeRecentActions.slice(0, 4).map((action) => (
                    <div key={`${action.nodeId}:${action.summary}`} className="rounded-xl border border-primary/20 bg-white/70 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">
                          {action.agentLabel ?? action.label}
                        </p>
                        <Badge variant="secondary" className="border border-border bg-background text-[10px] text-muted-foreground">
                          {action.nodeLabel ?? formatResearchNodeLabel(action.nodeId)}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        状態: {formatRuntimeAgentStatus(
                          action.status === "running"
                            ? "running"
                            : action.status === "failed"
                              ? "failed"
                              : action.status === "completed" || action.status === "succeeded"
                                ? "completed"
                                : "idle",
                        )}
                      </p>
                      <p className="mt-2 text-xs text-muted-foreground">{action.summary}</p>
                    </div>
                  ))}
                </div>
              )}
              {!!runtimeRecentEvents.length && (
                <div className="mt-4 rounded-xl border border-primary/20 bg-white/70 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-foreground">ライブタイムライン</p>
                    <p className="text-[11px] text-muted-foreground">直近 {runtimeRecentEvents.length} 件</p>
                  </div>
                  <div className="mt-3 space-y-2">
                    {runtimeRecentEvents.map((event) => (
                      <div key={`${event.seq ?? "evt"}:${event.nodeId}:${event.timestamp ?? ""}`} className="flex items-start gap-3 rounded-lg border border-border/70 bg-background/80 px-3 py-2">
                        <div className="min-w-[58px] pt-0.5 text-[11px] text-muted-foreground">
                          {formatLiveEventTimestamp(event.timestamp)}
                        </div>
                        <div className="flex-1 space-y-1">
                          <div className="flex items-center gap-2">
                            <p className="text-xs font-medium text-foreground">{formatResearchNodeLabel(event.nodeId)}</p>
                            <Badge variant="secondary" className="border border-border bg-background text-[10px] text-muted-foreground">
                              {formatLiveEventStatus(event.status)}
                            </Badge>
                          </div>
                          <p className="text-xs text-muted-foreground">{event.summary}</p>
                          {event.agent && (
                            <p className="text-[11px] text-muted-foreground">担当: {event.agent}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {!!runtimeAgentCards.length && (
                <div className="mt-4 grid gap-3 xl:grid-cols-2">
                  {runtimeAgentCards.map((agent) => (
                    <div key={agent.agentId} className="rounded-xl border border-primary/20 bg-white/70 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">{agent.label}</p>
                        <Badge
                          variant="secondary"
                          className={cn(
                            "border text-[10px]",
                            agent.status === "running"
                              ? "border-primary/20 bg-primary/10 text-primary"
                              : agent.status === "completed"
                                ? "border-success/20 bg-success/10 text-success"
                                : agent.status === "failed"
                                  ? "border-destructive/20 bg-destructive/10 text-destructive"
                                  : "border-border bg-background text-muted-foreground",
                          )}
                        >
                          {agent.status === "running" ? "実行中" : agent.status === "completed" ? "完了" : agent.status === "failed" ? "失敗" : "待機"}
                        </Badge>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">{agent.currentTask}</p>
                      {agent.delegatedTo && (
                        <p className="mt-1 text-[11px] text-muted-foreground">連携先: {agent.delegatedTo}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {!!runtimeRecentNodes.length && (
                <p className="mt-4 text-xs text-primary/80">
                  直近の流れ: {runtimeRecentNodes.map(formatResearchNodeLabel).join(" → ")}
                </p>
              )}
              {visibleProgress.length > 0 && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {visibleProgress.map((agent) => (
                    <Badge
                      key={agent.nodeId}
                      variant="secondary"
                      className={cn(
                        "gap-1.5 border",
                        agent.status === "completed"
                          ? "border-success/20 bg-success/10 text-success"
                          : agent.status === "running"
                            ? "border-primary/20 bg-primary/10 text-primary"
                            : agent.status === "failed"
                              ? "border-destructive/20 bg-destructive/10 text-destructive"
                              : "border-border bg-background text-muted-foreground",
                      )}
                    >
                      {agent.status === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
                      {agent.status === "completed" && <Check className="h-3 w-3" />}
                      {agent.status === "failed" && <AlertCircle className="h-3 w-3" />}
                      {formatResearchNodeLabel(agent.nodeId)}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          )}

          {!!r.quality_gates?.length && (
            <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
              <div className="rounded-2xl border border-border bg-card p-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-bold text-foreground">品質ゲート</h3>
                  <Badge variant={r.readiness === "ready" ? "default" : "secondary"} className="text-[10px]">
                    {r.readiness ?? "rework"}
                  </Badge>
                </div>
                <div className="mt-3 space-y-2">
                  {r.quality_gates.map((gate) => (
                    <div key={gate.id} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">{formatResearchGateTitle(gate.id, gate.title)}</p>
                        <Badge variant={gate.passed ? "default" : "secondary"} className="text-[10px]">
                          {gate.passed ? "通過" : "未達"}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">{polishResearchCopy(gate.reason)}</p>
                      {!!gate.blockingNodeIds.length && (
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          関連ノード: {gate.blockingNodeIds.map(formatResearchNodeLabel).join(" / ")}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-border bg-card p-4">
                <h3 className="text-sm font-bold text-foreground">エージェント健全性</h3>
                <div className="mt-3 space-y-2">
                  {(r.node_results ?? []).map((node) => (
                    <div key={node.nodeId} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">{formatResearchNodeLabel(node.nodeId)}</p>
                        <Badge variant={node.status === "success" ? "default" : "secondary"} className="text-[10px]">
                          {formatNodeStatus(node.status)}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        応答構造: {formatParseStatus(node.parseStatus)}
                        {node.retryCount > 0 ? ` · 再試行 ${node.retryCount} 回` : ""}
                      </p>
                      {!!node.missingSourceClasses.length && (
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          不足ソース: {node.missingSourceClasses.map(formatSourceClassLabel).join(" / ")}
                        </p>
                      )}
                      {!!node.degradationReasons.length && (
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {Array.from(new Set(node.degradationReasons.map(formatResearchDegradationReason))).join(" / ")}
                        </p>
                      )}
                    </div>
                  ))}
                  {!(r.node_results ?? []).length && (
                    <p className="text-xs text-muted-foreground">健全性ログはまだ記録されていません。</p>
                  )}
                </div>
                {r.remediation_plan && (
                  <div className="mt-4 rounded-lg border border-primary/15 bg-primary/5 p-3">
                    <p className="text-xs font-medium text-foreground">次に補うべき内容</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{r.remediation_plan.objective}</p>
                    {!!r.remediation_plan.retryNodeIds.length && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        再調査対象: {r.remediation_plan.retryNodeIds.map(formatResearchNodeLabel).join(" / ")}
                      </p>
                    )}
                  </div>
                )}
                {autonomousRemediation && (
                  <div className="mt-4 rounded-lg border border-border bg-background p-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium text-foreground">AI 自動補完</p>
                      <Badge variant={autonomousRemediation.status === "blocked" ? "secondary" : "default"} className="text-[10px]">
                        {formatAutonomousRemediationStatus(autonomousRemediation.status)}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {autonomousRemediation.maxAttempts > 0
                        ? `実行回数 ${autonomousRemediation.attemptCount}/${autonomousRemediation.maxAttempts} · 残り ${autonomousRemediation.remainingAttempts} 回`
                        : "実行回数はまだ記録されていません。"}
                    </p>
                    {!!autonomousRemediation.objective && (
                      <p className="mt-1 text-[11px] text-muted-foreground">{autonomousRemediation.objective}</p>
                    )}
                    {!!autonomousRemediation.retryNodeIds.length && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        補完対象: {autonomousRemediation.retryNodeIds.map(formatResearchNodeLabel).join(" / ")}
                      </p>
                    )}
                    {!!autonomousRemediation.blockingSummary?.length && (
                      <div className="mt-2 space-y-1">
                        {autonomousRemediation.blockingSummary.map((item) => (
                          <p key={item} className="text-[11px] text-muted-foreground">
                            • {item}
                          </p>
                        ))}
                      </div>
                    )}
                    {!!autonomousRemediation.stopReason && (
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        停止条件: {autonomousRemediation.stopReason}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Market overview */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <BarChart3 className="h-4 w-4" /> 市場規模
              </div>
              <p className="text-sm text-foreground">{r.market_size}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <Zap className="h-4 w-4" /> 技術実現性
              </div>
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
                  <div className="h-full rounded-full bg-success" style={{ width: `${r.tech_feasibility.score * 100}%` }} />
                </div>
                <span className="text-sm font-bold text-foreground">{(r.tech_feasibility.score * 100).toFixed(0)}%</span>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">{r.tech_feasibility.notes}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <TrendingUp className="h-4 w-4" /> 競合数
              </div>
              <p className="text-3xl font-bold text-foreground">{r.competitors.length}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <Check className="h-4 w-4" /> 判定信頼度
              </div>
              <p className="text-3xl font-bold text-foreground">{((r.confidence_summary?.average ?? 0) * 100).toFixed(0)}%</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                採択 {r.confidence_summary?.accepted ?? 0} / 主張 {r.claims?.length ?? 0}
              </p>
            </div>
          </div>

          {!!r.winning_theses?.length && (
            <div className="rounded-2xl border border-primary/20 bg-primary/5 p-5">
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-primary/80">有力な仮説</p>
              <div className="mt-3 grid gap-2 lg:grid-cols-3">
                {r.winning_theses.map((thesis, index) => (
                  <div key={index} className="rounded-xl border border-primary/10 bg-background/70 p-3 text-sm text-foreground">
                    {thesis}
                  </div>
                ))}
              </div>
              {r.judge_summary && <p className="mt-3 text-xs text-muted-foreground">{r.judge_summary}</p>}
            </div>
          )}

          {/* Competitors */}
          <div>
            <h3 className="text-sm font-bold text-foreground mb-3">競合分析</h3>
            <div className="grid gap-3 lg:grid-cols-3">
              {r.competitors.map((c, i) => (
                <div key={i} className="rounded-xl border border-border bg-card p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-bold text-foreground">{c.name}</h4>
                    <Badge variant="outline" className="text-[10px]">{c.pricing}</Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground">{c.target}</p>
                  <div>
                    <p className="text-[10px] font-medium text-success mb-1">強み</p>
                    {c.strengths.map((s, j) => (
                      <p key={j} className="text-xs text-foreground flex items-start gap-1"><Check className="h-3 w-3 mt-0.5 text-success shrink-0" />{s}</p>
                    ))}
                  </div>
                  <div>
                    <p className="text-[10px] font-medium text-destructive mb-1">弱み</p>
                    {c.weaknesses.map((w, j) => (
                      <p key={j} className="text-xs text-foreground flex items-start gap-1"><ShieldAlert className="h-3 w-3 mt-0.5 text-destructive shrink-0" />{w}</p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* SWOT-like grid */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="rounded-xl border-2 border-success/20 bg-success/5 p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-success mb-2"><Lightbulb className="h-4 w-4" /> 機会</h3>
              {r.opportunities.map((o, i) => <p key={i} className="text-xs text-foreground py-0.5">• {o}</p>)}
            </div>
            <div className="rounded-xl border-2 border-destructive/20 bg-destructive/5 p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-destructive mb-2"><ShieldAlert className="h-4 w-4" /> 脅威</h3>
              {r.threats.map((t, i) => <p key={i} className="text-xs text-foreground py-0.5">• {t}</p>)}
            </div>
          </div>

          {/* Trends */}
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-3"><TrendingUp className="h-4 w-4 text-primary" /> 市場トレンド</h3>
            <div className="flex flex-wrap gap-2">
              {r.trends.map((t, i) => (
                <Badge key={i} variant="secondary" className="text-xs">{t}</Badge>
              ))}
            </div>
          </div>

          {!!r.user_research && (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-sm font-bold text-foreground mb-3">ユーザーシグナル</h3>
                <div className="space-y-2">
                  {r.user_research.signals.map((signal, index) => (
                    <p key={index} className="text-xs text-foreground">• {signal}</p>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-sm font-bold text-foreground mb-3">痛みと摩擦</h3>
                <div className="space-y-2">
                  {r.user_research.pain_points.map((pain, index) => (
                    <p key={index} className="text-xs text-foreground">• {pain}</p>
                  ))}
                </div>
              </div>
            </div>
          )}

          {!!r.claims?.length && (
            <div>
              <h3 className="text-sm font-bold text-foreground mb-3">主張台帳</h3>
              <div className="grid gap-3 lg:grid-cols-2">
                {r.claims.map((claim) => (
                  <div key={claim.id} className="rounded-xl border border-border bg-card p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-foreground">{claim.statement}</p>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {formatResearchNodeLabel(claim.owner)} · {formatClaimCategory(claim.category)}
                        </p>
                      </div>
                      <Badge variant={claim.status === "accepted" ? "default" : "secondary"} className="shrink-0 text-[10px]">
                        {formatClaimStatus(claim.status)}
                      </Badge>
                    </div>
                    <div className="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground">
                      <span>確信度 {(claim.confidence * 100).toFixed(0)}%</span>
                      <span>根拠 {claim.evidence_ids.length}</span>
                      <span>反証 {claim.counterevidence_ids.length}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-3">
                <ShieldAlert className="h-4 w-4 text-destructive" /> 反対意見
              </h3>
              <div className="space-y-2">
                {(r.dissent ?? []).map((item) => (
                  <div key={item.id} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium text-foreground">{item.argument}</p>
                      <Badge variant="outline" className="text-[10px]">{formatDissentSeverity(item.severity)}</Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {item.resolved ? "解決済み" : "未解決"} · {item.recommended_test ?? "追加検証を定義"}
                    </p>
                  </div>
                ))}
                {!(r.dissent ?? []).length && <p className="text-xs text-muted-foreground">重大な反対意見はありません。</p>}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-3">
                <AlertCircle className="h-4 w-4 text-primary" /> 未解決の問い
              </h3>
              <div className="space-y-2">
                {(r.open_questions ?? []).map((question, index) => (
                  <p key={index} className="rounded-lg border border-border/80 bg-background px-3 py-2 text-xs text-foreground">
                    {question}
                  </p>
                ))}
                {!(r.open_questions ?? []).length && <p className="text-xs text-muted-foreground">未解決の問いはありません。</p>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
