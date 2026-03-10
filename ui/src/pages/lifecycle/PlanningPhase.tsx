import { useState, useEffect, useMemo, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Lightbulb, Loader2, Check, ArrowRight, ArrowLeft, Users,
  BarChart3, BookOpen, Target, AlertTriangle, Eye,
  CheckSquare, Square, Zap, Flag, Plus, Trash2, AlertCircle,
  Layers, GanttChart, DollarSign, Clock, Bot, Wrench,
  ArrowDown, ChevronRight, Route, Briefcase, Network,
  Smile, Meh, Frown, MapPin, ChevronsUpDown,
  UserCheck, Shield, FileText, CircleDot, ArrowRightCircle,
  FolderOpen, Sparkles, Palette,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLifecycle } from "./LifecycleLayout";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { parsePlanningOutput } from "@/api/lifecycle";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";
import type { AnalysisResult, KanoFeature, FeatureSelection, Milestone, UserStory, PlanEstimate, PlanPreset, WbsItem, Epic, UserJourneyMap, JourneyTouchpoint, JourneyPhase, JobStory, IAAnalysis, IANode, Actor, Role, UseCase, RecommendedMilestone, DesignTokenAnalysis } from "@/types/lifecycle";

/* ── Sub-step within planning ── */
type PlanningStep = "analyze" | "analyzing" | "review" | "features" | "milestones" | "epics" | "gantt";

const PLANNING_AGENTS = [
  { id: "persona-builder", label: "ペルソナ分析" },
  { id: "feature-analyst", label: "KANO分析" },
  { id: "planning-synthesizer", label: "企画統合" },
];

export function PlanningPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const workflow = useWorkflowRun("planning", projectSlug ?? "");
  const [subStep, setSubStep] = useState<PlanningStep>(lc.analysis ? "review" : "analyze");

  useEffect(() => {
    if (lc.analysis && subStep === "analyze") setSubStep("review");
  }, [lc.analysis]);

  // Handle workflow completion
  const stateHasPlanning = "analysis" in workflow.state || "planning" in workflow.state || Object.keys(workflow.state).length > 3;
  useEffect(() => {
    if (workflow.status === "completed" && stateHasPlanning) {
      const { analysis, features, planEstimates } = parsePlanningOutput(workflow.state);
      lc.setAnalysis(analysis);
      if (features.length > 0) {
        lc.setFeatures(features);
      } else {
        initFeatures(analysis);
      }
      if (planEstimates.length > 0) {
        lc.setPlanEstimates(planEstimates);
      }
      setSubStep("review");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.status, stateHasPlanning]);

  // Handle workflow failure
  useEffect(() => {
    if (workflow.status === "failed") {
      setSubStep("analyze");
    }
  }, [workflow.status]);

  const runAnalysis = () => {
    setSubStep("analyzing");
    lc.advancePhase("planning");
    workflow.start({
      spec: lc.spec,
      research: lc.research,
    });
  };

  const initFeatures = (result: AnalysisResult) => {
    lc.setFeatures(result.kano_features.map((k) => ({
      feature: k.feature,
      category: k.category,
      selected: k.category === "must-be" || k.category === "one-dimensional",
      priority: k.category === "must-be" ? "must" : k.category === "one-dimensional" ? "should" : "could",
      user_delight: k.user_delight,
      implementation_cost: k.implementation_cost,
      rationale: k.rationale,
    })));
  };

  const goNext = () => {
    lc.completePhase("planning");
    navigate(`/p/${projectSlug}/lifecycle/design`);
  };

  const goBack = () => {
    navigate(`/p/${projectSlug}/lifecycle/research`);
  };

  // Analyze input
  if (subStep === "analyze") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-xl w-full space-y-6 text-center">
          <Lightbulb className="h-12 w-12 text-primary mx-auto" />
          <h2 className="text-xl font-bold text-foreground">UX / ビジネス分析</h2>
          <p className="text-sm text-muted-foreground">
            調査結果を基にペルソナ、ユーザーストーリー、KANO分析を実施します
          </p>
          {lc.spec && (
            <div className="rounded-lg border border-border bg-card p-4 text-left">
              <p className="text-xs font-medium text-muted-foreground mb-1">分析対象</p>
              <p className="text-sm text-foreground line-clamp-3">{lc.spec}</p>
            </div>
          )}
          <button onClick={runAnalysis} disabled={!lc.spec.trim()} className={cn(
            "w-full flex items-center justify-center gap-2 rounded-lg py-3 text-sm font-medium transition-colors",
            lc.spec.trim() ? "bg-primary text-primary-foreground hover:bg-primary/90" : "bg-muted text-muted-foreground cursor-not-allowed",
          )}>
            <Zap className="h-4 w-4" /> 分析を開始
          </button>
        </div>
      </div>
    );
  }

  // Analyzing
  if (subStep === "analyzing") {
    if (workflow.status === "failed") {
      return (
        <div className="flex h-full items-center justify-center p-6">
          <div className="max-w-md w-full space-y-4 text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
            <h2 className="text-lg font-bold text-foreground">分析エラー</h2>
            <p className="text-sm text-muted-foreground">{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
            <button onClick={() => { workflow.reset(); setSubStep("analyze"); }} className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
              やり直す
            </button>
          </div>
        </div>
      );
    }
    return (
      <AgentProgressView
        agents={PLANNING_AGENTS}
        progress={workflow.agentProgress}
        elapsedMs={workflow.elapsedMs}
        title="AIが徹底分析中..."
        subtitle="ペルソナ分析とKANO分析を並列実行し、MoSCoW優先度で統合します"
      />
    );
  }

  // Review / Features / Milestones
  const a = lc.analysis!;
  return (
    <div className="flex h-full flex-col">
      {/* Sub-nav */}
      <div className="flex items-center gap-1 border-b border-border px-6 py-2">
        <button onClick={goBack} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mr-2">
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>
        {([
          { key: "review" as const, label: "分析結果", icon: Eye },
          { key: "features" as const, label: "機能選択", icon: CheckSquare },
          { key: "epics" as const, label: "エピック/WBS", icon: Layers },
          { key: "gantt" as const, label: "ガントチャート", icon: GanttChart },
          { key: "milestones" as const, label: "マイルストーン", icon: Flag },
        ]).map((tab) => (
          <button key={tab.key} onClick={() => setSubStep(tab.key)} className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            subStep === tab.key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
          )}>
            <tab.icon className="h-3.5 w-3.5" />{tab.label}
          </button>
        ))}
        <div className="flex-1" />
        <button onClick={goNext} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
          デザイン比較へ <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {subStep === "review" && <ReviewContent analysis={a} />}
        {subStep === "features" && <FeaturesContent features={lc.features} setFeatures={lc.setFeatures} />}
        {subStep === "epics" && (
          <EpicsWbsContent
            planEstimates={lc.planEstimates}
            selectedPreset={lc.selectedPreset}
            onSelectPreset={lc.setSelectedPreset}
          />
        )}
        {subStep === "gantt" && (
          <GanttContent
            planEstimates={lc.planEstimates}
            selectedPreset={lc.selectedPreset}
            onSelectPreset={lc.setSelectedPreset}
          />
        )}
        {subStep === "milestones" && <MilestonesContent milestones={lc.milestones} setMilestones={lc.setMilestones} recommended={lc.analysis?.recommended_milestones} />}
      </div>
    </div>
  );
}

