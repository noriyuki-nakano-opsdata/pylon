import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Code2,
  ExternalLink,
  Eye,
  Loader2,
  Maximize2,
  Monitor,
  Palette,
  Smartphone,
  Sparkles,
  Star,
  Tablet,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { lifecycleApi } from "@/api/lifecycle";
import { MultiAgentCollaborationPulse, type CollaborationTimelineStep } from "@/components/lifecycle/MultiAgentCollaborationPulse";
import { buildPhasePulseSnapshot } from "@/components/lifecycle/pulseUtils";
import {
  presentDecisionCoreLoop,
  presentDecisionLeadThesis,
  presentDecisionReviewItems,
  presentDecisionNorthStar,
  presentDecisionSummary,
  presentDirectionLabel,
  presentFeatureLabel,
  localizePreviewHtmlForDisplay,
  presentNamedItem,
  presentScreenText,
  presentSignatureMoment,
  presentVariantApprovalFocus,
  presentVariantApprovalPacket,
  presentVariantEstimatedCost,
  presentVariantExperienceThesis,
  presentVariantHandoffNote,
  presentVariantModelLabel,
  presentVariantOperationalBet,
  presentVariantSelectionReasons,
  presentVariantSelectionSummary,
  presentVariantTradeoffs,
  presentVariantSynopsis,
  presentVariantTitle,
} from "@/lifecycle/designDecisionPresentation";
import { buildDesignWorkflowInput } from "@/lifecycle/inputs";
import {
  downstreamTopbarClassName,
  downstreamWorkspaceClassName,
} from "@/lifecycle/downstreamTheme";
import { hasRestorablePhaseRun } from "@/lifecycle/phaseStatus";
import { BehaviorModelPanel } from "./BehaviorModelPanel";
import { TechnicalDesignPanel } from "./TechnicalDesignPanel";
import {
  selectPhaseStatus,
  selectPhaseTeam,
  selectSelectedFeatureCount,
} from "@/lifecycle/selectors";
import { persistCompletedPhase } from "@/lifecycle/phasePersistence";
import type {
  DesignVariant,
  DesignImplementationBrief,
  LifecycleDecisionContext,
  LifecycleDecisionContextIssue,
  LifecycleDecisionFrame,
  PrototypeScreen,
} from "@/types/lifecycle";

const DESIGN_AGENTS = [
  { id: "claude-designer", label: "Claude Sonnet 4.6", role: "案出し", autonomy: "A2", tools: [], skills: [] },
  { id: "gemini-designer", label: "KIMI K2.5 / Direction B", role: "案出し", autonomy: "A2", tools: [], skills: [] },
  { id: "design-evaluator", label: "デザイン審査", role: "評価", autonomy: "A2", tools: [], skills: [] },
];

type PreviewDevice = "desktop" | "tablet" | "mobile";
type DesignReviewSection = "overview" | "compare" | "prototype" | "handoff";

const DESIGN_REVIEW_SECTIONS: Array<{
  id: DesignReviewSection;
  label: string;
  summary: string;
}> = [
  { id: "overview", label: "判断概要", summary: "採用判断と現在地" },
  { id: "compare", label: "比較", summary: "2 案の差を固定軸で比較" },
  { id: "prototype", label: "試作プレビュー", summary: "実際のプレビューと画面構成を確認" },
  { id: "handoff", label: "実装引き継ぎ", summary: "実装と承認への受け渡し内容" },
];

const PREVIEW_DEVICE_LABELS: Record<PreviewDevice, string> = {
  desktop: "デスクトップ",
  tablet: "タブレット",
  mobile: "モバイル",
};

const ARTIFACT_FIELD_LABELS: Record<string, string> = {
  preview_html: "プレビューHTML",
  scorecard: "判断シート",
  selection_rationale: "選定理由",
  approval_packet: "承認パケット",
  primary_workflows: "主要フロー",
  screen_specs: "画面仕様",
  prototype_app: "実装ハンドオフ試作",
  prototype_spec: "試作仕様",
};

function buildDesignTimeline(agents: ReturnType<typeof buildPhasePulseSnapshot>["agents"]): CollaborationTimelineStep[] {
  const runningCount = agents.filter((agent) => agent.status === "running").length;
  const completedCount = agents.filter((agent) => agent.status === "completed").length;
  const evaluator = agents.find((agent) => agent.id === "design-evaluator");
  const lead = agents.find((agent) => agent.status === "running") ?? agents[0];

  return [
    {
      id: "thesis-translation",
      label: "勝ち筋の翻訳",
      detail: runningCount > 0
        ? `${runningCount} 本の設計レーンが、同じ勝ち筋を違う操作体験へ翻訳しています。`
        : "分析済みの勝ち筋を設計ブリーフとして固定しています。",
      status: runningCount > 0 || completedCount > 0 ? "completed" : "pending",
      owner: lead?.label,
      artifact: "設計ブリーフ",
    },
    {
      id: "prototype-assembly",
      label: "プロトタイプ構築",
      detail: evaluator?.status === "running"
        ? evaluator.currentTask ?? "審査担当が、各案の差分と価値の出方を比較しています。"
        : "各案が、同じ勝ち筋を別の運用リズムを持つプロダクト試作へ翻訳しています。",
      status: evaluator?.status === "completed" ? "completed" : evaluator?.status === "running" ? "running" : completedCount >= 2 ? "running" : "pending",
      owner: lead?.label,
      artifact: "比較用プロトタイプ",
    },
    {
      id: "comparative-judgement",
      label: "比較判断",
      detail: "単なる見た目ではなく、承認に渡すときの説明可能性まで含めて勝ち筋を見極めます。",
      status: completedCount >= Math.max(agents.length - 1, 1) ? "running" : "pending",
      owner: evaluator?.label,
      artifact: "選定メモ",
    },
    {
      id: "approval-packet",
      label: "承認パケット",
      detail: "選定理由、主要画面、実装で守るべき体験を一つの承認パケットに束ねます。",
      status: agents.every((agent) => agent.status === "completed") ? "completed" : "pending",
      owner: evaluator?.label,
      artifact: "承認パケット",
    },
  ];
}

function deviceWidthFor(device: PreviewDevice) {
  if (device === "mobile") return "420px";
  if (device === "tablet") return "900px";
  return "100%";
}

function deviceHeightFor(device: PreviewDevice) {
  if (device === "mobile") return "840px";
  if (device === "tablet") return "900px";
  return "880px";
}

function lifecyclePhaseLabel(phase: string | null | undefined): string {
  if (phase === "research") return "調査";
  if (phase === "planning") return "企画";
  if (phase === "design") return "デザイン";
  if (phase === "approval") return "承認";
  if (phase === "development") return "開発";
  if (phase === "deploy") return "デプロイ";
  if (phase === "iterate") return "改善";
  return "未設定";
}

function runtimeConnectionLabel(state: string | null | undefined): string {
  if (state === "live") return "ライブ接続";
  if (state === "connecting") return "接続中";
  if (state === "inactive") return "待機中";
  return state || "未接続";
}

function runStatusLabel(status: string | null | undefined): string {
  if (status === "running") return "進行中";
  if (status === "starting") return "起動中";
  if (status === "completed" || status === "review") return "完了";
  if (status === "failed") return "要確認";
  if (status === "available") return "利用可能";
  if (status === "idle") return "待機中";
  return status || "未計測";
}

function previewValidationLabel(ok: boolean): string {
  return ok ? "適合" : "要確認";
}

function localizedArtifactFieldName(field: string): string {
  return ARTIFACT_FIELD_LABELS[field] ?? presentNamedItem(field);
}

function projectFrameOf(context?: LifecycleDecisionContext | null): LifecycleDecisionFrame | null {
  return context?.project_frame ?? null;
}

function contextIssuesOf(context?: LifecycleDecisionContext | null): LifecycleDecisionContextIssue[] {
  return context?.consistency_snapshot?.issues ?? [];
}

function variantNarrativeThesis(variant: DesignVariant, frame: LifecycleDecisionFrame | null) {
  return presentVariantExperienceThesis(variant, frame);
}

function variantOperationalBet(variant: DesignVariant) {
  return presentVariantOperationalBet(variant);
}

function variantSignatureMoments(variant: DesignVariant) {
  const fromNarrative = variant.narrative?.signature_moments ?? [];
  if (fromNarrative.length > 0) return fromNarrative.map((item) => presentSignatureMoment(item));
  return (variant.prototype?.screens ?? [])
    .map((screen) => presentScreenText(screen.headline || screen.title))
    .filter((item): item is string => Boolean(item))
    .slice(0, 4);
}

function variantHandoffNote(variant: DesignVariant) {
  return presentVariantApprovalPacket(variant).handoffSummary || presentVariantHandoffNote(variant);
}

function variantSelectionSummary(variant: DesignVariant) {
  return presentVariantSelectionSummary(variant);
}

function variantSelectionReasons(variant: DesignVariant) {
  return presentVariantSelectionReasons(variant);
}

function variantTradeoffs(variant: DesignVariant) {
  return presentVariantTradeoffs(variant);
}

function variantApprovalFocus(variant: DesignVariant) {
  return presentVariantApprovalFocus(variant);
}

function variantApprovalPacket(variant: DesignVariant) {
  return presentVariantApprovalPacket(variant);
}

function scoreItems(variant: DesignVariant) {
  const scorecardDimensions = variant.scorecard?.dimensions ?? [];
  if (scorecardDimensions.length > 0) {
    return scorecardDimensions.map((item) => ({
      label: presentNamedItem(item.label),
      value: item.score,
      evidence: presentNamedItem(item.evidence),
    }));
  }
  return [
    { label: "運用明快さ", value: variant.scores.ux_quality, evidence: "" },
    { label: "実装安定性", value: variant.scores.code_quality, evidence: "" },
    { label: "性能", value: variant.scores.performance, evidence: "" },
    { label: "アクセシビリティ", value: variant.scores.accessibility, evidence: "" },
  ];
}

function freshnessTone(variant: DesignVariant | null): "positive" | "warning" | "neutral" {
  const status = variant?.freshness?.status;
  if (status === "fresh" && variant?.freshness?.can_handoff) return "positive";
  if (status === "stale" || variant?.freshness?.can_handoff === false) return "warning";
  return "neutral";
}

function freshnessLabel(variant: DesignVariant | null): string {
  const status = variant?.freshness?.status;
  if (status === "fresh" && variant?.freshness?.can_handoff) return "最新";
  if (status === "stale") return "要再生成";
  if (variant?.freshness?.can_handoff === false) return "保留";
  return "未確認";
}

function completenessLabel(variant: DesignVariant | null): string {
  const status = variant?.artifact_completeness?.status;
  if (status === "complete") return "完全";
  if (status === "partial") return "一部不足";
  if (status === "incomplete") return "不足";
  return "未評価";
}

function previewSourceLabel(variant: DesignVariant | null): string {
  if (variant?.preview_meta?.source === "llm") return "LLM";
  if (variant?.preview_meta?.source === "repaired") return "再構成";
  if (variant?.preview_meta?.source === "template") return "テンプレート";
  return "不明";
}

function previewSourceDetailLabel(variant: DesignVariant | null): string {
  if (variant?.preview_meta?.source === "llm") return "LLM生成プレビュー";
  if (variant?.preview_meta?.source === "repaired") return "再構成プレビュー";
  if (variant?.preview_meta?.source === "template") return "テンプレート生成プレビュー";
  return "プレビュー情報なし";
}

function localizedPreviewValidationIssue(issue: string): string {
  return issue
    .replace("missing_html_document", "HTML ドキュメント形式ではありません")
    .replace("missing_inline_style", "インラインスタイルが不足しています")
    .replace("missing_inline_script", "インラインスクリプトが不足しています")
    .replace("external_assets_detected", "外部アセット参照が残っています")
    .replace("missing_viewport", "viewport 設定がありません")
    .replace("missing_responsive_breakpoint", "レスポンシブ用の分岐がありません")
    .replace("insufficient_screen_count", "画面数が不足しています")
    .replace("limited_interactivity", "操作要素が不足しています")
    .replace("missing_navigation_shell", "ナビゲーションシェルが不足しています")
    .replace("missing_accessibility_annotations", "アクセシビリティ注記が不足しています");
}

