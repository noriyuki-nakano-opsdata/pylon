import { useCallback, useEffect, useId, useRef, useState, type RefObject } from "react";
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
import { MultiAgentCollaborationPulse } from "@/components/lifecycle/MultiAgentCollaborationPulse";
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
  formatResearchOperatorAction,
  formatResearchRecoveryMode,
  formatSourceClassLabel,
  polishResearchCopy,
} from "@/lifecycle/presentation";
import { auditResearchQuality } from "@/lifecycle/researchAudit";
import { buildResearchExperienceFrames } from "@/lifecycle/researchExperienceFrames";
import { completePhaseStatuses, hasRestorablePhaseRun } from "@/lifecycle/phaseStatus";
import { persistCompletedPhase } from "@/lifecycle/phasePersistence";
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
import { RequirementsPanel } from "./RequirementsPanel";
import { ReverseEngineeringPanel } from "./ReverseEngineeringPanel";
import {
  buildIdentityAutofillMessages,
  describeProductIdentityState,
  joinIdentityList,
  mergeProductIdentityFallback,
  normalizeIdentityDomain,
  normalizeIdentityListInput,
  normalizeIdentityWebsite,
  normalizeProductIdentity,
} from "@/lifecycle/productIdentity";
import type {
  LifecycleProject,
  LifecycleResearchRecoveryMode,
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

const JOURNEY_PHASE_LABELS = {
  awareness: "認知",
  consideration: "比較",
  acquisition: "導入判断",
  usage: "運用開始",
  advocacy: "展開",
} as const;

const JOURNEY_EMOTION_CLASS = {
  positive: "border-emerald-200/80 bg-emerald-50 text-emerald-900",
  neutral: "border-slate-200/80 bg-slate-100 text-slate-900",
  negative: "border-amber-200/80 bg-amber-50 text-amber-950",
} as const;

const KANO_TONE_CLASS = {
  "must-be": "border-rose-200/80 bg-rose-50 text-rose-900",
  "one-dimensional": "border-sky-200/80 bg-sky-50 text-sky-900",
  attractive: "border-emerald-200/80 bg-emerald-50 text-emerald-900",
  indifferent: "border-slate-200/80 bg-slate-100 text-slate-800",
  reverse: "border-violet-200/80 bg-violet-50 text-violet-900",
} as const;

const KANO_LABEL = {
  "must-be": "必須",
  "one-dimensional": "性能",
  attractive: "魅力",
  indifferent: "無関心",
  reverse: "逆効果",
} as const;

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

function SetupChecklistItem(props: {
  done: boolean;
  label: string;
  description: string;
}) {
  const { done, label, description } = props;
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border px-3.5 py-3",
        done
          ? "border-emerald-500/20 bg-emerald-500/5"
          : "border-border bg-background/70",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
          done
            ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-300"
            : "border-border bg-background text-muted-foreground",
        )}
      >
        {done ? <Check className="h-3.5 w-3.5" /> : <span className="h-1.5 w-1.5 rounded-full bg-current/70" />}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
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

function formatPulseElapsedLabel(ms: number): string {
  return ms > 0 ? formatElapsedCompact(ms) : "開始直後";
}

function buildResearchPulseTimeline(agents: Array<{
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed";
  currentTask?: string;
}>) {
  const runningCount = agents.filter((agent) => agent.status === "running").length;
  const completedCount = agents.filter((agent) => agent.status === "completed").length;
  const synthAgent = agents.find((agent) => agent.id === "research-synthesizer");
  const leadAgent = agents.find((agent) => agent.status === "running") ?? agents[0];

  return [
    {
      id: "signal-collection",
      label: "シグナル収集",
      detail: runningCount > 0
        ? `${runningCount} 人の専門エージェントが、市場・競合・ユーザー・技術の各レーンで並列に根拠を集めています。`
        : "各専門レーンへ最初の情報収集タスクを振り分けています。",
      status: completedCount > 0 || runningCount > 0 ? "completed" as const : "pending" as const,
      owner: leadAgent?.label,
      artifact: "一次根拠",
    },
    {
      id: "claim-challenge",
      label: "仮説の突合",
      detail: "弱い主張を隣接シグナルで突き合わせ、統合前に精度を引き上げます。",
      status: runningCount > 0 ? "running" as const : completedCount >= 3 ? "completed" as const : "pending" as const,
      owner: agents.find((agent) => agent.status === "running")?.label,
      artifact: "信頼度評価",
    },
    {
      id: "synthesis-pass",
      label: "統合ブリーフ生成",
      detail: synthAgent?.status === "running"
        ? synthAgent.currentTask || "統合担当が、集まった根拠を企画に渡せる要約へ圧縮しています。"
        : "統合担当が、最も強い根拠をまとめて企画向けの判断材料を作ります。",
      status: synthAgent?.status === "completed" ? "completed" as const : synthAgent?.status === "running" ? "running" as const : "pending" as const,
      owner: synthAgent?.label,
      artifact: "調査ブリーフ",
    },
    {
      id: "planning-handoff",
      label: "企画への引き渡し",
      detail: "信頼度チェックを通った論点を、企画フェーズですぐ使える形にして渡します。",
      status: agents.every((agent) => agent.status === "completed") ? "completed" as const : "pending" as const,
      owner: synthAgent?.label,
      artifact: "企画パケット",
    },
  ];
}

function applyWarmupMotion<T extends {
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed";
  currentTask?: string;
}>(agents: T[], options: { enabled?: boolean } = {}): T[] {
  if (options.enabled === false) {
    return agents;
  }
  if (agents.some((agent) => agent.status === "running" || agent.status === "completed" || agent.status === "failed")) {
    return agents;
  }
  return agents.map((agent, index) => ({
    ...agent,
    status: index === 0 ? "running" : index === 1 ? "running" : "pending",
    currentTask: index === 0
      ? `${agent.label} が最初のシグナル収集を開始`
      : index === 1
        ? `${agent.label} が共有コンテキストの受け取りを準備中`
        : agent.currentTask,
  }));
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
          recoveryMode: normalizeTextValue((research.autonomous_remediation as Record<string, unknown>).recoveryMode, "", 32) as NonNullable<MarketResearch["autonomous_remediation"]>["recoveryMode"],
          recommendedOperatorAction: normalizeTextValue((research.autonomous_remediation as Record<string, unknown>).recommendedOperatorAction, "", 40) as NonNullable<MarketResearch["autonomous_remediation"]>["recommendedOperatorAction"],
          conditionalHandoffAllowed: (research.autonomous_remediation as Record<string, unknown>).conditionalHandoffAllowed === true,
          strategySummary: normalizeCopyValue((research.autonomous_remediation as Record<string, unknown>).strategySummary, "", 220) || undefined,
          strategyChecklist: normalizeCopyList((research.autonomous_remediation as Record<string, unknown>).strategyChecklist, 4, 180),
          planningGuardrails: normalizeCopyList((research.autonomous_remediation as Record<string, unknown>).planningGuardrails, 4, 180),
          followUpQuestion: normalizeCopyValue((research.autonomous_remediation as Record<string, unknown>).followUpQuestion, "", 180) || undefined,
          stalledSignature: (research.autonomous_remediation as Record<string, unknown>).stalledSignature === true,
          confidenceFloor: typeof (research.autonomous_remediation as Record<string, unknown>).confidenceFloor === "number"
            ? (research.autonomous_remediation as Record<string, unknown>).confidenceFloor as number
            : undefined,
          targetConfidenceFloor: typeof (research.autonomous_remediation as Record<string, unknown>).targetConfidenceFloor === "number"
            ? (research.autonomous_remediation as Record<string, unknown>).targetConfidenceFloor as number
            : undefined,
          stopReason: normalizeCopyValue((research.autonomous_remediation as Record<string, unknown>).stopReason, "", 180) || undefined,
        }
      : undefined,
  };
}

