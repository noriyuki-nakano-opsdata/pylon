import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  RefreshCw, Check, ArrowLeft, MessageSquare, TrendingUp,
  Lightbulb, Star, BarChart3, Zap, RotateCcw,
  ThumbsUp, ThumbsDown, GitBranch,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { useLifecycle } from "./LifecycleLayout";

interface FeedbackItem {
  id: string;
  type: "bug" | "feature" | "improvement" | "praise";
  text: string;
  impact: "low" | "medium" | "high";
  votes: number;
}

export function IteratePhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackType, setFeedbackType] = useState<FeedbackItem["type"]>("improvement");
  const [feedbacks, setFeedbacks] = useState<FeedbackItem[]>([
    { id: "1", type: "improvement", text: "ダッシュボードのグラフをインタラクティブにしたい", impact: "medium", votes: 3 },
    { id: "2", type: "feature", text: "ダークモード/ライトモードの切り替え機能", impact: "low", votes: 5 },
    { id: "3", type: "bug", text: "モバイル表示でサイドバーが重なる", impact: "high", votes: 8 },
  ]);
  const [nps, setNps] = useState<number | null>(null);

  const addFeedback = () => {
    if (!feedbackText.trim()) return;
    setFeedbacks([
      { id: `fb-${Date.now()}`, type: feedbackType, text: feedbackText, impact: "medium", votes: 0 },
      ...feedbacks,
    ]);
    setFeedbackText("");
  };

  const vote = (id: string, delta: number) => {
    setFeedbacks(feedbacks.map((f) => f.id === id ? { ...f, votes: f.votes + delta } : f));
  };

  const startNewIteration = () => {
    // Go back to planning with current context preserved
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

  const sorted = [...feedbacks].sort((a, b) => b.votes - a.votes);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-6 py-3">
        <button onClick={goBack} className="text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="flex items-center gap-2 text-sm font-bold text-foreground">
          <RefreshCw className="h-4 w-4 text-primary" /> フィードバック & 改善
        </h1>
        <div className="flex-1" />
        <button onClick={startNewIteration} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
          <RotateCcw className="h-3.5 w-3.5" /> 次のイテレーションを開始
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-5xl grid gap-6 lg:grid-cols-3">
          {/* Left: Feedback collection */}
          <div className="lg:col-span-2 space-y-6">
            {/* NPS */}
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
                  {nps <= 6 ? "Detractor — 改善が必要です" : nps <= 8 ? "Passive — まだ改善の余地があります" : "Promoter — 素晴らしい！"}
                </div>
              )}
            </div>

            {/* Add feedback */}
            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <MessageSquare className="h-4 w-4" /> フィードバックを追加
              </h3>
              <div className="flex gap-1 mb-3">
                {(["bug", "feature", "improvement", "praise"] as const).map((t) => (
                  <button key={t} onClick={() => setFeedbackType(t)} className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium border transition-colors",
                    feedbackType === t ? typeColors[t] : "border-border text-muted-foreground hover:text-foreground",
                  )}>
                    {typeLabels[t]}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                  placeholder="フィードバックを入力..."
                  className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  onKeyDown={(e) => e.key === "Enter" && addFeedback()}
                />
                <button onClick={addFeedback} disabled={!feedbackText.trim()} className="rounded-md bg-primary px-4 py-2 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                  送信
                </button>
              </div>
            </div>

            {/* Feedback list */}
            <div className="space-y-2">
              <h3 className="text-sm font-bold text-foreground">フィードバック一覧（投票順）</h3>
              {sorted.map((fb) => (
                <div key={fb.id} className={cn("flex items-start gap-3 rounded-xl border bg-card p-4", typeColors[fb.type].split(" ").find(c => c.startsWith("border"))!)}>
                  <div className="flex flex-col items-center gap-0.5 shrink-0">
                    <button onClick={() => vote(fb.id, 1)} className="text-muted-foreground hover:text-foreground"><ThumbsUp className="h-3.5 w-3.5" /></button>
                    <span className="text-xs font-bold text-foreground">{fb.votes}</span>
                    <button onClick={() => vote(fb.id, -1)} className="text-muted-foreground hover:text-foreground"><ThumbsDown className="h-3.5 w-3.5" /></button>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant="outline" className={cn("text-[10px]", typeColors[fb.type])}>{typeLabels[fb.type]}</Badge>
                      <Badge variant="outline" className="text-[10px] capitalize">{fb.impact}</Badge>
                    </div>
                    <p className="text-sm text-foreground">{fb.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Summary & AI suggestions */}
          <div className="space-y-4">
            {/* Build stats */}
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <BarChart3 className="h-4 w-4 text-primary" /> ビルド統計
              </h3>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">総コスト</span><span className="font-mono text-foreground">${lc.buildCost.toFixed(4)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">イテレーション</span><span className="font-mono text-foreground">{lc.buildIteration || 1}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">選択機能数</span><span className="font-mono text-foreground">{lc.features.filter((f) => f.selected).length}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">マイルストーン</span><span className="font-mono text-foreground">{lc.milestoneResults.filter((r) => r.status === "satisfied").length}/{lc.milestones.length}</span></div>
              </div>
            </div>

            {/* AI suggestions */}
            <div className="rounded-xl border-2 border-primary/20 bg-primary/5 p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <Lightbulb className="h-4 w-4 text-primary" /> AI改善提案
              </h3>
              <div className="space-y-2">
                {[
                  "バグ「モバイル表示」の修正は最優先 — 投票数最多",
                  "ダークモード切替は低コストで実装可能 — Quick Win",
                  "インタラクティブグラフはrecharts導入で対応可能",
                ].map((s, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-foreground">
                    <Zap className="h-3 w-3 text-primary mt-0.5 shrink-0" />
                    <span>{s}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Version history */}
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
                <GitBranch className="h-4 w-4" /> バージョン履歴
              </h3>
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs">
                  <div className="h-2 w-2 rounded-full bg-success" />
                  <span className="font-mono text-foreground">v1.0</span>
                  <span className="text-muted-foreground">— 初回リリース</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
