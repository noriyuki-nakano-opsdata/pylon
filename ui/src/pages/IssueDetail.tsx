import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CircleDot, CircleCheck, MessageSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { fetchIssue, fetchIssueComments } from "@/api/github";
import { cn } from "@/lib/utils";

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function IssueDetail() {
  const { issueNumber } = useParams<{ issueNumber: string }>();
  const { currentProject } = useTenantProject();
  const navigate = useNavigate();
  const num = Number(issueNumber);

  const { data: issue, isLoading } = useQuery({
    queryKey: ["issue", currentProject?.id, num],
    queryFn: () => fetchIssue(currentProject?.id ?? "", num),
    enabled: !!currentProject && !isNaN(num),
  });

  const { data: comments = [] } = useQuery({
    queryKey: ["issueComments", currentProject?.id, num],
    queryFn: () => fetchIssueComments(currentProject?.id ?? "", num),
    enabled: !!currentProject && !isNaN(num),
  });

  if (isLoading) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">Loading...</div>;
  }

  if (!issue) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">Issue not found</div>;
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* Header */}
      <div className="border-b border-border px-6 py-4">
        <button
          onClick={() => navigate(-1)}
          className="mb-3 flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to issues
        </button>
        <div className="flex items-start gap-3">
          {issue.state === "open" ? (
            <Badge variant="success" className="mt-1 gap-1">
              <CircleDot className="h-3 w-3" /> Open
            </Badge>
          ) : (
            <Badge className="mt-1 gap-1 bg-purple-500/20 text-purple-400 border-transparent">
              <CircleCheck className="h-3 w-3" /> Closed
            </Badge>
          )}
          <div>
            <h1 className="text-xl font-bold text-foreground">
              {issue.title} <span className="font-normal text-muted-foreground">#{issue.number}</span>
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {issue.author.login} opened on {formatDate(issue.created_at)}
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1">
        {/* Main */}
        <div className="flex-1 p-6">
          {/* Issue body */}
          <div className="rounded-lg border border-border">
            <div className="flex items-center gap-2 border-b border-border bg-accent/30 px-4 py-2">
              <Avatar login={issue.author.login} size="sm" />
              <span className="text-sm font-medium text-foreground">{issue.author.login}</span>
              <span className="text-xs text-muted-foreground">{formatDate(issue.created_at)}</span>
            </div>
            <div className="p-4 text-sm text-foreground whitespace-pre-wrap leading-relaxed">
              {issue.body}
            </div>
          </div>

          {/* Comments */}
          {comments.length > 0 && (
            <div className="mt-6 space-y-4">
              <h3 className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                <MessageSquare className="h-4 w-4" />
                {comments.length} comment{comments.length !== 1 ? "s" : ""}
              </h3>
              {comments.map((comment) => (
                <div key={comment.id} className="rounded-lg border border-border">
                  <div className="flex items-center gap-2 border-b border-border bg-accent/30 px-4 py-2">
                    <Avatar login={comment.author.login} size="sm" />
                    <span className="text-sm font-medium text-foreground">{comment.author.login}</span>
                    <span className="text-xs text-muted-foreground">{formatDate(comment.created_at)}</span>
                  </div>
                  <div className="p-4 text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                    {comment.body}
                  </div>
                </div>
              ))}
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
              <h4 className="text-xs font-medium uppercase text-muted-foreground/70">Assignees</h4>
              <div className="mt-2">
                {issue.assignee ? (
                  <div className="flex items-center gap-2">
                    <Avatar login={issue.assignee.login} size="sm" />
                    <span className="text-sm text-foreground">{issue.assignee.login}</span>
                  </div>
                ) : (
                  <span className="text-sm text-muted-foreground">None</span>
                )}
              </div>
            </div>
            <div>
              <h4 className="text-xs font-medium uppercase text-muted-foreground/70">Labels</h4>
              <div className="mt-2 flex flex-wrap gap-1">
                {issue.labels.map((label) => (
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
          </div>
        </div>
      </div>
    </div>
  );
}