function localizedPreviewCopyIssue(issue: string): string {
  return issue
    .replace("placeholder_copy", "placeholder や TODO などの仮文言が残っています")
    .replace("internal_jargon_visible", "visible UI に実装用語や内部メモ語が残っています")
    .replace("internal_milestone_id", "visible UI に内部IDやマイルストーン記号が残っています")
    .replace("english_ui_drift", "日本語 UI の中に英語ラベルが混在しています");
}

function localizedInteractiveFeature(feature: string): string {
  return feature
    .replace("tabs", "タブ切替")
    .replace("accordion", "アコーディオン")
    .replace("hover", "ホバー")
    .replace("navigation", "ナビゲーション")
    .replace("transition", "トランジション")
    .replace("responsive", "レスポンシブ");
}

function localizedBlockingReason(reason: string): string {
  return reason
    .replace("planning/research decision context changed after this design was generated", "企画または調査の判断文脈が変わったため、この案は再生成が必要です")
    .replace("decision context fingerprint is incomplete", "判断文脈の照合情報が不足しています")
    .replace("design artifact contract is incomplete", "デザイン成果物に必要な構造化項目が不足しています")
    .replace("design preview does not satisfy the preview contract", "プレビューがプロダクトワークスペースの要件を満たしていないため、承認には使えません");
}

function selectedDesignBlockingReasons(
  variant: DesignVariant | null,
  options: { staleSelectionIssueTitle?: string | null } = {},
): string[] {
  const reasons = [...(variant?.freshness?.reasons ?? [])].map(localizedBlockingReason);
  const staleSelectionIssueTitle = options.staleSelectionIssueTitle?.trim();
  if (staleSelectionIssueTitle) {
    reasons.push(presentNamedItem(staleSelectionIssueTitle));
  }
  const missing = variant?.artifact_completeness?.missing ?? [];
  if (missing.length > 0) {
    reasons.push(`不足項目: ${missing.slice(0, 3).map(localizedArtifactFieldName).join("、")}`);
  }
  const previewIssues = variant?.preview_meta?.validation_issues ?? [];
  if (previewIssues.length > 0 && variant?.preview_meta?.validation_ok === false) {
    reasons.push(`プレビュー要修正: ${previewIssues.slice(0, 2).map(localizedPreviewValidationIssue).join("、")}`);
  }
  return reasons.filter(Boolean);
}

function canHandoffSelectedDesign(
  variant: DesignVariant | null,
  options: { hasStaleSelectionIssue: boolean } = { hasStaleSelectionIssue: false },
): boolean {
  if (!variant) return false;
  if (options.hasStaleSelectionIssue) return false;
  if (variant.freshness?.can_handoff === false || variant.freshness?.status === "stale") {
    return false;
  }
  const completenessStatus = variant.artifact_completeness?.status;
  if (completenessStatus === "partial" || completenessStatus === "incomplete") {
    return false;
  }
  if (variant.preview_meta?.validation_ok !== true) {
    return false;
  }
  return true;
}

function decisionFrameUseCaseTitles(frame: LifecycleDecisionFrame | null) {
  return (frame?.primary_use_cases ?? []).map((item) => presentNamedItem(item.title)).filter(Boolean).slice(0, 4);
}

function featureNames(frame: LifecycleDecisionFrame | null) {
  return (frame?.selected_features ?? []).map((item) => presentFeatureLabel(item.name)).filter(Boolean).slice(0, 5);
}

function milestoneNames(frame: LifecycleDecisionFrame | null) {
  return (frame?.milestones ?? []).map((item) => presentNamedItem(item.name)).filter(Boolean).slice(0, 4);
}

function riskTitles(frame: LifecycleDecisionFrame | null) {
  return (frame?.key_risks ?? []).map((item) => presentNamedItem(item.title)).filter(Boolean).slice(0, 4);
}

function flowNames(variant: DesignVariant | null) {
  return (variant?.prototype?.flows ?? []).map((flow) => presentNamedItem(flow.name)).filter(Boolean).slice(0, 4);
}

function activeModules(screen: PrototypeScreen | null) {
  return (screen?.modules ?? []).slice(0, 4);
}

function implementationBriefFor(variant: DesignVariant | null): DesignImplementationBrief | null {
  return variant?.implementation_brief ?? null;
}

function uniqueBriefEntries(left: string[], right: string[]) {
  return left.filter((item) => item && !right.includes(item));
}

type DeliverySliceView = {
  key: string;
  code?: string;
  title: string;
  milestone?: string;
  acceptance?: string;
};

