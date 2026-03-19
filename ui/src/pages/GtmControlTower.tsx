import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  CalendarDays,
  FileText,
  Loader2,
  Megaphone,
  Radar,
  ShieldAlert,
  Target,
  Users,
} from "lucide-react";
import { gtmApi } from "@/api/gtm";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const PRIORITY_CLASS = {
  high: "bg-red-500/15 text-red-300 border-red-500/20",
  medium: "bg-amber-500/15 text-amber-200 border-amber-500/20",
  low: "bg-emerald-500/15 text-emerald-200 border-emerald-500/20",
} as const;

const STATUS_CLASS = {
  strong: "bg-emerald-500/15 text-emerald-200 border-emerald-500/20",
  watch: "bg-amber-500/15 text-amber-200 border-amber-500/20",
  thin: "bg-red-500/15 text-red-300 border-red-500/20",
  covered: "bg-emerald-500/15 text-emerald-200 border-emerald-500/20",
  partial: "bg-amber-500/15 text-amber-200 border-amber-500/20",
  missing: "bg-red-500/15 text-red-300 border-red-500/20",
} as const;

function coverageTone(score: number): string {
  if (score >= 0.8) return "text-emerald-300";
  if (score >= 0.55) return "text-amber-200";
  return "text-red-300";
}

export function GtmControlTower() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["gtm", "overview"],
    queryFn: () => gtmApi.getOverview(),
  });

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !data) {
    const message = error instanceof Error ? error.message : "GTM overview の取得に失敗しました";
    return (
      <div className="p-6">
        <Card className="border-red-500/20 bg-red-500/10 p-6 text-red-100">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <h1 className="text-lg font-semibold">GTM Control Tower</h1>
              <p className="mt-1 text-sm text-red-100/80">{message}</p>
            </div>
          </div>
        </Card>
      </div>
    );
  }

  const coveragePct = Math.round(data.summary.coverage_score * 100);

  return (
    <div className="space-y-6 p-6">
      <section className="overflow-hidden rounded-3xl border border-border bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.18),_transparent_32%),linear-gradient(135deg,_rgba(15,23,42,0.96),_rgba(17,24,39,0.96))] p-6 text-slate-50 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.55)]">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-amber-100/80">
              <Radar className="h-3.5 w-3.5" />
              GTM Control Tower
            </div>
            <h1 className="text-3xl font-semibold tracking-tight">Sales, marketing, CS, partnerships, and ads in one operating view.</h1>
            <p className="mt-3 max-w-2xl text-sm text-slate-300">
              エージェント構成、実行中タスク、直近のコンテンツ、予定イベント、広告監査の信号を束ねて、
              GTM オペレーションの厚みと不足を可視化します。
            </p>
          </div>
          <div className="grid min-w-[280px] grid-cols-2 gap-3">
            <MetricCard icon={Users} label="GTM Agents" value={String(data.summary.total_gtm_agents)} />
            <MetricCard icon={Activity} label="Open Tasks" value={String(data.summary.open_tasks)} />
            <MetricCard icon={CalendarDays} label="Upcoming Events" value={String(data.summary.upcoming_events)} />
            <MetricCard icon={BarChart3} label="Coverage" value={`${coveragePct}%`} valueClass={coverageTone(data.summary.coverage_score)} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard icon={Target} label="Open GTM Tasks" value={data.summary.open_tasks} hint="sales + marketing + cs + partnerships + ads" />
        <KpiCard icon={FileText} label="Active Content" value={data.summary.active_content_items} hint="research, draft, review, ready" />
        <KpiCard icon={CalendarDays} label="Upcoming Cadence" value={data.summary.upcoming_events} hint="meetings, webinars, reviews" />
        <KpiCard icon={Megaphone} label="Recent Ads Reports" value={data.summary.recent_ads_reports} hint="last 30 days" />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="p-5">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-foreground">Operating Lanes</h2>
            <p className="text-sm text-muted-foreground">チーム別の稼働密度とプレイブック装備。</p>
          </div>
          <div className="space-y-3">
            {data.teams.map((team) => (
              <div key={team.id} className="rounded-2xl border border-border bg-card/50 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-foreground">{team.label}</h3>
                      <Badge className={cn("border", STATUS_CLASS[team.status])}>{team.status}</Badge>
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                      Agents {team.agent_count} · Tasks {team.open_tasks} · Events {team.upcoming_events} · Content {team.active_content}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {team.core_skills.slice(0, 5).map((skillId) => (
                      <Badge key={skillId} variant="secondary" className="bg-secondary/70 text-secondary-foreground">
                        {skillId}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-foreground">Recommendations</h2>
            <p className="text-sm text-muted-foreground">今の環境に対する次アクション。</p>
          </div>
          <div className="space-y-3">
            {data.recommendations.map((item, idx) => (
              <div key={`${item.title}-${idx}`} className="rounded-2xl border border-border bg-card/50 p-4">
                <div className="flex items-center gap-2">
                  <Badge className={cn("border", PRIORITY_CLASS[item.priority])}>{item.priority}</Badge>
                  <span className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{item.owner_team}</span>
                </div>
                <h3 className="mt-3 font-semibold text-foreground">{item.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{item.rationale}</p>
                <p className="mt-3 text-sm text-foreground">{item.action}</p>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <Card className="p-5">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-foreground">Motion Health</h2>
            <p className="text-sm text-muted-foreground">主要 GTM モーションを lane 単位で確認。</p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {data.motions.map((motion) => (
              <div key={motion.id} className="rounded-2xl border border-border bg-card/50 p-4">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-foreground">{motion.label}</h3>
                  <Badge className={cn("border", STATUS_CLASS[motion.status])}>{motion.status}</Badge>
                </div>
                <p className="mt-1 text-xs uppercase tracking-[0.14em] text-muted-foreground">{motion.owner_team}</p>
                <p className="mt-3 text-sm text-muted-foreground">{motion.summary}</p>
                <div className="mt-4 space-y-2">
                  {motion.signals.map((signal) => (
                    <div key={`${motion.id}-${signal.label}`} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{signal.label}</span>
                      <span className="font-medium text-foreground">{signal.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-foreground">Capability Coverage</h2>
            <p className="text-sm text-muted-foreground">この環境で利用可能な GTM プレイブックの厚み。</p>
          </div>
          <div className="space-y-3">
            {data.capabilities.map((capability) => (
              <div key={capability.id} className="rounded-2xl border border-border bg-card/50 p-4">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-foreground">{capability.label}</h3>
                  <Badge className={cn("border", STATUS_CLASS[capability.status])}>{capability.status}</Badge>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{capability.summary}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {capability.skill_ids.map((skillId) => (
                    <Badge key={`${capability.id}-${skillId}`} variant="secondary" className="bg-secondary/70 text-secondary-foreground">
                      {skillId}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  valueClass,
}: {
  icon: typeof Radar;
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-slate-300">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={cn("mt-3 text-2xl font-semibold text-white", valueClass)}>{value}</div>
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Target;
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-foreground">{value}</p>
        </div>
        <div className="rounded-2xl bg-secondary p-3 text-secondary-foreground">
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <p className="mt-3 text-xs uppercase tracking-[0.12em] text-muted-foreground">{hint}</p>
    </Card>
  );
}
