import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, GitPullRequest, GitMerge, GitPullRequestDraft,
  Check, X, Clock, FileDiff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { fetchPullRequest } from "@/api/github";
import { cn } from "@/lib/utils";

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function PullRequestDetail() {
  const { prNumber } = useParams<{ prNumber: string }>();
  const { currentProject } = useTenantProject();
  const navigate = useNavigate();
  const num = Number(prNumber);

  const { data: pr, isLoading } = useQuery({
    queryKey: ["pullRequest", currentProject?.id, num],
    queryFn: () => fetchPullRequest(currentProject?.id ?? "", num),
    enabled: !!currentProject && !isNaN(num),
  });

  if (isLoading) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">Loading...</div>;
  }

  if (!pr) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">Pull request not found</div>;
  }

  const statusBadge = pr.state === "merged" ? (
    <Badge className="gap-1 bg-purple-500/20 text-purple-400 border-transparent">
      <GitMerge className="h-3 w-3" /> Merged
    </Badge>
  ) : pr.draft ? (
    <Badge variant="secondary" className="gap-1">
      <GitPullRequestDraft className="h-3 w-3" /> Draft
    </Badge>
  ) : pr.state === "closed" ? (
    <Badge variant="destructive" className="gap-1">
      <GitPullRequest className="h-3 w-3" /> Closed
    </Badge>
  ) : (
    <Badge variant="success" className="gap-1">
      <GitPullRequest className="h-3 w-3" /> Open
    </Badge>
  );

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* Header */}
      <div className="border-b border-border px-6 py-4">
        <button
          onClick={() => navigate(-1)}
          className="mb-3 flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to pull requests
        </button>
        <div className="flex items-start gap-3">
          {statusBadge}
          <div>
            <h1 className="text-xl font-bold text-foreground">
              {pr.title} <span className="font-normal text-muted-foreground">#{pr.number}</span>
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {pr.author.login} wants to merge{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">{pr.head.ref}</code>
              {" "}into{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">{pr.base.ref}</code>
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1">
        {/* Main */}
        <div className="flex-1 p-6">
          {/* Stats bar */}
          <div className="mb-6 flex items-center gap-6 rounded-lg border border-border bg-accent/30 px-4 py-3">
            <div className="flex items-center gap-2">
              {pr.checks_status === "success" ? <Check className="h-4 w-4 text-success" />
                : pr.checks_status === "failure" ? <X className="h-4 w-4 text-destructive" />
                : <Clock className="h-4 w-4 text-warning" />}
              <span className="text-sm text-foreground capitalize">{pr.checks_status}</span>
            </div>
            <div className="flex items-center gap-1.5 text-sm">
              <FileDiff className="h-4 w-4 text-muted-foreground" />
              <span className="text-foreground">{pr.changed_files} files</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-success">+{pr.additions}</span>
              <span className="text-destructive">-{pr.deletions}</span>
            </div>
          </div>

          {/* PR body */}
          <div className="rounded-lg border border-border">
            <div className="flex items-center gap-2 border-b border-border bg-accent/30 px-4 py-2">
              <Avatar login={pr.author.login} size="sm" />
              <span className="text-sm font-medium text-foreground">{pr.author.login}</span>
              <span className="text-xs text-muted-foreground">{formatDate(pr.created_at)}</span>
            </div>
            <div className="p-4 text-sm text-foreground whitespace-pre-wrap leading-relaxed">
              {pr.body}
            </div>
          </div>

          {/* Merge area */}
          {pr.state === "open" && !pr.draft && (
            <div className="mt-6 rounded-lg border border-border bg-accent/20 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {pr.checks_status === "success"
                      ? "All checks passed"
                      : pr.checks_status === "pending"
                      ? "Checks are running..."
                      : "Some checks failed"}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {pr.reviewers.length > 0
                      ? `${pr.reviewers.length} reviewer(s) assigned`
                      : "No reviewers assigned"}
                  </p>
                </div>
                <button
                  disabled={pr.checks_status !== "success"}
                  className={cn(
                    "rounded-md px-4 py-2 text-sm font-medium transition-colors",
                    pr.checks_status === "success"
                      ? "bg-success text-white hover:bg-success/90"
                      : "bg-muted text-muted-foreground cursor-not-allowed",
                  )}
                >
                  Merge Pull Request
                </button>
              </div>
            </div>
          )}

          {/* Comment input */}
          <div className="mt-6">
            <textarea
              placeholder="Leave a comment..."
              className="w-full rounded-lg border border-border bg-background p-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
              rows={3}
            />
            <div className="mt-2 flex justify-end">
              <button className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
                Comment
              </button>
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className="hidden w-64 shrink-0 border-l border-border p-4 lg:block">
          <div className="space-y-5">
            <div>
              <h4 className="text-xs font-medium uppercase text-muted-foreground/70">Reviewers</h4>
              <div className="mt-2 space-y-2">
                {pr.reviewers.length > 0 ? (
                  pr.reviewers.map((r) => (
                    <div key={r.login} className="flex items-center gap-2">
                      <Avatar login={r.login} size="sm" />
                      <span className="text-sm text-foreground">{r.login}</span>
                    </div>
                  ))
                ) : (
                  <span className="text-sm text-muted-foreground">None</span>
                )}
              </div>
            </div>
            <div>
              <h4 className="text-xs font-medium uppercase text-muted-foreground/70">Labels</h4>
              <div className="mt-2 flex flex-wrap gap-1">
                {pr.labels.map((label) => (
                  <Badge
                    key={label.name}
                    variant="outline"
                    className={cn("text-[11px] py-0 px-1.5")}
                    style={{ borderColor: `#${label.color}40`, color: `#${label.color}` }}
                  >
                    {label.name}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <h4 className="text-xs font-medium uppercase text-muted-foreground/70">Branch</h4>
              <div className="mt-2 text-sm">
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">{pr.head.ref}</code>
                <span className="mx-1.5 text-muted-foreground">&rarr;</span>
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">{pr.base.ref}</code>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
