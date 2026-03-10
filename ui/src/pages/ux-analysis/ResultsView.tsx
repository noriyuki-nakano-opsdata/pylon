import {
  Users, BookOpen, BarChart3,
  Lightbulb, Eye, ChevronDown,
  ArrowRight, ArrowLeft, Smile, Meh, Frown,
  Check, AlertTriangle, Rocket,
  Square, CheckSquare, Plus, Trash2,
  Flag,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { AnalysisResult, Persona, KanoFeature, UserStory, FeatureSelection, Milestone } from "@/types/ux-analysis";

/* ── Step 3: Review ── */
type ReviewTab = "overview" | "persona" | "kano" | "user_story" | "recommendations";

export function ReviewStep({ result, reviewTab, setReviewTab, onNext }: { result: AnalysisResult; reviewTab: string; setReviewTab: (t: string) => void; onNext: () => void }) {
  const tabs: { key: ReviewTab; label: string; icon: React.ElementType }[] = [
    { key: "overview", label: "概要", icon: BarChart3 },
    { key: "persona", label: "ペルソナ", icon: Users },
    { key: "kano", label: "KANO", icon: BarChart3 },
    { key: "user_story", label: "ストーリー", icon: BookOpen },
    { key: "recommendations", label: "提言", icon: Lightbulb },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-border px-6 py-2">
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setReviewTab(t.key)} className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            reviewTab === t.key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
          )}>
            <t.icon className="h-3.5 w-3.5" />
            {t.label}
          </button>
        ))}
        <div className="flex-1" />
        <button onClick={onNext} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
          機能を選択 <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {reviewTab === "overview" && <ReviewOverview result={result} />}
        {reviewTab === "persona" && <ReviewPersonas personas={result.personas} />}
        {reviewTab === "kano" && <ReviewKano features={result.kano_features} />}
        {reviewTab === "user_story" && <ReviewStories stories={result.user_stories} />}
        {reviewTab === "recommendations" && <ReviewRecommendations recommendations={result.recommendations} />}
      </div>
    </div>
  );
}

