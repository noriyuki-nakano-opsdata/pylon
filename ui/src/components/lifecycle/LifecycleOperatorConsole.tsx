import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  LifecycleArtifact,
  LifecycleDecision,
  LifecycleDelegation,
  LifecyclePhase,
  LifecyclePhaseRun,
  LifecycleSkillInvocation,
} from "@/types/lifecycle";

interface OperatorConsoleProps {
  currentPhase: LifecyclePhase | null;
  artifacts: LifecycleArtifact[];
  decisions: LifecycleDecision[];
  skillInvocations: LifecycleSkillInvocation[];
  delegations: LifecycleDelegation[];
  phaseRuns: LifecyclePhaseRun[];
  className?: string;
}

export function LifecycleOperatorConsole({
  currentPhase,
  artifacts: allArtifacts,
  decisions: allDecisions,
  skillInvocations: allSkills,
  delegations: allDelegations,
  phaseRuns,
  className,
}: OperatorConsoleProps) {
  const phase = currentPhase ?? "research";
  const artifacts = allArtifacts.filter((item) => item.phase === phase).slice(0, 5);
  const decisions = allDecisions.filter((item) => item.phase === phase).slice(0, 5);
  const skills = allSkills.filter((item) => item.phase === phase).slice(0, 6);
  const delegations = allDelegations.filter((item) => item.phase === phase).slice(0, 4);
  const phaseRun = phaseRuns.find((item) => item.phase === phase);
  const hasTelemetry =
    phaseRun != null ||
    artifacts.length > 0 ||
    decisions.length > 0 ||
    skills.length > 0 ||
    delegations.length > 0;

  return (
    <aside className={cn("flex flex-col border-l border-border bg-card/40", className)}>
      <div className="border-b border-border px-4 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">Operator Console</p>
        <h2 className="mt-1 text-sm font-bold text-foreground">{phase} phase</h2>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <ConsoleSection title="Phase Run">
          {phaseRun ? (
            <div className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-foreground">{phaseRun.runId.slice(0, 8)}</span>
                <Badge variant="outline" className="text-[10px] capitalize">{phaseRun.status}</Badge>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                <span>Artifacts: {phaseRun.artifactCount}</span>
                <span>Decisions: {phaseRun.decisionCount}</span>
                <span>Cost: ${phaseRun.costUsd.toFixed(3)}</span>
                <span>{phaseRun.completedAt ? new Date(phaseRun.completedAt).toLocaleTimeString("ja-JP") : "running"}</span>
              </div>
            </div>
          ) : (
            <EmptyLine text="まだ実行履歴はありません。" />
          )}
        </ConsoleSection>

        {!hasTelemetry && (
          <EmptyLine text="このフェーズの operator telemetry はまだありません。ワークフロー実行後に artifact、decision、delegation がここに集約されます。" />
        )}

        {artifacts.length > 0 && (
          <ConsoleSection title="Artifacts">
            {artifacts.map((artifact) => (
            <div key={artifact.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{artifact.title}</span>
                <Badge variant="outline" className="text-[10px]">{artifact.kind}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{artifact.summary}</p>
              {artifact.skillIds.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {artifact.skillIds.slice(0, 3).map((skillId) => (
                    <Badge key={skillId} variant="secondary" className="text-[10px]">{skillId}</Badge>
                  ))}
                </div>
              )}
            </div>
            ))}
          </ConsoleSection>
        )}

        {decisions.length > 0 && (
          <ConsoleSection title="Decisions">
            {decisions.map((decision) => (
            <div key={decision.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{decision.title}</span>
                <Badge variant="outline" className="text-[10px]">{decision.kind}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{decision.rationale}</p>
            </div>
            ))}
          </ConsoleSection>
        )}

        {skills.length > 0 && (
          <ConsoleSection title="Skill Planner">
            {skills.map((skill) => (
            <div key={skill.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{skill.skill}</span>
                <Badge variant="outline" className="text-[10px]">{skill.mode}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{skill.agentLabel}</p>
              {skill.delegatedTo && <p className="mt-1 text-primary">delegated to {skill.delegatedTo}</p>}
            </div>
            ))}
          </ConsoleSection>
        )}

        {delegations.length > 0 && (
          <ConsoleSection title="A2A Delegations">
            {delegations.map((delegation) => (
            <div key={delegation.id} className="rounded-lg border border-border bg-card p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-foreground">{delegation.peer}</span>
                <Badge variant="outline" className="text-[10px]">{delegation.skill}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">{delegation.agentId} {"->"} {delegation.peer}</p>
              <p className="mt-1 text-muted-foreground">task: {String(delegation.task.id ?? "").slice(0, 8)}</p>
            </div>
            ))}
          </ConsoleSection>
        )}
      </div>
    </aside>
  );
}

function ConsoleSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-border px-3 py-3 text-xs text-muted-foreground">{text}</div>;
}
