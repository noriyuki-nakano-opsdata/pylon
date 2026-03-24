import type {
  Competitor,
  IAAnalysis,
  IANode,
  JobStory,
  JourneyPhase,
  KanoFeature,
  MarketResearch,
  UserJourneyMap,
  UserStory,
} from "@/types/lifecycle";
import type { ResearchQualityAudit } from "@/lifecycle/researchAudit";

export interface ResearchExperienceFrames {
  personaLabel: string;
  personaSummary: string;
  designPrinciples: string[];
  userJourney: UserJourneyMap;
  userStories: UserStory[];
  jobStories: JobStory[];
  kanoFeatures: KanoFeature[];
  iaAnalysis: IAAnalysis;
}

interface BuildResearchExperienceFramesParams {
  projectSpec?: string;
  research: MarketResearch;
  audit: ResearchQualityAudit;
  trustedCompetitors: Competitor[];
  trustedTrends: string[];
  trustedOpportunities: string[];
  trustedThreats: string[];
  trustedUserSignals: string[];
  trustedPainPoints: string[];
}

function unique(items: Array<string | undefined | null>, limit = 6): string[] {
  const seen = new Set<string>();
  return items
    .map((item) => (item ?? "").trim())
    .filter(Boolean)
    .filter((item) => !seen.has(item) && (seen.add(item), true))
    .slice(0, limit);
}

