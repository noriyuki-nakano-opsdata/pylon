import type { DCSAnalysis } from "../../types/lifecycle";

function MermaidBlock({ title, code }: { title: string; code: string }) {
  if (!code) return null;
  return (
    <div className="space-y-1">
      <h4 className="text-sm font-medium text-gray-700">{title}</h4>
      <pre className="overflow-x-auto rounded-lg bg-gray-50 p-3 text-xs text-gray-700 border border-gray-200">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function EdgeCaseList({ analysis }: { analysis: DCSAnalysis }) {
  const ec = analysis.edgeCases;
  if (!ec || !ec.edgeCases.length) return null;
  const severityColor: Record<string, string> = {
    critical: "text-red-700 bg-red-50",
    high: "text-orange-700 bg-orange-50",
    medium: "text-yellow-700 bg-yellow-50",
    low: "text-gray-600 bg-gray-50",
  };
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-gray-700">
        エッジケース ({ec.edgeCases.length}) — カバレッジ: {(ec.coverageScore * 100).toFixed(0)}%
      </h4>
      <div className="grid gap-2">
        {ec.edgeCases.map((e) => (
          <div key={e.id} className="flex items-start gap-2 rounded border border-gray-200 p-2 text-xs">
            <span className={`shrink-0 rounded px-1.5 py-0.5 font-medium ${severityColor[e.severity] ?? severityColor.low}`}>
              {e.severity}
            </span>
            <div>
              <p className="text-gray-800">{e.scenario}</p>
              {e.mitigation && <p className="text-gray-500 mt-0.5">緩和策: {e.mitigation}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RubberDuckSummary({ analysis }: { analysis: DCSAnalysis }) {
  const prd = analysis.rubberDuckPrd;
  if (!prd) return null;
  return (
    <div className="space-y-2 rounded-xl border border-gray-200 bg-gray-50/70 p-4">
      <h4 className="text-sm font-medium text-gray-800">ラバーダック PRD</h4>
      {prd.problemStatement ? (
        <p className="text-sm text-gray-700">{prd.problemStatement}</p>
      ) : null}
      {prd.targetUsers.length > 0 ? (
        <div className="text-xs text-gray-600">
          <span className="font-medium">対象ユーザー:</span> {prd.targetUsers.join(" / ")}
        </div>
      ) : null}
      {prd.scopeBoundaries.inScope.length > 0 ? (
        <div className="text-xs text-gray-600">
          <span className="font-medium">In scope:</span> {prd.scopeBoundaries.inScope.join("、")}
        </div>
      ) : null}
      {prd.scopeBoundaries.outOfScope.length > 0 ? (
        <div className="text-xs text-gray-500">
          <span className="font-medium">Out of scope:</span> {prd.scopeBoundaries.outOfScope.join("、")}
        </div>
      ) : null}
    </div>
  );
}

function ImpactAnalysisList({ analysis }: { analysis: DCSAnalysis }) {
  const impact = analysis.impactAnalysis;
  if (!impact || impact.layers.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-gray-700">影響範囲分析</h4>
        <p className="text-xs text-gray-500">
          Blast radius: {impact.blastRadius}
          {impact.criticalPathsAffected.length > 0 ? ` / Critical path: ${impact.criticalPathsAffected.join(" → ")}` : ""}
        </p>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {impact.layers.map((layer) => (
          <div key={layer.layer} className="rounded-lg border border-gray-200 bg-white p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-gray-500">{layer.layer}</p>
            <div className="mt-2 space-y-2">
              {layer.impacts.map((entry, index) => (
                <div key={`${layer.layer}-${index}`} className="text-xs text-gray-600">
                  <p className="font-medium text-gray-800">{String(entry.component ?? "component")}</p>
                  <p>{String(entry.description ?? "")}</p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BehaviorModelPanel({ analysis }: { analysis: DCSAnalysis | null }) {
  if (!analysis) return null;
  const seqDiagrams = analysis.sequenceDiagrams?.diagrams ?? [];
  const stateMermaid = analysis.stateTransitions?.mermaidCode ?? "";
  const hasContent = seqDiagrams.length > 0
    || stateMermaid
    || analysis.edgeCases?.edgeCases?.length
    || analysis.impactAnalysis?.layers?.length
    || analysis.rubberDuckPrd;
  if (!hasContent) return null;
  return (
    <section className="space-y-4">
      <h3 className="text-base font-semibold text-gray-900">DCS 行動モデル分析</h3>
      <RubberDuckSummary analysis={analysis} />
      <EdgeCaseList analysis={analysis} />
      <ImpactAnalysisList analysis={analysis} />
      {seqDiagrams.map((d) => (
        <MermaidBlock key={d.id} title={`${d.title} (${d.flowType})`} code={d.mermaidCode} />
      ))}
      {stateMermaid && <MermaidBlock title="状態遷移図" code={stateMermaid} />}
      {analysis.stateTransitions?.riskStates && analysis.stateTransitions.riskStates.length > 0 && (
        <div className="text-xs text-red-600">
          リスク状態数: {analysis.stateTransitions.riskStates.length}
        </div>
      )}
    </section>
  );
}
