import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, ChevronDown, ChevronUp, Zap, AlertTriangle, FileBarChart,
  Download, Copy,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/PageSkeleton";
import { EmptyState } from "@/components/EmptyState";
import { adsApi } from "@/api/ads";
import { cn } from "@/lib/utils";
import type { AuditGrade, CheckResult, CheckSeverity, PlatformHealthScore, AdsPlatform } from "@/types/ads";

const GRADE_COLORS: Record<AuditGrade, string> = {
  A: "bg-emerald-500/10 text-emerald-500 border-emerald-500/30",
  B: "bg-blue-500/10 text-blue-500 border-blue-500/30",
  C: "bg-yellow-500/10 text-yellow-500 border-yellow-500/30",
  D: "bg-orange-500/10 text-orange-500 border-orange-500/30",
  F: "bg-red-500/10 text-red-500 border-red-500/30",
};

const RESULT_COLORS: Record<CheckResult, string> = {
  pass: "text-emerald-500",
  warning: "text-yellow-500",
  fail: "text-red-500",
  na: "text-muted-foreground",
};

const SEVERITY_VARIANTS: Record<CheckSeverity, string> = {
  critical: "bg-red-500/10 text-red-500",
  high: "bg-orange-500/10 text-orange-500",
  medium: "bg-yellow-500/10 text-yellow-500",
  low: "bg-blue-500/10 text-blue-500",
};

const PLATFORM_LABELS: Record<AdsPlatform, string> = {
  google: "Google Ads", meta: "Meta Ads", linkedin: "LinkedIn Ads",
  tiktok: "TikTok Ads", microsoft: "Microsoft Ads",
};

export function AuditReport() {
  const { reportId } = useParams();
  const navigate = useNavigate();

  if (reportId) return <ReportDetail reportId={reportId} onBack={() => navigate(".")} />;
  return <ReportList onSelect={(id) => navigate(id)} />;
}

