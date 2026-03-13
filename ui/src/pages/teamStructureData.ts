import type { TeamDef as ApiTeamDef } from "@/api/mission-control";

interface TeamMeta {
  description: string;
  emptyState: string;
  recommendedRoles: string[];
}

export const AVAILABLE_MODELS = [
  "anthropic/claude-sonnet-4-6",
  "openai/gpt-5-mini",
  "moonshot/kimi-k2.5",
  "zhipu/glm-4-plus",
  "gemini/gemini-3-pro-preview",
];

const CORE_TEAM_DEFS: ApiTeamDef[] = [
  { id: "product", name: "Product Strategy", nameJa: "プロダクト戦略", icon: "Network", color: "text-orange-400", bg: "bg-orange-600" },
  { id: "research", name: "Research Intelligence", nameJa: "リサーチ", icon: "PenTool", color: "text-emerald-400", bg: "bg-emerald-600" },
  { id: "design", name: "UX & Design Systems", nameJa: "UX / デザインシステム", icon: "Palette", color: "text-purple-400", bg: "bg-pink-600" },
  { id: "development", name: "Application Engineering", nameJa: "アプリケーション開発", icon: "Code2", color: "text-blue-400", bg: "bg-blue-600" },
  { id: "platform", name: "Platform & Infra", nameJa: "プラットフォーム / 基盤", icon: "Monitor", color: "text-sky-400", bg: "bg-sky-600" },
  { id: "data", name: "Data & Evaluation", nameJa: "データ / 評価", icon: "Zap", color: "text-cyan-400", bg: "bg-cyan-600" },
  { id: "security", name: "Security & Governance", nameJa: "セキュリティ / ガバナンス", icon: "Shield", color: "text-red-400", bg: "bg-red-600" },
  { id: "operations", name: "Operations & Release", nameJa: "運用 / リリース", icon: "Bot", color: "text-amber-400", bg: "bg-amber-600" },
];

const KNOWN_DYNAMIC_TEAM_DEFS: Record<string, ApiTeamDef> = {
  advertising: {
    id: "advertising",
    name: "Advertising",
    nameJa: "広告運用",
    icon: "Megaphone",
    color: "text-amber-400",
    bg: "bg-amber-600",
  },
};

const TEAM_META: Record<string, TeamMeta> = {
  product: {
    description: "企画、優先順位、承認判断、全体ハンドオフを束ねる中核チーム。",
    emptyState: "まだ product specialist が配備されていません。",
    recommendedRoles: ["Product Orchestrator", "Delivery Manager"],
  },
  research: {
    description: "市場、競合、ユーザー仮説を検証し、planning の根拠を作るチーム。",
    emptyState: "調査担当が不在です。research の質が落ちます。",
    recommendedRoles: ["Competitive Researcher", "User Insight Analyst"],
  },
  design: {
    description: "IA、UX、プロトタイプ品質、アクセシビリティを引き上げるチーム。",
    emptyState: "design specialist が未配備です。",
    recommendedRoles: ["UX Architect", "Design Critic"],
  },
  development: {
    description: "UI/API の実装と統合を進め、成果物に落とし込むチーム。",
    emptyState: "実装担当が不足しています。",
    recommendedRoles: ["Frontend Builder", "Backend Integrator"],
  },
  platform: {
    description: "実行基盤、観測性、デプロイ導線を支えるチーム。",
    emptyState: "platform 担当がいません。実行基盤が弱くなります。",
    recommendedRoles: ["Platform Engineer"],
  },
  data: {
    description: "評価、実験、品質計測を担当し、意思決定を定量で支えるチーム。",
    emptyState: "評価担当がいません。改善サイクルが鈍ります。",
    recommendedRoles: ["Evaluation Analyst"],
  },
  security: {
    description: "安全性、ガバナンス、承認ゲートを監督するチーム。",
    emptyState: "security / governance の監視役が未配備です。",
    recommendedRoles: ["Safety Guardian"],
  },
  operations: {
    description: "リリース運用、監視、インシデント初動を担うチーム。",
    emptyState: "運用 / リリース担当が未配備です。",
    recommendedRoles: ["Release Operator"],
  },
  advertising: {
    description: "媒体運用、配信最適化、クリエイティブ監査を担うチーム。",
    emptyState: "広告運用担当がまだ配備されていません。",
    recommendedRoles: ["Campaign Strategist", "Compliance Reviewer"],
  },
};

const TEAM_ORDER = [...CORE_TEAM_DEFS.map((team) => team.id), ...Object.keys(KNOWN_DYNAMIC_TEAM_DEFS)];

function slugToLabel(value: string): string {
  return value
    .split(/[-_]+/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function buildUnknownTeamDef(teamId: string): ApiTeamDef {
  return KNOWN_DYNAMIC_TEAM_DEFS[teamId] ?? {
    id: teamId,
    name: slugToLabel(teamId),
    nameJa: slugToLabel(teamId),
    icon: "Users",
    color: "text-slate-400",
    bg: "bg-slate-600",
  };
}

function sortTeams(left: ApiTeamDef, right: ApiTeamDef): number {
  const leftIndex = TEAM_ORDER.indexOf(left.id);
  const rightIndex = TEAM_ORDER.indexOf(right.id);
  if (leftIndex >= 0 || rightIndex >= 0) {
    return (leftIndex >= 0 ? leftIndex : Number.MAX_SAFE_INTEGER) - (rightIndex >= 0 ? rightIndex : Number.MAX_SAFE_INTEGER);
  }
  return left.name.localeCompare(right.name, "ja");
}

export function mergeTeamDefs(teamDefs?: ApiTeamDef[], teamIds?: Iterable<string | null | undefined>): ApiTeamDef[] {
  const merged = new Map<string, ApiTeamDef>(CORE_TEAM_DEFS.map((team) => [team.id, team]));
  for (const team of teamDefs ?? []) {
    merged.set(team.id, {
      ...(merged.get(team.id) ?? buildUnknownTeamDef(team.id)),
      ...team,
    });
  }
  for (const teamId of teamIds ?? []) {
    const normalized = String(teamId ?? "").trim();
    if (!normalized || merged.has(normalized)) continue;
    merged.set(normalized, buildUnknownTeamDef(normalized));
  }
  return [...merged.values()].sort(sortTeams);
}

export function resolveTeamDef(teamId: string | null | undefined, teamDefs: ApiTeamDef[]): ApiTeamDef {
  const normalized = String(teamId ?? "").trim() || "product";
  return teamDefs.find((team) => team.id === normalized) ?? buildUnknownTeamDef(normalized);
}

export function getTeamMeta(teamId: string): TeamMeta {
  return TEAM_META[teamId] ?? {
    description: `${slugToLabel(teamId)} チームの役割説明は未設定です。`,
    emptyState: `${slugToLabel(teamId)} のメンバーはまだ配備されていません。`,
    recommendedRoles: [],
  };
}

export function buildModelOptions(currentModel?: string): string[] {
  const normalized = String(currentModel ?? "").trim();
  if (!normalized) return AVAILABLE_MODELS;
  return [normalized, ...AVAILABLE_MODELS.filter((model) => model !== normalized)];
}
