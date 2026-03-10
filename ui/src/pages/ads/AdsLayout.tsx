import { NavLink, Outlet } from "react-router-dom";
import { Megaphone, LayoutDashboard, Search, FileBarChart, Map, Wallet } from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { to: "dashboard", label: "ダッシュボード", icon: LayoutDashboard, end: true },
  { to: "audit", label: "監査", icon: Search, end: false },
  { to: "reports", label: "レポート", icon: FileBarChart, end: false },
  { to: "plan", label: "プラン", icon: Map, end: false },
  { to: "budget", label: "予算最適化", icon: Wallet, end: false },
] as const;

export function AdsLayout() {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border px-6 pt-4 pb-0">
        <div className="flex items-center gap-2 mb-3">
          <Megaphone className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-bold tracking-tight text-foreground">広告管理</h1>
        </div>

        {/* Tab bar */}
        <nav className="flex gap-1">
          {TABS.map((tab) => (
            <NavLink
              key={tab.label}
              to={tab.to}
              end={tab.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:border-border",
                )
              }
            >
              <tab.icon className="h-3.5 w-3.5" />
              {tab.label}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  );
}
