import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useTenantProject } from "@/contexts/TenantProjectContext";

const MAX_NOTE_LENGTH = 1200;
const MAX_SUMMARY_LENGTH = 240;

function slugifyProject(value: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");

  return (normalized || `project-${Date.now().toString(36)}`).slice(0, 48);
}

function summarizeProjectNote(name: string, note: string): string {
  const normalizedName = name.trim();
  const base = note.trim();
  if (!base) {
    return normalizedName
      ? `${normalizedName} の要件と実装範囲を明確化したい。`
      : "新規プロジェクトの要件定義を明確化したい。";
  }

  const chunks = base
    .split(/[。\n]+/)
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk.length > 0)
    .slice(0, 3);

  const merged = `${normalizedName || "このプロジェクト"}: ${chunks.join("。")}`;
  if (merged.length <= MAX_SUMMARY_LENGTH) {
    return merged;
  }

  return `${merged.slice(0, MAX_SUMMARY_LENGTH - 1).trimEnd()}…`;
}

export function ProjectNew() {
  const navigate = useNavigate();
  const { createProject, currentTenant } = useTenantProject();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [projectNote, setProjectNote] = useState("");
  const [summary, setSummary] = useState("");
  const [isSummaryEdited, setIsSummaryEdited] = useState(false);
  const [githubRepo, setGithubRepo] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const normalizedName = name.trim();
  const autoSlug = useMemo(() => slugifyProject(normalizedName), [normalizedName]);
  const autoSummary = useMemo(() => summarizeProjectNote(normalizedName, projectNote), [normalizedName, projectNote]);
  const effectiveSummary = isSummaryEdited ? summary : autoSummary;
  const finalSlug = slug.trim() || autoSlug;
  const canSubmit = !!normalizedName && effectiveSummary.trim().length > 0 && !creating && finalSlug.length > 0;
  const helperText = slugTouched ? "任意で編集可能です。英数字とハイフンを使ってください。" : "名前から自動生成されます。必要なら編集してください。";

  useEffect(() => {
    if (!slugTouched) {
      setSlug(autoSlug);
    }
  }, [autoSlug, slugTouched]);

  useEffect(() => {
    if (!isSummaryEdited) {
      setSummary(autoSummary);
    }
  }, [autoSummary, isSummaryEdited]);

  const handleSubmit = async () => {
    setError("");
    if (!normalizedName) {
      setError("プロジェクト名は必須です");
      return;
    }
    setCreating(true);
    try {
      await createProject({
        name: normalizedName,
        slug: slug.trim() || autoSlug,
        description: effectiveSummary.trim(),
        githubRepo: githubRepo.trim(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "プロジェクト作成に失敗しました");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/dashboard"
            className="rounded-md p-1 hover:bg-accent"
            aria-label="ダッシュボードへ戻る"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">新規プロジェクト</h1>
            <p className="text-sm text-muted-foreground">
              基本情報を入力すると、作成後にプロダクトライフサイクルの研究フェーズへ移動します。
            </p>
          </div>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">プロジェクト情報</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <FieldGroup label="所属テナント" description="現在の組織に紐づけて作成します。">
            <Input value={currentTenant?.name ?? ""} disabled />
          </FieldGroup>

          <FieldGroup label="プロジェクト名" description="画面内表示名として使われます。">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例: todo-app-builder"
              autoComplete="off"
              required
            />
          </FieldGroup>

          <FieldGroup label="スラッグ" description={helperText}>
            <Input
              value={slug}
              onChange={(event) => {
                setSlugTouched(true);
                setSlug(event.target.value);
              }}
              placeholder="project-slug"
            />
          </FieldGroup>

          <FieldGroup
            label="説明（要約前）"
            description="要件・想定ユーザー・対象シナリオを自由に記述できます。"
          >
            <textarea
              value={projectNote}
              onChange={(event) => {
                if (event.target.value.length <= MAX_NOTE_LENGTH) {
                  setProjectNote(event.target.value);
                }
              }}
              rows={4}
              maxLength={MAX_NOTE_LENGTH}
              placeholder="例: タスク整理が苦手なチーム向けに、優先度と進捗を可視化するToDoツールを作りたい。"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <p className="text-xs text-muted-foreground">
              {projectNote.length}/{MAX_NOTE_LENGTH} 文字
            </p>
          </FieldGroup>

          <FieldGroup
            label="要約（研究に渡される内容）"
            description="研究フェーズで扱う内容を短く要約して登録します。"
          >
            <textarea
              value={effectiveSummary}
              onChange={(event) => {
                if (event.target.value.length <= MAX_SUMMARY_LENGTH) {
                  setSummary(event.target.value);
                  setIsSummaryEdited(true);
                }
              }}
              rows={3}
              maxLength={MAX_SUMMARY_LENGTH}
              placeholder="自動生成した要約がここに入ります"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setSummary(autoSummary);
                  setIsSummaryEdited(false);
                }}
              >
                要約を再生成
              </Button>
              <p className="text-xs text-muted-foreground">
                {effectiveSummary.length}/{MAX_SUMMARY_LENGTH} 文字
              </p>
            </div>
          </FieldGroup>

          <FieldGroup label="GitHub リポジトリ" description="任意。後続のデータ連携で利用します。">
            <Input
              value={githubRepo}
              onChange={(event) => setGithubRepo(event.target.value)}
              placeholder="owner/repo 形式で入力（例: octo-org/todo-app）"
            />
          </FieldGroup>

          <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
            作成後の初期URL: <span className="font-mono text-foreground">/p/{finalSlug}/lifecycle/research</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void handleSubmit()} disabled={!canSubmit}>
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "この内容で作成して開始"}
            </Button>
            <Button variant="outline" onClick={() => navigate("/dashboard")}>
              キャンセル
            </Button>
            {error && <p className="w-full text-sm text-destructive">{error}</p>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function FieldGroup({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-sm font-medium text-foreground">{label}</label>
      <p className="text-xs text-muted-foreground">{description}</p>
      {children}
    </div>
  );
}