/* ── Report List ── */
function ReportList({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: reports, isLoading } = useQuery({
    queryKey: ["ads", "reports"],
    queryFn: () => adsApi.listReports(),
  });

  if (isLoading) return <PageSkeleton />;
  if (!reports || reports.length === 0) {
    return (
      <div className="p-6">
        <EmptyState icon={FileBarChart} title="レポートなし" description="監査を実行するとレポートが表示されます。" />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <h2 className="text-lg font-bold text-foreground">監査レポート一覧</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {reports.map((r) => (
          <button key={r.id} onClick={() => onSelect(r.id)} className="text-left">
            <Card className="transition-colors hover:border-primary/50">
              <CardContent className="p-4">
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-foreground">{r.aggregate_score}</span>
                  <Badge variant="outline" className={cn("text-xs", GRADE_COLORS[r.aggregate_grade])}>
                    {r.aggregate_grade}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {new Date(r.created_at).toLocaleDateString("ja-JP")} ・ {r.platforms.map((p) => PLATFORM_LABELS[p.platform]).join(", ")}
                </p>
              </CardContent>
            </Card>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Report Detail ── */
function ReportDetail({ reportId, onBack }: { reportId: string; onBack: () => void }) {
  const [copied, setCopied] = useState(false);
  const { data: report, isLoading } = useQuery({
    queryKey: ["ads", "report", reportId],
    queryFn: () => adsApi.getReport(reportId),
  });

  if (isLoading) return <PageSkeleton />;
  if (!report) return <div className="p-6 text-muted-foreground">レポートが見つかりません</div>;

  const crossItems = [
    { label: "予算配分", value: report.cross_platform.budget_assessment },
    { label: "トラッキング整合性", value: report.cross_platform.tracking_consistency },
    { label: "クリエイティブ一貫性", value: report.cross_platform.creative_consistency },
    { label: "アトリビューション重複", value: report.cross_platform.attribution_overlap },
  ];

  const handleExportCsv = () => {
    const allChecks = report.platforms.flatMap((p) =>
      p.checks.map((c) => ({
        id: c.id,
        platform: p.platform,
        category: c.category,
        name: c.name,
        severity: c.severity,
        result: c.result,
        finding: c.finding,
      })),
    );
    const header = ["ID", "Platform", "Category", "Name", "Severity", "Result", "Finding"];
    const rows = allChecks.map((c) =>
      [c.id, c.platform, c.category, c.name, c.severity, c.result, `"${(c.finding ?? "").replace(/"/g, '""')}"`].join(","),
    );
    const csv = "\uFEFF" + [header.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit-report-${reportId}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyReport = () => {
    const criticalCount = report.critical_issues.length;
    const quickWinCount = report.quick_wins.length;
    const platformSummary = report.platforms
      .map((p) => `- ${PLATFORM_LABELS[p.platform]}: ${p.score}点 (${p.grade})`)
      .join("\n");
    const md = [
      `# 監査レポート`,
      ``,
      `- 総合スコア: **${report.aggregate_score}** (${report.aggregate_grade})`,
      `- 業種: ${report.industry_type}`,
      `- 作成日: ${new Date(report.created_at).toLocaleDateString("ja-JP")}`,
      ``,
      `## プラットフォーム別スコア`,
      platformSummary,
      ``,
      `## サマリー`,
      `- 重大な問題: ${criticalCount}件`,
      `- クイックウィン: ${quickWinCount}件`,
    ].join("\n");
    navigator.clipboard.writeText(md).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-baseline gap-3">
          <span className="text-4xl font-bold text-foreground">{report.aggregate_score}</span>
          <Badge variant="outline" className={cn("text-xl px-3 py-1 font-bold", GRADE_COLORS[report.aggregate_grade])}>
            {report.aggregate_grade}
          </Badge>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleExportCsv}>
            <Download className="mr-1.5 h-3.5 w-3.5" />CSV出力
          </Button>
          <Button variant="outline" size="sm" onClick={handleCopyReport}>
            <Copy className="mr-1.5 h-3.5 w-3.5" />{copied ? "コピー済み" : "レポートコピー"}
          </Button>
        </div>
        <div className="text-right text-sm text-muted-foreground">
          <p>{new Date(report.created_at).toLocaleDateString("ja-JP")}</p>
          <p className="capitalize">{report.industry_type.replace("-", " ")}</p>
        </div>
      </div>

      {/* Quick Wins */}
      {report.quick_wins.length > 0 && (
        <Card className="border-emerald-500/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-emerald-500">
              <Zap className="h-4 w-4" /> クイックウィン ({report.quick_wins.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {report.quick_wins.map((c) => (
                <div key={c.id} className="flex items-start gap-3 rounded-md border border-border p-2">
                  <Badge className={cn("text-[10px] shrink-0", SEVERITY_VARIANTS[c.severity])}>{c.severity}</Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">{c.name}</p>
                    <p className="text-xs text-muted-foreground">{c.finding}</p>
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">{c.estimated_fix_time_min}分</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Critical Issues */}
      {report.critical_issues.length > 0 && (
        <Card className="border-red-500/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-red-500">
              <AlertTriangle className="h-4 w-4" /> 重大な問題 ({report.critical_issues.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {report.critical_issues.map((c) => (
                <div key={c.id} className="rounded-md border border-red-500/20 bg-red-500/5 p-3">
                  <p className="text-sm font-medium text-foreground">{c.name}</p>
                  <p className="text-xs text-muted-foreground mt-1">{c.finding}</p>
                  <p className="text-xs text-emerald-500 mt-1">{c.remediation}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Platform Sections */}
      {report.platforms.map((p) => (
        <PlatformSection key={p.platform} platform={p} />
      ))}

      {/* Cross-platform Analysis */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">クロスプラットフォーム分析</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {crossItems.map((item) => (
              <div key={item.label} className="rounded-md border border-border p-3">
                <p className="text-xs font-medium text-muted-foreground">{item.label}</p>
                <p className="text-sm text-foreground mt-1">{item.value}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ── Platform Section ── */
function PlatformSection({ platform }: { platform: PlatformHealthScore }) {
  const [open, setOpen] = useState(false);
  const categoryEntries = Object.entries(platform.category_scores);

  return (
    <Card>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 p-4 text-left"
      >
        <span className="text-sm font-bold text-foreground">{PLATFORM_LABELS[platform.platform]}</span>
        <div className="flex items-center gap-2 flex-1">
          <div className="h-1.5 w-24 rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full",
                platform.score >= 80 ? "bg-emerald-500" : platform.score >= 60 ? "bg-yellow-500" : "bg-red-500",
              )}
              style={{ width: `${platform.score}%` }}
            />
          </div>
          <span className="text-sm font-mono text-foreground">{platform.score}</span>
          <Badge variant="outline" className={cn("text-xs", GRADE_COLORS[platform.grade])}>{platform.grade}</Badge>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
      </button>

      {open && (
        <div className="border-t border-border p-4 space-y-4">
          {/* Category scores */}
          {categoryEntries.length > 0 && (
            <div className="flex flex-wrap gap-3">
              {categoryEntries.map(([cat, score]) => (
                <div key={cat} className="text-xs">
                  <span className="text-muted-foreground">{cat}: </span>
                  <span className="font-mono text-foreground">{score}</span>
                </div>
              ))}
            </div>
          )}

          {/* Checks table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">ID</th>
                  <th className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">チェック名</th>
                  <th className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">重要度</th>
                  <th className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">結果</th>
                  <th className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">所見</th>
                </tr>
              </thead>
              <tbody>
                {platform.checks.map((c) => (
                  <tr key={c.id} className="border-b border-border last:border-0">
                    <td className="px-2 py-1.5 text-xs font-mono text-muted-foreground">{c.id}</td>
                    <td className="px-2 py-1.5 text-xs text-foreground">{c.name}</td>
                    <td className="px-2 py-1.5">
                      <Badge className={cn("text-[10px]", SEVERITY_VARIANTS[c.severity])}>{c.severity}</Badge>
                    </td>
                    <td className={cn("px-2 py-1.5 text-xs font-medium", RESULT_COLORS[c.result])}>{c.result}</td>
                    <td className="px-2 py-1.5 text-xs text-muted-foreground max-w-xs truncate">{c.finding}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
