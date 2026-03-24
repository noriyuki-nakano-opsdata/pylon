import type { TechnicalDesignBundle } from "../../types/lifecycle";

function APISpecTable({ endpoints }: { endpoints: TechnicalDesignBundle["apiSpecification"] }) {
  if (!endpoints.length) return null;
  return (
    <div className="space-y-1">
      <h4 className="text-sm font-medium text-gray-700">API エンドポイント ({endpoints.length})</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-200 text-left text-gray-500">
              <th className="pb-1 pr-3 font-medium">Method</th>
              <th className="pb-1 pr-3 font-medium">Path</th>
              <th className="pb-1 font-medium">Description</th>
            </tr>
          </thead>
          <tbody>
            {endpoints.map((ep, i) => (
              <tr key={i} className="border-b border-gray-100">
                <td className="py-1 pr-3 font-mono font-semibold text-blue-700">{ep.method}</td>
                <td className="py-1 pr-3 font-mono text-gray-700">{ep.path}</td>
                <td className="py-1 text-gray-600">{ep.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SchemaTable({ tables }: { tables: TechnicalDesignBundle["databaseSchema"] }) {
  if (!tables.length) return null;
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-gray-700">データベーススキーマ ({tables.length})</h4>
      {tables.map((table) => (
        <details key={table.name} className="text-xs">
          <summary className="cursor-pointer font-mono font-medium text-gray-700">{table.name}</summary>
          <table className="mt-1 w-full ml-4">
            <tbody>
              {table.columns.map((col, i) => (
                <tr key={i} className="border-b border-gray-50">
                  <td className="py-0.5 pr-2 font-mono text-gray-700">{col.name}</td>
                  <td className="py-0.5 pr-2 text-gray-500">{col.type}</td>
                  <td className="py-0.5 text-gray-400">{col.primaryKey ? "PK" : col.nullable ? "nullable" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </div>
  );
}

function InterfaceList({ interfaces }: { interfaces: TechnicalDesignBundle["interfaceDefinitions"] }) {
  if (!interfaces.length) return null;
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-gray-700">TypeScript インターフェース ({interfaces.length})</h4>
      {interfaces.map((iface) => (
        <pre key={iface.name} className="overflow-x-auto rounded bg-gray-50 p-2 text-xs border border-gray-200">
          <code>
            {`interface ${iface.name}${iface.extends.length ? ` extends ${iface.extends.join(", ")}` : ""} {\n`}
            {iface.properties.map((p) => `  ${p.name}${p.optional ? "?" : ""}: ${p.type};\n`).join("")}
            {"}"}
          </code>
        </pre>
      ))}
    </div>
  );
}

export function TechnicalDesignPanel({ bundle }: { bundle: TechnicalDesignBundle | null }) {
  if (!bundle) return null;
  const arch = bundle.architecture;
  const hasContent = arch?.system_overview || bundle.apiSpecification.length || bundle.databaseSchema.length;
  if (!hasContent) return null;
  return (
    <section className="space-y-4">
      <h3 className="text-base font-semibold text-gray-900">技術設計書</h3>
      {arch?.system_overview ? (
        <p className="text-sm text-gray-700">{String(arch.system_overview)}</p>
      ) : null}
      {arch?.architectural_pattern ? (
        <div className="text-xs text-gray-500">
          パターン: <span className="font-medium">{String(arch.architectural_pattern)}</span>
        </div>
      ) : null}
      {bundle.dataflowMermaid && (
        <div className="space-y-1">
          <h4 className="text-sm font-medium text-gray-700">データフロー図</h4>
          <pre className="overflow-x-auto rounded-lg bg-gray-50 p-3 text-xs text-gray-700 border border-gray-200">
            <code>{bundle.dataflowMermaid}</code>
          </pre>
        </div>
      )}
      <APISpecTable endpoints={bundle.apiSpecification} />
      <SchemaTable tables={bundle.databaseSchema} />
      <InterfaceList interfaces={bundle.interfaceDefinitions} />
    </section>
  );
}