/* ── Analyzing animation ── */
function AnalyzingView({ phases }: { phases: string[] }) {
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setCurrent((c) => Math.min(c + 1, phases.length - 1)), 1200);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6 text-center">
        <Loader2 className="h-12 w-12 text-primary mx-auto animate-spin" />
        <h2 className="text-lg font-bold text-foreground">AIが徹底分析中...</h2>
        <div className="space-y-2">
          {phases.map((p, i) => (
            <div key={i} className={cn("flex items-center gap-2 rounded-md px-4 py-2 text-sm transition-all",
              i < current && "text-success", i === current && "text-primary font-medium", i > current && "text-muted-foreground/50",
            )}>
              {i < current ? <Check className="h-4 w-4" /> : i === current ? <Loader2 className="h-4 w-4 animate-spin" /> : <div className="h-4 w-4" />}
              {p}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── KANO Bubble Chart ── */
const KANO_CAT_STYLE: Record<string, { fill: string; stroke: string; text: string; label: string }> = {
  "must-be": { fill: "rgba(239,68,68,0.25)", stroke: "rgba(239,68,68,0.7)", text: "#f87171", label: "Must-Be" },
  "one-dimensional": { fill: "rgba(59,130,246,0.25)", stroke: "rgba(59,130,246,0.7)", text: "#60a5fa", label: "One-Dimensional" },
  "attractive": { fill: "rgba(34,197,94,0.25)", stroke: "rgba(34,197,94,0.7)", text: "#4ade80", label: "Attractive" },
  "indifferent": { fill: "rgba(148,163,184,0.2)", stroke: "rgba(148,163,184,0.5)", text: "#94a3b8", label: "Indifferent" },
  "reverse": { fill: "rgba(168,85,247,0.25)", stroke: "rgba(168,85,247,0.7)", text: "#a855f7", label: "Reverse" },
};

function KanoBubbleChart({ features, hoveredIdx, onHover }: { features: KanoFeature[]; hoveredIdx: number | null; onHover: (i: number | null) => void }) {

  // Chart dimensions
  const W = 720, H = 400;
  const pad = { top: 30, right: 30, bottom: 50, left: 60 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  // Map cost to X: low=0.15, medium=0.5, high=0.85 with jitter to avoid overlap
  const costBase: Record<string, number> = { low: 0.15, medium: 0.5, high: 0.85 };
  const positions = useMemo(() => {
    const placed: { x: number; y: number }[] = [];
    return features.map((f, i) => {
      let x = costBase[f.implementation_cost] ?? 0.5;
      let y = f.user_delight;
      // Jitter to separate overlapping bubbles
      const R = 22;
      for (let attempt = 0; attempt < 20; attempt++) {
        const px = pad.left + x * plotW;
        const py = pad.top + (1 - y) * plotH;
        const overlap = placed.some((p) => Math.hypot(p.x - px, p.y - py) < R * 1.6);
        if (!overlap) { placed.push({ x: px, y: py }); return { x: px, y: py }; }
        // Apply spiral jitter
        const angle = (attempt * 137.5 * Math.PI) / 180;
        const dist = 6 + attempt * 4;
        x = (costBase[f.implementation_cost] ?? 0.5) + (Math.cos(angle) * dist) / plotW;
        y = f.user_delight + (Math.sin(angle) * dist) / plotH;
        x = Math.max(0.03, Math.min(0.97, x));
        y = Math.max(0.02, Math.min(0.98, y));
      }
      const px = pad.left + x * plotW;
      const py = pad.top + (1 - y) * plotH;
      placed.push({ x: px, y: py });
      return { x: px, y: py };
    });
  }, [features]);

  // Quadrant labels
  const quadrants = [
    { x: pad.left + plotW * 0.08, y: pad.top + plotH * 0.08, text: "High Delight / Low Cost", sub: "Quick Wins" },
    { x: pad.left + plotW * 0.75, y: pad.top + plotH * 0.08, text: "High Delight / High Cost", sub: "Strategic" },
  ];

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="text-sm font-medium text-foreground mb-4">KANO バブルチャート</h3>
      <div className="flex justify-center">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-3xl" style={{ aspectRatio: `${W}/${H}` }}>
          <defs>
            <filter id="tooltip-shadow" x="-10%" y="-10%" width="120%" height="130%">
              <feDropShadow dx="0" dy="4" stdDeviation="6" floodColor="rgba(0,0,0,0.5)" />
            </filter>
          </defs>
          {/* Background */}
          <rect x={pad.left} y={pad.top} width={plotW} height={plotH} rx={8} fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.08)" />

          {/* Grid lines */}
          {[0.25, 0.5, 0.75].map((v) => (
            <g key={`g-${v}`}>
              <line x1={pad.left} y1={pad.top + (1 - v) * plotH} x2={pad.left + plotW} y2={pad.top + (1 - v) * plotH} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
              <line x1={pad.left + v * plotW} y1={pad.top} x2={pad.left + v * plotW} y2={pad.top + plotH} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
            </g>
          ))}

          {/* Quadrant labels */}
          {quadrants.map((q, i) => (
            <g key={i}>
              <text x={q.x} y={q.y} fill="rgba(255,255,255,0.15)" fontSize={11} fontWeight={600}>{q.sub}</text>
            </g>
          ))}

          {/* X axis labels */}
          {[
            { x: 0.15, label: "Low" },
            { x: 0.5, label: "Medium" },
            { x: 0.85, label: "High" },
          ].map((a) => (
            <text key={a.label} x={pad.left + a.x * plotW} y={H - 12} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize={11}>{a.label}</text>
          ))}
          <text x={W / 2} y={H - 0} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={12} fontWeight={500}>Implementation Cost</text>

          {/* Y axis labels */}
          {[0, 0.25, 0.5, 0.75, 1.0].map((v) => (
            <text key={v} x={pad.left - 8} y={pad.top + (1 - v) * plotH + 4} textAnchor="end" fill="rgba(255,255,255,0.4)" fontSize={10}>{v.toFixed(1)}</text>
          ))}
          <text x={14} y={pad.top + plotH / 2} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={12} fontWeight={500} transform={`rotate(-90, 14, ${pad.top + plotH / 2})`}>User Delight</text>

          {/* Bubbles */}
          {features.map((f, i) => {
            const pos = positions[i];
            const style = KANO_CAT_STYLE[f.category] ?? KANO_CAT_STYLE["indifferent"];
            const isHovered = hoveredIdx === i;
            const r = isHovered ? 24 : 18;
            return (
              <g key={i} onMouseEnter={() => onHover(i)} onMouseLeave={() => onHover(null)} style={{ cursor: "pointer", transition: "transform 0.15s ease" }}>
                {isHovered && <circle cx={pos.x} cy={pos.y} r={r + 8} fill={style.fill} opacity={0.4}>
                  <animate attributeName="r" from={String(r + 4)} to={String(r + 10)} dur="0.8s" repeatCount="indefinite" />
                  <animate attributeName="opacity" from="0.4" to="0.1" dur="0.8s" repeatCount="indefinite" />
                </circle>}
                <circle cx={pos.x} cy={pos.y} r={r} fill={style.fill} stroke={style.stroke} strokeWidth={isHovered ? 2.5 : 1.5} style={{ transition: "r 0.15s ease, stroke-width 0.15s ease" }} />
                <text x={pos.x} y={pos.y + 1} textAnchor="middle" dominantBaseline="central" fill={style.text} fontSize={isHovered ? 13 : 11} fontWeight={600}>{i + 1}</text>
              </g>
            );
          })}

          {/* Hover tooltip */}
          {hoveredIdx !== null && (() => {
            const f = features[hoveredIdx];
            const pos = positions[hoveredIdx];
            const style = KANO_CAT_STYLE[f.category] ?? KANO_CAT_STYLE["indifferent"];
            const hasRationale = f.rationale && f.rationale.length > 0;
            const tooltipW = 240;
            const tooltipH = hasRationale ? 68 : 48;
            const tx = Math.min(Math.max(pos.x - tooltipW / 2, pad.left), W - pad.right - tooltipW);
            const ty = pos.y - 36 - tooltipH;
            const above = ty > pad.top;
            const finalY = above ? ty : pos.y + 30;
            return (
              <g style={{ pointerEvents: "none" }}>
                <rect x={tx} y={finalY} width={tooltipW} height={tooltipH} rx={8} fill="rgba(15,23,42,0.95)" stroke={style.stroke} strokeWidth={1.5} filter="url(#tooltip-shadow)" />
                <text x={tx + 12} y={finalY + 18} fill="#e2e8f0" fontSize={12} fontWeight={600}>{f.feature}</text>
                <text x={tx + 12} y={finalY + 36} fill="rgba(148,163,184,0.8)" fontSize={10}>
                  {style.label} · Delight {f.user_delight.toFixed(1)} · Cost {f.implementation_cost}
                </text>
                {hasRationale && (
                  <text x={tx + 12} y={finalY + 54} fill="rgba(148,163,184,0.6)" fontSize={9}>
                    {f.rationale.length > 40 ? f.rationale.slice(0, 40) + "…" : f.rationale}
                  </text>
                )}
              </g>
            );
          })()}

          {/* Legend */}
          {Object.entries(KANO_CAT_STYLE).filter(([k]) => features.some((f) => f.category === k)).map(([, style], i) => (
            <g key={style.label} transform={`translate(${pad.left + i * 140}, ${pad.top - 18})`}>
              <circle cx={6} cy={0} r={5} fill={style.fill} stroke={style.stroke} strokeWidth={1.5} />
              <text x={16} y={4} fill="rgba(255,255,255,0.6)" fontSize={11}>{style.label}</text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

/* ── Review content ── */
type ReviewTab = "overview" | "persona" | "kano" | "stories" | "journey" | "jtbd" | "ia" | "actors" | "usecases" | "design-tokens";
type KanoSortKey = "index" | "feature" | "category" | "delight" | "cost";
type SortDir = "asc" | "desc";
const COST_ORDER: Record<string, number> = { low: 0, medium: 1, high: 2 };

function ReviewContent({ analysis }: { analysis: AnalysisResult }) {
  const [tab, setTab] = useState<ReviewTab>("overview");
  const [kanoHovered, setKanoHovered] = useState<number | null>(null);
  const [kanoSort, setKanoSort] = useState<{ key: KanoSortKey; dir: SortDir }>({ key: "index", dir: "asc" });

  const toggleKanoSort = useCallback((key: KanoSortKey) => {
    setKanoSort((prev) => prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" });
  }, []);

  const sortedKanoFeatures = useMemo(() => {
    const items = analysis.kano_features.map((f, i) => ({ ...f, _origIdx: i }));
    const { key, dir } = kanoSort;
    items.sort((a, b) => {
      let cmp = 0;
      switch (key) {
        case "index": cmp = a._origIdx - b._origIdx; break;
        case "feature": cmp = a.feature.localeCompare(b.feature, "ja"); break;
        case "category": cmp = a.category.localeCompare(b.category); break;
        case "delight": cmp = a.user_delight - b.user_delight; break;
        case "cost": cmp = (COST_ORDER[a.implementation_cost] ?? 1) - (COST_ORDER[b.implementation_cost] ?? 1); break;
      }
      return dir === "desc" ? -cmp : cmp;
    });
    return items;
  }, [analysis.kano_features, kanoSort]);
  const tabs: { key: ReviewTab; label: string; icon: typeof BarChart3; hidden?: boolean }[] = [
    { key: "overview", label: "概要", icon: BarChart3 },
    { key: "persona", label: "ペルソナ", icon: Users },
    { key: "journey", label: "ジャーニー", icon: Route, hidden: !analysis.user_journeys?.length },
    { key: "jtbd", label: "JTBD", icon: Briefcase, hidden: !analysis.job_stories?.length },
    { key: "kano", label: "KANO", icon: BarChart3 },
    { key: "stories", label: "ストーリー", icon: BookOpen },
    { key: "actors", label: "アクター/ロール", icon: UserCheck, hidden: !analysis.actors?.length && !analysis.roles?.length },
    { key: "usecases", label: "ユースケース", icon: FileText, hidden: !analysis.use_cases?.length },
    { key: "ia", label: "IA分析", icon: Network, hidden: !analysis.ia_analysis },
    { key: "design-tokens", label: "デザイントークン", icon: Palette, hidden: !analysis.design_tokens },
  ];

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex gap-1 mb-4 flex-wrap">
        {tabs.filter((t) => !t.hidden).map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            tab === t.key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
          )}>
            <t.icon className="h-3.5 w-3.5" />{t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: "Personas", value: analysis.personas.length },
              { label: "Stories", value: analysis.user_stories.length },
              { label: "Features", value: analysis.kano_features.length },
              { label: "Recommendations", value: analysis.recommendations.length },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-border bg-card p-4 text-center">
                <p className="text-2xl font-bold text-foreground">{s.value}</p>
                <p className="text-xs text-muted-foreground">{s.label}</p>
              </div>
            ))}
          </div>
          {/* KANO distribution */}
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="text-sm font-medium text-foreground mb-3">KANO分布</h3>
            <div className="flex gap-3">
              {[
                { label: "Must-Be", count: analysis.kano_features.filter((f) => f.category === "must-be").length, color: "bg-destructive/10 text-destructive" },
                { label: "One-Dim", count: analysis.kano_features.filter((f) => f.category === "one-dimensional").length, color: "bg-primary/10 text-primary" },
                { label: "Attractive", count: analysis.kano_features.filter((f) => f.category === "attractive").length, color: "bg-success/10 text-success" },
              ].map((k) => (
                <div key={k.label} className={cn("flex-1 rounded-lg p-3 text-center", k.color)}>
                  <p className="text-lg font-bold">{k.count}</p>
                  <p className="text-xs">{k.label}</p>
                </div>
              ))}
            </div>
          </div>
          {/* Recommendations */}
          <div className="space-y-2">
            {analysis.recommendations.map((r, i) => {
              const isQuick = r.includes("Quick Win");
              const isStrategic = r.includes("Strategic");
              return (
                <div key={i} className={cn("rounded-lg border-2 p-3 text-sm text-foreground",
                  isQuick ? "border-success/30 bg-success/5" : isStrategic ? "border-primary/30 bg-primary/5" : "border-border",
                )}>{r}</div>
              );
            })}
          </div>
        </div>
      )}

      {tab === "persona" && (
        <div className="grid gap-4 lg:grid-cols-3">
          {analysis.personas.map((p, i) => (
            <div key={i} className="rounded-xl border border-border bg-card p-5 space-y-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/20 text-primary font-bold">{p.name.charAt(0)}</div>
                <div>
                  <p className="font-medium text-foreground">{p.name}</p>
                  <p className="text-xs text-muted-foreground">{p.role} · {p.age_range}</p>
                </div>
              </div>
              <p className="text-xs text-muted-foreground">{p.context}</p>
              {p.goals.map((g, j) => <p key={j} className="flex items-start gap-1.5 text-xs text-foreground"><Check className="h-3 w-3 mt-0.5 text-success shrink-0" />{g}</p>)}
              {p.frustrations.map((f, j) => <p key={j} className="flex items-start gap-1.5 text-xs text-foreground"><AlertTriangle className="h-3 w-3 mt-0.5 text-destructive shrink-0" />{f}</p>)}
            </div>
          ))}
        </div>
      )}

      {tab === "kano" && (
        <div className="space-y-4">
          <KanoBubbleChart features={analysis.kano_features} hoveredIdx={kanoHovered} onHover={setKanoHovered} />
          {/* Sortable Table */}
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  {([
                    { key: "index" as KanoSortKey, label: "#", w: "w-10" },
                    { key: "feature" as KanoSortKey, label: "Feature", w: "" },
                    { key: "category" as KanoSortKey, label: "Category", w: "w-36" },
                    { key: "delight" as KanoSortKey, label: "Delight", w: "w-32" },
                    { key: "cost" as KanoSortKey, label: "Cost", w: "w-24" },
                  ]).map((col) => (
                    <th key={col.key} className={cn("px-3 py-2.5 text-xs font-medium text-muted-foreground text-left select-none", col.w)}>
                      <button onClick={() => toggleKanoSort(col.key)} className="flex items-center gap-1 hover:text-foreground transition-colors cursor-pointer">
                        {col.label}
                        <ChevronsUpDown className={cn("h-3 w-3", kanoSort.key === col.key ? "text-primary" : "text-muted-foreground/40")} />
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sortedKanoFeatures.map((f) => {
                  const catColor: Record<string, string> = { "must-be": "text-destructive", "one-dimensional": "text-primary", attractive: "text-success", indifferent: "text-muted-foreground", reverse: "text-purple-400" };
                  const isHovered = kanoHovered === f._origIdx;
                  return (
                    <tr key={f._origIdx} onMouseEnter={() => setKanoHovered(f._origIdx)} onMouseLeave={() => setKanoHovered(null)} className={cn("transition-colors cursor-default", isHovered ? "bg-accent/50" : "hover:bg-muted/20")}>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground font-mono">{f._origIdx + 1}</td>
                      <td className="px-3 py-2.5">
                        <p className="font-medium text-foreground">{f.feature}</p>
                        {f.rationale && <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-1">{f.rationale}</p>}
                      </td>
                      <td className={cn("px-3 py-2.5 text-xs font-medium capitalize", catColor[f.category])}>{f.category.replace("-", " ")}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-14 rounded-full bg-muted overflow-hidden">
                            <div className={cn("h-full rounded-full transition-all", f.user_delight > 0.7 ? "bg-success" : f.user_delight > 0.4 ? "bg-primary" : "bg-amber-500")} style={{ width: `${Math.max(f.user_delight * 100, 5)}%` }} />
                          </div>
                          <span className="text-xs text-muted-foreground tabular-nums">{f.user_delight.toFixed(1)}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5"><Badge variant="outline" className={cn("text-[10px] capitalize", f.implementation_cost === "high" ? "border-destructive/40 text-destructive" : f.implementation_cost === "low" ? "border-success/40 text-success" : "")}>{f.implementation_cost}</Badge></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "stories" && (
        <div className="space-y-2 max-w-3xl">
          {analysis.user_stories.map((s, i) => {
            const color: Record<string, string> = { must: "bg-destructive/20 text-destructive", should: "bg-warning/20 text-warning", could: "bg-primary/20 text-primary", wont: "bg-muted text-muted-foreground" };
            return (
              <div key={i} className="flex items-start gap-2 rounded-lg border border-border bg-card p-3">
                <Badge className={cn("text-[10px] border-0 uppercase shrink-0 mt-0.5", color[s.priority])}>{s.priority}</Badge>
                <div>
                  <p className="text-sm text-foreground">As a {s.role}, I want to {s.action}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">So that {s.benefit}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {tab === "journey" && analysis.user_journeys && <JourneyContent journeys={analysis.user_journeys} />}
      {tab === "jtbd" && analysis.job_stories && <JTBDContent stories={analysis.job_stories} />}
      {tab === "actors" && <ActorRoleContent actors={analysis.actors ?? []} roles={analysis.roles ?? []} />}
      {tab === "usecases" && analysis.use_cases && <UseCaseContent useCases={analysis.use_cases} />}
      {tab === "ia" && analysis.ia_analysis && <IAContent ia={analysis.ia_analysis} />}
      {tab === "design-tokens" && analysis.design_tokens && <DesignTokenContent tokens={analysis.design_tokens} />}
    </div>
  );
}

/* ── Design Token Analysis ── */
function DesignTokenContent({ tokens }: { tokens: DesignTokenAnalysis }) {
  const { style, colors, typography, effects, anti_patterns, rationale } = tokens;
  const colorEntries = Object.entries(colors).filter(([k]) => k !== "notes") as [string, string][];
  const colorLabels: Record<string, string> = {
    primary: "Primary", secondary: "Secondary", cta: "CTA",
    background: "Background", text: "Text",
  };

  return (
    <div className="space-y-6">
      {/* Rationale */}
      <div className="rounded-lg bg-card/60 border border-border/40 p-4">
        <p className="text-sm text-muted-foreground leading-relaxed">{rationale}</p>
      </div>

      {/* Style */}
      <div className="rounded-lg bg-card/60 border border-border/40 p-4 space-y-3">
        <h4 className="text-sm font-semibold flex items-center gap-2">
          <Palette className="h-4 w-4 text-violet-400" /> スタイル
        </h4>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-base font-medium">{style.name}</span>
          {style.keywords.map((kw) => (
            <Badge key={kw} variant="secondary" className="text-[10px]">{kw}</Badge>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3 text-xs text-muted-foreground">
          <div><span className="block text-foreground/70 font-medium">適用先</span>{style.best_for || "—"}</div>
          <div><span className="block text-foreground/70 font-medium">パフォーマンス</span>{style.performance || "—"}</div>
          <div><span className="block text-foreground/70 font-medium">アクセシビリティ</span>{style.accessibility || "—"}</div>
        </div>
      </div>

      {/* Colors */}
      <div className="rounded-lg bg-card/60 border border-border/40 p-4 space-y-3">
        <h4 className="text-sm font-semibold">カラーパレット</h4>
        <div className="grid grid-cols-5 gap-3">
          {colorEntries.map(([key, hex]) => (
            <div key={key} className="space-y-1.5">
              <div
                className="h-16 rounded-lg border border-border/30 transition-transform hover:scale-105 cursor-pointer"
                style={{ backgroundColor: hex }}
                title={hex}
              />
              <div className="text-[10px] text-center">
                <div className="font-medium text-foreground/80">{colorLabels[key] ?? key}</div>
                <div className="text-muted-foreground font-mono">{hex}</div>
              </div>
            </div>
          ))}
        </div>
        {colors.notes && <p className="text-xs text-muted-foreground mt-2">{colors.notes}</p>}
      </div>

      {/* Typography */}
      <div className="rounded-lg bg-card/60 border border-border/40 p-4 space-y-3">
        <h4 className="text-sm font-semibold">タイポグラフィ</h4>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <span className="text-[10px] text-muted-foreground block mb-1">見出し</span>
            <span className="text-lg font-semibold" style={{ fontFamily: typography.heading }}>{typography.heading}</span>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground block mb-1">本文</span>
            <span className="text-lg" style={{ fontFamily: typography.body }}>{typography.body}</span>
          </div>
        </div>
        {typography.mood.length > 0 && (
          <div className="flex gap-1.5 flex-wrap">
            {typography.mood.map((m) => <Badge key={m} variant="outline" className="text-[10px]">{m}</Badge>)}
          </div>
        )}
        {typography.google_fonts_url && (
          <a href={typography.google_fonts_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-blue-400 hover:underline">
            Google Fonts で表示
          </a>
        )}
      </div>

      {/* Effects & Anti-patterns */}
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg bg-card/60 border border-border/40 p-4 space-y-2">
          <h4 className="text-sm font-semibold flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5 text-amber-400" /> エフェクト
          </h4>
          <ul className="space-y-1">
            {effects.map((e, i) => (
              <li key={i} className="text-xs text-muted-foreground flex items-center gap-1.5">
                <Check className="h-3 w-3 text-green-400 shrink-0" />{e}
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg bg-card/60 border border-border/40 p-4 space-y-2">
          <h4 className="text-sm font-semibold flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-red-400" /> アンチパターン
          </h4>
          <ul className="space-y-1">
            {anti_patterns.map((a, i) => (
              <li key={i} className="text-xs text-muted-foreground flex items-center gap-1.5">
                <AlertCircle className="h-3 w-3 text-red-400 shrink-0" />{a}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

/* ── Actor & Role Analysis ── */
const ACTOR_TYPE_STYLE: Record<string, { bg: string; text: string; label: string; icon: typeof Users }> = {
  primary: { bg: "bg-primary/15 border-primary/30", text: "text-primary", label: "プライマリ", icon: Users },
  secondary: { bg: "bg-amber-500/15 border-amber-500/30", text: "text-amber-400", label: "セカンダリ", icon: UserCheck },
  external_system: { bg: "bg-purple-500/15 border-purple-500/30", text: "text-purple-400", label: "外部システム", icon: Network },
};

function ActorRoleContent({ actors, roles }: { actors: Actor[]; roles: Role[] }) {
  const [activeTab, setActiveTab] = useState<"actors" | "roles">("actors");

  return (
    <div className="space-y-4">
      {/* Sub-tab toggle */}
      <div className="flex gap-1">
        {([
          { key: "actors" as const, label: "アクター", icon: Users, count: actors.length },
          { key: "roles" as const, label: "ロール", icon: Shield, count: roles.length },
        ]).map((t) => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} className={cn(
            "flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
            activeTab === t.key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
          )}>
            <t.icon className="h-3.5 w-3.5" />{t.label}
            <span className={cn("ml-1 rounded-full px-1.5 py-0.5 text-[10px]", activeTab === t.key ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground")}>{t.count}</span>
          </button>
        ))}
      </div>

      {activeTab === "actors" && (
        <div className="grid gap-4 lg:grid-cols-2">
          {actors.map((a, i) => {
            const style = ACTOR_TYPE_STYLE[a.type] ?? ACTOR_TYPE_STYLE.primary;
            return (
              <div key={i} className={cn("rounded-xl border p-5 space-y-3", style.bg)}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={cn("flex h-10 w-10 items-center justify-center rounded-full", style.bg)}>
                      <style.icon className={cn("h-5 w-5", style.text)} />
                    </div>
                    <div>
                      <p className="font-medium text-foreground">{a.name}</p>
                      <p className="text-xs text-muted-foreground">{a.description}</p>
                    </div>
                  </div>
                  <Badge variant="outline" className={cn("text-[10px]", style.text)}>{style.label}</Badge>
                </div>
                {a.goals.length > 0 && (
                  <div>
                    <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">ゴール</p>
                    <div className="space-y-1">
                      {a.goals.map((g, j) => (
                        <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                          <Target className="h-3 w-3 mt-0.5 text-success shrink-0" />{g}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
                {a.interactions.length > 0 && (
                  <div>
                    <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">インタラクション</p>
                    <div className="flex flex-wrap gap-1">
                      {a.interactions.map((int, j) => (
                        <Badge key={j} variant="outline" className="text-[10px] bg-muted/30">{int}</Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {activeTab === "roles" && (
        <div className="space-y-3">
          {roles.map((r, i) => (
            <div key={i} className="rounded-xl border border-border bg-card p-5 space-y-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/20">
                  <Shield className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="font-medium text-foreground">{r.name}</p>
                  {r.related_actors.length > 0 && (
                    <p className="text-xs text-muted-foreground">関連アクター: {r.related_actors.join(", ")}</p>
                  )}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">責務</p>
                  <div className="space-y-1">
                    {r.responsibilities.map((resp, j) => (
                      <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                        <Check className="h-3 w-3 mt-0.5 text-success shrink-0" />{resp}
                      </p>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">権限</p>
                  <div className="space-y-1">
                    {r.permissions.map((perm, j) => (
                      <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                        <Shield className="h-3 w-3 mt-0.5 text-amber-400 shrink-0" />{perm}
                      </p>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Use Case Catalog ── */
function UseCaseContent({ useCases }: { useCases: UseCase[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const priorityStyle: Record<string, string> = {
    must: "bg-destructive/20 text-destructive",
    should: "bg-amber-500/20 text-amber-400",
    could: "bg-primary/20 text-primary",
  };

  // Group by category → sub_category
  const grouped = useMemo(() => {
    const cats = new Map<string, Map<string, UseCase[]>>();
    for (const uc of useCases) {
      const cat = uc.category || "未分類";
      const sub = uc.sub_category || "その他";
      if (!cats.has(cat)) cats.set(cat, new Map());
      const subMap = cats.get(cat)!;
      if (!subMap.has(sub)) subMap.set(sub, []);
      subMap.get(sub)!.push(uc);
    }
    return cats;
  }, [useCases]);

  const renderUseCase = (uc: UseCase) => {
    const isOpen = expanded.has(uc.id);
    return (
      <div key={uc.id} className="rounded-xl border border-border bg-card overflow-hidden">
        <button onClick={() => toggle(uc.id)} className="w-full flex items-center gap-3 p-4 text-left hover:bg-muted/20 transition-colors cursor-pointer">
          <ChevronRight className={cn("h-4 w-4 text-muted-foreground shrink-0 transition-transform", isOpen && "rotate-90")} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground font-mono">{uc.id}</span>
              <p className="font-medium text-foreground truncate">{uc.title}</p>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              <Users className="h-3 w-3 inline mr-1" />{uc.actor}
            </p>
          </div>
          <Badge className={cn("text-[10px] border-0 uppercase shrink-0", priorityStyle[uc.priority])}>{uc.priority}</Badge>
        </button>
        {isOpen && (
          <div className="border-t border-border px-4 py-4 space-y-4 bg-muted/5">
            {uc.preconditions.length > 0 && (
              <div>
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">事前条件</p>
                <div className="space-y-1">
                  {uc.preconditions.map((pre, j) => (
                    <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                      <CircleDot className="h-3 w-3 mt-0.5 text-amber-400 shrink-0" />{pre}
                    </p>
                  ))}
                </div>
              </div>
            )}
            <div>
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">メインフロー</p>
              <div className="space-y-1.5">
                {uc.main_flow.map((step, j) => (
                  <div key={j} className="flex items-start gap-2 text-xs text-foreground">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-primary text-[10px] font-bold shrink-0">{j + 1}</span>
                    <span className="pt-0.5">{step}</span>
                  </div>
                ))}
              </div>
            </div>
            {uc.alternative_flows && uc.alternative_flows.length > 0 && (
              <div>
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">代替フロー</p>
                {uc.alternative_flows.map((af, j) => (
                  <div key={j} className="rounded-lg border border-border bg-card p-3 mb-2">
                    <p className="text-xs font-medium text-amber-400 mb-1.5">
                      <AlertTriangle className="h-3 w-3 inline mr-1" />{af.condition}
                    </p>
                    <div className="space-y-1 ml-4">
                      {af.steps.map((s, k) => (
                        <p key={k} className="text-xs text-muted-foreground">{k + 1}. {s}</p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {uc.postconditions.length > 0 && (
              <div>
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5">事後条件</p>
                <div className="space-y-1">
                  {uc.postconditions.map((post, j) => (
                    <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                      <Check className="h-3 w-3 mt-0.5 text-success shrink-0" />{post}
                    </p>
                  ))}
                </div>
              </div>
            )}
            {uc.related_stories && uc.related_stories.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-[10px] text-muted-foreground mr-1">関連ストーリー:</span>
                {uc.related_stories.map((s, j) => (
                  <Badge key={j} variant="outline" className="text-[10px]">{s}</Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {/* Summary bar */}
      <div className="flex gap-3">
        {(["must", "should", "could"] as const).map((p) => {
          const count = useCases.filter((uc) => uc.priority === p).length;
          const labels: Record<string, string> = { must: "Must", should: "Should", could: "Could" };
          return (
            <div key={p} className={cn("flex-1 rounded-lg p-3 text-center border", priorityStyle[p])}>
              <p className="text-lg font-bold">{count}</p>
              <p className="text-xs">{labels[p]}</p>
            </div>
          );
        })}
      </div>

      {/* Category grouped use cases */}
      {Array.from(grouped.entries()).map(([cat, subMap]) => (
        <div key={cat} className="space-y-3">
          <div className="flex items-center gap-2 pt-2">
            <FolderOpen className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-bold text-foreground">{cat}</h3>
            <span className="text-[10px] text-muted-foreground">({Array.from(subMap.values()).flat().length})</span>
          </div>
          {Array.from(subMap.entries()).map(([sub, ucs]) => (
            <div key={sub} className="ml-4 space-y-2">
              <div className="flex items-center gap-1.5">
                <div className="h-px flex-1 max-w-3 bg-border" />
                <span className="text-[11px] font-medium text-muted-foreground">{sub}</span>
                <span className="text-[10px] text-muted-foreground/60">({ucs.length})</span>
                <div className="h-px flex-1 bg-border" />
              </div>
              {ucs.map(renderUseCase)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ── User Journey Map ── */
const PHASE_LABELS: Record<JourneyPhase, string> = {
  awareness: "認知", consideration: "検討", acquisition: "導入", usage: "利用", advocacy: "推奨",
};
const PHASE_COLORS: Record<JourneyPhase, string> = {
  awareness: "bg-blue-500/20 border-blue-500/40", consideration: "bg-amber-500/20 border-amber-500/40",
  acquisition: "bg-green-500/20 border-green-500/40", usage: "bg-purple-500/20 border-purple-500/40",
  advocacy: "bg-pink-500/20 border-pink-500/40",
};
const EmotionIcon = ({ emotion }: { emotion: JourneyTouchpoint["emotion"] }) => {
  if (emotion === "positive") return <Smile className="h-4 w-4 text-green-500" />;
  if (emotion === "negative") return <Frown className="h-4 w-4 text-red-500" />;
  return <Meh className="h-4 w-4 text-amber-500" />;
};

function JourneyContent({ journeys }: { journeys: UserJourneyMap[] }) {
  const [activePersona, setActivePersona] = useState(0);
  const journey = journeys[activePersona];
  if (!journey) return null;
  const phases: JourneyPhase[] = ["awareness", "consideration", "acquisition", "usage", "advocacy"];

  return (
    <div className="space-y-4">
      {/* Persona selector */}
      {journeys.length > 1 && (
        <div className="flex gap-2">
          {journeys.map((j, i) => (
            <button key={i} onClick={() => setActivePersona(i)} className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
              i === activePersona ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
            )}>
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/20 text-primary text-[10px] font-bold">{j.persona_name.charAt(0)}</div>
              {j.persona_name}
            </button>
          ))}
        </div>
      )}

      {/* Journey map */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Phase header */}
        <div className="grid grid-cols-5 border-b border-border">
          {phases.map((p) => (
            <div key={p} className={cn("px-3 py-2.5 text-center text-xs font-bold border-r border-border last:border-r-0", PHASE_COLORS[p])}>
              {PHASE_LABELS[p]}
            </div>
          ))}
        </div>

        {/* Emotion curve */}
        <div className="grid grid-cols-5 border-b border-border">
          {phases.map((p) => {
            const tp = journey.touchpoints.find((t) => t.phase === p);
            return (
              <div key={p} className="flex items-center justify-center py-3 border-r border-border last:border-r-0">
                {tp ? <EmotionIcon emotion={tp.emotion} /> : <Meh className="h-4 w-4 text-muted-foreground/30" />}
              </div>
            );
          })}
        </div>

        {/* Actions row */}
        <div className="grid grid-cols-5 border-b border-border">
          {phases.map((p) => {
            const tp = journey.touchpoints.find((t) => t.phase === p);
            return (
              <div key={p} className="px-3 py-3 border-r border-border last:border-r-0">
                <p className="text-[10px] font-medium text-muted-foreground mb-1">行動</p>
                <p className="text-xs text-foreground">{tp?.action || "—"}</p>
              </div>
            );
          })}
        </div>

        {/* Touchpoints row */}
        <div className="grid grid-cols-5 border-b border-border">
          {phases.map((p) => {
            const tp = journey.touchpoints.find((t) => t.phase === p);
            return (
              <div key={p} className="px-3 py-3 border-r border-border last:border-r-0">
                <p className="text-[10px] font-medium text-muted-foreground mb-1">タッチポイント</p>
                <p className="text-xs text-foreground flex items-start gap-1"><MapPin className="h-3 w-3 mt-0.5 shrink-0 text-primary" />{tp?.touchpoint || "—"}</p>
              </div>
            );
          })}
        </div>

        {/* Pain points row */}
        <div className="grid grid-cols-5 border-b border-border">
          {phases.map((p) => {
            const tp = journey.touchpoints.find((t) => t.phase === p);
            return (
              <div key={p} className="px-3 py-3 border-r border-border last:border-r-0">
                {tp?.pain_point && (
                  <>
                    <p className="text-[10px] font-medium text-destructive/80 mb-1">ペインポイント</p>
                    <p className="text-xs text-destructive/90">{tp.pain_point}</p>
                  </>
                )}
              </div>
            );
          })}
        </div>

        {/* Opportunities row */}
        <div className="grid grid-cols-5">
          {phases.map((p) => {
            const tp = journey.touchpoints.find((t) => t.phase === p);
            return (
              <div key={p} className="px-3 py-3 border-r border-border last:border-r-0">
                {tp?.opportunity && (
                  <>
                    <p className="text-[10px] font-medium text-green-500/80 mb-1">機会</p>
                    <p className="text-xs text-green-500/90">{tp.opportunity}</p>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ── JTBD / Job Stories ── */
const JTBD_COLORS: Record<JobStory["priority"], { badge: string; border: string }> = {
  core: { badge: "bg-destructive/20 text-destructive", border: "border-destructive/30 bg-destructive/5" },
  supporting: { badge: "bg-primary/20 text-primary", border: "border-primary/30 bg-primary/5" },
  aspirational: { badge: "bg-success/20 text-success", border: "border-success/30 bg-success/5" },
};

function JTBDContent({ stories }: { stories: JobStory[] }) {
  const grouped = {
    core: stories.filter((s) => s.priority === "core"),
    supporting: stories.filter((s) => s.priority === "supporting"),
    aspirational: stories.filter((s) => s.priority === "aspirational"),
  };
  const sections: { key: JobStory["priority"]; label: string; desc: string }[] = [
    { key: "core", label: "Core Jobs", desc: "プロダクトの存在理由となる中核的ジョブ" },
    { key: "supporting", label: "Supporting Jobs", desc: "コアジョブを補助する関連ジョブ" },
    { key: "aspirational", label: "Aspirational Jobs", desc: "差別化につながる願望的ジョブ" },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-3">
        {sections.map((s) => (
          <div key={s.key} className={cn("rounded-xl border p-4 text-center", JTBD_COLORS[s.key].border)}>
            <p className="text-2xl font-bold text-foreground">{grouped[s.key].length}</p>
            <p className="text-xs text-muted-foreground">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Stories */}
      {sections.map((s) => {
        const items = grouped[s.key];
        if (items.length === 0) return null;
        return (
          <div key={s.key}>
            <h3 className="text-sm font-bold text-foreground mb-1">{s.label}</h3>
            <p className="text-xs text-muted-foreground mb-3">{s.desc}</p>
            <div className="space-y-3">
              {items.map((story, i) => (
                <div key={i} className={cn("rounded-lg border p-4 space-y-2", JTBD_COLORS[s.key].border)}>
                  <div className="space-y-1">
                    <p className="text-sm text-foreground"><span className="font-medium text-muted-foreground">When</span> {story.situation}</p>
                    <p className="text-sm text-foreground"><span className="font-medium text-muted-foreground">I want to</span> {story.motivation}</p>
                    <p className="text-sm text-foreground"><span className="font-medium text-muted-foreground">So I can</span> {story.outcome}</p>
                  </div>
                  {story.related_features.length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {story.related_features.map((f, j) => (
                        <Badge key={j} variant="outline" className="text-[10px]">{f}</Badge>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── IA (Information Architecture) ── */
const IA_PRIORITY_COLORS: Record<IANode["priority"], string> = {
  primary: "bg-primary/20 text-primary border-primary/40",
  secondary: "bg-amber-500/20 text-amber-500 border-amber-500/40",
  utility: "bg-muted text-muted-foreground border-border",
};
const NAV_MODEL_LABELS: Record<IAAnalysis["navigation_model"], string> = {
  hierarchical: "階層型", flat: "フラット型", "hub-and-spoke": "ハブ＆スポーク型", matrix: "マトリクス型",
};

function IANodeTree({ node, depth = 0 }: { node: IANode; depth?: number }) {
  return (
    <div className={cn("border-l-2 pl-3", depth === 0 ? "border-primary/40" : "border-border/50")} style={{ marginLeft: depth > 0 ? 12 : 0 }}>
      <div className="flex items-center gap-2 py-1.5">
        <Badge className={cn("text-[10px] border shrink-0", IA_PRIORITY_COLORS[node.priority])}>{node.priority}</Badge>
        <span className="text-sm font-medium text-foreground">{node.label}</span>
        {node.description && <span className="text-xs text-muted-foreground truncate">— {node.description}</span>}
      </div>
      {node.children?.map((child) => <IANodeTree key={child.id} node={child} depth={depth + 1} />)}
    </div>
  );
}

function IAContent({ ia }: { ia: IAAnalysis }) {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Navigation model badge */}
      <div className="flex items-center gap-3">
        <div className="rounded-lg border border-border bg-card px-4 py-3 flex items-center gap-2">
          <Network className="h-4 w-4 text-primary" />
          <div>
            <p className="text-[10px] text-muted-foreground">ナビゲーションモデル</p>
            <p className="text-sm font-bold text-foreground">{NAV_MODEL_LABELS[ia.navigation_model]}</p>
          </div>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-3 flex items-center gap-2">
          <Route className="h-4 w-4 text-primary" />
          <div>
            <p className="text-[10px] text-muted-foreground">主要パス</p>
            <p className="text-sm font-bold text-foreground">{ia.key_paths.length} フロー</p>
          </div>
        </div>
      </div>

      {/* Site map tree */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-bold text-foreground mb-4 flex items-center gap-2">
          <Network className="h-4 w-4 text-primary" />サイトマップ
        </h3>
        <div className="space-y-1">
          {ia.site_map.map((node) => <IANodeTree key={node.id} node={node} />)}
        </div>
      </div>

      {/* Key paths */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-bold text-foreground mb-4 flex items-center gap-2">
          <Route className="h-4 w-4 text-primary" />主要ユーザーフロー
        </h3>
        <div className="space-y-4">
          {ia.key_paths.map((path, i) => (
            <div key={i}>
              <p className="text-xs font-medium text-foreground mb-2">{path.name}</p>
              <div className="flex items-center gap-1 flex-wrap">
                {path.steps.map((step, j) => (
                  <div key={j} className="flex items-center gap-1">
                    <span className="rounded-md bg-primary/10 border border-primary/30 px-2.5 py-1 text-xs text-primary font-medium">{step}</span>
                    {j < path.steps.length - 1 && <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Features content ── */
function FeaturesContent({ features, setFeatures }: { features: FeatureSelection[]; setFeatures: (f: FeatureSelection[]) => void }) {
  const toggle = (idx: number) => {
    const next = [...features];
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
    setFeatures(features.map((f) => {
      if (f.category === "must-be") return { ...f, selected: true };
      if (preset === "minimal") return { ...f, selected: false };
      if (preset === "full") return { ...f, selected: true };
      return { ...f, selected: f.category === "one-dimensional" || (f.category === "attractive" && f.user_delight >= 0.7) };
    }));
  };

  const selectedCount = features.filter((f) => f.selected).length;

  const groups = [
    { title: "Must-Be（必須機能）", desc: "製品として必須。除外不可。", category: "must-be", locked: true },
    { title: "One-Dimensional（性能機能）", desc: "実装の質に比例して満足度が上がる。", category: "one-dimensional", locked: false },
    { title: "Attractive（魅力機能）", desc: "あると感動する差別化機能。", category: "attractive", locked: false },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{selectedCount}/{features.length} 選択中</span>
        <div className="flex gap-1">
          {(["minimal", "recommended", "full"] as const).map((p) => (
            <button key={p} onClick={() => selectPreset(p)} className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
              {p === "minimal" ? "最小" : p === "recommended" ? "推奨" : "全機能"}
            </button>
          ))}
        </div>
      </div>

      {groups.map((g) => {
        const groupFeatures = features.filter((f) => f.category === g.category);
        if (groupFeatures.length === 0) return null;
        return (
          <div key={g.category}>
            <h3 className="text-sm font-bold text-foreground">{g.title}</h3>
            <p className="text-xs text-muted-foreground mb-3">{g.desc}</p>
            <div className="space-y-2">
              {groupFeatures.map((f) => {
                const idx = features.indexOf(f);
                const catColor: Record<string, string> = { "must-be": "border-destructive/30 bg-destructive/5", "one-dimensional": "border-primary/30 bg-primary/5", attractive: "border-success/30 bg-success/5" };
                return (
                  <div key={f.feature} className={cn("flex items-center gap-3 rounded-lg border p-3 transition-colors", f.selected ? catColor[f.category] || "border-border" : "border-border bg-card opacity-60")}>
                    <button onClick={() => toggle(idx)} disabled={g.locked} className={cn(g.locked && "cursor-not-allowed")}>
                      {f.selected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted-foreground" />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground">{f.feature}</p>
                      <p className="text-xs text-muted-foreground truncate">{f.rationale}</p>
                    </div>
                    <Badge variant="outline" className="text-[10px] capitalize shrink-0">{f.implementation_cost}</Badge>
                    {f.selected && !g.locked && (
                      <div className="flex gap-0.5 shrink-0">
                        {(["must", "should", "could"] as const).map((p) => (
                          <button key={p} onClick={() => setPriority(idx, p)} className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase transition-colors",
                            f.priority === p ? (p === "must" ? "bg-destructive/20 text-destructive" : p === "should" ? "bg-warning/20 text-warning" : "bg-primary/20 text-primary") : "text-muted-foreground hover:text-foreground",
                          )}>{p}</button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Milestones content ── */
const PHASE_MILESTONE_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  alpha: { bg: "bg-amber-500/15 border-amber-500/30", text: "text-amber-400", label: "Alpha" },
  beta: { bg: "bg-blue-500/15 border-blue-500/30", text: "text-blue-400", label: "Beta" },
  release: { bg: "bg-green-500/15 border-green-500/30", text: "text-green-400", label: "Release" },
};

function MilestonesContent({ milestones, setMilestones, recommended }: { milestones: Milestone[]; setMilestones: (m: Milestone[]) => void; recommended?: RecommendedMilestone[] }) {
  const addMilestone = () => setMilestones([...milestones, { id: `ms-${Date.now()}`, name: "", criteria: "", status: "pending" }]);
  const update = (idx: number, field: "name" | "criteria", value: string) => {
    const next = [...milestones]; next[idx] = { ...next[idx], [field]: value }; setMilestones(next);
  };
  const remove = (idx: number) => setMilestones(milestones.filter((_, i) => i !== idx));
  const addPreset = (type: "feature" | "quality" | "responsive") => {
    const presets: Record<string, Milestone> = {
      feature: { id: `ms-${Date.now()}`, name: "全機能実装", criteria: "選択されたすべての機能が動作可能", status: "pending" },
      quality: { id: `ms-${Date.now() + 1}`, name: "コード品質", criteria: "エラーハンドリング、バリデーション、ローディング状態の適切な実装", status: "pending" },
      responsive: { id: `ms-${Date.now() + 2}`, name: "レスポンシブ", criteria: "モバイル・タブレット・デスクトップで正しく表示", status: "pending" },
    };
    setMilestones([...milestones, presets[type]]);
  };

  const adoptRecommended = (rm: RecommendedMilestone) => {
    if (milestones.some((m) => m.id === rm.id)) return;
    setMilestones([...milestones, { id: rm.id, name: rm.name, criteria: rm.criteria, status: "pending" }]);
  };
  const adoptAll = () => {
    if (!recommended) return;
    const existing = new Set(milestones.map((m) => m.id));
    const newMs = recommended.filter((rm) => !existing.has(rm.id)).map((rm) => ({ id: rm.id, name: rm.name, criteria: rm.criteria, status: "pending" as const }));
    if (newMs.length > 0) setMilestones([...milestones, ...newMs]);
  };
  const isAdopted = (id: string) => milestones.some((m) => m.id === id);

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-foreground"><Flag className="h-4 w-4 text-primary" />マイルストーン（完成条件）</h3>
          <p className="text-xs text-muted-foreground">条件をクリアするまでAIが自律的に改善を繰り返します（最大5回）</p>
        </div>
        <button onClick={addMilestone} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer">
          <Plus className="h-3.5 w-3.5" /> 追加
        </button>
      </div>

      {/* Recommended milestones from analysis */}
      {recommended && recommended.length > 0 && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium text-foreground">AIおすすめマイルストーン</span>
              <span className="text-[10px] text-muted-foreground">（分析結果に基づく推奨）</span>
            </div>
            <button onClick={adoptAll} className="flex items-center gap-1 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/20 transition-colors cursor-pointer">
              <Plus className="h-3 w-3" /> すべて採用
            </button>
          </div>
          <div className="space-y-2">
            {(["alpha", "beta", "release"] as const).map((phase) => {
              const items = recommended.filter((rm) => rm.phase === phase);
              if (items.length === 0) return null;
              const style = PHASE_MILESTONE_STYLE[phase];
              return (
                <div key={phase}>
                  <p className={cn("text-[10px] font-medium uppercase tracking-wide mb-1.5", style.text)}>{style.label} Phase</p>
                  <div className="space-y-1.5">
                    {items.map((rm) => {
                      const adopted = isAdopted(rm.id);
                      return (
                        <div key={rm.id} className={cn("flex items-start gap-3 rounded-lg border p-3 transition-colors", adopted ? "border-success/30 bg-success/5" : "border-border bg-card hover:border-primary/30")}>
                          <button onClick={() => adoptRecommended(rm)} disabled={adopted} className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full mt-0.5 transition-colors cursor-pointer", adopted ? "bg-success/20 text-success" : "bg-muted hover:bg-primary/20 hover:text-primary")}>
                            {adopted ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                          </button>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-foreground">{rm.name}</p>
                            <p className="text-xs text-muted-foreground mt-0.5">{rm.criteria}</p>
                            <p className="text-[11px] text-muted-foreground/70 mt-1 italic">{rm.rationale}</p>
                            {rm.depends_on_use_cases && rm.depends_on_use_cases.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1.5">
                                {rm.depends_on_use_cases.map((uc) => (
                                  <Badge key={uc} variant="outline" className="text-[9px]">{uc}</Badge>
                                ))}
                              </div>
                            )}
                          </div>
                          <Badge variant="outline" className={cn("text-[10px] shrink-0", style.text)}>{style.label}</Badge>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {milestones.length === 0 && !recommended?.length && (
        <div className="rounded-lg border-2 border-dashed border-border p-8 text-center">
          <Flag className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
          <p className="text-sm text-muted-foreground mb-3">マイルストーン未定義（定義しなくても開発は可能）</p>
          <div className="flex items-center justify-center gap-2">
            <button onClick={() => addPreset("feature")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 cursor-pointer">全機能実装</button>
            <button onClick={() => addPreset("quality")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 cursor-pointer">コード品質</button>
            <button onClick={() => addPreset("responsive")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 cursor-pointer">レスポンシブ</button>
          </div>
        </div>
      )}

      {/* Current milestones */}
      {milestones.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">採用済みマイルストーン ({milestones.length})</p>
          {milestones.map((ms, i) => (
            <div key={ms.id} className="flex gap-3 rounded-lg border border-border bg-card p-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary mt-0.5">{i + 1}</div>
              <div className="flex-1 space-y-2">
                <input value={ms.name} onChange={(e) => update(i, "name", e.target.value)} placeholder="マイルストーン名" className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
                <textarea value={ms.criteria} onChange={(e) => update(i, "criteria", e.target.value)} placeholder="完成条件の詳細" rows={2} className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none" />
              </div>
              <button onClick={() => remove(i)} className="shrink-0 text-muted-foreground hover:text-destructive transition-colors mt-0.5 cursor-pointer"><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Preset Selector (shared) ── */
const PRESET_CONFIG: Record<PlanPreset, { label: string; color: string; bg: string; desc: string }> = {
  minimal: { label: "Minimal", color: "text-green-500", bg: "bg-green-500/10 border-green-500/30", desc: "Must-haveのみ、最短・低コスト" },
  standard: { label: "Standard", color: "text-blue-500", bg: "bg-blue-500/10 border-blue-500/30", desc: "Must + Shouldの機能でバランス型" },
  full: { label: "Full", color: "text-purple-500", bg: "bg-purple-500/10 border-purple-500/30", desc: "全機能、最高品質、フルスキル活用" },
};

function PresetSelector({ plans, selected, onSelect }: {
  plans: PlanEstimate[];
  selected: PlanPreset;
  onSelect: (p: PlanPreset) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {(["minimal", "standard", "full"] as const).map((preset) => {
        const plan = plans.find((p) => p.preset === preset);
        const cfg = PRESET_CONFIG[preset];
        const isActive = selected === preset;
        return (
          <button
            key={preset}
            onClick={() => onSelect(preset)}
            className={cn(
              "rounded-xl border-2 p-4 text-left transition-all",
              isActive ? `${cfg.bg} border-current ${cfg.color}` : "border-border hover:border-primary/30",
            )}
          >
            <div className="flex items-center justify-between mb-2">
              <span className={cn("text-sm font-bold", isActive ? cfg.color : "text-foreground")}>{cfg.label}</span>
              {isActive && <Check className="h-4 w-4" />}
            </div>
            <p className="text-[11px] text-muted-foreground mb-3">{cfg.desc}</p>
            {plan ? (
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <p className="text-[10px] text-muted-foreground">工数</p>
                  <p className="text-sm font-bold text-foreground">{plan.total_effort_hours}h</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground">予算</p>
                  <p className="text-sm font-bold text-foreground">${plan.total_cost_usd.toFixed(0)}</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground">期間</p>
                  <p className="text-sm font-bold text-foreground">{plan.duration_weeks}w</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">データなし</p>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ── Epics & WBS Content ── */
function EpicsWbsContent({ planEstimates, selectedPreset, onSelectPreset }: {
  planEstimates: PlanEstimate[];
  selectedPreset: PlanPreset;
  onSelectPreset: (p: PlanPreset) => void;
}) {
  const plan = planEstimates.find((p) => p.preset === selectedPreset);

  if (planEstimates.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-border p-12 text-center">
        <Layers className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-sm text-muted-foreground">プランデータが生成されていません</p>
        <p className="text-xs text-muted-foreground mt-1">分析を実行するとエピック/WBS/ガントチャートが生成されます</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PresetSelector plans={planEstimates} selected={selectedPreset} onSelect={onSelectPreset} />

      {plan && (
        <>
          {/* Summary */}
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Bot className="h-3.5 w-3.5" />
              <span>{plan.agents_used.length} agents</span>
            </div>
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Wrench className="h-3.5 w-3.5" />
              <span>{plan.skills_used.length} skills</span>
            </div>
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Layers className="h-3.5 w-3.5" />
              <span>{plan.epics.length} epics / {plan.wbs.length} tasks</span>
            </div>
          </div>

          {/* Epics */}
          {plan.epics.map((epic, ei) => {
            const epicWbs = plan.wbs.filter((w) => w.epic_id === epic.id);
            return (
              <div key={epic.id} className="rounded-xl border border-border bg-card overflow-hidden">
                {/* Epic Header */}
                <div className="flex items-start gap-3 border-b border-border px-4 py-3 bg-accent/20">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary">
                    E{ei + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-foreground">{epic.name}</p>
                      <Badge variant={epic.priority === "must" ? "destructive" : epic.priority === "should" ? "warning" : "secondary"} className="text-[10px]">
                        {epic.priority}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{epic.description}</p>
                  </div>
                </div>

                {/* Use Cases */}
                {epic.use_cases.length > 0 && (
                  <div className="border-b border-border px-4 py-2.5 bg-accent/10">
                    <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">ユースケース</p>
                    <div className="flex flex-wrap gap-1.5">
                      {epic.use_cases.map((uc, j) => (
                        <span key={j} className="rounded-md bg-background border border-border px-2 py-0.5 text-[11px] text-foreground">{uc}</span>
                      ))}
                    </div>
                  </div>
                )}

                {/* WBS Items */}
                {epicWbs.length > 0 && (
                  <div className="divide-y divide-border">
                    <div className="flex items-center gap-3 px-4 py-1.5 bg-accent/5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                      <div className="w-48 shrink-0">タスク</div>
                      <div className="w-28 shrink-0">担当</div>
                      <div className="flex-1">スキル</div>
                      <div className="w-16 shrink-0 text-right">工数</div>
                      <div className="w-16 shrink-0 text-right">期間</div>
                      <div className="w-16 shrink-0">依存</div>
                    </div>
                    {epicWbs.map((item) => (
                      <WbsRow key={item.id} item={item} allItems={plan.wbs} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

function WbsRow({ item, allItems }: { item: WbsItem; allItems: WbsItem[] }) {
  const deps = item.depends_on
    .map((depId) => allItems.find((w) => w.id === depId))
    .filter(Boolean);

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-accent/20 transition-colors">
      <div className="w-48 shrink-0">
        <p className="text-xs font-medium text-foreground truncate">{item.title}</p>
        {item.description && (
          <p className="text-[10px] text-muted-foreground truncate">{item.description}</p>
        )}
      </div>
      <div className="flex items-center gap-1 w-28 shrink-0">
        {item.assignee_type === "agent" ? <Bot className="h-3 w-3 text-blue-500" /> : <Users className="h-3 w-3 text-orange-500" />}
        <span className="text-[11px] text-muted-foreground truncate">{item.assignee}</span>
      </div>
      <div className="flex gap-1 flex-1 min-w-0">
        {item.skills.slice(0, 3).map((s) => (
          <Badge key={s} variant="outline" className="text-[9px] shrink-0">{s}</Badge>
        ))}
      </div>
      <div className="text-right w-16 shrink-0">
        <span className="text-xs font-mono text-foreground">{item.effort_hours}h</span>
      </div>
      <div className="text-right w-16 shrink-0">
        <span className="text-[11px] text-muted-foreground">{item.duration_days}d</span>
      </div>
      <div className="w-16 shrink-0">
        {deps.length > 0 ? (
          <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
            <ArrowDown className="h-3 w-3" />{deps.length}
          </span>
        ) : (
          <span className="text-[10px] text-muted-foreground">—</span>
        )}
      </div>
    </div>
  );
}

/* ── Gantt Chart Content ── */
function GanttContent({ planEstimates, selectedPreset, onSelectPreset }: {
  planEstimates: PlanEstimate[];
  selectedPreset: PlanPreset;
  onSelectPreset: (p: PlanPreset) => void;
}) {
  const plan = planEstimates.find((p) => p.preset === selectedPreset);

  if (planEstimates.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-border p-12 text-center">
        <GanttChart className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-sm text-muted-foreground">プランデータが生成されていません</p>
      </div>
    );
  }

  const wbs = plan?.wbs ?? [];
  const maxDay = Math.max(...wbs.map((w) => w.start_day + w.duration_days), 1);
  const totalWeeks = Math.ceil(maxDay / 7);
  const weekMarkers = Array.from({ length: totalWeeks }, (_, i) => i + 1);

  // Group WBS by epic
  const epicIds = [...new Set(wbs.map((w) => w.epic_id))];
  const epics = plan?.epics ?? [];

  const EPIC_COLORS = ["bg-blue-500", "bg-green-500", "bg-purple-500", "bg-orange-500", "bg-pink-500", "bg-cyan-500"];

  return (
    <div className="max-w-full mx-auto space-y-6">
      <PresetSelector plans={planEstimates} selected={selectedPreset} onSelect={onSelectPreset} />

      {plan && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-border px-4 py-2.5 bg-accent/20">
            <GanttChart className="h-4 w-4 text-primary" />
            <span className="text-sm font-bold text-foreground">
              プロジェクトタイムライン — {plan.duration_weeks}週間
            </span>
            <div className="flex-1" />
            <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
              <span><Clock className="h-3 w-3 inline mr-1" />{plan.total_effort_hours}h</span>
              <span><DollarSign className="h-3 w-3 inline mr-1" />${plan.total_cost_usd.toFixed(0)}</span>
            </div>
          </div>

          {/* Gantt body */}
          <div className="overflow-x-auto">
            <div style={{ minWidth: Math.max(600, totalWeeks * 100 + 200) }}>
              {/* Week headers */}
              <div className="flex border-b border-border">
                <div className="w-48 shrink-0 px-3 py-1.5 text-[10px] font-medium text-muted-foreground border-r border-border">
                  タスク
                </div>
                <div className="flex-1 flex">
                  {weekMarkers.map((w) => (
                    <div key={w} className="flex-1 px-1 py-1.5 text-center text-[10px] text-muted-foreground border-r border-border last:border-r-0">
                      W{w}
                    </div>
                  ))}
                </div>
              </div>

              {/* Rows grouped by epic */}
              {epicIds.map((epicId, groupIdx) => {
                const epic = epics.find((e) => e.id === epicId);
                const items = wbs.filter((w) => w.epic_id === epicId);
                const barColor = EPIC_COLORS[groupIdx % EPIC_COLORS.length];

                return (
                  <div key={epicId}>
                    {/* Epic group header */}
                    <div className="flex border-b border-border bg-accent/10">
                      <div className="w-48 shrink-0 px-3 py-1.5 flex items-center gap-1.5">
                        <span className={cn("h-2 w-2 rounded-full", barColor)} />
                        <span className="text-[11px] font-bold text-foreground truncate">{epic?.name ?? epicId}</span>
                      </div>
                      <div className="flex-1" />
                    </div>

                    {/* Items */}
                    {items.map((item) => {
                      const leftPct = (item.start_day / maxDay) * 100;
                      const widthPct = Math.max((item.duration_days / maxDay) * 100, 2);
                      const hasDeps = item.depends_on.length > 0;

                      return (
                        <div key={item.id} className="flex border-b border-border last:border-b-0 hover:bg-accent/10 transition-colors">
                          <div className="w-48 shrink-0 px-3 py-2 flex items-center gap-2">
                            {item.assignee_type === "agent" ? (
                              <Bot className="h-3 w-3 text-blue-500 shrink-0" />
                            ) : (
                              <Users className="h-3 w-3 text-orange-500 shrink-0" />
                            )}
                            <div className="min-w-0">
                              <p className="text-[11px] text-foreground truncate">{item.title}</p>
                              <p className="text-[9px] text-muted-foreground truncate">{item.assignee} · {item.effort_hours}h</p>
                            </div>
                          </div>
                          <div className="flex-1 relative py-2">
                            {/* Grid lines for weeks */}
                            <div className="absolute inset-0 flex">
                              {weekMarkers.map((w) => (
                                <div key={w} className="flex-1 border-r border-border/30 last:border-r-0" />
                              ))}
                            </div>
                            {/* Gantt bar */}
                            <div
                              className={cn("absolute top-2.5 h-4 rounded-full flex items-center px-1.5", barColor, "opacity-80")}
                              style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                              title={`${item.title}: Day ${item.start_day}–${item.start_day + item.duration_days} (${item.effort_hours}h)`}
                            >
                              <span className="text-[8px] text-white font-medium truncate">{item.duration_days}d</span>
                            </div>
                            {/* Dependency indicator */}
                            {hasDeps && (
                              <div className="absolute top-1 right-1">
                                <ChevronRight className="h-2.5 w-2.5 text-muted-foreground/50" />
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-4 border-t border-border px-4 py-2">
            {epicIds.map((epicId, i) => {
              const epic = epics.find((e) => e.id === epicId);
              return (
                <div key={epicId} className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <span className={cn("h-2 w-2 rounded-full", EPIC_COLORS[i % EPIC_COLORS.length])} />
                  {epic?.name ?? epicId}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
