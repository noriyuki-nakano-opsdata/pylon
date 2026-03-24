import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Settings as SettingsIcon, Key, Building2, Palette, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { healthApi, type HealthCheck } from "@/api/health";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/contexts/I18nContext";
import { queryKeys } from "@/lib/queryKeys";

type Translator = (key: string, values?: Record<string, string | number>) => string;

function readinessTierLabel(
  tier: string | undefined,
  t: Translator,
) {
  if (!tier) return "unknown";
  const key = `settings.readiness.tier.${tier}`;
  const translated = t(key);
  return translated === key ? tier : translated;
}

function readinessAction(check: HealthCheck, t: Translator) {
  if (check.production_capable === true) return null;
  if (check.name === "control_plane") return t("settings.readiness.action.control_plane");
  if (check.name === "auth") return t("settings.readiness.action.auth");
  if (check.name === "rate_limit") return t("settings.readiness.action.rate_limit");
  return null;
}

export function Settings() {
  const { locale, setLocale, t } = useI18n();
  const [tenantName, setTenantName] = useState("Default Tenant");
  const [tenantSaved, setTenantSaved] = useState(false);
  const [theme, setTheme] = useState("dark");
  const readinessQuery = useQuery({
    queryKey: queryKeys.providers.readiness(),
    queryFn: () => healthApi.getReadiness(),
    refetchInterval: 10_000,
  });

  const handleSaveTenant = () => {
    setTenantSaved(true);
    setTimeout(() => setTenantSaved(false), 2000);
  };

  const readinessChecks = (readinessQuery.data?.checks ?? []).filter(
    (check) => typeof check.production_capable === "boolean",
  );
  const productionCapableCount = readinessChecks.filter((check) => check.production_capable === true).length;
  const upgradeActions = Array.from(
    new Set(
      readinessChecks
        .map((check) => readinessAction(check, t))
        .filter((item): item is string => Boolean(item)),
    ),
  );

  return (
    <div className="space-y-6 p-6">
      <div>
        <div className="flex items-center gap-2">
          <SettingsIcon className="h-6 w-6 text-foreground" />
          <h1 className="text-2xl font-bold tracking-tight">{t("settings.title")}</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("settings.description")}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* API Providers */}
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Key className="h-5 w-5 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">{t("settings.apiProviders.title")}</h2>
          </div>
          <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
            {t("settings.apiProviders.description")}
          </p>
          <Link
            to="/providers"
            className="text-xs font-medium text-primary hover:underline"
          >
            {t("settings.apiProviders.link")} →
          </Link>
        </Card>

        {/* Tenant Settings */}
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Building2 className="h-5 w-5 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">{t("settings.tenant.title")}</h2>
          </div>
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
            {t("settings.tenant.description")}
          </p>
          <div className="space-y-2">
            <label className="block text-xs font-medium text-foreground">{t("settings.tenant.displayName")}</label>
            <Input
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              className="h-8 text-xs"
            />
            <Button size="sm" className="h-7 text-xs" onClick={handleSaveTenant}>
              {tenantSaved ? t("common.saved") : t("common.save")}
            </Button>
          </div>
        </Card>

        {/* Display Settings */}
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Palette className="h-5 w-5 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">{t("settings.display.title")}</h2>
          </div>
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
            {t("settings.display.description")}
          </p>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-foreground">{t("common.language")}</label>
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value as "ja" | "en")}
                className="flex h-8 w-full rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="ja">{t("common.japanese")}</option>
                <option value="en">{t("common.english")}</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-foreground">{t("common.theme")}</label>
              <select
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                className="flex h-8 w-full rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="dark">{t("common.dark")}</option>
                <option value="light">{t("common.light")}</option>
                <option value="system">{t("common.system")}</option>
              </select>
            </div>
          </div>
        </Card>

        <Card className="p-5 sm:col-span-2 lg:col-span-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="mb-3 flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-primary" />
                <h2 className="text-sm font-semibold text-foreground">{t("settings.readiness.title")}</h2>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {t("settings.readiness.description")}
              </p>
            </div>
            {readinessQuery.data ? (
              <StatusBadge status={readinessQuery.data.status} />
            ) : null}
          </div>

          {readinessQuery.isLoading ? (
            <p className="mt-4 text-sm text-muted-foreground">
              {t("settings.readiness.loading")}
            </p>
          ) : readinessQuery.isError ? (
            <p className="mt-4 text-sm text-destructive">
              {t("settings.readiness.error")}
            </p>
          ) : readinessQuery.data ? (
            <div className="mt-4 space-y-4">
              <div className="grid gap-3 lg:grid-cols-[15rem_minmax(0,1fr)]">
                <div className="rounded-2xl border border-border bg-background/70 p-4">
                  <p className="text-sm leading-6 text-foreground">
                    {readinessQuery.data.ready
                      ? t("settings.readiness.summaryReady")
                      : t("settings.readiness.summaryNotReady")}
                  </p>
                  <p className="mt-4 text-2xl font-semibold text-foreground">
                    {productionCapableCount} / {readinessChecks.length}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t("settings.readiness.productionCapable")}
                  </p>
                </div>

                <div className="grid gap-3 md:grid-cols-3">
                  {readinessChecks.map((check) => (
                    <div
                      key={check.name}
                      className="rounded-2xl border border-border bg-background/70 p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-foreground">
                            {check.name}
                          </p>
                          <p className="mt-2 text-xs leading-5 text-muted-foreground">
                            {check.message}
                          </p>
                        </div>
                        <StatusBadge status={check.status} />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {check.backend ? (
                          <Badge variant="optional" size="field">{check.backend}</Badge>
                        ) : null}
                        {check.readiness_tier ? (
                          <Badge
                            variant={check.production_capable ? "assistive" : "optional"}
                            size="field"
                          >
                            {readinessTierLabel(check.readiness_tier, t)}
                          </Badge>
                        ) : null}
                        {typeof check.workflow_count === "number" ? (
                          <Badge variant="optional" size="field">
                            {check.workflow_count} workflows
                          </Badge>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {!readinessQuery.data.ready && upgradeActions.length > 0 ? (
                <div className="rounded-2xl border border-border bg-background/70 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    {t("settings.readiness.upgradePath")}
                  </p>
                  <div className="mt-3 space-y-2">
                    {upgradeActions.map((action) => (
                      <p key={action} className="text-sm leading-6 text-foreground">
                        {action}
                      </p>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