function clip(text: string, limit = 108): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, limit).trimEnd()}...`;
}

function inferPersonaLabel(segment: string, spec?: string): string {
  const normalized = segment.trim();
  if (normalized === "B2C") return "B2C 向けサービスの導入責任者";
  if (normalized === "B2B") return "B2B SaaS の導入責任者";
  if (normalized) return normalized;
  if (spec?.includes("開発")) return "プロダクト責任者 / 開発責任者";
  return "導入責任者";
}

function buildJourneyTouchpoint(
  phase: JourneyPhase,
  persona: string,
  values: {
    action: string;
    touchpoint: string;
    pain?: string;
    opportunity?: string;
    emotion: "positive" | "neutral" | "negative";
  },
) {
  return {
    phase,
    persona,
    action: clip(values.action, 84),
    touchpoint: clip(values.touchpoint, 64),
    pain_point: values.pain ? clip(values.pain, 96) : undefined,
    opportunity: values.opportunity ? clip(values.opportunity, 96) : undefined,
    emotion: values.emotion,
  };
}

function buildSiteNode(
  id: string,
  label: string,
  priority: IANode["priority"],
  children: string[],
  description?: string,
): IANode {
  return {
    id,
    label,
    priority,
    description,
    children: children.map((child, index) => ({
      id: `${id}-${index + 1}`,
      label: child,
      priority: priority === "primary" ? "secondary" : "utility",
    })),
  };
}

export function buildResearchExperienceFrames(
  params: BuildResearchExperienceFramesParams,
): ResearchExperienceFrames {
  const segment = inferPersonaLabel(params.research.user_research?.segment ?? "", params.projectSpec);
  const pains = unique([
    ...params.trustedPainPoints,
    ...params.trustedThreats,
    ...params.audit.issues,
    ...(params.research.open_questions ?? []),
  ], 6);
  const gains = unique([
    ...params.trustedOpportunities,
    ...(params.research.winning_theses ?? []),
    ...params.trustedUserSignals,
    ...params.trustedTrends,
  ], 6);
  const marketSignals = unique([
    ...params.trustedTrends,
    ...params.trustedUserSignals,
    ...(params.research.winning_theses ?? []),
  ], 5);
  const competitorNames = unique(params.trustedCompetitors.map((item) => item.name), 3);

  const primaryPain = pains[0] ?? "導入判断に必要な根拠が分散している";
  const secondaryPain = pains[1] ?? "初期運用の摩擦が事前に見えにくい";
  const primaryGain = gains[0] ?? "運用品質と説明責任を両立したい";
  const secondaryGain = gains[1] ?? "比較から意思決定までを短時間で終えたい";
  const tertiaryGain = gains[2] ?? "未解決の前提を抱えたままでも安全に次工程へ進みたい";
  const firstCompetitor = competitorNames[0] ?? "既存の代替手段";
  const secondCompetitor = competitorNames[1] ?? "周辺の隣接サービス";
  const signalLead = marketSignals[0] ?? "信頼できる根拠を重視する傾向";

  const userJourney: UserJourneyMap = {
    persona_name: segment,
    touchpoints: [
      buildJourneyTouchpoint("awareness", segment, {
        action: `市場変化を察知し、${firstCompetitor} を含む候補を探し始める`,
        touchpoint: "検索 / 紹介 / 比較記事",
        pain: primaryPain,
        opportunity: signalLead,
        emotion: params.audit.semanticReady ? "neutral" : "negative",
      }),
      buildJourneyTouchpoint("consideration", segment, {
        action: "競合と代替手段を比較し、信頼できる根拠だけを残す",
        touchpoint: "比較表 / ベンダーサイト / 第三者レポート",
        pain: secondaryPain,
        opportunity: primaryGain,
        emotion: params.trustedCompetitors.length > 0 ? "neutral" : "negative",
      }),
      buildJourneyTouchpoint("acquisition", segment, {
        action: "導入条件、稟議材料、失敗条件を確認して採否を判断する",
        touchpoint: "稟議 / デモ / セキュリティレビュー",
        pain: params.research.open_questions?.[0] ?? primaryPain,
        opportunity: secondaryGain,
        emotion: params.audit.semanticReady ? "positive" : "negative",
      }),
      buildJourneyTouchpoint("usage", segment, {
        action: "初期運用を安定させ、チームの摩擦を減らす",
        touchpoint: "セットアップ / 運用パネル / 定着支援",
        pain: secondaryPain,
        opportunity: params.trustedOpportunities[1] ?? tertiaryGain,
        emotion: params.research.tech_feasibility.score >= 0.7 ? "positive" : "neutral",
      }),
      buildJourneyTouchpoint("advocacy", segment, {
        action: "成果を社内へ説明し、継続利用と横展開につなげる",
        touchpoint: "成果レポート / KPI 共有 / 運用レビュー",
        pain: params.trustedThreats[0] ?? "価値の説明責任が弱いと継続利用が止まる",
        opportunity: tertiaryGain,
        emotion: "neutral",
      }),
    ],
  };

  const userStories: UserStory[] = [
    {
      role: segment,
      action: "信頼できる根拠だけで比較したい",
      benefit: "候補を短時間で絞り、誤った比較を避けられる",
      priority: "must",
      acceptance_criteria: [
        "競合と外部根拠が混ざらずに整理されている",
        "対象外の候補は隔離されている",
      ],
    },
    {
      role: segment,
      action: "未解決の論点と停止理由を先に把握したい",
      benefit: "どこまで企画に持ち込めるかを判断できる",
      priority: "must",
      acceptance_criteria: [
        "品質ゲート未達の理由が一読で分かる",
        "次に取るべき回復アクションが提示される",
      ],
    },
    {
      role: segment,
      action: "価値仮説と運用上の差別化を説明したい",
      benefit: "社内合意を取りやすくなり、企画へ引き継ぎやすい",
      priority: "should",
      acceptance_criteria: [
        "有力仮説が企画に渡せる言い回しで整理される",
        "導入後の運用価値がひと目で伝わる",
      ],
    },
  ];

  const jobStories: JobStory[] = [
    {
      situation: `候補が多く、${firstCompetitor} との違いを短時間で説明しなければならないとき`,
      motivation: "信頼できる根拠だけで比較軸をそろえたい",
      outcome: "誤った候補を早い段階で外し、導入判断を進められる",
      priority: "core",
      related_features: ["信頼できる根拠", "隔離した項目", "競合分析"],
    },
    {
      situation: "企画へ進む前に、未解決の前提とリスクを明確にしたいとき",
      motivation: "停止理由と回復戦略を一つの面で確認したい",
      outcome: "再調査するか、条件付きで進むかを迷わず決められる",
      priority: "supporting",
      related_features: ["停止理由", "回復オペレーション", "品質ゲート"],
    },
    {
      situation: "導入後の運用品質や説明責任まで含めて価値を社内共有したいとき",
      motivation: `「${primaryGain}」につながる価値仮説を言語化したい`,
      outcome: "ロードマップと成功条件を関係者に共有しやすくなる",
      priority: "aspirational",
      related_features: ["企画に渡す主要示唆", "KANO仮説", "IA仮説"],
    },
  ];

  const kanoFeatures: KanoFeature[] = [
    {
      feature: "信頼できる外部根拠の明示",
      category: "must-be",
      user_delight: 0.25,
      implementation_cost: "low",
      rationale: "根拠が曖昧だと比較そのものが成立せず、導入判断の前提が崩れます。",
    },
    {
      feature: "競合との差別化が一目で分かる比較",
      category: "one-dimensional",
      user_delight: 0.62,
      implementation_cost: "medium",
      rationale: `${firstCompetitor} や ${secondCompetitor} と並べたときに、何が違うかがそのまま意思決定速度に直結します。`,
    },
    {
      feature: "未解決の前提を抱えたままでも安全に企画へ渡せるガードレール",
      category: "attractive",
      user_delight: 0.84,
      implementation_cost: "medium",
      rationale: "完全に揃わない調査でも、持ち込み条件が明示されていれば次工程での手戻りを減らせます。",
    },
    {
      feature: "運用品質と説明責任を示す価値ストーリー",
      category: "attractive",
      user_delight: 0.91,
      implementation_cost: "high",
      rationale: `最終的には「${primaryGain}」が評価軸になりやすく、機能数だけでは勝ち切れません。`,
    },
  ];

  const siteMap = [
    buildSiteNode("decision", "判断サマリー", "primary", [
      "信頼できる根拠",
      "隔離した項目",
      "次に取る行動",
    ], "まず進めるか止めるかを判断する入口"),
    buildSiteNode("people", "人と仕事の構造", "primary", [
      "ユーザージャーニー",
      "ユーザーストーリー",
      "ジョブストーリー / JTBD",
      "KANO仮説",
    ], "誰の何の仕事を助けるかを整理する領域"),
    buildSiteNode("market", "市場と競争環境", "primary", [
      "市場トレンド",
      "競合分析",
      "機会と脅威",
      "技術実現性",
    ], "市場妥当性と差別化を検証する領域"),
    buildSiteNode("governance", "信頼性と未解決論点", "secondary", [
      "品質ゲート",
      "エージェント健全性",
      "反対意見",
      "未解決の問い",
    ], "次工程へ渡す前の監査と残課題"),
  ];

  const iaAnalysis: IAAnalysis = {
    navigation_model: "hub-and-spoke",
    site_map: siteMap,
    key_paths: [
      {
        name: "企画に進めるか判断する",
        steps: ["判断サマリー", "信頼できる根拠", "隔離した項目", "次に取る行動"],
      },
      {
        name: "誰のどの仕事を支えるか理解する",
        steps: ["人と仕事の構造", "ユーザージャーニー", "ジョブストーリー / JTBD", "KANO仮説"],
      },
      {
        name: "市場妥当性を検証する",
        steps: ["市場と競争環境", "市場トレンド", "競合分析", "機会と脅威"],
      },
    ],
  };

  return {
    personaLabel: segment,
    personaSummary: `${segment} は「${clip(primaryPain, 52)}」を避けながら、「${clip(primaryGain, 52)}」を確実に説明できることを求めています。`,
    designPrinciples: unique([
      "判断より先に監査ログを読ませず、まず進めるか止めるかを決められる順に並べる",
      `「${clip(primaryPain, 40)}」に対応する根拠と打ち手を同じ視野に置く`,
      `価値仮説は「${clip(primaryGain, 42)}」へつながる言葉でそろえる`,
    ], 3),
    userJourney,
    userStories,
    jobStories,
    kanoFeatures,
    iaAnalysis,
  };
}
