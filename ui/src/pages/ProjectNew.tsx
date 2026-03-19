import { type FormEvent, type ReactNode, useId, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  FolderPlus,
  Loader2,
  Orbit,
  Sparkles,
  GitBranch,
  ShieldCheck,
  Cpu,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import {
  buildIdentityAutofillMessages,
  hasProductIdentity,
  normalizeIdentityDomain,
  normalizeIdentityListInput,
  normalizeIdentityWebsite,
} from "@/lifecycle/productIdentity";
import { cn } from "@/lib/utils";

const MAX_BRIEF_LENGTH = 1200;

const HERO_METRICS = [
  { label: "必要な入力", value: "1項目", description: "名前だけで開始できます。" },
  { label: "開始の流れ", value: "即時", description: "作成後そのままリサーチへ進みます。" },
  { label: "後から更新", value: "可能", description: "brief と GitHub リポジトリは追記できます。" },
] as const;

const STARTUP_FACTS = [
  {
    title: "作成直後にリサーチが始まります",
    description: "不足している背景や論点は、開始後の工程で拾いながら整えていけます。",
    icon: Sparkles,
  },
  {
    title: "詳細な仕様は後から育てられます",
    description: "最初から完成した要件を求めず、輪郭のある仮説だけを置けば十分です。",
    icon: Cpu,
  },
  {
    title: "運用に必要な判断だけをここで行います",
    description: "この画面では着手の意思決定に集中し、細部の検討は次のフェーズへ渡します。",
    icon: ShieldCheck,
  },
] as const;

const FLOW_STEPS = [
  {
    step: "01",
    title: "呼び名を決める",
    description: "チームが同じ言葉で扱える名前を置きます。",
  },
  {
    step: "02",
    title: "輪郭を添える",
    description: "必要なら brief や既存リポジトリを添えて出発点をそろえます。",
  },
  {
    step: "03",
    title: "リサーチへ移る",
    description: "作成後すぐに初期調査が走り、次の論点が見える状態へ進みます。",
  },
] as const;

const DECISION_CARDS = [
  {
    title: "この画面で決めること",
    items: ["プロジェクトの呼び名", "最初に見るべき論点の輪郭", "既存リポジトリを使うかどうか"],
    icon: GitBranch,
  },
  {
    title: "今は決めなくてよいこと",
    items: ["詳細な仕様や画面一覧", "実装タスクの粒度", "運用フローの細部"],
    icon: ShieldCheck,
  },
] as const;
const GITHUB_REPO_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

function normalizeGithubRepo(input: string): string | null {
  const trimmed = input.trim().replace(/\.git$/i, "");
  if (!trimmed) return "";
  if (GITHUB_REPO_PATTERN.test(trimmed)) return trimmed;

  try {
    const url = new URL(trimmed);
    if (!["github.com", "www.github.com"].includes(url.hostname)) {
      return null;
    }
    const [owner, repo] = url.pathname.split("/").filter(Boolean);
    if (!owner || !repo) {
      return null;
    }
    const normalized = `${owner}/${repo}`;
    return GITHUB_REPO_PATTERN.test(normalized) ? normalized : null;
  } catch {
    return null;
  }
}

export function ProjectNew() {
  const navigate = useNavigate();
  const { createProject, currentTenant } = useTenantProject();
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [productName, setProductName] = useState("");
  const [officialWebsite, setOfficialWebsite] = useState("");
  const [identityAliases, setIdentityAliases] = useState("");
  const [excludedEntityNames, setExcludedEntityNames] = useState("");
  const [showIdentity, setShowIdentity] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [repoTouched, setRepoTouched] = useState(false);
  const [identityWebsiteTouched, setIdentityWebsiteTouched] = useState(false);

  const normalizedName = name.trim();
  const normalizedGithubRepo = useMemo(() => normalizeGithubRepo(githubRepo), [githubRepo]);
  const normalizedIdentityWebsite = useMemo(
    () => normalizeIdentityWebsite(officialWebsite),
    [officialWebsite],
  );
  const draftProductIdentity = useMemo(() => ({
    companyName,
    productName: productName.trim(),
    officialWebsite: normalizedIdentityWebsite,
    aliases: normalizeIdentityListInput(identityAliases),
    excludedEntityNames: normalizeIdentityListInput(excludedEntityNames),
  }), [
    companyName,
    excludedEntityNames,
    identityAliases,
    normalizedIdentityWebsite,
    productName,
  ]);
  const identityAutofillMessages = useMemo(
    () => buildIdentityAutofillMessages(draftProductIdentity, { fallbackProductName: normalizedName }),
    [draftProductIdentity, normalizedName],
  );
  const identityWebsiteError =
    identityWebsiteTouched && officialWebsite.trim() && !normalizeIdentityDomain(officialWebsite)
      ? "公式サイトは有効な URL またはドメインで入力してください"
      : "";
  const githubRepoError =
    repoTouched && githubRepo.trim() && normalizedGithubRepo === null
      ? "GitHub リポジトリは owner/repo 形式または GitHub URL を入力してください"
      : "";
  const canSubmit = !!normalizedName && !creating && !githubRepoError && !identityWebsiteError;
  const briefDensity = useMemo(() => {
    if (brief.length === 0) return "empty";
    if (brief.length < 140) return "light";
    if (brief.length < 360) return "good";
    return "dense";
  }, [brief.length]);

  const nameFieldId = useId();
  const briefFieldId = useId();
  const githubFieldId = useId();
  const githubHelpId = useId();
  const identitySectionId = useId();
  const companyFieldId = useId();
  const productFieldId = useId();
  const websiteFieldId = useId();
  const websiteHelpId = useId();
  const aliasesFieldId = useId();
  const excludedEntitiesFieldId = useId();
  const advancedSectionId = useId();
  const errorMessageId = useId();
  const nameInputRef = useRef<HTMLInputElement>(null);
  const githubInputRef = useRef<HTMLInputElement>(null);
  const identityWebsiteInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    setError("");
    if (!normalizedName) {
      setError("プロジェクト名は必須です");
      nameInputRef.current?.focus();
      return;
    }
    if (githubRepo.trim() && normalizedGithubRepo === null) {
      setRepoTouched(true);
      setError("GitHub リポジトリの形式を確認してください");
      githubInputRef.current?.focus();
      return;
    }
    if (officialWebsite.trim() && !normalizeIdentityDomain(officialWebsite)) {
      setIdentityWebsiteTouched(true);
      setError("公式サイトの形式を確認してください");
      identityWebsiteInputRef.current?.focus();
      return;
    }

    setCreating(true);
    try {
      await createProject({
        name: normalizedName,
        brief: brief.trim(),
        githubRepo: normalizedGithubRepo ?? "",
        ...(hasProductIdentity(draftProductIdentity) ? { productIdentity: draftProductIdentity } : {}),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "プロダクト作成に失敗しました");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="intake-workspace intake-shell relative min-h-full overflow-hidden">
      <div className="pointer-events-none absolute left-[4%] top-16 h-44 w-44 rounded-full bg-[var(--intake-accent-soft)] blur-3xl" />
      <div className="pointer-events-none absolute bottom-8 right-[6%] h-52 w-52 rounded-full bg-[var(--intake-bronze-soft)] blur-3xl" />

      <div className="relative mx-auto flex max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6 sm:py-8 xl:px-8">
        <header className="intake-panel flex flex-col gap-3 rounded-[var(--intake-radius-xl)] px-4 py-4 sm:gap-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <Link
              to="/dashboard"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[var(--intake-border)] bg-[var(--intake-elevated)] text-[var(--intake-text-soft)] transition-colors hover:border-[var(--intake-border-strong)] hover:text-[var(--intake-text)]"
              aria-label="ダッシュボードへ戻る"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div className="space-y-1.5 sm:space-y-2">
              <div className="hidden sm:inline-flex intake-eyebrow">
                <Orbit className="h-3.5 w-3.5" />
                プロジェクト開始
              </div>
              <div>
                <h1 className="text-xl font-semibold tracking-tight text-[var(--intake-text)] sm:text-3xl">
                  新規プロジェクト
                </h1>
                <p className="mt-1 hidden text-sm leading-6 text-[var(--intake-text-muted)] sm:block">
                  最初の判断だけを静かに整え、次のフェーズへ確実につなげます。
                </p>
              </div>
            </div>
          </div>
          <div className="intake-note inline-flex items-center gap-3 self-start px-4 py-2 text-sm text-[var(--intake-text-soft)]">
            <span className="h-2 w-2 rounded-full bg-[var(--intake-success)] shadow-[0_0_16px_var(--intake-success-soft)]" />
            {currentTenant?.name ?? "テナント未設定"}
          </div>
        </header>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.06fr)_30rem]">
          <div className="order-2 space-y-6 xl:order-1">
            <section className="intake-panel rounded-[var(--intake-radius-xxl)] px-5 py-6 sm:px-7 sm:py-8">
              <div className="space-y-5">
                <SectionEyebrow icon={Sparkles}>着手のための静かな導線</SectionEyebrow>
                <div className="space-y-4">
                  <h2 className="intake-display max-w-4xl text-[2rem] leading-[1.08] text-[var(--intake-text)] sm:text-5xl lg:text-[4rem]">
                    最初の一歩だけ決めれば、
                    <br />
                    調査と設計は
                    <br />
                    すぐに走り出します。
                  </h2>
                  <p className="max-w-2xl text-sm leading-7 text-[var(--intake-text-soft)] sm:text-[15px]">
                    ここで必要なのは、何を始めるのかを示す呼び名と、必要に応じた最小限の輪郭だけです。
                    完成した仕様はまだ不要です。作成後のリサーチで論点を集め、次の工程で構造化していきます。
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {HERO_METRICS.map((item) => (
                    <div key={item.label} className="intake-stat px-4 py-4">
                      <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--intake-text-muted)]">
                        {item.label}
                      </p>
                      <p className="mt-3 text-2xl font-semibold text-[var(--intake-text)]">{item.value}</p>
                      <p className="mt-2 text-sm leading-6 text-[var(--intake-text-muted)]">{item.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
              <div className="intake-panel rounded-[var(--intake-radius-xl)] p-5 sm:p-6">
                <SectionEyebrow icon={GitBranch}>作成後の進行</SectionEyebrow>
                <div className="mt-5 space-y-4">
                  {FLOW_STEPS.map((item) => (
                    <div key={item.step} className="intake-note flex gap-4 px-4 py-4">
                      <div className="intake-mono flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[var(--intake-border)] bg-[var(--intake-accent-soft)] text-sm font-semibold text-[var(--intake-accent-strong)]">
                        {item.step}
                      </div>
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-[var(--intake-text)]">{item.title}</p>
                        <p className="text-sm leading-6 text-[var(--intake-text-muted)]">{item.description}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-4">
                {DECISION_CARDS.map((card) => (
                  <div key={card.title} className="intake-panel rounded-[var(--intake-radius-xl)] p-5 sm:p-6">
                    <SectionEyebrow icon={card.icon}>{card.title}</SectionEyebrow>
                    <div className="mt-5 space-y-3">
                      {card.items.map((item) => (
                        <div key={item} className="intake-note px-4 py-3 text-sm leading-6 text-[var(--intake-text-soft)]">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <aside className="order-1 xl:sticky xl:top-6 xl:order-2 xl:self-start">
            <section className="intake-panel-strong rounded-[var(--intake-radius-xxl)] px-5 py-6 sm:px-7 sm:py-7">
              <div className="space-y-5 sm:space-y-6">
                <div className="space-y-2 sm:space-y-3">
                  <SectionEyebrow icon={FolderPlus}>入力</SectionEyebrow>
                  <div className="space-y-2 sm:space-y-3">
                    <h3 className="intake-display text-[2rem] leading-[1.14] text-[var(--intake-text)] sm:text-[2.5rem]">
                      始めるための情報だけ、
                      <br />
                      ここに置きます。
                    </h3>
                    <p className="text-sm leading-6 text-[var(--intake-text-soft)] sm:hidden">
                      プロジェクト名があれば開始できます。
                    </p>
                    <p className="hidden text-sm leading-7 text-[var(--intake-text-soft)] sm:block">
                      プロジェクト名があれば開始できます。必要に応じて brief や GitHub リポジトリを添え、
                      出発点の精度を少しだけ上げてください。
                    </p>
                  </div>
                </div>

                <form className="flex flex-col gap-5 sm:gap-6" onSubmit={(event) => void handleSubmit(event)} noValidate>
                  <div className="order-1">
                    <FieldGroup
                      label="プロジェクト名"
                      description="チームが共通言語として使う名前を入力してください。内部 ID と URL は自動で発行されます。"
                      id={nameFieldId}
                      descriptionClassName="hidden sm:block"
                      badgeLabel="必須"
                      badgeTone="required"
                    >
                      <Input
                        id={nameFieldId}
                        ref={nameInputRef}
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        placeholder="例: Revenue Command Center"
                        autoComplete="off"
                        required
                        aria-invalid={Boolean(error && !normalizedName)}
                        aria-describedby={error && !normalizedName ? errorMessageId : undefined}
                        className="h-15 rounded-[1.15rem] border-[var(--intake-border)] bg-[var(--intake-surface-soft)] px-5 text-lg text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus-visible:ring-[var(--intake-ring)]"
                      />
                      <div className="hidden flex-wrap gap-2 text-xs text-[var(--intake-text-soft)] sm:flex">
                        <SignalPill>名前だけで開始可能</SignalPill>
                        <SignalPill>作成後にリサーチへ移動</SignalPill>
                        <SignalPill>後から情報を追記可能</SignalPill>
                      </div>
                    </FieldGroup>
                  </div>

                  <div className="order-2 intake-note overflow-hidden p-4">
                    <button
                      type="button"
                      onClick={() => setShowIdentity((value) => !value)}
                      aria-expanded={showIdentity}
                      aria-controls={identitySectionId}
                      className="flex w-full items-start justify-between gap-4 text-left"
                    >
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-[var(--intake-text)]">運営会社と自社プロダクトを登録する</p>
                        <p className="text-sm leading-6 text-[var(--intake-text-muted)]">
                          同名サービスとの混同を防ぐための登録です。ここで入れておくと、リサーチの精度が上がります。
                        </p>
                      </div>
                      <div className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[var(--intake-border)] bg-[var(--intake-elevated)] text-[var(--intake-text-soft)]">
                        {showIdentity ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </div>
                    </button>

                    {showIdentity && (
                      <div id={identitySectionId} className="mt-5 space-y-5 border-t border-[var(--intake-border)] pt-5">
                        <div className="grid gap-4 xl:grid-cols-2">
                          <div className="rounded-[1.4rem] border border-[var(--intake-border)] bg-[var(--intake-surface-soft)] p-4 sm:p-5">
                            <div className="flex items-start justify-between gap-3">
                              <div className="space-y-1">
                                <p className="text-sm font-semibold text-[var(--intake-text)]">research までに固定する項目</p>
                                <p className="text-xs leading-6 text-[var(--intake-text-muted)]">
                                  必須です。ここが決まると、AI が同名他社との混同を避けやすくなります。
                                </p>
                              </div>
                              <FieldBadge tone="required">必須</FieldBadge>
                            </div>
                            <div className="mt-4 grid gap-5 sm:grid-cols-2">
                              <FieldGroup
                                label="会社名"
                                description="このプロダクトを運営する会社名を入力します。"
                                id={companyFieldId}
                                badgeLabel="必須"
                                badgeTone="required"
                              >
                                <Input
                                  id={companyFieldId}
                                  value={companyName}
                                  onChange={(event) => setCompanyName(event.target.value)}
                                  placeholder="例: Pylon Labs"
                                  autoComplete="organization"
                                  className="h-12 rounded-[1.15rem] border-[var(--intake-border)] bg-[var(--intake-surface-soft)] text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus-visible:ring-[var(--intake-ring)]"
                                />
                              </FieldGroup>

                              <FieldGroup
                                label="自社プロダクト名"
                                description="空欄ならプロジェクト名を使います。あとで正式名称に直せます。"
                                id={productFieldId}
                                badgeLabel="必須"
                                badgeTone="required"
                              >
                                <Input
                                  id={productFieldId}
                                  value={productName}
                                  onChange={(event) => setProductName(event.target.value)}
                                  placeholder="例: Pylon"
                                  autoComplete="off"
                                  className="h-12 rounded-[1.15rem] border-[var(--intake-border)] bg-[var(--intake-surface-soft)] text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus-visible:ring-[var(--intake-ring)]"
                                />
                              </FieldGroup>
                            </div>
                          </div>

                          <div className="rounded-[1.4rem] border border-[var(--intake-border)] bg-[var(--intake-elevated)] p-4 sm:p-5">
                            <div className="flex items-start justify-between gap-3">
                              <div className="space-y-1">
                                <p className="text-sm font-semibold text-[var(--intake-text)]">任意で追加する項目</p>
                                <p className="text-xs leading-6 text-[var(--intake-text-muted)]">
                                  未入力でも構いません。AI が補完しながら調査軸を整えます。
                                </p>
                              </div>
                              <FieldBadge tone="assistive">AI が補完</FieldBadge>
                            </div>
                            <div className="mt-4 space-y-5">
                              <FieldGroup
                                label="公式サイト"
                                description="公式サイトまたは主要ドメインを入力してください。research の anchor に利用します。"
                                id={websiteFieldId}
                                badgeLabel="任意"
                                badgeTone="optional"
                              >
                                <Input
                                  id={websiteFieldId}
                                  ref={identityWebsiteInputRef}
                                  value={officialWebsite}
                                  onChange={(event) => setOfficialWebsite(event.target.value)}
                                  onBlur={() => {
                                    setIdentityWebsiteTouched(true);
                                    if (normalizeIdentityDomain(officialWebsite)) {
                                      setOfficialWebsite(normalizedIdentityWebsite);
                                    }
                                  }}
                                  placeholder="https://example.com"
                                  aria-invalid={Boolean(identityWebsiteError)}
                                  aria-describedby={websiteHelpId}
                                  className="h-12 rounded-[1.15rem] border-[var(--intake-border)] bg-[var(--intake-surface-soft)] text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus-visible:ring-[var(--intake-ring)]"
                                />
                                <p
                                  id={websiteHelpId}
                                  className={cn("text-xs", identityWebsiteError ? "text-[var(--intake-danger)]" : "text-[var(--intake-text-muted)]")}
                                >
                                  {identityWebsiteError || "ドメインは自動で正規化します。"}
                                </p>
                              </FieldGroup>

                              <div className="grid gap-5 sm:grid-cols-2">
                                <FieldGroup
                                  label="別名・略称"
                                  description="カンマ区切りで入力します。検索語の補助に使います。"
                                  id={aliasesFieldId}
                                  badgeLabel="任意"
                                  badgeTone="optional"
                                >
                                  <Input
                                    id={aliasesFieldId}
                                    value={identityAliases}
                                    onChange={(event) => setIdentityAliases(event.target.value)}
                                    placeholder="例: Pylon AI, Pylon Platform"
                                    autoComplete="off"
                                    className="h-12 rounded-[1.15rem] border-[var(--intake-border)] bg-[var(--intake-surface-soft)] text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus-visible:ring-[var(--intake-ring)]"
                                  />
                                </FieldGroup>

                                <FieldGroup
                                  label="除外したい同名サービス"
                                  description="既知の同名プロダクトや会社名があれば登録します。"
                                  id={excludedEntitiesFieldId}
                                  badgeLabel="任意"
                                  badgeTone="optional"
                                >
                                  <Input
                                    id={excludedEntitiesFieldId}
                                    value={excludedEntityNames}
                                    onChange={(event) => setExcludedEntityNames(event.target.value)}
                                    placeholder="例: Basler pylon, AppMatch Pylon"
                                    autoComplete="off"
                                    className="h-12 rounded-[1.15rem] border-[var(--intake-border)] bg-[var(--intake-surface-soft)] text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus-visible:ring-[var(--intake-ring)]"
                                  />
                                </FieldGroup>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-[1.3rem] border border-[var(--intake-border)] bg-[var(--intake-elevated)] px-4 py-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <FieldBadge tone="assistive">未入力でも補完</FieldBadge>
                            <p className="text-sm font-medium text-[var(--intake-text)]">AI が先回りして行うこと</p>
                          </div>
                          <div className="mt-3 space-y-2">
                            {(identityAutofillMessages.length > 0
                              ? identityAutofillMessages
                              : ["任意項目は十分に入力されています。AI は入力された値を優先して調査軸を固定します。"]).map((item) => (
                              <div key={item} className="intake-note px-3 py-3 text-sm leading-6 text-[var(--intake-text-soft)]">
                                {item}
                              </div>
                            ))}
                          </div>
                        </div>

                        {(companyName.trim() || productName.trim() || officialWebsite.trim() || identityAliases.trim() || excludedEntityNames.trim()) && (
                          <div className="flex flex-wrap gap-2 text-xs text-[var(--intake-text-soft)]">
                            {companyName.trim() && <SignalPill>{companyName.trim()}</SignalPill>}
                            <SignalPill>{productName.trim() || normalizedName || "プロジェクト名を利用"}</SignalPill>
                            {officialWebsite.trim() && <SignalPill>{normalizeIdentityDomain(officialWebsite) ?? officialWebsite.trim()}</SignalPill>}
                            {normalizeIdentityListInput(excludedEntityNames).slice(0, 2).map((item) => (
                              <SignalPill key={item}>除外: {item}</SignalPill>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="order-4 intake-note overflow-hidden p-4 sm:order-3">
                    <button
                      type="button"
                      onClick={() => setShowAdvanced((value) => !value)}
                      aria-expanded={showAdvanced}
                      aria-controls={advancedSectionId}
                      className="flex w-full items-start justify-between gap-4 text-left"
                    >
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-[var(--intake-text)]">補足情報を先に入力する</p>
                        <p className="text-sm leading-6 text-[var(--intake-text-muted)]">
                          brief や既存リポジトリを最初から渡したい場合だけ開いてください。空のままでも始められます。
                        </p>
                      </div>
                      <div className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[var(--intake-border)] bg-[var(--intake-elevated)] text-[var(--intake-text-soft)]">
                        {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </div>
                    </button>

                    {showAdvanced && (
                      <div id={advancedSectionId} className="mt-5 space-y-5 border-t border-[var(--intake-border)] pt-5">
                        <FieldGroup
                          label="初期 brief"
                          description="対象、欲しい判断、避けたい失敗など、出発点となる考えを簡潔に書いてください。"
                          id={briefFieldId}
                        >
                          <textarea
                            id={briefFieldId}
                            value={brief}
                            onChange={(event) => {
                              if (event.target.value.length <= MAX_BRIEF_LENGTH) {
                                setBrief(event.target.value);
                              }
                            }}
                            rows={6}
                            maxLength={MAX_BRIEF_LENGTH}
                            placeholder="例: 営業、マーケ、CS の情報が分断されている。次にどこへ打ち手を置くべきかを一画面で判断できる運用基盤を作りたい。"
                            className="w-full rounded-[1.15rem] border border-[var(--intake-border)] bg-[var(--intake-surface-soft)] px-4 py-4 text-sm leading-7 text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--intake-ring)]"
                          />
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <p className="text-xs text-[var(--intake-text-muted)]">{brief.length}/{MAX_BRIEF_LENGTH} 文字</p>
                            <DensityPill density={briefDensity} />
                          </div>
                        </FieldGroup>

                        <FieldGroup
                          label="GitHub リポジトリ"
                          description="既存リポジトリがある場合のみ入力してください。owner/repo 形式と GitHub URL のどちらでも構いません。"
                          id={githubFieldId}
                        >
                          <Input
                            id={githubFieldId}
                            ref={githubInputRef}
                            value={githubRepo}
                            onChange={(event) => setGithubRepo(event.target.value)}
                            onBlur={() => {
                              setRepoTouched(true);
                              if (normalizedGithubRepo) {
                                setGithubRepo(normalizedGithubRepo);
                              }
                            }}
                            placeholder="owner/repo または https://github.com/owner/repo"
                            aria-invalid={Boolean(githubRepoError)}
                            aria-describedby={githubHelpId}
                            className="h-12 rounded-[1.15rem] border-[var(--intake-border)] bg-[var(--intake-surface-soft)] text-[var(--intake-text)] placeholder:text-[var(--intake-text-muted)] focus-visible:ring-[var(--intake-ring)]"
                          />
                          <div id={githubHelpId} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                            <p className={githubRepoError ? "text-[var(--intake-danger)]" : "text-[var(--intake-text-muted)]"}>
                              {githubRepoError || "入力後に owner/repo 形式へ整えます。"}
                            </p>
                            {normalizedGithubRepo && githubRepo.trim() && (
                              <SignalPill>{normalizedGithubRepo}</SignalPill>
                            )}
                          </div>
                        </FieldGroup>
                      </div>
                    )}
                  </div>

                  <div className="order-3 space-y-3 sm:order-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        type="submit"
                        disabled={!canSubmit}
                        className="h-12 rounded-full border border-[var(--intake-border-strong)] bg-[linear-gradient(135deg,var(--intake-accent),#c7b28a)] px-5 text-sm font-semibold text-[var(--intake-ink-deep)] shadow-[var(--intake-shadow-soft)] transition-transform hover:-translate-y-0.5 hover:brightness-105"
                      >
                        {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderPlus className="h-4 w-4" />}
                        プロジェクトを作成してリサーチを開始
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => navigate("/dashboard")}
                        className="h-12 rounded-full border-[var(--intake-border)] bg-transparent px-5 text-[var(--intake-text-soft)] hover:bg-[var(--intake-elevated)] hover:text-[var(--intake-text)]"
                      >
                        キャンセル
                      </Button>
                    </div>
                    <p className="text-xs leading-6 text-[var(--intake-text-muted)]">
                      作成後はリサーチ画面へ移動し、次の論点を確認できます。
                    </p>
                    {error && (
                      <p id={errorMessageId} className="rounded-[1rem] border border-[var(--intake-danger)] bg-[var(--intake-danger-soft)] px-4 py-3 text-sm text-[var(--intake-text)]" role="alert" aria-live="polite">
                        {error}
                      </p>
                    )}
                  </div>
                </form>
              </div>
            </section>
          </aside>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          {STARTUP_FACTS.map((fact) => (
            <div key={fact.title} className="intake-panel rounded-[var(--intake-radius-xl)] p-5 sm:p-6">
              <div className="flex items-start gap-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[var(--intake-border)] bg-[var(--intake-accent-soft)] text-[var(--intake-accent-strong)]">
                  <fact.icon className="h-4 w-4" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-[var(--intake-text)]">{fact.title}</p>
                  <p className="text-sm leading-6 text-[var(--intake-text-muted)]">{fact.description}</p>
                </div>
              </div>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

function SectionEyebrow({
  icon: Icon,
  children,
}: {
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <div className="intake-eyebrow">
      <Icon className="h-3.5 w-3.5" />
      {children}
    </div>
  );
}

function SignalPill({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border border-[var(--intake-border)] bg-[var(--intake-elevated)] px-3 py-1.5 text-[var(--intake-text-soft)]">
      {children}
    </span>
  );
}

function DensityPill({ density }: { density: "empty" | "light" | "good" | "dense" }) {
  const label =
    density === "empty" ? "未入力" : density === "light" ? "短め" : density === "good" ? "十分" : "詳細";

  return (
    <div
      className={cn(
        "rounded-full px-3 py-1 text-[11px] font-medium",
        density === "empty" && "bg-[var(--intake-elevated)] text-[var(--intake-text-muted)]",
        density === "light" && "bg-[var(--intake-bronze-soft)] text-[var(--intake-text-soft)]",
        density === "good" && "bg-[var(--intake-success-soft)] text-[var(--intake-text-soft)]",
        density === "dense" && "bg-[var(--intake-accent-soft)] text-[var(--intake-accent-strong)]",
      )}
    >
      {label}
    </div>
  );
}

function FieldGroup({
  label,
  description,
  id,
  children,
  descriptionClassName,
  badgeLabel,
  badgeTone,
}: {
  label: string;
  description: string;
  id: string;
  children: ReactNode;
  descriptionClassName?: string;
  badgeLabel?: string;
  badgeTone?: "required" | "optional" | "assistive";
}) {
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-start gap-x-2 gap-y-1.5">
          <label htmlFor={id} className="text-sm font-semibold text-[var(--intake-text)]">
            {label}
          </label>
          {badgeLabel ? <FieldBadge tone={badgeTone}>{badgeLabel}</FieldBadge> : null}
        </div>
        <p className={cn("text-sm leading-6 text-[var(--intake-text-muted)]", descriptionClassName)}>{description}</p>
      </div>
      {children}
    </div>
  );
}

function FieldBadge({
  children,
  tone = "optional",
}: {
  children: ReactNode;
  tone?: "required" | "optional" | "assistive";
}) {
  return (
    <Badge
      variant={tone === "required" ? "required" : tone === "assistive" ? "assistive" : "optional"}
      size="field"
    >
      {children}
    </Badge>
  );
}
