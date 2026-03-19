import { useState } from "react";
import { Settings as SettingsIcon, Key, Building2, Palette } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/contexts/I18nContext";

export function Settings() {
  const { locale, setLocale, t } = useI18n();
  const [tenantName, setTenantName] = useState("Default Tenant");
  const [tenantSaved, setTenantSaved] = useState(false);
  const [theme, setTheme] = useState("dark");

  const handleSaveTenant = () => {
    setTenantSaved(true);
    setTimeout(() => setTenantSaved(false), 2000);
  };

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
      </div>
    </div>
  );
}