function ReviewOverview({ result }: { result: AnalysisResult }) {
  const stats = [
    { label: "Personas", value: result.personas.length },
    { label: "User Stories", value: result.user_stories.length },
    { label: "KANO Features", value: result.kano_features.length },
    { label: "Recommendations", value: result.recommendations.length },
  ];
  const kanoCounts = {
    "Must-Be": result.kano_features.filter((f) => f.category === "must-be").length,
    "One-Dim": result.kano_features.filter((f) => f.category === "one-dimensional").length,
    "Attractive": result.kano_features.filter((f) => f.category === "attractive").length,
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <h2 className="text-lg font-bold text-foreground">分析結果サマリー</h2>
      <div className="grid grid-cols-4 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg border border-border bg-card p-4 text-center">
            <p className="text-2xl font-bold text-foreground">{s.value}</p>
            <p className="text-xs text-muted-foreground">{s.label}</p>
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">KANO分布</h3>
        <div className="flex gap-3">
          {Object.entries(kanoCounts).map(([k, v]) => (
            <div key={k} className="flex-1 rounded-md bg-accent/50 p-3 text-center">
              <p className="text-lg font-bold text-foreground">{v}</p>
              <p className="text-xs text-muted-foreground">{k}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-2">Must-Have ストーリー</h3>
        {result.user_stories.filter((s) => s.priority === "must").map((s, i) => (
          <div key={i} className="flex items-start gap-2 py-1 text-sm">
            <Badge variant="destructive" className="shrink-0 text-[10px]">MUST</Badge>
            <span className="text-foreground">{s.action}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewPersonas({ personas }: { personas: Persona[] }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3 max-w-5xl">
      {personas.map((p, i) => (
        <div key={i} className="rounded-lg border border-border bg-card p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/20 text-primary font-bold">{p.name.charAt(0)}</div>
            <div>
              <p className="font-medium text-foreground">{p.name}</p>
              <p className="text-xs text-muted-foreground">{p.role} · {p.age_range}</p>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mb-3">{p.context}</p>
          <div className="space-y-2">
            {p.goals.map((g, j) => <p key={j} className="flex items-start gap-1.5 text-xs text-foreground"><Check className="h-3 w-3 mt-0.5 text-success shrink-0" />{g}</p>)}
            {p.frustrations.map((f, j) => <p key={j} className="flex items-start gap-1.5 text-xs text-foreground"><AlertTriangle className="h-3 w-3 mt-0.5 text-destructive shrink-0" />{f}</p>)}
          </div>
        </div>
      ))}
    </div>
  );
}

function ReviewKano({ features }: { features: KanoFeature[] }) {
  const catColor: Record<string, string> = { "must-be": "text-destructive", "one-dimensional": "text-primary", attractive: "text-success", indifferent: "text-muted-foreground" };
  return (
    <div className="max-w-4xl">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <th className="pb-2 text-xs font-medium text-muted-foreground">Feature</th>
            <th className="pb-2 text-xs font-medium text-muted-foreground">Category</th>
            <th className="pb-2 text-xs font-medium text-muted-foreground">Delight</th>
            <th className="pb-2 text-xs font-medium text-muted-foreground">Cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {features.map((f, i) => (
            <tr key={i}>
              <td className="py-2 font-medium text-foreground">{f.feature}</td>
              <td className={cn("py-2 capitalize text-xs font-medium", catColor[f.category])}>{f.category.replace("-", " ")}</td>
              <td className="py-2"><div className="flex items-center gap-1"><div className="h-1.5 w-12 rounded-full bg-muted overflow-hidden"><div className={cn("h-full rounded-full", f.user_delight > 0.5 ? "bg-success" : "bg-primary")} style={{ width: `${Math.max(f.user_delight * 100, 5)}%` }} /></div><span className="text-xs text-muted-foreground">{f.user_delight.toFixed(1)}</span></div></td>
              <td className="py-2"><Badge variant="outline" className="text-[10px] capitalize">{f.implementation_cost}</Badge></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReviewStories({ stories }: { stories: UserStory[] }) {
  const color: Record<string, string> = { must: "bg-destructive/20 text-destructive", should: "bg-warning/20 text-warning", could: "bg-primary/20 text-primary", wont: "bg-muted text-muted-foreground" };
  return (
    <div className="space-y-2 max-w-3xl">
      {stories.map((s, i) => (
        <div key={i} className="flex items-start gap-2 rounded-lg border border-border bg-card p-3">
          <Badge className={cn("text-[10px] border-0 uppercase shrink-0 mt-0.5", color[s.priority])}>{s.priority}</Badge>
          <div>
            <p className="text-sm text-foreground">As a {s.role}, I want to {s.action}</p>
            <p className="text-xs text-muted-foreground mt-0.5">So that {s.benefit}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReviewRecommendations({ recommendations }: { recommendations: string[] }) {
  return (
    <div className="space-y-2 max-w-3xl">
      {recommendations.map((r, i) => {
        const isQuick = r.includes("Quick Win");
        const isStrategic = r.includes("Strategic");
        const isRisk = r.includes("Risk");
        return (
          <div key={i} className={cn("rounded-lg border-2 p-3", isQuick ? "border-success/50 bg-success/5" : isStrategic ? "border-primary/50 bg-primary/5" : isRisk ? "border-destructive/50 bg-destructive/5" : "border-border")}>
            <p className="text-sm text-foreground">{r}</p>
          </div>
        );
      })}
    </div>
  );
}

/* ── Step 4: Feature Selection Wizard ── */
export function SelectStep({ features, setFeatures, milestones, setMilestones, onBack, onBuild }: {
  features: FeatureSelection[];
  setFeatures: (f: FeatureSelection[]) => void;
  milestones: Milestone[];
  setMilestones: (m: Milestone[]) => void;
  onBack: () => void;
  onBuild: () => void;
}) {
  const toggle = (idx: number) => {
    const next = [...features];
    // must-be cannot be deselected
    if (next[idx].category === "must-be") return;
    next[idx] = { ...next[idx], selected: !next[idx].selected };
    setFeatures(next);
  };

  const setPriority = (idx: number, priority: FeatureSelection["priority"]) => {
    const next = [...features];
    next[idx] = { ...next[idx], priority };
    setFeatures(next);
  };

  const selectPreset = (preset: "minimal" | "recommended" | "full") => {
    const next = features.map((f) => {
      if (f.category === "must-be") return { ...f, selected: true };
      if (preset === "minimal") return { ...f, selected: false };
      if (preset === "full") return { ...f, selected: true };
      // recommended: must-be + one-dimensional + attractive with delight > 0.7
      return { ...f, selected: f.category === "one-dimensional" || (f.category === "attractive" && f.user_delight >= 0.7) };
    });
    setFeatures(next);
  };

  const selectedCount = features.filter((f) => f.selected).length;
  const catColor: Record<string, string> = { "must-be": "border-destructive/30 bg-destructive/5", "one-dimensional": "border-primary/30 bg-primary/5", attractive: "border-success/30 bg-success/5", indifferent: "border-border bg-card" };

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <button onClick={onBack} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" /> 分析に戻る</button>
        <div className="flex-1" />
        <span className="text-xs text-muted-foreground">{selectedCount}/{features.length} 選択中</span>
        <div className="flex gap-1">
          {(["minimal", "recommended", "full"] as const).map((p) => (
            <button key={p} onClick={() => selectPreset(p)} className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors capitalize">
              {p === "minimal" ? "最小" : p === "recommended" ? "推奨" : "全機能"}
            </button>
          ))}
        </div>
        <button onClick={onBuild} disabled={selectedCount === 0} className={cn(
          "flex items-center gap-1.5 rounded-md px-5 py-2 text-sm font-medium transition-colors",
          selectedCount > 0 ? "bg-primary text-primary-foreground hover:bg-primary/90" : "bg-muted text-muted-foreground cursor-not-allowed",
        )}>
          <Rocket className="h-4 w-4" /> 開発開始
        </button>
      </div>

      {/* Feature list */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* Must-be (locked) */}
          <FeatureGroup
            title="Must-Be（必須機能）"
            description="これらは製品として必須の機能です。除外できません。"
            features={features.filter((f) => f.category === "must-be")}
            allFeatures={features}
            toggle={toggle}
            setPriority={setPriority}
            catColor={catColor}
            locked
          />
          {/* One-dimensional */}
          <FeatureGroup
            title="One-Dimensional（性能機能）"
            description="実装の質に比例してユーザー満足度が上がる機能です。"
            features={features.filter((f) => f.category === "one-dimensional")}
            allFeatures={features}
            toggle={toggle}
            setPriority={setPriority}
            catColor={catColor}
          />
          {/* Attractive */}
          <FeatureGroup
            title="Attractive（魅力機能）"
            description="なくても不満にならないが、あると感動する差別化機能です。"
            features={features.filter((f) => f.category === "attractive")}
            allFeatures={features}
            toggle={toggle}
            setPriority={setPriority}
            catColor={catColor}
          />
          {/* Indifferent */}
          {features.some((f) => f.category === "indifferent") && (
            <FeatureGroup
              title="Indifferent（無関心機能）"
              description="ほとんどのユーザーが気にしない機能です。"
              features={features.filter((f) => f.category === "indifferent")}
              allFeatures={features}
              toggle={toggle}
              setPriority={setPriority}
              catColor={catColor}
            />
          )}

          {/* Milestones */}
          <MilestoneEditor milestones={milestones} setMilestones={setMilestones} />
        </div>
      </div>
    </div>
  );
}

function FeatureGroup({ title, description, features: groupFeatures, allFeatures, toggle, setPriority, catColor, locked }: {
  title: string;
  description: string;
  features: FeatureSelection[];
  allFeatures: FeatureSelection[];
  toggle: (idx: number) => void;
  setPriority: (idx: number, p: FeatureSelection["priority"]) => void;
  catColor: Record<string, string>;
  locked?: boolean;
}) {
  return (
    <div>
      <h3 className="text-sm font-bold text-foreground">{title}</h3>
      <p className="text-xs text-muted-foreground mb-3">{description}</p>
      <div className="space-y-2">
        {groupFeatures.map((f) => {
          const globalIdx = allFeatures.indexOf(f);
          return (
            <div key={f.feature} className={cn("flex items-center gap-3 rounded-lg border p-3 transition-colors", f.selected ? catColor[f.category] : "border-border bg-card opacity-60")}>
              <button onClick={() => toggle(globalIdx)} disabled={locked} className={cn(locked && "cursor-not-allowed")}>
                {f.selected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted-foreground" />}
              </button>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground">{f.feature}</p>
                <p className="text-xs text-muted-foreground truncate">{f.rationale}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant="outline" className="text-[10px] capitalize">{f.implementation_cost}</Badge>
                {f.selected && !locked && (
                  <div className="flex gap-0.5">
                    {(["must", "should", "could"] as const).map((p) => (
                      <button key={p} onClick={() => setPriority(globalIdx, p)} className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase transition-colors",
                        f.priority === p ? (p === "must" ? "bg-destructive/20 text-destructive" : p === "should" ? "bg-warning/20 text-warning" : "bg-primary/20 text-primary") : "text-muted-foreground hover:text-foreground",
                      )}>
                        {p}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Milestone Editor ── */
function MilestoneEditor({ milestones, setMilestones }: { milestones: Milestone[]; setMilestones: (m: Milestone[]) => void }) {
  const addMilestone = () => {
    setMilestones([...milestones, { id: `ms-${Date.now()}`, name: "", criteria: "", status: "pending" }]);
  };
  const updateMilestone = (idx: number, field: "name" | "criteria", value: string) => {
    const next = [...milestones];
    next[idx] = { ...next[idx], [field]: value };
    setMilestones(next);
  };
  const removeMilestone = (idx: number) => {
    setMilestones(milestones.filter((_, i) => i !== idx));
  };
  const addPreset = (preset: "quality" | "feature" | "responsive") => {
    const presets: Record<string, Milestone> = {
      quality: { id: `ms-${Date.now()}`, name: "コード品質", criteria: "エラーハンドリング、ローディング状態、バリデーションが適切に実装されている", status: "pending" },
      feature: { id: `ms-${Date.now() + 1}`, name: "全機能実装", criteria: "選択されたすべての機能が動作可能な状態で実装されている", status: "pending" },
      responsive: { id: `ms-${Date.now() + 2}`, name: "レスポンシブ対応", criteria: "モバイル・タブレット・デスクトップで正しくレイアウトされる", status: "pending" },
    };
    setMilestones([...milestones, presets[preset]]);
  };

  return (
    <div className="mt-6 border-t border-border pt-6">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
            <Flag className="h-4 w-4 text-primary" />
            マイルストーン（完成条件）
          </h3>
          <p className="text-xs text-muted-foreground">
            条件をクリアするまでAIが自律的に改善を繰り返します（最大5回）
          </p>
        </div>
        <button onClick={addMilestone} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
          <Plus className="h-3.5 w-3.5" /> 追加
        </button>
      </div>

      {milestones.length === 0 && (
        <div className="rounded-lg border-2 border-dashed border-border p-6 text-center">
          <Flag className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
          <p className="text-sm text-muted-foreground mb-3">
            マイルストーンを定義すると、AIが条件を満たすまで自律的に改善サイクルを回します
          </p>
          <div className="flex items-center justify-center gap-2">
            <button onClick={() => addPreset("feature")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 transition-colors">全機能実装</button>
            <button onClick={() => addPreset("quality")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 transition-colors">コード品質</button>
            <button onClick={() => addPreset("responsive")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 transition-colors">レスポンシブ</button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {milestones.map((ms, i) => (
          <div key={ms.id} className="flex gap-3 rounded-lg border border-border bg-card p-3">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary mt-0.5">
              {i + 1}
            </div>
            <div className="flex-1 space-y-2">
              <input
                value={ms.name}
                onChange={(e) => updateMilestone(i, "name", e.target.value)}
                placeholder="マイルストーン名（例: 全機能実装）"
                className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <textarea
                value={ms.criteria}
                onChange={(e) => updateMilestone(i, "criteria", e.target.value)}
                placeholder="完成条件の詳細（例: 選択されたすべての機能が動作可能な状態で実装されている）"
                rows={2}
                className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
              />
            </div>
            <button onClick={() => removeMilestone(i)} className="shrink-0 text-muted-foreground hover:text-destructive transition-colors mt-0.5">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>

      {milestones.length > 0 && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-muted-foreground">プリセット:</span>
          <button onClick={() => addPreset("feature")} className="text-xs text-primary hover:underline">全機能実装</button>
          <button onClick={() => addPreset("quality")} className="text-xs text-primary hover:underline">コード品質</button>
          <button onClick={() => addPreset("responsive")} className="text-xs text-primary hover:underline">レスポンシブ</button>
        </div>
      )}
    </div>
  );
}
