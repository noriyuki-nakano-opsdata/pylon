import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  planningActionVariants,
  planningBodyLabelClassName,
  planningChipVariants,
  planningDataValueClassName,
  planningDetailCardVariants,
  planningEyebrowClassName,
  planningMetricTileVariants,
  planningMicroLabelClassName,
  planningMutedCopyClassName,
  planningSectionTitleClassName,
  planningSoftBadgeVariants,
  planningSurfaceVariants,
  planningTabVariants,
} from "@/lifecycle/planningTheme";
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
const KANO_COST_LABELS: Record<string, string> = { low: "低", medium: "中", high: "高" };
const KANO_CATEGORY_HELP: Record<string, string> = {
  "must-be": "無いと不満が大きい基礎品質です。",
  "one-dimensional": "増やすほど満足度が素直に伸びる領域です。",
  attractive: "あると驚きが生まれる魅力要素です。",
  indifferent: "増やしても体験改善が限定的な領域です。",
  reverse: "増やすほど逆効果になりうる要素です。",
};
const PROFICIENCY_LABELS: Record<string, string> = { high: "高い", medium: "中程度", low: "低い" };
const SEVERITY_TEXT_LABELS: Record<string, string> = { critical: "重大", high: "高", medium: "中", low: "低" };
const USE_CASE_PRIORITY_LABELS: Record<string, string> = { must: "必須", should: "推奨", could: "任意" };

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

