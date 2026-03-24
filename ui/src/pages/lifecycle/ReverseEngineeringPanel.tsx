import type { ReverseEngineeringResult } from "../../types/lifecycle";

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500">{label}</p>
      <p className="mt-2 text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}

export function ReverseEngineeringPanel({ result }: { result: ReverseEngineeringResult | null }) {
  if (!result) return null;
  const hasContent = result.coverageScore > 0
    || result.apiEndpoints.length > 0
    || result.interfaces.length > 0
    || result.databaseSchema.length > 0
    || result.extractedRequirements.length > 0;
  if (!hasContent) return null;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-gray-900">既存コードの逆分析</h3>
        <p className="text-xs text-gray-500">
          カバレッジ {(result.coverageScore * 100).toFixed(0)}%
          {result.sourceType ? ` / source: ${result.sourceType}` : ""}
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <SummaryCard label="Requirements" value={String(result.extractedRequirements.length)} />
        <SummaryCard label="API" value={String(result.apiEndpoints.length)} />
        <SummaryCard label="Schema" value={String(result.databaseSchema.length)} />
        <SummaryCard label="Interfaces" value={String(result.interfaces.length)} />
      </div>

      {result.languagesDetected.length > 0 ? (
        <div className="flex flex-wrap gap-2 text-xs text-gray-600">
          {result.languagesDetected.map((language) => (
            <span key={language} className="rounded-full bg-gray-100 px-2 py-1">
              {language}
            </span>
          ))}
        </div>
      ) : null}

      {result.extractedRequirements.length > 0 ? (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-gray-700">抽出された要件</h4>
          <div className="grid gap-2">
            {result.extractedRequirements.slice(0, 5).map((item, index) => (
              <div key={`${String(item.id ?? index)}`} className="rounded-lg border border-gray-200 p-3 text-sm text-gray-700">
                <p className="font-medium text-gray-900">{String(item.statement ?? item.id ?? `REQ-${index + 1}`)}</p>
                {"sourceFile" in item && item.sourceFile ? (
                  <p className="mt-1 text-xs text-gray-500">{String(item.sourceFile)}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {result.apiEndpoints.length > 0 ? (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-gray-700">発見した API</h4>
          <div className="grid gap-2">
            {result.apiEndpoints.slice(0, 6).map((endpoint) => (
              <div key={`${endpoint.method}:${endpoint.path}`} className="rounded-lg border border-gray-200 p-3 text-xs text-gray-600">
                <p className="font-mono font-semibold text-blue-700">{endpoint.method} {endpoint.path}</p>
                {endpoint.filePath ? <p className="mt-1">{endpoint.filePath}</p> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {result.dataflowMermaid ? (
        <div className="space-y-1">
          <h4 className="text-sm font-medium text-gray-700">抽出データフロー</h4>
          <pre className="overflow-x-auto rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
            <code>{result.dataflowMermaid}</code>
          </pre>
        </div>
      ) : null}
    </section>
  );
}
