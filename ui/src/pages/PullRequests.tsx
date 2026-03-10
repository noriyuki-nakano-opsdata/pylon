import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  GitPullRequest, GitPullRequestDraft, GitMerge,
  MessageSquare, Search, Check, X, Clock, FileDiff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { fetchPullRequests, type GitHubPullRequest } from "@/api/github";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/time";

function PRIcon({ pr }: { pr: GitHubPullRequest }) {
  if (pr.state === "merged") return <GitMerge className="mt-0.5 h-4 w-4 shrink-0 text-purple-400" />;
  if (pr.draft) return <GitPullRequestDraft className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />;
  if (pr.state === "closed") return <GitPullRequest className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />;
  return <GitPullRequest className="mt-0.5 h-4 w-4 shrink-0 text-success" />;
}

function ChecksIcon({ status }: { status: GitHubPullRequest["checks_status"] }) {
  switch (status) {
    case "success": return <Check className="h-3.5 w-3.5 text-success" />;
    case "failure": return <X className="h-3.5 w-3.5 text-destructive" />;
    case "pending": return <Clock className="h-3.5 w-3.5 text-warning" />;
    default: return null;
  }
}

type PRFilter = "open" | "closed";

export function PullRequests() {
  const { currentProject } = useTenantProject();
  const [filter, setFilter] = useState<PRFilter>("open");
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  const { data: prs = [], isLoading } = useQuery({
    queryKey: ["pullRequests", currentProject?.id, filter],
    queryFn: () => {
      if (filter === "closed") {
        return fetchPullRequests(currentProject?.id ?? "").then((all) =>
          all.filter((pr) => pr.state === "closed" || pr.state === "merged"),
        );
      }
      return fetchPullRequests(currentProject?.id ?? "", "open");
    },
    enabled: !!currentProject,
  });

  const filtered = search
    ? prs.filter((pr) => pr.title.toLowerCase().includes(search.toLowerCase()))
    : prs;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h1 className="text-xl font-bold text-foreground">Pull Requests</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {currentProject?.githubRepo ?? currentProject?.name}
          </p>
        </div>
        <button className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
          New Pull Request
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 border-b border-border px-6 py-3">
        <TabsList>
          <TabsTrigger value="open" active={filter === "open"} onClick={() => setFilter("open")}>
            <GitPullRequest className="mr-1.5 h-3.5 w-3.5" />
            Open
          </TabsTrigger>
          <TabsTrigger value="closed" active={filter === "closed"} onClick={() => setFilter("closed")}>
            <Check className="mr-1.5 h-3.5 w-3.5" />
            Closed
          </TabsTrigger>
        </TabsList>
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search pull requests..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 w-full rounded-md border border-border bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
      </div>

      {/* PR list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">Loading...</div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            No {filter} pull requests found.
          </div>
        ) : (
          <div className="divide-y divide-border">
            {filtered.map((pr) => (
              <PRRow key={pr.id} pr={pr} onClick={() => navigate(`pulls/${pr.number}`)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PRRow({ pr, onClick }: { pr: GitHubPullRequest; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="flex items-start gap-3 px-6 py-3 cursor-pointer hover:bg-accent/50 transition-colors"
    >
      <PRIcon pr={pr} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-foreground hover:text-primary cursor-pointer">
            {pr.title}
          </span>
          {pr.draft && (
            <Badge variant="secondary" className="text-[11px] py-0">Draft</Badge>
          )}
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
        <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
          <span>#{pr.number}</span>
          <span>
            {pr.state === "merged"
              ? `merged ${timeAgo(pr.merged_at!)}`
              : `opened ${timeAgo(pr.created_at)}`}{" "}
            by {pr.author.login}
          </span>
          <span className="flex items-center gap-1">
            <span className="text-success">+{pr.additions}</span>
            <span className="text-destructive">-{pr.deletions}</span>
          </span>
          <span className="flex items-center gap-0.5">
            <FileDiff className="h-3 w-3" />
            {pr.changed_files}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <ChecksIcon status={pr.checks_status} />
        <div className="flex -space-x-1">
          {pr.reviewers.map((r) => (
            <Avatar key={r.login} login={r.login} size="sm" />
          ))}
        </div>
        {(pr.comments + pr.review_comments) > 0 && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <MessageSquare className="h-3.5 w-3.5" />
            {pr.comments + pr.review_comments}
          </span>
        )}
      </div>
    </div>
  );
}
