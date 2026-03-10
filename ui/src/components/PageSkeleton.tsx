import { cn } from "@/lib/utils";

interface PageSkeletonProps {
  lines?: number;
  className?: string;
}

export function PageSkeleton({ lines = 5, className }: PageSkeletonProps) {
  return (
    <div className={cn("space-y-4 p-6", className)}>
      <div className="h-8 w-48 animate-pulse rounded-md bg-muted" />
      <div className="space-y-3">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className="h-4 animate-pulse rounded-md bg-muted"
            style={{ width: `${70 + Math.random() * 30}%` }}
          />
        ))}
      </div>
    </div>
  );
}
