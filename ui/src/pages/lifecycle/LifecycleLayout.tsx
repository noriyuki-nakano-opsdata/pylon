import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Loader2, LockKeyhole, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { cn } from "@/lib/utils";
import { LifecycleOperatorConsole } from "@/components/lifecycle/LifecycleOperatorConsole";
import { PhaseNav } from "@/components/lifecycle/PhaseNav";
import { findLatestReachablePhase } from "@/lifecycle/phaseStatus";
import { formatPhaseLabel, presentLifecycleGateReason } from "@/lifecycle/presentation";
import { LifecycleWorkspaceHeader } from "@/components/lifecycle/LifecycleWorkspaceHeader";
import { useLifecycleWorkspaceController } from "@/lifecycle/useLifecycleWorkspaceController";
import { LifecycleContext } from "./LifecycleContext";
import type { LifecycleNextAction, LifecyclePhase, LifecycleProject, PhaseStatus } from "@/types/lifecycle";

const PHASE_ORDER: LifecyclePhase[] = [
  "research",
  "planning",
  "design",
  "approval",
  "development",
  "deploy",
  "iterate",
];

function LifecycleContentSkeleton() {
  return (
    <div className="space-y-6 px-6 py-8">
      <div className="space-y-3">
        <div className="h-3 w-28 rounded-full bg-muted/70" />
        <div className="h-9 w-80 max-w-full rounded-2xl bg-card/80" />
        <div className="h-4 w-[32rem] max-w-full rounded-full bg-muted/40" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.95fr]">
        <div className="space-y-4 rounded-3xl border border-border/60 bg-card/70 p-6">
          <div className="h-5 w-40 rounded-full bg-muted/60" />
          <div className="space-y-3">
            <div className="h-12 rounded-2xl bg-muted/40" />
            <div className="h-28 rounded-3xl bg-muted/30" />
            <div className="h-10 w-40 rounded-2xl bg-muted/50" />
          </div>
        </div>
        <div className="space-y-4 rounded-3xl border border-border/60 bg-card/60 p-6">
          <div className="h-5 w-36 rounded-full bg-muted/60" />
          <div className="space-y-3">
            <div className="h-20 rounded-2xl bg-muted/35" />
            <div className="h-20 rounded-2xl bg-muted/35" />
            <div className="h-20 rounded-2xl bg-muted/35" />
          </div>
        </div>
      </div>
    </div>
  );
}

