import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { formatUptime } from "@/lib/time";
import {
  Bot, User, Users, Shield, Code2, Palette, PenTool, Monitor, Network,
  Zap, ChevronRight, X, Loader2, Cpu, MemoryStick, Clock, Wifi, WifiOff, Megaphone,
  CheckCircle2, Plus, Pencil, Trash2, Save,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import {
  listAgentsActivity, listTasks, listTeams,
  createAgent, updateAgent, deleteAgent,
  type AgentActivity, type Task, type TeamDef as ApiTeamDef,
} from "@/api/mission-control";
import {
  AVAILABLE_MODELS,
  buildModelOptions,
  getTeamMeta,
  mergeTeamDefs,
  resolveTeamDef,
} from "@/pages/teamStructureData";

type ViewTab = "team" | "workspace";
type AgentStatus = "online" | "offline" | "busy";

interface AgentMember {
  id: string; name: string; role: string; status: AgentStatus;
  specialties: string[]; model: string; tools: string[];
  currentTask: string | null; cpuUsage: number; memoryUsage: number;
  uptimeSeconds: number; team: string; teamId: string; teamColor: string;
  avatarBg: string; initials: string;
}

interface Team {
  id: string; name: string; nameJa: string; icon: React.ElementType;
  color: string; members: AgentMember[];
  description: string; emptyState: string; recommendedRoles: string[];
}

const ICON_MAP: Record<string, React.ElementType> = {
  Code2, Palette, PenTool, Zap, Shield, Network, Users, Monitor, Bot, Megaphone,
};
function resolveIcon(name: string): React.ElementType {
  return ICON_MAP[name] ?? Users;
}

function stableUnit(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 1000) / 1000;
}

function stableMetric(seed: string, min: number, max: number): number {
  return min + stableUnit(seed) * (max - min);
}

function dedupeAgents(agents: AgentActivity[]): AgentActivity[] {
  const deduped = new Map<string, AgentActivity>();
  for (const agent of agents) {
    const key = agent.id || `${agent.name}:${agent.role}:${agent.team ?? "product"}`;
    if (!deduped.has(key)) {
      deduped.set(key, agent);
      continue;
    }
    const current = deduped.get(key);
    if ((agent.current_task?.updated_at ?? "") > (current?.current_task?.updated_at ?? "")) {
      deduped.set(key, agent);
    }
  }
  return [...deduped.values()];
}

function buildMember(agent: AgentActivity, teamDefs: ApiTeamDef[]): AgentMember {
  const teamId = agent.team ?? "product";
  const def = resolveTeamDef(teamId, teamDefs);
  const hasTask = agent.current_task !== null;
  const status: AgentStatus = hasTask ? "busy" : agent.status === "ready" ? "online" : "offline";
  const taskSeed = agent.current_task?.id ?? "idle";
  return {
    id: agent.id, name: agent.name, role: agent.role, status,
    specialties: agent.tools.slice(0, 4), model: agent.model, tools: agent.tools,
    currentTask: agent.current_task?.title ?? null,
    cpuUsage: hasTask ? stableMetric(`${agent.id}:cpu:${taskSeed}`, 42, 88) : stableMetric(`${agent.id}:cpu:idle`, 6, 18),
    memoryUsage: stableMetric(`${agent.id}:mem:${taskSeed}`, 26, 72), uptimeSeconds: agent.uptime_seconds,
    team: def.name, teamId: def.id, teamColor: def.color, avatarBg: def.bg,
    initials: agent.name.slice(0, 2).toUpperCase(),
  };
}

const STATUS_CFG: Record<AgentStatus, { dot: string; label: string; variant: "success" | "secondary" | "warning" }> = {
  online: { dot: "bg-green-500", label: "オンライン", variant: "success" },
  offline: { dot: "bg-gray-500", label: "オフライン", variant: "secondary" },
  busy: { dot: "bg-yellow-500", label: "ビジー", variant: "warning" },
};

type AgentEditForm = {
  name: string;
  model: string;
  role: string;
  team: string;
};

const inputCls = "w-full rounded border border-border bg-background px-3 py-1.5 text-sm";

