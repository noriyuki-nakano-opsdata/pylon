// GitHub integration API and mock data
import type { GitHubIssue, GitHubPullRequest, GitHubComment } from "@/types/github";

export type { GitHubIssue, GitHubPullRequest, GitHubComment } from "@/types/github";

// ── Mock Data ──

const MOCK_AUTHORS = {
  alice: { login: "alice", avatar_url: "" },
  bob: { login: "bob", avatar_url: "" },
  claude: { login: "claude-bot", avatar_url: "" },
};

const MOCK_ISSUES: GitHubIssue[] = [
  {
    id: 1, number: 42, title: "Add dark mode toggle to settings page",
    body: "Users have requested a dark mode toggle in the settings panel.\n\n## Requirements\n- Toggle switch in settings\n- Persist preference to localStorage\n- Support system preference detection",
    state: "open",
    labels: [{ name: "enhancement", color: "a2eeef" }, { name: "ui", color: "d4c5f9" }],
    assignee: MOCK_AUTHORS.alice, author: MOCK_AUTHORS.bob, comments: 3,
    created_at: "2026-03-07T10:00:00Z", updated_at: "2026-03-08T15:30:00Z", closed_at: null,
  },
  {
    id: 2, number: 41, title: "Fix authentication redirect loop on expired tokens",
    body: "When a JWT token expires, the app enters a redirect loop between /login and /dashboard.",
    state: "open",
    labels: [{ name: "bug", color: "d73a4a" }, { name: "priority: high", color: "b60205" }],
    assignee: null, author: MOCK_AUTHORS.alice, comments: 5,
    created_at: "2026-03-06T08:00:00Z", updated_at: "2026-03-09T09:00:00Z", closed_at: null,
  },
  {
    id: 3, number: 40, title: "Implement webhook retry with exponential backoff",
    body: "Webhook deliveries should retry with exponential backoff on failure.",
    state: "open",
    labels: [{ name: "enhancement", color: "a2eeef" }, { name: "backend", color: "0e8a16" }],
    assignee: MOCK_AUTHORS.bob, author: MOCK_AUTHORS.alice, comments: 2,
    created_at: "2026-03-05T14:00:00Z", updated_at: "2026-03-07T11:00:00Z", closed_at: null,
  },
  {
    id: 4, number: 39, title: "Add rate limiting to public API endpoints",
    body: "We need rate limiting on all public-facing API endpoints to prevent abuse.",
    state: "closed",
    labels: [{ name: "security", color: "e11d48" }, { name: "backend", color: "0e8a16" }],
    assignee: MOCK_AUTHORS.alice, author: MOCK_AUTHORS.bob, comments: 8,
    created_at: "2026-03-01T09:00:00Z", updated_at: "2026-03-04T16:00:00Z", closed_at: "2026-03-04T16:00:00Z",
  },
  {
    id: 5, number: 38, title: "Migrate database schema to support multi-tenancy",
    body: "Database tables need tenant_id columns and RLS policies.",
    state: "closed",
    labels: [{ name: "database", color: "1d76db" }, { name: "priority: high", color: "b60205" }],
    assignee: MOCK_AUTHORS.bob, author: MOCK_AUTHORS.alice, comments: 12,
    created_at: "2026-02-25T10:00:00Z", updated_at: "2026-03-02T14:00:00Z", closed_at: "2026-03-02T14:00:00Z",
  },
];

