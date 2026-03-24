export const queryKeys = {
  features: ["features"] as const,
  health: ["health"] as const,
  agents: {
    list: () => ["agents"] as const,
    detail: (id: string) => ["agents", id] as const,
  },
  workflows: {
    list: () => ["workflows"] as const,
    detail: (id: string) => ["workflows", id] as const,
    plan: (id: string) => ["workflows", id, "plan"] as const,
  },
  runs: {
    list: () => ["runs"] as const,
    detail: (id: string) => ["runs", id] as const,
    forWorkflow: (wfId: string) => ["runs", "workflow", wfId] as const,
  },
  approvals: {
    list: (filter?: string) => ["approvals", filter ?? "all"] as const,
    detail: (id: string) => ["approvals", id] as const,
  },
  experiments: {
    list: (projectSlug?: string) => ["experiments", projectSlug ?? "all"] as const,
    detail: (id: string) => ["experiments", id] as const,
    iterations: (id: string) => ["experiments", id, "iterations"] as const,
  },
  costs: {
    summary: (period: string) => ["costs", "summary", period] as const,
    breakdown: (period: string) => ["costs", "breakdown", period] as const,
  },
  providers: {
    list: () => ["providers"] as const,
    health: () => ["providers", "health"] as const,
    readiness: () => ["providers", "readiness"] as const,
  },
  models: {
    all: ["models"] as const,
    health: ["models", "health"] as const,
  },
  audit: {
    list: () => ["audit"] as const,
  },
  skills: {
    all: ["skills"] as const,
    detail: (id: string) => ["skills", id] as const,
    categories: ["skills", "categories"] as const,
    importSummary: ["skills", "import-summary"] as const,
  },
  ads: {
    reports: () => ["ads", "reports"] as const,
    report: (id: string) => ["ads", "reports", id] as const,
    auditStatus: (runId: string) => ["ads", "audit", runId] as const,
    benchmarks: (platform: string) => ["ads", "benchmarks", platform] as const,
    templates: () => ["ads", "templates"] as const,
  },
};
