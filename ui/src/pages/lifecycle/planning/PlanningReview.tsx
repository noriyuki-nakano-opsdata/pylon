import { useCallback, useMemo, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  BarChart3,
  BookOpen,
  Briefcase,
  Check,
  ChevronRight,
  ChevronsUpDown,
  CircleDot,
  FileText,
  FolderOpen,
  Frown,
  MapPin,
  Meh,
  Network,
  Palette,
  Route,
  Shield,
  Smile,
  Sparkles,
  Target,
  UserCheck,
  Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  selectPlanningReviewViewModel,
  type PlanningReviewTab,
} from "@/lifecycle/selectors";
import type {
  Actor,
  AnalysisResult,
  DesignTokenAnalysis,
  IAAnalysis,
  IANode,
  JobStory,
  JourneyPhase,
  JourneyTouchpoint,
  KanoFeature,
  Role,
  UseCase,
  UserJourneyMap,
} from "@/types/lifecycle";

const KANO_CAT_STYLE: Record<string, { fill: string; stroke: string; text: string; label: string }> = {
  "must-be": { fill: "rgba(239,68,68,0.25)", stroke: "rgba(239,68,68,0.7)", text: "#f87171", label: "当たり前" },
  "one-dimensional": { fill: "rgba(59,130,246,0.25)", stroke: "rgba(59,130,246,0.7)", text: "#60a5fa", label: "一元的" },
  attractive: { fill: "rgba(34,197,94,0.25)", stroke: "rgba(34,197,94,0.7)", text: "#4ade80", label: "魅力" },
  indifferent: { fill: "rgba(148,163,184,0.2)", stroke: "rgba(148,163,184,0.5)", text: "#94a3b8", label: "無関心" },
  reverse: { fill: "rgba(168,85,247,0.25)", stroke: "rgba(168,85,247,0.7)", text: "#a855f7", label: "逆転" },
};
const KANO_CHART_WIDTH = 720;
const KANO_CHART_HEIGHT = 400;
const KANO_CHART_PADDING = { top: 30, right: 30, bottom: 50, left: 60 } as const;
const KANO_COST_BASE: Record<string, number> = { low: 0.15, medium: 0.5, high: 0.85 };

type KanoSortKey = "index" | "feature" | "category" | "delight" | "cost";
type SortDir = "asc" | "desc";
const COST_ORDER: Record<string, number> = { low: 0, medium: 1, high: 2 };
const REVIEW_TAB_ICONS = {
  overview: BarChart3,
  persona: Users,
  journey: Route,
  jtbd: Briefcase,
  kano: BarChart3,
  stories: BookOpen,
  actors: UserCheck,
  usecases: FileText,
  ia: Network,
  "design-tokens": Palette,
} as const;

const ACTOR_TYPE_STYLE: Record<string, { bg: string; text: string; label: string; icon: typeof Users }> = {
  primary: { bg: "bg-primary/15 border-primary/30", text: "text-primary", label: "プライマリ", icon: Users },
  secondary: { bg: "bg-amber-500/15 border-amber-500/30", text: "text-amber-400", label: "セカンダリ", icon: UserCheck },
  external_system: { bg: "bg-purple-500/15 border-purple-500/30", text: "text-purple-400", label: "外部システム", icon: Network },
};

const PHASE_LABELS: Record<JourneyPhase, string> = {
  awareness: "認知",
  consideration: "検討",
  acquisition: "導入",
  usage: "利用",
  advocacy: "推奨",
};
const PHASE_COLORS: Record<JourneyPhase, string> = {
  awareness: "bg-blue-500/20 border-blue-500/40",
  consideration: "bg-amber-500/20 border-amber-500/40",
  acquisition: "bg-green-500/20 border-green-500/40",
  usage: "bg-purple-500/20 border-purple-500/40",
  advocacy: "bg-pink-500/20 border-pink-500/40",
};

const JTBD_COLORS: Record<JobStory["priority"], { badge: string; border: string }> = {
  core: { badge: "bg-destructive/20 text-destructive", border: "border-destructive/30 bg-destructive/5" },
  supporting: { badge: "bg-primary/20 text-primary", border: "border-primary/30 bg-primary/5" },
  aspirational: { badge: "bg-success/20 text-success", border: "border-success/30 bg-success/5" },
};

const IA_PRIORITY_COLORS: Record<IANode["priority"], string> = {
  primary: "bg-primary/20 text-primary border-primary/40",
  secondary: "bg-amber-500/20 text-amber-500 border-amber-500/40",
  utility: "bg-muted text-muted-foreground border-border",
};
const NAV_MODEL_LABELS: Record<IAAnalysis["navigation_model"], string> = {
  hierarchical: "階層型",
  flat: "フラット型",
  "hub-and-spoke": "ハブ＆スポーク型",
  matrix: "マトリクス型",
};

