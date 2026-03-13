import { useEffect, useState } from "react";
import { Outlet, useLocation, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { cn } from "@/lib/utils";
import { LifecycleOperatorConsole } from "@/components/lifecycle/LifecycleOperatorConsole";
import { PhaseNav } from "@/components/lifecycle/PhaseNav";
import { LifecycleWorkspaceHeader } from "@/components/lifecycle/LifecycleWorkspaceHeader";
import { useLifecycleWorkspaceController } from "@/lifecycle/useLifecycleWorkspaceController";
import { LifecycleContext } from "./LifecycleContext";
import type { LifecyclePhase } from "@/types/lifecycle";

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
        <div className="h-9 w-80 max-w-full rounded-2xl bg-muted/60" />
        <div className="h-4 w-[32rem] max-w-full rounded-full bg-muted/40" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.95fr]">
        <div className="space-y-4 rounded-3xl border border-border/60 bg-card/60 p-6">
          <div className="h-5 w-40 rounded-full bg-muted/60" />
          <div className="space-y-3">
            <div className="h-12 rounded-2xl bg-muted/40" />
            <div className="h-28 rounded-3xl bg-muted/30" />
            <div className="h-10 w-40 rounded-2xl bg-muted/50" />
          </div>
        </div>
        <div className="space-y-4 rounded-3xl border border-border/60 bg-card/50 p-6">
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

export function LifecycleLayout() {
  const { projectSlug } = useParams();
  const { currentProject } = useTenantProject();
  const projectLabel = currentProject?.name || projectSlug || "";
  return <LifecycleLayoutInner key={projectSlug} projectSlug={projectSlug ?? ""} projectLabel={projectLabel} />;
}

function LifecycleLayoutInner({ projectSlug, projectLabel }: { projectSlug: string; projectLabel: string }) {
  const basePath = `/p/${projectSlug}`;
  const location = useLocation();
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
    projectSlug,
  });
  const {
    artifacts,
    decisionLog,
    delegations,
    phaseRuns,
    phaseStatuses,
    research,
    skillInvocations,
  } = workspace;

  return (
    <LifecycleContext.Provider value={contextValue}>
      <div className="flex h-full">
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
            phaseNavCollapsed={phaseNavCollapsed}
            isMobile={isMobile}
            consoleOpen={consoleOpen}
            saveState={saveState}
            runtimeConnectionState={runtimeStream.connectionState}
            lastSavedAt={lastSavedAt}
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
                    <Outlet />
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
                liveTelemetry={runtimeStream.liveTelemetry}
                phaseSummary={runtimeStream.runtime?.phaseSummary ?? null}
                activePhaseSummary={runtimeStream.runtime?.activePhaseSummary ?? null}
                className="hidden w-[22rem] shrink-0 xl:flex"
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
          <div className="fixed inset-y-0 right-0 z-50 w-[22rem] max-w-[92vw]">
            <LifecycleOperatorConsole
              currentPhase={currentPhase}
              artifacts={artifacts}
              decisions={decisionLog}
              skillInvocations={skillInvocations}
              delegations={delegations}
              phaseRuns={phaseRuns}
              research={research}
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
