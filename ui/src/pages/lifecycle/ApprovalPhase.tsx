import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock3,
  FileText,
  Flag,
  Loader2,
  MessageSquare,
  Palette,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { lifecycleApi } from "@/api/lifecycle";
import {
  presentDeliverySlices,
  presentFeatureLabel,
  presentNamedItem,
  presentVariantApprovalPacket,
  presentVariantModelLabel,
  presentVariantSelectionReasons,
  presentVariantSelectionSummary,
  presentVariantTitle,
} from "@/lifecycle/designDecisionPresentation";
import {
  downstreamActionVariants,
  downstreamEyebrowClassName,
  downstreamMetricVariants,
  downstreamSurfaceVariants,
  downstreamTopbarClassName,
  downstreamWorkspaceClassName,
} from "@/lifecycle/downstreamTheme";
import { buildApprovalPayload } from "@/lifecycle/inputs";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { selectApprovalViewModel } from "@/lifecycle/selectors";

function approvalStatusMeta(status: "pending" | "approved" | "rejected" | "revision_requested") {
  if (status === "approved") {
    return {
      label: "承認済み",
      description: "承認レビューは完了しています。開発フェーズへ引き継げます。",
      tone: "success" as const,
      icon: CheckCircle2,
    };
  }
  if (status === "revision_requested" || status === "rejected") {
    return {
      label: "差し戻し",
      description: "上流フェーズへ戻って判断を更新してください。再レビュー前提で差し戻されています。",
      tone: "danger" as const,
      icon: XCircle,
    };
  }
  return {
    label: "承認待ち",
    description: "企画、デザイン、実装ハンドオフの整合を確認し、このまま開発へ渡せるかを判断します。",
    tone: "warning" as const,
    icon: Clock3,
  };
}

function freshnessLabel(status: string | undefined, canHandoff: boolean | undefined): string {
  if (status === "fresh" && canHandoff) return "最新";
  if (status === "stale") return "要再生成";
  if (canHandoff === false) return "保留";
  return "未確認";
}

function completenessLabel(status: string | undefined): string {
  if (status === "complete") return "完全";
  if (status === "partial") return "一部不足";
  if (status === "incomplete") return "不足";
  return "未評価";
}

function previewSourceLabel(source: string | undefined): string {
  if (source === "llm") return "LLM";
  if (source === "repaired") return "再構成";
  if (source === "template") return "テンプレート";
  return "未確認";
}

function toneClasses(tone: "success" | "warning" | "danger") {
  if (tone === "success") {
    return {
      shell: "border-emerald-200 bg-emerald-50/80",
      icon: "text-emerald-700",
      badge: "border-emerald-300 bg-emerald-100 text-emerald-900",
    };
  }
  if (tone === "danger") {
    return {
      shell: "border-rose-200 bg-rose-50/80",
      icon: "text-rose-700",
      badge: "border-rose-300 bg-rose-100 text-rose-900",
    };
  }
  return {
    shell: "border-amber-200 bg-amber-50/80",
    icon: "text-amber-700",
    badge: "border-amber-300 bg-amber-100 text-amber-900",
  };
}

function formatScore(score: number | undefined): string {
  if (typeof score !== "number" || Number.isNaN(score)) return "未計測";
  return `${Math.round(score * 100)}点`;
}

function MetricCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof FileText;
}) {
  return (
    <div className={downstreamMetricVariants()}>
      <div className={cn("flex items-center gap-2", downstreamEyebrowClassName)}>
        <Icon className="h-3.5 w-3.5 text-primary" />
        {label}
      </div>
      <p className="mt-3 text-lg font-semibold text-foreground">{value}</p>
    </div>
  );
}