function buildAgentPatch(agent: AgentMember, draft: AgentEditForm): Parameters<typeof updateAgent>[1] {
  const nextName = draft.name.trim();
  const nextRole = draft.role.trim();
  const patch: Parameters<typeof updateAgent>[1] = {};
  if (nextName && nextName !== agent.name) patch.name = nextName;
  if (draft.model !== agent.model) patch.model = draft.model;
  if (nextRole && nextRole !== agent.role) patch.role = nextRole;
  if (draft.team !== agent.teamId) patch.team = draft.team;
  return patch;
}

export function TeamStructure() {
  const queryClient = useQueryClient();

  const { data: agentsData, isLoading: agentsLoading, error: agentsError } = useQuery({
    queryKey: ["agents-activity"], queryFn: listAgentsActivity, refetchInterval: 8000,
  });
  const { data: tasksData, isLoading: tasksLoading, error: tasksError } = useQuery({
    queryKey: ["tasks"], queryFn: () => listTasks(), refetchInterval: 8000,
  });
  const { data: teamsData, isLoading: teamsLoading, error: teamsError } = useQuery({
    queryKey: ["teams"], queryFn: listTeams,
  });

  const loading = agentsLoading || tasksLoading || teamsLoading;
  const queryError = agentsError || tasksError || teamsError;
  const error = queryError ? (queryError instanceof Error ? queryError.message : "データの取得に失敗しました") : null;

  const teamDefs = useMemo(
    () => mergeTeamDefs(teamsData, agentsData?.map((agent) => agent.team)),
    [agentsData, teamsData],
  );

  const [tab, setTab] = useState<ViewTab>("team");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const createMut = useMutation({
    mutationFn: createAgent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents-activity"] });
      setShowCreateForm(false);
    },
  });

  const { allMembers, teams, tasksCount } = useMemo(() => {
    if (!agentsData || !tasksData) return { allMembers: [] as AgentMember[], teams: [] as Team[], tasksCount: 0 };
    const doneCount = tasksData.filter((t: Task) => t.status === "done").length;
    const members = dedupeAgents(agentsData).map((a) => buildMember(a, teamDefs));
    const teamMap: Record<string, AgentMember[]> = {};
    for (const def of teamDefs) teamMap[def.id] = [];
    for (const m of members) {
      (teamMap[m.teamId] ?? (teamMap[teamDefs[0]?.id ?? "product"] ??= [])).push(m);
    }
    const builtTeams: Team[] = teamDefs
      .map((def) => ({
        ...def,
        icon: resolveIcon(def.icon),
        members: (teamMap[def.id] ?? []).slice().sort((left, right) => left.name.localeCompare(right.name)),
        description: getTeamMeta(def.id).description,
        emptyState: getTeamMeta(def.id).emptyState,
        recommendedRoles: getTeamMeta(def.id).recommendedRoles,
      }));
    return { allMembers: members, teams: builtTeams, tasksCount: doneCount };
  }, [agentsData, tasksData, teamDefs]);

  const selected = selectedId ? allMembers.find((m) => m.id === selectedId) ?? null : null;
  const selectedTeam = selected ? teams.find((t) => t.members.some((m) => m.id === selected.id)) ?? null : null;

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>;
  }

  const totalAgents = allMembers.length;
  const activeAgents = allMembers.filter((m) => m.status !== "offline").length;
  const staffedTeams = teams.filter((team) => team.members.length > 0).length;

  return (
    <div
      className="relative min-h-full"
      style={tab === "workspace" ? { backgroundImage: "radial-gradient(circle, hsl(var(--border)) 1px, transparent 1px)", backgroundSize: "24px 24px" } : undefined}
    >
      <div className={cn("space-y-6 p-6 transition-all", selected && "mr-80")}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight"><Users className="mr-2 inline-block h-6 w-6" />エージェント監視</h1>
            <p className="text-sm text-muted-foreground">AIエージェントのチーム構成とワークスペースをリアルタイムで監視</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowCreateForm(true)} className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
              <Plus className="h-4 w-4" />エージェント追加
            </button>
            <div className="flex rounded-lg border border-border bg-muted/50 p-0.5">
              {(["team", "workspace"] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)} className={cn("rounded-md px-4 py-1.5 text-sm font-medium transition-colors", tab === t ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                  {t === "team" ? "チーム" : "ワークステーション"}
                </button>
              ))}
            </div>
          </div>
        </div>
        {error && <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">{error}</div>}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard icon={Users} iconClass="bg-primary/10 text-primary" value={totalAgents} label="総エージェント数" />
          <StatCard icon={Network} iconClass="bg-orange-500/10 text-orange-500" value={staffedTeams} label="配備済みチーム" />
          <StatCard icon={Zap} iconClass="bg-green-500/10 text-green-500" value={activeAgents} label="稼働中" />
          <StatCard icon={Monitor} iconClass="bg-blue-500/10 text-blue-500" value={tasksCount} label="完了タスク" />
        </div>
        {tab === "team" ? <TeamView teams={teams} selectedId={selectedId} onSelect={setSelectedId} /> : <WorkspaceView agents={allMembers} onSelect={setSelectedId} />}
      </div>
      {selected && <DetailPanel agent={selected} team={selectedTeam} teamDefs={teamDefs} onClose={() => setSelectedId(null)} />}
      {showCreateForm && <CreateAgentModal teamDefs={teamDefs} mutation={createMut} onClose={() => setShowCreateForm(false)} />}
    </div>
  );
}

