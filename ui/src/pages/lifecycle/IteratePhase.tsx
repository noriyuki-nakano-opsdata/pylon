import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Code2,
  Eye,
  GitBranch,
  Lightbulb,
  Loader2,
  MessageSquare,
  Palette,
  RefreshCw,
  Rocket,
  RotateCcw,
  Search,
  Target,
  ThumbsDown,
  ThumbsUp,
  Users,
  XCircle,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { lifecycleApi } from "@/api/lifecycle";
import {
  presentFeedbackImpactLabel,
  presentFeedbackTypeLabel,
  presentFeatureLabel,
  presentNamedItem,
  presentVariantModelLabel,
  presentVariantTitle,
} from "@/lifecycle/designDecisionPresentation";
import { buildFeedbackPayload } from "@/lifecycle/inputs";
import type { FeedbackItem } from "@/types/lifecycle";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import {
  selectIterateViewModel,
  selectSelectedDesign,
  selectSelectedFeatures,
} from "@/lifecycle/selectors";
import {
  downstreamTopbarClassName,
  downstreamWorkspaceClassName,
} from "@/lifecycle/downstreamTheme";

export function IteratePhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackType, setFeedbackType] = useState<FeedbackItem["type"]>("improvement");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [votingId, setVotingId] = useState<string | null>(null);
  const [nps, setNps] = useState<number | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    research: false,
    planning: false,
    design: false,
    development: false,
    deploy: false,
  });

  const selectedDesign = selectSelectedDesign(lc);
  const selectedFeatures = selectSelectedFeatures(lc);
  const {
    byType,
    completedPhaseCount,
    feedbackCount,
    latestRelease,
    sortedFeedback,
    sortedRecommendations,
    topFeedback,
  } = selectIterateViewModel(lc);
  const selectedDesignTitle = selectedDesign ? presentVariantTitle(selectedDesign, -1) : "未選択";
  const selectedDesignModel = selectedDesign ? presentVariantModelLabel(selectedDesign) : "未選択";

  const typeColors: Record<FeedbackItem["type"], string> = {
    bug: "bg-destructive/10 text-destructive border-destructive/20",
    feature: "bg-primary/10 text-primary border-primary/20",
    improvement: "bg-warning/10 text-warning border-warning/20",
    praise: "bg-success/10 text-success border-success/20",
  };
  const iterateGatePending = lc.nextAction?.phase === "iterate" && lc.nextAction?.type === "request_iteration_triage";
  const iterateGateReason = iterateGatePending ? lc.nextAction?.reason ?? "" : "";
  const iterateGateDecisions = iterateGatePending && Array.isArray(lc.nextAction?.payload?.availableDecisions)
    ? (lc.nextAction?.payload?.availableDecisions as string[])
    : [];

  const addFeedback = async () => {
    if (!projectSlug || !feedbackText.trim()) return;
    setIsSubmitting(true);
    try {
      const response = await lifecycleApi.addFeedback(
        projectSlug,
        buildFeedbackPayload(feedbackType, feedbackText),
      );
      actions.applyProject(response.project);
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
      actions.applyProject(response.project);
    } finally {
      setVotingId(null);
    }
  };

  const focusFeedbackForm = () => {
    const element = document.getElementById("iterate-feedback-form");
    if (!element) return;
    element.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const startNewIteration = () => navigate(`/p/${projectSlug}/lifecycle/planning`);
  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/deploy`);
  const toggleSection = (key: string) => setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div className={cn(downstreamWorkspaceClassName, "flex h-full flex-col")}>
      <div className={cn(downstreamTopbarClassName, "flex flex-wrap items-center gap-2 px-6 py-3")}>
        <button onClick={goBack} className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <h1 className="flex items-center gap-2 text-sm font-bold text-foreground">
          <RefreshCw className="h-4 w-4 text-primary" />
          フィードバック & 改善
        </h1>
        <div className="flex-1" />
        <button
          onClick={startNewIteration}
          className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          {iterateGatePending ? "優先順位を確定して planning へ" : "次の改善サイクルを開始"}
        </button>
      </div>

      {showPreview && lc.buildCode && (
        <div className="fixed inset-0 z-50 flex flex-col bg-background">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <span className="text-xs font-medium text-foreground">ビルドプレビュー</span>
            <button
              onClick={() => setShowPreview(false)}
              className="rounded-md border border-border px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
            >
              閉じる
            </button>
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
        <div className="mx-auto max-w-6xl space-y-6">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)_minmax(0,0.9fr)]">
            <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_20px_56px_rgba(15,23,42,0.08)]">
              <div className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">
                <Rocket className="h-3.5 w-3.5 text-primary" />
                LATEST RELEASE
              </div>
              <h2 className="mt-3 text-lg font-semibold text-foreground">
                {latestRelease ? `${latestRelease.version} の結果を次の企画へ戻す` : "改善ループの起点を蓄積する"}
              </h2>
              <p className="mt-2 text-sm leading-7 text-muted-foreground">
                {latestRelease
                  ? `選択案 ${selectedDesignTitle} を基準に出荷した結果を集め、次の planning に返す仮説と課題を整理します。`
                  : "まだ正式リリースはありません。ここでは build / deploy の結果を振り返り、次の改善で扱う論点を蓄積します。"}
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] text-muted-foreground">完了フェーズ</p>
                  <p className="mt-1 text-base font-semibold text-foreground">{completedPhaseCount}/7</p>
                </div>
                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] text-muted-foreground">収集フィードバック</p>
                  <p className="mt-1 text-base font-semibold text-foreground">{feedbackCount} 件</p>
                </div>
                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] text-muted-foreground">改善提案</p>
                  <p className="mt-1 text-base font-semibold text-foreground">{sortedRecommendations.length} 件</p>
                </div>
              </div>
            </div>

            <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_20px_56px_rgba(15,23,42,0.08)]">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">CURRENT BASELINE</p>
              <h3 className="mt-3 text-base font-semibold text-foreground">{selectedDesignTitle}</h3>
              <p className="mt-1 text-xs font-medium text-primary">{selectedDesignModel}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {selectedFeatures.slice(0, 5).map((feature) => (
                  <Badge
                    key={feature.feature}
                    variant="outline"
                    className="rounded-full border-border/70 bg-muted/10 px-3 py-1 text-[11px] font-medium text-foreground"
                  >
                    {presentFeatureLabel(feature.feature)}
                  </Badge>
                ))}
              </div>
              {topFeedback ? (
                <div className="mt-4 rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">最多支持の声</p>
                  <p className="mt-2 text-sm leading-6 text-foreground">{presentNamedItem(topFeedback.text)}</p>
                </div>
              ) : (
                <div className="mt-4 rounded-[1.2rem] border border-dashed border-border/60 p-3 text-sm text-muted-foreground">
                  まだ支持の集まったフィードバックはありません。
                </div>
              )}
            </div>

            <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_20px_56px_rgba(15,23,42,0.08)]">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">FEEDBACK MIX</p>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] text-muted-foreground">不具合</p>
                  <p className="mt-1 font-semibold text-foreground">{byType.bug}</p>
                </div>
                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] text-muted-foreground">機能要望</p>
                  <p className="mt-1 font-semibold text-foreground">{byType.feature}</p>
                </div>
                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] text-muted-foreground">改善案</p>
                  <p className="mt-1 font-semibold text-foreground">{byType.improvement}</p>
                </div>
                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                  <p className="text-[11px] text-muted-foreground">好意的な声</p>
                  <p className="mt-1 font-semibold text-foreground">{byType.praise}</p>
                </div>
              </div>
              {sortedRecommendations[0] ? (
                <div className="mt-4 rounded-[1.2rem] border border-primary/20 bg-primary/5 p-3">
                  <p className="text-[11px] font-semibold tracking-[0.14em] text-primary">次に着手する提案</p>
                  <p className="mt-2 text-sm font-medium text-foreground">{presentNamedItem(sortedRecommendations[0].title)}</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">{presentNamedItem(sortedRecommendations[0].reason)}</p>
                </div>
              ) : null}
            </div>
          </div>

          {iterateGatePending ? (
            <div className="rounded-[1.8rem] border border-primary/20 bg-primary/5 p-5 shadow-[0_20px_56px_rgba(37,99,235,0.10)]">
              <div className="flex flex-wrap items-start gap-3">
                <div className="rounded-full border border-primary/20 bg-background/90 px-3 py-1 text-[11px] font-semibold tracking-[0.18em] text-primary">
                  HUMAN ITERATION GATE
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-foreground">次の改善 wave に入る前に、人が優先順位を確定します</h3>
                  <p className="mt-2 text-sm leading-7 text-muted-foreground">{presentNamedItem(iterateGateReason)}</p>
                  {iterateGateDecisions.length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {iterateGateDecisions.map((decision) => (
                        <Badge
                          key={decision}
                          variant="outline"
                          className="rounded-full border-primary/20 bg-background/80 px-3 py-1 text-[11px] font-medium text-foreground"
                        >
                          {decision}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={startNewIteration}
                    className="inline-flex items-center gap-2 rounded-2xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    planning に戻って scope を決める
                  </button>
                  <button
                    onClick={focusFeedbackForm}
                    className="inline-flex items-center gap-2 rounded-2xl border border-border bg-background/90 px-4 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent"
                  >
                    <MessageSquare className="h-3.5 w-3.5" />
                    追加フィードバックを集める
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2 space-y-6">
              <div className="rounded-xl border border-border bg-card p-5 space-y-3">
                <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
                  <Target className="h-4 w-4 text-primary" />
                  プロダクトジャーニー
                  <span className="ml-auto text-xs font-normal text-muted-foreground">{completedPhaseCount}/7 フェーズ完了</span>
                </h3>

                {lc.spec && (
                  <div className="rounded-lg bg-accent/50 px-3 py-2 text-xs text-foreground">
                    <span className="font-medium text-muted-foreground">プロダクト仕様: </span>
                    {presentNamedItem(lc.spec)}
                  </div>
                )}

                {lc.research && (
                  <div className="rounded-lg border border-border">
                    <button
                      onClick={() => toggleSection("research")}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent/50"
                    >
                      <Search className="h-3.5 w-3.5 text-blue-400" />
                      <span>調査</span>
                      <Badge variant="outline" className="ml-1 text-[10px]">完了</Badge>
                      {lc.research.competitors && <span className="ml-auto text-muted-foreground">競合 {lc.research.competitors.length} 社</span>}
                      {expandedSections.research ? <ChevronUp className="ml-1 h-3 w-3" /> : <ChevronDown className="ml-1 h-3 w-3" />}
                    </button>
                    {expandedSections.research && (
                      <div className="space-y-2 border-t border-border px-3 py-2.5 text-xs">
                        {lc.research.competitors && lc.research.competitors.length > 0 && (
                          <div>
                            <span className="font-medium text-foreground">競合: </span>
                            <span className="text-muted-foreground">{lc.research.competitors.map((competitor) => presentNamedItem(competitor.name)).join(", ")}</span>
                          </div>
                        )}
                        {lc.research.trends && lc.research.trends.length > 0 && (
                          <div>
                            <span className="font-medium text-foreground">トレンド: </span>
                            <span className="text-muted-foreground">{lc.research.trends.map((trend) => presentNamedItem(trend)).join(", ")}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {lc.analysis && (
                  <div className="rounded-lg border border-border">
                    <button
                      onClick={() => toggleSection("planning")}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent/50"
                    >
                      <ClipboardList className="h-3.5 w-3.5 text-amber-400" />
                      <span>企画</span>
                      <Badge variant="outline" className="ml-1 text-[10px]">完了</Badge>
                      <span className="ml-auto text-muted-foreground">
                        ペルソナ {lc.analysis.personas?.length ?? 0} · 機能 {selectedFeatures.length}
                      </span>
                      {expandedSections.planning ? <ChevronUp className="ml-1 h-3 w-3" /> : <ChevronDown className="ml-1 h-3 w-3" />}
                    </button>
                    {expandedSections.planning && (
                      <div className="space-y-2 border-t border-border px-3 py-2.5 text-xs">
                        {lc.analysis.personas && lc.analysis.personas.length > 0 && (
                          <div>
                            <span className="font-medium text-foreground">ペルソナ: </span>
                            {lc.analysis.personas.map((persona, index) => (
                              <span key={persona.name} className="text-muted-foreground">
                                {index > 0 && " · "}
                                <Users className="mr-0.5 inline h-3 w-3" />
                                {presentNamedItem(persona.name)} ({presentNamedItem(persona.role)})
                              </span>
                            ))}
                          </div>
                        )}
                        {selectedFeatures.length > 0 && (
                          <div>
                            <span className="font-medium text-foreground">選択機能: </span>
                            <div className="mt-1 flex flex-wrap gap-1">
                              {selectedFeatures.map((feature) => (
                                <Badge
                                  key={feature.feature}
                                  variant="outline"
                                  className={cn(
                                    "text-[10px]",
                                    feature.priority === "must"
                                      ? "border-red-500/30 text-red-400"
                                      : feature.priority === "should"
                                        ? "border-amber-500/30 text-amber-400"
                                        : "border-border text-muted-foreground",
                                  )}
                                >
                                  {presentFeatureLabel(feature.feature)} ({feature.priority})
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {selectedDesign && (
                  <div className="rounded-lg border border-border">
                    <button
                      onClick={() => toggleSection("design")}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent/50"
                    >
                      <Palette className="h-3.5 w-3.5 text-purple-400" />
                      <span>デザイン</span>
                      <Badge variant="outline" className="ml-1 text-[10px]">選択済</Badge>
                      <span className="ml-auto text-muted-foreground">{selectedDesignTitle}</span>
                      {expandedSections.design ? <ChevronUp className="ml-1 h-3 w-3" /> : <ChevronDown className="ml-1 h-3 w-3" />}
                    </button>
                    {expandedSections.design && (
                      <div className="space-y-2 border-t border-border px-3 py-2.5 text-xs">
                        {selectedDesign.description ? <p className="text-muted-foreground">{presentNamedItem(selectedDesign.description)}</p> : null}
                        <div className="flex flex-wrap gap-2">
                          <Badge variant="outline" className="text-[10px]">パターン: {selectedDesignTitle}</Badge>
                          <Badge variant="outline" className="text-[10px]">モデル: {selectedDesignModel}</Badge>
                          <Badge variant="outline" className="text-[10px]">UX: {selectedDesign.scores.ux_quality}/10</Badge>
                          <Badge variant="outline" className="text-[10px]">コスト: ${selectedDesign.cost_usd.toFixed(4)}</Badge>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {lc.buildCode && (
                  <div className="rounded-lg border border-border">
                    <button
                      onClick={() => toggleSection("development")}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent/50"
                    >
                      <Code2 className="h-3.5 w-3.5 text-green-400" />
                      <span>開発</span>
                      <Badge variant="outline" className="ml-1 text-[10px]">ビルド完了</Badge>
                      <span className="ml-auto text-muted-foreground">{(lc.buildCode.length / 1024).toFixed(1)} KB</span>
                      {expandedSections.development ? <ChevronUp className="ml-1 h-3 w-3" /> : <ChevronDown className="ml-1 h-3 w-3" />}
                    </button>
                    {expandedSections.development && (
                      <div className="space-y-2 border-t border-border px-3 py-2.5 text-xs">
                        <div className="flex gap-2">
                          <span className="text-muted-foreground">マイルストーン:</span>
                          {lc.milestoneResults.length > 0 ? lc.milestoneResults.map((result, index) => (
                            <span key={`${result.id}-${index}`} className="flex items-center gap-1">
                              {result.status === "satisfied"
                                ? <CheckCircle2 className="h-3 w-3 text-green-400" />
                                : <XCircle className="h-3 w-3 text-red-400" />}
                              {presentNamedItem(result.name || lc.milestones[index]?.name || result.id)}
                            </span>
                          )) : <span className="text-muted-foreground">データなし</span>}
                        </div>
                        <button
                          onClick={() => setShowPreview(true)}
                          className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
                        >
                          <Eye className="h-3 w-3" />
                          ビルドプレビューを開く
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {lc.releases.length > 0 && (
                  <div className="rounded-lg border border-border">
                    <button
                      onClick={() => toggleSection("deploy")}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent/50"
                    >
                      <Rocket className="h-3.5 w-3.5 text-orange-400" />
                      <span>デプロイ</span>
                      <Badge variant="outline" className="ml-1 text-[10px]">{lc.releases.length} 回リリース</Badge>
                      <span className="ml-auto text-muted-foreground">{lc.releases[lc.releases.length - 1]?.version}</span>
                      {expandedSections.deploy ? <ChevronUp className="ml-1 h-3 w-3" /> : <ChevronDown className="ml-1 h-3 w-3" />}
                    </button>
                    {expandedSections.deploy && (
                      <div className="space-y-1 border-t border-border px-3 py-2.5 text-xs">
                        {lc.deployChecks.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {lc.deployChecks.map((check) => (
                              <Badge
                                key={check.id}
                                variant="outline"
                                className={cn(
                                  "text-[10px]",
                                  check.status === "pass" ? "border-green-500/30 text-green-400" : "border-red-500/30 text-red-400",
                                )}
                              >
                                {check.status === "pass"
                                  ? <CheckCircle2 className="mr-0.5 inline h-2.5 w-2.5" />
                                  : <XCircle className="mr-0.5 inline h-2.5 w-2.5" />}
                                {presentNamedItem(check.label)}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-border bg-card p-5">
                <h3 className="mb-3 text-sm font-bold text-foreground">このプロダクトを推薦する可能性は？</h3>
                <div className="flex gap-1">
                  {Array.from({ length: 11 }, (_, index) => (
                    <button
                      key={index}
                      onClick={() => setNps(index)}
                      className={cn(
                        "flex-1 rounded-md py-2 text-xs font-medium transition-colors",
                        nps === index
                          ? index <= 6
                            ? "bg-destructive text-white"
                            : index <= 8
                              ? "bg-warning text-white"
                              : "bg-success text-white"
                          : "bg-accent text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {index}
                    </button>
                  ))}
                </div>
                <div className="mt-1.5 flex justify-between text-[10px] text-muted-foreground">
                  <span>全く推薦しない</span>
                  <span>強く推薦する</span>
                </div>
                {nps !== null ? (
                  <div className={cn(
                    "mt-3 rounded-md px-3 py-2 text-xs",
                    nps <= 6 ? "bg-destructive/10 text-destructive" : nps <= 8 ? "bg-warning/10 text-warning" : "bg-success/10 text-success",
                  )}>
                    {nps <= 6 ? "批判者 — 改善が必要です" : nps <= 8 ? "中立者 — まだ改善の余地があります" : "推薦者 — 次の展開に進めます"}
                  </div>
                ) : null}
              </div>

              <div id="iterate-feedback-form" className="rounded-xl border border-border bg-card p-5">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-foreground">
                  <MessageSquare className="h-4 w-4" />
                  フィードバックを追加
                </h3>
                <div className="mb-3 flex gap-1">
                  {(["bug", "feature", "improvement", "praise"] as const).map((type) => (
                    <button
                      key={type}
                      onClick={() => setFeedbackType(type)}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                        feedbackType === type ? typeColors[type] : "border-border text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {presentFeedbackTypeLabel(type)}
                    </button>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    value={feedbackText}
                    onChange={(event) => setFeedbackText(event.target.value)}
                    placeholder="改善したい点や反応を入力..."
                    className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    onKeyDown={(event) => event.key === "Enter" && void addFeedback()}
                  />
                  <button
                    onClick={() => void addFeedback()}
                    disabled={!feedbackText.trim() || isSubmitting}
                    className="rounded-md bg-primary px-4 py-2 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {isSubmitting ? (
                      <span className="inline-flex items-center gap-1">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        送信中
                      </span>
                    ) : "送信"}
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <h3 className="text-sm font-bold text-foreground">フィードバック一覧（投票順）</h3>
                {sortedFeedback.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border bg-card p-5 text-sm text-muted-foreground">
                    まだフィードバックはありません。デプロイ後のシグナルをここに集約します。
                  </div>
                ) : null}
                {sortedFeedback.map((feedback) => (
                  <div
                    key={feedback.id}
                    className={cn(
                      "flex items-start gap-3 rounded-xl border bg-card p-4",
                      typeColors[feedback.type].split(" ").find((token) => token.startsWith("border")) ?? "border-border",
                    )}
                  >
                    <div className="flex shrink-0 flex-col items-center gap-0.5">
                      <button onClick={() => void vote(feedback.id, 1)} disabled={votingId === feedback.id} className="text-muted-foreground hover:text-foreground disabled:opacity-50">
                        <ThumbsUp className="h-3.5 w-3.5" />
                      </button>
                      <span className="text-xs font-bold text-foreground">{feedback.votes}</span>
                      <button onClick={() => void vote(feedback.id, -1)} disabled={votingId === feedback.id} className="text-muted-foreground hover:text-foreground disabled:opacity-50">
                        <ThumbsDown className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <div className="flex-1">
                      <div className="mb-1 flex items-center gap-2">
                        <Badge variant="outline" className={cn("text-[10px]", typeColors[feedback.type])}>
                          {presentFeedbackTypeLabel(feedback.type)}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] capitalize">
                          {presentFeedbackImpactLabel(feedback.impact)}
                        </Badge>
                        {feedback.createdAt ? (
                          <span className="ml-auto text-[10px] text-muted-foreground">
                            {new Date(feedback.createdAt).toLocaleString("ja-JP")}
                          </span>
                        ) : null}
                      </div>
                      <p className="text-sm text-foreground">{presentNamedItem(feedback.text)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-foreground">
                  <BarChart3 className="h-4 w-4 text-primary" />
                  ビルド統計
                </h3>
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between"><span className="text-muted-foreground">総コスト</span><span className="font-mono text-foreground">${lc.buildCost.toFixed(4)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">イテレーション</span><span className="font-mono text-foreground">{lc.buildIteration || 1}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">選択機能数</span><span className="font-mono text-foreground">{selectedFeatures.length}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">マイルストーン</span><span className="font-mono text-foreground">{lc.milestoneResults.filter((result) => result.status === "satisfied").length}/{lc.milestones.length}</span></div>
                </div>
              </div>

              <div className="rounded-xl border-2 border-primary/20 bg-primary/5 p-4">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-foreground">
                  <Lightbulb className="h-4 w-4 text-primary" />
                  AI改善提案
                </h3>
                <div className="space-y-2">
                  {sortedRecommendations.length > 0 ? sortedRecommendations.map((recommendation) => (
                    <div key={recommendation.id} className="flex items-start gap-2 text-xs text-foreground">
                      <Zap className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                      <div>
                        <div className="flex items-center gap-2">
                          <span>{presentNamedItem(recommendation.title)}</span>
                          <Badge variant="outline" className="text-[10px] capitalize">{recommendation.priority}</Badge>
                        </div>
                        <p className="mt-0.5 text-muted-foreground">{presentNamedItem(recommendation.reason)}</p>
                      </div>
                    </div>
                  )) : (
                    <div className="rounded-lg border border-dashed border-border px-3 py-4 text-xs text-muted-foreground">
                      まだ次の改善提案はありません。
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-foreground">
                  <GitBranch className="h-4 w-4" />
                  バージョン履歴
                </h3>
                <div className="space-y-2">
                  {lc.releases.length === 0 ? (
                    <div className="text-xs text-muted-foreground">まだリリース記録はありません。</div>
                  ) : null}
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
    </div>
  );
}
