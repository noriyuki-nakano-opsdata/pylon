import type { LifecycleProductIdentity } from "@/types/lifecycle";

function unique(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

function aliasVariants(value: string): string[] {
  const base = value.trim();
  if (!base) return [];
  const spaced = base.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  const condensed = base.replace(/[\s._-]+/g, "").trim();
  return unique([
    base,
    spaced,
    condensed.length >= 2 ? condensed : "",
  ]);
}

export function defaultProductIdentity(): LifecycleProductIdentity {
  return {
    companyName: "",
    productName: "",
    officialWebsite: "",
    officialDomains: [],
    aliases: [],
    excludedEntityNames: [],
  };
}

export function normalizeIdentityDomain(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  try {
    const parsed = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    const hostname = parsed.hostname.replace(/^www\./i, "").toLowerCase();
    return hostname || null;
  } catch {
    return null;
  }
}

export function normalizeIdentityWebsite(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  try {
    const parsed = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    return `${parsed.protocol}//${parsed.hostname.replace(/^www\./i, "").toLowerCase()}`;
  } catch {
    return trimmed;
  }
}

export function normalizeIdentityListInput(input: string): string[] {
  return unique(
    input
      .split(/[\n,、]/)
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

export function joinIdentityList(values: string[]): string {
  return values.join(", ");
}

export function normalizeProductIdentity(
  value: Partial<LifecycleProductIdentity> | null | undefined,
  options: {
    fallbackProductName?: string;
  } = {},
): LifecycleProductIdentity {
  const base = defaultProductIdentity();
  const companyName = value?.companyName?.trim() ?? "";
  const productName = value?.productName?.trim() || options.fallbackProductName?.trim() || "";
  const officialWebsite = normalizeIdentityWebsite(value?.officialWebsite ?? "");
  const domains = unique([
    ...(value?.officialDomains ?? []).map((item) => normalizeIdentityDomain(item) ?? "").filter(Boolean),
    normalizeIdentityDomain(officialWebsite) ?? "",
  ]);

  return {
    ...base,
    companyName,
    productName,
    officialWebsite,
    officialDomains: domains,
    aliases: unique((value?.aliases ?? []).map((item) => item.trim()).filter(Boolean)),
    excludedEntityNames: unique((value?.excludedEntityNames ?? []).map((item) => item.trim()).filter(Boolean)),
  };
}

function coalesceIdentityList(primary: string[], fallback: string[]): string[] {
  return primary.length > 0 ? primary : fallback;
}

export function mergeProductIdentityFallback(
  value: Partial<LifecycleProductIdentity> | null | undefined,
  fallback: Partial<LifecycleProductIdentity> | null | undefined,
  options: {
    fallbackProductName?: string;
  } = {},
): LifecycleProductIdentity {
  const normalizedValue = normalizeProductIdentity(value, options);
  const normalizedFallback = normalizeProductIdentity(fallback, options);

  return normalizeProductIdentity(
    {
      companyName: normalizedValue.companyName || normalizedFallback.companyName,
      productName: normalizedValue.productName || normalizedFallback.productName,
      officialWebsite: normalizedValue.officialWebsite || normalizedFallback.officialWebsite,
      officialDomains: coalesceIdentityList(normalizedValue.officialDomains, normalizedFallback.officialDomains),
      aliases: coalesceIdentityList(normalizedValue.aliases, normalizedFallback.aliases),
      excludedEntityNames: coalesceIdentityList(
        normalizedValue.excludedEntityNames,
        normalizedFallback.excludedEntityNames,
      ),
    },
    options,
  );
}

export function resolveProductIdentityForResearch(
  value: Partial<LifecycleProductIdentity> | null | undefined,
  options: {
    fallbackProductName?: string;
  } = {},
): LifecycleProductIdentity {
  const normalized = normalizeProductIdentity(value, options);
  const inferredAliases = aliasVariants(normalized.productName).filter(
    (item) => item.localeCompare(normalized.productName, undefined, { sensitivity: "accent" }) !== 0,
  );
  const aliases = unique([
    ...normalized.aliases,
    ...inferredAliases,
  ]);

  return {
    ...normalized,
    aliases,
  };
}

export function buildIdentityAutofillMessages(
  value: Partial<LifecycleProductIdentity> | null | undefined,
  options: {
    fallbackProductName?: string;
  } = {},
): string[] {
  const normalized = normalizeProductIdentity(value, options);
  const messages: string[] = [];
  const hasNamedEntity = Boolean(normalized.companyName || normalized.productName);

  if (!hasNamedEntity) {
    messages.push("会社名やサービス名が未定でも、概要から調査テーマと検索軸を組み立てます。");
  }

  if (!normalized.officialWebsite) {
    messages.push(
      hasNamedEntity
        ? "公式サイトが空でも、決まっている名称から検索軸を固定します。"
        : "公式サイトがなくても、概要と関連語から調査対象を広げます。",
    );
  }
  if (normalized.aliases.length === 0) {
    messages.push(
      normalized.productName
        ? "別名・略称が空でも、表記ゆれ候補を自動生成して照合します。"
        : "固有名が未定でも、概要から関連語候補を生成して照合します。",
    );
  }
  if (normalized.excludedEntityNames.length === 0) {
    messages.push("除外候補が空でも、同名他社らしいソースを自動で隔離します。");
  }

  return messages;
}

export type ProductIdentityStateMode =
  | "concept_only"
  | "company_context"
  | "product_context"
  | "identity_locked";

export interface ProductIdentityStateDescriptor {
  mode: ProductIdentityStateMode;
  badgeLabel: string;
  summaryLabel: string;
  helperText: string;
  nextBestAction: string;
  collisionPrompt: string;
}

export function describeProductIdentityState(
  value: Partial<LifecycleProductIdentity> | null | undefined,
  options: {
    fallbackProductName?: string;
  } = {},
): ProductIdentityStateDescriptor {
  const normalized = normalizeProductIdentity(value, options);
  const hasCompany = Boolean(normalized.companyName);
  const hasProduct = Boolean(normalized.productName);
  const hasWebsite = Boolean(normalized.officialWebsite || normalized.officialDomains.length > 0);
  const hasExcluded = normalized.excludedEntityNames.length > 0;
  const identityLocked = (hasCompany && hasProduct) || hasWebsite || hasExcluded;

  if (identityLocked) {
    return {
      mode: "identity_locked",
      badgeLabel: hasWebsite ? "公式導線あり" : "対象を絞れる",
      summaryLabel: hasCompany && hasProduct
        ? `${normalized.companyName} / ${normalized.productName}`
        : hasWebsite
          ? "公式サイトを起点に調査"
          : "除外条件つきで調査",
      helperText: hasCompany && hasProduct
        ? "名称と運営主体を使って、同名候補を隔離しながら調査します。"
        : hasWebsite
          ? "公式サイトを anchor にして、周辺ソースの信頼性を見極めます。"
          : "除外候補を使って、既知の同名サービスを最初から避けて調査します。",
      nextBestAction: "必要なら別名や競合 URL を足すと、比較軸がさらに安定します。",
      collisionPrompt: "登録した調査対象と一致しない同名候補を隔離しており、entity の混同が検出されています。",
    };
  }

  if (hasCompany) {
    return {
      mode: "company_context",
      badgeLabel: "会社軸あり",
      summaryLabel: normalized.companyName,
      helperText: "会社名を起点に事業ドメインと公開情報を広げて調査します。",
      nextBestAction: "サービス名・構想名か公式サイトを追加すると、同名候補の絞り込みが安定します。",
      collisionPrompt: "同名候補が混ざっているため、サービス名・構想名か公式サイトを追加してください。",
    };
  }

  if (hasProduct) {
    return {
      mode: "product_context",
      badgeLabel: "構想名あり",
      summaryLabel: normalized.productName,
      helperText: "構想名を起点に検索し、曖昧さが出たときだけ追加情報で絞り込みます。",
      nextBestAction: "会社名・運営主体か公式サイトを追加すると、同名候補の絞り込みが安定します。",
      collisionPrompt: "同名候補が混ざっているため、会社名・運営主体か公式サイトを追加してください。",
    };
  }

  return {
    mode: "concept_only",
    badgeLabel: "未定でも可",
    summaryLabel: "未設定でも開始できます",
    helperText: "概要から課題、ユーザー、代替手段を広げ、構想ベースで調査を始めます。",
    nextBestAction: "同名候補が出たら、会社名・サービス名・公式サイトのいずれかを後から追加してください。",
    collisionPrompt: "同名候補が混ざっているため、会社名・サービス名・公式サイトのいずれかを追加してください。",
  };
}

export function hasProductIdentity(
  value: Partial<LifecycleProductIdentity> | null | undefined,
): boolean {
  if (!value) return false;
  return Boolean(
    value.companyName?.trim()
    || value.productName?.trim()
    || value.officialWebsite?.trim()
    || value.officialDomains?.length
    || value.aliases?.length
    || value.excludedEntityNames?.length,
  );
}

export function hasMinimumProductIdentity(
  value: Partial<LifecycleProductIdentity> | null | undefined,
): boolean {
  return Boolean(value?.companyName?.trim() && value?.productName?.trim());
}
