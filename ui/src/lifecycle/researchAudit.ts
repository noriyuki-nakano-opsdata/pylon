import type {
  Competitor,
  LifecycleProductIdentity,
  MarketResearch,
  ResearchClaim,
  ResearchDissent,
  ResearchEvidence,
} from "@/types/lifecycle";
import {
  describeProductIdentityState,
  resolveProductIdentityForResearch,
} from "@/lifecycle/productIdentity";

type ResearchAuditCategory =
  | "market_size"
  | "competitor"
  | "source"
  | "evidence"
  | "trend"
  | "opportunity"
  | "threat"
  | "user_signal"
  | "pain_point"
  | "winning_thesis"
  | "claim"
  | "dissent"
  | "open_question";

export interface ResearchAuditQuarantineEntry<T> {
  value: T;
  reason: string;
  detail?: string;
}

export interface ResearchAuditBucket<T> {
  trusted: T[];
  quarantined: ResearchAuditQuarantineEntry<T>[];
}

export interface ResearchAuditFinding {
  id: string;
  category: ResearchAuditCategory;
  label: string;
  reason: string;
  detail?: string;
}

export interface ResearchQualityAudit {
  semanticReady: boolean;
  issues: string[];
  findings: ResearchAuditFinding[];
  contextTerms: string[];
  malformedMarketSize: boolean;
  trustedEvidenceCount: number;
  totalEvidenceCount: number;
  evidenceCoveragePercent: number;
  quarantinedCount: number;
  competitors: ResearchAuditBucket<Competitor>;
  sourceLinks: ResearchAuditBucket<string>;
  evidence: ResearchAuditBucket<ResearchEvidence>;
  trends: ResearchAuditBucket<string>;
  opportunities: ResearchAuditBucket<string>;
  threats: ResearchAuditBucket<string>;
  userSignals: ResearchAuditBucket<string>;
  painPoints: ResearchAuditBucket<string>;
  winningTheses: ResearchAuditBucket<string>;
  claims: ResearchAuditBucket<ResearchClaim>;
  dissent: ResearchAuditBucket<ResearchDissent>;
  openQuestions: ResearchAuditBucket<string>;
}

interface ResearchAuditOptions {
  projectSpec?: string;
  seedUrls?: string[];
  identityProfile?: LifecycleProductIdentity;
}

const GENERIC_CONTEXT_TERMS = new Set([
  "a0",
  "a1",
  "a2",
  "a3",
  "a4",
  "agent",
  "agents",
  "ai",
  "app",
  "apps",
  "dag",
  "development",
  "json",
  "llm",
  "mcp",
  "oauth",
  "pylon",
  "quality",
  "research",
  "service",
  "services",
  "software",
  "system",
  "systems",
  "tool",
  "tools",
  "workflow",
  "workflows",
  "アプリ",
  "エージェント",
  "サービス",
  "システム",
  "ツール",
  "プロダクト",
  "プラットフォーム",
  "ワークフロー",
  "企画",
  "品質",
  "基盤",
  "改善",
  "技術",
  "市場",
  "機能",
  "研究",
  "自律",
  "設計",
  "調査",
  "開発",
]);

const RAW_SOURCE_PATTERNS = [
  /@charset/i,
  /\bSTAGING SERVER\b/i,
  /\bDEVELOPMENT SERVER\b/i,
  /\bNot publicly listed\b/i,
  /https?:\/\//i,
];

const GENERIC_URL_TERMS = new Set([
  "api",
  "app",
  "blog",
  "co",
  "com",
  "console",
  "dev",
  "docs",
  "doc",
  "guide",
  "help",
  "html",
  "https",
  "http",
  "index",
  "io",
  "learn",
  "learning",
  "net",
  "note",
  "org",
  "page",
  "pages",
  "support",
  "tutorial",
  "www",
  "www2",
]);

const ARTICLE_LIKE_PATTERNS = [
  /^【要約】/,
  /チュートリアル/i,
  /(?:^|[\s\u3000])tutorial(?:$|[\s\u3000])/i,
  /ガイド/i,
  /(?:^|[\s\u3000])guide(?:$|[\s\u3000])/i,
  /記事/i,
  /ブログ/i,
  /note\.com/i,
  /[【】｜]/,
];

