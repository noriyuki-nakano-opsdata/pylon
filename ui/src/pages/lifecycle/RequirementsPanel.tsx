import type { RequirementsBundle, EARSRequirement } from "../../types/lifecycle";

const CONFIDENCE_BADGE: Record<string, { label: string; color: string }> = {
  high: { label: "高信頼度", color: "bg-blue-100 text-blue-800" },
  medium: { label: "中信頼度", color: "bg-yellow-100 text-yellow-800" },
  low: { label: "低信頼度", color: "bg-red-100 text-red-800" },
};

const PATTERN_LABEL: Record<string, string> = {
  ubiquitous: "普遍的要件",
  "event-driven": "イベント駆動",
  unwanted: "例外処理",
  "state-driven": "状態駆動",
  optional: "オプション",
  complex: "複合要件",
};

function confidenceLevel(c: number): string {
  if (c >= 0.8) return "high";
  if (c >= 0.5) return "medium";
  return "low";
}

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const level = confidenceLevel(confidence);
  const badge = CONFIDENCE_BADGE[level];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${badge.color}`}>
      {badge.label} ({(confidence * 100).toFixed(0)}%)
    </span>
  );
}

function RequirementCard({ req }: { req: EARSRequirement }) {
  return (
    <div className="rounded-lg border border-gray-200 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-semibold text-gray-700">{req.id}</span>
        <div className="flex items-center gap-2">
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
            {PATTERN_LABEL[req.pattern] ?? req.pattern}
          </span>
          <ConfidenceBadge confidence={req.confidence} />
        </div>
      </div>
      <p className="text-sm text-gray-800">{req.statement}</p>
      {req.acceptanceCriteria.length > 0 && (
        <div className="text-xs text-gray-500">
          <span className="font-medium">受入基準:</span>{" "}
          {req.acceptanceCriteria.join("; ")}
        </div>
      )}
    </div>
  );
}

export function RequirementsPanel({ bundle }: { bundle: RequirementsBundle | null }) {
  if (!bundle || !bundle.requirements.length) return null;
  const dist = bundle.confidenceDistribution;
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-gray-900">EARS 要件定義</h3>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span>完全性: {(bundle.completenessScore * 100).toFixed(0)}%</span>
          <span>高: {dist.high} / 中: {dist.medium} / 低: {dist.low}</span>
        </div>
      </div>
      <div className="grid gap-3">
        {bundle.requirements.map((req) => (
          <RequirementCard key={req.id} req={req} />
        ))}
      </div>
      {bundle.userStories.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-gray-700">
            ユーザーストーリー ({bundle.userStories.length})
          </summary>
          <ul className="mt-2 space-y-1 pl-4 text-gray-600">
            {bundle.userStories.map((s) => (
              <li key={s.id}>{s.title}: {s.description}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
