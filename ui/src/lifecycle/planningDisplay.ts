import { polishConsoleCopy } from "@/lifecycle/presentation";
import type {
  AnalysisResult,
  Epic,
  FeatureSelection,
  PlanEstimate,
  PlanPreset,
  RecommendedMilestone,
  WbsItem,
} from "@/types/lifecycle";

const PLANNING_COPY_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\bMilestones lack stop conditions\b/gi, "マイルストーンに中止条件がありません"],
  [/\bSpeed-vs-governance assumption is unvalidated\b/gi, "速度重視か統制重視かの前提が未検証です"],
  [/\bImpatient Evaluator has no hard gate\b/gi, "早期離脱ユーザーへのハードゲートがありません"],
  [/\bHistory and recovery scope is unbounded\b/gi, "履歴と復旧のスコープが膨らみやすい状態です"],
  [/\bMulti-agent architectural assumption may foreclose future options\b/gi, "マルチエージェント前提の扱い次第で将来の選択肢を狭める恐れがあります"],
  [/Neither M1 nor M2 has a defined failure signal or halt threshold\./gi, "M1 と M2 のどちらにも、失敗シグナルや中止閾値が定義されていません。"],
  [/The team will ship on schedule rather than on evidence\./gi, "このままでは、根拠ではなく予定に合わせて出荷してしまいます。"],
  [/This is the single highest-probability path to a product that appears to progress while the core assumption goes untested\./gi, "中核仮説を検証しないまま、進んでいるように見える製品を作ってしまう最も起こりやすい経路です。"],
  [/The entire selected feature set assumes users \(represented by Naoki\) will accept onboarding friction in exchange for control and traceability\./gi, "現在の機能選定は、Naoki のような利用者が導入時の摩擦を受け入れてでも統制と追跡可能性を重視する、という前提に立っています。"],
  [/If users actually optimize for speed, the scope is wrong and no current instrumentation will surface this before rollout\./gi, "実際には速度が優先されるなら、スコープは誤っており、現状の計測ではリリース前にそのズレを検知できません。"],
  [/The negative persona is documented but not wired into acceptance criteria or instrumentation\./gi, "ネガティブペルソナは定義されていますが、受け入れ条件や計測設計にはまだ組み込まれていません。"],
  [/Early evaluators who abandon after one incomplete run will not generate actionable signal unless session-completion metrics are captured from day one\./gi, "初回の不完全な実行で離脱する評価者は、初日からセッション完了率を計測しない限り、有効な学習シグナルを残しません。"],
  [/Selected without a size constraint, history and recovery can silently consume M1 capacity\./gi, "履歴と復旧は規模の上限を決めないまま選ぶと、M1 の工数を静かに食い潰します。"],
  [/If it expands beyond single-run restoration, it delays the falsifiable core loop\./gi, "単一 run の復元を超えて広がると、反証可能なコアループの検証を遅らせます。"],
  [/assumption-3 identifies a structural shift in the LLM landscape\./gi, "assumption-3 は LLM 活用の構造変化を指摘しています。"],
  [/If M1 architecture assumes single-agent execution, adding multi-agent coordination later may require rework that is disproportionate to the original build cost\./gi, "M1 の設計が単一エージェント前提だと、後からマルチエージェント協調を足す際の手戻りが初期実装コストに見合わないほど大きくなる恐れがあります。"],
  [/Add explicit failure conditions to both milestones before design begins\./gi, "デザイン着手前に、両方のマイルストーンへ明示的な失敗条件を追加します。"],
  [/Each milestone spec must include: \(a\) the observable failure signal, \(b\) a numeric stop threshold, and \(c\) a named decision owner who can call a halt\./gi, "各マイルストーン仕様には、(a) 観測可能な失敗シグナル、(b) 数値の中止閾値、(c) 停止判断を下せる責任者名を必ず含めます。"],
  [/Milestones without stop conditions create false progress\./gi, "中止条件のないマイルストーンは、進捗しているように見えるだけの誤学習を生みます。"],
  [/\bmilestone-1 and milestone-2\b/gi, "マイルストーン 1 と 2"],
  [/\bProduct Owner\b/gi, "プロダクトオーナー"],
  [/\bPrimary User\b/gi, "主要ユーザー"],
  [/Define the single evidence-to-decision loop as the only shippable unit for Milestone 1\./gi, "Milestone 1 で出荷可能な単位を、単一の根拠から意思決定までのループに限定します。"],
  [/Write it as a falsifiable acceptance test:/gi, "これを反証可能な受け入れ条件として記述します:"],
  [/A user completes \[specific workflow\] and the system produces \[specific traceable output\] within \[time bound\]\./gi, "利用者が [具体的なワークフロー] を完了し、システムが [追跡可能な具体的出力] を [時間上限] 内に生成すること。"],
  [/No feature outside this loop ships in M1\./gi, "このループ外の機能は M1 では出荷しません。"],
  [/scope-skeptic and assumption-2 both flag that scope blur is the primary risk to learning\./gi, "スコープ批判と assumption-2 は、スコープのにじみが学習を阻害する主要リスクだと示しています。"],
  [/Locking the loop definition in design prevents feature creep from obscuring whether the core workflow works\./gi, "デザイン段階でループ定義を固定すると、機能追加でコアワークフローの成立可否が曖昧になるのを防げます。"],
  [/\bComplete the primary workflow\b/gi, "主要ワークフローを完了する"],
  [/\bAdjust settings\b/gi, "設定を調整する"],
  [/\bProtect first-release scope\b/gi, "初回リリースのスコープを守る"],
  [/\bguided onboarding\b/gi, "ガイド付きオンボーディング"],
  [/\bprimary workflow\b/gi, "主要ワークフロー"],
  [/\bstatus visibility\b/gi, "状態の見える化"],
  [/When a user first tries the product/gi, "はじめて製品を使うとき"],
  [/When a user is midway through the product's main task/gi, "主要タスクの途中にいるとき"],
  [/When a product team scopes the first release/gi, "プロダクトチームが初回リリースを絞り込むとき"],
  [/When a returning user resumes the product/gi, "再訪した利用者が作業を再開するとき"],
  [/\bI want the core path to be obvious\b/gi, "最短の導線がすぐ分かってほしい"],
  [/\bI want the current state and next action to stay visible\b/gi, "現在地と次の一手を見失いたくない"],
  [/\bI want a crisp definition of the MVP\b/gi, "MVP の境界を明確にしたい"],
  [/\bI want my previous context to be restored quickly\b/gi, "前回の文脈をすぐに取り戻したい"],
  [/\bSo I can reach value without reading a manual\b/gi, "説明を読まなくても価値に到達できるように"],
  [/\bSo I can complete the workflow without second-guessing what happens next\b/gi, "次に何が起こるか悩まずに完了できるように"],
  [/\bSo I can ship without uncontrolled scope growth\b/gi, "スコープを膨らませずに出荷できるように"],
  [/\bSo I can continue instead of restarting from scratch\b/gi, "最初からやり直さずに続きへ戻れるように"],
  [/\bLanding \/ first view\b/gi, "ランディング / 初期表示"],
  [/\bOnboarding\b/gi, "導入ガイド"],
  [/\bSetup\b/gi, "初期設定"],
  [/\bShare \/ export\b/gi, "共有 / 出力"],
  [/\bnotifications?\b/gi, "通知"],
  [/\bhistory and recovery\b/gi, "履歴と復旧"],
  [/\bpersonalization\b/gi, "パーソナライズ"],
  [/\bresearch workspace\b/gi, "調査ワークスペース"],
  [/\bplanning synthesis\b/gi, "企画統合"],
  [/\bapproval gate\b/gi, "承認ゲート"],
  [/\bartifact lineage\b/gi, "成果物の系譜"],
  [/\brelease gate\b/gi, "リリースゲート"],
  [/\boperator console\b/gi, "運用コンソール"],
  [/\bLifecycle foundation\b/gi, "ライフサイクル基盤"],
  [/\bMilestone validation\b/gi, "マイルストーン検証"],
  [/\bMinimal scope for the selected lifecycle features\b/gi, "最小範囲でライフサイクル機能を検証する構成"],
  [/\bStandard scope for the selected lifecycle features\b/gi, "価値と負荷の均衡を取る標準構成"],
  [/\bFull scope for the selected lifecycle features\b/gi, "差別化要素まで含める拡張構成"],
  [/\bMinimal scope covering the selected use cases and milestone evidence loops\b/gi, "必須ユースケースとマイルストーン検証に絞った最小構成"],
  [/\bStandard scope covering the selected use cases and milestone evidence loops\b/gi, "主要ユースケースと検証ループを押さえる標準構成"],
  [/\bFull scope covering the selected use cases and milestone evidence loops\b/gi, "拡張ユースケースまで含めて検証ループを広げる構成"],
  [/\bModel lifecycle state in the control plane\b/gi, "制御プレーンでライフサイクル状態を扱う"],
  [/\bBackend record, phase flow, and operator UI alignment\b/gi, "バックエンド記録、フェーズ進行、運用 UI をそろえる"],
  [/\bPersist phase state, artifacts, releases, and feedback\./gi, "フェーズ状態、成果物、リリース、フィードバックを保持する。"],
  [/^(.+)\s+track$/gi, "$1トラック"],
  [/^Define acceptance for (.+)$/gi, "$1 の受け入れ条件を定義"],
  [/^Implement (.+)$/gi, "$1 を実装"],
  [/^Verify (.+)$/gi, "$1 を検証"],
  [/^Validate (.+)$/gi, "$1 の完了判定"],
  [/\bRun discovery-to-build workflow\b/gi, "調査からビルドまでを実行する"],
  [/\bRecover degraded research lane\b/gi, "劣化した調査レーンを回復する"],
  [/\bApprove or rework a phase\b/gi, "フェーズを承認または差し戻す"],
  [/\bTrace artifact lineage\b/gi, "成果物の系譜を追跡する"],
  [/\bConfigure policies and team routing\b/gi, "ポリシーとチームルーティングを設定する"],
  [/\bMonitor active runs and intervene\b/gi, "実行中の run を監視して介入する"],
  [/\bReview release readiness and publish outcome\b/gi, "リリース準備を確認して結果を記録する"],
  [/\bComplete guided onboarding\b/gi, "ガイド付きオンボーディングを完了する"],
  [/\bReview status and next action\b/gi, "状態と次アクションを確認する"],
  [/\bRecover previous work context\b/gi, "前回の作業文脈を復旧する"],
  [/\bConfigure notifications and preferences\b/gi, "通知と基本設定を構成する"],
  [/\bAdminister workspace settings\b/gi, "ワークスペース設定を管理する"],
  [/\bplanner\b/gi, "プランナー"],
  [/\bfrontend-builder\b/gi, "フロントエンド担当"],
  [/\bbackend-builder\b/gi, "バックエンド担当"],
  [/\breviewer\b/gi, "レビュー担当"],
  [/\bqa-engineer\b/gi, "QA担当"],
  [/\bacceptance-design\b/gi, "受け入れ設計"],
  [/\binstrumentation-planning\b/gi, "計測設計"],
  [/\bworkflow-design\b/gi, "ワークフロー設計"],
  [/\bconfiguration-management\b/gi, "設定管理"],
  [/\binteraction-design\b/gi, "インタラクション設計"],
  [/\bmilestone-review\b/gi, "マイルストーン判定"],
  [/\bquality-gating\b/gi, "品質ゲート"],
  [/\bdomain-modeling\b/gi, "ドメイン設計"],
  [/\bdelivery-review\b/gi, "デリバリーレビュー"],
  [/\bpolicy-review\b/gi, "ポリシーレビュー"],
  [/\bacceptance-testing\b/gi, "受け入れ検証"],
  [/\bquality-assurance\b/gi, "品質保証"],
  [/\bresponsive-ui\b/gi, "レスポンシブUI"],
  [/\bapi-design\b/gi, "API設計"],
  [/\bConfiguration and recovery\b/gi, "設定と復旧"],
  [/\bCore workflow ready\b/gi, "コアワークフロー成立"],
  [/\bRelease quality\b/gi, "リリース品質"],
  [/\bEvidence-to-build loop\b/gi, "根拠からビルドまでのループ"],
  [/\bGoverned delivery\b/gi, "統制されたデリバリー"],
  [/\bOperator-ready release\b/gi, "運用可能なリリース"],
  [/\bGovernance\b/gi, "統制"],
  [/\bQuality control\b/gi, "品質管理"],
  [/\bPlatform 設定\b/gi, "プラットフォーム設定"],
  [/Trace\s+成果物の系譜/gi, "成果物の系譜を追跡する"],
  [/\bFirst-run success\b/gi, "初回成功フロー"],
  [/\bConfiguration\b/gi, "設定"],
  [/\bResults\b/gi, "結果"],
  [/\bAdmin\b/gi, "管理者"],
  [/Adding convenience features early would blur whether the core workflow is actually working\./gi, "便利機能を早期に足すと、コアワークフローが本当に機能しているか判別しにくくなります。"],
  [/Keep the first milestone focused on a single evidence-to-decision loop\./gi, "最初のマイルストーンは、根拠から意思決定までの単一ループに絞ります。"],
  [/Naoki will trade setup breadth for stronger control and traceability\./gi, "Naoki は導入範囲の広さよりも、強い統制と追跡可能性を優先します。"],
  [/\bImpatient Evaluator\b/gi, "すぐ離脱する評価者"],
  [/Leaves before the core loop demonstrates value\./gi, "コアループの価値が見える前に離脱します。"],
  [/Judges the product after one incomplete run\./gi, "1 回の不完全な実行だけで製品を判断します。"],
  [/Make the first successful workflow obvious and measurable\./gi, "最初の成功フローがひと目で分かり、計測できる状態にします。"],
  [/If Core workflow ready cannot show observable completion evidence, stop scope expansion and re-open planning\./gi, "コアワークフローの完了で観測可能な証跡を示せない場合は、スコープ拡張を止めて planning を再開します。"],
  [/Treat phase-by-phase (?:artifact lineage|成果物の系譜) as a first-class surface so approval evidence never gets lost\./gi, "フェーズごとの成果物の系譜を主軸として扱い、承認判断の根拠を失わないようにします。"],
  [/Stabilize handoff and rework control before widening multi-agent parallelism\./gi, "マルチエージェントの並列実行を広げる前に、handoff と差し戻しの制御面を固めます。"],
  [/Milestones must be falsifiable instead of narrative\./gi, "マイルストーンは物語ではなく、反証可能でなければなりません。"],
  [/\bBalanced Product\b/gi, "バランス型プロダクト"],
  [/general-purpose digital products with mixed audiences/gi, "幅広い利用者が混在する汎用デジタルプロダクト"],
  [/progressive disclosure and responsive content grouping/gi, "段階的な情報開示とレスポンシブな情報グルーピング"],
  [/clear semantic hierarchy and keyboard-safe interactions/gi, "明確な意味階層とキーボードでも迷わないインタラクション"],
  [/subtle entry fades/gi, "穏やかなフェードイン"],
  [/hover elevation/gi, "hover 時の浮き上がり"],
  [/clear focus rings/gi, "明確なフォーカスリング"],
  [/generic dashboard filler/gi, "情報密度の低いダッシュボード装飾"],
  [/weak empty states/gi, "弱い空状態"],
  [/low-information hero sections/gi, "情報量の少ないヒーロー領域"],
  [/The product should stay adaptable while preserving clear task hierarchy and predictable interactions\./gi, "プロダクトは適応性を保ちつつ、タスク階層の明快さと予測可能な操作感を維持します。"],
];