const ACTOR_TYPE_STYLE: Record<string, { tone: "accent" | "warning" | "default"; accent: string; label: string; icon: typeof Users }> = {
  primary: { tone: "accent", accent: "text-primary", label: "プライマリ", icon: Users },
  secondary: { tone: "warning", accent: "text-[color:var(--planning-warning-strong)]", label: "セカンダリ", icon: UserCheck },
  external_system: { tone: "default", accent: "text-[color:var(--planning-text-soft)]", label: "外部システム", icon: Network },
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

const JTBD_COLORS: Record<JobStory["priority"], { tone: "danger" | "accent" | "success" }> = {
  core: { tone: "danger" },
  supporting: { tone: "accent" },
  aspirational: { tone: "success" },
};

const RISK_SEVERITY_STYLE: Record<string, { badge: string; card: string; label: string }> = {
  critical: {
    badge: planningChipVariants({ tone: "danger" }),
    card: planningSurfaceVariants({ tone: "danger", padding: "md" }),
    label: "重大",
  },
  high: {
    badge: planningChipVariants({ tone: "warning" }),
    card: planningSurfaceVariants({ tone: "warning", padding: "md" }),
    label: "高",
  },
  medium: {
    badge: planningChipVariants({ tone: "accent" }),
    card: planningSurfaceVariants({ tone: "accent", padding: "md" }),
    label: "中",
  },
  low: {
    badge: planningChipVariants({ tone: "default" }),
    card: planningSurfaceVariants({ tone: "inset", padding: "md" }),
    label: "低",
  },
};

const RECOMMENDATION_PRIORITY_STYLE: Record<string, { badge: string; card: string; label: string }> = {
  critical: {
    badge: planningChipVariants({ tone: "danger" }),
    card: planningSurfaceVariants({ tone: "danger", padding: "md" }),
    label: "最優先",
  },
  high: {
    badge: planningChipVariants({ tone: "accent" }),
    card: planningSurfaceVariants({ tone: "accent", padding: "md" }),
    label: "高",
  },
  medium: {
    badge: planningChipVariants({ tone: "warning" }),
    card: planningSurfaceVariants({ tone: "warning", padding: "md" }),
    label: "中",
  },
  low: {
    badge: planningChipVariants({ tone: "default" }),
    card: planningSurfaceVariants({ tone: "inset", padding: "md" }),
    label: "低",
  },
};

const IA_PRIORITY_STYLE: Record<IANode["priority"], { label: string; tone: "accent" | "warning" | "default" }> = {
  primary: { label: "主要", tone: "accent" },
  secondary: { label: "補助", tone: "warning" },
  utility: { label: "補助線", tone: "default" },
};
const NAV_MODEL_LABELS: Record<IAAnalysis["navigation_model"], string> = {
  hierarchical: "階層型",
  flat: "フラット型",
  "hub-and-spoke": "ハブ＆スポーク型",
  matrix: "マトリクス型",
};

function KanoBubbleChart({
  features,
  activeIdx,
  tooltipIdx,
  onHover,
  onSelect,
}: {
  features: KanoFeature[];
  activeIdx: number | null;
  tooltipIdx: number | null;
  onHover: (i: number | null) => void;
  onSelect: (i: number) => void;
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
    <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
      <h3 className={cn("mb-4", planningSectionTitleClassName)}>KANO バブルチャート</h3>
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
            const isActive = activeIdx === i;
            const r = isActive ? 24 : 18;
            return (
              <g
                key={i}
                tabIndex={0}
                role="button"
                aria-label={`${f.feature} の詳細を表示`}
                onMouseEnter={() => onHover(i)}
                onMouseLeave={() => onHover(null)}
                onFocus={() => onSelect(i)}
                onBlur={() => onHover(null)}
                onClick={() => onSelect(i)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(i);
                  }
                }}
                style={{ cursor: "pointer", transition: "transform 0.15s ease" }}
              >
                {isActive && (
                  <circle cx={pos.x} cy={pos.y} r={r + 8} fill={style.fill} opacity={0.4}>
                    <animate attributeName="r" from={String(r + 4)} to={String(r + 10)} dur="0.8s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.4" to="0.1" dur="0.8s" repeatCount="indefinite" />
                  </circle>
                )}
                <circle cx={pos.x} cy={pos.y} r={r} fill={style.fill} stroke={style.stroke} strokeWidth={isActive ? 2.5 : 1.5} style={{ transition: "r 0.15s ease, stroke-width 0.15s ease" }} />
                <text x={pos.x} y={pos.y + 1} textAnchor="middle" dominantBaseline="central" fill={style.text} fontSize={isActive ? 13 : 11} fontWeight={600}>
                  {i + 1}
                </text>
              </g>
            );
          })}

          {tooltipIdx !== null &&
            (() => {
              const f = features[tooltipIdx];
              const pos = positions[tooltipIdx];
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

export function ReviewContent({
  analysis,
  handoffNotice = null,
  planningGuardrails = [],
  onContinue,
  continueLabel = "デザイン比較へ",
  requiresDecisionConfirmation = false,
  decisionConfirmed = true,
  onDecisionConfirmedChange,
}: {
  analysis: AnalysisResult;
  handoffNotice?: string | null;
  planningGuardrails?: string[];
  onContinue?: (() => void) | undefined;
  continueLabel?: string;
  requiresDecisionConfirmation?: boolean;
  decisionConfirmed?: boolean;
  onDecisionConfirmedChange?: ((confirmed: boolean) => void) | undefined;
}) {
  const reviewVm = selectPlanningReviewViewModel(analysis);
  const [tab, setTab] = useState<PlanningReviewTab>("overview");
  const [kanoHovered, setKanoHovered] = useState<number | null>(null);
  const [kanoSelected, setKanoSelected] = useState<number | null>(
    analysis.kano_features.length > 0 ? 0 : null,
  );
  const [kanoSort, setKanoSort] = useState<{ key: KanoSortKey; dir: SortDir }>({ key: "index", dir: "asc" });
  const riskSectionRef = useRef<HTMLDivElement | null>(null);
  const recommendationSectionRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setKanoSelected((prev) => {
      if (analysis.kano_features.length === 0) return null;
      return prev !== null && prev < analysis.kano_features.length ? prev : 0;
    });
  }, [analysis.kano_features.length]);

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

  const jumpToOverviewSection = useCallback((section: "risk" | "recommendation") => {
    setTab("overview");
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const target = section === "risk" ? riskSectionRef.current : recommendationSectionRef.current;
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }, []);

  const topRisk = reviewVm.riskHighlights[0] ?? null;
  const topRecommendation = reviewVm.structuredRecommendations[0] ?? null;
  const decisionSummary = reviewVm.decisionSummary;
  const detailPrimaryLabel = topRisk ? "最優先リスク" : decisionSummary?.label ?? "主要フォーカス";
  const detailPrimaryTitle = topRisk?.title ?? decisionSummary?.title ?? "大きな阻害要因はありません";
  const detailPrimaryMeta = topRisk?.mustResolveBefore ?? decisionSummary?.due ?? null;
  const topRiskStyle = topRisk
    ? (RISK_SEVERITY_STYLE[topRisk.severity] ?? RISK_SEVERITY_STYLE.medium)
    : null;
  const activeKanoIdx = kanoHovered ?? kanoSelected;
  const activeKanoFeature = activeKanoIdx !== null ? analysis.kano_features[activeKanoIdx] ?? null : null;
  const continueDisabled = requiresDecisionConfirmation && !decisionConfirmed;
  const [handoffCopyState, setHandoffCopyState] = useState<"idle" | "copied" | "error">("idle");
  const handoffCopyText = useMemo(() => {
    const lines = [
      reviewVm.handoffBrief.headline,
      reviewVm.handoffBrief.summary,
      "",
      ...reviewVm.handoffBrief.bullets.map((item) => `- ${item}`),
    ];
    if (planningGuardrails.length > 0) {
      lines.push("", "持ち込む前提:");
      planningGuardrails.forEach((item) => lines.push(`- ${item}`));
    }
    return lines.join("\n");
  }, [planningGuardrails, reviewVm.handoffBrief]);

  useEffect(() => {
    if (handoffCopyState === "idle") return;
    const timeoutId = window.setTimeout(() => setHandoffCopyState("idle"), 2200);
    return () => window.clearTimeout(timeoutId);
  }, [handoffCopyState]);

  const handleCouncilAction = useCallback((targetTab?: PlanningReviewTab, targetSection?: "risk" | "recommendation") => {
    if (targetSection) {
      jumpToOverviewSection(targetSection);
      return;
    }
    if (targetTab) {
      setTab(targetTab);
    }
  }, [jumpToOverviewSection]);

  const copyHandoffBrief = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(handoffCopyText);
      setHandoffCopyState("copied");
    } catch {
      setHandoffCopyState("error");
    }
  }, [handoffCopyText]);

  const councilCardStyle = (tone?: string) => {
    if (tone && tone in RISK_SEVERITY_STYLE) {
      return RISK_SEVERITY_STYLE[tone];
    }
    if (tone && tone in RECOMMENDATION_PRIORITY_STYLE) {
      return RECOMMENDATION_PRIORITY_STYLE[tone];
    }
    return RECOMMENDATION_PRIORITY_STYLE.medium;
  };
  const isOverview = tab === "overview";
  const detailTabCopy: Record<Exclude<PlanningReviewTab, "overview">, { title: string; description: string }> = {
    persona: {
      title: "主要ユーザー像を揃える",
      description: "誰の判断を支える企画なのかを短く確認し、以降の比較軸をぶらさないためのタブです。",
    },
    journey: {
      title: "行動の流れを確認する",
      description: "導入前から継続利用までの接点を見て、どこで価値が立ち上がるかを把握します。",
    },
    jtbd: {
      title: "片づけたい仕事を確認する",
      description: "ジョブストーリーの文脈で、機能ではなくユーザーが得たい成果を確認します。",
    },
    kano: {
      title: "価値の重みを確認する",
      description: "KANO の観点で、必須品質と魅力品質の釣り合いを見直します。",
    },
    stories: {
      title: "ストーリーを整列する",
      description: "誰が何をしたいかを受け入れ条件つきで並べ、スコープを判断可能にします。",
    },
    actors: {
      title: "関係者と役割を揃える",
      description: "ユーザーだけでなく運用者や外部システムまで含めて責務の境界を確認します。",
    },
    usecases: {
      title: "ユースケースで操作を固める",
      description: "主要フローと分岐を見て、デザイン比較で崩してはいけない導線を明確にします。",
    },
    ia: {
      title: "情報構造を確認する",
      description: "情報のまとまりと遷移経路を見て、迷わないナビゲーションの骨格を確認します。",
    },
    "design-tokens": {
      title: "表現ルールを確認する",
      description: "色、文字、動きの方針をまとめ、デザインが判断面から逸れないようにします。",
    },
  };
  const activeDetailTab = !isOverview ? detailTabCopy[tab] : null;
  const activeTabLabel = reviewVm.reviewTabs.find((item) => item.key === tab)?.label ?? "概要";
  const heroStatLabel: Record<string, string> = {
    "重要リスク": "重要リスク",
    "高優先アクション": "優先アクション",
    "中止基準": "中止基準",
    "持ち込む前提": "前提数",
  };

  return (
    <div className="mx-auto max-w-5xl">
      {isOverview ? (
        <div className={cn(planningSurfaceVariants({ tone: "strong", padding: "md" }), "mb-4")}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-2">
              <div className={planningChipVariants({ tone: "accent" })}>
                <Sparkles className="h-3.5 w-3.5" />
                企画統合
              </div>
              <div>
                <h2 className="text-lg font-semibold text-foreground">いま固めるべき企画判断を先に出す</h2>
                <p className={cn("mt-1", planningMutedCopyClassName)}>
                  量より順序を優先し、次のデザインフェーズに渡す前に処理すべき論点と前提だけを先頭に集約します。
                </p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 lg:w-[22rem] xl:w-[30rem] xl:grid-cols-4">
              {reviewVm.heroStats.map((item) => (
                <div
                  key={item.label}
                  className={cn(
                    planningMetricTileVariants({
                      tone:
                        item.label === "重要リスク"
                          ? "warning"
                          : item.label === "高優先アクション"
                            ? "accent"
                            : "default",
                    }),
                    "text-center",
                  )}
                >
                  <p className="text-lg font-semibold text-foreground">{item.value}</p>
                  <p className={cn(planningMicroLabelClassName, "mt-1 leading-4 [word-break:keep-all]")}>
                    {heroStatLabel[item.label] ?? item.label}
                  </p>
                </div>
              ))}
            </div>
          </div>
          {(decisionSummary || handoffNotice || planningGuardrails.length > 0 || onContinue) && (
            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(17rem,0.9fr)]">
              <div className={planningSurfaceVariants({ tone: "accent", padding: "md" })}>
                <div className="flex flex-wrap items-center gap-2">
                  {handoffNotice && (
                    <Badge variant="outline" className={planningChipVariants({ tone: "accent" })}>
                      調査から前提つきで引き継ぎ
                    </Badge>
                  )}
                  {decisionSummary?.label && (
                    <Badge variant="outline" className={planningChipVariants({ tone: "default" })}>
                      {decisionSummary.label}
                    </Badge>
                  )}
                  {topRisk && topRiskStyle && (
                    <Badge variant="outline" className={topRiskStyle.badge}>
                      {topRiskStyle.label}
                    </Badge>
                  )}
                </div>
                <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(16rem,0.9fr)]">
                  <div className="space-y-3">
                    {decisionSummary && (
                      <div className="space-y-2">
                        <h3 className="text-base font-semibold text-foreground">{decisionSummary.title}</h3>
                        <p className={cn("leading-6", planningMutedCopyClassName)}>{decisionSummary.description}</p>
                      </div>
                    )}
                    <div className="flex flex-wrap gap-2 text-[11px] text-[color:var(--planning-text-soft)]">
                      {decisionSummary?.owner && (
                        <span className={planningChipVariants({ tone: "default" })}>
                          担当: {decisionSummary.owner}
                        </span>
                      )}
                      {decisionSummary?.due && (
                        <span className={planningChipVariants({ tone: "default" })}>
                          {topRisk ? "解消期限" : "対象"}: {decisionSummary.due}
                        </span>
                      )}
                    </div>
                    {handoffNotice && (
                      <p className="text-xs leading-5 text-[color:var(--planning-text-soft)]">{handoffNotice}</p>
                    )}
                  </div>

                  <div className={cn(planningSurfaceVariants({ tone: "inset", padding: "sm" }), "space-y-3")}>
                    <div>
                      <p className={planningEyebrowClassName}>持ち込む前提</p>
                      <p className="mt-2 text-sm font-medium text-foreground">
                        {planningGuardrails[0] ?? "主要導線と停止条件を先に崩さない"}
                      </p>
                    </div>
                    {planningGuardrails.length > 1 && (
                      <div className="space-y-1.5">
                        {planningGuardrails.slice(1, 3).map((item) => (
                          <p key={item} className="text-xs leading-5 text-[color:var(--planning-text-soft)]">
                            • {item}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className={planningSurfaceVariants({ tone: "inset", padding: "md" })}>
                <p className={planningEyebrowClassName}>進行チェック</p>
                <div className="mt-3 flex flex-col gap-2">
                  {topRisk && (
                    <button
                      onClick={() => jumpToOverviewSection("risk")}
                      className={planningActionVariants({ tone: "primary" })}
                    >
                      主要リスクを確認
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  )}
                  {topRecommendation && (
                    <button
                      onClick={() => jumpToOverviewSection("recommendation")}
                      className={planningActionVariants({ tone: "secondary" })}
                    >
                      推奨アクションを見る
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  )}
                  {requiresDecisionConfirmation && onDecisionConfirmedChange && (
                    <button
                      type="button"
                      onClick={() => onDecisionConfirmedChange(!decisionConfirmed)}
                      className={cn(
                        "rounded-xl border px-3 py-3 text-left transition-colors",
                        decisionConfirmed
                          ? "border-[color:var(--planning-success-border)] bg-[var(--planning-success-soft)] text-foreground"
                          : "border-[color:var(--planning-border)] bg-[var(--planning-surface)] text-foreground hover:bg-[var(--planning-surface-strong)]",
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <span className={cn(
                          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                          decisionConfirmed
                            ? "border-[color:var(--planning-success-border)] bg-[var(--planning-success-soft)] text-[color:var(--planning-success-strong)]"
                            : "border-[color:var(--planning-border)] bg-[var(--planning-inset)] text-transparent",
                        )}>
                          <Check className="h-3.5 w-3.5" />
                        </span>
                        <span className="space-y-1">
                          <span className="block text-sm font-medium">主要リスクと前提を確認した</span>
                          <span className="block text-xs leading-5 text-[color:var(--planning-text-soft)]">
                            未解決の前提を理解した上で、次のデザイン比較へ進める状態を明示します。
                          </span>
                        </span>
                      </div>
                    </button>
                  )}
                </div>
                {continueDisabled && (
                  <p className="mt-3 text-xs leading-5 text-[color:var(--planning-text-soft)]">
                    進行前に、主要リスクと持ち込む前提の確認を完了してください。
                  </p>
                )}
                {!continueDisabled && onContinue && (
                  <p className="mt-3 text-xs leading-5 text-[color:var(--planning-text-soft)]">
                    確認が済んだら、上部ヘッダーの「{continueLabel}」から次へ進めます。
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className={cn(planningSurfaceVariants({ tone: "subtle", padding: "md" }), "mb-4")}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-2">
              <div className={planningChipVariants({ tone: "default" })}>
                <CircleDot className="h-3.5 w-3.5 text-primary" />
                分析結果 / {activeTabLabel}
              </div>
              <div>
                <h2 className="text-lg font-semibold text-foreground">{activeDetailTab?.title}</h2>
                <p className={cn("mt-1", planningMutedCopyClassName)}>{activeDetailTab?.description}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setTab("overview")}
                className={planningActionVariants({ tone: "secondary" })}
              >
                概要に戻る
              </button>
              {topRisk && (
                <button
                  type="button"
                  onClick={() => jumpToOverviewSection("risk")}
                  className={planningActionVariants({ tone: "tonal" })}
                >
                  主要リスク
                </button>
              )}
              <button
                type="button"
                onClick={copyHandoffBrief}
                className={planningActionVariants({ tone: "secondary" })}
              >
                {handoffCopyState === "copied" ? "要約をコピー済み" : "要約をコピー"}
              </button>
            </div>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className={planningMetricTileVariants({ tone: "warning" })}>
              <p className={planningEyebrowClassName}>{detailPrimaryLabel}</p>
              <p className="mt-2 text-sm font-medium text-foreground">{detailPrimaryTitle}</p>
              {detailPrimaryMeta && <p className="mt-1 text-xs text-[color:var(--planning-text-soft)]">期限: {detailPrimaryMeta}</p>}
            </div>
            <div className={planningMetricTileVariants({ tone: "accent" })}>
              <p className={planningEyebrowClassName}>次の判断</p>
              <p className="mt-2 text-sm font-medium text-foreground">{topRecommendation?.action ?? "主要仮説を保ちながら詳細を確認します"}</p>
            </div>
            <div className={planningMetricTileVariants({ tone: "default" })}>
              <p className={planningEyebrowClassName}>持ち込む前提</p>
              <p className="mt-2 text-sm font-medium text-foreground">{planningGuardrails[0] ?? "主要導線と停止条件を先に崩さない"}</p>
            </div>
          </div>
        </div>
      )}
      {isOverview && (
        <div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(18rem,0.9fr)]">
          <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className={planningEyebrowClassName}>判断を支える視点</p>
                <h3 className="mt-1 text-base font-semibold text-foreground">補助メモだけを短く並べる</h3>
              </div>
              <Badge variant="outline" className={planningChipVariants({ tone: "accent" })}>
                4視点レビュー
              </Badge>
            </div>
            <div className="mt-4 space-y-3">
              {reviewVm.councilCards.map((card) => {
                const style = councilCardStyle(card.tone);
                return (
                  <div key={card.id} className={cn(style.card, "space-y-2")}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="space-y-1">
                        <p className={planningMicroLabelClassName}>{card.agent}</p>
                        <p className="text-sm font-semibold text-foreground">{card.title}</p>
                      </div>
                      <Badge variant="outline" className={style.badge}>
                        {card.lens}
                      </Badge>
                    </div>
                    <p className="text-xs leading-5 text-muted-foreground">{card.summary}</p>
                    <button
                      type="button"
                      onClick={() => handleCouncilAction(card.targetTab, card.targetSection)}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-[color:var(--planning-accent-strong)] hover:text-white"
                    >
                      {card.actionLabel}
                      <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          <div className={planningSurfaceVariants({ tone: "accent", padding: "md" })}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className={planningEyebrowClassName}>デザイン引き継ぎ</p>
                <h3 className="mt-1 text-base font-semibold text-foreground">そのまま渡せる要約</h3>
              </div>
              <button
                type="button"
                onClick={copyHandoffBrief}
                className={cn(
                  "px-3 py-1",
                  handoffCopyState === "copied"
                    ? planningActionVariants({ tone: "secondary" }).replace("px-4 py-2", "")
                    : handoffCopyState === "error"
                      ? planningActionVariants({ tone: "danger" }).replace("px-4 py-2", "")
                      : planningActionVariants({ tone: "secondary" }).replace("px-4 py-2", ""),
                )}
              >
                {handoffCopyState === "copied" ? "コピー済み" : handoffCopyState === "error" ? "コピー失敗" : "要約をコピー"}
              </button>
            </div>
            <div className={cn(planningSurfaceVariants({ tone: "inset", padding: "md" }), "mt-4")}>
              <p className="text-sm font-semibold text-foreground">{reviewVm.handoffBrief.headline}</p>
              <p className={cn("mt-2 leading-6", planningMutedCopyClassName)}>{reviewVm.handoffBrief.summary}</p>
              <div className="mt-4 space-y-2">
                {reviewVm.handoffBrief.bullets.slice(0, 4).map((item) => (
                  <p key={item} className="flex items-start gap-2 text-xs leading-5 text-foreground">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                    <span>{item}</span>
                  </p>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="mb-4 -mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {reviewVm.reviewTabs.filter((item) => !item.hidden).map((item) => {
          const Icon = REVIEW_TAB_ICONS[item.key];
          return (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={planningTabVariants({ active: tab === item.key })}
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
              <div key={item.label} className={cn(planningMetricTileVariants({ tone: "default" }), "text-center")}>
                <p className="text-2xl font-bold text-foreground">{item.value}</p>
                <p className={planningEyebrowClassName}>{item.label}</p>
              </div>
            ))}
          </div>
          {reviewVm.coverageSummary && (
            <div className={planningSurfaceVariants({ tone: "accent", padding: "md" })}>
              <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className={planningEyebrowClassName}>計画カバレッジ</p>
                  <h3 className="mt-1 text-sm font-semibold text-foreground">この企画がどこまで作り切れる粒度になっているか</h3>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {reviewVm.coverageSummary.tiles.map((item) => (
                    <div key={item.label} className={cn(planningMetricTileVariants({ tone: "default" }), "min-w-[6rem] text-center")}>
                      <p className="text-lg font-semibold text-foreground">{item.value}</p>
                      <p className={planningMicroLabelClassName}>{item.label}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-4 grid gap-2 lg:grid-cols-2">
                {reviewVm.coverageSummary.notes.map((note, index) => (
                  <div key={`${note}-${index}`} className={cn(planningSurfaceVariants({ tone: index === 0 ? "subtle" : "inset", padding: "sm" }), "text-xs leading-5 text-foreground")}>
                    {note}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
            <h3 className="mb-3 text-sm font-medium text-foreground">KANO分布</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              {reviewVm.kanoDistribution.map((item) => (
                <div key={item.label} className={cn(planningMetricTileVariants({ tone: "default" }), "text-center", item.color)}>
                  <p className="text-lg font-bold">{item.count}</p>
                  <p className="text-xs">{item.label}</p>
                </div>
              ))}
            </div>
          </div>
          {!!reviewVm.riskHighlights.length && (
            <div ref={riskSectionRef} className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
              <div className="mb-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-400" />
                <h3 className="text-sm font-medium text-foreground">主要リスク</h3>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {reviewVm.riskHighlights.map((risk) => {
                  const style = RISK_SEVERITY_STYLE[risk.severity] ?? RISK_SEVERITY_STYLE.medium;
                  return (
                    <div key={risk.id} className={style.card}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1">
                          <p className="text-sm font-medium text-foreground">{risk.title}</p>
                          <div className="flex flex-wrap gap-2 text-[11px] text-[color:var(--planning-text-soft)]">
                            {risk.owner && <span>担当: {risk.owner}</span>}
                            {risk.mustResolveBefore && <span>期限: {risk.mustResolveBefore}</span>}
                          </div>
                        </div>
                        <Badge variant="outline" className={style.badge}>
                          {style.label}
                        </Badge>
                      </div>
                      <p className="mt-3 text-xs leading-5 text-[color:var(--planning-text-soft)]">{risk.description}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {!!reviewVm.structuredRecommendations.length && (
            <div ref={recommendationSectionRef} className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
              <div className="mb-3 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-medium text-foreground">推奨アクション</h3>
              </div>
              <div className="space-y-3">
                {reviewVm.structuredRecommendations.map((item) => {
                  const style = RECOMMENDATION_PRIORITY_STYLE[item.priority] ?? RECOMMENDATION_PRIORITY_STYLE.medium;
                  return (
                    <div key={item.id} className={style.card}>
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="space-y-1">
                          <p className="text-sm font-medium text-foreground">{item.action}</p>
                          {item.target && (
                            <p className="text-[11px] text-[color:var(--planning-text-soft)]">対象: {item.target}</p>
                          )}
                        </div>
                        <Badge variant="outline" className={style.badge}>
                          {style.label}
                        </Badge>
                      </div>
                      {item.rationale && (
                        <p className="mt-3 text-xs leading-5 text-[color:var(--planning-text-soft)]">{item.rationale}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {!!reviewVm.recommendationNotes.length && (
            <div className="space-y-2">
              {reviewVm.recommendationNotes.map((note, index) => (
                <div key={`${note}-${index}`} className={cn(planningSurfaceVariants({ tone: "inset", padding: "sm" }), "text-sm text-foreground")}>
                  {note}
                </div>
              ))}
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
              <h3 className="mb-3 text-sm font-medium text-foreground">判定テーブル</h3>
              <div className="space-y-2">
                {(analysis.feature_decisions ?? []).map((decision) => (
                  <div key={decision.feature} className={planningSurfaceVariants({ tone: "inset", padding: "sm" })}>
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
            <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
              <h3 className="mb-3 text-sm font-medium text-foreground">仮説とレッドチームの発見</h3>
              <div className="space-y-2">
                {(analysis.assumptions ?? []).map((assumption) => (
                  <div key={assumption.id} className={planningSurfaceVariants({ tone: "inset", padding: "sm" })}>
                    <p className="text-xs font-medium text-foreground">{assumption.statement}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{SEVERITY_TEXT_LABELS[assumption.severity] ?? assumption.severity}</p>
                  </div>
                ))}
                {(analysis.red_team_findings ?? []).map((finding) => (
                  <div key={finding.id} className={planningSurfaceVariants({ tone: "danger", padding: "sm" })}>
                    <p className="text-xs font-medium text-foreground">{finding.title}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{finding.recommendation}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
              <h3 className="mb-3 text-sm font-medium text-foreground">トレーサビリティ</h3>
              <div className="space-y-2">
                {(analysis.traceability ?? []).map((item, index) => (
                  <div key={`${item.feature}-${index}`} className={cn(planningSurfaceVariants({ tone: "inset", padding: "sm" }), "text-xs text-foreground")}>
                    <p>{item.feature}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      主張 {item.claim_id || "n/a"} → ユースケース {item.use_case_id || "n/a"} → マイルストーン {item.milestone_id || "n/a"}
                    </p>
                  </div>
                ))}
              </div>
            </div>
            <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
              <h3 className="mb-3 text-sm font-medium text-foreground">ネガティブペルソナと中止基準</h3>
              <div className="space-y-2">
                {(analysis.negative_personas ?? []).map((persona) => (
                  <div key={persona.id} className={planningSurfaceVariants({ tone: "inset", padding: "sm" })}>
                    <p className="text-xs font-medium text-foreground">{persona.name}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{persona.mitigation}</p>
                  </div>
                ))}
                {(analysis.kill_criteria ?? []).map((criterion) => (
                  <div key={criterion.id} className={planningSurfaceVariants({ tone: "inset", padding: "sm" })}>
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
            <div key={i} className={cn(planningDetailCardVariants({ tone: "default", padding: "lg" }), "space-y-3")}>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full border border-[color:var(--planning-border-strong)] bg-[var(--planning-accent-soft)] font-bold text-primary">{p.name.charAt(0)}</div>
                <div>
                  <p className="font-medium text-foreground">{p.name}</p>
                  <p className={planningBodyLabelClassName}>
                    {p.role} · {p.age_range}
                    {p.tech_proficiency ? ` · 熟練度 ${PROFICIENCY_LABELS[p.tech_proficiency] ?? p.tech_proficiency}` : ""}
                  </p>
                </div>
              </div>
              <p className={planningBodyLabelClassName}>{p.context}</p>
              {p.goals.map((g, j) => (
                <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                  <Check className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--planning-success-strong)]" />
                  {g}
                </p>
              ))}
              {p.frustrations.map((f, j) => (
                <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--planning-danger-strong)]" />
                  {f}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}

      {tab === "kano" && (
        <div className="space-y-4">
          <KanoBubbleChart
            features={analysis.kano_features}
            activeIdx={activeKanoIdx}
            tooltipIdx={kanoHovered}
            onHover={setKanoHovered}
            onSelect={setKanoSelected}
          />
          {activeKanoFeature && (
            <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-2">
                  <p className={planningMicroLabelClassName}>
                    タップ / クリックで固定
                  </p>
                  <div>
                    <h3 className="text-base font-semibold text-foreground">{activeKanoFeature.feature}</h3>
                    <p className={cn("mt-1", planningMutedCopyClassName)}>
                      {KANO_CATEGORY_HELP[activeKanoFeature.category] ?? "価値仮説の扱いを見直すポイントです。"}
                    </p>
                  </div>
                </div>
                <span className={planningSoftBadgeVariants({ tone: activeKanoFeature.category === "must-be" ? "danger" : activeKanoFeature.category === "attractive" ? "success" : activeKanoFeature.category === "one-dimensional" ? "accent" : "default" })}>
                  {(KANO_CAT_STYLE[activeKanoFeature.category] ?? KANO_CAT_STYLE.indifferent).label}
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className={planningDetailCardVariants({ tone: "default", padding: "md" })}>
                  <p className={planningEyebrowClassName}>満足度</p>
                  <p className="mt-1 text-lg font-semibold text-foreground">{activeKanoFeature.user_delight.toFixed(1)}</p>
                </div>
                <div className={planningDetailCardVariants({ tone: "default", padding: "md" })}>
                  <p className={planningEyebrowClassName}>実装コスト</p>
                  <p className="mt-1 text-lg font-semibold text-foreground">{KANO_COST_LABELS[activeKanoFeature.implementation_cost] ?? activeKanoFeature.implementation_cost}</p>
                </div>
                <div className={planningDetailCardVariants({ tone: "default", padding: "md" })}>
                  <p className={planningEyebrowClassName}>カテゴリ</p>
                  <p className="mt-1 text-lg font-semibold text-foreground">
                    {(KANO_CAT_STYLE[activeKanoFeature.category] ?? KANO_CAT_STYLE.indifferent).label}
                  </p>
                </div>
              </div>
              {activeKanoFeature.rationale && (
                <p className={cn("mt-4 leading-6", planningMutedCopyClassName)}>{activeKanoFeature.rationale}</p>
              )}
            </div>
          )}
          <div className={cn(planningSurfaceVariants({ tone: "default" }), "overflow-x-auto")}>
            <table className="min-w-[40rem] w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-[rgba(119,182,234,0.05)]">
                  {([
                    { key: "index" as KanoSortKey, label: "#", w: "w-10" },
                    { key: "feature" as KanoSortKey, label: "機能", w: "" },
                    { key: "category" as KanoSortKey, label: "カテゴリ", w: "w-36" },
                    { key: "delight" as KanoSortKey, label: "満足度", w: "w-32" },
                    { key: "cost" as KanoSortKey, label: "コスト", w: "w-24" },
                  ]).map((col) => (
                    <th key={col.key} className={cn("select-none px-3 py-3 text-left text-xs font-medium text-[color:var(--planning-text-soft)]", col.w)}>
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
                    indifferent: "text-[color:var(--planning-text-soft)]",
                    reverse: "text-[color:var(--planning-text-muted)]",
                  };
                  const isHovered = activeKanoIdx === f._origIdx;
                  return (
                    <tr
                      key={f._origIdx}
                      tabIndex={0}
                      role="button"
                      aria-pressed={kanoSelected === f._origIdx}
                      onMouseEnter={() => setKanoHovered(f._origIdx)}
                      onMouseLeave={() => setKanoHovered(null)}
                      onFocus={() => setKanoSelected(f._origIdx)}
                      onBlur={() => setKanoHovered(null)}
                      onClick={() => setKanoSelected(f._origIdx)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setKanoSelected(f._origIdx);
                        }
                      }}
                      className={cn("cursor-pointer transition-colors outline-none", isHovered ? "bg-[rgba(119,182,234,0.12)]" : "hover:bg-[rgba(119,182,234,0.05)]")}
                    >
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{f._origIdx + 1}</td>
                      <td className="px-3 py-2.5">
                        <p className="font-medium text-foreground">{f.feature}</p>
                        {f.rationale && <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{f.rationale}</p>}
                      </td>
                      <td className={cn("px-3 py-2.5 text-xs font-medium", catColor[f.category])}>
                        {(KANO_CAT_STYLE[f.category] ?? KANO_CAT_STYLE.indifferent).label}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-14 overflow-hidden rounded-full bg-[rgba(127,147,169,0.22)]">
                            <div
                              className={cn("h-full rounded-full transition-all", f.user_delight > 0.7 ? "bg-[color:var(--planning-success-strong)]" : f.user_delight > 0.4 ? "bg-[color:var(--planning-accent)]" : "bg-[color:var(--planning-warning-strong)]")}
                              style={{ width: `${Math.max(f.user_delight * 100, 5)}%` }}
                            />
                          </div>
                          <span className="tabular-nums text-xs text-muted-foreground">{f.user_delight.toFixed(1)}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={planningSoftBadgeVariants({ tone: f.implementation_cost === "high" ? "danger" : f.implementation_cost === "low" ? "success" : "default" })}>
                          {KANO_COST_LABELS[f.implementation_cost] ?? f.implementation_cost}
                        </span>
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
            return (
              <div key={i} className={cn(planningDetailCardVariants({ tone: "default", padding: "md" }), "flex items-start gap-2")}>
                <span className={cn(planningSoftBadgeVariants({ tone: s.priority === "must" ? "danger" : s.priority === "should" ? "warning" : s.priority === "could" ? "accent" : "default" }), "mt-0.5 shrink-0")}>{s.priority}</span>
                <div>
                  <p className="text-sm text-foreground">
                    {s.role} として、{s.action} したい
                  </p>
                  <p className={cn("mt-0.5", planningBodyLabelClassName)}>それにより {s.benefit}</p>
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
      <div className={planningDetailCardVariants({ tone: "default", padding: "md" })}>
        <p className={cn("leading-relaxed", planningMutedCopyClassName)}>{rationale}</p>
      </div>

      <div className={cn(planningDetailCardVariants({ tone: "default", padding: "md" }), "space-y-3")}>
        <h4 className={cn(planningSectionTitleClassName, "flex items-center gap-2")}>
          <Palette className="h-4 w-4 text-primary" />
          スタイル
        </h4>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-base font-medium text-foreground">{style.name}</span>
          {style.keywords.map((kw) => (
            <span key={kw} className={planningSoftBadgeVariants({ tone: "default" })}>{kw}</span>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-3 text-xs text-[color:var(--planning-text-soft)] sm:grid-cols-3">
          <div>
            <span className={cn("block", planningEyebrowClassName)}>適用先</span>
            {style.best_for || "—"}
          </div>
          <div>
            <span className={cn("block", planningEyebrowClassName)}>パフォーマンス</span>
            {style.performance || "—"}
          </div>
          <div>
            <span className={cn("block", planningEyebrowClassName)}>アクセシビリティ</span>
            {style.accessibility || "—"}
          </div>
        </div>
      </div>

      <div className={cn(planningDetailCardVariants({ tone: "default", padding: "md" }), "space-y-3")}>
        <h4 className={planningSectionTitleClassName}>カラーパレット</h4>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {colorEntries.map(([key, hex]) => (
            <div key={key} className="space-y-1.5">
              <div className="h-16 cursor-pointer rounded-[1rem] border border-[color:var(--planning-border)] transition-transform hover:scale-[1.02]" style={{ backgroundColor: hex }} title={hex} />
              <div className="text-center text-[10px]">
                <div className="font-medium text-foreground/80">{colorLabels[key] ?? key}</div>
                <div className="font-mono text-[color:var(--planning-text-soft)]">{hex}</div>
              </div>
            </div>
          ))}
        </div>
        {colors.notes && <p className={cn("mt-2", planningBodyLabelClassName)}>{colors.notes}</p>}
      </div>

      <div className={cn(planningDetailCardVariants({ tone: "default", padding: "md" }), "space-y-3")}>
        <h4 className={planningSectionTitleClassName}>タイポグラフィ</h4>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <span className={cn("mb-1 block", planningEyebrowClassName)}>見出し</span>
            <span className="text-lg font-semibold" style={{ fontFamily: typography.heading }}>
              {typography.heading}
            </span>
          </div>
          <div>
            <span className={cn("mb-1 block", planningEyebrowClassName)}>本文</span>
            <span className="text-lg" style={{ fontFamily: typography.body }}>
              {typography.body}
            </span>
          </div>
        </div>
        {typography.mood.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {typography.mood.map((m) => (
              <span key={m} className={planningSoftBadgeVariants({ tone: "default" })}>{m}</span>
            ))}
          </div>
        )}
        {typography.google_fonts_url && (
          <a href={typography.google_fonts_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[color:var(--planning-accent-strong)] hover:text-white hover:underline">
            Google Fonts で表示
          </a>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={cn(planningDetailCardVariants({ tone: "accent", padding: "md" }), "space-y-2")}>
          <h4 className={cn(planningSectionTitleClassName, "flex items-center gap-1.5")}>
            <Sparkles className="h-3.5 w-3.5 text-[color:var(--planning-warning-strong)]" />
            エフェクト
          </h4>
          <ul className="space-y-1">
            {effects.map((e, i) => (
              <li key={i} className="flex items-center gap-1.5 text-xs text-[color:var(--planning-text-soft)]">
                <Check className="h-3 w-3 shrink-0 text-[color:var(--planning-success-strong)]" />
                {e}
              </li>
            ))}
          </ul>
        </div>
        <div className={cn(planningDetailCardVariants({ tone: "danger", padding: "md" }), "space-y-2")}>
          <h4 className={cn(planningSectionTitleClassName, "flex items-center gap-1.5")}>
            <AlertTriangle className="h-3.5 w-3.5 text-[color:var(--planning-danger-strong)]" />
            アンチパターン
          </h4>
          <ul className="space-y-1">
            {anti_patterns.map((a, i) => (
              <li key={i} className="flex items-center gap-1.5 text-xs text-[color:var(--planning-text-soft)]">
                <AlertCircle className="h-3 w-3 shrink-0 text-[color:var(--planning-danger-strong)]" />
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
            className={planningTabVariants({ active: activeTab === t.key })}
          >
            <t.icon className="h-3.5 w-3.5" />
            {t.label}
            <span className={cn(planningSoftBadgeVariants({ tone: activeTab === t.key ? "accent" : "default" }), "ml-1 px-1.5 py-0.5 text-[10px]")}>{t.count}</span>
          </button>
        ))}
      </div>

      {activeTab === "actors" && (
        <div className="grid gap-4 lg:grid-cols-2">
          {actors.map((a, i) => {
            const style = ACTOR_TYPE_STYLE[a.type] ?? ACTOR_TYPE_STYLE.primary;
            return (
              <div key={i} className={cn(planningDetailCardVariants({ tone: style.tone, padding: "lg" }), "space-y-3")}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={cn("flex h-10 w-10 items-center justify-center rounded-full border", style.tone === "accent" ? "border-[color:var(--planning-border-strong)] bg-[var(--planning-accent-soft)]" : style.tone === "warning" ? "border-[color:var(--planning-warning-border)] bg-[var(--planning-warning-soft)]" : "border-[color:var(--planning-border)] bg-[var(--planning-inset)]")}>
                      <style.icon className={cn("h-5 w-5", style.accent)} />
                    </div>
                    <div>
                      <p className="font-medium text-foreground">{a.name}</p>
                      <p className={planningBodyLabelClassName}>{a.description}</p>
                    </div>
                  </div>
                  <span className={planningSoftBadgeVariants({ tone: style.tone })}>{style.label}</span>
                </div>
                {a.goals.length > 0 && (
                  <div>
                    <p className={cn("mb-1.5", planningEyebrowClassName)}>ゴール</p>
                    <div className="space-y-1">
                      {a.goals.map((g, j) => (
                        <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                          <Target className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--planning-success-strong)]" />
                          {g}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
                {a.interactions.length > 0 && (
                  <div>
                    <p className={cn("mb-1.5", planningEyebrowClassName)}>インタラクション</p>
                    <div className="flex flex-wrap gap-1">
                      {a.interactions.map((interaction, j) => (
                        <span key={j} className={planningSoftBadgeVariants({ tone: "default" })}>{interaction}</span>
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
            <div key={i} className={cn(planningDetailCardVariants({ tone: "default", padding: "lg" }), "space-y-3")}>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full border border-[color:var(--planning-border-strong)] bg-[var(--planning-accent-soft)]">
                  <Shield className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="font-medium text-foreground">{r.name}</p>
                  {r.related_actors.length > 0 && <p className={planningBodyLabelClassName}>関連アクター: {r.related_actors.join(", ")}</p>}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className={cn("mb-1.5", planningEyebrowClassName)}>責務</p>
                  <div className="space-y-1">
                    {r.responsibilities.map((resp, j) => (
                      <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                        <Check className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--planning-success-strong)]" />
                        {resp}
                      </p>
                    ))}
                  </div>
                </div>
                <div>
                  <p className={cn("mb-1.5", planningEyebrowClassName)}>権限</p>
                  <div className="space-y-1">
                    {r.permissions.map((perm, j) => (
                      <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                        <Shield className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--planning-warning-strong)]" />
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
    must: planningSoftBadgeVariants({ tone: "danger" }),
    should: planningSoftBadgeVariants({ tone: "warning" }),
    could: planningSoftBadgeVariants({ tone: "accent" }),
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
      <div key={uc.id} className={cn(planningDetailCardVariants({ tone: "default", padding: "none" }), "overflow-hidden")}>
        <button onClick={() => toggle(uc.id)} className="flex w-full cursor-pointer items-center gap-3 p-4 text-left transition-colors hover:bg-[rgba(119,182,234,0.06)]">
          <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">{uc.id}</span>
              <p className="truncate font-medium text-foreground">{uc.title}</p>
            </div>
            <p className={cn("mt-0.5", planningBodyLabelClassName)}>
              <Users className="mr-1 inline h-3 w-3" />
              {uc.actor}
            </p>
          </div>
          <span className={cn(priorityStyle[uc.priority], "shrink-0")}>{USE_CASE_PRIORITY_LABELS[uc.priority] ?? uc.priority}</span>
        </button>
        {isOpen && (
          <div className="space-y-4 border-t border-border bg-[rgba(119,182,234,0.04)] px-4 py-4">
            {uc.preconditions.length > 0 && (
              <div>
                <p className={cn("mb-1.5", planningEyebrowClassName)}>事前条件</p>
                <div className="space-y-1">
                  {uc.preconditions.map((pre, j) => (
                    <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                      <CircleDot className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--planning-warning-strong)]" />
                      {pre}
                    </p>
                  ))}
                </div>
              </div>
            )}
            <div>
              <p className={cn("mb-1.5", planningEyebrowClassName)}>メインフロー</p>
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
                <p className={cn("mb-1.5", planningEyebrowClassName)}>代替フロー</p>
                {uc.alternative_flows.map((af, j) => (
                  <div key={j} className={cn(planningDetailCardVariants({ tone: "warning", padding: "sm" }), "mb-2")}>
                    <p className="mb-1.5 text-xs font-medium text-[color:var(--planning-warning-strong)]">
                      <AlertTriangle className="mr-1 inline h-3 w-3" />
                      {af.condition}
                    </p>
                    <div className="ml-4 space-y-1">
                      {af.steps.map((step, k) => (
                        <p key={k} className="text-xs text-[color:var(--planning-text-soft)]">
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
                <p className={cn("mb-1.5", planningEyebrowClassName)}>事後条件</p>
                <div className="space-y-1">
                  {uc.postconditions.map((post, j) => (
                    <p key={j} className="flex items-start gap-1.5 text-xs text-foreground">
                      <Check className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--planning-success-strong)]" />
                      {post}
                    </p>
                  ))}
                </div>
              </div>
            )}
            {uc.related_stories?.length ? (
              <div className="flex flex-wrap gap-1">
                <span className={cn("mr-1", planningEyebrowClassName)}>関連ストーリー:</span>
                {uc.related_stories.map((story, j) => (
                  <span key={j} className={planningSoftBadgeVariants({ tone: "default" })}>{story}</span>
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
          return (
            <div key={priority} className={cn(planningDetailCardVariants({ tone: priority === "must" ? "danger" : priority === "should" ? "warning" : "accent", padding: "md" }), "flex-1 text-center")}>
              <p className="text-lg font-bold">{count}</p>
              <p className="text-xs">{USE_CASE_PRIORITY_LABELS[priority]}</p>
            </div>
          );
        })}
      </div>

      {Array.from(grouped.entries()).map(([category, subMap]) => (
        <div key={category} className="space-y-3">
          <div className="flex items-center gap-2 pt-2">
            <FolderOpen className="h-4 w-4 text-primary" />
            <h3 className={planningSectionTitleClassName}>{category}</h3>
            <span className={cn(planningEyebrowClassName, "normal-case tracking-normal")}>({Array.from(subMap.values()).flat().length})</span>
          </div>
          {Array.from(subMap.entries()).map(([sub, cases]) => (
            <div key={sub} className="ml-4 space-y-2">
              <div className="flex items-center gap-1.5">
                <div className="h-px max-w-3 flex-1 bg-border" />
                <span className="text-[12px] font-medium text-[color:var(--planning-text-soft)]">{sub}</span>
                <span className="text-[11px] text-[color:var(--planning-text-muted)]">({cases.length})</span>
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
  if (emotion === "positive") return <Smile className="h-4 w-4 text-[color:var(--planning-success-strong)]" />;
  if (emotion === "negative") return <Frown className="h-4 w-4 text-[color:var(--planning-danger-strong)]" />;
  return <Meh className="h-4 w-4 text-[color:var(--planning-warning-strong)]" />;
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
              className={planningTabVariants({ active: i === activePersona })}
            >
              <div className="flex h-6 w-6 items-center justify-center rounded-full border border-[color:var(--planning-border)] bg-[var(--planning-inset)] text-[10px] font-bold text-primary">{j.persona_name.charAt(0)}</div>
              {j.persona_name}
            </button>
          ))}
        </div>
      )}

      <div className={cn(planningSurfaceVariants({ tone: "default" }), "overflow-x-auto")}>
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
                  <p className={cn("mb-1", planningEyebrowClassName)}>行動</p>
                  <p className={planningDataValueClassName}>{tp?.action || "—"}</p>
                </div>
              );
            })}
          </div>

          <div className="grid grid-cols-5 border-b border-border">
            {phases.map((phase) => {
              const tp = journey.touchpoints.find((t) => t.phase === phase);
              return (
                <div key={phase} className="border-r border-border px-3 py-3 last:border-r-0">
                  <p className={cn("mb-1", planningEyebrowClassName)}>タッチポイント</p>
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
                      <p className={cn("mb-1", planningEyebrowClassName, "text-[color:var(--planning-danger-strong)]")}>ペインポイント</p>
                      <p className="text-xs text-[color:var(--planning-danger-strong)]">{tp.pain_point}</p>
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
                      <p className={cn("mb-1", planningEyebrowClassName, "text-[color:var(--planning-success-strong)]")}>機会</p>
                      <p className="text-xs text-[color:var(--planning-success-strong)]">{tp.opportunity}</p>
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
    { key: "core", label: "中核ジョブ", desc: "プロダクトの存在理由となる中核的ジョブ" },
    { key: "supporting", label: "補助ジョブ", desc: "コアジョブを補助する関連ジョブ" },
    { key: "aspirational", label: "拡張ジョブ", desc: "差別化につながる願望的ジョブ" },
  ];

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {sections.map((section) => (
          <div key={section.key} className={cn(planningDetailCardVariants({ tone: JTBD_COLORS[section.key].tone, padding: "md" }), "text-center")}>
            <p className="text-2xl font-bold text-foreground">{grouped[section.key].length}</p>
            <p className={planningBodyLabelClassName}>{section.label}</p>
          </div>
        ))}
      </div>

      {sections.map((section) => {
        const items = grouped[section.key];
        if (items.length === 0) return null;
        return (
          <div key={section.key}>
            <h3 className={cn("mb-1", planningSectionTitleClassName)}>{section.label}</h3>
            <p className={cn("mb-3", planningBodyLabelClassName)}>{section.desc}</p>
            <div className="space-y-3">
              {items.map((story, i) => (
                <div key={i} className={cn(planningDetailCardVariants({ tone: JTBD_COLORS[section.key].tone, padding: "md" }), "space-y-2")}>
                  <div className="space-y-1">
                    <p className="text-sm text-foreground">
                      <span className="font-medium text-[color:var(--planning-text-soft)]">状況</span> {story.situation}
                    </p>
                    <p className="text-sm text-foreground">
                      <span className="font-medium text-[color:var(--planning-text-soft)]">したいこと</span> {story.motivation}
                    </p>
                    <p className="text-sm text-foreground">
                      <span className="font-medium text-[color:var(--planning-text-soft)]">得たい結果</span> {story.outcome}
                    </p>
                  </div>
                  {story.related_features.length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {story.related_features.map((feature, j) => (
                        <span key={j} className={planningSoftBadgeVariants({ tone: "default" })}>{feature}</span>
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
  const style = IA_PRIORITY_STYLE[node.priority];
  return (
    <div className={cn("border-l-2 pl-3", depth === 0 ? "border-primary/40" : "border-border/50")} style={{ marginLeft: depth > 0 ? 12 : 0 }}>
      <div className="flex items-center gap-2 py-1.5">
        <span className={cn(planningSoftBadgeVariants({ tone: style.tone }), "shrink-0")}>{style.label}</span>
        <span className="text-sm font-medium text-foreground">{node.label}</span>
        {node.description && <span className="truncate text-xs text-[color:var(--planning-text-soft)]">— {node.description}</span>}
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
        <div className={cn(planningDetailCardVariants({ tone: "default", padding: "md" }), "flex items-center gap-2")}>
          <Network className="h-4 w-4 text-primary" />
          <div>
            <p className={planningEyebrowClassName}>ナビゲーションモデル</p>
            <p className="text-sm font-bold text-foreground">{NAV_MODEL_LABELS[ia.navigation_model]}</p>
          </div>
        </div>
        <div className={cn(planningDetailCardVariants({ tone: "default", padding: "md" }), "flex items-center gap-2")}>
          <Route className="h-4 w-4 text-primary" />
          <div>
            <p className={planningEyebrowClassName}>主要パス</p>
            <p className="text-sm font-bold text-foreground">{ia.key_paths.length} フロー</p>
          </div>
        </div>
      </div>

      <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
        <h3 className={cn("mb-4 flex items-center gap-2", planningSectionTitleClassName)}>
          <Network className="h-4 w-4 text-primary" />
          サイトマップ
        </h3>
        <div className="space-y-1">
          {ia.site_map.map((node) => (
            <IANodeTree key={node.id} node={node} />
          ))}
        </div>
      </div>

      <div className={planningSurfaceVariants({ tone: "default", padding: "md" })}>
        <h3 className={cn("mb-4 flex items-center gap-2", planningSectionTitleClassName)}>
          <Route className="h-4 w-4 text-primary" />
          主要ユーザーフロー
        </h3>
        <div className="space-y-4">
          {ia.key_paths.map((path, i) => (
            <div key={i}>
              <p className="mb-2 text-sm font-medium text-foreground">{path.name}</p>
              <div className="flex flex-wrap items-center gap-1">
                {path.steps.map((step, j) => (
                  <div key={j} className="flex items-center gap-1">
                    <span className={planningSoftBadgeVariants({ tone: "accent" })}>{step}</span>
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
