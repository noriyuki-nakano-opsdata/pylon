import { useQuery } from "@tanstack/react-query";
import { Server } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { healthApi, type HealthCheck } from "@/api/health";

export function Providers() {
  const query = useQuery({
    queryKey: queryKeys.providers.health(),
    queryFn: () => healthApi.get(),
    refetchInterval: 10_000,
  });

  if (query.isLoading) return <PageSkeleton />;

  const checks = query.data?.checks ?? [];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Providers</h1>
        <p className="text-sm text-muted-foreground">
          System health: {query.data?.status ?? "unknown"}
        </p>
      </div>

      {checks.length === 0 ? (
        <EmptyState
          icon={Server}
          title="No health checks"
          description="Configure LLM providers in your pylon.yaml to get started."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {checks.map((check: HealthCheck) => (
            <Card key={check.name}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Server className="h-4 w-4 text-muted-foreground" />
                    <span className="font-medium">{check.name}</span>
                  </div>
                  <StatusBadge status={check.status} />
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {check.message}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