const PLANNING_EXACT_TEXT_REPLACEMENTS: Record<string, string> = {
  clear: "明快",
  adaptive: "適応的",
  modern: "モダン",
  balanced: "均衡",
  practical: "実務的",
};

const FEATURE_CATEGORY_LABELS: Record<string, string> = {
  "must-be": "当たり前品質",
  "one-dimensional": "一元的品質",
  attractive: "魅力品質",
  indifferent: "無関心",
  reverse: "逆転",
};

const FEATURE_CATEGORY_TITLES: Record<string, string> = {
  "must-be": "当たり前品質（必須機能）",
  "one-dimensional": "一元的品質（効用機能）",
  attractive: "魅力品質（差別化機能）",
};

const FEATURE_CATEGORY_DESCRIPTIONS: Record<string, string> = {
  "must-be": "製品として欠かせない基礎機能です。除外すると体験の前提が崩れます。",
  "one-dimensional": "実装の質に比例して評価が伸びる領域です。初回体験との釣り合いで選びます。",
  attractive: "あると差がつく魅力機能です。コアループが立った後でも追加できます。",
};

const PRIORITY_LABELS: Record<string, string> = {
  must: "必須",
  should: "推奨",
  could: "任意",
  wont: "対象外",
};

const COST_LABELS: Record<string, string> = {
  low: "低コスト",
  medium: "中コスト",
  high: "高コスト",
};