const DOC_LIKE_URL_PATTERN = /(?:docs?|guide|tutorial|help|learning|learn|blog|note|article|insights)/i;
const MALFORMED_MARKET_SIZE_PATTERNS = [
  /#(?:[0-9a-f]{3,8})\b/i,
  /@charset/i,
  /,\s*#(?:[0-9a-f]{3,8})/i,
];

const ROLE_LIKE_NAME_PATTERN = /\b(?:account manager|administrator|analyst|architect|consultant|coordinator|designer|developer|director|engineer|hr|human resources|intern|lead|manager|marketer|owner|product manager|recruiter|sales|specialist)\b/i;
const JAPANESE_ROLE_PATTERN = /(?:担当者|採用担当|人事|責任者|管理者|設計者|開発者|営業|採用|マネージャー|ディレクター|コンサルタント|スペシャリスト|アナリスト)/;

function normalizeHost(value: string): string {
  try {
    return new URL(value).hostname.replace(/^www\./i, "").toLowerCase();
  } catch {
    return value.trim().toLowerCase();
  }
}

function truncate(value: string, limit = 96): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, limit).trimEnd()}...`;
}

function normalizeEntityText(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\u3040-\u30ff\u3400-\u9fff]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function buildIdentityTerms(identityProfile?: LifecycleProductIdentity): {
  productTerms: string[];
  companyTerms: string[];
  excludedTerms: string[];
  officialHosts: string[];
} {
  if (!identityProfile) {
    return {
      productTerms: [],
      companyTerms: [],
      excludedTerms: [],
      officialHosts: [],
    };
  }
  const resolvedIdentity = resolveProductIdentityForResearch(identityProfile);
  const uniq = (values: string[]) => {
    const seen = new Set<string>();
    return values.filter((value) => {
      if (!value || seen.has(value)) return false;
      seen.add(value);
      return true;
    });
  };
  return {
    productTerms: uniq(
      [resolvedIdentity.productName, ...(resolvedIdentity.aliases ?? [])]
        .map((item) => normalizeEntityText(item))
        .filter((item) => item.length >= 2),
    ),
    companyTerms: uniq(
      [resolvedIdentity.companyName]
        .map((item) => normalizeEntityText(item))
        .filter((item) => item.length >= 2),
    ),
    excludedTerms: uniq(
      (resolvedIdentity.excludedEntityNames ?? [])
        .map((item) => normalizeEntityText(item))
        .filter((item) => item.length >= 2),
    ),
    officialHosts: uniq(
      (resolvedIdentity.officialDomains ?? [])
        .map((item) => normalizeHost(item))
        .filter(Boolean),
    ),
  };
}

function textIncludesAny(text: string, candidates: string[]): string | null {
  const normalized = normalizeEntityText(text);
  if (!normalized) return null;
  return candidates.find((candidate) => normalized.includes(candidate)) ?? null;
}

function isOfficialIdentityHost(hostOrUrl: string, officialHosts: string[]): boolean {
  const host = normalizeHost(hostOrUrl);
  return officialHosts.some((candidate) => host === candidate || host.endsWith(`.${candidate}`));
}

function classifyIdentityCollision(
  value: string,
  identityProfile: LifecycleProductIdentity | undefined,
  options: {
    url?: string;
  } = {},
): { reason: string; detail?: string } | null {
  if (!identityProfile) return null;
  const identityTerms = buildIdentityTerms(identityProfile);
  const combined = [value, options.url ?? ""].filter(Boolean).join(" ");
  const excludedMatch = textIncludesAny(combined, identityTerms.excludedTerms);
  if (excludedMatch) {
    return {
      reason: "登録した除外対象と一致しており、別エンティティとして隔離します。",
      detail: truncate(excludedMatch),
    };
  }
  if (!options.url || identityTerms.productTerms.length === 0) {
    return null;
  }
  if (identityTerms.officialHosts.length > 0 && isOfficialIdentityHost(options.url, identityTerms.officialHosts)) {
    return null;
  }
  const productMatch = textIncludesAny(combined, identityTerms.productTerms);
  if (!productMatch) {
    return null;
  }
  const companyMatch = textIncludesAny(combined, identityTerms.companyTerms);
  if (companyMatch) {
    return null;
  }
  return {
    reason: identityTerms.officialHosts.length > 0
      ? "登録したプロダクト名に近い別会社の候補であり、同名衝突の可能性があります。"
      : "会社名と一致しない同名候補であり、別会社の可能性があるため隔離します。",
    detail: truncate(options.url),
  };
}

function extractContextTerms(text: string): string[] {
  const english = Array.from(text.matchAll(/\b[A-Za-z][A-Za-z0-9-]{3,}\b/g), (match) => match[0] ?? "");
  const abbreviations = Array.from(text.matchAll(/\b[A-Z]{2,5}\b/g), (match) => match[0] ?? "");
  const japanese = Array.from(text.matchAll(/[一-龠々]{2,}|[ァ-ヶー]{3,}|[ぁ-ん]{3,}/gu), (match) => match[0] ?? "");
  const seen = new Set<string>();
  return [...english, ...abbreviations, ...japanese]
    .map((term) => term.trim())
    .map((term) => /^[A-Za-z0-9-]+$/.test(term) ? term.toLowerCase() : term)
    .filter((term) => term.length >= 2)
    .filter((term) => !GENERIC_CONTEXT_TERMS.has(term))
    .filter((term) => !seen.has(term) && (seen.add(term), true))
    .sort((left, right) => right.length - left.length)
    .slice(0, 14);
}

function extractSeedUrlTerms(seedUrls: string[]): string[] {
  const seen = new Set<string>();
  const tokens = seedUrls.flatMap((raw) => {
    const candidate = raw.trim();
    if (!candidate) return [];
    try {
      const parsed = new URL(candidate);
      return [
        ...parsed.hostname.split("."),
        ...parsed.pathname.split(/[^A-Za-z0-9-]+/),
      ];
    } catch {
      return candidate.split(/[^A-Za-z0-9-]+/);
    }
  });

  return tokens
    .map((token) => token.trim().toLowerCase())
    .filter((token) => token.length >= 3)
    .filter((token) => !GENERIC_CONTEXT_TERMS.has(token))
    .filter((token) => !GENERIC_URL_TERMS.has(token))
    .filter((token) => !seen.has(token) && (seen.add(token), true))
    .slice(0, 10);
}

function buildContextTerms(
  projectSpec: string,
  seedUrls: string[],
  identityProfile?: LifecycleProductIdentity,
): string[] {
  const seen = new Set<string>();
  const identityTerms = buildIdentityTerms(identityProfile);
  return [
    ...extractContextTerms(projectSpec),
    ...extractSeedUrlTerms(seedUrls),
    ...identityTerms.productTerms,
    ...identityTerms.companyTerms,
    ...identityTerms.officialHosts,
  ].filter((term) => !seen.has(term) && (seen.add(term), true));
}

function countContextMatches(text: string, contextTerms: string[]): number {
  if (!text.trim() || contextTerms.length === 0) return 0;
  const normalized = text.toLowerCase();
  return contextTerms.filter((term) => {
    if (/^[A-Za-z0-9-]+$/.test(term)) return normalized.includes(term.toLowerCase());
    return text.includes(term);
  }).length;
}

function hasRawSourceSignals(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) return false;
  return RAW_SOURCE_PATTERNS.some((pattern) => pattern.test(normalized))
    || ARTICLE_LIKE_PATTERNS.some((pattern) => pattern.test(normalized))
    || (/[:：]/.test(normalized) && normalized.length > 80 && /(?:Basler|Series [A-Z]|@charset|note\.com|docs?)/i.test(normalized));
}

function looksLikeArticleTitle(text: string): boolean {
  return ARTICLE_LIKE_PATTERNS.some((pattern) => pattern.test(text)) || text.trim().length >= 44;
}

function looksLikeRoleName(text: string): boolean {
  return ROLE_LIKE_NAME_PATTERN.test(text) || JAPANESE_ROLE_PATTERN.test(text);
}

function classifyCompetitor(
  competitor: Competitor,
  contextTerms: string[],
  seedHosts: Set<string>,
  identityProfile?: LifecycleProductIdentity,
): ResearchAuditQuarantineEntry<Competitor> | null {
  const evidenceText = [
    competitor.name,
    competitor.url ?? "",
    competitor.target,
    ...competitor.strengths,
    ...competitor.weaknesses,
  ].join(" ");
  const contextMatches = countContextMatches(evidenceText, contextTerms);
  const hasSeedHost = competitor.url ? seedHosts.has(normalizeHost(competitor.url)) : false;
  const articleLike = looksLikeArticleTitle(competitor.name);
  const docLikeUrl = competitor.url ? DOC_LIKE_URL_PATTERN.test(competitor.url) : false;
  const identityCollision = classifyIdentityCollision(evidenceText, identityProfile, {
    url: competitor.url,
  });
  if (identityCollision) {
    return {
      value: competitor,
      reason: identityCollision.reason,
      detail: identityCollision.detail ?? truncate(competitor.name),
    };
  }
  const weakContext =
    contextTerms.length > 0
    && contextMatches === 0
    && !hasSeedHost;
  if (hasRawSourceSignals(competitor.name)) {
    return {
      value: competitor,
      reason: "記事タイトルやスクレイプ断片が競合名として混入しています。",
      detail: truncate(competitor.name),
    };
  }
  if (!hasSeedHost && articleLike) {
    return {
      value: competitor,
      reason: "プロダクト名ではなく記事・要約ページに見えます。",
      detail: truncate(competitor.name),
    };
  }
  if (!hasSeedHost && docLikeUrl && contextMatches === 0) {
    return {
      value: competitor,
      reason: "対象プロダクトとの関係が弱いドキュメント系ソースです。",
      detail: truncate(competitor.url ?? competitor.name),
    };
  }
  if (weakContext && !competitor.url && looksLikeRoleName(competitor.name)) {
    return {
      value: competitor,
      reason: "プロダクト名ではなく、役職名や人物ラベルに見えます。",
      detail: truncate(competitor.name),
    };
  }
  if (
    weakContext
    && !competitor.url
    && competitor.name.trim().split(/\s+/).length >= 3
    && countContextMatches(competitor.target, contextTerms) === 0
    && competitor.strengths.every((item) => countContextMatches(item, contextTerms) === 0)
    && competitor.weaknesses.every((item) => countContextMatches(item, contextTerms) === 0)
  ) {
    return {
      value: competitor,
      reason: "対象領域との接点が読み取れず、比較対象としては弱い候補です。",
      detail: truncate(competitor.name),
    };
  }
  return null;
}

function classifySourceLink(
  url: string,
  contextTerms: string[],
  seedHosts: Set<string>,
  identityProfile?: LifecycleProductIdentity,
): ResearchAuditQuarantineEntry<string> | null {
  const identityCollision = classifyIdentityCollision(url, identityProfile, { url });
  if (identityCollision) {
    return {
      value: url,
      reason: identityCollision.reason,
      detail: identityCollision.detail ?? normalizeHost(url),
    };
  }
  const hasSeedHost = seedHosts.has(normalizeHost(url));
  const contextMatches = countContextMatches(url, contextTerms);
  if (hasSeedHost) return null;
  if (DOC_LIKE_URL_PATTERN.test(url) && contextMatches === 0) {
    return {
      value: url,
      reason: "対象文脈との一致が弱い補助記事・ドキュメントです。",
      detail: normalizeHost(url),
    };
  }
  return null;
}

function classifyNarrativeItem(
  value: string,
  contextTerms: string[],
  identityProfile?: LifecycleProductIdentity,
): ResearchAuditQuarantineEntry<string> | null {
  if (!value.trim()) return null;
  const identityCollision = classifyIdentityCollision(value, identityProfile);
  if (identityCollision) {
    return {
      value,
      reason: identityCollision.reason,
      detail: identityCollision.detail ?? truncate(value),
    };
  }
  const contextMatches = countContextMatches(value, contextTerms);
  const rawSource = hasRawSourceSignals(value);
  if (rawSource) {
    return {
      value,
      reason: "要約ではなく、記事タイトルやスクレイプ断片がそのまま残っています。",
      detail: truncate(value),
    };
  }
  if (contextTerms.length > 0 && contextMatches === 0 && /[:：]/.test(value) && value.length > 48) {
    return {
      value,
      reason: "対象プロダクトとの関係が読み取りにくい記述です。",
      detail: truncate(value),
    };
  }
  return null;
}

function classifyEvidence(
  evidence: ResearchEvidence,
  contextTerms: string[],
  seedHosts: Set<string>,
  identityProfile?: LifecycleProductIdentity,
): ResearchAuditQuarantineEntry<ResearchEvidence> | null {
  const sourceRef = evidence.source_ref?.trim() ?? "";
  const snippet = evidence.snippet?.trim() ?? "";
  const combined = [sourceRef, snippet].filter(Boolean).join(" ");
  const identityCollision = classifyIdentityCollision(combined, identityProfile, {
    url: /^https?:\/\//i.test(sourceRef) ? sourceRef : undefined,
  });
  if (identityCollision) {
    return {
      value: evidence,
      reason: identityCollision.reason,
      detail: identityCollision.detail ?? truncate(sourceRef || snippet),
    };
  }
  const hasSeedHost = /^https?:\/\//i.test(sourceRef) ? seedHosts.has(normalizeHost(sourceRef)) : false;
  const contextMatches = countContextMatches(combined, contextTerms);

  if (/^https?:\/\//i.test(sourceRef)) {
    const sourceIssue = classifySourceLink(sourceRef, contextTerms, seedHosts, identityProfile);
    if (sourceIssue) {
      return {
        value: evidence,
        reason: sourceIssue.reason,
        detail: truncate(sourceRef),
      };
    }
  }

  if (snippet && hasRawSourceSignals(snippet)) {
    return {
      value: evidence,
      reason: "根拠要約ではなく、記事断片やスクレイプ断片が残っています。",
      detail: truncate(snippet),
    };
  }

  if (contextTerms.length > 0 && contextMatches === 0 && !hasSeedHost && combined.length > 48) {
    return {
      value: evidence,
      reason: "対象プロダクトとの接点が弱く、判断根拠としては不十分です。",
      detail: truncate(sourceRef || snippet),
    };
  }

  return null;
}

function classifyClaim(
  claim: ResearchClaim,
  contextTerms: string[],
  trustedEvidenceIds: Set<string>,
  hasEvidence: boolean,
  identityProfile?: LifecycleProductIdentity,
): ResearchAuditQuarantineEntry<ResearchClaim> | null {
  const narrativeIssue = classifyNarrativeItem(claim.statement, contextTerms, identityProfile);
  if (narrativeIssue) {
    return {
      value: claim,
      reason: "主張文に記事タイトルや対象外の断片が混ざっています。",
      detail: narrativeIssue.detail ?? truncate(claim.statement),
    };
  }

  if (claim.status === "accepted" && hasEvidence && claim.evidence_ids.length === 0) {
    return {
      value: claim,
      reason: "採用済みの主張ですが、根拠との接続が空です。",
      detail: truncate(claim.statement),
    };
  }

  if (
    claim.status === "accepted"
    && claim.evidence_ids.length > 0
    && !claim.evidence_ids.some((id) => trustedEvidenceIds.has(id))
  ) {
    return {
      value: claim,
      reason: "主張を支える根拠が隔離済みで、そのままでは企画判断に使えません。",
      detail: truncate(claim.statement),
    };
  }

  return null;
}

function classifyDissent(
  dissent: ResearchDissent,
  contextTerms: string[],
  identityProfile?: LifecycleProductIdentity,
): ResearchAuditQuarantineEntry<ResearchDissent> | null {
  const narrativeIssue = classifyNarrativeItem(
    [dissent.argument, dissent.recommended_test ?? ""].filter(Boolean).join(" "),
    contextTerms,
    identityProfile,
  );
  if (!narrativeIssue) return null;
  return {
    value: dissent,
    reason: "反対意見に記事断片や対象外の文章が混ざっています。",
    detail: narrativeIssue.detail ?? truncate(dissent.argument),
  };
}

function auditList<T>(
  values: T[],
  classifier: (value: T) => ResearchAuditQuarantineEntry<T> | null,
): ResearchAuditBucket<T> {
  return values.reduce<ResearchAuditBucket<T>>((acc, value) => {
    const quarantined = classifier(value);
    if (quarantined) {
      acc.quarantined.push(quarantined);
      return acc;
    }
    acc.trusted.push(value);
    return acc;
  }, { trusted: [], quarantined: [] });
}

function buildFindings<T>(
  category: ResearchAuditCategory,
  entries: ResearchAuditQuarantineEntry<T>[],
  label: (entry: T) => string,
): ResearchAuditFinding[] {
  return entries.map((entry, index) => ({
    id: `${category}-${index + 1}`,
    category,
    label: label(entry.value),
    reason: entry.reason,
    detail: entry.detail,
  }));
}

export function auditResearchQuality(
  research: MarketResearch,
  options: ResearchAuditOptions = {},
): ResearchQualityAudit {
  const identityProfile = options.identityProfile;
  const identityTerms = buildIdentityTerms(identityProfile);
  const contextTerms = buildContextTerms(
    options.projectSpec ?? "",
    options.seedUrls ?? [],
    identityProfile,
  );
  const seedHosts = new Set([
    ...(options.seedUrls ?? []).map(normalizeHost),
    ...identityTerms.officialHosts,
  ]);

  const competitors = auditList(research.competitors ?? [], (competitor) => classifyCompetitor(competitor, contextTerms, seedHosts, identityProfile));
  const sourceLinks = auditList(research.source_links ?? [], (url) => classifySourceLink(url, contextTerms, seedHosts, identityProfile));
  const evidence = auditList(research.evidence ?? [], (item) => classifyEvidence(item, contextTerms, seedHosts, identityProfile));
  const trustedEvidenceIds = new Set(evidence.trusted.map((item) => item.id));
  const trends = auditList(research.trends ?? [], (value) => classifyNarrativeItem(value, contextTerms, identityProfile));
  const opportunities = auditList(research.opportunities ?? [], (value) => classifyNarrativeItem(value, contextTerms, identityProfile));
  const threats = auditList(research.threats ?? [], (value) => classifyNarrativeItem(value, contextTerms, identityProfile));
  const userSignals = auditList(research.user_research?.signals ?? [], (value) => classifyNarrativeItem(value, contextTerms, identityProfile));
  const painPoints = auditList(research.user_research?.pain_points ?? [], (value) => classifyNarrativeItem(value, contextTerms, identityProfile));
  const winningTheses = auditList(research.winning_theses ?? [], (value) => classifyNarrativeItem(value, contextTerms, identityProfile));
  const claims = auditList(research.claims ?? [], (claim) => classifyClaim(claim, contextTerms, trustedEvidenceIds, (research.evidence?.length ?? 0) > 0, identityProfile));
  const dissent = auditList(research.dissent ?? [], (item) => classifyDissent(item, contextTerms, identityProfile));
  const openQuestions = auditList(research.open_questions ?? [], (value) => classifyNarrativeItem(value, contextTerms, identityProfile));

  const malformedMarketSize = MALFORMED_MARKET_SIZE_PATTERNS.some((pattern) => pattern.test(research.market_size));
  const trustedEvidenceCount = competitors.trusted.length + sourceLinks.trusted.length;
  const totalEvidenceCount = (research.competitors?.length ?? 0) + (research.source_links?.length ?? 0);
  const quarantinedCount =
    competitors.quarantined.length
    + sourceLinks.quarantined.length
    + evidence.quarantined.length
    + trends.quarantined.length
    + opportunities.quarantined.length
    + threats.quarantined.length
    + userSignals.quarantined.length
    + painPoints.quarantined.length
    + winningTheses.quarantined.length
    + claims.quarantined.length
    + dissent.quarantined.length
    + openQuestions.quarantined.length
    + (malformedMarketSize ? 1 : 0);
  const evidenceCoveragePercent = totalEvidenceCount > 0
    ? Math.round((trustedEvidenceCount / totalEvidenceCount) * 100)
    : 100;

  const issues: string[] = [];
  const identityState = describeProductIdentityState(identityProfile);
  const hasStrongIdentityLock =
    identityTerms.officialHosts.length > 0
    || identityTerms.excludedTerms.length > 0
    || (identityTerms.productTerms.length > 0 && identityTerms.companyTerms.length > 0);
  if (malformedMarketSize) {
    issues.push("市場規模の値が崩れており、数値根拠として扱えません。");
  }
  if ((research.competitors?.length ?? 0) > 0 && competitors.trusted.length === 0) {
    issues.push("競合候補が記事や対象外ソースに寄っており、比較対象として使えません。");
  }
  if ((research.source_links?.length ?? 0) > 0 && sourceLinks.trusted.length === 0) {
    issues.push("外部根拠リンクの大半が対象文脈に合っておらず、根拠として弱い状態です。");
  } else if ((research.source_links?.length ?? 0) >= 3 && evidenceCoveragePercent < 50) {
    issues.push("外部根拠の半数以上を隔離しており、根拠の信頼性が不足しています。");
  }
  if (totalEvidenceCount > 0 && trustedEvidenceCount < Math.min(totalEvidenceCount, 2)) {
    issues.push("企画判断に使える一次根拠が不足しています。");
  }
  const narrativeQuarantineCount =
    trends.quarantined.length
    + opportunities.quarantined.length
    + threats.quarantined.length
    + userSignals.quarantined.length
    + painPoints.quarantined.length;
  if (narrativeQuarantineCount >= 2) {
    issues.push("市場・ユーザー要約にスクレイプ断片が混ざっており、記述精度の見直しが必要です。");
  }
  if ((research.winning_theses?.length ?? 0) > 0 && winningTheses.trusted.length === 0) {
    issues.push("企画へ渡す主要仮説に対象外の文章が混ざっており、そのままでは採用できません。");
  }
  if (claims.quarantined.length + dissent.quarantined.length + openQuestions.quarantined.length >= 2) {
    issues.push("主張台帳と残課題に対象外の文章が混ざっており、企画に渡す論点の再整理が必要です。");
  }
  const identityCollisionCount =
    competitors.quarantined.filter((entry) => entry.reason.includes("同名") || entry.reason.includes("除外対象")).length
    + sourceLinks.quarantined.filter((entry) => entry.reason.includes("同名") || entry.reason.includes("除外対象")).length
    + evidence.quarantined.filter((entry) => entry.reason.includes("同名") || entry.reason.includes("除外対象")).length;
  if (identityCollisionCount > 0) {
    issues.push(
      hasStrongIdentityLock
        ? "登録した調査対象と一致しない同名候補を隔離しており、entity の混同が検出されています。"
        : identityState.collisionPrompt,
    );
  }

  const findings: ResearchAuditFinding[] = [
    ...(malformedMarketSize ? [{
      id: "market-size-1",
      category: "market_size" as const,
      label: "市場規模",
      reason: "数値文字列が崩れており、表示値として破損しています。",
      detail: truncate(research.market_size),
    }] : []),
    ...buildFindings("competitor", competitors.quarantined, (item) => item.name),
    ...buildFindings("source", sourceLinks.quarantined, (item) => normalizeHost(item)),
    ...buildFindings("evidence", evidence.quarantined, (item) => truncate(item.source_ref || item.snippet, 40)),
    ...buildFindings("trend", trends.quarantined, (item) => truncate(item, 40)),
    ...buildFindings("opportunity", opportunities.quarantined, (item) => truncate(item, 40)),
    ...buildFindings("threat", threats.quarantined, (item) => truncate(item, 40)),
    ...buildFindings("user_signal", userSignals.quarantined, (item) => truncate(item, 40)),
    ...buildFindings("pain_point", painPoints.quarantined, (item) => truncate(item, 40)),
    ...buildFindings("winning_thesis", winningTheses.quarantined, (item) => truncate(item, 40)),
    ...buildFindings("claim", claims.quarantined, (item) => truncate(item.statement, 40)),
    ...buildFindings("dissent", dissent.quarantined, (item) => truncate(item.argument, 40)),
    ...buildFindings("open_question", openQuestions.quarantined, (item) => truncate(item, 40)),
  ].slice(0, 12);

  return {
    semanticReady: issues.length === 0,
    issues,
    findings,
    contextTerms,
    malformedMarketSize,
    trustedEvidenceCount,
    totalEvidenceCount,
    evidenceCoveragePercent,
    quarantinedCount,
    competitors,
    sourceLinks,
    evidence,
    trends,
    opportunities,
    threats,
    userSignals,
    painPoints,
    winningTheses,
    claims,
    dissent,
    openQuestions,
  };
}
