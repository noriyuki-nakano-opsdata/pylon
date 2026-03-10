import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CircleDot, CircleCheck, MessageSquare, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { fetchIssues, type GitHubIssue } from "@/api/github";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/time";

export function Issues() {
  const { currentProject } = useTenantProject();
  const [filter, setFilter] = useState<"open" | "closed">("open");
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  const { data: issues = [], isLoading } = useQuery({
    queryKey: ["issues", currentProject?.id, filter],
    queryFn: () => fetchIssues(currentProject?.id ?? "", filter),
    enabled: !!currentProject,
  });

  const filtered = search
    ? issues.filter((i) => i.title.toLowerCase().includes(search.toLowerCase()))
    : issues;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h1 className="text-xl font-bold text-foreground">Issues</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {currentProject?.githubRepo ?? currentProject?.name}
          </p>
        </div>
        <button className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
          イシュー作成
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 border-b border-border px-6 py-3">
        <TabsList>
          <TabsTrigger value="open" active={filter === "open"} onClick={() => setFilter("open")}>
            <CircleDot className="mr-1.5 h-3.5 w-3.5" />
            Open
          </TabsTrigger>
          <TabsTrigger value="closed" active={filter === "closed"} onClick={() => setFilter("closed")}>
            <CircleCheck className="mr-1.5 h-3.5 w-3.5" />
            Closed
          </TabsTrigger>
        </TabsList>
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search issues..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 w-full rounded-md border border-border bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
      </div>

      {/* Issue list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">Loading...</div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            No {filter} issues found.
          </div>
        ) : (
          <div className="divide-y divide-border">
            {filtered.map((issue) => (
              <IssueRow key={issue.id} issue={issue} onClick={() => navigate(`issues/${issue.number}`)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function IssueRow({ issue, onClick }: { issue: GitHubIssue; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="flex items-start gap-3 px-6 py-3 cursor-pointer hover:bg-accent/50 transition-colors"
    >
      {issue.state === "open" ? (
        <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-success" />
      ) : (
        <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-purple-400" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-foreground hover:text-primary cursor-pointer">
            {issue.title}
          </span>
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
        <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
          <span>#{issue.number}</span>
          <span>opened {timeAgo(issue.created_at)} by {issue.author.login}</span>
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        {issue.assignee && (
          <Avatar login={issue.assignee.login} size="sm" />
        )}
        {issue.comments > 0 && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <MessageSquare className="h-3.5 w-3.5" />
            {issue.comments}
          </span>
        )}
      </div>
    </div>
  );
}