const PRESET_LABELS: Record<PlanPreset, string> = {
  minimal: "最小構成",
  standard: "標準構成",
  full: "拡張構成",
};

const PRESET_DESCRIPTIONS: Record<PlanPreset, string> = {
  minimal: "必須だけで検証を最短距離に寄せる",
  standard: "価値と実装負荷の均衡を取る",
  full: "差別化機能まで含めて広く押さえる",
};

const EPIC_PRIORITY_LABELS: Record<string, string> = {
  must: "必須",
  should: "推奨",
  could: "任意",
};

const ASSIGNEE_TYPE_LABELS: Record<string, string> = {
  agent: "AI担当",
  human: "人担当",
};

function applyPlanningCopyReplacements(value: string): string {
  return PLANNING_COPY_REPLACEMENTS.reduce(
    (acc, [pattern, replacement]) => acc.replace(pattern, replacement),
    value,
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function normalizePlanningText(value: unknown, fallback = ""): string {
  const base = typeof value === "string" ? value : fallback;
  const cleaned = applyPlanningCopyReplacements(
    polishConsoleCopy(applyPlanningCopyReplacements(base)),
  )
    .replace(/\bOperational Clarity\b/gi, "運用明瞭性")
    .replace(
      /phase ごとの 成果物の系譜 を first-class にし、承認判断の根拠を失わないようにする/gi,
      "フェーズごとの成果物の系譜を主軸として扱い、承認判断の根拠を失わないようにします。",
    )
    .replace(
      /If (.+?) cannot show observable completion (?:根拠|evidence), stop scope expansion and re-open (?:企画|planning)\./gi,
      "$1 で観測可能な完了証跡を示せない場合は、スコープ拡張を止めて企画を見直します。",
    )
    .replace(
      /If this remains in the first cut, the team may lose falsifiability and review speed\./gi,
      "これを初期スコープに残すと、仮説の反証可能性とレビュー速度を失う恐れがあります。",
    )
    .replace(/\brelease readiness\b/gi, "リリース準備")
    .replace(/The team will ship on schedule rather than on 根拠\./gi, "このままでは、根拠ではなく予定に合わせて出荷してしまいます。")
    .replace(/This is the single highest-probability path to a product that appears to progress while the core 前提条件 goes untested\./gi, "中核仮説を検証しないまま、進んでいるように見える製品を作ってしまう最も起こりやすい経路です。")
    .replace(/If users actually optimize for speed, the scope is wrong and no current instrumentation will surface this before rollout\./gi, "実際には速度が優先されるなら、スコープは誤っており、現状の計測ではリリース前にそのズレを検知できません。")
    .replace(/\bproduct lead\b/gi, "プロダクト責任者")
    .replace(/\bresearch lead\b/gi, "リサーチ責任者")
    .replace(/\bengineering lead\b/gi, "開発責任者")
    .replace(/\barchitecture lead\b/gi, "アーキテクト責任者")
    .replace(/\bdesign kickoff\b/gi, "デザイン着手前")
    .replace(/\bend of M1 user testing\b/gi, "M1 ユーザーテスト終了前")
    .replace(/\bM1 instrumentation spec\b/gi, "M1 計測仕様確定前")
    .replace(/\bM1 design spec\b/gi, "M1 デザイン仕様確定前")
    .replace(/\bM1 technical design review\b/gi, "M1 技術設計レビュー前")
    .replace(/\bM1\b/g, "M1")
    .replace(/\bM2\b/g, "M2")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) return fallback;
  return PLANNING_EXACT_TEXT_REPLACEMENTS[cleaned.toLowerCase()] ?? cleaned;
}

export function normalizePlanningCopyList(values?: string[]): string[] {
  return (values ?? [])
    .map((item) => normalizePlanningText(item))
    .filter((item) => item.length > 0);
}

export function planningFeatureCategoryLabel(category: string): string {
  return FEATURE_CATEGORY_LABELS[category] ?? normalizePlanningText(category, category);
}

export function planningFeatureCategoryTitle(category: string): string {
  return FEATURE_CATEGORY_TITLES[category] ?? planningFeatureCategoryLabel(category);
}

export function planningFeatureCategoryDescription(category: string): string {
  return FEATURE_CATEGORY_DESCRIPTIONS[category] ?? "価値仮説と実装負荷の釣り合いを見て残すか決めます。";
}

export function planningPriorityLabel(priority: string): string {
  return PRIORITY_LABELS[priority] ?? normalizePlanningText(priority, priority);
}

export function planningCostLabel(cost: string): string {
  return COST_LABELS[cost] ?? normalizePlanningText(cost, cost);
}

export function planningPresetLabel(preset: PlanPreset): string {
  return PRESET_LABELS[preset];
}

export function planningPresetDescription(preset: PlanPreset): string {
  return PRESET_DESCRIPTIONS[preset];
}

export function planningEpicPriorityLabel(priority: string): string {
  return EPIC_PRIORITY_LABELS[priority] ?? normalizePlanningText(priority, priority);
}

export function planningAssigneeTypeLabel(type: string): string {
  return ASSIGNEE_TYPE_LABELS[type] ?? normalizePlanningText(type, type);
}

export type PlanningFeatureDisplay = {
  index: number;
  feature: FeatureSelection;
  displayFeature: string;
  displayRationale: string;
  categoryLabel: string;
  categoryTitle: string;
  categoryDescription: string;
  priorityLabel: string;
  costLabel: string;
};

export type PlanningDisplayEpic = {
  epic: Epic;
  displayName: string;
  displayDescription: string;
  displayUseCases: string[];
  priorityLabel: string;
};

export type PlanningDisplayWbsItem = {
  item: WbsItem;
  displayTitle: string;
  displayDescription: string;
  displayAssignee: string;
  displaySkills: string[];
};

export type PlanningPlanEstimateDisplay = {
  plan: PlanEstimate;
  displayLabel: string;
  displayDescription: string;
  scheduledWorkdays: number;
  durationLabel: string;
  durationNote: string;
  staffingLabel: string;
  staffingNote: string;
  displayAgentsUsed: string[];
  displaySkillsUsed: string[];
  displayEpics: PlanningDisplayEpic[];
  displayWbs: PlanningDisplayWbsItem[];
};

export type PlanningRecommendedMilestoneDisplay = {
  id: string;
  displayName: string;
  displayCriteria: string;
  displayRationale: string;
  displayDependsOnUseCases: string[];
  phase: RecommendedMilestone["phase"];
  canonical: RecommendedMilestone;
};

export function buildPlanningFeatureDisplay(features: FeatureSelection[]): PlanningFeatureDisplay[] {
  return features.map((feature, index) => ({
    index,
    feature,
    displayFeature: normalizePlanningText(feature.feature, feature.feature),
    displayRationale: normalizePlanningText(feature.rationale, feature.rationale),
    categoryLabel: planningFeatureCategoryLabel(feature.category),
    categoryTitle: planningFeatureCategoryTitle(feature.category),
    categoryDescription: planningFeatureCategoryDescription(feature.category),
    priorityLabel: planningPriorityLabel(feature.priority),
    costLabel: planningCostLabel(feature.implementation_cost),
  }));
}

export function buildPlanningPlanEstimateDisplay(planEstimates: PlanEstimate[]): PlanningPlanEstimateDisplay[] {
  return planEstimates.map((plan) => {
    const scheduledWorkdays = Math.max(
      ...plan.wbs.map((item) => item.start_day + item.duration_days),
      1,
    );
    const staffRoleMap = new Map<string, string>();
    plan.wbs.forEach((item) => {
      if (!staffRoleMap.has(item.assignee)) {
        staffRoleMap.set(item.assignee, normalizePlanningText(item.assignee, item.assignee));
      }
    });
    if (staffRoleMap.size === 0) {
      plan.agents_used.forEach((item) => {
        if (!staffRoleMap.has(item)) {
          staffRoleMap.set(item, normalizePlanningText(item, item));
        }
      });
    }
    const staffRoles = [...staffRoleMap.values()];
    const peakParallelAssignees = Math.max(
      ...Array.from({ length: scheduledWorkdays }, (_, day) => {
        const activeAssignees = new Set(
          plan.wbs
            .filter((item) => item.start_day <= day && day < item.start_day + item.duration_days)
            .map((item) => item.assignee),
        );
        return activeAssignees.size;
      }),
      staffRoles.length > 0 ? 1 : 0,
    );
    const visibleRoles = staffRoles.slice(0, 3);
    const remainingRoles = staffRoles.length - visibleRoles.length;
    const staffingRoleSummary = remainingRoles > 0
      ? `${visibleRoles.join("・")} ほか${remainingRoles}役割`
      : visibleRoles.join("・");
    return {
      plan,
      displayLabel: planningPresetLabel(plan.preset),
      displayDescription: normalizePlanningText(plan.description, planningPresetDescription(plan.preset)),
      scheduledWorkdays,
      durationLabel: `${plan.duration_weeks}週`,
      durationNote: `${scheduledWorkdays}営業日を 5営業日/週 で換算`,
      staffingLabel: `${staffRoles.length}役割 / 最大${peakParallelAssignees}並列`,
      staffingNote: staffingRoleSummary,
      displayAgentsUsed: plan.agents_used.map((item) => normalizePlanningText(item, item)),
      displaySkillsUsed: plan.skills_used.map((item) => normalizePlanningText(item, item)),
      displayEpics: plan.epics.map((epic) => ({
        epic,
        displayName: normalizePlanningText(epic.name, epic.name),
        displayDescription: normalizePlanningText(epic.description, epic.description),
        displayUseCases: epic.use_cases.map((item) => normalizePlanningText(item, item)),
        priorityLabel: planningEpicPriorityLabel(epic.priority),
      })),
      displayWbs: plan.wbs.map((item) => ({
        item,
        displayTitle: normalizePlanningText(item.title, item.title),
        displayDescription: normalizePlanningText(item.description, item.description),
        displayAssignee: normalizePlanningText(item.assignee, item.assignee),
        displaySkills: item.skills.map((skill) => normalizePlanningText(skill, skill)),
      })),
    };
  });
}

function parseRecommendedMilestone(raw: unknown): RecommendedMilestone | null {
  const record = asRecord(raw);
  const id = asString(record.id);
  const name = asString(record.name);
  const criteria = asString(record.criteria);
  if (!id || !name || !criteria) return null;
  const phase = asString(record.phase, "beta");
  return {
    id,
    name,
    criteria,
    rationale: asString(record.rationale),
    phase: (["alpha", "beta", "release"].includes(phase) ? phase : "beta") as RecommendedMilestone["phase"],
    depends_on_use_cases: asArray<string>(record.depends_on_use_cases ?? record.dependsOnUseCases),
  };
}

export function buildPlanningRecommendedMilestoneDisplay(
  analysis: AnalysisResult | null,
): PlanningRecommendedMilestoneDisplay[] {
  const displayMilestones = analysis?.recommended_milestones ?? [];
  const canonicalMilestones = asArray(
    asRecord(analysis?.canonical).recommended_milestones,
  )
    .map(parseRecommendedMilestone)
    .filter((item): item is RecommendedMilestone => item !== null);
  const canonicalById = new Map(canonicalMilestones.map((item) => [item.id, item]));

  return displayMilestones.map((item) => ({
    id: item.id,
    displayName: normalizePlanningText(item.name, item.name),
    displayCriteria: normalizePlanningText(item.criteria, item.criteria),
    displayRationale: normalizePlanningText(item.rationale, item.rationale),
    displayDependsOnUseCases: normalizePlanningCopyList(item.depends_on_use_cases),
    phase: item.phase,
    canonical: canonicalById.get(item.id) ?? item,
  }));
}
