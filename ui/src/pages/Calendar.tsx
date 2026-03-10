import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Calendar as CalendarIcon,
  ChevronLeft,
  ChevronRight,
  Plus,
  Clock,
  Bot,
  X,
  Repeat,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import {
  listEvents,
  createEvent,
  type ScheduledEvent,
} from "@/api/mission-control";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EventType = "cron" | "task" | "review" | "deploy";

interface CalendarEvent {
  id: string;
  title: string;
  date: string; // YYYY-MM-DD
  time: string; // HH:mm
  type: EventType;
  agent: string;
  recurrence: "once" | "daily" | "weekly";
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EVENT_TYPE_CONFIG: Record<EventType, { label: string; color: string; dotClass: string }> = {
  cron: { label: "Cron", color: "bg-blue-500", dotClass: "bg-blue-500" },
  task: { label: "タスク", color: "bg-green-500", dotClass: "bg-green-500" },
  review: { label: "レビュー", color: "bg-orange-500", dotClass: "bg-orange-500" },
  deploy: { label: "デプロイ", color: "bg-purple-500", dotClass: "bg-purple-500" },
};

const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function toDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number): number {
  return new Date(year, month, 1).getDay();
}

function formatFullDate(dateKey: string): string {
  const d = new Date(dateKey + "T00:00:00");
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 (${WEEKDAYS[d.getDay()]})`;
}

function apiToCalendarEvent(evt: ScheduledEvent): CalendarEvent {
  const startDate = new Date(evt.start);
  return {
    id: evt.id,
    title: evt.title,
    date: toDateKey(startDate),
    time: `${String(startDate.getHours()).padStart(2, "0")}:${String(startDate.getMinutes()).padStart(2, "0")}`,
    type: (evt.type as EventType) || "task",
    agent: evt.agentId || "system",
    recurrence: "once",
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Calendar() {
  const today = useMemo(() => new Date(), []);
  const todayKey = useMemo(() => toDateKey(today), [today]);

  const queryClient = useQueryClient();
  const { data: eventsData, isLoading: loading, error: queryError } = useQuery({
    queryKey: ["events"],
    queryFn: async () => {
      const data = await listEvents();
      return data.map(apiToCalendarEvent);
    },
  });
  const events = useMemo(() => eventsData ?? [], [eventsData]);
  const error = queryError ? (queryError instanceof Error ? queryError.message : "イベントの取得に失敗しました") : null;

  const [currentYear, setCurrentYear] = useState(today.getFullYear());
  const [currentMonth, setCurrentMonth] = useState(today.getMonth());
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  // Events grouped by date key
  const eventsByDate = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const evt of events) {
      const list = map.get(evt.date) ?? [];
      list.push(evt);
      map.set(evt.date, list);
    }
    return map;
  }, [events]);

  // Navigation
  const goToPrevMonth = () => {
    setCurrentMonth((m) => {
      if (m === 0) { setCurrentYear((y) => y - 1); return 11; }
      return m - 1;
    });
    setSelectedDay(null);
  };

  const goToNextMonth = () => {
    setCurrentMonth((m) => {
      if (m === 11) { setCurrentYear((y) => y + 1); return 0; }
      return m + 1;
    });
    setSelectedDay(null);
  };

  const goToToday = () => {
    setCurrentYear(today.getFullYear());
    setCurrentMonth(today.getMonth());
    setSelectedDay(todayKey);
  };

  // Calendar grid
  const calendarDays = useMemo(() => {
    const firstDow = getFirstDayOfWeek(currentYear, currentMonth);
    const daysInMonth = getDaysInMonth(currentYear, currentMonth);
    const cells: (number | null)[] = [];
    for (let i = 0; i < firstDow; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);
    while (cells.length % 7 !== 0) cells.push(null);
    return cells;
  }, [currentYear, currentMonth]);

  // Stats
  const stats = useMemo(() => {
    const todayEvents = eventsByDate.get(todayKey) ?? [];
    return { total: events.length, today: todayEvents.length };
  }, [events, eventsByDate, todayKey]);

  // Selected day events
  const selectedDayEvents = useMemo(() => {
    if (!selectedDay) return [];
    return (eventsByDate.get(selectedDay) ?? []).sort((a, b) => a.time.localeCompare(b.time));
  }, [selectedDay, eventsByDate]);

  // Add event handler
  const createMutation = useMutation({
    mutationFn: (evt: Omit<CalendarEvent, "id">) => {
      const startIso = `${evt.date}T${evt.time}:00Z`;
      return createEvent({
        title: evt.title,
        description: "",
        start: startIso,
        end: "",
        type: evt.type,
        agentId: evt.agent,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["events"] });
      setShowForm(false);
    },
  });

  const handleAddEvent = (evt: Omit<CalendarEvent, "id">) => {
    createMutation.mutate(evt);
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Stats bar */}
      <div className="flex items-center gap-4">
        <StatCard icon={CalendarIcon} label="イベント総数" value={stats.total} />
        <StatCard icon={Clock} label="本日の予定" value={stats.today} />
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={goToPrevMonth}><ChevronLeft className="h-4 w-4" /></Button>
          <h2 className="text-lg font-semibold text-foreground">{currentYear}年{currentMonth + 1}月</h2>
          <Button variant="ghost" size="icon" onClick={goToNextMonth}><ChevronRight className="h-4 w-4" /></Button>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={goToToday}><CalendarIcon className="mr-1.5 h-3.5 w-3.5" />今日</Button>
          <Button size="sm" onClick={() => setShowForm(true)}><Plus className="mr-1.5 h-3.5 w-3.5" />イベント追加</Button>
        </div>
      </div>

      {/* Main area */}
      <div className="flex flex-1 gap-4 overflow-hidden">
        <div className={cn("flex-1 flex flex-col", selectedDay && "max-w-[60%]")}>
          <div className="grid grid-cols-7 gap-px mb-1">
            {WEEKDAYS.map((w, i) => (
              <div key={w} className={cn("text-center text-xs font-medium py-1", i === 0 && "text-red-400", i === 6 && "text-blue-400", i !== 0 && i !== 6 && "text-muted-foreground")}>{w}</div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-px flex-1 auto-rows-fr">
            {calendarDays.map((day, idx) => {
              if (day === null) return <div key={`empty-${idx}`} className="rounded-md bg-card/30" />;
              const dateKey = toDateKey(new Date(currentYear, currentMonth, day));
              const dayEvents = eventsByDate.get(dateKey) ?? [];
              const isToday = dateKey === todayKey;
              const isSelected = dateKey === selectedDay;
              const dow = new Date(currentYear, currentMonth, day).getDay();
              return (
                <button
                  key={dateKey}
                  onClick={() => setSelectedDay(dateKey)}
                  className={cn(
                    "rounded-md border border-transparent p-1.5 text-left transition-colors hover:bg-accent",
                    isSelected && "border-primary bg-accent",
                    !isSelected && "bg-card",
                  )}
                >
                  <span className={cn(
                    "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium",
                    isToday && "bg-primary text-primary-foreground",
                    !isToday && dow === 0 && "text-red-400",
                    !isToday && dow === 6 && "text-blue-400",
                    !isToday && dow !== 0 && dow !== 6 && "text-foreground",
                  )}>
                    {day}
                  </span>
                  <div className="mt-0.5 flex flex-col gap-0.5">
                    {dayEvents.slice(0, 3).map((evt) => (
                      <div key={evt.id} className="flex items-center gap-1 truncate">
                        <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", EVENT_TYPE_CONFIG[evt.type]?.dotClass ?? "bg-gray-500")} />
                        <span className="truncate text-[10px] text-muted-foreground">{evt.title}</span>
                      </div>
                    ))}
                    {dayEvents.length > 3 && (
                      <span className="text-[10px] text-muted-foreground">+{dayEvents.length - 3} more</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {selectedDay && (
          <Card className="w-[40%] shrink-0 flex flex-col overflow-hidden border-border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-foreground">{formatFullDate(selectedDay)}</h3>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setSelectedDay(null)}><X className="h-3.5 w-3.5" /></Button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2">
              {selectedDayEvents.length === 0 && (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                  <CalendarIcon className="h-8 w-8 mb-2 opacity-40" />
                  <span className="text-sm">予定なし</span>
                </div>
              )}
              {selectedDayEvents.map((evt) => {
                const cfg = EVENT_TYPE_CONFIG[evt.type] ?? EVENT_TYPE_CONFIG.task;
                return (
                  <div key={evt.id} className="flex items-start gap-3 rounded-lg border border-border p-3">
                    <div className={cn("mt-0.5 h-2 w-2 shrink-0 rounded-full", cfg.dotClass)} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground truncate">{evt.title}</span>
                        <Badge className={cn("text-[10px] text-white", cfg.color)}>{cfg.label}</Badge>
                      </div>
                      <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                        <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{evt.time}</span>
                        <span className="flex items-center gap-1"><Bot className="h-3 w-3" />{evt.agent}</span>
                        {evt.recurrence !== "once" && (
                          <span className="flex items-center gap-1"><Repeat className="h-3 w-3" />{evt.recurrence === "daily" ? "毎日" : "毎週"}</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <Button size="sm" className="mt-3 w-full" onClick={() => setShowForm(true)}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />イベントを追加
            </Button>
          </Card>
        )}
      </div>

      {showForm && (
        <AddEventModal
          defaultDate={selectedDay ?? todayKey}
          onClose={() => setShowForm(false)}
          onSubmit={handleAddEvent}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({ icon: Icon, label, value }: { icon: typeof CalendarIcon; label: string; value: number }) {
  return (
    <Card className="flex items-center gap-3 border-border bg-card px-4 py-2.5">
      <Icon className="h-4 w-4 text-muted-foreground" />
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-lg font-semibold text-foreground">{value}</p>
      </div>
    </Card>
  );
}

function AddEventModal({
  defaultDate,
  onClose,
  onSubmit,
}: {
  defaultDate: string;
  onClose: () => void;
  onSubmit: (evt: Omit<CalendarEvent, "id">) => void;
}) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(defaultDate);
  const [time, setTime] = useState("09:00");
  const [type, setType] = useState<EventType>("task");
  const [agent, setAgent] = useState("");
  const [recurrence, setRecurrence] = useState<"once" | "daily" | "weekly">("once");

  const handleSubmit = () => {
    if (!title.trim() || !agent.trim()) return;
    onSubmit({ title: title.trim(), date, time, type, agent: agent.trim(), recurrence });
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-[400px] flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h3 className="text-lg font-semibold text-foreground">イベントを追加</h3>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">タイトル</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="イベント名" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">日付</label>
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">時間</label>
              <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">タイプ</label>
            <div className="mt-1 flex gap-2">
              {(Object.keys(EVENT_TYPE_CONFIG) as EventType[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setType(t)}
                  className={cn(
                    "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                    type === t ? cn(EVENT_TYPE_CONFIG[t].color, "text-white") : "bg-muted text-muted-foreground hover:bg-accent",
                  )}
                >
                  {EVENT_TYPE_CONFIG[t].label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">エージェント</label>
            <Input value={agent} onChange={(e) => setAgent(e.target.value)} placeholder="agent名" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">繰り返し</label>
            <div className="mt-1 flex gap-2">
              {([["once", "1回のみ"], ["daily", "毎日"], ["weekly", "毎週"]] as const).map(([val, label]) => (
                <button
                  key={val}
                  onClick={() => setRecurrence(val)}
                  className={cn(
                    "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                    recurrence === val ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-accent",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={onClose}>キャンセル</Button>
            <Button size="sm" onClick={handleSubmit} disabled={!title.trim() || !agent.trim()}>追加</Button>
          </div>
        </div>
      </aside>
    </>
  );
}