function ListBlock({
  title,
  items,
  tone = "neutral",
}: {
  title: string;
  items: string[];
  tone?: "neutral" | "warning";
}) {
  if (items.length === 0) return null;
  return (
    <div className={downstreamSurfaceVariants({ tone: tone === "warning" ? "warning" : "inset", padding: "sm" })}>
      <p className={downstreamEyebrowClassName}>{title}</p>
      <div className="mt-3 space-y-2">
        {items.map((item) => (
          <div
            key={item}
            className={cn(
              "rounded-2xl border px-3 py-2 text-sm leading-6",
              tone === "warning"
                ? "border-amber-200 bg-amber-50/70 text-amber-950"
                : "border-border/60 bg-muted/10 text-foreground/90",
            )}
          >
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ApprovalPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState<"comment" | "approve" | "reject" | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    allChecked,
    approvalPacketReady,
    checkItems,
    checklistProgressPercent,
    completedChecklistCount,
    designIntegrityReady,
    milestoneCount,
    reviewLinks,
    selectedDesign,
    selectedFeatureCount,
    selectedFeatures,
    selectedRouteCount,
    selectedScreenCount,
    selectedWorkflowCount,
  } = selectApprovalViewModel(lc);

  const statusMeta = approvalStatusMeta(lc.approvalStatus);
  const tone = toneClasses(statusMeta.tone);
  const StatusIcon = statusMeta.icon;

  const selectedTitle = selectedDesign ? presentVariantTitle(selectedDesign, -1) : "未選択";
  const selectedModel = selectedDesign ? presentVariantModelLabel(selectedDesign) : "未選択";
  const selectedSummary = selectedDesign ? presentVariantSelectionSummary(selectedDesign) : "比較済みのデザインがまだ選ばれていません。";
  const selectedReasons = selectedDesign ? presentVariantSelectionReasons(selectedDesign).slice(0, 3) : [];
  const approvalPacket = useMemo(
    () => (selectedDesign ? presentVariantApprovalPacket(selectedDesign) : null),
    [selectedDesign],
  );
  const deliverySlices = presentDeliverySlices(selectedDesign?.implementation_brief?.delivery_slices);
  const scoreItems = (selectedDesign?.scorecard?.dimensions ?? []).map((item) => ({
    label: presentNamedItem(item.label),
    evidence: presentNamedItem(item.evidence),
    score: formatScore(item.score),
  }));

  const submitComment = async (type: "comment" | "approve" | "reject") => {
    if (!projectSlug) return;
    if (type === "comment" && !comment.trim()) return;
    if (submitting !== null) return;
    setSubmitting(type);
    setSubmitError(null);
    try {
      const payload = buildApprovalPayload(type, comment);
      if (type === "comment") {
        const response = await lifecycleApi.addApprovalComment(projectSlug, payload);
        actions.applyProject(response.project);
      } else {
        const decision = type === "approve" ? "approved" : "revision_requested";
        const response = await lifecycleApi.decideApproval(projectSlug, decision, payload.text);
        actions.applyProject(response.project);
      }
      setComment("");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "コメントの送信に失敗しました");
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <div className={cn(downstreamWorkspaceClassName, "min-h-full")}>
      <div className="mx-auto max-w-6xl px-6 py-6">
        <div className={cn(downstreamTopbarClassName, "flex flex-wrap items-center gap-3 rounded-[1.5rem] px-4 py-4")}>
          <button onClick={() => navigate(`/p/${projectSlug}/lifecycle/design`)} className="text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <p className={downstreamEyebrowClassName}>PHASE 4 / 7</p>
            <h1 className="mt-1 flex items-center gap-2 text-lg font-semibold text-foreground">
              <ShieldCheck className="h-4 w-4 text-primary" />
              承認レビュー
            </h1>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="rounded-full border-border/70 bg-background/82 px-3 py-1 text-[11px] text-foreground">
              選択案: {selectedTitle}
            </Badge>
            {lc.approvalStatus === "approved" && (
              <button
                onClick={() => navigate(`/p/${projectSlug}/lifecycle/development`)}
                className={downstreamActionVariants({ tone: "primary" })}
              >
                開発へ進む
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        <div className={cn("mt-6 rounded-[2rem] border p-6 shadow-[0_24px_70px_rgba(15,23,42,0.08)]", tone.shell)}>
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,0.8fr)]">
            <div className="space-y-4">
              <div className="flex flex-wrap items-start gap-4">
                <div className={cn("flex h-12 w-12 items-center justify-center rounded-2xl border", tone.badge)}>
                  <StatusIcon className={cn("h-6 w-6", tone.icon)} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={cn("rounded-full px-3 py-1 text-[11px] font-semibold", tone.badge)}>
                      {statusMeta.label}
                    </Badge>
                    <Badge variant="outline" className="rounded-full border-border/70 bg-background/80 px-3 py-1 text-[11px] text-foreground">
                      {selectedModel}
                    </Badge>
                  </div>
                  <h2 className="mt-3 text-2xl font-semibold tracking-tight text-foreground">
                    {selectedTitle} を開発の基準案として固定するかを最終確認します
                  </h2>
                  <p className="mt-2 max-w-3xl text-sm leading-7 text-muted-foreground">
                    {statusMeta.description}
                  </p>
                  <p className="mt-3 max-w-3xl text-sm leading-7 text-foreground/90">
                    {selectedSummary}
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-4">
                <MetricCard label="機能スコープ" value={`${selectedFeatureCount} 機能`} icon={Users} />
                <MetricCard label="マイルストーン" value={`${milestoneCount} 件`} icon={Flag} />
                <MetricCard label="主要画面" value={`${selectedScreenCount} 画面`} icon={Palette} />
                <MetricCard label="主要フロー" value={`${selectedWorkflowCount} 本`} icon={Sparkles} />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
              <div className="rounded-[1.4rem] border border-border/60 bg-background/80 p-4 shadow-[0_12px_28px_rgba(15,23,42,0.05)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">ハンドオフ整合</p>
                <div className="mt-3 space-y-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">鮮度</span>
                    <span className="font-semibold text-foreground">{freshnessLabel(selectedDesign?.freshness?.status, selectedDesign?.freshness?.can_handoff)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">構造化成果物</span>
                    <span className="font-semibold text-foreground">{completenessLabel(selectedDesign?.artifact_completeness?.status)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">プレビュー出所</span>
                    <span className="font-semibold text-foreground">{previewSourceLabel(selectedDesign?.preview_meta?.source)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">ルート数</span>
                    <span className="font-semibold text-foreground">{selectedRouteCount}</span>
                  </div>
                </div>
              </div>
              <div className="rounded-[1.4rem] border border-border/60 bg-background/80 p-4 shadow-[0_12px_28px_rgba(15,23,42,0.05)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">承認判断の要点</p>
                <div className="mt-3 space-y-2 text-sm leading-6 text-foreground/90">
                  {selectedReasons.length > 0 ? selectedReasons.map((reason) => (
                    <div key={reason} className="rounded-2xl border border-border/60 bg-muted/10 px-3 py-2">
                      {reason}
                    </div>
                  )) : (
                    <div className="rounded-2xl border border-dashed border-border/60 px-3 py-3 text-muted-foreground">
                      選定理由はまだ生成されていません。
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.18fr)_minmax(22rem,0.82fr)]">
          <div className="space-y-6">
            <div className={downstreamSurfaceVariants({ tone: "strong", padding: "lg" })}>
              <p className={cn("tracking-[0.2em]", downstreamEyebrowClassName)}>今回固定する内容</p>
              <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
                <div className="rounded-[1.35rem] border border-border/60 bg-background/80 p-4">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">プロダクト仕様</p>
                  <p className="mt-3 text-sm leading-7 text-foreground/90">{presentNamedItem(lc.spec) || "未入力"}</p>
                </div>
                <div className="rounded-[1.35rem] border border-border/60 bg-background/80 p-4">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">オペレーターへの約束</p>
                  <p className="mt-3 text-sm leading-7 text-foreground/90">
                    {approvalPacket?.operatorPromise ?? "承認パケットがまだ揃っていません。"}
                  </p>
                </div>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-[1.35rem] border border-border/60 bg-background/80 p-4">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">固定した機能</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {selectedFeatures.length > 0 ? selectedFeatures.map((feature) => (
                      <Badge
                        key={feature.feature}
                        variant="outline"
                        className="rounded-full border-border/70 bg-muted/10 px-3 py-1 text-[11px] font-medium text-foreground"
                      >
                        {presentFeatureLabel(feature.feature)}
                      </Badge>
                    )) : (
                      <span className="text-sm text-muted-foreground">まだ機能が選択されていません。</span>
                    )}
                  </div>
                </div>
                <div className="rounded-[1.35rem] border border-border/60 bg-background/80 p-4">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">完成条件</p>
                  <div className="mt-3 space-y-2">
                    {lc.milestones.length > 0 ? lc.milestones.map((milestone, index) => (
                      <div key={milestone.id} className="flex items-start gap-3 rounded-2xl border border-border/55 bg-muted/10 px-3 py-2.5">
                        <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
                          {index + 1}
                        </span>
                        <div>
                          <p className="text-sm font-medium text-foreground">{presentNamedItem(milestone.name)}</p>
                          <p className="mt-1 text-xs leading-5 text-muted-foreground">{presentNamedItem(milestone.criteria)}</p>
                        </div>
                      </div>
                    )) : (
                      <span className="text-sm text-muted-foreground">まだマイルストーンが定義されていません。</span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <ListBlock title="絶対に守ること" items={approvalPacket?.mustKeep ?? []} />
              <ListBlock title="承認前の注意点" items={approvalPacket?.guardrails ?? []} tone="warning" />
            </div>

            <div className={downstreamSurfaceVariants({ tone: "strong", padding: "lg" })}>
              <div className="flex flex-wrap items-center gap-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.2em] text-muted-foreground">判断シート</p>
                  <h3 className="mt-2 text-lg font-semibold text-foreground">選択案を採用する理由と、承認時に見る根拠</h3>
                </div>
                <Badge variant="outline" className="ml-auto rounded-full border-border/70 bg-background/80 px-3 py-1 text-[11px] text-foreground">
                  総合評価 {formatScore(selectedDesign?.scorecard?.overall_score)}
                </Badge>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {scoreItems.length > 0 ? scoreItems.map((item) => (
                  <div key={item.label} className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-foreground">{item.label}</p>
                      <Badge variant="outline" className="rounded-full border-primary/30 bg-primary/5 px-3 py-1 text-[11px] text-primary">
                        {item.score}
                      </Badge>
                    </div>
                    <p className="mt-3 text-xs leading-6 text-muted-foreground">{item.evidence}</p>
                  </div>
                )) : (
                  <div className="rounded-[1.3rem] border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
                    判断シートはまだ生成されていません。
                  </div>
                )}
              </div>

              <ListBlock title="承認時に確認するチェックリスト" items={approvalPacket?.reviewChecklist ?? []} />
            </div>

            <div className={downstreamSurfaceVariants({ tone: "strong", padding: "lg" })}>
              <div className="flex flex-wrap items-center gap-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.2em] text-muted-foreground">実装ハンドオフ</p>
                  <h3 className="mt-2 text-lg font-semibold text-foreground">今回固定する実装スライスと技術判断</h3>
                </div>
                <Badge variant="outline" className="ml-auto rounded-full border-border/70 bg-background/80 px-3 py-1 text-[11px] text-foreground">
                  {deliverySlices.length} スライス
                </Badge>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {deliverySlices.length > 0 ? deliverySlices.map((slice) => (
                  <div key={slice.key} className="rounded-[1.35rem] border border-border/60 bg-background/82 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      {slice.code ? (
                        <Badge variant="outline" className="rounded-full border-primary/30 bg-primary/5 px-3 py-1 text-[11px] text-primary">
                          {slice.code}
                        </Badge>
                      ) : null}
                      {slice.milestone ? (
                        <Badge variant="outline" className="rounded-full border-border/70 bg-muted/10 px-3 py-1 text-[11px] text-foreground">
                          {slice.milestone}
                        </Badge>
                      ) : null}
                    </div>
                    <p className="mt-3 text-sm font-semibold leading-6 text-foreground [overflow-wrap:anywhere]">{slice.title}</p>
                    {slice.acceptance ? (
                      <div className="mt-3 rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                        <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">受け入れ条件</p>
                        <p className="mt-2 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">{slice.acceptance}</p>
                      </div>
                    ) : null}
                  </div>
                )) : (
                  <div className="rounded-[1.35rem] border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
                    実装スライスはまだ生成されていません。
                  </div>
                )}
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-[1.35rem] border border-border/60 bg-background/82 p-4">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">技術判断</p>
                  <div className="mt-3 space-y-3">
                    {(selectedDesign?.implementation_brief?.technical_choices ?? []).slice(0, 4).map((choice) => (
                      <div key={`${choice.area}-${choice.decision}`} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                        <p className="text-sm font-semibold text-foreground">{presentNamedItem(choice.area)}</p>
                        <p className="mt-2 text-xs leading-5 text-foreground/90">{presentNamedItem(choice.decision)}</p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">{presentNamedItem(choice.rationale)}</p>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="rounded-[1.35rem] border border-border/60 bg-background/82 p-4">
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">実装レーン</p>
                  <div className="mt-3 space-y-3">
                    {(selectedDesign?.implementation_brief?.agent_lanes ?? []).slice(0, 4).map((lane) => (
                      <div key={`${lane.role}-${lane.remit}`} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                        <p className="text-sm font-semibold text-foreground">{presentNamedItem(lane.role)}</p>
                        <p className="mt-2 text-xs leading-5 text-foreground/90">{presentNamedItem(lane.remit)}</p>
                        {lane.skills.length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {lane.skills.slice(0, 4).map((skill) => (
                              <Badge key={skill} variant="outline" className="rounded-full border-border/70 bg-background/80 px-3 py-1 text-[11px] text-foreground">
                                {presentNamedItem(skill)}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className={downstreamSurfaceVariants({ tone: "strong", padding: "lg" })}>
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-primary" />
                <h3 className="text-lg font-semibold text-foreground">レビュー履歴</h3>
              </div>
              <div className="mt-4 space-y-3">
                {lc.approvalComments.length === 0 ? (
                  <div className="rounded-[1.35rem] border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
                    まだコメントはありません。承認理由や差し戻し理由をここに残します。
                  </div>
                ) : lc.approvalComments.map((entry) => (
                  <div
                    key={entry.id}
                    className={cn(
                      "rounded-[1.35rem] border px-4 py-3",
                      entry.type === "approve"
                        ? "border-emerald-200 bg-emerald-50/70"
                        : entry.type === "reject"
                          ? "border-rose-200 bg-rose-50/70"
                          : "border-border/60 bg-background/82",
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">
                      <span>
                        {entry.type === "approve" ? "承認" : entry.type === "reject" ? "差し戻し" : "コメント"}
                      </span>
                      <span className="ml-auto tracking-normal">{new Date(entry.time).toLocaleString("ja-JP")}</span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-foreground/90">{entry.text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
            <div className={downstreamSurfaceVariants({ tone: "strong", padding: "md" })}>
              <p className={downstreamEyebrowClassName}>承認ドック</p>
              <div className="mt-4 space-y-3">
                <div className="rounded-[1.3rem] border border-border/60 bg-background/82 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-foreground">レビュー進捗</p>
                    <span className="text-xs font-medium text-muted-foreground">{completedChecklistCount}/{checkItems.length}</span>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-muted/70">
                    <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${checklistProgressPercent}%` }} />
                  </div>
                  <div className="mt-4 space-y-2">
                    {checkItems.map((item) => (
                      <button
                        key={item.label}
                        onClick={() => navigate(`/p/${projectSlug}/lifecycle/${item.phase}`)}
                        className="flex w-full items-center gap-2 rounded-2xl border border-border/55 bg-muted/10 px-3 py-2 text-left text-sm transition-colors hover:bg-accent/60"
                      >
                        {item.done ? (
                          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
                        ) : (
                          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                        )}
                        <span className={item.done ? "text-foreground" : "text-muted-foreground"}>{item.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded-[1.3rem] border border-border/60 bg-background/82 p-4">
                  <p className="text-sm font-semibold text-foreground">ハンドオフ可否</p>
                  <div className="mt-3 space-y-2 text-sm">
                    <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                      <span className="text-muted-foreground">構造化成果物</span>
                      <span className={approvalPacketReady ? "font-semibold text-emerald-700" : "font-semibold text-amber-700"}>
                        {approvalPacketReady ? "揃っている" : "不足あり"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                      <span className="text-muted-foreground">鮮度とプレビュー契約</span>
                      <span className={designIntegrityReady ? "font-semibold text-emerald-700" : "font-semibold text-amber-700"}>
                        {designIntegrityReady ? "有効" : "要確認"}
                      </span>
                    </div>
                  </div>
                  {selectedDesign?.freshness?.reasons?.length ? (
                    <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50/70 px-3 py-3 text-xs leading-5 text-amber-950">
                      {selectedDesign.freshness.reasons.slice(0, 2).map((reason) => presentNamedItem(reason)).join(" / ")}
                    </div>
                  ) : null}
                </div>

                {lc.approvalStatus === "revision_requested" && (
                  <div className="rounded-[1.3rem] border border-rose-200 bg-rose-50/70 p-4">
                    <p className="text-sm font-semibold text-rose-900">差し戻し先</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {reviewLinks.map((link) => (
                        <button
                          key={link.phase}
                          onClick={() => navigate(`/p/${projectSlug}/lifecycle/${link.phase}`)}
                          className="rounded-full border border-rose-200 bg-background/90 px-3 py-1.5 text-xs font-medium text-rose-900 transition-colors hover:bg-rose-100/80"
                        >
                          {link.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="rounded-[1.3rem] border border-border/60 bg-background/82 p-4">
                  <p className="text-sm font-semibold text-foreground">判断メモ</p>
                  <textarea
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    placeholder="承認理由、差し戻し理由、気になる点を残す..."
                    rows={4}
                    className="mt-3 w-full rounded-2xl border border-border/60 bg-card px-3 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                  {submitError ? (
                    <div className="mt-3 rounded-2xl border border-rose-200 bg-rose-50/70 px-3 py-2 text-xs text-rose-900">
                      {submitError}
                    </div>
                  ) : null}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      onClick={() => void submitComment("comment")}
                      disabled={!comment.trim() || submitting !== null}
                      className="rounded-full border border-border/70 bg-background px-4 py-2 text-xs font-semibold text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {submitting === "comment" ? (
                        <span className="inline-flex items-center gap-1">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          保存中
                        </span>
                      ) : "コメントを残す"}
                    </button>
                    <div className="ml-auto flex flex-wrap gap-2">
                      <button
                        onClick={() => void submitComment("reject")}
                        disabled={submitting !== null}
                        className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50/70 px-4 py-2 text-xs font-semibold text-rose-900 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {submitting === "reject" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
                        差し戻す
                      </button>
                      <button
                        onClick={() => void submitComment("approve")}
                        disabled={!allChecked || submitting !== null}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full px-4 py-2 text-xs font-semibold text-white transition-colors",
                          allChecked && submitting === null
                            ? "bg-emerald-600 hover:bg-emerald-700"
                            : "cursor-not-allowed bg-muted text-muted-foreground",
                        )}
                      >
                        {submitting === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                        承認する
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