function parseEmbeddedSliceField(source: string, field: string): string {
  const closedMatch = source.match(new RegExp(`['"]${field}['"]\\s*:\\s*['"]([^'"]+)['"]`));
  if (closedMatch?.[1]) return closedMatch[1].trim();
  const openMatch = source.match(new RegExp(`['"]${field}['"]\\s*:\\s*['"](.+)$`));
  return openMatch?.[1]?.replace(/['"}\],\s]+$/g, "").trim() ?? "";
}

function parseDeliverySlice(item: string, index: number): DeliverySliceView {
  const raw = String(item ?? "").trim();
  if (!raw) {
    return {
      key: `slice-${index}`,
      title: `実装スライス ${index + 1}`,
    };
  }
  if (raw.startsWith("{") && raw.includes("title")) {
    const code = parseEmbeddedSliceField(raw, "slice");
    const title = parseEmbeddedSliceField(raw, "title");
    const milestone = parseEmbeddedSliceField(raw, "milestone");
    const acceptance = parseEmbeddedSliceField(raw, "acceptance");
    if (title) {
      return {
        key: code || title || `slice-${index}`,
        code: code || undefined,
        title,
        milestone: milestone || undefined,
        acceptance: acceptance || undefined,
      };
    }
  }
  return {
    key: raw,
    title: raw,
  };
}

function deliverySliceViews(items: string[] | undefined | null): DeliverySliceView[] {
  return (items ?? [])
    .map((item, index) => parseDeliverySlice(item, index))
    .filter((item, index, values) => values.findIndex((candidate) => candidate.key === item.key) === index);
}

function SliceChip({ text, variant = "assistive" }: { text: string; variant?: "assistive" | "optional" | "required" }) {
  return (
    <Badge
      variant={variant}
      size="field"
      className="max-w-full whitespace-normal break-words text-left leading-5 [overflow-wrap:anywhere]"
    >
      {presentNamedItem(text)}
    </Badge>
  );
}

function DeliverySliceCard({ slice }: { slice: DeliverySliceView }) {
  const acceptance = presentNamedItem(slice.acceptance ?? "");
  const title = presentNamedItem(slice.title);
  const milestone = slice.milestone ? presentNamedItem(slice.milestone) : "";
  const isLongAcceptance = acceptance.length > 72;
  return (
    <div className="min-w-0 rounded-[1.35rem] border border-border/60 bg-card/78 p-4 shadow-[0_10px_28px_rgba(15,23,42,0.08)]">
      <div className="flex flex-wrap items-start gap-2">
        {slice.code ? <SliceChip text={slice.code} variant="assistive" /> : null}
        {milestone ? <SliceChip text={milestone} variant="optional" /> : null}
      </div>
      <p className="mt-3 text-sm font-semibold leading-6 text-foreground [overflow-wrap:anywhere]">
        {title}
      </p>
      {acceptance ? (
        isLongAcceptance ? (
          <details className="mt-3 rounded-2xl border border-border/55 bg-background/72 px-3 py-3">
            <summary className="cursor-pointer list-none text-[11px] font-semibold tracking-[0.12em] text-muted-foreground">
              受け入れ条件を開く
            </summary>
            <p className="mt-3 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">
              {acceptance}
            </p>
          </details>
        ) : (
          <div className="mt-3 rounded-2xl border border-border/55 bg-background/72 px-3 py-3">
            <p className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground">受け入れ条件</p>
            <p className="mt-2 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">
              {acceptance}
            </p>
          </div>
        )
      ) : null}
    </div>
  );
}

function uniqueBriefSliceTitles(left: string[], right: string[]) {
  const rightTitles = new Set(deliverySliceViews(right).map((item) => item.title));
  return deliverySliceViews(left)
    .map((item) => item.title)
    .filter((item) => item && !rightTitles.has(item));
}

function compareVariants(left: DesignVariant | null, right: DesignVariant | null) {
  const leftBrief = implementationBriefFor(left);
  const rightBrief = implementationBriefFor(right);
  return {
    leftOnlyShape: uniqueBriefEntries(leftBrief?.system_shape ?? [], rightBrief?.system_shape ?? []).slice(0, 3),
    rightOnlyShape: uniqueBriefEntries(rightBrief?.system_shape ?? [], leftBrief?.system_shape ?? []).slice(0, 3),
    leftOnlySlices: uniqueBriefSliceTitles(leftBrief?.delivery_slices ?? [], rightBrief?.delivery_slices ?? []).slice(0, 3),
    rightOnlySlices: uniqueBriefSliceTitles(rightBrief?.delivery_slices ?? [], leftBrief?.delivery_slices ?? []).slice(0, 3),
  };
}

function activeScreenFor(variant: DesignVariant | null, activeScreenId: string | null): PrototypeScreen | null {
  const screens = variant?.prototype?.screens ?? [];
  if (screens.length === 0) return null;
  return screens.find((screen) => screen.id === activeScreenId) ?? screens[0] ?? null;
}

function formatPercentScore(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "未計測";
  return `${Math.round(value * 100)}`;
}

function prototypeFrameworkLabel(value: string | null | undefined): string {
  if (!value) return "未設定";
  if (value.toLowerCase() === "nextjs") return "Next.js";
  return value;
}

function prototypeRouterLabel(value: string | null | undefined): string {
  if (!value) return "未設定";
  if (value.toLowerCase() === "app") return "App Router";
  return value;
}

function prototypeFileKindLabel(value: string | null | undefined): string {
  if (!value) return "ファイル";
  return presentNamedItem(value) || value;
}

function firstEvidenceFor(variant: DesignVariant, labelFragments: string[]): string {
  const item = scoreItems(variant).find((entry) => labelFragments.some((fragment) => entry.label.includes(fragment)));
  return item?.evidence ?? "";
}

function compactCompareNote(value: string, fallback: string): string {
  const compact = value.trim();
  if (!compact) return fallback;
  if (compact.length <= 72) return compact;
  return `${compact.slice(0, 69).trimEnd()}...`;
}

type CompareRow = {
  label: string;
  description: string;
  left: { value: string; note: string };
  right: { value: string; note: string };
};

function buildCompareRows(left: DesignVariant, right: DesignVariant): CompareRow[] {
  const previewLeft = left.preview_meta;
  const previewRight = right.preview_meta;
  return [
    {
      label: "運用明快さ",
      description: "主要判断の見通し",
      left: {
        value: formatPercentScore(left.scores.ux_quality),
        note: compactCompareNote(firstEvidenceFor(left, ["運用", "明快", "clarity"]) || variantOperationalBet(left), "主要判断を同じ面で捌ける設計です。"),
      },
      right: {
        value: formatPercentScore(right.scores.ux_quality),
        note: compactCompareNote(firstEvidenceFor(right, ["運用", "明快", "clarity"]) || variantOperationalBet(right), "主要判断を同じ面で捌ける設計です。"),
      },
    },
    {
      label: "根拠追跡",
      description: "構造化成果物と引き継ぎ整合",
      left: {
        value: completenessLabel(left),
        note: compactCompareNote(variantHandoffNote(left), "主要フローと判断理由を承認へ固定します。"),
      },
      right: {
        value: completenessLabel(right),
        note: compactCompareNote(variantHandoffNote(right), "主要フローと判断理由を承認へ固定します。"),
      },
    },
    {
      label: "差し戻し耐性",
      description: "鮮度と再生成要否",
      left: {
        value: freshnessLabel(left),
        note: compactCompareNote(selectedDesignBlockingReasons(left)[0] ?? "判断文脈と成果物の整合が維持されています。", "判断文脈と成果物の整合が維持されています。"),
      },
      right: {
        value: freshnessLabel(right),
        note: compactCompareNote(selectedDesignBlockingReasons(right)[0] ?? "判断文脈と成果物の整合が維持されています。", "判断文脈と成果物の整合が維持されています。"),
      },
    },
    {
      label: "モバイル忠実度",
      description: "レスポンシブ試作の観測結果",
      left: {
        value: previewLeft ? `${previewLeft.screen_count_estimate} 画面` : "未計測",
        note: compactCompareNote(
          previewLeft?.validation_ok
            ? `操作要素: ${(previewLeft.interactive_features ?? []).slice(0, 2).map(localizedInteractiveFeature).join(" / ") || "レスポンシブ"}`
            : (previewLeft?.validation_issues ?? []).slice(0, 2).map(localizedPreviewValidationIssue).join(" / "),
          "responsive の追加確認が必要です。",
        ),
      },
      right: {
        value: previewRight ? `${previewRight.screen_count_estimate} 画面` : "未計測",
        note: compactCompareNote(
          previewRight?.validation_ok
            ? `操作要素: ${(previewRight.interactive_features ?? []).slice(0, 2).map(localizedInteractiveFeature).join(" / ") || "レスポンシブ"}`
            : (previewRight?.validation_issues ?? []).slice(0, 2).map(localizedPreviewValidationIssue).join(" / "),
          "responsive の追加確認が必要です。",
        ),
      },
    },
    {
      label: "実装安定性",
      description: "構成と技術判断の安定度",
      left: {
        value: formatPercentScore(left.scores.code_quality),
        note: compactCompareNote(presentNamedItem(left.implementation_brief?.architecture_thesis || ""), "主要フローを壊さない構成を優先します。"),
      },
      right: {
        value: formatPercentScore(right.scores.code_quality),
        note: compactCompareNote(presentNamedItem(right.implementation_brief?.architecture_thesis || ""), "主要フローを壊さない構成を優先します。"),
      },
    },
    {
      label: "アクセシビリティ",
      description: "アクセシビリティと視認性",
      left: {
        value: formatPercentScore(left.scores.accessibility),
        note: compactCompareNote(firstEvidenceFor(left, ["アクセシ", "a11y"]) || "主要操作の視認性と状態ラベルの明快さを優先しています。", "主要操作の視認性と状態ラベルの明快さを優先しています。"),
      },
      right: {
        value: formatPercentScore(right.scores.accessibility),
        note: compactCompareNote(firstEvidenceFor(right, ["アクセシ", "a11y"]) || "主要操作の視認性と状態ラベルの明快さを優先しています。", "主要操作の視認性と状態ラベルの明快さを優先しています。"),
      },
    },
  ];
}

function openPreviewInNewTab(html: string) {
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.open();
  win.document.write(html);
  win.document.close();
}

export function DesignPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const designPhaseStatus = selectPhaseStatus(lc.phaseStatuses, "design");
  const hasKnownDesignRun = hasRestorablePhaseRun(
    lc.phaseStatuses,
    lc.phaseRuns,
    lc.runtimeActivePhase,
    "design",
  );
  const workflow = useWorkflowRun("design", projectSlug ?? "", { knownRunExists: hasKnownDesignRun });
  const designAgents = selectPhaseTeam(lc, "design", DESIGN_AGENTS);
  const designPulse = buildPhasePulseSnapshot({
    lifecycle: lc,
    phase: "design",
    team: designAgents,
    workflow,
    warmupTasks: [
      "Claude Sonnet 4.6 が濃色の制御室案を、勝ち筋の信頼仮説から組み立てています。",
      "KIMI K2.5 が明るい判断室案を、同じ中核ループの別解として構築しています。",
      "デザイン審査が承認に渡せる選定メモを準備しています。",
    ],
  });
  const [previewDevice, setPreviewDevice] = useState<PreviewDevice>("desktop");
  const [reviewSection, setReviewSection] = useState<DesignReviewSection>(
    lc.designVariants.length > 0 ? "prototype" : "overview",
  );
  const [activeVariantId, setActiveVariantId] = useState<string | null>(lc.selectedDesignId ?? null);
  const [activeScreenId, setActiveScreenId] = useState<string | null>(null);
  const [showCode, setShowCode] = useState(false);
  const [selectError, setSelectError] = useState<string | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [isHandingOff, setIsHandingOff] = useState(false);
  const syncedRunRef = useRef<string | null>(null);

  useEffect(() => {
    if ((workflow.status !== "completed" && workflow.status !== "failed") || !workflow.runId || !projectSlug) return;
    if (syncedRunRef.current === workflow.runId) return;
    syncedRunRef.current = workflow.runId;
    void lifecycleApi.syncPhaseRun(projectSlug, "design", workflow.runId).then(({ project }) => {
      actions.applyProject(project);
    });
  }, [actions, workflow.runId, workflow.status, projectSlug]);

  useEffect(() => {
    if (lc.designVariants.length === 0) {
      setActiveVariantId(null);
      setReviewSection("overview");
      return;
    }
    setActiveVariantId((previous) => {
      if (previous && lc.designVariants.some((variant) => variant.id === previous)) return previous;
      return lc.selectedDesignId ?? lc.designVariants[0]?.id ?? null;
    });
  }, [lc.designVariants, lc.selectedDesignId]);

  useEffect(() => {
    if (lc.designVariants.length === 0) return;
    setReviewSection((previous) => previous === "overview" ? "prototype" : previous);
  }, [lc.designVariants.length]);

  const activeVariant = lc.designVariants.find((variant) => variant.id === activeVariantId)
    ?? lc.designVariants[0]
    ?? null;

  useEffect(() => {
    const screens = activeVariant?.prototype?.screens ?? [];
    if (screens.length === 0) {
      setActiveScreenId(null);
      return;
    }
    setActiveScreenId((previous) => (
      previous && screens.some((screen) => screen.id === previous) ? previous : screens[0]?.id ?? null
    ));
  }, [activeVariant?.id, activeVariant?.prototype?.screens]);

  const activeScreen = activeScreenFor(activeVariant, activeScreenId);
  const activePreviewHtml = activeVariant ? localizePreviewHtmlForDisplay(activeVariant.preview_html) : "";
  const projectFrame = projectFrameOf(lc.decisionContext);
  const contextIssues = contextIssuesOf(lc.decisionContext);
  const selectedFeatureCount = selectSelectedFeatureCount(lc);
  const planningReady = Boolean(lc.analysis);
  const isGenerating =
    workflow.status === "starting"
    || workflow.status === "running"
    || (designPhaseStatus === "in_progress" && lc.designVariants.length === 0);

  const generate = () => {
    actions.advancePhase("design");
    workflow.start(buildDesignWorkflowInput(lc));
  };

  const goNext = async () => {
    if (!lc.selectedDesignId) {
      setTransitionError("採用する方向を 1 つ選んでから承認へ進んでください");
      return;
    }
    if (!selectedCanHandoff) {
      setTransitionError(
        selectedBlockingReasons[0]
          ? `この案はまだ承認へ渡せません: ${selectedBlockingReasons[0]}`
          : "選択中の案が最新の判断文脈または成果物契約を満たしていません",
      );
      return;
    }
    if (!projectSlug) return;
    setTransitionError(null);
    setIsHandingOff(true);
    try {
      const response = await persistCompletedPhase(projectSlug, "design", lc.phaseStatuses);
      actions.applyProject(response.project);
      navigate(`/p/${projectSlug}/lifecycle/approval`);
    } catch (err) {
      setTransitionError(err instanceof Error ? err.message : "承認への引き継ぎに失敗しました");
    } finally {
      setIsHandingOff(false);
    }
  };

  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/planning`);

  const selectDesign = (designId: string) => {
    setSelectError(null);
    setTransitionError(null);
    setActiveVariantId(designId);
    if (!projectSlug) {
      actions.selectDesign(designId);
      return;
    }
    actions.selectDesign(designId);
    void lifecycleApi.saveProject(projectSlug, { selectedDesignId: designId })
      .then((response) => {
        actions.applyProject(response.project);
      })
      .catch((err) => {
        setSelectError(err instanceof Error ? err.message : "デザインの保存に失敗しました");
      });
  };

  if (lc.designVariants.length === 0 && !isGenerating) {
    const useCases = decisionFrameUseCaseTitles(projectFrame);
    const features = featureNames(projectFrame);
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="grid w-full max-w-6xl gap-6 xl:grid-cols-[1.3fr_0.9fr]">
          <section className="rounded-[2rem] border border-border/70 bg-[linear-gradient(160deg,rgba(12,16,26,0.96),rgba(16,24,39,0.9))] p-8 text-white shadow-[0_28px_120px_rgba(2,6,23,0.36)]">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium tracking-[0.22em] text-white/70">
              <Sparkles className="h-3.5 w-3.5 text-amber-300" />
              デザイン判断デスク
            </div>
            <h2 className="mt-6 max-w-3xl text-[2rem] font-semibold tracking-tight text-white sm:text-[2.4rem]">
              勝ち筋を 2 つのプロダクト試作に変換し、
              そのまま承認へ渡せる方向を選びます。
            </h2>
            <p className="mt-4 max-w-3xl text-sm leading-7 text-white/72">
              Pylon のデザイン工程は見た目の好み比べではありません。調査と企画で残した勝ち筋を、
              実際の運用導線と承認への引き継ぎに耐えるプロダクトUIとして比較します。
            </p>
            <div className="mt-7 grid gap-4 sm:grid-cols-3">
              <InfoStat label="企画分析" value={planningReady ? "準備完了" : "未完了"} tone={planningReady ? "positive" : "neutral"} />
              <InfoStat label="選択機能" value={`${selectedFeatureCount}`} tone="neutral" />
              <InfoStat label="マイルストーン" value={`${lc.milestones.length}`} tone="neutral" />
            </div>
            <div className="mt-7 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] p-5">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-white/55">現在の勝ち筋</p>
                <p className="mt-3 text-sm leading-7 text-white/82">
                  {presentDecisionLeadThesis(projectFrame, lc.analysis?.judge_summary)}
                </p>
              </div>
              <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] p-5">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-white/55">今回の比較観点</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {["判断が迷わない", "承認に渡しやすい", "系譜を追いやすい", "実装へ落としやすい"].map((item) => (
                    <span key={item} className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-1 text-xs text-white/72">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="space-y-4 rounded-[2rem] border border-border/70 bg-card/85 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.14)]">
            <div>
              <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">生成前チェック</p>
              <h3 className="mt-2 text-lg font-semibold text-foreground">承認に渡せる比較を作る</h3>
            </div>
            <div className="space-y-2">
              {[
                { label: "企画分析が完了している", done: planningReady },
                { label: "少なくとも 1 つ機能が選択されている", done: selectedFeatureCount > 0 },
                { label: "仕様文が入力されている", done: lc.spec.trim().length > 0 },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm">
                  <span className={cn("h-2.5 w-2.5 rounded-full", item.done ? "bg-emerald-500" : "bg-amber-500")} />
                  <span className={item.done ? "text-foreground" : "text-muted-foreground"}>{item.label}</span>
                </div>
              ))}
            </div>
            {(features.length > 0 || useCases.length > 0) && (
              <div className="rounded-[1.5rem] border border-border/70 bg-background/72 p-4">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">今回使う入力</p>
                {features.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {features.map((item) => (
                      <Badge key={item} variant="assistive" size="field">{item}</Badge>
                    ))}
                  </div>
                )}
                {useCases.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {useCases.slice(0, 3).map((item) => (
                      <p key={item} className="rounded-xl border border-border/60 bg-card px-3 py-2 text-xs text-muted-foreground">
                        {item}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <Button variant="outline" onClick={goBack} className="flex-1">
                企画に戻る
              </Button>
              <Button
                onClick={generate}
                disabled={!planningReady || selectedFeatureCount === 0 || lc.spec.trim().length === 0}
                className="flex-1 gap-2"
              >
                <Zap className="h-4 w-4" />
                勝ち筋から 2 案を作る
              </Button>
            </div>
          </section>
        </div>
      </div>
    );
  }

  if (workflow.status === "failed") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md w-full space-y-4 text-center">
          <AlertCircle className="mx-auto h-12 w-12 text-destructive" />
          <h2 className="text-lg font-bold text-foreground">デザイン生成エラー</h2>
          <p className="text-sm text-muted-foreground">{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
          <Button variant="default" onClick={() => workflow.reset()}>やり直す</Button>
        </div>
      </div>
    );
  }

  if (isGenerating) {
    return (
      <MultiAgentCollaborationPulse
        title="勝ち筋から 2 つのプロダクト試作を生成中..."
        subtitle="同じ判断文脈を 2 本の比較案に翻訳し、審査が承認に渡せる比較理由を固めています"
        elapsedLabel={designPulse.elapsedLabel}
        agents={designPulse.agents}
        actions={designPulse.actions}
        events={designPulse.events}
        timeline={buildDesignTimeline(designPulse.agents)}
      />
    );
  }

  const previewWidth = deviceWidthFor(previewDevice);
  const previewHeight = deviceHeightFor(previewDevice);
  const useCases = decisionFrameUseCaseTitles(projectFrame);
  const selectedFeatures = featureNames(projectFrame);
  const milestones = milestoneNames(projectFrame);
  const projectRisks = riskTitles(projectFrame);
  const reviewFocusItems = [
    ...contextIssues.map((issue) => presentNamedItem(issue.title)),
    ...presentDecisionReviewItems(projectFrame),
  ].filter((item, index, list) => Boolean(item) && list.indexOf(item) === index).slice(0, 4);
  const activeVariantIndex = Math.max(lc.designVariants.findIndex((variant) => variant.id === activeVariant?.id), 0);
  const activeVariantTitle = activeVariant ? presentVariantTitle(activeVariant, activeVariantIndex) : "比較案";
  const selectedVariant = lc.designVariants.find((variant) => variant.id === lc.selectedDesignId) ?? activeVariant;
  const selectedVariantTitle = selectedVariant
    ? presentVariantTitle(selectedVariant, Math.max(lc.designVariants.findIndex((variant) => variant.id === selectedVariant.id), 0))
    : "未選択";
  const selectedApprovalPacket = selectedVariant ? variantApprovalPacket(selectedVariant) : null;
  const activeApprovalPacket = activeVariant ? variantApprovalPacket(activeVariant) : null;
  const staleSelectionIssue = contextIssues.find((issue) => issue.id === "stale-selected-design") ?? null;
  const selectedBlockingReasons = selectedDesignBlockingReasons(selectedVariant, {
    staleSelectionIssueTitle: staleSelectionIssue?.title ?? null,
  });
  const selectedCanHandoff = Boolean(
    lc.selectedDesignId
    && canHandoffSelectedDesign(selectedVariant, { hasStaleSelectionIssue: staleSelectionIssue != null }),
  );
  const activeFallbackVariant = activeVariant ?? lc.designVariants[0] ?? null;
  const activeFlows = flowNames(activeFallbackVariant);
  const activeBrief = implementationBriefFor(activeFallbackVariant);
  const selectedBrief = implementationBriefFor(selectedVariant);
  const runnerUpVariant = lc.designVariants.find((variant) => variant.id !== selectedVariant?.id) ?? null;
  const primaryCompareVariant = lc.designVariants[0] ?? null;
  const challengerCompareVariant = lc.designVariants[1] ?? null;
  const comparisonDelta = compareVariants(primaryCompareVariant, challengerCompareVariant);
  const compareRows = primaryCompareVariant && challengerCompareVariant
    ? buildCompareRows(primaryCompareVariant, challengerCompareVariant)
    : [];
  const selectedReasons = variantSelectionReasons(selectedVariant ?? activeFallbackVariant ?? lc.designVariants[0]).slice(0, 3);
  const overviewRisks = (selectedBlockingReasons.length > 0
    ? selectedBlockingReasons
    : variantTradeoffs(selectedVariant ?? activeFallbackVariant ?? lc.designVariants[0]).length > 0
      ? variantTradeoffs(selectedVariant ?? activeFallbackVariant ?? lc.designVariants[0])
      : [
          ...contextIssues.map((issue) => presentNamedItem(issue.title)),
          ...projectRisks,
        ]).slice(0, 3);
  const runtimePhaseMismatch = lc.runtimeActivePhase != null && lc.runtimeActivePhase !== "design";
  const runtimeStatusLabel =
    designPulse.telemetry?.run?.status
    ?? (workflow.status === "running" ? "running" : workflow.status === "starting" ? "starting" : designPhaseStatus);
  const runtimeStatusValue = runStatusLabel(String(runtimeStatusLabel));
  const runtimeConnectionValue = runtimeConnectionLabel(lc.runtimeConnectionState);
  const runtimePhaseValue = lifecyclePhaseLabel(lc.runtimeActivePhase ?? "design");
  const runtimeHasSignal = Boolean(
    designPulse.telemetry?.completedNodeCount
    || designPulse.telemetry?.runningNodeIds.length
    || designPulse.telemetry?.failedNodeIds.length
    || designPulse.telemetry?.recentEvents.length
    || designPulse.telemetry?.recentNodeIds.length
    || designPulse.runtimeSummary?.recentActions?.length
    || designPulse.runtimeSummary?.agents?.length
  );
  const runtimeCompletedAgentCount = designPulse.runtimeSummary?.agents?.filter((agent) => agent.status === "completed").length
    ?? designPulse.agents.filter((agent) => agent.status === "completed").length;
  const runtimeCompletedNodeValue = designPulse.telemetry?.completedNodeCount && designPulse.telemetry.completedNodeCount > 0
    ? `${designPulse.telemetry.completedNodeCount}`
    : runtimeCompletedAgentCount > 0
      ? `${runtimeCompletedAgentCount}`
      : hasKnownDesignRun && (designPhaseStatus === "completed" || designPhaseStatus === "review")
        ? "復元中"
        : "0";
  const runtimeLatestSummary =
    designPulse.telemetry?.recentEvents[0]?.summary
    ?? designPulse.runtimeSummary?.recentActions?.[0]?.summary
    ?? designPulse.actions[0]?.summary;
  const runtimeFocus =
    designPulse.telemetry?.activeFocusNodeId
    ?? runtimeLatestSummary
    ?? designPulse.telemetry?.lastNodeId
    ?? designPulse.runtimeSummary?.agents?.find((agent) => agent.status === "running")?.currentTask
    ?? designPulse.agents.find((agent) => agent.status === "running")?.currentTask
    ?? designPulse.runtimeSummary?.agents?.findLast((agent) => agent.status === "completed")?.lastArtifactTitle
    ?? designPulse.agents.findLast((agent) => agent.status === "completed")?.currentTask
    ?? designPulse.runtimeSummary?.objective
    ?? (!runtimeHasSignal && hasKnownDesignRun && (designPhaseStatus === "completed" || designPhaseStatus === "review")
      ? "完了した run の詳細を復元しています。"
      : designPulse.telemetry?.run?.status === "completed"
        ? "全ノード完了"
        : "最新のフォーカスはありません");
  const runtimeEvents = designPulse.events.length > 0
    ? designPulse.events.map((event) => `${event.label}: ${event.summary}`)
    : designPulse.actions.map((action) => `${action.label}: ${action.summary}`);
  const selectedFreshnessValue = staleSelectionIssue ? "要再生成" : freshnessLabel(selectedVariant);
  const selectedArtifactValue =
    !selectedCanHandoff && !(selectedVariant?.artifact_completeness?.status)
      ? "再評価待ち"
      : completenessLabel(selectedVariant);
  const activeFreshnessValue =
    activeVariant?.id === selectedVariant?.id && staleSelectionIssue
      ? "要再生成"
      : freshnessLabel(activeVariant);

  return (
    <div className={cn(downstreamWorkspaceClassName, "flex min-h-full flex-col")}>
      <div className={cn(downstreamTopbarClassName, "sticky top-0 z-20 flex flex-wrap items-center gap-3 px-6 py-3")}>
        <button aria-label="企画へ戻る" onClick={goBack} className="rounded-full border border-border/70 p-2 text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">
            <Palette className="h-3.5 w-3.5 text-primary" />
            デザイン判断デスク
          </div>
          <h1 className="text-base font-semibold text-foreground">勝ち筋をプロダクト試作として比較する</h1>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex gap-0.5 rounded-full border border-border/70 bg-card/70 p-1">
            {([["desktop", Monitor], ["tablet", Tablet], ["mobile", Smartphone]] as const).map(([device, Icon]) => (
              <button
                key={device}
                onClick={() => setPreviewDevice(device)}
                aria-pressed={previewDevice === device}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs transition-colors",
                  previewDevice === device ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="inline-flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5" />
                  {PREVIEW_DEVICE_LABELS[device]}
                </span>
              </button>
            ))}
          </div>
          <Button onClick={() => void goNext()} className="gap-2" disabled={isHandingOff || !lc.selectedDesignId || !selectedCanHandoff}>
            {isHandingOff ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            {isHandingOff ? "保存して引き継ぎ中..." : "この方向で承認へ"}
            {!isHandingOff && <ArrowRight className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      <div className="px-4 py-6 pb-16 sm:px-6 sm:pb-20">
        {transitionError && (
          <div className="mx-auto mb-4 max-w-7xl">
            <p className="rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {transitionError}
            </p>
          </div>
        )}
        {selectError && (
          <div className="mx-auto mb-4 max-w-7xl">
            <p className="rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {selectError}
            </p>
          </div>
        )}

        <div className="mx-auto max-w-[1460px] space-y-6">
          <section className="grid gap-5 xl:grid-cols-[minmax(0,1.24fr)_23rem]">
            <div className="rounded-[2rem] border border-slate-800/85 bg-[linear-gradient(160deg,rgba(5,9,17,0.98),rgba(12,18,33,0.95))] p-7 text-white shadow-[0_28px_120px_rgba(2,6,23,0.34)]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium tracking-[0.18em] text-white/70">
                  勝ち筋
                </span>
                {lc.selectedDesignId ? (
                  <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-[11px] font-medium text-emerald-200">
                    採用中: {selectedVariantTitle}
                  </span>
                ) : null}
              </div>
              <h2 className="mt-5 max-w-4xl text-[1.8rem] font-semibold tracking-tight text-white sm:text-[2.2rem]">
                {presentDecisionLeadThesis(projectFrame, lc.analysis?.judge_summary)}
              </h2>
              <p className="mt-4 max-w-3xl text-sm leading-7 text-white/72">
                {presentDecisionSummary(projectFrame)}
              </p>
              <div className="mt-6 grid gap-4 lg:grid-cols-2">
                <HeroPanel label="判断の北極星" value={presentDecisionNorthStar(projectFrame)} />
                <HeroPanel label="中核ループ" value={presentDecisionCoreLoop(projectFrame)} />
              </div>
              <div className="mt-6 grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
                <SignalCluster title="主要ユースケース" items={useCases} emptyLabel="分析からユースケースを継承します。" />
                <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] p-5">
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-white/55">今回の比較レンズ</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {["承認が迷わない", "根拠と操作が離れない", "差し戻しが怖くない", "実装へ渡しやすい"].map((item) => (
                      <span key={item} className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-1 text-xs text-white/78">
                        {item}
                      </span>
                    ))}
                  </div>
                  {selectedFeatures.length > 0 ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {selectedFeatures.map((item) => (
                        <Badge key={item} variant="assistive" size="field" className="border-white/12 bg-white/[0.06] text-white/82">
                          {item}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-4 text-sm text-white/62">選択機能を比較案に反映します。</p>
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-[2rem] border border-border/70 bg-card/88 p-6 shadow-[0_20px_70px_rgba(15,23,42,0.16)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">承認に渡すパケット</p>
                <div className="mt-4 space-y-4">
                  <div className="rounded-[1.35rem] border border-border/70 bg-background/78 p-4">
                    <p className="text-xs text-muted-foreground">採用方向</p>
                    <p className="mt-2 text-base font-semibold text-foreground">
                      {selectedVariantTitle}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {selectedVariant ? variantSelectionSummary(selectedVariant) : "比較中の方向から 1 つ選ぶと、承認に渡すパケットを固定します。"}
                    </p>
                    {selectedApprovalPacket ? (
                      <div className="mt-3 space-y-2">
                        <p className="text-sm leading-6 text-foreground/92">{selectedApprovalPacket.operatorPromise}</p>
                        <p className="text-xs leading-5 text-foreground/88">{selectedApprovalPacket.handoffSummary}</p>
                        {variantApprovalFocus(selectedVariant ?? activeFallbackVariant ?? lc.designVariants[0]).length > 0 ? (
                          <div className="flex flex-wrap gap-2">
                            {variantApprovalFocus(selectedVariant ?? activeFallbackVariant ?? lc.designVariants[0]).slice(0, 3).map((item) => (
                              <Badge key={item} variant="assistive" size="field">{item}</Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <InfoStat label="主要画面" value={`${selectedVariant?.screen_specs?.length ?? selectedVariant?.prototype?.screens.length ?? 0}`} tone="neutral" />
                    <InfoStat label="主要フロー" value={`${selectedVariant?.primary_workflows?.length ?? selectedVariant?.prototype?.flows.length ?? 0}`} tone="neutral" />
                    <InfoStat label="鮮度" value={selectedFreshnessValue} tone={!selectedCanHandoff ? "warning" : freshnessTone(selectedVariant)} />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <InfoStat label="成果物" value={selectedArtifactValue} tone={!selectedCanHandoff ? "warning" : freshnessTone(selectedVariant)} />
                    <InfoStat label="プレビュー" value={previewSourceLabel(selectedVariant)} tone="neutral" />
                    <InfoStat label="マイルストーン" value={`${milestones.length}`} tone="neutral" />
                  </div>
                  {activeVariant?.id !== selectedVariant?.id ? (
                    <p className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3 text-xs leading-5 text-muted-foreground">
                      いま閲覧中: {activeVariantTitle} / 承認へ渡す案: {selectedVariantTitle}
                    </p>
                  ) : null}
                  {!selectedCanHandoff && selectedBlockingReasons.length > 0 ? (
                    <div className="rounded-2xl border border-amber-500/25 bg-amber-500/8 px-4 py-3 text-xs leading-5 text-amber-950/80 dark:text-amber-100/80">
                      {selectedBlockingReasons.slice(0, 2).map((reason) => (
                        <p key={reason}>{reason}</p>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              {reviewFocusItems.length > 0 && (
                <div className="rounded-[1.6rem] border border-amber-500/25 bg-amber-500/8 p-5">
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-amber-900/70 dark:text-amber-200/90">判断前に押さえる論点</p>
                  <div className="mt-3 space-y-3">
                    {reviewFocusItems.map((item) => (
                      <div key={item} className="rounded-2xl border border-amber-500/15 bg-black/10 px-4 py-3 dark:bg-black/15">
                        <p className="text-sm font-medium text-amber-950 dark:text-amber-50">{item}</p>
                      </div>
                    ))}
                    {staleSelectionIssue ? (
                      <p className="text-xs leading-6 text-amber-950/80 dark:text-amber-100/74">
                        解消方法: planning の変更を反映した design を再生成し、基準案を選び直してください。
                      </p>
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(19rem,0.8fr)]">
            <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.12)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">レビューセクション</p>
                  <h3 className="mt-2 text-lg font-semibold text-foreground">判断に必要な情報だけを順番に見る</h3>
                </div>
                <p className="text-xs text-muted-foreground">
                  閲覧中: {activeVariantTitle} / 承認候補: {selectedVariantTitle}
                </p>
              </div>
              <div className="mt-5">
                <TabsList className="h-auto flex-wrap rounded-[1.25rem] bg-muted/60 p-1.5">
                  {DESIGN_REVIEW_SECTIONS.map((section) => (
                    <TabsTrigger
                      key={section.id}
                      value={section.id}
                      active={reviewSection === section.id}
                      onClick={() => setReviewSection(section.id)}
                      className="rounded-[0.95rem] px-3 py-2 text-xs sm:text-sm"
                    >
                      {section.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {DESIGN_REVIEW_SECTIONS.map((section) => (
                    <button
                      key={`${section.id}-summary`}
                      onClick={() => setReviewSection(section.id)}
                      className={cn(
                        "rounded-[1.2rem] border px-4 py-4 text-left transition-colors",
                        reviewSection === section.id
                          ? "border-primary/40 bg-primary/[0.08]"
                          : "border-border/70 bg-background/72 hover:border-primary/20",
                      )}
                    >
                      <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">{section.label}</p>
                      <p className="mt-2 text-sm leading-6 text-foreground/90">{section.summary}</p>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.12)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">協調ランタイム</p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <InfoStat label="接続" value={runtimeConnectionValue} tone={lc.runtimeConnectionState === "live" ? "positive" : "neutral"} />
                  <InfoStat label="実行状態" value={runtimeStatusValue} tone={runtimeStatusLabel === "running" ? "positive" : runtimeStatusLabel === "failed" ? "warning" : "neutral"} />
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <InfoStat label="対象フェーズ" value={runtimePhaseValue} tone={runtimePhaseMismatch ? "warning" : "neutral"} />
                  <InfoStat label="完了ノード" value={runtimeCompletedNodeValue} tone="neutral" />
                </div>
                <div className="mt-4 rounded-2xl border border-border/60 bg-background/72 px-4 py-3">
                  <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">現在のフォーカス</p>
                  <p className="mt-2 text-sm leading-6 text-foreground/92">{presentNamedItem(runtimeFocus)}</p>
                </div>
                {runtimePhaseMismatch ? (
                  <p className="mt-4 rounded-2xl border border-amber-500/25 bg-amber-500/8 px-4 py-3 text-xs leading-5 text-amber-950/80 dark:text-amber-100/80">
                    いま開いているのはデザイン画面ですが、ランタイム側は {lifecyclePhaseLabel(lc.runtimeActivePhase)} を指しています。フェーズ不一致の間は、別フェーズのテレメトリを混ぜません。
                  </p>
                ) : null}
                {runtimeEvents.length > 0 ? (
                  <div className="mt-4 space-y-2">
                    {runtimeEvents.slice(0, 3).map((item) => (
                      <div key={item} className="rounded-2xl border border-border/60 bg-background/72 px-4 py-3 text-xs leading-5 text-muted-foreground">
                        {presentNamedItem(item)}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-muted-foreground">現在はデザイン実行のライブイベントがありません。</p>
                )}
              </div>
            </div>
          </section>

          {reviewSection === "overview" ? (
            <section className="grid gap-4 xl:grid-cols-[minmax(0,1.14fr)_minmax(0,0.86fr)]">
              <div className="rounded-[2rem] border border-border/70 bg-card/92 p-6 shadow-[0_22px_80px_rgba(15,23,42,0.14)]">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">採用判断サマリー</p>
                    <h3 className="mt-2 text-lg font-semibold text-foreground">3 分で承認判断に必要な論点を読む</h3>
                  </div>
                  <Badge variant={selectedCanHandoff ? "assistive" : "optional"} size="field">
                    {selectedCanHandoff ? "承認へ進行可能" : "要再生成"}
                  </Badge>
                </div>
                <div className="mt-5 grid gap-4 lg:grid-cols-2">
                  <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">採用理由 3 点</p>
                    <div className="mt-4 space-y-3">
                      {selectedReasons.length > 0 ? selectedReasons.map((reason) => (
                        <div key={reason} className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3 text-sm leading-6 text-foreground/90">
                          {reason}
                        </div>
                      )) : (
                        <p className="text-sm text-muted-foreground">採用理由は compare で比較しながら確定します。</p>
                      )}
                    </div>
                  </div>
                  <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">主リスク</p>
                    <div className="mt-4 space-y-3">
                      {overviewRisks.length > 0 ? overviewRisks.map((risk) => (
                        <div key={risk} className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3 text-sm leading-6 text-foreground/88">
                          {risk}
                        </div>
                      )) : (
                        <p className="text-sm text-muted-foreground">現時点で重大な阻害要因は見つかっていません。</p>
                      )}
                    </div>
                  </div>
                </div>
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">今見ている案</p>
                    <p className="mt-3 text-base font-semibold text-foreground">{activeVariantTitle}</p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {activeVariant ? variantSelectionSummary(activeVariant) : "比較案がありません。"}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                        <Badge variant="assistive" size="field">{presentVariantModelLabel(activeVariant ?? { id: "", model: "" })}</Badge>
                      {activeVariant?.preview_meta ? (
                        <Badge variant="optional" size="field">{previewSourceDetailLabel(activeVariant)}</Badge>
                      ) : null}
                      <Badge variant="optional" size="field">{activeFreshnessValue}</Badge>
                    </div>
                  </div>
                  <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">次アクション</p>
                    <p className="mt-3 text-base font-semibold text-foreground">
                      {selectedCanHandoff ? "このまま承認へ進めます" : "比較または再生成で基準案を確定してください"}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {selectedCanHandoff
                        ? (selectedVariant ? variantHandoffNote(selectedVariant) : "比較中の方向から 1 つ選ぶと、引き継ぎ内容を固定できます。")
                        : (selectedBlockingReasons[0] ?? "選択中の案が最新の判断文脈または成果物契約を満たしていません。")}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button variant="outline" size="sm" onClick={() => setReviewSection("compare")}>比較を見る</Button>
                      <Button variant="outline" size="sm" onClick={() => setReviewSection("handoff")}>引き継ぎ内容を見る</Button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-[2rem] border border-border/70 bg-card/92 p-6 shadow-[0_22px_80px_rgba(15,23,42,0.14)]">
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">判断シート</p>
                  <div className="mt-4 grid gap-3">
                    {activeFallbackVariant ? scoreItems(activeFallbackVariant).map((item) => (
                      <ScoreStat key={item.label} label={item.label} value={item.value} evidence={item.evidence} />
                    )) : null}
                  </div>
                </div>
                {activeVariant?.preview_meta ? (
                  <div className="rounded-[2rem] border border-border/70 bg-card/92 p-6 shadow-[0_22px_80px_rgba(15,23,42,0.14)]">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">プレビュー品質</p>
                    <div className="mt-4 grid gap-3 sm:grid-cols-3">
                      <InfoStat label="生成元" value={previewSourceLabel(activeVariant)} tone="neutral" />
                      <InfoStat label="検証" value={previewValidationLabel(activeVariant.preview_meta.validation_ok)} tone={activeVariant.preview_meta.validation_ok ? "positive" : "warning"} />
                      <InfoStat label="文言品質" value={formatPercentScore(activeVariant.preview_meta.copy_quality_score)} tone={(activeVariant.preview_meta.copy_quality_score ?? 0) >= 0.85 ? "positive" : "warning"} />
                    </div>
                    {activeVariant.preview_meta.validation_issues.length > 0 ? (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {activeVariant.preview_meta.validation_issues.slice(0, 4).map((issue) => (
                          <Badge key={`${activeVariant.id}-${issue}`} variant="optional" size="field">{localizedPreviewValidationIssue(issue)}</Badge>
                        ))}
                      </div>
                    ) : null}
                    {(activeVariant.preview_meta.copy_issues?.length ?? 0) > 0 ? (
                      <div className="mt-4 space-y-2">
                        <div className="flex flex-wrap gap-2">
                          {activeVariant.preview_meta.copy_issues?.slice(0, 4).map((issue) => (
                            <Badge key={`${activeVariant.id}-copy-${issue}`} variant="optional" size="field">{localizedPreviewCopyIssue(issue)}</Badge>
                          ))}
                        </div>
                        {(activeVariant.preview_meta.copy_issue_examples?.length ?? 0) > 0 ? (
                          <p className="text-xs leading-5 text-muted-foreground">
                            例: {activeVariant.preview_meta.copy_issue_examples?.slice(0, 2).map((item) => presentNamedItem(item)).join(" / ")}
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}

          {reviewSection === "prototype" ? (
            <section className="space-y-5">
            <div className="rounded-[2rem] border border-border/70 bg-card/92 shadow-[0_28px_120px_rgba(15,23,42,0.16)]">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/70 px-6 py-5">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-medium tracking-[0.14em] text-primary">
                      {presentDirectionLabel(activeVariantIndex)}
                    </span>
                    {activeVariant?.id === lc.selectedDesignId ? (
                      <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-200">
                        実装候補
                      </span>
                    ) : null}
                  </div>
                  <div>
                    <h3 className="text-[1.45rem] font-semibold tracking-tight text-foreground">
                      {activeVariantTitle}
                    </h3>
                    <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
                      {activeVariant ? variantSelectionSummary(activeVariant) : "勝ち筋を別のUI方針として翻訳した比較案です。"}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span>{activeVariant ? presentVariantModelLabel(activeVariant) : "設計レーン"}</span>
                    <span>•</span>
                    <span>参考コスト ${activeVariant ? presentVariantEstimatedCost(activeVariant).toFixed(3) : "0.000"}</span>
                    <span>•</span>
                    <span>{presentScreenText(activeVariant?.prototype?.kind ?? "product-workspace")}</span>
                    <span>•</span>
                    <span>{activeVariant?.display_language === "ja" ? "日本語表示契約あり" : "原文表示"}</span>
                    {activeVariant?.preview_meta ? (
                      <>
                        <span>•</span>
                        <span>{previewSourceDetailLabel(activeVariant)}</span>
                      </>
                    ) : null}
                    {(activeVariant?.freshness || (activeVariant?.id === selectedVariant?.id && staleSelectionIssue)) ? (
                      <>
                        <span>•</span>
                        <span>{activeFreshnessValue}</span>
                      </>
                    ) : null}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex gap-1 rounded-full border border-border/70 bg-background/70 p-1">
                    <button
                      onClick={() => setShowCode(false)}
                      aria-pressed={!showCode}
                      className={cn(
                        "rounded-full px-3 py-1.5 text-xs transition-colors",
                        !showCode ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        <Eye className="h-3.5 w-3.5" />
                        プレビュー
                      </span>
                    </button>
                    <button
                      onClick={() => setShowCode(true)}
                      aria-pressed={showCode}
                      className={cn(
                        "rounded-full px-3 py-1.5 text-xs transition-colors",
                        showCode ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        <Code2 className="h-3.5 w-3.5" />
                        HTML
                      </span>
                    </button>
                  </div>
                  {activeVariant ? (
                    <button
                      onClick={() => openPreviewInNewTab(activePreviewHtml)}
                      className="inline-flex items-center gap-2 rounded-full border border-border/70 px-3 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      新しいタブで開く
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="space-y-5 px-6 py-6">
                {(activeVariant?.prototype?.screens.length ?? 0) > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {activeVariant?.prototype?.screens.map((screen) => (
                      <button
                        key={screen.id}
                        onClick={() => setActiveScreenId(screen.id)}
                        aria-pressed={screen.id === activeScreenId}
                        className={cn(
                          "rounded-full border px-3 py-2 text-xs transition-colors",
                          screen.id === activeScreenId
                            ? "border-primary/35 bg-primary text-primary-foreground"
                            : "border-border/70 bg-background/78 text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {presentScreenText(screen.title)}
                      </button>
                    ))}
                  </div>
                ) : null}

                <div className="rounded-[1.75rem] border border-border/70 bg-[linear-gradient(180deg,rgba(250,250,250,0.95),rgba(244,246,251,0.92))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] dark:bg-[linear-gradient(180deg,rgba(8,13,23,0.94),rgba(14,20,34,0.96))]">
                  {showCode ? (
                    <pre className="max-h-[920px] overflow-auto rounded-[1.35rem] border border-border/70 bg-background p-5 text-[11px] leading-6 text-foreground">
                      {activePreviewHtml}
                    </pre>
                  ) : (
                    <div
                      className="overflow-auto rounded-[1.35rem] border border-border/60 bg-[linear-gradient(180deg,rgba(226,232,240,0.55),rgba(248,250,252,0.92))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] dark:bg-[linear-gradient(180deg,rgba(15,23,42,0.72),rgba(15,23,42,0.48))]"
                      role="region"
                      aria-label="デザインプレビュー"
                    >
                      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[1.1rem] border border-slate-200/90 bg-white/90 px-4 py-3 shadow-[0_10px_24px_rgba(15,23,42,0.08)] dark:border-slate-700/80 dark:bg-slate-950/55 dark:shadow-[0_12px_30px_rgba(2,6,23,0.26)]">
                        <div>
                          <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-700 dark:text-slate-300">プロトタイプステージ</p>
                          <p className="mt-1 text-sm font-medium text-slate-950 dark:text-slate-50">
                            ここを基準に、画面、技術判断、承認パケットの整合性を見ます。
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Badge
                            variant="assistive"
                            size="field"
                            className="border-slate-900/90 bg-slate-950 text-white shadow-[0_6px_18px_rgba(15,23,42,0.16)] dark:border-slate-200/30 dark:bg-slate-100 dark:text-slate-950"
                          >
                            {PREVIEW_DEVICE_LABELS[previewDevice]}
                          </Badge>
                          {activeScreen ? (
                            <Badge
                              variant="optional"
                              size="field"
                              className="border-slate-300 bg-slate-100 text-slate-900 shadow-[0_4px_14px_rgba(148,163,184,0.16)] dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                            >
                              {presentScreenText(activeScreen.title)}
                            </Badge>
                          ) : null}
                        </div>
                      </div>
                      <div className="flex min-h-[780px] items-start justify-center">
                        {activeVariant ? (
                          <iframe
                            srcDoc={activePreviewHtml}
                            className="max-w-full rounded-[1rem] border border-border/70 bg-white shadow-[0_28px_80px_rgba(15,23,42,0.18)]"
                            style={{ width: previewWidth, height: previewHeight }}
                            sandbox="allow-scripts"
                            title={activeVariant.pattern_name}
                          />
                        ) : null}
                      </div>
                    </div>
                  )}
                </div>

                <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_21rem]">
                  <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">この案が勝ち筋をどう体験に変えるか</p>
                    <p className="mt-4 text-sm leading-7 text-foreground/92">
                      {variantNarrativeThesis(activeFallbackVariant ?? lc.designVariants[0], projectFrame)}
                    </p>
                    <div className="mt-4 rounded-2xl border border-border/60 bg-card/70 px-4 py-3 text-xs leading-6 text-muted-foreground">
                      {variantOperationalBet(activeFallbackVariant ?? lc.designVariants[0])}
                    </div>
                    <div className="mt-4 space-y-3">
                      {variantSelectionReasons(activeFallbackVariant ?? lc.designVariants[0]).slice(0, 4).map((moment, index) => (
                        <div key={`${moment}-${index}`} className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                          <p className="text-sm leading-6 text-foreground">{moment}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">アクティブ画面の読み解き</p>
                    {activeScreen ? (
                      <div className="mt-4 space-y-4">
                        <div>
                          <p className="text-base font-semibold text-foreground">{presentScreenText(activeScreen.title)}</p>
                          <p className="mt-2 text-sm leading-6 text-muted-foreground">{presentScreenText(activeScreen.purpose)}</p>
                          {activeScreen.supporting_text ? (
                            <p className="mt-2 text-xs leading-5 text-muted-foreground">{presentScreenText(activeScreen.supporting_text)}</p>
                          ) : null}
                        </div>
                        <div className="space-y-3">
                          {activeModules(activeScreen).slice(0, 3).map((module) => (
                            <div key={module.name} className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                              <p className="text-xs font-semibold tracking-[0.14em] text-muted-foreground">{presentScreenText(module.type)}</p>
                              <p className="mt-1 text-sm font-medium text-foreground">{presentScreenText(module.name)}</p>
                              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                                {module.items.slice(0, 3).map((item) => presentScreenText(item)).join(" / ")}
                              </p>
                            </div>
                          ))}
                        </div>
                        {activeScreen.primary_actions.length > 0 ? (
                          <div>
                            <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">主要操作</p>
                            <div className="mt-2 flex flex-wrap gap-2">
                              {activeScreen.primary_actions.slice(0, 3).map((action) => (
                                <Badge key={action} variant="optional" size="field">{presentScreenText(action)}</Badge>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-muted-foreground">この方向に含まれる画面がまだありません。</p>
                    )}
                  </div>

                  <div className="space-y-4">
                    <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                      <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">判断シート</p>
                      <div className="mt-4 grid gap-3">
                        {activeFallbackVariant ? scoreItems(activeFallbackVariant).map((item) => (
                          <ScoreStat key={item.label} label={item.label} value={item.value} evidence={item.evidence} />
                        )) : null}
                      </div>
                    </div>
                    {activeVariant?.preview_meta ? (
                      <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                        <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">プレビュー品質</p>
                        <div className="mt-4 grid gap-3 sm:grid-cols-3">
                          <InfoStat label="生成元" value={previewSourceLabel(activeVariant)} tone="neutral" />
                          <InfoStat label="検証" value={previewValidationLabel(activeVariant.preview_meta.validation_ok)} tone={activeVariant.preview_meta.validation_ok ? "positive" : "warning"} />
                          <InfoStat label="文言品質" value={formatPercentScore(activeVariant.preview_meta.copy_quality_score)} tone={(activeVariant.preview_meta.copy_quality_score ?? 0) >= 0.85 ? "positive" : "warning"} />
                        </div>
                        {activeVariant.preview_meta.validation_issues.length > 0 ? (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {activeVariant.preview_meta.validation_issues.slice(0, 4).map((issue) => (
                              <Badge key={`${activeVariant.id}-${issue}`} variant="optional" size="field">{localizedPreviewValidationIssue(issue)}</Badge>
                            ))}
                          </div>
                        ) : null}
                        {(activeVariant.preview_meta.copy_issues?.length ?? 0) > 0 ? (
                          <div className="mt-4 space-y-2">
                            <div className="flex flex-wrap gap-2">
                              {activeVariant.preview_meta.copy_issues?.slice(0, 4).map((issue) => (
                                <Badge key={`${activeVariant.id}-prototype-copy-${issue}`} variant="optional" size="field">{localizedPreviewCopyIssue(issue)}</Badge>
                              ))}
                            </div>
                            {(activeVariant.preview_meta.copy_issue_examples?.length ?? 0) > 0 ? (
                              <p className="text-xs leading-5 text-muted-foreground">
                                例: {activeVariant.preview_meta.copy_issue_examples?.slice(0, 2).map((item) => presentNamedItem(item)).join(" / ")}
                              </p>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                      <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">
                        {activeVariant?.id === selectedVariant?.id ? "承認へ渡す内容" : "この案を承認へ渡すなら"}
                      </p>
                      <div className="mt-4 space-y-3 text-sm leading-6 text-foreground/92">
                        <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                          {activeFlows.join(" / ") || "主要フローを承認パケットに固定します。"}
                        </div>
                        <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                          {activeApprovalPacket?.handoffSummary ?? (activeVariant ? variantHandoffNote(activeVariant) : "採用理由と守るべき体験を承認へ引き継ぎます。")}
                        </div>
                        {activeApprovalPacket?.mustKeep.length ? (
                          <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                            <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">実装で守るもの</p>
                            <div className="mt-3 space-y-2">
                              {activeApprovalPacket.mustKeep.slice(0, 3).map((item) => (
                                <p key={item} className="text-xs leading-5 text-foreground/88">{item}</p>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {activeApprovalPacket?.guardrails.length ? (
                          <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                            <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">崩してはいけない条件</p>
                            <div className="mt-3 space-y-2">
                              {activeApprovalPacket.guardrails.slice(0, 3).map((item) => (
                                <p key={item} className="text-xs leading-5 text-foreground/88">{item}</p>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {activeApprovalPacket?.reviewChecklist.length ? (
                          <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                            <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">承認前チェック</p>
                            <div className="mt-3 space-y-2">
                              {activeApprovalPacket.reviewChecklist.slice(0, 3).map((item) => (
                                <p key={item} className="text-xs leading-5 text-foreground/88">{item}</p>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                    {activeVariant?.prototype_app ? (
                      <div className="rounded-[1.6rem] border border-border/70 bg-background/78 p-5">
                        <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">実装ハンドオフ試作</p>
                        <div className="mt-4 space-y-3">
                          <div className="flex flex-wrap gap-2">
                            <Badge variant="assistive" size="field">{prototypeFrameworkLabel(activeVariant.prototype_app.framework)}</Badge>
                            <Badge variant="optional" size="field">{prototypeRouterLabel(activeVariant.prototype_app.router)}</Badge>
                            <Badge variant="optional" size="field">
                              {activeVariant.prototype_app.artifact_summary?.route_count ?? activeVariant.prototype_app.entry_routes.length} ルート
                            </Badge>
                            <Badge variant="optional" size="field">
                              {activeVariant.prototype_app.artifact_summary?.file_count ?? activeVariant.prototype_app.files.length} ファイル
                            </Badge>
                          </div>
                          <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3 text-xs leading-6 text-muted-foreground">
                            <p className="font-medium text-foreground/90">{activeVariant.prototype_app.dev_command}</p>
                            <p>{activeVariant.prototype_app.build_command}</p>
                          </div>
                          <div className="space-y-2">
                            {activeVariant.prototype_app.files.slice(0, 4).map((file) => (
                              <div key={file.path} className="rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
                                <p className="text-xs font-semibold tracking-[0.14em] text-muted-foreground">{prototypeFileKindLabel(file.kind)}</p>
                                <p className="mt-1 text-xs leading-5 text-foreground/88">{file.path}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>

                {(activeVariant?.prototype?.screens.length ?? 0) > 0 ? (
                  <div className="space-y-3">
                    <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">画面ストーリーボード</p>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      {activeVariant?.prototype?.screens.map((screen) => (
                        <button
                          key={screen.id}
                          onClick={() => setActiveScreenId(screen.id)}
                          className={cn(
                            "rounded-[1.35rem] border px-4 py-4 text-left transition-colors",
                            screen.id === activeScreenId
                              ? "border-primary/50 bg-primary/8"
                              : "border-border/70 bg-background/72 hover:border-primary/25",
                          )}
                        >
                          <p className="text-xs font-semibold tracking-[0.14em] text-muted-foreground">{presentScreenText(screen.layout)}</p>
                          <p className="mt-2 text-sm font-semibold text-foreground">{presentScreenText(screen.title)}</p>
                          <p className="mt-2 text-xs leading-5 text-muted-foreground">{presentScreenText(screen.headline || screen.supporting_text)}</p>
                          {screen.success_state ? (
                            <p className="mt-3 text-xs leading-5 text-foreground/72">{presentScreenText(screen.success_state)}</p>
                          ) : null}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </section>
          ) : null}

          {reviewSection === "compare" ? (
            <>
          <section className="rounded-[2rem] border border-border/70 bg-card/92 p-6 shadow-[0_22px_80px_rgba(15,23,42,0.14)]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">比較する 2 案</p>
                <h3 className="mt-2 text-lg font-semibold text-foreground">同じ勝ち筋を、違う運用体験として見比べる</h3>
              </div>
              <Badge variant="assistive" size="field">{lc.designVariants.length}案</Badge>
            </div>
            <div className="mt-5 grid gap-4 xl:grid-cols-2">
              {lc.designVariants.map((variant, index) => (
                <DirectionCard
                  key={variant.id}
                  index={index}
                  label={presentDirectionLabel(index)}
                  variant={variant}
                  frame={projectFrame}
                  isActive={variant.id === activeVariant?.id}
                  isSelected={variant.id === lc.selectedDesignId}
                  onFocus={() => setActiveVariantId(variant.id)}
                  onSelect={() => selectDesign(variant.id)}
                />
              ))}
            </div>
          </section>

          {primaryCompareVariant && challengerCompareVariant ? (
            <section className="rounded-[2rem] border border-border/70 bg-card/92 p-6 shadow-[0_22px_80px_rgba(15,23,42,0.14)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">固定軸での比較</p>
                  <h3 className="mt-2 text-lg font-semibold text-foreground">承認判断に必要な観点を同じ行で比べる</h3>
                </div>
                <Badge variant="assistive" size="field">判断マトリクス</Badge>
              </div>
              <div className="mt-5 overflow-hidden rounded-[1.6rem] border border-border/70 bg-background/74">
                <div className="grid grid-cols-[11rem_minmax(0,1fr)_minmax(0,1fr)] border-b border-border/70 bg-card/90">
                  <div className="px-4 py-4 text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">比較軸</div>
                  <div className="border-l border-border/70 px-4 py-4 text-sm font-semibold text-foreground">
                    案 A / {presentVariantTitle(primaryCompareVariant, 0)}
                  </div>
                  <div className="border-l border-border/70 px-4 py-4 text-sm font-semibold text-foreground">
                    案 B / {presentVariantTitle(challengerCompareVariant, 1)}
                  </div>
                </div>
                {compareRows.map((row, index) => (
                  <div
                    key={row.label}
                    className={cn(
                      "grid grid-cols-[11rem_minmax(0,1fr)_minmax(0,1fr)]",
                      index < compareRows.length - 1 ? "border-b border-border/70" : "",
                    )}
                  >
                    <div className="bg-card/65 px-4 py-4">
                      <p className="text-xs font-semibold text-foreground">{row.label}</p>
                      <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{row.description}</p>
                    </div>
                    <div className="border-l border-border/70 px-4 py-4">
                      <p className="text-base font-semibold text-foreground">{row.left.value}</p>
                      <p className="mt-2 text-xs leading-5 text-muted-foreground">{row.left.note}</p>
                    </div>
                    <div className="border-l border-border/70 px-4 py-4">
                      <p className="text-base font-semibold text-foreground">{row.right.value}</p>
                      <p className="mt-2 text-xs leading-5 text-muted-foreground">{row.right.note}</p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {selectedVariant && runnerUpVariant ? (
            <section className="grid gap-4 xl:grid-cols-2">
              <div className="rounded-[1.8rem] border border-emerald-500/18 bg-emerald-500/8 p-5 shadow-[0_18px_60px_rgba(16,185,129,0.08)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-emerald-900/70 dark:text-emerald-200/90">今回採用する理由</p>
                <p className="mt-3 text-base font-semibold text-foreground">{selectedVariantTitle}</p>
                <p className="mt-3 text-sm leading-6 text-foreground/90">{variantSelectionSummary(selectedVariant)}</p>
                <div className="mt-4 space-y-2">
                  {variantSelectionReasons(selectedVariant).slice(0, 2).map((item) => (
                    <div key={`winner-${item}`} className="rounded-2xl border border-emerald-500/18 bg-background/82 px-4 py-3 text-sm leading-6 text-foreground/90">
                      {item}
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-[1.8rem] border border-amber-500/18 bg-amber-500/8 p-5 shadow-[0_18px_60px_rgba(245,158,11,0.08)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-amber-900/70 dark:text-amber-200/90">今回は見送る理由</p>
                <p className="mt-3 text-base font-semibold text-foreground">
                  {presentVariantTitle(runnerUpVariant, Math.max(lc.designVariants.findIndex((variant) => variant.id === runnerUpVariant.id), 0))}
                </p>
                <p className="mt-3 text-sm leading-6 text-foreground/90">{variantSelectionSummary(runnerUpVariant)}</p>
                <div className="mt-4 space-y-2">
                  {variantTradeoffs(runnerUpVariant).slice(0, 2).map((item) => (
                    <div key={`runner-up-${item}`} className="rounded-2xl border border-amber-500/18 bg-background/82 px-4 py-3 text-sm leading-6 text-foreground/90">
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            </section>
          ) : null}

          {primaryCompareVariant && challengerCompareVariant ? (
            <section className="rounded-[2rem] border border-border/70 bg-card/92 p-6 shadow-[0_22px_80px_rgba(15,23,42,0.14)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">構造差分レビュー</p>
                  <h3 className="mt-2 text-lg font-semibold text-foreground">構成方針と技術選定の違いを明示して比べる</h3>
                </div>
                <Badge variant="assistive" size="field">実装ブリーフ比較</Badge>
              </div>
              <div className="mt-5 grid gap-4 xl:grid-cols-2">
                {[primaryCompareVariant, challengerCompareVariant].map((variant, index) => {
                  const brief = implementationBriefFor(variant);
                  const variantLabel = `${presentDirectionLabel(index)} / ${presentVariantTitle(variant, index)}`;
                  const sliceViews = deliverySliceViews(brief?.delivery_slices);
                  return (
                    <div key={`diff-${variant.id}`} className="rounded-[1.6rem] border border-border/70 bg-background/74 p-5">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">{variantLabel}</p>
                          <p className="mt-2 text-sm font-medium text-foreground">{presentVariantModelLabel(variant)}</p>
                        </div>
                        <Badge variant={variant.id === lc.selectedDesignId ? "required" : "optional"} size="field">
                          {variant.id === lc.selectedDesignId ? "採用中" : "比較中"}
                        </Badge>
                      </div>

                      <div className="mt-4 rounded-2xl border border-border/60 bg-card/70 px-4 py-4">
                        <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">構成方針</p>
                        <p className="mt-2 text-sm leading-6 text-foreground/92">
                          {presentNamedItem(brief?.architecture_thesis || "主要フローを崩さずに引き継げる構成を優先します。")}
                        </p>
                      </div>

                      <div className="mt-4 grid gap-3 md:grid-cols-2">
                        <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-4">
                          <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">構成の骨格</p>
                          <div className="mt-3 space-y-2">
                            {(brief?.system_shape ?? []).slice(0, 4).map((item) => (
                              <p key={`${variant.id}-shape-${item}`} className="text-xs leading-5 text-foreground/88">
                                {presentNamedItem(item)}
                              </p>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-2xl border border-border/60 bg-card/70 px-4 py-4">
                          <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">実装スライス</p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {sliceViews.slice(0, 4).map((item) => (
                              <div key={`${variant.id}-slice-${item.key}`} className="max-w-full">
                                <SliceChip text={item.title} />
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      <div className="mt-4 space-y-3">
                        {(brief?.technical_choices ?? []).slice(0, 3).map((choice) => (
                          <div key={`${variant.id}-${choice.area}-${choice.decision}`} className="rounded-2xl border border-border/60 bg-card/70 px-4 py-4">
                            <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">{presentNamedItem(choice.area)}</p>
                            <p className="mt-2 text-sm font-medium text-foreground">{presentNamedItem(choice.decision)}</p>
                            <p className="mt-2 text-xs leading-5 text-muted-foreground">{presentNamedItem(choice.rationale)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-5 grid gap-4 xl:grid-cols-2">
                <div className="rounded-[1.5rem] border border-border/70 bg-background/72 p-5">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">案 A にだけ強く出ている構造</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(comparisonDelta.leftOnlyShape.length > 0 ? comparisonDelta.leftOnlyShape : comparisonDelta.leftOnlySlices).slice(0, 3).map((item) => (
                      <SliceChip key={`left-delta-${item}`} text={item} variant="optional" />
                    ))}
                    {(comparisonDelta.leftOnlyShape.length === 0 && comparisonDelta.leftOnlySlices.length === 0) ? (
                      <span className="text-sm text-muted-foreground">大きな構造差分はありません。</span>
                    ) : null}
                  </div>
                </div>
                <div className="rounded-[1.5rem] border border-border/70 bg-background/72 p-5">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">案 B にだけ強く出ている構造</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(comparisonDelta.rightOnlyShape.length > 0 ? comparisonDelta.rightOnlyShape : comparisonDelta.rightOnlySlices).slice(0, 3).map((item) => (
                      <SliceChip key={`right-delta-${item}`} text={item} variant="optional" />
                    ))}
                    {(comparisonDelta.rightOnlyShape.length === 0 && comparisonDelta.rightOnlySlices.length === 0) ? (
                      <span className="text-sm text-muted-foreground">大きな構造差分はありません。</span>
                    ) : null}
                  </div>
                </div>
              </div>
            </section>
          ) : null}
            </>
          ) : null}

          {reviewSection === "handoff" ? (
          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1.05fr)_minmax(21rem,0.92fr)]">
            <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.12)]">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">承認パケット</p>
              <p className="mt-4 text-sm leading-7 text-foreground/92">
                {activeApprovalPacket?.operatorPromise ?? "主要フロー、判断根拠、承認への引き継ぎが分断しない設計を固定します。"}
              </p>
              <div className="mt-4 rounded-2xl border border-border/60 bg-background/72 px-4 py-4">
                <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">引き継ぎサマリー</p>
                <p className="mt-2 text-sm leading-6 text-foreground/88">
                  {activeApprovalPacket?.handoffSummary ?? variantHandoffNote(activeFallbackVariant ?? lc.designVariants[0])}
                </p>
              </div>
              <div className="mt-4 space-y-3">
                {(activeApprovalPacket?.mustKeep ?? [
                  "主要フローと承認理由を同じ文脈で確認できること。",
                  "根拠、承認、成果物の系譜を分断しないこと。",
                  "モバイルでも主要状態と次の一手が読めること。",
                ]).slice(0, 4).map((item) => (
                  <div key={item} className="rounded-2xl border border-border/60 bg-background/72 px-4 py-3 text-sm text-foreground/90">
                    {presentNamedItem(item)}
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.12)]">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">アーキテクチャ方針と技術判断</p>
              <p className="mt-4 text-sm leading-7 text-foreground/92">
                {presentNamedItem(activeBrief?.architecture_thesis || "主要フロー、判断根拠、承認への引き継ぎが別々の画面責務に分断しない構成を優先します。")}
              </p>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-border/60 bg-background/72 px-4 py-4">
                  <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">構成の骨格</p>
                  <div className="mt-3 space-y-2">
                    {(activeBrief?.system_shape ?? [
                      "主要ワークスペース",
                      "フェーズ状態同期",
                      "承認パケット",
                      "成果物リネージ",
                    ]).slice(0, 4).map((item) => (
                      <p key={item} className="text-xs leading-5 text-foreground/88">
                        {presentNamedItem(item)}
                      </p>
                    ))}
                  </div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/72 px-4 py-4">
                  <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">今回固定する実装スライス</p>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    実装順と判断単位が一目で分かるよう、長文はカード内で折り返し、受け入れ条件は必要時だけ開ける構成にしています。
                  </p>
                  <div className="mt-3 grid gap-3 lg:grid-cols-2">
                    {deliverySliceViews(
                      (selectedBrief?.delivery_slices ?? activeBrief?.delivery_slices)
                      ?? selectedFeatures,
                    ).slice(0, 5).map((item) => (
                      <DeliverySliceCard key={item.key} slice={item} />
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {(activeBrief?.technical_choices ?? []).slice(0, 4).map((choice) => (
                  <div key={`${choice.area}-${choice.decision}`} className="rounded-2xl border border-border/60 bg-background/72 px-4 py-4">
                    <p className="text-xs font-semibold tracking-[0.14em] text-muted-foreground">{presentNamedItem(choice.area)}</p>
                    <p className="mt-2 text-sm font-medium text-foreground">{presentNamedItem(choice.decision)}</p>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">{presentNamedItem(choice.rationale)}</p>
                  </div>
                ))}
                {(activeBrief?.technical_choices?.length ?? 0) === 0 ? (
                  <p className="rounded-2xl border border-border/60 bg-background/72 px-4 py-4 text-sm text-muted-foreground">
                    技術選定は、主要フローを壊さない構成を優先して承認パケットに束ねます。
                  </p>
                ) : null}
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.12)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">実装ガードレール</p>
                <div className="mt-4 space-y-3">
                  {(activeApprovalPacket?.guardrails ?? [
                    "visible UI に内部用語や英語ラベルを残さない。",
                    "主要操作と blocked 状態のコントラストを下げない。",
                    "承認理由、差し戻し理由、次の一手をファーストビューに残す。",
                  ]).slice(0, 4).map((item) => (
                    <div key={item} className="rounded-2xl border border-border/60 bg-background/72 px-4 py-3">
                      <p className="text-sm leading-6 text-foreground/90">{presentNamedItem(item)}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.12)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">承認レビューのチェックリスト</p>
                <div className="mt-4 space-y-3">
                  {(activeApprovalPacket?.reviewChecklist ?? [
                    "主要 4 画面以上で table / metrics / status / form が揃っている。",
                    "承認または差し戻し理由を、その場で根拠と照合できる。",
                    "成果物の系譜と復旧導線が operator 目線で読める。",
                  ]).slice(0, 4).map((item) => (
                    <div key={item} className="rounded-2xl border border-border/60 bg-background/72 px-4 py-3 text-sm text-foreground/90">
                      {presentNamedItem(item)}
                    </div>
                  ))}
                </div>
                <div className="mt-4 rounded-2xl border border-border/60 bg-background/72 px-4 py-3 text-xs leading-6 text-muted-foreground">
                  {reviewFocusItems.slice(0, 2).join(" / ") || "承認前に確認する論点をパケットへ含めます。"}
                </div>
              </div>

              <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.12)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">マルチエージェント実装レーン</p>
                <div className="mt-4 space-y-3">
                  {(activeBrief?.agent_lanes ?? []).slice(0, 3).map((lane) => (
                    <div key={lane.role} className="rounded-2xl border border-border/60 bg-background/72 px-4 py-3">
                      <p className="text-sm font-medium text-foreground">{presentNamedItem(lane.role)}</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">{presentNamedItem(lane.remit)}</p>
                      {lane.skills.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {lane.skills.slice(0, 3).map((skill) => (
                            <Badge key={`${lane.role}-${skill}`} variant="assistive" size="field">{presentNamedItem(skill)}</Badge>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                  {(activeBrief?.agent_lanes?.length ?? 0) === 0 ? (
                    <p className="rounded-2xl border border-border/60 bg-background/72 px-4 py-4 text-sm text-muted-foreground">
                      プロダクト設計、アーキテクチャ設計、実装計画の 3 レーンで協調させます。
                    </p>
                  ) : null}
                </div>
              </div>
            </div>
          </section>
          ) : null}
          <BehaviorModelPanel analysis={lc.dcsAnalysis ?? null} />
          <TechnicalDesignPanel bundle={lc.technicalDesign ?? null} />
        </div>
      </div>
    </div>
  );
}

function HeroPanel({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] p-5">
      <p className="text-[11px] font-semibold tracking-[0.18em] text-white/55">{label}</p>
      <p className="mt-3 text-sm leading-7 text-white/82">{value}</p>
    </div>
  );
}

function SignalCluster({ title, items, emptyLabel }: { title: string; items: string[]; emptyLabel: string }) {
  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] p-5">
      <p className="text-[11px] font-semibold tracking-[0.18em] text-white/55">{title}</p>
      {items.length > 0 ? (
        <div className="mt-3 space-y-2">
          {items.map((item) => (
            <p key={item} className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white/82">
              {item}
            </p>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm text-white/62">{emptyLabel}</p>
      )}
    </div>
  );
}

function InfoStat({ label, value, tone }: { label: string; value: string; tone: "positive" | "warning" | "neutral" }) {
  return (
    <div className={cn(
      "rounded-[1.35rem] border p-4",
      tone === "positive"
        ? "border-emerald-400/18 bg-emerald-400/10 text-emerald-50"
        : tone === "warning"
          ? "border-amber-500/25 bg-amber-500/10 text-amber-950 dark:text-amber-100"
        : "border-border/70 bg-background/78 text-foreground",
    )}>
      <p className={cn(
        "text-[11px] font-semibold tracking-[0.18em]",
        tone === "positive"
          ? "text-emerald-100/72"
          : tone === "warning"
            ? "text-amber-900/70 dark:text-amber-100/72"
            : "text-muted-foreground",
      )}>
        {label}
      </p>
      <p className="mt-2 text-xl font-semibold tracking-tight">{value}</p>
    </div>
  );
}

function ScoreStat({ label, value, evidence }: { label: string; value: number; evidence?: string }) {
  return (
    <div className="rounded-[1.2rem] border border-border/70 bg-background/78 p-4">
      <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">{label}</p>
      <p className="mt-2 text-lg font-semibold tracking-tight text-foreground">{Math.round(value * 100)}</p>
      {evidence ? (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{evidence}</p>
      ) : null}
    </div>
  );
}

function DirectionCard(props: {
  index: number;
  label: string;
  variant: DesignVariant;
  frame: LifecycleDecisionFrame | null;
  isActive: boolean;
  isSelected: boolean;
  onFocus: () => void;
  onSelect: () => void;
}) {
  const { index, label, variant, frame, isActive, isSelected, onFocus, onSelect } = props;
  const metrics = scoreItems(variant).slice(0, 3);
  return (
    <div
      className={cn(
        "rounded-[1.7rem] border p-5 transition-colors",
        isActive ? "border-primary/45 bg-primary/[0.07] shadow-[0_18px_50px_rgba(37,99,235,0.08)]" : "border-border/70 bg-background/72",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-border/70 bg-card px-2.5 py-1 text-[11px] font-medium tracking-[0.14em] text-muted-foreground">
              {label}
            </span>
            {isSelected ? (
              <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-200">
                選択中
              </span>
            ) : null}
          </div>
          <h4 className="mt-3 text-base font-semibold text-foreground">{presentVariantTitle(variant, index)}</h4>
          <p className="mt-2 text-xs leading-6 text-muted-foreground">{variantSelectionSummary(variant)}</p>
          <p className="mt-3 text-[11px] text-muted-foreground">
            {presentVariantModelLabel(variant)} ・ 参考コスト ${presentVariantEstimatedCost(variant).toFixed(3)}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge variant="optional" size="field">{freshnessLabel(variant)}</Badge>
            <Badge variant="optional" size="field">{completenessLabel(variant)}</Badge>
            {variant.preview_meta ? (
              <Badge variant="optional" size="field">{previewSourceDetailLabel(variant)}</Badge>
            ) : null}
          </div>
        </div>
        <button
          onClick={onFocus}
          aria-pressed={isActive}
          className={cn(
            "rounded-full border px-3 py-1.5 text-xs transition-colors",
            isActive ? "border-primary/40 bg-primary text-primary-foreground" : "border-border/70 text-muted-foreground hover:text-foreground",
          )}
        >
          {isActive ? "閲覧中" : "見る"}
        </button>
      </div>

      <div className="mt-4 rounded-[1.2rem] border border-border/70 bg-card/78 px-4 py-3">
        <p className="text-xs leading-6 text-foreground/88">{variantOperationalBet(variant)}</p>
      </div>

      {variant.implementation_brief ? (
        <div className="mt-4 rounded-[1.2rem] border border-border/70 bg-background/72 px-4 py-3">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground">実装方針</p>
          <p className="mt-2 text-xs leading-5 text-foreground/88">
            {presentNamedItem(variant.implementation_brief.architecture_thesis)}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {deliverySliceViews(variant.implementation_brief.delivery_slices).slice(0, 3).map((item) => (
              <div key={`${variant.id}-${item.key}`} className="max-w-full">
                <SliceChip text={item.title} />
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {metrics.map((item) => (
          <div key={item.label} className="rounded-2xl border border-border/60 bg-background/72 px-3 py-3">
            <p className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground">{item.label}</p>
            <p className="mt-2 text-sm font-semibold tracking-tight text-foreground">{Math.round(item.value * 100)}</p>
            {item.evidence ? (
              <p className="mt-2 text-[11px] leading-5 text-muted-foreground">{item.evidence}</p>
            ) : null}
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between gap-3">
        <Button
          size="sm"
          variant={isSelected ? "default" : "outline"}
          className="gap-1.5"
          onClick={onSelect}
        >
          {isSelected ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Star className="h-3.5 w-3.5" />}
          {isSelected ? "採用済み" : "基準案にする"}
        </Button>
        <button
          onClick={() => openPreviewInNewTab(localizePreviewHtmlForDisplay(variant.preview_html))}
          className="inline-flex items-center gap-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <Maximize2 className="h-3.5 w-3.5" />
          フルサイズで確認
        </button>
      </div>

      {variantSignatureMoments(variant).length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {variantSignatureMoments(variant).slice(0, 3).map((moment) => (
            <span key={moment} className="rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] text-muted-foreground">
              {presentSignatureMoment(moment)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