function KanoBubbleChart({
  features,
  hoveredIdx,
  onHover,
}: {
  features: KanoFeature[];
  hoveredIdx: number | null;
  onHover: (i: number | null) => void;
}) {
  const W = KANO_CHART_WIDTH;
  const H = KANO_CHART_HEIGHT;
  const pad = KANO_CHART_PADDING;
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const positions = useMemo(() => {
    const placed: { x: number; y: number }[] = [];
    return features.map((f) => {
      let x = KANO_COST_BASE[f.implementation_cost] ?? 0.5;
      let y = f.user_delight;
      const R = 22;
      for (let attempt = 0; attempt < 20; attempt++) {
        const px = pad.left + x * plotW;
        const py = pad.top + (1 - y) * plotH;
        const overlap = placed.some((p) => Math.hypot(p.x - px, p.y - py) < R * 1.6);
        if (!overlap) {
          placed.push({ x: px, y: py });
          return { x: px, y: py };
        }
        const angle = (attempt * 137.5 * Math.PI) / 180;
        const dist = 6 + attempt * 4;
        x = (KANO_COST_BASE[f.implementation_cost] ?? 0.5) + (Math.cos(angle) * dist) / plotW;
        y = f.user_delight + (Math.sin(angle) * dist) / plotH;
        x = Math.max(0.03, Math.min(0.97, x));
        y = Math.max(0.02, Math.min(0.98, y));
      }
      const px = pad.left + x * plotW;
      const py = pad.top + (1 - y) * plotH;
      placed.push({ x: px, y: py });
      return { x: px, y: py };
    });
  }, [features, pad.left, pad.top, plotH, plotW]);

  const quadrants = [
    { x: pad.left + plotW * 0.08, y: pad.top + plotH * 0.08, sub: "即効性あり" },
    { x: pad.left + plotW * 0.75, y: pad.top + plotH * 0.08, sub: "戦略的" },
  ];

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-4 text-sm font-medium text-foreground">KANO バブルチャート</h3>
      <div className="flex justify-center">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-3xl" style={{ aspectRatio: `${W}/${H}` }}>
          <defs>
            <filter id="tooltip-shadow" x="-10%" y="-10%" width="120%" height="130%">
              <feDropShadow dx="0" dy="4" stdDeviation="6" floodColor="rgba(0,0,0,0.5)" />
            </filter>
          </defs>
          <rect x={pad.left} y={pad.top} width={plotW} height={plotH} rx={8} fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.08)" />

          {[0.25, 0.5, 0.75].map((v) => (
            <g key={`g-${v}`}>
              <line x1={pad.left} y1={pad.top + (1 - v) * plotH} x2={pad.left + plotW} y2={pad.top + (1 - v) * plotH} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
              <line x1={pad.left + v * plotW} y1={pad.top} x2={pad.left + v * plotW} y2={pad.top + plotH} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
            </g>
          ))}

          {quadrants.map((q, i) => (
            <g key={i}>
              <text x={q.x} y={q.y} fill="rgba(255,255,255,0.15)" fontSize={11} fontWeight={600}>
                {q.sub}
              </text>
            </g>
          ))}

          {[
            { x: 0.15, label: "低" },
            { x: 0.5, label: "中" },
            { x: 0.85, label: "高" },
          ].map((a) => (
            <text key={a.label} x={pad.left + a.x * plotW} y={H - 12} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize={11}>
              {a.label}
            </text>
          ))}
          <text x={W / 2} y={H} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={12} fontWeight={500}>
            実装コスト
          </text>

          {[0, 0.25, 0.5, 0.75, 1.0].map((v) => (
            <text key={v} x={pad.left - 8} y={pad.top + (1 - v) * plotH + 4} textAnchor="end" fill="rgba(255,255,255,0.4)" fontSize={10}>
              {v.toFixed(1)}
            </text>
          ))}
          <text
            x={14}
            y={pad.top + plotH / 2}
            textAnchor="middle"
            fill="rgba(255,255,255,0.5)"
            fontSize={12}
            fontWeight={500}
            transform={`rotate(-90, 14, ${pad.top + plotH / 2})`}
          >
            ユーザー満足度
          </text>

          {features.map((f, i) => {
            const pos = positions[i];
            const style = KANO_CAT_STYLE[f.category] ?? KANO_CAT_STYLE.indifferent;
            const isHovered = hoveredIdx === i;
            const r = isHovered ? 24 : 18;
            return (
              <g key={i} onMouseEnter={() => onHover(i)} onMouseLeave={() => onHover(null)} style={{ cursor: "pointer", transition: "transform 0.15s ease" }}>
                {isHovered && (
                  <circle cx={pos.x} cy={pos.y} r={r + 8} fill={style.fill} opacity={0.4}>
                    <animate attributeName="r" from={String(r + 4)} to={String(r + 10)} dur="0.8s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.4" to="0.1" dur="0.8s" repeatCount="indefinite" />
                  </circle>
                )}
                <circle cx={pos.x} cy={pos.y} r={r} fill={style.fill} stroke={style.stroke} strokeWidth={isHovered ? 2.5 : 1.5} style={{ transition: "r 0.15s ease, stroke-width 0.15s ease" }} />
                <text x={pos.x} y={pos.y + 1} textAnchor="middle" dominantBaseline="central" fill={style.text} fontSize={isHovered ? 13 : 11} fontWeight={600}>
                  {i + 1}
                </text>
              </g>
            );
          })}

          {hoveredIdx !== null &&
            (() => {
              const f = features[hoveredIdx];
              const pos = positions[hoveredIdx];
              const style = KANO_CAT_STYLE[f.category] ?? KANO_CAT_STYLE.indifferent;
              const hasRationale = f.rationale && f.rationale.length > 0;
              const tooltipW = 240;
              const tooltipH = hasRationale ? 68 : 48;
              const tx = Math.min(Math.max(pos.x - tooltipW / 2, pad.left), W - pad.right - tooltipW);
              const ty = pos.y - 36 - tooltipH;
              const finalY = ty > pad.top ? ty : pos.y + 30;
              return (
                <g style={{ pointerEvents: "none" }}>
                  <rect x={tx} y={finalY} width={tooltipW} height={tooltipH} rx={8} fill="rgba(15,23,42,0.95)" stroke={style.stroke} strokeWidth={1.5} filter="url(#tooltip-shadow)" />
                  <text x={tx + 12} y={finalY + 18} fill="#e2e8f0" fontSize={12} fontWeight={600}>
                    {f.feature}
                  </text>
                  <text x={tx + 12} y={finalY + 36} fill="rgba(148,163,184,0.8)" fontSize={10}>
                    {style.label} · 満足度 {f.user_delight.toFixed(1)} · コスト {f.implementation_cost}
                  </text>
                  {hasRationale && (
                    <text x={tx + 12} y={finalY + 54} fill="rgba(148,163,184,0.6)" fontSize={9}>
                      {f.rationale.length > 40 ? `${f.rationale.slice(0, 40)}…` : f.rationale}
                    </text>
                  )}
                </g>
              );
            })()}

          {Object.entries(KANO_CAT_STYLE)
            .filter(([k]) => features.some((f) => f.category === k))
            .map(([, style], i) => (
              <g key={style.label} transform={`translate(${pad.left + i * 140}, ${pad.top - 18})`}>
                <circle cx={6} cy={0} r={5} fill={style.fill} stroke={style.stroke} strokeWidth={1.5} />
                <text x={16} y={4} fill="rgba(255,255,255,0.6)" fontSize={11}>
                  {style.label}
                </text>
              </g>
            ))}
        </svg>
      </div>
    </div>
  );
}

