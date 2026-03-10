/* ── GitHub Integration Types ── */

export interface GitHubIssue {
  id: number;
  number: number;
  title: string;
  body: string;
  state: "open" | "closed";
  labels: { name: string; color: string }[];
  assignee: { login: string; avatar_url: string } | null;
  author: { login: string; avatar_url: string };
  comments: number;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface GitHubPullRequest {
  id: number;
  number: number;
  title: string;
  body: string;
  state: "open" | "closed" | "merged";
  draft: boolean;
  labels: { name: string; color: string }[];
  author: { login: string; avatar_url: string };
  reviewers: { login: string; avatar_url: string }[];
  additions: number;
  deletions: number;
  changed_files: number;
  head: { ref: string };
  base: { ref: string };
  comments: number;
  review_comments: number;
  created_at: string;
  updated_at: string;
  merged_at: string | null;
  closed_at: string | null;
  checks_status: "success" | "failure" | "pending" | "neutral";
}

export interface GitHubComment {
  id: number;
  body: string;
  author: { login: string; avatar_url: string };
  created_at: string;
}
