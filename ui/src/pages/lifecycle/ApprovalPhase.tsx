import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ShieldCheck, Check, X, ArrowRight, ArrowLeft, MessageSquare,
  FileText, Users, Palette, Flag, CheckCircle2, XCircle,
  Clock, AlertTriangle, Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { lifecycleApi } from "@/api/lifecycle";
import { buildApprovalPayload } from "@/lifecycle/inputs";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { selectApprovalViewModel } from "@/lifecycle/selectors";

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
    checkItems,
    checklistProgressPercent,
    completedChecklistCount,
    milestoneCount,
    reviewLinks,
    selectedDesign,
    selectedFeatureCount,
  } = selectApprovalViewModel(lc);

  const submitComment = async (type: "comment" | "approve" | "reject") => {
    if (!projectSlug) return;
    if (type === "comment" && !comment.trim()) return;
    if (submitting !== null) return;
    setSubmitting(type);
    setSubmitError(null);
    try {
      const payload = buildApprovalPayload(type, comment);
      const project = await lifecycleApi.addApprovalComment(projectSlug, payload);
      actions.applyProject(project);
      if (type === "approve") {
        actions.completePhase("approval");
      }
      setComment("");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "コメントの送信に失敗しました");
    } finally {
      setSubmitting(null);
    }
  };

  const goNext = () => navigate(`/p/${projectSlug}/lifecycle/development`);
  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/design`);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-6 py-3">
        <button onClick={goBack} className="text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="flex items-center gap-2 text-sm font-bold text-foreground">
          <ShieldCheck className="h-4 w-4 text-primary" /> 企画承認
        </h1>
        <div className="flex-1" />
        {lc.approvalStatus === "approved" && (
          <button onClick={goNext} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
            開発へ <ArrowRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-4xl grid gap-6 lg:grid-cols-5">
          {/* Main content - left */}
          <div className="lg:col-span-3 space-y-6">
            {/* Status banner */}
            <div className={cn(
              "rounded-xl border-2 p-5",
              lc.approvalStatus === "approved" ? "border-success/30 bg-success/5" :
              lc.approvalStatus === "revision_requested" ? "border-destructive/30 bg-destructive/5" :
              "border-primary/30 bg-primary/5",
            )}>
              <div className="flex items-center gap-3">
                {lc.approvalStatus === "approved" ? <CheckCircle2 className="h-8 w-8 text-success" /> :
                 lc.approvalStatus === "revision_requested" ? <XCircle className="h-8 w-8 text-destructive" /> :
                 <Clock className="h-8 w-8 text-primary" />}
                <div>
                  <h2 className="text-lg font-bold text-foreground">
                    {lc.approvalStatus === "approved" ? "承認済み" :
                     lc.approvalStatus === "revision_requested" ? "要修正" :
                     "承認待ち"}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {lc.approvalStatus === "approved" ? "企画内容が承認されました。開発フェーズへ進めます。" :
                     lc.approvalStatus === "revision_requested" ? "企画内容に修正が必要です。前のフェーズに戻って修正してください。" :
                     "以下の企画内容をレビューし、承認または差し戻してください。"}
                  </p>
                  {lc.approvalStatus === "revision_requested" && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {reviewLinks.map((link) => (
                        <button
                          key={link.phase}
                          onClick={() => navigate(`/p/${projectSlug}/lifecycle/${link.phase}`)}
                          className={cn(
                            "rounded-md border px-3 py-1.5 text-xs transition-colors",
                            link.ready
                              ? "border-destructive/30 bg-background text-foreground hover:bg-destructive/10"
                              : "border-border text-muted-foreground hover:bg-accent",
                          )}
                        >
                          {link.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Summary cards */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <SummaryCard icon={FileText} title="プロダクト仕様" content={lc.spec} />
              <SummaryCard icon={Users} title="ペルソナ" content={`${lc.analysis?.personas.length ?? 0}名のペルソナを定義`} />
              <SummaryCard icon={Palette} title="デザインパターン" content={selectedDesign ? `${selectedDesign.pattern_name} (${selectedDesign.model})` : "未選択"} />
              <SummaryCard icon={Flag} title="マイルストーン" content={`${milestoneCount}個の完成条件`} />
            </div>

            {/* Feature scope */}
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="text-sm font-bold text-foreground mb-3">実装スコープ ({selectedFeatureCount}機能)</h3>
              <div className="flex flex-wrap gap-1.5">
                {lc.features.filter((f) => f.selected).map((f) => {
                  const catColor: Record<string, string> = { "must-be": "border-destructive/30 bg-destructive/5 text-destructive", "one-dimensional": "border-primary/30 bg-primary/5 text-primary", attractive: "border-success/30 bg-success/5 text-success" };
                  return (
                    <Badge key={f.feature} variant="outline" className={cn("text-[11px]", catColor[f.category])}>
                      {f.feature}
                    </Badge>
                  );
                })}
              </div>
            </div>

            {/* Comments thread */}
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <MessageSquare className="h-4 w-4" /> コメント
              </h3>
              {lc.approvalComments.length === 0 && (
                <p className="text-xs text-muted-foreground py-4 text-center">コメントはまだありません</p>
              )}
              <div className="space-y-2 mb-3">
                {lc.approvalComments.map((c) => (
                  <div key={c.id} className={cn("rounded-lg p-3 text-sm",
                    c.type === "approve" ? "bg-success/10 text-success" :
                    c.type === "reject" ? "bg-destructive/10 text-destructive" :
                    "bg-accent text-foreground",
                  )}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium">
                        {c.type === "approve" ? "✓ 承認" : c.type === "reject" ? "✗ 差し戻し" : "コメント"}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {new Date(c.time).toLocaleString("ja-JP")}
                      </span>
                    </div>
                    <p className="text-xs">{c.text}</p>
                  </div>
                ))}
              </div>

              {submitError && (
                <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                  {submitError}
                </p>
              )}

              {lc.approvalStatus !== "approved" && (
                <div className="space-y-2">
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="コメントを入力..."
                    rows={2}
                    className="w-full rounded-lg border border-border bg-background p-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => void submitComment("comment")}
                      disabled={!comment.trim() || submitting !== null}
                      className="rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      {submitting === "comment" ? <span className="inline-flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" />送信中</span> : "コメント"}
                    </button>
                    <div className="flex-1" />
                    <button
                      onClick={() => void submitComment("reject")}
                      disabled={submitting !== null}
                      className="flex items-center gap-1 rounded-md border border-destructive/30 px-3 py-1.5 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50"
                    >
                      {submitting === "reject" ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />} 差し戻し
                    </button>
                    <button onClick={() => void submitComment("approve")} disabled={!allChecked || submitting !== null} className={cn(
                      "flex items-center gap-1 rounded-md px-4 py-1.5 text-xs font-medium transition-colors",
                      allChecked && submitting === null ? "bg-success text-white hover:bg-success/90" : "bg-muted text-muted-foreground cursor-not-allowed",
                    )}>
                      {submitting === "approve" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />} 承認
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Sidebar - right */}
          <div className="lg:col-span-2 space-y-4">
            {/* Checklist */}
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="text-sm font-bold text-foreground mb-3">承認チェックリスト</h3>
              <div className="space-y-2">
                {checkItems.map((item, i) => (
                  <button
                    key={i}
                    onClick={() => navigate(`/p/${projectSlug}/lifecycle/${item.phase}`)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
                  >
                    {item.done ? <CheckCircle2 className="h-4 w-4 text-success shrink-0" /> : <AlertTriangle className="h-4 w-4 text-warning shrink-0" />}
                    <span className={cn("flex-1", item.done ? "text-foreground" : "text-muted-foreground")}>{item.label}</span>
                    <span className="text-[10px] text-muted-foreground">開く</span>
                  </button>
                ))}
              </div>
              <div className="mt-3 h-2 rounded-full bg-muted overflow-hidden">
                <div className="h-full rounded-full bg-success transition-all" style={{ width: `${checklistProgressPercent}%` }} />
              </div>
              <p className="mt-1 text-[10px] text-muted-foreground text-right">{completedChecklistCount}/{checkItems.length} 完了</p>
            </div>

            {/* Cost estimate */}
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="text-sm font-bold text-foreground mb-2">コスト見積</h3>
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs"><span className="text-muted-foreground">UX分析</span><span className="font-mono text-foreground">~$0.05</span></div>
                <div className="flex justify-between text-xs"><span className="text-muted-foreground">デザイン生成</span><span className="font-mono text-foreground">~${(lc.designVariants.reduce((a, v) => a + v.cost_usd, 0)).toFixed(2)}</span></div>
                <div className="flex justify-between text-xs"><span className="text-muted-foreground">自律開発 (見積)</span><span className="font-mono text-foreground">~$0.50</span></div>
                <div className="border-t border-border pt-1.5 mt-1.5 flex justify-between text-xs font-medium"><span className="text-foreground">合計見積</span><span className="font-mono text-foreground">~$0.60</span></div>
              </div>
            </div>

            {/* Milestones preview */}
            {lc.milestones.length > 0 && (
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-sm font-bold text-foreground mb-2">マイルストーン</h3>
                <div className="space-y-1.5">
                  {lc.milestones.map((ms, i) => (
                    <div key={ms.id} className="flex items-start gap-2 text-xs">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary shrink-0">{i + 1}</span>
                      <span className="text-foreground">{ms.name}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ icon: Icon, title, content }: { icon: React.ElementType; title: string; content: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
        <Icon className="h-3.5 w-3.5" /> {title}
      </div>
      <p className="text-sm text-foreground line-clamp-2">{content}</p>
    </div>
  );
}
