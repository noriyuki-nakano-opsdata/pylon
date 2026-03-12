import { type ReactNode, useId, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  FolderPlus,
  GitBranch,
  Lightbulb,
  Loader2,
  Route,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { createUniqueProjectSlug } from "@/lib/projectSlug";
import { useTenantProject } from "@/contexts/TenantProjectContext";

const MAX_BRIEF_LENGTH = 1200;

const FLOW_STEPS = [
  {
    title: "Research kickoff",
    description: "市場・競合・仮説を整理するための brief を research 画面で 1 回だけ入力します。",
    icon: Sparkles,
  },
  {
    title: "Planning synthesis",
    description: "User journey / user stories / job stories / JTBD / KANO を planning で自動整理します。",
    icon: Route,
  },
  {
    title: "Design to delivery",
    description: "比較用デザイン案、承認、開発、deploy gate まで同じコンテキストで進めます。",
    icon: GitBranch,
  },
] as const;

export function ProjectNew() {
  const navigate = useNavigate();
  const { createProject, currentTenant, projects } = useTenantProject();
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const normalizedName = name.trim();
  const canSubmit = !!normalizedName && !creating;
  const slugPreview = useMemo(() => {
    if (!normalizedName) return "";
    return createUniqueProjectSlug(normalizedName, projects.map((project) => project.slug));
  }, [normalizedName, projects]);

  const nameFieldId = useId();
  const briefFieldId = useId();
  const githubFieldId = useId();

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
        brief: brief.trim(),
        githubRepo: githubRepo.trim(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "プロジェクト作成に失敗しました");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6 p-6 pb-24">
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
              ここでは名前だけで作成できます。詳細な brief は research kickoff で入力します。
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="border-border/80">
          <CardHeader className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle className="text-base">1分で開始</CardTitle>
              <span className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground">
                作成先: {currentTenant?.name ?? "No tenant"}
              </span>
            </div>
            <div className="rounded-xl border border-primary/15 bg-primary/5 p-4">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary">
                  <FolderPlus className="h-4 w-4" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-medium text-foreground">最初に必要なのはプロジェクト名だけです。</p>
                  <p className="text-sm text-muted-foreground">
                    後戻りしにくい要件定義は research kickoff に集約し、この画面では初速を落としません。
                  </p>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <FieldGroup
              label="プロジェクト名"
              description="チームが呼ぶ名前をそのまま入力してください。URL もこの名前から自動生成します。"
              id={nameFieldId}
            >
              <Input
                id={nameFieldId}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="例: todo-app-builder"
                autoComplete="off"
                required
                autoFocus
              />
              {slugPreview && (
                <p className="text-xs text-muted-foreground">
                  URL: <span className="font-mono text-foreground">/p/{slugPreview}/lifecycle/research</span>
                </p>
              )}
            </FieldGroup>

            <div className="rounded-xl border border-border bg-muted/20 p-4">
              <button
                type="button"
                onClick={() => setShowAdvanced((value) => !value)}
                className="flex w-full items-center justify-between gap-3 text-left"
              >
                <div>
                  <p className="text-sm font-medium text-foreground">補足情報を先に入れる</p>
                  <p className="text-xs text-muted-foreground">
                    任意。brief を先に書く場合だけ開いてください。空でもそのまま作成できます。
                  </p>
                </div>
                {showAdvanced ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>

              {showAdvanced && (
                <div className="mt-4 space-y-4">
                  <FieldGroup
                    label="初期 brief"
                    description="research kickoff に引き継ぐ下書きです。後で書き直せます。"
                    id={briefFieldId}
                  >
                    <textarea
                      id={briefFieldId}
                      value={brief}
                      onChange={(event) => {
                        if (event.target.value.length <= MAX_BRIEF_LENGTH) {
                          setBrief(event.target.value);
                        }
                      }}
                      rows={4}
                      maxLength={MAX_BRIEF_LENGTH}
                      placeholder="例: タスク整理が苦手なチーム向けに、優先度と進捗を可視化する ToDo ツールを作りたい。"
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    <p className="text-xs text-muted-foreground">{brief.length}/{MAX_BRIEF_LENGTH} 文字</p>
                  </FieldGroup>

                  <FieldGroup
                    label="GitHub リポジトリ"
                    description="任意。後続の実装・連携で参照します。"
                    id={githubFieldId}
                  >
                    <Input
                      id={githubFieldId}
                      value={githubRepo}
                      onChange={(event) => setGithubRepo(event.target.value)}
                      placeholder="owner/repo 形式で入力（例: octo-org/todo-app）"
                    />
                  </FieldGroup>
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={() => void handleSubmit()} disabled={!canSubmit} className="gap-2">
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderPlus className="h-4 w-4" />}
                プロジェクトを作成して research へ
              </Button>
              <Button variant="outline" onClick={() => navigate("/dashboard")}>
                キャンセル
              </Button>
              {error && <p className="w-full text-sm text-destructive">{error}</p>}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">作成後の流れ</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {FLOW_STEPS.map((step, index) => (
                <div key={step.title} className="flex gap-3 rounded-xl border border-border bg-background p-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {index + 1}
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <step.icon className="h-4 w-4 text-muted-foreground" />
                      <p className="text-sm font-medium text-foreground">{step.title}</p>
                    </div>
                    <p className="text-xs leading-5 text-muted-foreground">{step.description}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Planning で整理される観点</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              {[
                "User journey",
                "User stories",
                "Job stories / JTBD",
                "KANO analysis",
              ].map((item) => (
                <div key={item} className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
                  <Lightbulb className="h-3.5 w-3.5 text-primary" />
                  <span>{item}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function FieldGroup({
  label,
  description,
  children,
  id,
}: {
  label: string;
  description: string;
  children: ReactNode;
  id?: string;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-foreground">{label}</label>
      <p className="text-xs text-muted-foreground">{description}</p>
      {children}
    </div>
  );
}