export function ReviewContent({ analysis }: { analysis: AnalysisResult }) {
  const reviewVm = selectPlanningReviewViewModel(analysis);
  const [tab, setTab] = useState<PlanningReviewTab>("overview");
  const [kanoHovered, setKanoHovered] = useState<number | null>(null);
  const [kanoSort, setKanoSort] = useState<{ key: KanoSortKey; dir: SortDir }>({ key: "index", dir: "asc" });

  const toggleKanoSort = useCallback((key: KanoSortKey) => {
    setKanoSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }, []);

  const sortedKanoFeatures = useMemo(() => {
    const items = analysis.kano_features.map((f, i) => ({ ...f, _origIdx: i }));
    const { key, dir } = kanoSort;
    items.sort((a, b) => {
      let cmp = 0;
      switch (key) {
        case "index":
          cmp = a._origIdx - b._origIdx;
          break;
        case "feature":
          cmp = a.feature.localeCompare(b.feature, "ja");
          break;
        case "category":
          cmp = a.category.localeCompare(b.category);
          break;
        case "delight":
          cmp = a.user_delight - b.user_delight;
          break;
        case "cost":
          cmp = (COST_ORDER[a.implementation_cost] ?? 1) - (COST_ORDER[b.implementation_cost] ?? 1);
          break;
      }
      return dir === "desc" ? -cmp : cmp;
    });
    return items;
  }, [analysis.kano_features, kanoSort]);

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-4 rounded-2xl border border-border bg-card p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] font-medium text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              企画統合
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">調査結果を実装可能な企画に圧縮</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                ペルソナ、ユースケース、KANO、IA を横断して、次のデザインフェーズに渡すスコープと判断材料を揃えます。
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:w-[26rem]">
            {reviewVm.heroStats.map((item) => (
              <div key={item.label} className="rounded-xl border border-border bg-background px-3 py-3 text-center">
                <p className="text-lg font-semibold text-foreground">{item.value}</p>
                <p className="text-[11px] text-muted-foreground">{item.label}</p>
              </div>
            ))}
          </div>
        </div>
        {reviewVm.focusSummary && (
          <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-primary/80">推奨フォーカス</p>
            <p className="mt-1 text-sm text-foreground">{reviewVm.focusSummary}</p>
          </div>
        )}
      </div>

      <div className="mb-4 -mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {reviewVm.reviewTabs.filter((item) => !item.hidden).map((item) => {
          const Icon = REVIEW_TAB_ICONS[item.key];
          return (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={cn(
                "shrink-0 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                tab === item.key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {item.label}
            </button>
          );
        })}
      </div>

      {tab === "overview" && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
            {reviewVm.overviewStats.map((item) => (
              <div key={item.label} className="rounded-xl border border-border bg-card p-4 text-center">
                <p className="text-2xl font-bold text-foreground">{item.value}</p>
                <p className="text-xs text-muted-foreground">{item.label}</p>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="mb-3 text-sm font-medium text-foreground">KANO分布</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              {reviewVm.kanoDistribution.map((item) => (
                <div key={item.label} className={cn("flex-1 rounded-lg p-3 text-center", item.color)}>
                  <p className="text-lg font-bold">{item.count}</p>
                  <p className="text-xs">{item.label}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            {analysis.recommendations.map((r, i) => {
              const isQuick = r.includes("Quick Win");
              const isStrategic = r.includes("Strategic");
              return (
                <div
                  key={i}
                  className={cn(
                    "rounded-lg border-2 p-3 text-sm text-foreground",
                    isQuick ? "border-success/30 bg-success/5" : isStrategic ? "border-primary/30 bg-primary/5" : "border-border",
                  )}
                >
                  {r}
                </div>
              );
            })}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="mb-3 text-sm font-medium text-foreground">判定テーブル</h3>
              <div className="space-y-2">
                {(analysis.feature_decisions ?? []).map((decision) => (
                  <div key={decision.feature} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium text-foreground">{decision.feature}</p>
                      <Badge variant={decision.selected ? "default" : "secondary"} className="text-[10px]">
                        {decision.selected ? "採用" : "保留"}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      不確実性 {(decision.uncertainty * 100).toFixed(0)}% · 裏付け {decision.supporting_claim_ids.length}
                    </p>
                    {!!decision.counterarguments.length && <p className="mt-1 text-[11px] text-muted-foreground">{decision.counterarguments[0]}</p>}
                    {!decision.selected && decision.rejection_reason && <p className="mt-1 text-[11px] text-muted-foreground">{decision.rejection_reason}</p>}
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="mb-3 text-sm font-medium text-foreground">仮説とレッドチームの発見</h3>
              <div className="space-y-2">
                {(analysis.assumptions ?? []).map((assumption) => (
                  <div key={assumption.id} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                    <p className="text-xs font-medium text-foreground">{assumption.statement}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{assumption.severity}</p>
                  </div>
                ))}
                {(analysis.red_team_findings ?? []).map((finding) => (
                  <div key={finding.id} className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2">
                    <p className="text-xs font-medium text-foreground">{finding.title}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{finding.recommendation}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="mb-3 text-sm font-medium text-foreground">トレーサビリティ</h3>
              <div className="space-y-2">
                {(analysis.traceability ?? []).map((item, index) => (
                  <div key={`${item.feature}-${index}`} className="rounded-lg border border-border/80 bg-background px-3 py-2 text-xs text-foreground">
                    <p>{item.feature}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      主張 {item.claim_id || "n/a"} → ユースケース {item.use_case_id || "n/a"} → マイルストーン {item.milestone_id || "n/a"}
                    </p>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="mb-3 text-sm font-medium text-foreground">ネガティブペルソナと中止基準</h3>
              <div className="space-y-2">
                {(analysis.negative_personas ?? []).map((persona) => (
                  <div key={persona.id} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                    <p className="text-xs font-medium text-foreground">{persona.name}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{persona.mitigation}</p>
                  </div>
                ))}
                {(analysis.kill_criteria ?? []).map((criterion) => (
                  <div key={criterion.id} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                    <p className="text-xs font-medium text-foreground">{criterion.condition}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{criterion.rationale}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === "persona" && (
        <div className="grid gap-4 lg:grid-cols-3">
          {analysis.personas.map((p, i) => (
            <div key={i} className="space-y-3 rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/20 font-bold text-primary">{p.name.charAt(0)}</div>
                <div>
                  <p className="font-medium text-foreground">{p.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {p.role} · {p.age_range}
                  </p>
                </div>
              </div>
              <p className="text-xs text-muted-foreground">{p.context}</p>
              {p.goals.map((g, j) => (
                <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                  <Check className="mt-0.5 h-3 w-3 shrink-0 text-success" />
                  {g}
                </p>
              ))}
              {p.frustrations.map((f, j) => (
                <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
                  {f}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}

      {tab === "kano" && (
        <div className="space-y-4">
          <KanoBubbleChart features={analysis.kano_features} hoveredIdx={kanoHovered} onHover={setKanoHovered} />
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <table className="min-w-[40rem] w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  {([
                    { key: "index" as KanoSortKey, label: "#", w: "w-10" },
                    { key: "feature" as KanoSortKey, label: "機能", w: "" },
                    { key: "category" as KanoSortKey, label: "カテゴリ", w: "w-36" },
                    { key: "delight" as KanoSortKey, label: "満足度", w: "w-32" },
                    { key: "cost" as KanoSortKey, label: "コスト", w: "w-24" },
                  ]).map((col) => (
                    <th key={col.key} className={cn("select-none px-3 py-2.5 text-left text-xs font-medium text-muted-foreground", col.w)}>
                      <button onClick={() => toggleKanoSort(col.key)} className="flex cursor-pointer items-center gap-1 transition-colors hover:text-foreground">
                        {col.label}
                        <ChevronsUpDown className={cn("h-3 w-3", kanoSort.key === col.key ? "text-primary" : "text-muted-foreground/40")} />
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sortedKanoFeatures.map((f) => {
                  const catColor: Record<string, string> = {
                    "must-be": "text-destructive",
                    "one-dimensional": "text-primary",
                    attractive: "text-success",
                    indifferent: "text-muted-foreground",
                    reverse: "text-purple-400",
                  };
                  const isHovered = kanoHovered === f._origIdx;
                  return (
                    <tr key={f._origIdx} onMouseEnter={() => setKanoHovered(f._origIdx)} onMouseLeave={() => setKanoHovered(null)} className={cn("cursor-default transition-colors", isHovered ? "bg-accent/50" : "hover:bg-muted/20")}>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{f._origIdx + 1}</td>
                      <td className="px-3 py-2.5">
                        <p className="font-medium text-foreground">{f.feature}</p>
                        {f.rationale && <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{f.rationale}</p>}
                      </td>
                      <td className={cn("px-3 py-2.5 text-xs font-medium capitalize", catColor[f.category])}>{f.category.replace("-", " ")}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-14 overflow-hidden rounded-full bg-muted">
                            <div
                              className={cn("h-full rounded-full transition-all", f.user_delight > 0.7 ? "bg-success" : f.user_delight > 0.4 ? "bg-primary" : "bg-amber-500")}
                              style={{ width: `${Math.max(f.user_delight * 100, 5)}%` }}
                            />
                          </div>
                          <span className="tabular-nums text-xs text-muted-foreground">{f.user_delight.toFixed(1)}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge variant="outline" className={cn("text-[10px] capitalize", f.implementation_cost === "high" ? "border-destructive/40 text-destructive" : f.implementation_cost === "low" ? "border-success/40 text-success" : "")}>
                          {f.implementation_cost}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "stories" && (
        <div className="max-w-3xl space-y-2">
          {analysis.user_stories.map((s, i) => {
            const color: Record<string, string> = {
              must: "bg-destructive/20 text-destructive",
              should: "bg-warning/20 text-warning",
              could: "bg-primary/20 text-primary",
              wont: "bg-muted text-muted-foreground",
            };
            return (
              <div key={i} className="flex items-start gap-2 rounded-lg border border-border bg-card p-3">
                <Badge className={cn("mt-0.5 shrink-0 border-0 text-[10px] uppercase", color[s.priority])}>{s.priority}</Badge>
                <div>
                  <p className="text-sm text-foreground">
                    {s.role} として、{s.action} したい
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">それにより {s.benefit}</p>
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

function DesignTokenContent({ tokens }: { tokens: DesignTokenAnalysis }) {
  const { style, colors, typography, effects, anti_patterns, rationale } = tokens;
  const colorEntries = Object.entries(colors).filter(([key]) => key !== "notes") as [string, string][];
  const colorLabels: Record<string, string> = {
    primary: "プライマリ",
    secondary: "セカンダリ",
    cta: "CTA",
    background: "背景",
    text: "テキスト",
  };

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border/40 bg-card/60 p-4">
        <p className="text-sm leading-relaxed text-muted-foreground">{rationale}</p>
      </div>

      <div className="space-y-3 rounded-lg border border-border/40 bg-card/60 p-4">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <Palette className="h-4 w-4 text-violet-400" />
          スタイル
        </h4>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-base font-medium">{style.name}</span>
          {style.keywords.map((kw) => (
            <Badge key={kw} variant="secondary" className="text-[10px]">
              {kw}
            </Badge>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-3 text-xs text-muted-foreground sm:grid-cols-3">
          <div>
            <span className="block font-medium text-foreground/70">適用先</span>
            {style.best_for || "—"}
          </div>
          <div>
            <span className="block font-medium text-foreground/70">パフォーマンス</span>
            {style.performance || "—"}
          </div>
          <div>
            <span className="block font-medium text-foreground/70">アクセシビリティ</span>
            {style.accessibility || "—"}
          </div>
        </div>
      </div>

      <div className="space-y-3 rounded-lg border border-border/40 bg-card/60 p-4">
        <h4 className="text-sm font-semibold">カラーパレット</h4>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {colorEntries.map(([key, hex]) => (
            <div key={key} className="space-y-1.5">
              <div className="h-16 cursor-pointer rounded-lg border border-border/30 transition-transform hover:scale-105" style={{ backgroundColor: hex }} title={hex} />
              <div className="text-center text-[10px]">
                <div className="font-medium text-foreground/80">{colorLabels[key] ?? key}</div>
                <div className="font-mono text-muted-foreground">{hex}</div>
              </div>
            </div>
          ))}
        </div>
        {colors.notes && <p className="mt-2 text-xs text-muted-foreground">{colors.notes}</p>}
      </div>

      <div className="space-y-3 rounded-lg border border-border/40 bg-card/60 p-4">
        <h4 className="text-sm font-semibold">タイポグラフィ</h4>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <span className="mb-1 block text-[10px] text-muted-foreground">見出し</span>
            <span className="text-lg font-semibold" style={{ fontFamily: typography.heading }}>
              {typography.heading}
            </span>
          </div>
          <div>
            <span className="mb-1 block text-[10px] text-muted-foreground">本文</span>
            <span className="text-lg" style={{ fontFamily: typography.body }}>
              {typography.body}
            </span>
          </div>
        </div>
        {typography.mood.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {typography.mood.map((m) => (
              <Badge key={m} variant="outline" className="text-[10px]">
                {m}
              </Badge>
            ))}
          </div>
        )}
        {typography.google_fonts_url && (
          <a href={typography.google_fonts_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-blue-400 hover:underline">
            Google Fonts で表示
          </a>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-2 rounded-lg border border-border/40 bg-card/60 p-4">
          <h4 className="flex items-center gap-1.5 text-sm font-semibold">
            <Sparkles className="h-3.5 w-3.5 text-amber-400" />
            エフェクト
          </h4>
          <ul className="space-y-1">
            {effects.map((e, i) => (
              <li key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Check className="h-3 w-3 shrink-0 text-green-400" />
                {e}
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-2 rounded-lg border border-border/40 bg-card/60 p-4">
          <h4 className="flex items-center gap-1.5 text-sm font-semibold">
            <AlertTriangle className="h-3.5 w-3.5 text-red-400" />
            アンチパターン
          </h4>
          <ul className="space-y-1">
            {anti_patterns.map((a, i) => (
              <li key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <AlertCircle className="h-3 w-3 shrink-0 text-red-400" />
                {a}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function ActorRoleContent({ actors, roles }: { actors: Actor[]; roles: Role[] }) {
  const [activeTab, setActiveTab] = useState<"actors" | "roles">("actors");

  return (
    <div className="space-y-4">
      <div className="flex gap-1">
        {([
          { key: "actors" as const, label: "アクター", icon: Users, count: actors.length },
          { key: "roles" as const, label: "ロール", icon: Shield, count: roles.length },
        ]).map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors",
              activeTab === t.key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <t.icon className="h-3.5 w-3.5" />
            {t.label}
            <span className={cn("ml-1 rounded-full px-1.5 py-0.5 text-[10px]", activeTab === t.key ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground")}>{t.count}</span>
          </button>
        ))}
      </div>

      {activeTab === "actors" && (
        <div className="grid gap-4 lg:grid-cols-2">
          {actors.map((a, i) => {
            const style = ACTOR_TYPE_STYLE[a.type] ?? ACTOR_TYPE_STYLE.primary;
            return (
              <div key={i} className={cn("space-y-3 rounded-xl border p-5", style.bg)}>
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
                  <Badge variant="outline" className={cn("text-[10px]", style.text)}>
                    {style.label}
                  </Badge>
                </div>
                {a.goals.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">ゴール</p>
                    <div className="space-y-1">
                      {a.goals.map((g, j) => (
                        <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                          <Target className="mt-0.5 h-3 w-3 shrink-0 text-success" />
                          {g}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
                {a.interactions.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">インタラクション</p>
                    <div className="flex flex-wrap gap-1">
                      {a.interactions.map((interaction, j) => (
                        <Badge key={j} variant="outline" className="bg-muted/30 text-[10px]">
                          {interaction}
                        </Badge>
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
            <div key={i} className="space-y-3 rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/20">
                  <Shield className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="font-medium text-foreground">{r.name}</p>
                  {r.related_actors.length > 0 && <p className="text-xs text-muted-foreground">関連アクター: {r.related_actors.join(", ")}</p>}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">責務</p>
                  <div className="space-y-1">
                    {r.responsibilities.map((resp, j) => (
                      <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                        <Check className="mt-0.5 h-3 w-3 shrink-0 text-success" />
                        {resp}
                      </p>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">権限</p>
                  <div className="space-y-1">
                    {r.permissions.map((perm, j) => (
                      <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                        <Shield className="mt-0.5 h-3 w-3 shrink-0 text-amber-400" />
                        {perm}
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

function UseCaseContent({ useCases }: { useCases: UseCase[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const priorityStyle: Record<string, string> = {
    must: "bg-destructive/20 text-destructive",
    should: "bg-amber-500/20 text-amber-400",
    could: "bg-primary/20 text-primary",
  };

  const grouped = useMemo(() => {
    const cats = new Map<string, Map<string, UseCase[]>>();
    for (const uc of useCases) {
      const category = uc.category || "未分類";
      const sub = uc.sub_category || "その他";
      if (!cats.has(category)) cats.set(category, new Map());
      const subMap = cats.get(category)!;
      if (!subMap.has(sub)) subMap.set(sub, []);
      subMap.get(sub)!.push(uc);
    }
    return cats;
  }, [useCases]);

  const renderUseCase = (uc: UseCase) => {
    const isOpen = expanded.has(uc.id);
    return (
      <div key={uc.id} className="overflow-hidden rounded-xl border border-border bg-card">
        <button onClick={() => toggle(uc.id)} className="flex w-full cursor-pointer items-center gap-3 p-4 text-left transition-colors hover:bg-muted/20">
          <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">{uc.id}</span>
              <p className="truncate font-medium text-foreground">{uc.title}</p>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              <Users className="mr-1 inline h-3 w-3" />
              {uc.actor}
            </p>
          </div>
          <Badge className={cn("shrink-0 border-0 text-[10px] uppercase", priorityStyle[uc.priority])}>{uc.priority}</Badge>
        </button>
        {isOpen && (
          <div className="space-y-4 border-t border-border bg-muted/5 px-4 py-4">
            {uc.preconditions.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">事前条件</p>
                <div className="space-y-1">
                  {uc.preconditions.map((pre, j) => (
                    <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                      <CircleDot className="mt-0.5 h-3 w-3 shrink-0 text-amber-400" />
                      {pre}
                    </p>
                  ))}
                </div>
              </div>
            )}
            <div>
              <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">メインフロー</p>
              <div className="space-y-1.5">
                {uc.main_flow.map((step, j) => (
                  <div key={j} className="flex items-start gap-2 text-xs text-foreground">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">{j + 1}</span>
                    <span className="pt-0.5">{step}</span>
                  </div>
                ))}
              </div>
            </div>
            {uc.alternative_flows?.length ? (
              <div>
                <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">代替フロー</p>
                {uc.alternative_flows.map((af, j) => (
                  <div key={j} className="mb-2 rounded-lg border border-border bg-card p-3">
                    <p className="mb-1.5 text-xs font-medium text-amber-400">
                      <AlertTriangle className="mr-1 inline h-3 w-3" />
                      {af.condition}
                    </p>
                    <div className="ml-4 space-y-1">
                      {af.steps.map((step, k) => (
                        <p key={k} className="text-xs text-muted-foreground">
                          {k + 1}. {step}
                        </p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
            {uc.postconditions.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">事後条件</p>
                <div className="space-y-1">
                  {uc.postconditions.map((post, j) => (
                    <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                      <Check className="mt-0.5 h-3 w-3 shrink-0 text-success" />
                      {post}
                    </p>
                  ))}
                </div>
              </div>
            )}
            {uc.related_stories?.length ? (
              <div className="flex flex-wrap gap-1">
                <span className="mr-1 text-[10px] text-muted-foreground">関連ストーリー:</span>
                {uc.related_stories.map((story, j) => (
                  <Badge key={j} variant="outline" className="text-[10px]">
                    {story}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {(["must", "should", "could"] as const).map((priority) => {
          const count = useCases.filter((uc) => uc.priority === priority).length;
          const labels: Record<string, string> = { must: "Must", should: "Should", could: "Could" };
          return (
            <div key={priority} className={cn("flex-1 rounded-lg border p-3 text-center", priorityStyle[priority])}>
              <p className="text-lg font-bold">{count}</p>
              <p className="text-xs">{labels[priority]}</p>
            </div>
          );
        })}
      </div>

      {Array.from(grouped.entries()).map(([category, subMap]) => (
        <div key={category} className="space-y-3">
          <div className="flex items-center gap-2 pt-2">
            <FolderOpen className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-bold text-foreground">{category}</h3>
            <span className="text-[10px] text-muted-foreground">({Array.from(subMap.values()).flat().length})</span>
          </div>
          {Array.from(subMap.entries()).map(([sub, cases]) => (
            <div key={sub} className="ml-4 space-y-2">
              <div className="flex items-center gap-1.5">
                <div className="h-px max-w-3 flex-1 bg-border" />
                <span className="text-[11px] font-medium text-muted-foreground">{sub}</span>
                <span className="text-[10px] text-muted-foreground/60">({cases.length})</span>
                <div className="h-px flex-1 bg-border" />
              </div>
              {cases.map(renderUseCase)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

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
      {journeys.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {journeys.map((j, i) => (
            <button
              key={i}
              onClick={() => setActivePersona(i)}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors",
                i === activePersona ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">{j.persona_name.charAt(0)}</div>
              {j.persona_name}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <div className="min-w-[48rem] overflow-hidden">
          <div className="grid grid-cols-5 border-b border-border">
            {phases.map((phase) => (
              <div key={phase} className={cn("border-r border-border px-3 py-2.5 text-center text-xs font-bold last:border-r-0", PHASE_COLORS[phase])}>
                {PHASE_LABELS[phase]}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-5 border-b border-border">
            {phases.map((phase) => {
              const tp = journey.touchpoints.find((t) => t.phase === phase);
              return (
                <div key={phase} className="flex items-center justify-center border-r border-border py-3 last:border-r-0">
                  {tp ? <EmotionIcon emotion={tp.emotion} /> : <Meh className="h-4 w-4 text-muted-foreground/30" />}
                </div>
              );
            })}
          </div>

          <div className="grid grid-cols-5 border-b border-border">
            {phases.map((phase) => {
              const tp = journey.touchpoints.find((t) => t.phase === phase);
              return (
                <div key={phase} className="border-r border-border px-3 py-3 last:border-r-0">
                  <p className="mb-1 text-[10px] font-medium text-muted-foreground">行動</p>
                  <p className="text-xs text-foreground">{tp?.action || "—"}</p>
                </div>
              );
            })}
          </div>

          <div className="grid grid-cols-5 border-b border-border">
            {phases.map((phase) => {
              const tp = journey.touchpoints.find((t) => t.phase === phase);
              return (
                <div key={phase} className="border-r border-border px-3 py-3 last:border-r-0">
                  <p className="mb-1 text-[10px] font-medium text-muted-foreground">タッチポイント</p>
                  <p className="flex items-start gap-1 text-xs text-foreground">
                    <MapPin className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                    {tp?.touchpoint || "—"}
                  </p>
                </div>
              );
            })}
          </div>

          <div className="grid grid-cols-5 border-b border-border">
            {phases.map((phase) => {
              const tp = journey.touchpoints.find((t) => t.phase === phase);
              return (
                <div key={phase} className="border-r border-border px-3 py-3 last:border-r-0">
                  {tp?.pain_point && (
                    <>
                      <p className="mb-1 text-[10px] font-medium text-destructive/80">ペインポイント</p>
                      <p className="text-xs text-destructive/90">{tp.pain_point}</p>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          <div className="grid grid-cols-5">
            {phases.map((phase) => {
              const tp = journey.touchpoints.find((t) => t.phase === phase);
              return (
                <div key={phase} className="border-r border-border px-3 py-3 last:border-r-0">
                  {tp?.opportunity && (
                    <>
                      <p className="mb-1 text-[10px] font-medium text-green-500/80">機会</p>
                      <p className="text-xs text-green-500/90">{tp.opportunity}</p>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

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
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {sections.map((section) => (
          <div key={section.key} className={cn("rounded-xl border p-4 text-center", JTBD_COLORS[section.key].border)}>
            <p className="text-2xl font-bold text-foreground">{grouped[section.key].length}</p>
            <p className="text-xs text-muted-foreground">{section.label}</p>
          </div>
        ))}
      </div>

      {sections.map((section) => {
        const items = grouped[section.key];
        if (items.length === 0) return null;
        return (
          <div key={section.key}>
            <h3 className="mb-1 text-sm font-bold text-foreground">{section.label}</h3>
            <p className="mb-3 text-xs text-muted-foreground">{section.desc}</p>
            <div className="space-y-3">
              {items.map((story, i) => (
                <div key={i} className={cn("space-y-2 rounded-lg border p-4", JTBD_COLORS[section.key].border)}>
                  <div className="space-y-1">
                    <p className="text-sm text-foreground">
                      <span className="font-medium text-muted-foreground">When</span> {story.situation}
                    </p>
                    <p className="text-sm text-foreground">
                      <span className="font-medium text-muted-foreground">I want to</span> {story.motivation}
                    </p>
                    <p className="text-sm text-foreground">
                      <span className="font-medium text-muted-foreground">So I can</span> {story.outcome}
                    </p>
                  </div>
                  {story.related_features.length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {story.related_features.map((feature, j) => (
                        <Badge key={j} variant="outline" className="text-[10px]">
                          {feature}
                        </Badge>
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

function IANodeTree({ node, depth = 0 }: { node: IANode; depth?: number }) {
  return (
    <div className={cn("border-l-2 pl-3", depth === 0 ? "border-primary/40" : "border-border/50")} style={{ marginLeft: depth > 0 ? 12 : 0 }}>
      <div className="flex items-center gap-2 py-1.5">
        <Badge className={cn("shrink-0 border text-[10px]", IA_PRIORITY_COLORS[node.priority])}>{node.priority}</Badge>
        <span className="text-sm font-medium text-foreground">{node.label}</span>
        {node.description && <span className="truncate text-xs text-muted-foreground">— {node.description}</span>}
      </div>
      {node.children?.map((child) => (
        <IANodeTree key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

function IAContent({ ia }: { ia: IAAnalysis }) {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3">
          <Network className="h-4 w-4 text-primary" />
          <div>
            <p className="text-[10px] text-muted-foreground">ナビゲーションモデル</p>
            <p className="text-sm font-bold text-foreground">{NAV_MODEL_LABELS[ia.navigation_model]}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3">
          <Route className="h-4 w-4 text-primary" />
          <div>
            <p className="text-[10px] text-muted-foreground">主要パス</p>
            <p className="text-sm font-bold text-foreground">{ia.key_paths.length} フロー</p>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 flex items-center gap-2 text-sm font-bold text-foreground">
          <Network className="h-4 w-4 text-primary" />
          サイトマップ
        </h3>
        <div className="space-y-1">
          {ia.site_map.map((node) => (
            <IANodeTree key={node.id} node={node} />
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 flex items-center gap-2 text-sm font-bold text-foreground">
          <Route className="h-4 w-4 text-primary" />
          主要ユーザーフロー
        </h3>
        <div className="space-y-4">
          {ia.key_paths.map((path, i) => (
            <div key={i}>
              <p className="mb-2 text-xs font-medium text-foreground">{path.name}</p>
              <div className="flex flex-wrap items-center gap-1">
                {path.steps.map((step, j) => (
                  <div key={j} className="flex items-center gap-1">
                    <span className="rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">{step}</span>
                    {j < path.steps.length - 1 && <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
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