function LockedPhaseState(props: {
  currentPhase: LifecyclePhase;
  fallbackPhase: LifecyclePhase | null;
  nextAction: LifecycleNextAction | null;
  phaseStatuses: PhaseStatus[];
  onOpenFallback: () => void;
}) {
  const { currentPhase, fallbackPhase, nextAction, phaseStatuses, onOpenFallback } = props;
  const nextSuggestedPhase = nextAction?.phase && nextAction.phase !== currentPhase
    ? phaseStatuses.find((entry) => entry.phase === nextAction.phase)?.status !== "locked"
      ? nextAction.phase
      : null
    : null;
  const recommendedPhase = nextSuggestedPhase ?? fallbackPhase;
  const headline = `${formatPhaseLabel(currentPhase)} はまだ未解放です`;
  const description = recommendedPhase
    ? `${formatPhaseLabel(currentPhase)} に入る前に、${formatPhaseLabel(recommendedPhase)} の判断を先に固める必要があります。`
    : `${formatPhaseLabel(currentPhase)} に入る前に、前の判断を先に固める必要があります。`;
  const supportingReason =
    nextAction?.phase === recommendedPhase
    && typeof nextAction.reason === "string"
    && nextAction.reason.trim().length > 0
      ? presentLifecycleGateReason({
          currentPhase,
          recommendedPhase,
          reason: nextAction.reason,
        })
      : null;
  const requirementLabel = recommendedPhase
    ? `${formatPhaseLabel(recommendedPhase)} を先に進める`
    : "前のフェーズを完了する";
  const completedPhases = phaseStatuses
    .filter((entry) => entry.status === "completed")
    .map((entry) => formatPhaseLabel(entry.phase))
    .slice(0, 4);
  const phasePreview: Record<LifecyclePhase, string> = {
    research: "市場と競合、ユーザー課題、根拠の信頼性を揃えます。",
    planning: "誰に何を届けるかを整理し、初期スコープと停止条件を固めます。",
    design: "比較可能な案を並べ、判断の根拠を保ったまま表現へ落とします。",
    approval: "企画とデザインの判断をレビューし、開発へ渡す基準を確定します。",
    development: "選んだ案を実装へ変換し、品質と運用性を崩さず積み上げます。",
    deploy: "公開前チェックを通し、リリース判断を安全に進めます。",
    iterate: "運用結果を吸い上げ、次の改善ループへつなげます。",
  };
  const phaseRail = phaseStatuses.map((entry) => ({
    ...entry,
    label: formatPhaseLabel(entry.phase),
  }));

  return (
    <div className="px-5 py-5 xl:px-6 xl:py-6">
      <div className="mx-auto flex min-h-[calc(100vh-13rem)] max-w-7xl flex-col overflow-hidden rounded-[2rem] border border-border/80 bg-card/80 shadow-[0_40px_120px_rgba(0,0,0,0.42)] backdrop-blur">
        <div className="border-b border-border/80 bg-background/75 px-5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
            <span className="ml-3 rounded-full border border-border bg-card px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              gate.md
            </span>
            <span className="rounded-full border border-border bg-card px-2.5 py-1 font-mono text-[10px] text-muted-foreground">
              {`lifecycle/${currentPhase}`}
            </span>
            <span className="ml-auto inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <LockKeyhole className="h-3.5 w-3.5 text-primary" />
              phase gate
            </span>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1.2fr)_24rem]">
          <div className="min-h-0 px-5 py-5 xl:px-6 xl:py-6">
            <div className="rounded-[1.6rem] border border-border/70 bg-background/70 p-6">
              <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                editor unavailable
              </div>
              <h2 className="mt-4 text-[2rem] font-semibold tracking-[-0.04em] text-foreground">
                {headline}
              </h2>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-muted-foreground">{description}</p>
              {supportingReason ? (
                <div className="mt-5 rounded-[1.25rem] border border-border bg-card/85 px-4 py-4 text-sm leading-6 text-foreground/90">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">gate rationale</p>
                  <p className="mt-2">{supportingReason}</p>
                </div>
              ) : null}

              <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.9fr)]">
                <div className="space-y-4">
                  <div className="rounded-[1.25rem] border border-border bg-card/80 p-4">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">unlock requirements</p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      <div className="rounded-2xl border border-border/70 bg-background/80 p-3">
                        <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">next phase</p>
                        <p className="mt-2 text-sm font-semibold text-foreground">
                          {recommendedPhase ? formatPhaseLabel(recommendedPhase) : "research"}
                        </p>
                      </div>
                      <div className="rounded-2xl border border-border/70 bg-background/80 p-3">
                        <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">condition</p>
                        <p className="mt-2 text-sm font-semibold text-foreground">{requirementLabel}</p>
                      </div>
                      <div className="rounded-2xl border border-border/70 bg-background/80 p-3">
                        <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">opens</p>
                        <p className="mt-2 text-sm font-semibold text-foreground">{formatPhaseLabel(currentPhase)}</p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-[1.25rem] border border-border bg-card/80 p-4">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">why this screen is blocked</p>
                    <div className="mt-3 space-y-3 text-sm leading-6 text-muted-foreground">
                      <p>
                        ライフサイクルは上流の判断が確定するまで下流の editor surface を解放しません。
                        誤った前提で preview や code を編集し始めるより、必要な判断を確定してから入るほうが早く、事故も減ります。
                      </p>
                      <p>
                        まずは {recommendedPhase ? formatPhaseLabel(recommendedPhase) : "前のフェーズ"} を閉じると、
                        この workbench はそのまま有効化されます。
                      </p>
                    </div>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="rounded-[1.25rem] border border-border bg-card/80 p-4">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">already resolved</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {completedPhases.length > 0 ? completedPhases.map((phase) => (
                          <span
                            key={phase}
                            className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-100"
                          >
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            {phase}
                          </span>
                        )) : (
                          <p className="text-sm text-muted-foreground">まだ開始直後です。最初の判断から順に積み上げます。</p>
                        )}
                      </div>
                    </div>

                    <div className="rounded-[1.25rem] border border-border bg-card/80 p-4">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">what opens here</p>
                      <p className="mt-3 text-sm leading-6 text-foreground/90">
                        {phasePreview[currentPhase]}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="rounded-[1.25rem] border border-border bg-card/80 p-4">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">action</p>
                  <Button onClick={onOpenFallback} className="mt-3 w-full justify-between rounded-2xl">
                    {recommendedPhase ? `${formatPhaseLabel(recommendedPhase)}へ戻る` : "進められるフェーズへ戻る"}
                    <ArrowLeft className="h-4 w-4" />
                  </Button>
                  <div className="mt-4 rounded-2xl border border-border/70 bg-background/80 p-4 text-xs leading-5 text-muted-foreground">
                    URL を直接開いた場合でも、判断の系譜を崩さないため未解放フェーズはここで止めます。
                    必要な判断を 1 つ戻って確定すると、この editor はそのまま開放されます。
                  </div>
                </div>
              </div>
            </div>
          </div>

          <aside className="border-t border-border/80 bg-background/70 xl:border-l xl:border-t-0">
            <div className="border-b border-border/80 px-5 py-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">phase stack</p>
              <p className="mt-2 font-mono text-xs text-foreground/85">pipeline://lifecycle</p>
            </div>
            <div className="space-y-3 px-5 py-5">
              {phaseRail.map((entry) => (
                <div key={entry.phase} className="rounded-[1.1rem] border border-border bg-card/75 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-foreground">{entry.label}</span>
                    <span className={cn(
                      "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]",
                      entry.phase === currentPhase
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : entry.status === "completed"
                          ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-100"
                          : entry.status === "locked"
                            ? "border-border bg-background/80 text-muted-foreground"
                            : "border-border bg-background/80 text-foreground/85",
                    )}>
                      {entry.status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">{phasePreview[entry.phase]}</p>
                </div>
              ))}
              <div className="rounded-[1.1rem] border border-border bg-card/75 px-4 py-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">next unlock</p>
                <p className="mt-2 text-sm font-semibold text-foreground">
                  {recommendedPhase ? formatPhaseLabel(recommendedPhase) : "research"}
                </p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {requirementLabel}
                </p>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

export function LifecycleLayout() {
  const { projectSlug } = useParams();
  const { currentProject } = useTenantProject();
  const projectLabel = currentProject?.name || projectSlug || "";
  return <LifecycleLayoutInner key={projectSlug} projectSlug={projectSlug ?? ""} projectLabel={projectLabel} />;
}

function LifecycleLayoutInner({ projectSlug, projectLabel }: { projectSlug: string; projectLabel: string }) {
  const basePath = `/p/${projectSlug}`;
  const location = useLocation();
  const navigate = useNavigate();
  const initialProject = useMemo(() => {
    const state = location.state as { initialLifecycleProject?: LifecycleProject } | null;
    return state?.initialLifecycleProject ?? null;
  }, [location.state]);
  const [isMobile, setIsMobile] = useState(false);
  const [phaseNavCollapsed, setPhaseNavCollapsed] = useState(false);
  const [mobilePhaseNavOpen, setMobilePhaseNavOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1024px)");
    const onChange = (event: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(event.matches);
      if (event.matches) {
        setPhaseNavCollapsed(false);
        setConsoleOpen(false);
      }
    };
    onChange(mq);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [projectSlug]);

  useEffect(() => {
    if (!isMobile) return;
    setMobilePhaseNavOpen(false);
    setConsoleOpen(false);
  }, [isMobile, location.pathname]);

  const currentPhase = PHASE_ORDER.find((phase) =>
    location.pathname.endsWith(`/lifecycle/${phase}`),
  ) ?? null;
  const {
    contextValue,
    hasHydratedContent,
    hydrateError,
    isHydrating,
    isRefreshingProject,
    lastSavedAt,
    runtimeStream,
    saveState,
    workspace,
  } = useLifecycleWorkspaceController({
    basePath,
    currentPhase,
    initialProject,
    projectSlug,
  });
  const {
    autonomyState,
    artifacts,
    decisionLog,
    delegations,
    governanceMode,
    nextAction,
    phaseRuns,
    phaseStatuses,
    research,
    skillInvocations,
  } = workspace;
  const currentPhaseStatus = currentPhase
    ? phaseStatuses.find((entry) => entry.phase === currentPhase) ?? null
    : null;
  const lockedPhaseFallback = useMemo(
    () => findLatestReachablePhase(phaseStatuses, currentPhase),
    [currentPhase, phaseStatuses],
  );
  const isLockedPhase = Boolean(currentPhase && currentPhaseStatus?.status === "locked");

  return (
    <LifecycleContext.Provider value={contextValue}>
      <div className="lifecycle-ide-shell flex h-full">
        {!isMobile && (
          <PhaseNav
            basePath={basePath}
            phaseStatuses={phaseStatuses}
            collapsed={phaseNavCollapsed}
            className="shrink-0"
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <LifecycleWorkspaceHeader
            currentPhase={currentPhase ?? "research"}
            projectLabel={projectLabel}
            phaseStatuses={phaseStatuses}
            governanceMode={governanceMode}
            pendingHumanDecisions={autonomyState?.requiredHumanDecisions?.length ?? 0}
            phaseNavCollapsed={phaseNavCollapsed}
            isMobile={isMobile}
            consoleOpen={consoleOpen}
            saveState={saveState}
            runtimeConnectionState={runtimeStream.connectionState}
            lastSavedAt={lastSavedAt}
            onSelectGovernanceMode={contextValue.actions.selectGovernanceMode}
            onTogglePhaseNav={() => {
              if (isMobile) setMobilePhaseNavOpen(true);
              else setPhaseNavCollapsed((value) => !value);
            }}
            onToggleConsole={() => setConsoleOpen((value) => !value)}
          />
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <div className="min-w-0 flex-1 overflow-hidden">
              <div className="h-full overflow-y-auto">
                {isHydrating && !hasHydratedContent ? (
                  <LifecycleContentSkeleton />
                ) : hydrateError && !hasHydratedContent ? (
                  <div className="px-6 py-10">
                    <div className="rounded-3xl border border-amber-500/30 bg-amber-500/10 p-6 text-sm text-amber-100">
                      {hydrateError}
                    </div>
                  </div>
                ) : (
                  <>
                    {isRefreshingProject && (
                      <div className="sticky top-0 z-10 border-b border-border/60 bg-background/85 px-6 py-3 backdrop-blur">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          最新の lifecycle state を同期中...
                        </div>
                      </div>
                    )}
                    {isLockedPhase && currentPhase ? (
                      <LockedPhaseState
                        currentPhase={currentPhase}
                        fallbackPhase={lockedPhaseFallback}
                        nextAction={nextAction}
                        phaseStatuses={phaseStatuses}
                        onOpenFallback={() => {
                          const phase = lockedPhaseFallback ?? "research";
                          navigate(`${basePath}/lifecycle/${phase}`);
                        }}
                      />
                    ) : (
                      <Outlet />
                    )}
                  </>
                )}
              </div>
            </div>
            {!isMobile && consoleOpen && (
              <LifecycleOperatorConsole
                currentPhase={currentPhase}
                artifacts={artifacts}
                decisions={decisionLog}
                skillInvocations={skillInvocations}
                delegations={delegations}
                phaseRuns={phaseRuns}
                research={research}
                autonomyState={autonomyState}
                liveTelemetry={runtimeStream.liveTelemetry}
                phaseSummary={runtimeStream.runtime?.phaseSummary ?? null}
                activePhaseSummary={runtimeStream.runtime?.activePhaseSummary ?? null}
                className="hidden w-[19rem] shrink-0 xl:flex"
              />
            )}
          </div>
        </div>
      </div>

      {isMobile && mobilePhaseNavOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60"
            onClick={() => setMobilePhaseNavOpen(false)}
          />
          <div className="fixed inset-y-0 left-0 z-50">
            <PhaseNav
              basePath={basePath}
              phaseStatuses={phaseStatuses}
              className="w-72 max-w-[85vw] shadow-2xl"
              onItemClick={() => setMobilePhaseNavOpen(false)}
            />
          </div>
        </>
      )}

      {isMobile && consoleOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60"
            onClick={() => setConsoleOpen(false)}
          />
          <div className="fixed inset-y-0 right-0 z-50 w-[19rem] max-w-[92vw]">
            <LifecycleOperatorConsole
              currentPhase={currentPhase}
              artifacts={artifacts}
              decisions={decisionLog}
              skillInvocations={skillInvocations}
              delegations={delegations}
              phaseRuns={phaseRuns}
              research={research}
              autonomyState={autonomyState}
              liveTelemetry={runtimeStream.liveTelemetry}
              phaseSummary={runtimeStream.runtime?.phaseSummary ?? null}
              activePhaseSummary={runtimeStream.runtime?.activePhaseSummary ?? null}
              className={cn("h-full w-full shadow-2xl")}
            />
          </div>
        </>
      )}
    </LifecycleContext.Provider>
  );
}