export function ResearchPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const identityFieldBaseId = useId();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const hasKnownResearchRun = hasRestorablePhaseRun(
    lc.phaseStatuses,
    lc.phaseRuns,
    lc.runtimeActivePhase,
    "research",
  );
  const workflow = useWorkflowRun("research", projectSlug ?? "", { knownRunExists: hasKnownResearchRun });
  const researchAgents = lc.blueprints.research.team.length > 0
    ? lc.blueprints.research.team.map((agent) => ({ id: agent.id, label: agent.label }))
    : RESEARCH_AGENTS;
  const [newUrl, setNewUrl] = useState("");
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showManualRecoveryOptions, setShowManualRecoveryOptions] = useState(false);
  const [liveNow, setLiveNow] = useState(() => Date.now());
  const companyFieldId = `${identityFieldBaseId}-company`;
  const productFieldId = `${identityFieldBaseId}-product`;
  const websiteFieldId = `${identityFieldBaseId}-website`;
  const websiteHelpId = `${identityFieldBaseId}-website-help`;
  const aliasesFieldId = `${identityFieldBaseId}-aliases`;
  const excludedEntitiesFieldId = `${identityFieldBaseId}-excluded-entities`;
  const specFieldId = `${identityFieldBaseId}-spec`;
  const specHelpId = `${identityFieldBaseId}-spec-help`;
  const researchAdvancedSectionId = `${identityFieldBaseId}-advanced`;
  const competitorUrlFieldId = `${identityFieldBaseId}-competitor-url`;
  const depthFieldId = `${identityFieldBaseId}-depth`;
  const syncedRunRef = useRef<string | null>(null);
  const competitorUrls = lc.researchConfig.competitorUrls;
  const depth = lc.researchConfig.depth;
  const outputLanguage = lc.researchConfig.outputLanguage ?? "ja";
  const recoveryMode = lc.researchConfig.recoveryMode ?? "auto";
  const productIdentity = normalizeProductIdentity(lc.productIdentity);
  const identityState = describeProductIdentityState(productIdentity);
  const trimmedSpec = lc.spec.trim();
  const hasIdentityContext = identityState.mode !== "concept_only";
  const identityWebsiteError =
    productIdentity.officialWebsite?.trim()
    && !normalizeIdentityDomain(productIdentity.officialWebsite)
      ? "公式サイトは有効な URL またはドメインで入力してください"
      : "";
  const identityAutofillMessages = buildIdentityAutofillMessages(productIdentity);
  const setupChecklist = [
    {
      label: "プロダクト概要",
      done: Boolean(trimmedSpec),
      description: "市場、競合、導入論点を組み立てる起点です。",
    },
    {
      label: "会社名・運営主体",
      done: Boolean(productIdentity.companyName.trim()),
      description: "決まっていれば入力します。ブランド衝突の隔離精度が上がります。",
    },
    {
      label: "サービス名・構想名",
      done: Boolean(productIdentity.productName.trim()),
      description: "仮称でも構いません。未定なら AI が概要から関連語を広げます。",
    },
  ] as const;
  const completedRequiredCount = setupChecklist[0].done ? 1 : 0;
  const completedAssistCount = setupChecklist.slice(1).filter((item) => item.done).length;
  const targetIdentityLabel = identityState.summaryLabel;
  const updateProductIdentityField = (patch: Partial<typeof productIdentity>) => {
    actions.updateProductIdentity({
      ...productIdentity,
      ...patch,
    });
  };
  const withIdentityFallback = useCallback((project: LifecycleProject): LifecycleProject => ({
    ...project,
    productIdentity: mergeProductIdentityFallback(project.productIdentity, productIdentity, {
      fallbackProductName: project.name?.trim() || project.projectId,
    }),
  }), [productIdentity]);

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
    void lifecycleApi.syncPhaseRun(projectSlug, "research", workflow.runId)
      .then(({ project }) => {
        syncedRunRef.current = workflow.runId;
        actions.applyProject(withIdentityFallback(project));
      })
      .catch(() => {
        syncedRunRef.current = null;
      });
  }, [actions, projectSlug, withIdentityFallback, workflow.runId, workflow.status]);

  const runResearch = async (override: { recoveryMode?: LifecycleResearchRecoveryMode } = {}) => {
    if (!lc.spec.trim() || !projectSlug) return;
    setLaunchError(null);
    if (identityWebsiteError) {
      setLaunchError(identityWebsiteError);
      return;
    }
    setIsPreparing(true);
    const researchConfig = {
      competitorUrls,
      depth,
      outputLanguage,
      recoveryMode: override.recoveryMode ?? recoveryMode,
    };
    try {
      const response = await lifecycleApi.saveProject(
        projectSlug,
        {
          ...buildResearchProjectPatch(lc, researchConfig),
          researchOperatorDecision: null,
        } satisfies Partial<LifecycleProject>,
        { autoRun: false },
      );
      actions.applyProject(withIdentityFallback(response.project));
      actions.advancePhase("research");
      workflow.start(buildResearchWorkflowInput(lc, researchConfig));
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : "調査の開始に失敗しました");
    } finally {
      setIsPreparing(false);
    }
  };

  const continueWithConditionalHandoff = async () => {
    if (!projectSlug || !research) return;
    setLaunchError(null);
    setIsPreparing(true);
    try {
      const response = await lifecycleApi.saveProject(
        projectSlug,
        {
          phaseStatuses: completePhaseStatuses(lc.phaseStatuses, "research"),
          researchOperatorDecision: {
            mode: "conditional_handoff",
            selectedAt: new Date().toISOString(),
            rationale: research.judge_summary ?? "未解決の前提を明示したうえで企画に進みます。",
          },
        } satisfies Partial<LifecycleProject>,
        { autoRun: false },
      );
      actions.applyProject(withIdentityFallback(response.project));
      actions.completePhase("research");
      navigate(`/p/${projectSlug}/lifecycle/planning`);
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : "企画への条件付き引き継ぎに失敗しました");
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
    if (!researchReady && conditionalHandoffAllowed) {
      void continueWithConditionalHandoff();
      return;
    }
    if (!researchReady && hasPlanningReviewAccess) {
      if (!projectSlug) return;
      navigate(`/p/${projectSlug}/lifecycle/planning`);
      return;
    }
    if (!researchReady) return;
    if (!projectSlug) {
      actions.completePhase("research");
      return;
    }
    setLaunchError(null);
    setIsPreparing(true);
    void persistCompletedPhase(projectSlug, "research", lc.phaseStatuses)
      .then((response) => {
        actions.applyProject(withIdentityFallback(response.project));
        navigate(`/p/${projectSlug}/lifecycle/planning`);
      })
      .catch((err) => {
        setLaunchError(err instanceof Error ? err.message : "企画への移動に失敗しました");
      })
      .finally(() => {
        setIsPreparing(false);
      });
  };

  const hasStoredResearch = hasResearchContent(lc.research);
  const runtimeResearchSource = (workflow.state as Record<string, unknown> | undefined)?.research;
  const hasRuntimeResearch = hasResearchContent(runtimeResearchSource);
  const research = hasStoredResearch
    ? normalizeResearch(lc.research)
    : hasRuntimeResearch
      ? normalizeResearch(runtimeResearchSource)
      : null;
  const completionGapMessage =
    workflow.status === "completed" && !hasStoredResearch && !hasRuntimeResearch
      ? "調査実行は完了しましたが、保存済みの調査結果を読み込めませんでした。再同期または再実行が必要です。"
      : null;
  const errorMessage =
    launchError
    ?? (workflow.status === "failed" ? workflow.error : null)
    ?? completionGapMessage;
  const researchPhaseStatus = selectPhaseStatus(lc.phaseStatuses, "research");
  const planningPhaseStatus = selectPhaseStatus(lc.phaseStatuses, "planning");
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
  const researchAudit = auditResearchQuality(r, {
    projectSpec: lc.spec,
    seedUrls: competitorUrls,
    identityProfile: productIdentity,
  });
  const {
    researchReady,
    confidenceFloor,
    semanticIssues,
    autonomousRemediation,
    isAutonomousRecoveryActive,
    conditionalHandoffAllowed,
    recommendedOperatorAction,
    strategySummary,
    planningGuardrails,
    followUpQuestion,
    gateIssues: researchGateIssues,
    warning: researchWarning,
  } = selectResearchReadinessState({
    research,
    phaseStatus: researchPhaseStatus,
    nextAction: lc.nextAction,
    projectSpec: lc.spec,
    seedUrls: competitorUrls,
    productIdentity,
  });
  const researchRecoverySummary = isAutonomousRecoveryActive
    ? autonomousRemediation?.objective || "不足している根拠、品質ゲート、未達ノードを順に補い、企画へ渡せる状態まで自律的に再調査します。"
    : researchWarning;
  const activeRecoveryMode = autonomousRemediation?.recoveryMode ?? recoveryMode;
  const activeStrategySummary = strategySummary ?? autonomousRemediation?.strategySummary ?? researchRecoverySummary;
  const primaryRecoveryActionLabel =
    conditionalHandoffAllowed && recommendedOperatorAction === "conditional_handoff"
      ? "推奨どおり企画へ進む"
      : "AI に最適な順で再調査を任せる";
  const primaryRecoveryActionDescription =
    conditionalHandoffAllowed && recommendedOperatorAction === "conditional_handoff"
      ? "いまは再調査を続けるより、未解決の前提を明示したうえで企画に進むほうが前に進める状態です。"
      : activeRecoveryMode === "reframe_research"
        ? "いまは観点変更を優先し、別セグメントや別評価軸で詰まりを解きます。"
        : "まず根拠を深掘りし、まだ詰まる場合は同一実行の中で観点も切り替えます。";
  const hasPlanningReviewAccess = planningPhaseStatus !== "locked";
  const canProceedToPlanning = researchReady || conditionalHandoffAllowed || hasPlanningReviewAccess;
  const hasGuardedPlanningHandoff =
    conditionalHandoffAllowed && recommendedOperatorAction === "conditional_handoff";
  const planningCtaLabel = hasPlanningReviewAccess && !researchReady && !hasGuardedPlanningHandoff
    ? "企画レビューへ進む"
    : researchReady
      ? "企画へ進む"
      : hasGuardedPlanningHandoff
        ? "条件付きで企画へ進む"
        : "企画へ進む";
  const qualityGateBadgeLabel = researchReady
    ? "通過"
    : hasGuardedPlanningHandoff
      ? "条件付き"
      : "要見直し";
  const trustedCompetitors = researchAudit.competitors.trusted;
  const quarantinedCompetitors = researchAudit.competitors.quarantined;
  const trustedTrends = researchAudit.trends.trusted;
  const trustedOpportunities = researchAudit.opportunities.trusted;
  const trustedThreats = researchAudit.threats.trusted;
  const trustedSourceLinks = researchAudit.sourceLinks.trusted;
  const trustedEvidenceItems = researchAudit.evidence.trusted;
  const trustedUserSignals = researchAudit.userSignals.trusted;
  const trustedPainPoints = researchAudit.painPoints.trusted;
  const trustedWinningTheses = researchAudit.winningTheses.trusted;
  const quarantinedWinningTheses = researchAudit.winningTheses.quarantined;
  const trustedClaims = researchAudit.claims.trusted;
  const quarantinedClaims = researchAudit.claims.quarantined;
  const trustedDissent = researchAudit.dissent.trusted;
  const quarantinedDissent = researchAudit.dissent.quarantined;
  const trustedOpenQuestions = researchAudit.openQuestions.trusted;
  const quarantinedOpenQuestions = researchAudit.openQuestions.quarantined;
  const trustedSourceHosts = Array.from(new Set([
    ...trustedSourceLinks.map(formatCompetitorHost),
    ...trustedEvidenceItems
      .filter((item) => item.source_type === "url" && /^https?:\/\//i.test(item.source_ref))
      .map((item) => formatCompetitorHost(item.source_ref)),
  ])).slice(0, 4);
  const trustedDecisionCount = trustedWinningTheses.length + trustedClaims.length + trustedDissent.length + trustedOpenQuestions.length;
  const decisionQuarantineCount =
    quarantinedWinningTheses.length
    + quarantinedClaims.length
    + quarantinedDissent.length
    + quarantinedOpenQuestions.length;
  const confidenceMetricLabel = !researchReady && semanticIssues.length > 0 ? "参考信頼度" : "信頼度下限";
  const confidenceMetricDescription = !researchReady && semanticIssues.length > 0
    ? "内容監査に問題があるため、単独では判断材料にしない値"
    : "企画へ渡すときの最低信頼ライン";
  const experienceFrames = buildResearchExperienceFrames({
    projectSpec: lc.spec,
    research: r,
    audit: researchAudit,
    trustedCompetitors,
    trustedTrends,
    trustedOpportunities,
    trustedThreats,
    trustedUserSignals,
    trustedPainPoints,
  });
  const blockingNodeIds = autonomousRemediation?.blockingNodeIds ?? [];
  const blockingSummary = autonomousRemediation?.blockingSummary ?? [];
  const shouldShowAutonomousRemediationDetail = autonomousRemediation != null && (
    autonomousRemediation.status !== "not_needed"
    || autonomousRemediation.retryNodeIds.length > 0
    || autonomousRemediation.blockingGateIds.length > 0
    || blockingNodeIds.length > 0
    || blockingSummary.length > 0
    || autonomousRemediation.stalledSignature
  );
  const trustHeadline = researchReady
    ? "企画に渡せる調査です"
    : hasGuardedPlanningHandoff
      ? "未解決の前提を添えて企画に進めます"
      : "調査結果の見直しが必要です";
  const trustSummary = researchReady
    ? "対象に関係する根拠を残し、記事断片や無関係ソースを混ぜずに要点を整理できています。まず主要示唆を確認し、その後で詳細へ進んでください。"
    : hasGuardedPlanningHandoff
      ? "完全な通過ではありませんが、信頼できる根拠と持ち込む前提を切り分けています。企画では下記の前提を条件として扱ってください。"
      : semanticIssues.length > 0
        ? "構造上は整って見えても、対象外のソースや崩れた値が混ざると判断を誤ります。隔離した項目を除外し、根拠を補ってから次へ進めてください。"
        : "品質ゲートを満たしていないため、追加調査または前提の再整理が必要です。";
  const trustTone = researchReady
    ? "border-emerald-200/60 bg-[linear-gradient(135deg,rgba(248,250,252,0.98),rgba(236,253,245,0.92))]"
    : hasGuardedPlanningHandoff
      ? "border-sky-200/60 bg-[linear-gradient(135deg,rgba(248,250,252,0.98),rgba(239,246,255,0.92))]"
      : "border-amber-300/60 bg-[linear-gradient(135deg,rgba(255,251,235,0.98),rgba(248,250,252,0.94))]";
  const trustBadgeTone = researchReady
    ? "border-emerald-200/70 bg-emerald-50 text-emerald-900"
    : hasGuardedPlanningHandoff
      ? "border-sky-200/70 bg-sky-50 text-sky-900"
      : "border-amber-300/60 bg-amber-100 text-amber-950";
  const sectionCardClass = "rounded-[24px] border border-border/80 bg-card/94 p-5 shadow-[0_18px_44px_-36px_rgba(15,23,42,0.38)]";
  const sectionSubtleCardClass = "rounded-[20px] border border-border/70 bg-background/84 p-4";
  const trustMetricCardClass = "rounded-[20px] border border-slate-950/10 bg-white/78 px-4 py-4 text-slate-950 shadow-[0_16px_38px_-34px_rgba(15,23,42,0.28)] backdrop-blur";
  const trustSupportCardClass = "rounded-[20px] border border-slate-950/10 bg-white/70 p-4 shadow-[0_16px_38px_-34px_rgba(15,23,42,0.2)] backdrop-blur";
  const trustAsideCardClass = "rounded-[24px] border border-border/80 bg-card/94 p-4 shadow-[0_18px_42px_-34px_rgba(15,23,42,0.38)]";
  const trustFocusPoints = researchReady
    ? [
      trustedSourceHosts.length > 0
        ? `信頼できる外部根拠: ${trustedSourceHosts.join(" / ")}`
        : `信頼できる外部根拠: ${researchAudit.trustedEvidenceCount} 件`,
      `企画に渡す有力仮説: ${trustedWinningTheses.length} 件`,
      `隔離項目: ${researchAudit.quarantinedCount} 件`,
    ]
    : [
      `隔離項目: ${researchAudit.quarantinedCount} 件`,
      `有効な外部根拠: ${researchAudit.trustedEvidenceCount}/${Math.max(researchAudit.totalEvidenceCount, 1)} 件`,
      decisionQuarantineCount > 0
        ? `後段で隔離した論点: ${decisionQuarantineCount} 件`
        : semanticIssues[0] ?? researchGateIssues[0] ?? "追加調査が必要です。",
    ];
  const handlePrimaryRecoveryAction = async () => {
    if (conditionalHandoffAllowed && recommendedOperatorAction === "conditional_handoff") {
      await continueWithConditionalHandoff();
      return;
    }
    await runResearch({ recoveryMode: "auto" });
  };
  const runtimePulseAgents = applyWarmupMotion(runtimeAgentCards.map((agent) => ({
    id: agent.agentId,
    label: agent.label,
    status:
      agent.status === "running"
        ? "running" as const
        : agent.status === "completed"
          ? "completed" as const
          : agent.status === "failed"
            ? "failed" as const
            : "pending" as const,
    currentTask: agent.currentTask,
    delegatedTo: agent.delegatedTo,
  })), { enabled: false });
  const runtimePulseTimeline = [
    {
      id: "delta-scan",
      label: "差分スキャン",
      detail: "保存済みの結果と新しいシグナルを比較し、意味のある変化だけを昇格させます。",
      status: runtimePulseAgents.some((agent) => agent.status === "completed" || agent.status === "running") ? "completed" as const : "pending" as const,
      owner: runtimePulseAgents[0]?.label,
      artifact: "差分候補",
    },
    {
      id: "re-score",
      label: "信頼度の再採点",
      detail: "主張の優先順位を見直し、阻害要因を再評価し、低信頼の論点を再調査へ戻します。",
      status: runtimePulseAgents.some((agent) => agent.status === "running") ? "running" as const : "pending" as const,
      owner: runtimePulseAgents.find((agent) => agent.status === "running")?.label,
      artifact: "更新済み信頼度",
    },
    {
      id: "merge-results",
      label: "結果への反映",
      detail: "検証済みの差分を、いま見えている調査結果を崩さずに反映します。",
      status: runtimePulseAgents.find((agent) => agent.id === "research-synthesizer")?.status === "completed"
        ? "completed" as const
        : runtimePulseAgents.find((agent) => agent.id === "research-synthesizer")?.status === "running"
          ? "running" as const
          : "pending" as const,
      owner: runtimePulseAgents.find((agent) => agent.id === "research-synthesizer")?.label,
      artifact: "更新ブリーフ",
    },
  ];
  const decisionSummarySectionRef = useRef<HTMLDivElement | null>(null);
  const peopleSectionRef = useRef<HTMLDivElement | null>(null);
  const governanceSectionRef = useRef<HTMLDivElement | null>(null);
  const marketSectionRef = useRef<HTMLDivElement | null>(null);
  const questionSectionRef = useRef<HTMLDivElement | null>(null);
  const scrollToSection = (sectionRef: RefObject<HTMLElement | null>) => {
    sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const reviewRailItems = [
    {
      label: "判定サマリー",
      description: researchReady ? "進める条件と採用根拠を見る" : "停止理由と採用根拠を見る",
      icon: AlertCircle,
      ref: decisionSummarySectionRef,
    },
    {
      label: "人と仕事",
      description: "誰のどの判断を支えるかを見る",
      icon: Briefcase,
      ref: peopleSectionRef,
    },
    {
      label: "運用統治",
      description: "品質ゲートと回復ログを見る",
      icon: ShieldAlert,
      ref: governanceSectionRef,
    },
    {
      label: "市場と仮説",
      description: "市場妥当性と残課題を見る",
      icon: TrendingUp,
      ref: marketSectionRef,
    },
    {
      label: "論点",
      description: "主張と未解決の問いを見る",
      icon: Lightbulb,
      ref: questionSectionRef,
    },
  ] as const;

  // Input state
  const isResearchRefreshRunning = !!research && (isRunning || isResearchRunLive);

  if (!research && !shouldShowInitialResearchRun) {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-4 py-4 sm:px-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
                <Search className="h-5 w-5 text-primary" />
                調査の開始
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                会社名やサービス名が未定でも、概要だけで開始できます。決まっている情報だけ足せば、AI が検索軸と隔離条件を補います。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge
                variant={completedRequiredCount === 1 ? "assistive" : "warning"}
                size="field"
                className={cn(
                  completedRequiredCount === 1
                    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                    : "border-amber-200 bg-amber-50 text-amber-950",
                )}
              >
                必須 {completedRequiredCount}/1
              </Badge>
              <Badge variant="outline" size="field" className="bg-background/80 text-muted-foreground">
                補足 {completedAssistCount}/2
              </Badge>
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="mx-auto grid max-w-6xl gap-5 xl:grid-cols-[minmax(0,1.15fr)_20rem]">
            <div className="flex flex-col gap-4">
              {errorMessage && (
                <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                  <p className="font-medium">前回の調査は失敗しました。</p>
                  <p className="mt-1">{errorMessage}</p>
                </div>
              )}

              <section className="order-4 rounded-2xl border border-border bg-card p-5 lg:order-1">
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_19rem] lg:items-start">
                  <div className="space-y-3">
                    <div className="inline-flex items-center gap-2 rounded-full border border-primary/15 bg-primary/5 px-3 py-1 text-[11px] font-medium tracking-[0.08em] text-primary">
                      <Sparkles className="h-3.5 w-3.5" />
                      最短で開始
                    </div>
                    <div className="space-y-2">
                      <h2 className="text-xl font-semibold tracking-tight text-foreground">
                        構想段階でも、概要があればすぐに調査へ進めます。
                      </h2>
                      <p className="text-sm leading-6 text-muted-foreground">
                        まずは調べたい構想を短く書きます。会社名やサービス名が未定なら空欄のままで構いません。同名候補が出たときだけ、後から追加情報を使って絞り込みます。
                      </p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    {setupChecklist.map((item) => (
                      <SetupChecklistItem
                        key={item.label}
                        done={item.done}
                        label={item.label}
                        description={item.description}
                      />
                    ))}
                  </div>
                </div>
              </section>

              <section className="order-1 rounded-2xl border border-border bg-card p-5 lg:order-2">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-medium text-foreground">1. 調べたい構想を書く</p>
                    <p className="mt-1 text-xs leading-6 text-muted-foreground">
                      誰のどんな課題をどう解決したいかを、3 から 5 文で置いてください。詳細仕様ではなく、判断したい論点の骨子で十分です。
                    </p>
                  </div>
                  <Badge
                    variant={trimmedSpec ? "assistive" : "warning"}
                    size="field"
                    className={cn(
                      "self-start",
                      trimmedSpec
                        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                        : "border-amber-200 bg-amber-50 text-amber-950",
                    )}
                  >
                    {trimmedSpec ? "開始準備 OK" : "概要を入力"}
                  </Badge>
                </div>

                <div className="mt-4">
                  <label htmlFor={specFieldId} className="mb-1.5 block text-sm font-medium text-foreground">プロダクト概要</label>
                  <p id={specHelpId} className="mb-3 text-xs text-muted-foreground">
                    後で企画の判断材料になります。いまは精密さより、論点が伝わることを優先してください。
                  </p>
                  <textarea
                    id={specFieldId}
                    value={lc.spec}
                    onChange={(e) => actions.editSpec(e.target.value)}
                  placeholder="例: タスク整理が苦手なチーム向けに、優先度と進捗を可視化する ToDo ツールを作りたい。複数人での進行管理と振り返りを簡単にしたい。"
                  rows={6}
                  aria-describedby={specHelpId}
                  className="w-full rounded-xl border border-border bg-background p-4 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                />
                </div>
              </section>

              <section className="order-2 rounded-2xl border border-border bg-card p-5 lg:order-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-medium text-foreground">2. 決まっている情報だけ補足する</p>
                    <p className="mt-1 text-xs leading-6 text-muted-foreground">
                      任意です。いまの状態に合わせて調査の起点を変えます。未定なら空欄のままで始められます。
                    </p>
                  </div>
                  <Badge
                    variant={identityState.mode === "identity_locked" ? "assistive" : "optional"}
                    size="field"
                    className={cn(
                      "self-start",
                      identityState.mode === "identity_locked"
                        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                        : hasIdentityContext
                          ? "border-sky-200 bg-sky-50 text-sky-800"
                          : "border-slate-200 bg-slate-50 text-slate-700",
                    )}
                  >
                    {identityState.badgeLabel}
                  </Badge>
                </div>
                <p className="mt-3 rounded-xl border border-border bg-background/70 px-3.5 py-3 text-xs leading-6 text-muted-foreground">
                  {identityState.helperText}
                </p>

                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  <div>
                    <div className="mb-1.5 flex items-center gap-2">
                      <label htmlFor={companyFieldId} className="block text-sm font-medium text-foreground">会社名・運営主体</label>
                      <Badge variant="optional" size="field" className="border-slate-200 bg-slate-50 text-slate-700">任意</Badge>
                    </div>
                    <input
                      id={companyFieldId}
                      value={productIdentity.companyName}
                      onChange={(e) => updateProductIdentityField({ companyName: e.target.value })}
                      placeholder="例: Pylon Labs"
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <div className="mb-1.5 flex items-center gap-2">
                      <label htmlFor={productFieldId} className="block text-sm font-medium text-foreground">サービス名・構想名</label>
                      <Badge variant="optional" size="field" className="border-slate-200 bg-slate-50 text-slate-700">任意</Badge>
                    </div>
                    <input
                      id={productFieldId}
                      value={productIdentity.productName}
                      onChange={(e) => updateProductIdentityField({ productName: e.target.value })}
                      placeholder="例: Pylon / 未定なら空欄"
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline" size="field" className="bg-background/80 text-muted-foreground">
                    補足: {targetIdentityLabel}
                  </Badge>
                  <span>{identityState.nextBestAction}</span>
                </div>
              </section>

              <section className="order-3 rounded-2xl border border-primary/20 bg-card p-4 sm:p-5 lg:order-4">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div className="space-y-1">
                    <p className="text-sm font-semibold text-foreground">ここまでで開始できます</p>
                    <p className="text-xs leading-6 text-muted-foreground">
                      概要があれば開始できます。会社名やサービス名が未定でも、必要になった時点で後から補足できます。
                    </p>
                  </div>
                  <Button
                    onClick={() => void runResearch()}
                    disabled={!trimmedSpec || Boolean(identityWebsiteError) || isPreparing}
                    className="w-full gap-2 lg:w-auto lg:min-w-[17rem]"
                    size="lg"
                  >
                    <Search className="h-4 w-4" />
                    この内容で調査を開始
                  </Button>
                </div>
                {!trimmedSpec && (
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-amber-700">
                    <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1">
                      プロダクト概要を入力してください
                    </span>
                  </div>
                )}
                {identityWebsiteError && (
                  <p className="mt-3 text-xs leading-6 text-destructive">{identityWebsiteError}</p>
                )}
              </section>

              <section className="order-5 rounded-2xl border border-border bg-background p-4">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((value) => !value)}
                  aria-expanded={showAdvanced}
                  aria-controls={researchAdvancedSectionId}
                  className="flex w-full items-center justify-between gap-3 text-left"
                >
                  <div>
                    <p className="text-sm font-medium text-foreground">3. 補足設定で精度を上げる</p>
                    <p className="text-xs leading-6 text-muted-foreground">
                      任意。公式サイト、別名、競合 URL、調査深度を追加したいときだけ開いてください。
                    </p>
                  </div>
                  {showAdvanced ? (
                    <ChevronUp className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  )}
                </button>

                {showAdvanced && (
                  <div id={researchAdvancedSectionId} className="mt-4 space-y-5 border-t border-border pt-4">
                    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.92fr)]">
                      <div className="space-y-4 rounded-xl border border-border bg-card p-4">
                        <div className="flex items-center gap-2">
                          <Globe className="h-4 w-4 text-primary" />
                          <p className="text-sm font-medium text-foreground">検索軸を補う</p>
                        </div>

                        <div>
                          <div className="mb-1.5 flex items-center gap-2">
                            <label htmlFor={websiteFieldId} className="block text-sm font-medium text-foreground">公式サイト</label>
                            <Badge variant="optional" size="field" className="border-slate-200 bg-slate-50 text-slate-700">任意</Badge>
                          </div>
                          <input
                            id={websiteFieldId}
                            value={productIdentity.officialWebsite ?? ""}
                            onChange={(e) => updateProductIdentityField({ officialWebsite: e.target.value })}
                            onBlur={(e) => updateProductIdentityField({ officialWebsite: normalizeIdentityWebsite(e.target.value) })}
                            placeholder="https://example.com"
                            aria-invalid={Boolean(identityWebsiteError)}
                            aria-describedby={websiteHelpId}
                            className={cn(
                              "w-full rounded-lg border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring",
                              identityWebsiteError ? "border-destructive/40" : "border-border",
                            )}
                          />
                          <p id={websiteHelpId} className={cn("mt-1 text-[11px]", identityWebsiteError ? "text-destructive" : "text-muted-foreground")}>
                            {identityWebsiteError || "公式ドメインは自動で抽出して research の anchor に使います。"}
                          </p>
                        </div>

                        <div>
                          <div className="mb-1.5 flex items-center gap-2">
                            <label htmlFor={aliasesFieldId} className="block text-sm font-medium text-foreground">別名・略称</label>
                            <Badge variant="optional" size="field" className="border-slate-200 bg-slate-50 text-slate-700">任意</Badge>
                          </div>
                          <input
                            id={aliasesFieldId}
                            value={joinIdentityList(productIdentity.aliases)}
                            onChange={(e) => updateProductIdentityField({ aliases: normalizeIdentityListInput(e.target.value) })}
                            placeholder="例: Pylon AI, Pylon Platform"
                            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                          />
                          <p className="mt-1 text-[11px] text-muted-foreground">カンマ区切りで入力します。</p>
                        </div>

                        <div>
                          <div className="mb-1.5 flex items-center gap-2">
                            <label htmlFor={excludedEntitiesFieldId} className="block text-sm font-medium text-foreground">除外したい同名サービス / 会社名</label>
                            <Badge variant="optional" size="field" className="border-slate-200 bg-slate-50 text-slate-700">任意</Badge>
                          </div>
                          <input
                            id={excludedEntitiesFieldId}
                            value={joinIdentityList(productIdentity.excludedEntityNames)}
                            onChange={(e) => updateProductIdentityField({ excludedEntityNames: normalizeIdentityListInput(e.target.value) })}
                            placeholder="例: Basler pylon, AppMatch Pylon"
                            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                          />
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            既知の同名プロダクトがある場合に入力します。source の隔離に使います。
                          </p>
                        </div>
                      </div>

                      <div className="space-y-4 rounded-xl border border-border bg-card p-4">
                        <div className="flex items-center gap-2">
                          <Zap className="h-4 w-4 text-primary" />
                          <p className="text-sm font-medium text-foreground">調査条件を調整する</p>
                        </div>

                        <div>
                          <label htmlFor={competitorUrlFieldId} className="mb-1.5 block text-sm font-medium text-foreground">競合 URL</label>
                          <div className="flex gap-2">
                            <input
                              id={competitorUrlFieldId}
                              value={newUrl}
                              onChange={(e) => setNewUrl(e.target.value)}
                              placeholder="https://competitor.com"
                              className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                              onKeyDown={(e) => e.key === "Enter" && addUrl()}
                            />
                            <button type="button" aria-label="競合 URL を追加" onClick={addUrl} className="rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
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
                                    className="ml-0.5 rounded-full p-0.5 hover:bg-foreground/10"
                                  >
                                    <X className="h-3 w-3" />
                                  </button>
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>

                        <div>
                          <div id={depthFieldId} className="mb-1.5 block text-sm font-medium text-foreground">調査深度</div>
                          <div role="group" aria-labelledby={depthFieldId} className="grid gap-2">
                            {([["quick", "簡易", "競合 2-3 社の基本分析"], ["standard", "標準", "競合 + 市場 + 技術評価"], ["deep", "詳細", "包括的な機会 / 脅威整理と提言"]] as const).map(([val, label, desc]) => (
                              <button
                                key={val}
                                type="button"
                                onClick={() => actions.updateResearchConfig({ ...lc.researchConfig, depth: val })}
                                className={cn(
                                  "rounded-lg border p-3 text-left transition-colors",
                                  depth === val ? "border-primary bg-primary/5" : "border-border hover:bg-accent/50",
                                )}
                              >
                                <div className="flex items-center justify-between gap-3">
                                  <p className="text-sm font-medium text-foreground">{label}</p>
                                  {depth === val && <ArrowRight className="h-4 w-4 text-primary" />}
                                </div>
                                <p className="mt-1 text-[11px] text-muted-foreground">{desc}</p>
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="rounded-xl border border-border bg-card p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="assistive" size="field" className="border-slate-200 bg-slate-50 text-slate-700">
                          未入力でも補完
                        </Badge>
                        <p className="text-sm font-medium text-foreground">AI が先回りして行うこと</p>
                      </div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        {(identityAutofillMessages.length > 0
                          ? identityAutofillMessages
                          : ["任意項目は十分に入力されています。AI は入力された値を優先して検索軸と隔離条件を固定します。"]).map((item) => (
                            <div key={item} className="flex items-start gap-2 rounded-lg border border-border bg-background px-3 py-3 text-sm leading-6 text-muted-foreground">
                              <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                              <span>{item}</span>
                            </div>
                          ))}
                      </div>
                    </div>
                  </div>
                )}
              </section>
            </div>

            <aside className="space-y-4 xl:sticky xl:top-6 xl:self-start">
              <div className="rounded-2xl border border-border bg-card p-5">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground/70">この画面で決めること</p>
                <div className="mt-4 space-y-3">
                  {[
                    "調査対象をどの会社 / 製品として扱うか",
                    "何を調べたいかの骨子",
                    "必要なら検索精度を上げる補足条件",
                  ].map((item) => (
                    <div key={item} className="flex items-start gap-2 rounded-lg border border-border bg-background px-3 py-3 text-sm text-foreground">
                      <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>

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
            </aside>
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
    const pulseAgents = applyWarmupMotion(researchAgents.map((agent) => {
      const item = progress.find((entry) => entry.nodeId === agent.id || entry.agent === agent.id || entry.agent === agent.label);
      return {
        id: agent.id,
        label: agent.label,
        status: item?.status ?? "pending",
        currentTask: item?.status === "running"
          ? `${agent.label} が現在の調査タスクを処理中`
          : item?.status === "completed"
            ? `${agent.label} が担当領域の一次調査を完了`
            : "上流エージェントからの文脈を待機中",
      };
    }));
    const pulseActions = pulseAgents
      .filter((agent, index) => index < pulseAgents.length - 1)
      .map((agent, index) => ({
        id: `${agent.id}:${index}`,
        label: agent.label,
        summary: agent.currentTask,
        status: agent.status,
        from: agent.label,
        to: pulseAgents[index + 1]?.label,
      }));
    const pulseEvents = progress
      .filter((item) => item.status !== "pending")
      .map((item) => ({
        id: `${item.nodeId}:${item.status}`,
        label: formatResearchNodeLabel(item.nodeId),
        summary:
          item.status === "running"
            ? "新しい根拠を収集中で、企画に渡せる形へ正規化しています。"
            : item.status === "completed"
              ? "検証済みの根拠を次の専門担当へ引き継ぎました。"
              : "統合前に、このノードの再確認が必要です。",
      }));
    const pulseTimeline = buildResearchPulseTimeline(pulseAgents);
    return (
      <div className="flex h-full flex-col overflow-y-auto p-6">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
          <MultiAgentCollaborationPulse
            title="リサーチオーケストラが進行中"
            subtitle="市場・競合・ユーザー・技術の専門エージェントが、企画に渡す根拠をリアルタイムで交換しています。"
            elapsedLabel={formatPulseElapsedLabel(workflow.elapsedMs)}
            agents={pulseAgents}
            actions={pulseActions}
            events={pulseEvents}
            timeline={pulseTimeline}
          />
          <div className="rounded-[24px] border border-border/70 bg-card/70 px-5 py-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground/70">レビュー視点</p>
                <p className="mt-1 text-sm text-foreground">
                  上段がマルチエージェントの協調ビューです。並列レーンと逐次ハンドオフを分離して表示しています。
                </p>
              </div>
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                現在の実行を継続監視中
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Results
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/80 bg-background/95 px-6 py-4 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1180px] flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className={cn("border text-[11px]", trustBadgeTone)}>
                {researchReady ? "調査通過" : hasGuardedPlanningHandoff ? "条件付き" : "要見直し"}
              </Badge>
              <Badge variant="outline" className="bg-background/80 text-[11px] text-muted-foreground">
                有効根拠 {researchAudit.trustedEvidenceCount} 件
              </Badge>
            </div>
            <div className="space-y-1">
              <p className="text-[11px] uppercase tracking-[0.24em] text-muted-foreground/70">調査レビュー</p>
              <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
                {researchReady ? <Check className="h-5 w-5 text-success" /> : <AlertCircle className="h-5 w-5 text-amber-500" />}
                調査結果
              </h1>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                企画に渡す前に、信頼できる根拠と隔離した項目を切り分けて確認します。
              </p>
            </div>
          </div>
          <div className="flex flex-col items-start gap-2 sm:items-end">
            <button
              onClick={goNext}
              disabled={!canProceedToPlanning}
              className={cn(
                "inline-flex items-center justify-center gap-1.5 rounded-full border px-4 py-2.5 text-sm font-medium transition-all",
                canProceedToPlanning
                  ? "border-primary/25 bg-primary text-primary-foreground shadow-[0_18px_45px_-28px_hsl(var(--primary))] hover:-translate-y-0.5 hover:bg-primary/90"
                  : "cursor-not-allowed border-border bg-muted/80 text-muted-foreground",
              )}
            >
              {planningCtaLabel} <ArrowRight className="h-4 w-4" />
            </button>
            {!canProceedToPlanning && (
              <p className="text-xs text-muted-foreground">
                進める前に、停止理由と隔離項目を先に解消してください。
              </p>
            )}
            {!researchReady && hasPlanningReviewAccess && (
              <p className="text-xs text-muted-foreground">
                企画側のレビュー素材は既にあるため、research の見直しを残したまま企画レビューへ戻れます。
              </p>
            )}
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex max-w-[1180px] flex-col gap-6">
          {errorMessage && (
            <div className="flex flex-col gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-destructive sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                  <div>
                  <p className="text-sm font-semibold">前回の調査は失敗しました。</p>
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
          {!researchReady && research && (
            <div className="rounded-[28px] border border-border/80 bg-card/95 p-5 shadow-[0_22px_55px_-44px_rgba(15,23,42,0.45)]">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-3">
                  <div className="space-y-1">
                    <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground/70">
                      回復オペレーション
                    </p>
                    <h2 className="text-lg font-semibold text-foreground">
                      {isAutonomousRecoveryActive
                        ? "AI が不足根拠を補完しています"
                        : hasGuardedPlanningHandoff
                          ? "持ち込む前提を固定して企画へ渡します"
                          : "次に変える観点をここで決めます"}
                    </h2>
                    <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                      {activeStrategySummary}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {hasGuardedPlanningHandoff ? (
                      <Badge variant="outline" className="bg-background/80">
                        現在状態: {formatResearchOperatorAction(recommendedOperatorAction)}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-background/80">
                        現在戦略: {formatResearchRecoveryMode(activeRecoveryMode)}
                      </Badge>
                    )}
                    {autonomousRemediation?.stalledSignature && (
                      <Badge variant="outline" className="bg-background/80 text-amber-700">
                        同じ阻害要因が継続中
                      </Badge>
                    )}
                    {recommendedOperatorAction && !isAutonomousRecoveryActive && (
                      <Badge variant="outline" className="bg-background/80">
                        推奨: {formatResearchOperatorAction(recommendedOperatorAction)}
                      </Badge>
                    )}
                  </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 lg:min-w-[320px]">
                  <div className="rounded-xl border border-border/80 bg-background px-3 py-3">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">残り自動補完</p>
                    <p className="mt-2 text-xl font-semibold text-foreground">{autonomousRemediation?.remainingAttempts ?? 0}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {autonomousRemediation?.maxAttempts ? `上限 ${autonomousRemediation.maxAttempts} 回` : "自動補完の上限未設定"}
                    </p>
                  </div>
                  <div className="rounded-xl border border-border/80 bg-background px-3 py-3">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">未解決論点</p>
                    <p className="mt-2 text-xl font-semibold text-foreground">{trustedOpenQuestions.length}</p>
                    <p className="text-[11px] text-muted-foreground">未解決の前提として管理が必要</p>
                  </div>
                  <div className="rounded-xl border border-border/80 bg-background px-3 py-3">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">条件付き前提</p>
                    <p className="mt-2 text-xl font-semibold text-foreground">{planningGuardrails.length}</p>
                    <p className="text-[11px] text-muted-foreground">企画に持ち込む前提条件の件数</p>
                  </div>
                  <div className="rounded-xl border border-border/80 bg-background px-3 py-3">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">要再確認ノード</p>
                    <p className="mt-2 text-xl font-semibold text-foreground">
                      {(r.node_results ?? []).filter((node) => node.status !== "success").length}
                    </p>
                    <p className="text-[11px] text-muted-foreground">品質が揺れている担当レーン</p>
                  </div>
                </div>
              </div>

              {!hasGuardedPlanningHandoff && autonomousRemediation?.strategyChecklist?.length ? (
                <div className="mt-4 rounded-xl border border-primary/15 bg-primary/5 p-4">
                  <p className="text-xs font-medium text-foreground">今回の回復で変えること</p>
                  <div className="mt-2 space-y-1.5">
                    {autonomousRemediation.strategyChecklist.map((item) => (
                      <p key={item} className="text-xs text-muted-foreground">• {item}</p>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 p-4">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-foreground">{primaryRecoveryActionLabel}</p>
                    <p className="text-xs text-muted-foreground">
                      {primaryRecoveryActionDescription}
                    </p>
                  </div>
                  <Button
                    type="button"
                    className="gap-1.5"
                    onClick={() => void handlePrimaryRecoveryAction()}
                    disabled={isPreparing || workflow.status === "running" || workflow.status === "starting" || (conditionalHandoffAllowed && recommendedOperatorAction === "conditional_handoff" && isAutonomousRecoveryActive)}
                  >
                    {primaryRecoveryActionLabel} <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
                {conditionalHandoffAllowed && recommendedOperatorAction === "conditional_handoff" && isAutonomousRecoveryActive && (
                  <p className="mt-2 text-[11px] text-primary/80">
                    自動回復が残っている間は、まず AI 側の最後の回復を完了させます。
                  </p>
                )}
              </div>

              <div className="mt-4 rounded-xl border border-border bg-background p-4">
                <button
                  type="button"
                  onClick={() => setShowManualRecoveryOptions((value) => !value)}
                  className="flex w-full items-center justify-between gap-3 text-left"
                >
                  <div>
                    <p className="text-sm font-medium text-foreground">必要なら回復戦略を固定する</p>
                    <p className="text-xs text-muted-foreground">
                      通常は AI に任せてください。オペレーターが再調査の軸を明示的に固定したいときだけ使います。
                    </p>
                  </div>
                  {showManualRecoveryOptions ? (
                    <ChevronUp className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  )}
                </button>

                {showManualRecoveryOptions && (
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-border bg-card p-4">
                      <div className="flex items-start gap-3">
                        <div className="rounded-lg bg-primary/10 p-2 text-primary">
                          <Search className="h-4 w-4" />
                        </div>
                        <div className="space-y-1">
                          <p className="text-sm font-medium text-foreground">根拠を深掘り</p>
                          <p className="text-xs text-muted-foreground">
                            公式ページ、料金、第三者レポートを増やし、confidence floor を押し上げます。
                          </p>
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        className="mt-4 w-full"
                        onClick={() => void runResearch({ recoveryMode: "deepen_evidence" })}
                        disabled={isPreparing || workflow.status === "running" || workflow.status === "starting"}
                      >
                        この方針で再実行
                      </Button>
                    </div>

                    <div className="rounded-xl border border-border bg-card p-4">
                      <div className="flex items-start gap-3">
                        <div className="rounded-lg bg-amber-500/10 p-2 text-amber-700">
                          <Route className="h-4 w-4" />
                        </div>
                        <div className="space-y-1">
                          <p className="text-sm font-medium text-foreground">観点を切り替えて再調査</p>
                          <p className="text-xs text-muted-foreground">
                            対象セグメント、導入障壁、運用統制など別の評価軸で問いを切り直します。
                          </p>
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        className="mt-4 w-full"
                        onClick={() => void runResearch({ recoveryMode: "reframe_research" })}
                        disabled={isPreparing || workflow.status === "running" || workflow.status === "starting"}
                      >
                        観点を変えて再実行
                      </Button>
                    </div>
                  </div>
                )}
              </div>

              {planningGuardrails.length > 0 && (
                <div className="mt-4 rounded-xl border border-border bg-background p-4">
                  <p className="text-xs font-medium text-foreground">条件付きで企画へ進むときに持ち込む前提</p>
                  <div className="mt-2 space-y-1.5">
                    {planningGuardrails.map((item) => (
                      <p key={item} className="text-xs text-muted-foreground">• {item}</p>
                    ))}
                  </div>
                </div>
              )}

              {followUpQuestion && (
                <div className="mt-4 rounded-xl border border-dashed border-border px-4 py-3">
                  <p className="text-xs font-medium text-foreground">次に確認したい問い</p>
                  <p className="mt-1 text-xs text-muted-foreground">{followUpQuestion}</p>
                </div>
              )}
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
                <MultiAgentCollaborationPulse
                  compact
                  title="複数エージェントが再調査を継続中"
                  subtitle="現在の結果を表示したまま、専門エージェントが弱い根拠を洗い直し、更新差分を裏で組み立てています。"
                  elapsedLabel={formatPulseElapsedLabel(runtimeResearchElapsedMs)}
                  agents={runtimePulseAgents}
                  actions={runtimeRecentActions.map((action) => ({
                    id: `${action.nodeId}:${action.summary}`,
                    label: action.agentLabel ?? action.label,
                    summary: action.summary,
                    status: action.status,
                    from: action.agentLabel ?? action.label,
                    to: runtimePulseAgents.find((agent) => agent.id === action.nodeId)?.delegatedTo,
                  })).length > 0
                    ? runtimeRecentActions.map((action) => ({
                      id: `${action.nodeId}:${action.summary}`,
                      label: action.agentLabel ?? action.label,
                      summary: action.summary,
                      status: action.status,
                      from: action.agentLabel ?? action.label,
                      to: runtimePulseAgents.find((agent) => agent.id === action.nodeId)?.delegatedTo,
                    }))
                    : runtimePulseAgents
                      .filter((agent, index) => index < runtimePulseAgents.length - 1)
                      .map((agent, index) => ({
                        id: `${agent.id}:warmup:${index}`,
                        label: agent.label,
                        summary: agent.currentTask ?? "共有コンテキストを次の専門担当へ引き渡しています。",
                        status: agent.status,
                        from: agent.label,
                        to: runtimePulseAgents[index + 1]?.label,
                      }))}
                  events={runtimeRecentEvents.map((event) => ({
                    id: `${event.seq ?? "evt"}:${event.nodeId}`,
                    label: event.agent ?? formatResearchNodeLabel(event.nodeId),
                    summary: event.summary,
                    timestamp: formatLiveEventTimestamp(event.timestamp),
                  }))}
                  timeline={runtimePulseTimeline}
                />
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

          <section ref={decisionSummarySectionRef} className="order-first">
            <div className="grid gap-4 xl:items-start xl:grid-cols-[minmax(0,1.18fr)_0.82fr]">
              <div className={cn("relative self-start overflow-hidden rounded-[28px] border px-5 py-6 sm:px-6 sm:py-7 shadow-[0_22px_52px_-42px_rgba(15,23,42,0.34)]", trustTone)}>
                <div className="relative space-y-6">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={cn("border text-[11px]", trustBadgeTone)}>
                      {researchReady ? "調査信頼性: 通過" : hasGuardedPlanningHandoff ? "調査信頼性: 条件付き" : "調査信頼性: 要見直し"}
                    </Badge>
                    <Badge variant="outline" className="border-slate-950/10 bg-white/70 text-[11px] text-slate-700">
                      採用根拠 {researchAudit.trustedEvidenceCount}/{Math.max(researchAudit.totalEvidenceCount, 1)}
                    </Badge>
                    <Badge variant="outline" className="border-slate-950/10 bg-white/70 text-[11px] text-slate-700">
                      隔離 {researchAudit.quarantinedCount} 件
                    </Badge>
                  </div>

                  <div className="grid gap-6 xl:grid-cols-[minmax(0,1.02fr)_0.98fr]">
                    <div className="space-y-6">
                      <div className="space-y-3">
                        <p className="text-[11px] uppercase tracking-[0.22em] text-slate-600">調査信頼性</p>
                        <h2 className="max-w-2xl font-serif text-[30px] leading-[1.15] text-slate-950 sm:text-[36px]">
                          {trustHeadline}
                        </h2>
                        <p className="max-w-2xl text-sm leading-7 text-slate-700 sm:text-[15px]">
                          {trustSummary}
                        </p>
                      </div>

                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className={trustMetricCardClass}>
                          <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">採用根拠</p>
                          <p className="mt-2 text-3xl font-semibold text-slate-950">{researchAudit.trustedEvidenceCount}</p>
                          <p className="mt-1 text-[11px] leading-5 text-slate-600">企画判断に残す競合と外部根拠の件数</p>
                        </div>
                        <div className={trustMetricCardClass}>
                          <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">隔離件数</p>
                          <p className="mt-2 text-3xl font-semibold text-slate-950">{researchAudit.quarantinedCount}</p>
                          <p className="mt-1 text-[11px] leading-5 text-slate-600">対象外候補、記事断片、破損値を退避しています</p>
                        </div>
                        <div className={trustMetricCardClass}>
                          <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{confidenceMetricLabel}</p>
                          <p className="mt-2 text-3xl font-semibold text-slate-950">{(confidenceFloor * 100).toFixed(0)}%</p>
                          <p className="mt-1 text-[11px] leading-5 text-slate-600">{confidenceMetricDescription}</p>
                        </div>
                        <div className={trustMetricCardClass}>
                          <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">有力仮説</p>
                          <p className="mt-2 text-3xl font-semibold text-slate-950">{trustedWinningTheses.length}</p>
                          <p className="mt-1 text-[11px] leading-5 text-slate-600">監査後に企画へ残せる判断論点の数</p>
                        </div>
                      </div>
                    </div>

                    <div className="grid content-start gap-3 min-w-0">
                      <div className={trustSupportCardClass}>
                        <p className="text-sm font-medium text-slate-950">調査対象のロック</p>
                        <div className="mt-4 space-y-2 text-sm leading-6 text-slate-700">
                          <p className="break-words"><span className="text-slate-500">対象:</span> {targetIdentityLabel}</p>
                          <p className="break-words">
                            <span className="text-slate-500">公式ドメイン:</span>{" "}
                            {productIdentity.officialDomains.length > 0 ? productIdentity.officialDomains.join(" / ") : "未登録"}
                          </p>
                          <p className="break-words">
                            <span className="text-slate-500">除外対象:</span>{" "}
                            {productIdentity.excludedEntityNames.length > 0 ? productIdentity.excludedEntityNames.join(" / ") : "未登録"}
                          </p>
                        </div>
                      </div>

                      <div className={trustSupportCardClass}>
                        <p className="text-sm font-medium text-slate-950">この画面で先に見てよいもの</p>
                        <div className="mt-4 space-y-2.5">
                          {trustFocusPoints.map((item) => (
                            <p key={item} className="break-words text-sm leading-6 text-slate-700">• {item}</p>
                          ))}
                        </div>
                      </div>

                      <div className={trustSupportCardClass}>
                        <p className="text-sm font-medium text-slate-950">信頼できる外部根拠</p>
                        {trustedSourceHosts.length > 0 ? (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {trustedSourceHosts.map((host) => (
                              <Badge key={host} variant="outline" className="border-slate-300 bg-white px-3 py-1 text-[11px] text-slate-800">
                                {host}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-4 text-sm leading-6 text-slate-700">
                            信頼できる外部リンクはまだ十分に残っていません。隔離した項目を確認してください。
                          </p>
                        )}
                        {!!r.judge_summary && (
                          <p className="mt-4 text-xs leading-6 text-slate-600">
                            判定メモ: {polishResearchCopy(r.judge_summary)}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>

                  {semanticIssues.length > 0 && (
                    <div className="overflow-hidden rounded-[24px] border border-amber-300/70 bg-white/72 text-amber-950 shadow-[0_18px_42px_-34px_rgba(180,83,9,0.16)] backdrop-blur-sm">
                      <div className="flex">
                        <div className="w-1.5 shrink-0 bg-amber-300/90" />
                        <div className="flex-1 p-5 sm:p-6">
                          <div className="flex items-start gap-3">
                            <div className="rounded-full border border-amber-200 bg-amber-50 p-2 text-amber-700">
                              <AlertCircle className="h-4 w-4" />
                            </div>
                            <div>
                              <p className="text-[11px] uppercase tracking-[0.18em] text-amber-700">停止理由</p>
                              <p className="mt-1 text-sm font-medium text-slate-950">この調査を止めている理由</p>
                            </div>
                          </div>
                          <div className="mt-4 grid gap-2.5 sm:gap-3">
                            {semanticIssues.map((issue) => (
                              <div key={issue} className="rounded-[18px] border border-amber-200/80 bg-amber-50/70 px-3.5 py-3">
                                <p className="break-words text-sm leading-6 text-slate-900">{issue}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="grid content-start gap-3">
                <div className={trustAsideCardClass}>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">監査ログ</p>
                      <p className="mt-1 text-sm font-medium text-foreground">隔離した項目</p>
                    </div>
                    <Badge variant="outline" className="border-border/70 bg-background text-[10px] text-muted-foreground">
                      {researchAudit.findings.length} 件
                    </Badge>
                  </div>
                  {researchAudit.findings.length > 0 ? (
                    <div className="mt-4 space-y-2">
                      {researchAudit.findings.slice(0, 5).map((finding) => (
                        <div key={finding.id} className="rounded-[18px] border border-border/70 bg-background/84 px-3 py-3">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-xs font-medium text-foreground">{finding.label}</p>
                              <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{finding.reason}</p>
                              {finding.detail && (
                                <p className="mt-2 break-words text-[11px] leading-5 text-muted-foreground/90">{finding.detail}</p>
                              )}
                            </div>
                            <Badge variant="secondary" className="shrink-0 border border-border/70 bg-background text-[10px] text-muted-foreground">
                              {finding.category === "market_size" ? "破損" : "隔離"}
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-4 text-sm leading-6 text-muted-foreground">
                      隔離対象はありません。上段の主要示唆をそのまま企画判断に使えます。
                    </p>
                  )}
                </div>
              </div>
            </div>
          </section>

          <section className="order-first">
            <nav
              aria-label="ページ内移動"
              className="rounded-[20px] border border-border/80 bg-card/70 px-4 py-3 shadow-[0_12px_30px_-26px_rgba(15,23,42,0.28)]"
            >
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">読み順</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    進行可否を決めてから、根拠の中身へ降ります。
                  </p>
                </div>
                <p className="text-xs text-muted-foreground">監査後に残った論点 {trustedDecisionCount} 件</p>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {reviewRailItems.map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    onClick={() => scrollToSection(item.ref)}
                    aria-label={`${item.label}へ移動`}
                    className="group inline-flex items-center gap-2 rounded-full border border-border/80 bg-background/80 px-3 py-2 text-xs text-foreground transition-colors hover:border-primary/30 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    <item.icon className="h-3.5 w-3.5 text-primary" />
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </nav>
          </section>

          <section ref={peopleSectionRef} className="space-y-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div className="space-y-2">
                <p className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground/70">人と仕事の構造</p>
                <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-[30px]">
                  ユーザー理解を、企画に渡せるフレームへ変換します
                </h2>
                <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
                  {experienceFrames.personaSummary}
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                {experienceFrames.designPrinciples.map((principle) => (
                  <div key={principle} className={cn(sectionSubtleCardClass, "p-3 text-sm leading-6 text-foreground")}>
                    {principle}
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[28px] border border-border/80 bg-card/94 p-5 shadow-[0_18px_44px_-36px_rgba(15,23,42,0.32)] sm:p-6">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">ユーザージャーニー仮説</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {experienceFrames.personaLabel} が比較から導入判断、運用定着まで進むときの主な判断点です。
                  </p>
                </div>
                <Badge variant="outline" className="bg-background text-[11px] text-muted-foreground">
                  5 フェーズで整理
                </Badge>
              </div>

              <div className="mt-5 grid gap-3 xl:grid-cols-5">
                {experienceFrames.userJourney.touchpoints.map((touchpoint) => (
                  <div key={touchpoint.phase} className={cn(sectionSubtleCardClass, "min-w-0")}>
                    <div className="flex items-center justify-between gap-2">
                      <Badge className={cn("border text-[10px]", JOURNEY_EMOTION_CLASS[touchpoint.emotion])}>
                        {JOURNEY_PHASE_LABELS[touchpoint.phase]}
                      </Badge>
                      <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{touchpoint.touchpoint}</span>
                    </div>
                    <p className="mt-4 break-words text-sm font-medium leading-6 text-foreground">{touchpoint.action}</p>
                    {touchpoint.pain_point && (
                      <p className="mt-3 break-words text-xs leading-5 text-muted-foreground">
                        摩擦: {touchpoint.pain_point}
                      </p>
                    )}
                    {touchpoint.opportunity && (
                      <p className="mt-2 break-words text-xs leading-5 text-muted-foreground">
                        価値機会: {touchpoint.opportunity}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_0.92fr] xl:items-start">
              <div className={sectionCardClass}>
                <div className="flex items-center gap-2">
                  <Lightbulb className="h-4 w-4 text-primary" />
                  <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">ユーザーストーリー</p>
                </div>
                <div className="mt-4 space-y-3">
                  {experienceFrames.userStories.map((story, index) => (
                    <div key={`${story.action}-${index}`} className={cn(sectionSubtleCardClass, "min-w-0")}>
                      <p className="break-words text-sm font-medium text-foreground">
                        {story.role} は、{story.action}。そうすることで {story.benefit}。
                      </p>
                      <div className="mt-3 space-y-1.5">
                        {story.acceptance_criteria.slice(0, 2).map((item) => (
                          <p key={item} className="text-xs leading-5 text-muted-foreground">• {item}</p>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className={sectionCardClass}>
                <div className="flex items-center gap-2">
                  <Briefcase className="h-4 w-4 text-primary" />
                  <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">ジョブストーリー / JTBD</p>
                </div>
                <div className="mt-4 space-y-3">
                  {experienceFrames.jobStories.map((story) => (
                    <div key={story.situation} className={cn(sectionSubtleCardClass, "min-w-0")}>
                      <Badge variant="outline" className="bg-background text-[10px] text-muted-foreground">
                        {story.priority === "core" ? "中核ジョブ" : story.priority === "supporting" ? "補助ジョブ" : "将来価値"}
                      </Badge>
                      <p className="mt-3 break-words text-sm leading-6 text-foreground">
                        {story.situation}、{story.motivation}。そうすれば {story.outcome}。
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {story.related_features.map((item) => (
                          <Badge key={item} variant="secondary" className="text-[10px]">{item}</Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className={sectionCardClass}>
                <div className="flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-primary" />
                  <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">KANO 仮説</p>
                </div>
                <div className="mt-4 space-y-3">
                  {experienceFrames.kanoFeatures.map((feature) => (
                    <div key={feature.feature} className={cn(sectionSubtleCardClass, "min-w-0")}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="break-words text-sm font-medium text-foreground">{feature.feature}</p>
                          <p className="mt-1 break-words text-[11px] leading-5 text-muted-foreground">{feature.rationale}</p>
                        </div>
                        <Badge className={cn("border text-[10px]", KANO_TONE_CLASS[feature.category])}>
                          {KANO_LABEL[feature.category]}
                        </Badge>
                      </div>
                      <div className="mt-4">
                        <div className="h-2 overflow-hidden rounded-full bg-muted">
                          <div
                            className={cn(
                              "h-full rounded-full",
                              feature.category === "must-be"
                                ? "bg-rose-500"
                                : feature.category === "one-dimensional"
                                  ? "bg-sky-500"
                                  : feature.category === "attractive"
                                    ? "bg-emerald-500"
                                    : feature.category === "reverse"
                                      ? "bg-violet-500"
                                      : "bg-slate-400",
                            )}
                            style={{ width: `${feature.user_delight * 100}%` }}
                          />
                        </div>
                        <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                          <span>期待価値 {(feature.user_delight * 100).toFixed(0)}%</span>
                          <span>実装コスト {feature.implementation_cost === "low" ? "低" : feature.implementation_cost === "medium" ? "中" : "高"}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-border/80 bg-card/94 p-5 shadow-[0_18px_44px_-36px_rgba(15,23,42,0.32)] sm:p-6">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">IA 仮説</p>
                  <h3 className="mt-1 text-xl font-semibold text-foreground">この調査画面が従うべき情報設計</h3>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                    まず進めるか止めるかを判断し、その後に人と仕事、市場妥当性、残課題へ降りるハブ&スポーク構成が最も自然です。
                  </p>
                </div>
                <Badge variant="outline" className="bg-background text-[11px] text-muted-foreground">
                  ナビゲーションモデル: ハブ&スポーク
                </Badge>
              </div>

              <div className="mt-5 grid gap-4 xl:grid-cols-[1.1fr_0.9fr] xl:items-start">
                <div className="grid gap-3 sm:grid-cols-2">
                  {experienceFrames.iaAnalysis.site_map.map((node) => (
                    <div key={node.id} className={cn(sectionSubtleCardClass, "min-w-0")}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-foreground">{node.label}</p>
                        <Badge variant="outline" className="bg-background text-[10px] text-muted-foreground">
                          {node.priority === "primary" ? "主要" : node.priority === "secondary" ? "補助" : "補助導線"}
                        </Badge>
                      </div>
                      {node.description && (
                        <p className="mt-2 break-words text-[11px] leading-5 text-muted-foreground">{node.description}</p>
                      )}
                      <div className="mt-3 flex flex-wrap gap-2">
                        {(node.children ?? []).map((child) => (
                          <Badge key={child.id} variant="secondary" className="border border-border/70 bg-background text-[10px] text-foreground">
                            {child.label}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                <div className={cn(sectionSubtleCardClass, "p-4")}>
                  <p className="text-sm font-medium text-foreground">主要パス</p>
                  <div className="mt-4 space-y-3">
                    {experienceFrames.iaAnalysis.key_paths.map((path) => (
                      <div key={path.name} className={cn(sectionSubtleCardClass, "bg-background/88 p-4")}>
                        <p className="text-sm font-medium text-foreground">{path.name}</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {path.steps.map((step) => (
                            <span key={step} className="inline-flex items-center rounded-full border border-border/70 bg-background px-3 py-1 text-[11px] text-muted-foreground">
                              {step}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <div ref={governanceSectionRef} className="space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground/70">信頼性と運用統治</p>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">企画へ渡す前の監査と実行品質</h2>
            <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
              品質ゲート、各エージェントの健全性、回復ログを一つの束として確認し、調査の信頼性を最終判断します。
            </p>
          </div>

          {!!r.quality_gates?.length && (
            <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
              <div className={cn(sectionCardClass, "p-4")}>
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-bold text-foreground">品質ゲート</h3>
                  <Badge variant={researchReady ? "default" : "secondary"} className="text-[10px]">
                    {qualityGateBadgeLabel}
                  </Badge>
                </div>
                <div className="mt-3 space-y-2">
                  {r.quality_gates.map((gate) => (
                    <div key={gate.id} className={cn(sectionSubtleCardClass, "px-3 py-3")}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">{formatResearchGateTitle(gate.id, gate.title)}</p>
                        <Badge variant={gate.passed ? "default" : "secondary"} className="text-[10px]">
                          {gate.passed ? "通過" : "未達"}
                        </Badge>
                      </div>
                      <p className="mt-1 break-words text-[11px] text-muted-foreground">{polishResearchCopy(gate.reason)}</p>
                      {!!gate.blockingNodeIds.length && (
                        <p className="mt-1 break-words text-[11px] text-muted-foreground">
                          関連ノード: {gate.blockingNodeIds.map(formatResearchNodeLabel).join(" / ")}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className={cn(sectionCardClass, "p-4")}>
                <h3 className="text-sm font-bold text-foreground">エージェント健全性</h3>
                <div className="mt-3 space-y-2">
                  {(r.node_results ?? []).map((node) => (
                    <div key={node.nodeId} className={cn(sectionSubtleCardClass, "px-3 py-3")}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">{formatResearchNodeLabel(node.nodeId)}</p>
                        <Badge variant={node.status === "success" ? "default" : "secondary"} className="text-[10px]">
                          {formatNodeStatus(node.status)}
                        </Badge>
                      </div>
                      <p className="mt-1 break-words text-[11px] text-muted-foreground">
                        応答構造: {formatParseStatus(node.parseStatus)}
                        {node.retryCount > 0 ? ` · 再試行 ${node.retryCount} 回` : ""}
                      </p>
                      {!!node.missingSourceClasses.length && (
                        <p className="mt-1 break-words text-[11px] text-muted-foreground">
                          不足ソース: {node.missingSourceClasses.map(formatSourceClassLabel).join(" / ")}
                        </p>
                      )}
                      {!!node.degradationReasons.length && (
                        <p className="mt-1 break-words text-[11px] text-muted-foreground">
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
                  <div className="mt-4 rounded-[18px] border border-primary/15 bg-primary/5 p-3">
                    <p className="text-xs font-medium text-foreground">次に補うべき内容</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{r.remediation_plan.objective}</p>
                    {!!r.remediation_plan.retryNodeIds.length && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        再調査対象: {r.remediation_plan.retryNodeIds.map(formatResearchNodeLabel).join(" / ")}
                      </p>
                    )}
                  </div>
                )}
                {shouldShowAutonomousRemediationDetail && autonomousRemediation && (
                  <div className={cn(sectionSubtleCardClass, "mt-4 p-3")}>
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
                    {!!autonomousRemediation.recoveryMode && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        回復戦略: {formatResearchRecoveryMode(autonomousRemediation.recoveryMode)}
                      </p>
                    )}
                    {!!autonomousRemediation.strategySummary && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {autonomousRemediation.strategySummary}
                      </p>
                    )}
                    {!!autonomousRemediation.retryNodeIds.length && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        補完対象: {autonomousRemediation.retryNodeIds.map(formatResearchNodeLabel).join(" / ")}
                      </p>
                    )}
                    {!!autonomousRemediation.strategyChecklist?.length && (
                      <div className="mt-2 space-y-1">
                        {autonomousRemediation.strategyChecklist.map((item) => (
                          <p key={item} className="text-[11px] text-muted-foreground">
                            • {item}
                          </p>
                        ))}
                      </div>
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
                    {!!autonomousRemediation.followUpQuestion && (
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        次に詰まったら確認したいこと: {autonomousRemediation.followUpQuestion}
                      </p>
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

          <div ref={marketSectionRef} className="space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground/70">市場と競争環境</p>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">市場妥当性、差別化、導入価値を読み解く</h2>
            <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
              企画に渡す主要示唆を軸に、市場規模、競合、機会と脅威、ユーザーシグナルを同じ面で照合します。
            </p>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.08fr)_0.92fr] xl:items-start">
            <div className="rounded-[24px] border border-primary/15 bg-primary/5 p-5 shadow-[0_18px_44px_-36px_rgba(15,23,42,0.28)]">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-primary" />
                    <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-primary/80">企画に渡す主要示唆</p>
                  </div>
                  <h3 className="mt-3 text-xl font-semibold tracking-tight text-foreground">監査後に残す仮説だけを並べます</h3>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                    記事断片や対象外の文章を除外したうえで、企画に持ち込んでよい論点だけを残しています。
                  </p>
                </div>
                {quarantinedWinningTheses.length > 0 && (
                  <Badge variant="outline" className="bg-background/80 text-[11px] text-muted-foreground">
                    隔離した仮説 {quarantinedWinningTheses.length} 件
                  </Badge>
                )}
              </div>

              {trustedWinningTheses.length > 0 ? (
                <div className="mt-5 grid gap-3 lg:grid-cols-2">
                  {trustedWinningTheses.map((thesis, index) => (
                    <div key={`${thesis}-${index}`} className="rounded-[18px] border border-primary/10 bg-background/90 p-4">
                      <p className="break-words text-sm leading-6 text-foreground">{thesis}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-5 rounded-[22px] border border-dashed border-border bg-background/70 p-4 text-sm leading-6 text-muted-foreground">
                  監査後に企画へ渡せる仮説はまだ残っていません。隔離した項目と停止理由を先に解消してください。
                </div>
              )}

              <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
                <div className={sectionSubtleCardClass}>
                  <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">判定メモ</p>
                  <p className="mt-2 break-words text-sm leading-6 text-foreground">
                    {r.judge_summary ? polishResearchCopy(r.judge_summary) : "主要示唆の採否メモはまだ整理されていません。"}
                  </p>
                </div>
                <div className={sectionSubtleCardClass}>
                  <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">扱い方</p>
                  <p className="mt-2 break-words text-sm leading-6 text-foreground">
                    {decisionQuarantineCount > 0
                      ? `対象外の主張・反対意見・未解決論点 ${decisionQuarantineCount} 件は、下段に出さず監査ログへ隔離しています。`
                      : "この面にある主要示唆は、そのまま企画の議論開始点に使えます。"}
                  </p>
                </div>
              </div>
            </div>

            <div className={sectionCardClass}>
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">根拠レビュー</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className={cn(sectionSubtleCardClass, "px-4 py-3")}>
                  <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                    <BarChart3 className="h-4 w-4" /> 市場規模
                  </div>
                  <p className="mt-2 break-words text-sm leading-6 text-foreground">
                    {researchAudit.malformedMarketSize
                      ? "破損値のため隔離しました。信頼できる市場規模の再取得が必要です。"
                      : r.market_size}
                  </p>
                </div>
                <div className={cn(sectionSubtleCardClass, "px-4 py-3")}>
                  <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                    <Zap className="h-4 w-4" /> 技術実現性
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-success" style={{ width: `${r.tech_feasibility.score * 100}%` }} />
                    </div>
                    <span className="text-sm font-bold text-foreground">{(r.tech_feasibility.score * 100).toFixed(0)}%</span>
                  </div>
                  <p className="mt-2 break-words text-[11px] leading-5 text-muted-foreground">{r.tech_feasibility.notes}</p>
                </div>
              </div>
              <div className={cn(sectionSubtleCardClass, "mt-4 px-4 py-3")}>
                <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Globe className="h-4 w-4" /> 信頼できる外部リンク
                </div>
                {trustedSourceLinks.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {trustedSourceLinks.slice(0, 6).map((url) => (
                      <a
                        key={url}
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center rounded-full border border-border bg-card px-3 py-1.5 text-[11px] text-foreground transition-colors hover:border-primary/40 hover:text-primary"
                      >
                        {formatCompetitorHost(url)}
                      </a>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-muted-foreground">
                    信頼できる外部リンクはまだ抽出できていません。
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Competitors */}
          <div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-bold text-foreground">競合分析</h3>
              {quarantinedCompetitors.length > 0 && (
                <Badge variant="outline" className="bg-background text-[11px] text-muted-foreground">
                  隔離した候補 {quarantinedCompetitors.length} 件
                </Badge>
              )}
            </div>
            {trustedCompetitors.length > 0 ? (
              <div className="grid gap-3 lg:grid-cols-3">
                {trustedCompetitors.map((c, i) => (
                  <div key={`${c.name}-${i}`} className={cn(sectionCardClass, "space-y-3 p-4")}>
                    <div className="flex items-center justify-between">
                      <h4 className="font-bold text-foreground">{c.name}</h4>
                      <Badge variant="outline" className="text-[10px]">{c.pricing}</Badge>
                    </div>
                    <p className="break-words text-[11px] text-muted-foreground">{c.target}</p>
                    <div>
                      <p className="mb-1 text-[10px] font-medium text-success">強み</p>
                      {c.strengths.map((s, j) => (
                        <p key={j} className="flex items-start gap-1 text-xs text-foreground"><Check className="mt-0.5 h-3 w-3 shrink-0 text-success" />{s}</p>
                      ))}
                    </div>
                    <div>
                      <p className="mb-1 text-[10px] font-medium text-destructive">弱み</p>
                      {c.weaknesses.map((w, j) => (
                        <p key={j} className="flex items-start gap-1 text-xs text-foreground"><ShieldAlert className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />{w}</p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-border bg-background/70 p-4 text-sm text-muted-foreground">
                競合候補はありましたが、記事や対象外ソースを隔離した結果、比較対象として残せる項目がありませんでした。
              </div>
            )}
          </div>

          {/* SWOT-like grid */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="rounded-[20px] border border-success/20 bg-success/5 p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-success mb-2"><Lightbulb className="h-4 w-4" /> 機会</h3>
              {trustedOpportunities.length > 0
                ? trustedOpportunities.map((o, i) => <p key={i} className="break-words py-0.5 text-xs text-foreground">• {o}</p>)
                : <p className="text-xs text-muted-foreground">信頼できる機会整理はまだ抽出できていません。</p>}
            </div>
            <div className="rounded-[20px] border border-destructive/20 bg-destructive/5 p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-destructive mb-2"><ShieldAlert className="h-4 w-4" /> 脅威</h3>
              {trustedThreats.length > 0
                ? trustedThreats.map((t, i) => <p key={i} className="break-words py-0.5 text-xs text-foreground">• {t}</p>)
                : <p className="text-xs text-muted-foreground">信頼できる脅威整理はまだ抽出できていません。</p>}
            </div>
          </div>

          {/* Trends */}
          <div className={cn(sectionCardClass, "p-4")}>
            <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-3"><TrendingUp className="h-4 w-4 text-primary" /> 市場トレンド</h3>
            {trustedTrends.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {trustedTrends.map((t, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">{t}</Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                市場トレンドは記事タイトルの混入を除くと、まだ十分な要約が残っていません。
              </p>
            )}
          </div>

          {!!r.user_research && (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className={cn(sectionCardClass, "p-4")}>
                <h3 className="text-sm font-bold text-foreground mb-3">ユーザーシグナル</h3>
                <div className="space-y-2">
                  {trustedUserSignals.length > 0
                    ? trustedUserSignals.map((signal, index) => (
                      <p key={index} className="break-words text-xs text-foreground">• {signal}</p>
                    ))
                    : <p className="text-xs text-muted-foreground">信頼できるユーザーシグナルはまだ抽出できていません。</p>}
                </div>
              </div>
              <div className={cn(sectionCardClass, "p-4")}>
                <h3 className="text-sm font-bold text-foreground mb-3">痛みと摩擦</h3>
                <div className="space-y-2">
                  {trustedPainPoints.length > 0
                    ? trustedPainPoints.map((pain, index) => (
                      <p key={index} className="break-words text-xs text-foreground">• {pain}</p>
                    ))
                    : <p className="text-xs text-muted-foreground">信頼できる課題仮説はまだ抽出できていません。</p>}
                </div>
              </div>
            </div>
          )}

          <div ref={questionSectionRef} className="space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground/70">主張と残課題</p>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">仮説、反証、未解決論点を企画へ接続する</h2>
            <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
              ここでは主張の強さと反証の扱い、まだ閉じていない問いを確認し、次工程での手戻りを防ぎます。
            </p>
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-bold text-foreground">主張台帳</h3>
              {quarantinedClaims.length > 0 && (
                <Badge variant="outline" className="bg-background text-[11px] text-muted-foreground">
                  隔離した主張 {quarantinedClaims.length} 件
                </Badge>
              )}
            </div>
            {trustedClaims.length > 0 ? (
              <div className="grid gap-3 xl:grid-cols-2">
                {trustedClaims.map((claim) => (
                  <div key={claim.id} className={cn(sectionCardClass, "min-w-0 p-4")}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={claim.status === "accepted" ? "default" : "secondary"} className="text-[10px]">
                          {formatClaimStatus(claim.status)}
                        </Badge>
                        <Badge variant="outline" className="text-[10px]">
                          {formatResearchNodeLabel(claim.owner)}
                        </Badge>
                        <Badge variant="outline" className="text-[10px]">
                          {formatClaimCategory(claim.category)}
                        </Badge>
                      </div>
                      <p className="text-[11px] text-muted-foreground">確信度 {(claim.confidence * 100).toFixed(0)}%</p>
                    </div>
                    <p className="mt-3 break-words text-sm leading-6 text-foreground">{claim.statement}</p>
                    <div className="mt-4 grid gap-2 sm:grid-cols-3">
                      <div className={cn(sectionSubtleCardClass, "px-3 py-2")}>
                        <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">根拠</p>
                        <p className="mt-1 text-sm font-medium text-foreground">{claim.evidence_ids.length}</p>
                      </div>
                      <div className={cn(sectionSubtleCardClass, "px-3 py-2")}>
                        <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">反証</p>
                        <p className="mt-1 text-sm font-medium text-foreground">{claim.counterevidence_ids.length}</p>
                      </div>
                      <div className={cn(sectionSubtleCardClass, "px-3 py-2")}>
                        <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">扱い</p>
                        <p className="mt-1 text-sm font-medium text-foreground">
                          {claim.status === "accepted" ? "企画候補" : "再検証"}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-[24px] border border-dashed border-border bg-background/70 p-4 text-sm leading-6 text-muted-foreground">
                監査後に残せる主張はまだありません。
                {quarantinedClaims.length > 0 ? " 記事断片や対象外ソースに紐づく主張は隔離済みです。" : ""}
              </div>
            )}
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.02fr)_0.98fr] xl:items-start">
            <div className={cn(sectionCardClass, "p-4")}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
                  <ShieldAlert className="h-4 w-4 text-destructive" /> 反対意見
                </h3>
                {quarantinedDissent.length > 0 && (
                  <Badge variant="outline" className="bg-background text-[11px] text-muted-foreground">
                    隔離した反対意見 {quarantinedDissent.length} 件
                  </Badge>
                )}
              </div>
              <div className="mt-4 space-y-3">
                {trustedDissent.length > 0 ? trustedDissent.map((item) => (
                  <div key={item.id} className={cn(sectionSubtleCardClass, "px-4 py-3")}>
                    <div className="flex items-center justify-between gap-2">
                      <Badge variant="outline" className="text-[10px]">{formatDissentSeverity(item.severity)}</Badge>
                      <p className="text-[11px] text-muted-foreground">{item.resolved ? "解決済み" : "未解決"}</p>
                    </div>
                    <p className="mt-3 break-words text-sm leading-6 text-foreground">{item.argument}</p>
                    <p className="mt-2 break-words text-[11px] leading-5 text-muted-foreground">
                      {item.recommended_test ?? "追加検証を定義"}
                    </p>
                  </div>
                )) : (
                  <p className="text-sm leading-6 text-muted-foreground">監査後に残る重大な反対意見はありません。</p>
                )}
              </div>
            </div>
            <div className={cn(sectionCardClass, "p-4")}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
                  <AlertCircle className="h-4 w-4 text-primary" /> 未解決の問い
                </h3>
                <Badge variant="outline" className="bg-background text-[11px] text-muted-foreground">
                  残り {trustedOpenQuestions.length} 件
                </Badge>
              </div>
              <div className="mt-4 space-y-3">
                {trustedOpenQuestions.length > 0 ? trustedOpenQuestions.map((question, index) => (
                  <div key={`${question}-${index}`} className={cn(sectionSubtleCardClass, "px-4 py-3")}>
                    <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">問い {index + 1}</p>
                    <p className="mt-2 break-words text-sm leading-6 text-foreground">{question}</p>
                  </div>
                )) : (
                  <p className="text-sm leading-6 text-muted-foreground">監査後に残る未解決の問いはありません。</p>
                )}
                {quarantinedOpenQuestions.length > 0 && (
                  <p className="text-[11px] leading-5 text-muted-foreground">
                    記事断片や対象外の論点 {quarantinedOpenQuestions.length} 件は監査ログへ移しています。
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
        <RequirementsPanel bundle={lc.requirements ?? null} />
        <ReverseEngineeringPanel result={lc.reverseEngineering ?? null} />
      </div>
    </div>
  );
}
