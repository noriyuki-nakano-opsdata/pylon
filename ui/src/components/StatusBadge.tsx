import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/contexts/I18nContext";

const STATUS_MAP: Record<
  string,
  {
    label: string;
    variant: "default" | "secondary" | "destructive" | "success" | "warning";
  }
> = {
  // Agent states
  draft: { label: "Draft", variant: "secondary" },
  init: { label: "Init", variant: "secondary" },
  ready: { label: "Ready", variant: "default" },
  running: { label: "Running", variant: "success" },
  paused: { label: "Paused", variant: "warning" },
  completed: { label: "Completed", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
  killed: { label: "Killed", variant: "destructive" },
  // Run statuses
  pending: { label: "Pending", variant: "secondary" },
  waiting_approval: { label: "Awaiting Approval", variant: "warning" },
  cancelled: { label: "Cancelled", variant: "secondary" },
  // Provider health
  healthy: { label: "Healthy", variant: "success" },
  degraded: { label: "Degraded", variant: "warning" },
  down: { label: "Down", variant: "destructive" },
  // Circuit breaker
  closed: { label: "Closed", variant: "success" },
  open: { label: "Open", variant: "destructive" },
  half_open: { label: "Half Open", variant: "warning" },
  // Approval
  approved: { label: "Approved", variant: "success" },
  rejected: { label: "Rejected", variant: "destructive" },
  expired: { label: "Expired", variant: "secondary" },
};

interface StatusBadgeProps {
  status: string;
  showDot?: boolean;
  className?: string;
}

export function StatusBadge({
  status,
  showDot = true,
  className,
}: StatusBadgeProps) {
  const { t } = useI18n();
  const config = STATUS_MAP[status] ?? {
    label: t(`status.${status}`),
    variant: "secondary" as const,
  };
  const isActive = status === "running";

  return (
    <Badge variant={config.variant} className={className}>
      {showDot && (
        <span className="relative mr-1.5 flex h-2 w-2">
          {isActive && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75" />
          )}
          <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
        </span>
      )}
      {t(`status.${status}`) === `status.${status}` ? config.label : t(`status.${status}`)}
    </Badge>
  );
}