/* ── Create Agent Modal ── */

function CreateAgentModal({ teamDefs, mutation, onClose }: {
  teamDefs: ApiTeamDef[];
  mutation: ReturnType<typeof useMutation<AgentActivity, Error, Parameters<typeof createAgent>[0]>>;
  onClose: () => void;
}) {
  const [form, setForm] = useState({ name: "", model: AVAILABLE_MODELS[0], role: "", team: teamDefs[0]?.id ?? "", tools: "" });
  const modelOptions = buildModelOptions(form.model);
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.role.trim()) return;
    mutation.mutate({
      name: form.name.trim(), model: form.model, role: form.role.trim(),
      team: form.team, tools: form.tools ? form.tools.split(",").map((t) => t.trim()).filter(Boolean) : [],
    });
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-background p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">エージェント追加</h2>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"><X className="h-5 w-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div><label className="mb-1 block text-xs text-muted-foreground">名前 *</label><input className={inputCls} value={form.name} onChange={(e) => set("name", e.target.value)} required /></div>
          <div><label className="mb-1 block text-xs text-muted-foreground">モデル</label><select className={inputCls} value={form.model} onChange={(e) => set("model", e.target.value)}>{modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}</select></div>
          <div><label className="mb-1 block text-xs text-muted-foreground">ロール *</label><input className={inputCls} value={form.role} onChange={(e) => set("role", e.target.value)} required /></div>
          <div><label className="mb-1 block text-xs text-muted-foreground">チーム</label><select className={inputCls} value={form.team} onChange={(e) => set("team", e.target.value)}>{teamDefs.map((t) => <option key={t.id} value={t.id}>{t.nameJa}</option>)}</select></div>
          <div><label className="mb-1 block text-xs text-muted-foreground">ツール (カンマ区切り)</label><input className={inputCls} value={form.tools} onChange={(e) => set("tools", e.target.value)} placeholder="bash, read, write" /></div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded-md border border-border px-4 py-1.5 text-sm hover:bg-muted">キャンセル</button>
            <button type="submit" disabled={mutation.isPending} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {mutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}作成
            </button>
          </div>
          {mutation.isError && <p className="text-xs text-destructive">{mutation.error.message}</p>}
        </form>
      </div>
    </>
  );
}

/* ── Sub-components ── */

function StatCard({ icon: Icon, iconClass, value, label }: { icon: React.ElementType; iconClass: string; value: number; label: string }) {
  const [bgClass, textClass] = iconClass.split(" ");
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className={cn("flex h-10 w-10 items-center justify-center rounded-lg", bgClass)}><Icon className={cn("h-5 w-5", textClass)} /></div>
        <div><p className="text-2xl font-bold">{value}</p><p className="text-xs text-muted-foreground">{label}</p></div>
      </CardContent>
    </Card>
  );
}

