import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { approvalsApi, type Approval } from "@/api/approvals";
import { cn } from "@/lib/utils";

export function Approvals() {
  const [showPending, setShowPending] = useState(true);
  const queryClient = useQueryClient();
  const isPending = showPending;

  const query = useQuery({
    queryKey: queryKeys.approvals.list(isPending ? "pending" : "all"),
    queryFn: () => approvalsApi.list(),
    refetchInterval: 5_000,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approvalsApi.approve(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => approvalsApi.reject(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  });

  if (query.isLoading) return <PageSkeleton />;

  const allApprovals = query.data ?? [];
  const pendingCount = allApprovals.filter((a) => a.status === "pending").length;
  const filtered = isPending
    ? allApprovals.filter((a) => a.status === "pending")
    : allApprovals;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Approvals</h1>
        <p className="text-sm text-muted-foreground">
          Review and approve agent actions
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <button
          onClick={() => setShowPending(true)}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium transition-colors",
            isPending
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          Pending
          {pendingCount > 0 && (
            <Badge variant="default" className="h-5 min-w-5 px-1.5">
              {pendingCount}
            </Badge>
          )}
        </button>
        <button
          onClick={() => setShowPending(false)}
          className={cn(
            "border-b-2 px-4 py-2 text-sm font-medium transition-colors",
            !isPending
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          All
        </button>
      </div>

      {/* Approval list */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title={isPending ? "No pending approvals" : "No approvals yet"}
          description={
            isPending
              ? "All agent actions have been reviewed."
              : "Approvals will appear when agents request A3+ actions."
          }
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              onApprove={() => approveMutation.mutate(approval.id)}
              onReject={() => rejectMutation.mutate(approval.id)}
              isApproving={approveMutation.isPending}
              isRejecting={rejectMutation.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface ApprovalCardProps {
  approval: Approval;
  onApprove: () => void;
  onReject: () => void;
  isApproving: boolean;
  isRejecting: boolean;
}

function ApprovalCard({
  approval,
  onApprove,
  onReject,
  isApproving,
  isRejecting,
}: ApprovalCardProps) {
  const isPending = approval.status === "pending";

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{approval.agent_id}</span>
              <StatusBadge status={approval.status} />
            </div>
            <p className="text-sm text-muted-foreground">{approval.action}</p>
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span>
                {new Date(approval.created_at).toLocaleString("ja-JP")}
              </span>
              {(() => {
                const runId = approval.context?.workflow_run_id ?? approval.context?.run_id;
                return runId ? (
                  <span className="font-mono">
                    run: {String(runId).slice(0, 8)}
                  </span>
                ) : null;
              })()}
              {approval.plan_hash && (
                <span className="font-mono">
                  plan: {approval.plan_hash.slice(0, 8)}
                </span>
              )}
              {approval.effect_hash && (
                <Badge
                  variant={
                    approval.plan_hash === approval.effect_hash
                      ? "success"
                      : "destructive"
                  }
                  className="text-[10px]"
                >
                  {approval.plan_hash === approval.effect_hash
                    ? "Hash Match"
                    : "Hash Drift"}
                </Badge>
              )}
            </div>
          </div>

          {isPending && (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={onReject}
                disabled={isRejecting}
              >
                <X className="mr-1 h-3 w-3" />
                Reject
              </Button>
              <Button size="sm" onClick={onApprove} disabled={isApproving}>
                <Check className="mr-1 h-3 w-3" />
                Approve
              </Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
