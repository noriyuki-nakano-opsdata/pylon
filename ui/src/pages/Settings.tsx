import { useState } from "react";
import { Settings as SettingsIcon, Key, Building2, Palette } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export function Settings() {
  const [tenantName, setTenantName] = useState("Default Tenant");
  const [tenantSaved, setTenantSaved] = useState(false);
  const [language, setLanguage] = useState("ja");
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
          <h1 className="text-2xl font-bold tracking-tight">設定</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          アプリケーションの各種設定を管理します。
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* API Providers */}
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Key className="h-5 w-5 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">API Providers</h2>
          </div>
          <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
            外部APIプロバイダーの接続設定を管理します。
          </p>
          <Link
            to="/providers"
            className="text-xs font-medium text-primary hover:underline"
          >
            プロバイダー一覧へ →
          </Link>
        </Card>

        {/* Tenant Settings */}
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Building2 className="h-5 w-5 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">テナント設定</h2>
          </div>
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
            テナントの基本情報や権限を管理します。
          </p>
          <div className="space-y-2">
            <label className="block text-xs font-medium text-foreground">テナント表示名</label>
            <Input
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              className="h-8 text-xs"
            />
            <Button size="sm" className="h-7 text-xs" onClick={handleSaveTenant}>
              {tenantSaved ? "保存しました" : "保存"}
            </Button>
          </div>
        </Card>

        {/* Display Settings */}
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Palette className="h-5 w-5 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">表示設定</h2>
          </div>
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
            UIテーマや言語など表示に関する設定を変更します。
          </p>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-foreground mb-1">言語</label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="flex h-8 w-full rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="ja">日本語</option>
                <option value="en">English</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-foreground mb-1">テーマ</label>
              <select
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                className="flex h-8 w-full rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
                <option value="system">System</option>
              </select>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