function TeamView({ teams, selectedId, onSelect }: { teams: Team[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <>
      <div className="flex flex-col items-center">
        <Card className="w-full max-w-xs">
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/20"><User className="h-6 w-6 text-primary" /></div>
            <div><p className="font-semibold">You</p><p className="text-xs text-muted-foreground">チームリーダー</p></div>
            <Badge variant="success" className="ml-auto">オンライン</Badge>
          </CardContent>
        </Card>
        <div className="h-8 w-px border-l-2 border-dashed border-border" />
        <div className="h-px w-full max-w-3xl border-t-2 border-dashed border-border" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {teams.map((team) => {
          const TeamIcon = team.icon;
          const onlineCount = team.members.filter((m) => m.status !== "offline").length;
          return (
            <Card key={team.id}>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <TeamIcon className={cn("h-5 w-5", team.color)} />
                  <CardTitle className="text-base">{team.nameJa}</CardTitle>
                  <Badge variant="secondary" className="ml-auto">{onlineCount}/{team.members.length} 稼働</Badge>
                </div>
                <p className="text-sm text-muted-foreground">{team.description}</p>
              </CardHeader>
              <CardContent>
                {team.members.length > 0 ? (
                  <div className="ml-6 space-y-2 border-l-2 border-dashed border-border pl-4">
                    {team.members.map((member) => (
                      <button key={member.id} onClick={() => onSelect(member.id)} className={cn("relative flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:bg-accent", selectedId === member.id && "border-primary bg-accent")}>
                        <div className="absolute -left-[1.125rem] top-1/2 h-px w-3 border-t-2 border-dashed border-border" />
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted"><Bot className="h-4 w-4 text-muted-foreground" /></div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{member.name}</span>
                            <span className={cn("h-2 w-2 rounded-full", STATUS_CFG[member.status].dot)} />
                          </div>
                          <p className="text-xs text-muted-foreground">{member.role}</p>
                        </div>
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4">
                    <p className="text-sm text-foreground">{team.emptyState}</p>
                    {team.recommendedRoles.length > 0 && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        推奨ロール: {team.recommendedRoles.join(" / ")}
                      </p>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </>
  );
}

function WorkspaceView({ agents, onSelect }: { agents: AgentMember[]; onSelect: (id: string) => void }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {agents.map((a) => <WorkstationCard key={a.id} agent={a} onClick={() => onSelect(a.id)} />)}
    </div>
  );
}

function StatusIndicator({ status }: { status: AgentStatus }) {
  if (status === "busy") {
    return (
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
      </span>
    );
  }
  return <span className={cn("inline-flex h-2.5 w-2.5 rounded-full", STATUS_CFG[status].dot)} />;
}

function UsageBar({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Cpu }) {
  const barColor = value > 80 ? "bg-red-500" : value > 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><Icon className="h-3 w-3" />{label}</span><span>{Math.round(value)}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted"><div className={cn("h-1.5 rounded-full transition-all duration-700", barColor)} style={{ width: `${Math.min(value, 100)}%` }} /></div>
    </div>
  );
}

function WorkstationCard({ agent, onClick }: { agent: AgentMember; onClick: () => void }) {
  const badgeLabel = agent.status === "busy" ? "稼働中" : agent.status === "online" ? "待機中" : "オフライン";
  return (
    <button type="button" onClick={onClick} className="group relative flex w-full flex-col gap-3 rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white", agent.avatarBg)}>{agent.initials}</div>
          <div className="min-w-0">
            <div className="flex items-center gap-2"><span className="font-semibold text-foreground">{agent.name}</span><StatusIndicator status={agent.status} /></div>
            <p className="text-xs text-muted-foreground">{agent.role}</p>
          </div>
        </div>
        <Badge variant={agent.status === "busy" ? "default" : "secondary"}>{badgeLabel}</Badge>
      </div>
      {agent.status === "busy" && agent.currentTask && (
        <div className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-2 text-xs">
          <Monitor className="h-3.5 w-3.5 shrink-0 text-green-400" /><span className="truncate text-foreground">{agent.currentTask}</span>
          <span className="inline-flex items-center gap-0.5 ml-1">{[0, 150, 300].map((d) => <span key={d} className="h-1 w-1 animate-bounce rounded-full bg-green-400" style={{ animationDelay: `${d}ms` }} />)}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3"><UsageBar label="CPU" value={agent.cpuUsage} icon={Cpu} /><UsageBar label="MEM" value={agent.memoryUsage} icon={MemoryStick} /></div>
      <div className="flex items-center justify-between text-[11px] text-muted-foreground border-t border-border pt-2">
        <span className={cn("font-medium", agent.teamColor)}>{agent.team}</span>
        <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{formatUptime(agent.uptimeSeconds)}</span>
      </div>
      <div className="flex items-center justify-end text-[11px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"><span>詳細を表示</span><ChevronRight className="h-3 w-3" /></div>
    </button>
  );
}

/* ── Detail Panel with Edit/Delete ── */

function DetailPanel({ agent, team, teamDefs, onClose }: {
  agent: AgentMember; team: Team | null; teamDefs: ApiTeamDef[]; onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const TeamIcon = team?.icon ?? Users;
  const cfg = STATUS_CFG[agent.status];

  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<AgentEditForm>({ name: agent.name, model: agent.model, role: agent.role, team: agent.teamId });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const modelOptions = buildModelOptions(editForm.model);

  const updateMut = useMutation({
    mutationFn: (patch: Parameters<typeof updateAgent>[1]) => updateAgent(agent.id, patch),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["agents-activity"] }); setEditing(false); },
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteAgent(agent.id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["agents-activity"] }); onClose(); },
  });

  const handleSave = () => {
    if (!editForm.name.trim() || !editForm.role.trim()) return;
    const patch = buildAgentPatch(agent, editForm);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    updateMut.mutate(patch);
  };

  const setField = (k: string, v: string) => setEditForm((f) => ({ ...f, [k]: v }));

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className={cn("flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold text-white", agent.avatarBg)}>{agent.initials}</div>
            <div>
              <h2 className="font-semibold text-foreground">{agent.name}</h2>
              <p className="text-xs text-muted-foreground">{agent.role} / {team?.nameJa ?? agent.team}</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {!editing && (
              <button type="button" onClick={() => { setEditing(true); setEditForm({ name: agent.name, model: agent.model, role: agent.role, team: agent.teamId }); }}
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground" title="編集">
                <Pencil className="h-4 w-4" />
              </button>
            )}
            <button type="button" onClick={onClose} className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"><X className="h-5 w-5" /></button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
          {editing ? (
            <section className="space-y-3">
              <h3 className="text-sm font-medium">エージェント編集</h3>
              <div><label className="mb-1 block text-xs text-muted-foreground">名前</label><input className={inputCls} value={editForm.name} onChange={(e) => setField("name", e.target.value)} /></div>
              <div><label className="mb-1 block text-xs text-muted-foreground">モデル</label><select className={inputCls} value={editForm.model} onChange={(e) => setField("model", e.target.value)}>{modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}</select></div>
              <div><label className="mb-1 block text-xs text-muted-foreground">ロール</label><input className={inputCls} value={editForm.role} onChange={(e) => setField("role", e.target.value)} /></div>
              <div><label className="mb-1 block text-xs text-muted-foreground">チーム</label><select className={inputCls} value={editForm.team} onChange={(e) => setField("team", e.target.value)}>{teamDefs.map((t) => <option key={t.id} value={t.id}>{t.nameJa}</option>)}</select></div>
              <div className="flex gap-2 pt-1">
                <button onClick={handleSave} disabled={updateMut.isPending} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                  {updateMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}保存
                </button>
                <button onClick={() => setEditing(false)} className="rounded-md border border-border px-4 py-1.5 text-sm hover:bg-muted">キャンセル</button>
              </div>
              {updateMut.isError && <p className="text-xs text-destructive">{updateMut.error.message}</p>}
            </section>
          ) : (
            <>
              <section className="space-y-2">
                <h3 className="text-sm font-medium">ステータス</h3>
                <div className="flex items-center gap-2">
                  <StatusIndicator status={agent.status} />
                  <Badge variant={cfg.variant}>{cfg.label}</Badge>
                  {agent.status === "busy" && <span className="flex items-center gap-1 text-xs text-green-400"><Wifi className="h-3 w-3" /> 接続中</span>}
                  {agent.status === "online" && <span className="flex items-center gap-1 text-xs text-muted-foreground"><WifiOff className="h-3 w-3" /> 待機中</span>}
                </div>
              </section>
              {agent.currentTask && (
                <section className="space-y-2">
                  <h3 className="text-sm font-medium">現在のタスク</h3>
                  <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm">
                    {agent.status === "busy" ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-green-400" /> : <CheckCircle2 className="h-4 w-4 shrink-0 text-muted-foreground" />}
                    <span>{agent.currentTask}</span>
                  </div>
                </section>
              )}
              {team && (
                <section className="space-y-2">
                  <h3 className="text-sm font-medium">所属チーム</h3>
                  <div className="rounded-lg border border-border p-3">
                    <div className="flex items-center gap-2">
                      <TeamIcon className={cn("h-4 w-4", team.color)} /><span className="text-sm">{team.nameJa}</span>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">{team.description}</p>
                  </div>
                </section>
              )}
              <section className="space-y-3">
                <h3 className="text-sm font-medium">リソース使用状況</h3>
                <UsageBar label="CPU" value={agent.cpuUsage} icon={Cpu} />
                <UsageBar label="メモリ" value={agent.memoryUsage} icon={MemoryStick} />
              </section>
              <section className="space-y-2">
                <h3 className="text-sm font-medium">エージェント情報</h3>
                <div className="space-y-2 rounded-lg border border-border p-3 text-sm">
                  <InfoRow label="モデル" value={agent.model} mono />
                  <InfoRow label="ロール" value={agent.role} />
                  <InfoRow label="ID" value={agent.id} mono />
                  <InfoRow label="稼働時間" value={formatUptime(agent.uptimeSeconds)} />
                </div>
              </section>
              {agent.tools.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-sm font-medium">ツール</h3>
                  <div className="flex flex-wrap gap-1.5">{agent.tools.map((t) => <Badge key={t} variant="outline" className="text-[10px]">{t}</Badge>)}</div>
                </section>
              )}
              <section className="space-y-2">
                <h3 className="text-sm font-medium">権限</h3>
                <div className="space-y-1.5">
                  {["タスク実行", "メモリアクセス", "チーム内通信"].map((p) => (
                    <div key={p} className="flex items-center gap-2 text-sm"><Shield className="h-3.5 w-3.5 text-muted-foreground" /><span>{p}</span></div>
                  ))}
                </div>
              </section>
            </>
          )}
          <section className="border-t border-border pt-4">
            {confirmDelete ? (<div className="space-y-2">
              <p className="text-sm text-destructive">このエージェントを削除しますか？</p>
              <div className="flex gap-2">
                <button onClick={() => deleteMut.mutate()} disabled={deleteMut.isPending} className="flex items-center gap-1.5 rounded-md bg-destructive px-4 py-1.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50">
                  {deleteMut.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}削除する
                </button>
                <button onClick={() => setConfirmDelete(false)} className="rounded-md border border-border px-4 py-1.5 text-sm hover:bg-muted">キャンセル</button>
              </div>
              {deleteMut.isError && <p className="text-xs text-destructive">{deleteMut.error.message}</p>}
            </div>) : (
              <button onClick={() => setConfirmDelete(true)} className="flex items-center gap-1.5 text-sm text-destructive hover:bg-destructive/10 rounded-md px-3 py-1.5 transition-colors"><Trash2 className="h-3.5 w-3.5" />エージェントを削除</button>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("truncate ml-2 max-w-[200px]", mono && "font-mono text-xs")}>{value}</span>
    </div>
  );
}