const MOCK_PULL_REQUESTS: GitHubPullRequest[] = [
  {
    id: 1, number: 15, title: "feat: add dark mode toggle",
    body: "Implements dark mode toggle as described in #42.\n\n## Changes\n- Added `ThemeToggle` component\n- Updated `SettingsPage` layout\n- Added localStorage persistence",
    state: "open", draft: false,
    labels: [{ name: "enhancement", color: "a2eeef" }],
    author: MOCK_AUTHORS.alice,
    reviewers: [MOCK_AUTHORS.bob],
    additions: 142, deletions: 23, changed_files: 5,
    head: { ref: "feat/dark-mode" }, base: { ref: "main" },
    comments: 2, review_comments: 4,
    created_at: "2026-03-08T14:00:00Z", updated_at: "2026-03-09T10:00:00Z",
    merged_at: null, closed_at: null, checks_status: "success",
  },
  {
    id: 2, number: 14, title: "fix: resolve auth redirect loop",
    body: "Fixes #41. The issue was caused by the auth middleware not clearing the expired token before redirecting.",
    state: "open", draft: false,
    labels: [{ name: "bug", color: "d73a4a" }],
    author: MOCK_AUTHORS.claude,
    reviewers: [MOCK_AUTHORS.alice, MOCK_AUTHORS.bob],
    additions: 45, deletions: 12, changed_files: 3,
    head: { ref: "fix/auth-redirect" }, base: { ref: "main" },
    comments: 1, review_comments: 2,
    created_at: "2026-03-09T08:00:00Z", updated_at: "2026-03-09T11:00:00Z",
    merged_at: null, closed_at: null, checks_status: "pending",
  },
  {
    id: 3, number: 13, title: "feat: webhook retry with backoff",
    body: "Implements exponential backoff for webhook retries. Closes #40.",
    state: "open", draft: true,
    labels: [{ name: "enhancement", color: "a2eeef" }, { name: "wip", color: "fbca04" }],
    author: MOCK_AUTHORS.bob,
    reviewers: [],
    additions: 210, deletions: 5, changed_files: 4,
    head: { ref: "feat/webhook-retry" }, base: { ref: "main" },
    comments: 0, review_comments: 0,
    created_at: "2026-03-07T16:00:00Z", updated_at: "2026-03-08T09:00:00Z",
    merged_at: null, closed_at: null, checks_status: "neutral",
  },
  {
    id: 4, number: 12, title: "feat: add rate limiting middleware",
    body: "Adds token bucket rate limiting to all public API endpoints.",
    state: "merged", draft: false,
    labels: [{ name: "security", color: "e11d48" }],
    author: MOCK_AUTHORS.alice,
    reviewers: [MOCK_AUTHORS.bob],
    additions: 189, deletions: 8, changed_files: 6,
    head: { ref: "feat/rate-limit" }, base: { ref: "main" },
    comments: 3, review_comments: 7,
    created_at: "2026-03-03T10:00:00Z", updated_at: "2026-03-04T15:00:00Z",
    merged_at: "2026-03-04T15:00:00Z", closed_at: "2026-03-04T15:00:00Z", checks_status: "success",
  },
];

const MOCK_COMMENTS: Record<number, GitHubComment[]> = {
  42: [
    { id: 1, body: "This would be great! I prefer dark mode for everything.", author: MOCK_AUTHORS.alice, created_at: "2026-03-07T12:00:00Z" },
    { id: 2, body: "Should we also support auto-detection from OS settings?", author: MOCK_AUTHORS.bob, created_at: "2026-03-07T14:00:00Z" },
    { id: 3, body: "Yes, added to requirements. Will use `prefers-color-scheme` media query.", author: MOCK_AUTHORS.alice, created_at: "2026-03-08T09:00:00Z" },
  ],
  41: [
    { id: 4, body: "I can reproduce this consistently. The middleware checks the token after the redirect.", author: MOCK_AUTHORS.bob, created_at: "2026-03-06T10:00:00Z" },
    { id: 5, body: "Root cause: `checkAuth()` runs before `clearExpiredToken()`. Fix incoming.", author: MOCK_AUTHORS.claude, created_at: "2026-03-09T08:30:00Z" },
  ],
};

// ── API functions (mock) ──

export async function fetchIssues(_projectId: string, state?: "open" | "closed"): Promise<GitHubIssue[]> {
  await new Promise((r) => setTimeout(r, 300));
  if (state) return MOCK_ISSUES.filter((i) => i.state === state);
  return MOCK_ISSUES;
}

export async function fetchIssue(_projectId: string, issueNumber: number): Promise<GitHubIssue | null> {
  await new Promise((r) => setTimeout(r, 200));
  return MOCK_ISSUES.find((i) => i.number === issueNumber) ?? null;
}

export async function fetchIssueComments(_projectId: string, issueNumber: number): Promise<GitHubComment[]> {
  await new Promise((r) => setTimeout(r, 200));
  return MOCK_COMMENTS[issueNumber] ?? [];
}

export async function fetchPullRequests(_projectId: string, state?: "open" | "closed" | "merged"): Promise<GitHubPullRequest[]> {
  await new Promise((r) => setTimeout(r, 300));
  if (state) return MOCK_PULL_REQUESTS.filter((pr) => pr.state === state);
  return MOCK_PULL_REQUESTS;
}

export async function fetchPullRequest(_projectId: string, prNumber: number): Promise<GitHubPullRequest | null> {
  await new Promise((r) => setTimeout(r, 200));
  return MOCK_PULL_REQUESTS.find((pr) => pr.number === prNumber) ?? null;
}
