import { useState, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  RefreshCw, ArrowLeft, MessageSquare, BarChart3, Lightbulb, Zap, RotateCcw,
  ThumbsUp, ThumbsDown, GitBranch, Loader2,
  Search, ClipboardList, Palette, Code2, Rocket, Users, Target, ChevronDown, ChevronUp,
  CheckCircle2, XCircle, Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { lifecycleApi } from "@/api/lifecycle";
import type { FeedbackItem } from "@/types/lifecycle";
import { useLifecycle } from "./LifecycleContext";

export function IteratePhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackType, setFeedbackType] = useState<FeedbackItem["type"]>("improvement");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [votingId, setVotingId] = useState<string | null>(null);
  const [nps, setNps] = useState<number | null>(null);

  const addFeedback = async () => {
    if (!projectSlug || !feedbackText.trim()) return;
    setIsSubmitting(true);
    try {
      const impact = feedbackType === "bug" ? "high" : feedbackType === "feature" ? "medium" : "low";
      const response = await lifecycleApi.addFeedback(projectSlug, {
        text: feedbackText,
        type: feedbackType,
        impact,
      });
      lc.applyProject(response.project);
      setFeedbackText("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const vote = async (feedbackId: string, delta: number) => {
    if (!projectSlug) return;
    setVotingId(feedbackId);
    try {
      const response = await lifecycleApi.voteFeedback(projectSlug, feedbackId, delta);
      lc.applyProject(response.project);
    } finally {
      setVotingId(null);
    }
  };

  const startNewIteration = () => {
    navigate(`/p/${projectSlug}/lifecycle/planning`);
  };

  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/deploy`);

  const typeColors: Record<FeedbackItem["type"], string> = {
    bug: "bg-destructive/10 text-destructive border-destructive/20",
    feature: "bg-primary/10 text-primary border-primary/20",
    improvement: "bg-warning/10 text-warning border-warning/20",
    praise: "bg-success/10 text-success border-success/20",
  };
  const typeLabels: Record<FeedbackItem["type"], string> = {
    bug: "バグ", feature: "機能要望", improvement: "改善", praise: "良い点",
  };

  const sorted = [...lc.feedbackItems].sort((a, b) => b.votes - a.votes);

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    research: false, planning: false, design: false, development: false, deploy: false,
  });
  const toggleSection = (key: string) => setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));

  const selectedDesign = useMemo(
    () => lc.selectedDesignId ? lc.designVariants.find((v) => v.id === lc.selectedDesignId) : null,
    [lc.selectedDesignId, lc.designVariants],
  );
  const selectedFeatures = useMemo(() => lc.features.filter((f) => f.selected), [lc.features]);
  const completedPhases = useMemo(
    () => lc.phaseStatuses.filter((p) => p.status === "completed").length,
    [lc.phaseStatuses],
  );
  const [showPreview, setShowPreview] = useState(false);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-6 py-3">
        <button onClick={goBack} className="text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="flex items-center gap-2 text-sm font-bold text-foreground">
          <RefreshCw className="h-4 w-4 text-primary" /> フィードバック & 改善
        </h1>
        <div className="flex-1" />
        <button onClick={startNewIteration} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
          <RotateCcw className="h-3.5 w-3.5" /> 次のイテレーションを開始
        </button>
      </div>

      {/* Fullscreen build preview overlay */}
      {showPreview && lc.buildCode && (
        <div className="fixed inset-0 z-50 bg-background flex flex-col">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <span className="text-xs font-medium text-foreground">ビルドプレビュー</span>
            <button onClick={() => setShowPreview(false)} className="rounded-md px-3 py-1 text-xs text-muted-foreground hover:text-foreground border border-border">閉じる</button>
          </div>
          <iframe
            srcDoc={lc.buildCode}
            sandbox="allow-scripts allow-same-origin"
            className="flex-1 w-full bg-white"
            title="ビルドプレビュー"
          />
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-5xl grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-6">

            {/* ── Product Journey Summary ── */}
            <div className="rounded-xl border border-border bg-card p-5 space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
                <Target className="h-4 w-4 text-primary" /> プロダクトジャーニー
                <span className="ml-auto text-xs font-normal text-muted-foreground">{completedPhases}/7 フェーズ完了</span>
              </h3>

              {/* Spec */}
              {lc.spec && (
                <div className="rounded-lg bg-accent/50 px-3 py-2 text-xs text-foreground">
                  <span className="font-medium text-muted-foreground">プロダクト仕様: </span>{lc.spec}
                </div>
              )}

              {/* Research */}
              {lc.research && (
                <div className="rounded-lg border border-border">
                  <button onClick={() => toggleSection("research")} className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-medium text-foreground hover:bg-accent/50 transition-colors rounded-lg">
                    <Search className="h-3.5 w-3.5 text-blue-400" />
                    <span>調査</span>
                    <Badge variant="outline" className="text-[10px] ml-1">完了</Badge>
                    {lc.research.competitors && <span className="ml-auto text-muted-foreground">競合 {lc.research.competitors.length}社</span>}
                    {expandedSections.research ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
                  </button>
                  {expandedSections.research && (
                    <div className="border-t border-border px-3 py-2.5 space-y-2 text-xs">
                      {lc.research.competitors && lc.research.competitors.length > 0 && (
                        <div>
                          <span className="font-medium text-foreground">競合: </span>
                          <span className="text-muted-foreground">{lc.research.competitors.map((c) => c.name).join(", ")}</span>
                        </div>
                      )}
                      {lc.research.trends && lc.research.trends.length > 0 && (
                        <div>
                          <span className="font-medium text-foreground">トレンド: </span>
                          <span className="text-muted-foreground">{lc.research.trends.join(", ")}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Planning / Analysis */}
              {lc.analysis && (
                <div className="rounded-lg border border-border">
                  <button onClick={() => toggleSection("planning")} className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-medium text-foreground hover:bg-accent/50 transition-colors rounded-lg">
                    <ClipboardList className="h-3.5 w-3.5 text-amber-400" />
                    <span>企画</span>
                    <Badge variant="outline" className="text-[10px] ml-1">完了</Badge>
                    <span className="ml-auto text-muted-foreground">
                      ペルソナ {lc.analysis.personas?.length ?? 0} · 機能 {selectedFeatures.length}
                    </span>
                    {expandedSections.planning ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
                  </button>
                  {expandedSections.planning && (
                    <div className="border-t border-border px-3 py-2.5 space-y-2 text-xs">
                      {lc.analysis.personas && lc.analysis.personas.length > 0 && (
                        <div>
                          <span className="font-medium text-foreground">ペルソナ: </span>
                          {lc.analysis.personas.map((p, i) => (
                            <span key={i} className="text-muted-foreground">
                              {i > 0 && " · "}<Users className="inline h-3 w-3 mr-0.5" />{p.name} ({p.role})
                            </span>
                          ))}
                        </div>
                      )}
                      {selectedFeatures.length > 0 && (
                        <div>
                          <span className="font-medium text-foreground">選択機能: </span>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {selectedFeatures.map((f, i) => (
                              <Badge key={i} variant="outline" className={cn("text-[10px]",
                                f.priority === "must" ? "border-red-500/30 text-red-400" :
                                f.priority === "should" ? "border-amber-500/30 text-amber-400" :
                                "border-border text-muted-foreground"
                              )}>
                                {f.feature} ({f.priority})
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                      {lc.analysis.kano_features && lc.analysis.kano_features.length > 0 && (
                        <div>
                          <span className="font-medium text-foreground">KANO分析: </span>
                          <span className="text-muted-foreground">
                            {lc.analysis.kano_features.slice(0, 5).map((k) => `${k.feature}(${k.category})`).join(", ")}
                            {lc.analysis.kano_features.length > 5 && ` 他${lc.analysis.kano_features.length - 5}件`}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Design */}
              {selectedDesign && (
                <div className="rounded-lg border border-border">
                  <button onClick={() => toggleSection("design")} className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-medium text-foreground hover:bg-accent/50 transition-colors rounded-lg">
                    <Palette className="h-3.5 w-3.5 text-purple-400" />
                    <span>デザイン</span>
                    <Badge variant="outline" className="text-[10px] ml-1">選択済</Badge>
                    <span className="ml-auto text-muted-foreground">{selectedDesign.pattern_name || selectedDesign.id}</span>
                    {expandedSections.design ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
                  </button>
                  {expandedSections.design && (
                    <div className="border-t border-border px-3 py-2.5 space-y-2 text-xs">
                      {selectedDesign.description && <p className="text-muted-foreground">{selectedDesign.description}</p>}
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline" className="text-[10px]">パターン: {selectedDesign.pattern_name}</Badge>
                        <Badge variant="outline" className="text-[10px]">モデル: {selectedDesign.model}</Badge>
                        <Badge variant="outline" className="text-[10px]">UX: {selectedDesign.scores.ux_quality}/10</Badge>
                        <Badge variant="outline" className="text-[10px]">コスト: ${selectedDesign.cost_usd.toFixed(4)}</Badge>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Development */}
              {lc.buildCode && (
                <div className="rounded-lg border border-border">
                  <button onClick={() => toggleSection("development")} className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-medium text-foreground hover:bg-accent/50 transition-colors rounded-lg">
                    <Code2 className="h-3.5 w-3.5 text-green-400" />
                    <span>開発</span>
                    <Badge variant="outline" className="text-[10px] ml-1">ビルド完了</Badge>
                    <span className="ml-auto text-muted-foreground">
                      {(lc.buildCode.length / 1024).toFixed(1)} KB
                    </span>
                    {expandedSections.development ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
                  </button>
                  {expandedSections.development && (
                    <div className="border-t border-border px-3 py-2.5 space-y-2 text-xs">
                      <div className="flex gap-2">
                        <span className="text-muted-foreground">マイルストーン:</span>
                        {lc.milestoneResults.length > 0 ? lc.milestoneResults.map((r, i) => (
                          <span key={i} className="flex items-center gap-1">
                            {r.status === "satisfied" ? <CheckCircle2 className="h-3 w-3 text-green-400" /> : <XCircle className="h-3 w-3 text-red-400" />}
                            {r.name || lc.milestones[i]?.name || r.id}
                          </span>
                        )) : <span className="text-muted-foreground">データなし</span>}
                      </div>
                      <button
                        onClick={() => setShowPreview(true)}
                        className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
                      >
                        <Eye className="h-3 w-3" /> ビルドプレビューを開く
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Deploy */}
              {lc.releases.length > 0 && (
                <div className="rounded-lg border border-border">
                  <button onClick={() => toggleSection("deploy")} className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-medium text-foreground hover:bg-accent/50 transition-colors rounded-lg">
                    <Rocket className="h-3.5 w-3.5 text-orange-400" />
                    <span>デプロイ</span>
                    <Badge variant="outline" className="text-[10px] ml-1">{lc.releases.length}回リリース</Badge>
                    <span className="ml-auto text-muted-foreground">{lc.releases[lc.releases.length - 1]?.version}</span>
                    {expandedSections.deploy ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
                  </button>
                  {expandedSections.deploy && (
                    <div className="border-t border-border px-3 py-2.5 space-y-1 text-xs">
                      {lc.deployChecks.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {lc.deployChecks.map((c, i) => (
                            <Badge key={i} variant="outline" className={cn("text-[10px]",
                              c.status === "pass" ? "border-green-500/30 text-green-400" : "border-red-500/30 text-red-400"
                            )}>
                              {c.status === "pass" ? <CheckCircle2 className="inline h-2.5 w-2.5 mr-0.5" /> : <XCircle className="inline h-2.5 w-2.5 mr-0.5" />}
                              {c.label}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* ── NPS ── */}
            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="text-sm font-bold text-foreground mb-3">このプロダクトを推薦する可能性は？</h3>
              <div className="flex gap-1">
                {Array.from({ length: 11 }, (_, i) => (
                  <button
                    key={i}
                    onClick={() => setNps(i)}
                    className={cn(
                      "flex-1 rounded-md py-2 text-xs font-medium transition-colors",
                      nps === i ? (i <= 6 ? "bg-destructive text-white" : i <= 8 ? "bg-warning text-white" : "bg-success text-white") :
                      "bg-accent text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {i}
                  </button>
                ))}
              </div>
              <div className="flex justify-between mt-1.5 text-[10px] text-muted-foreground">
                <span>全く推薦しない</span><span>強く推薦する</span>
              </div>
              {nps !== null && (
                <div className={cn("mt-3 rounded-md px-3 py-2 text-xs",
                  nps <= 6 ? "bg-destructive/10 text-destructive" : nps <= 8 ? "bg-warning/10 text-warning" : "bg-success/10 text-success",
                )}>
                  {nps <= 6 ? "批判者 — 改善が必要です" : nps <= 8 ? "中立者 — まだ改善の余地があります" : "推薦者 — 素晴らしい！"}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <MessageSquare className="h-4 w-4" /> フィードバックを追加
              </h3>
              <div className="flex gap-1 mb-3">
                {(["bug", "feature", "improvement", "praise"] as const).map((type) => (
                  <button key={type} onClick={() => setFeedbackType(type)} className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium border transition-colors",
                    feedbackType === type ? typeColors[type] : "border-border text-muted-foreground hover:text-foreground",
                  )}>
                    {typeLabels[type]}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  value={feedbackText}
                  onChange={(event) => setFeedbackText(event.target.value)}
                  placeholder="フィードバックを入力..."
                  className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  onKeyDown={(event) => event.key === "Enter" && void addFeedback()}
                />
                <button onClick={() => void addFeedback()} disabled={!feedbackText.trim() || isSubmitting} className="rounded-md bg-primary px-4 py-2 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                  {isSubmitting ? <span className="inline-flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" />送信中</span> : "送信"}
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <h3 className="text-sm font-bold text-foreground">フィードバック一覧（投票順）</h3>
              {sorted.length === 0 && (
                <div className="rounded-xl border border-dashed border-border bg-card p-5 text-sm text-muted-foreground">
                  まだフィードバックはありません。デプロイ後のシグナルをここに集約します。
                </div>
              )}
              {sorted.map((feedback) => (
                <div key={feedback.id} className={cn("flex items-start gap-3 rounded-xl border bg-card p-4", typeColors[feedback.type].split(" ").find((token) => token.startsWith("border")) ?? "border-border")}>
                  <div className="flex flex-col items-center gap-0.5 shrink-0">
                    <button onClick={() => void vote(feedback.id, 1)} disabled={votingId === feedback.id} className="text-muted-foreground hover:text-foreground disabled:opacity-50"><ThumbsUp className="h-3.5 w-3.5" /></button>
                    <span className="text-xs font-bold text-foreground">{feedback.votes}</span>
                    <button onClick={() => void vote(feedback.id, -1)} disabled={votingId === feedback.id} className="text-muted-foreground hover:text-foreground disabled:opacity-50"><ThumbsDown className="h-3.5 w-3.5" /></button>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant="outline" className={cn("text-[10px]", typeColors[feedback.type])}>{typeLabels[feedback.type]}</Badge>
                      <Badge variant="outline" className="text-[10px] capitalize">{feedback.impact}</Badge>
                      {feedback.createdAt && <span className="text-[10px] text-muted-foreground ml-auto">{new Date(feedback.createdAt).toLocaleString("ja-JP")}</span>}
                    </div>
                    <p className="text-sm text-foreground">{feedback.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <BarChart3 className="h-4 w-4 text-primary" /> ビルド統計
              </h3>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">総コスト</span><span className="font-mono text-foreground">${lc.buildCost.toFixed(4)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">イテレーション</span><span className="font-mono text-foreground">{lc.buildIteration || 1}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">選択機能数</span><span className="font-mono text-foreground">{lc.features.filter((feature) => feature.selected).length}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">マイルストーン</span><span className="font-mono text-foreground">{lc.milestoneResults.filter((result) => result.status === "satisfied").length}/{lc.milestones.length}</span></div>
              </div>
            </div>

            <div className="rounded-xl border-2 border-primary/20 bg-primary/5 p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <Lightbulb className="h-4 w-4 text-primary" /> AI改善提案
              </h3>
              <div className="space-y-2">
                {lc.recommendations.map((recommendation) => (
                  <div key={recommendation.id} className="flex items-start gap-2 text-xs text-foreground">
                    <Zap className="h-3 w-3 text-primary mt-0.5 shrink-0" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span>{recommendation.title}</span>
                        <Badge variant="outline" className="text-[10px] capitalize">{recommendation.priority}</Badge>
                      </div>
                      <p className="text-muted-foreground mt-0.5">{recommendation.reason}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <GitBranch className="h-4 w-4" /> バージョン履歴
              </h3>
              <div className="space-y-2">
                {lc.releases.length === 0 && (
                  <div className="text-xs text-muted-foreground">まだリリース記録はありません。</div>
                )}
                {lc.releases.map((release) => (
                  <div key={release.id} className="flex items-center gap-2 text-xs">
                    <div className="h-2 w-2 rounded-full bg-success" />
                    <span className="font-mono text-foreground">{release.version}</span>
                    <span className="text-muted-foreground">— {new Date(release.createdAt).toLocaleString("ja-JP")}</span>
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
