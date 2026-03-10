import { useParams, Link } from "react-router-dom";
import {
  Sparkles,
  Search,
  Lightbulb,
  FileText,
  BarChart3,
  Layers,
} from "lucide-react";
import { EXAMPLES } from "./types";

// ─── Icon Mapping ─────────────────────────────────────

const ICON_MAP = {
  Lightbulb,
  Search,
  FileText,
  BarChart3,
} as const;

// ─── Welcome Screen ───────────────────────────────────

export function WelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  const { projectSlug } = useParams<{ projectSlug: string }>();

  return (
    <div className="flex h-full flex-col items-center justify-center px-4">
      <div className="mb-8 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
          <Sparkles className="h-7 w-7 text-primary" />
        </div>
        <h2 className="text-xl font-semibold tracking-tight">What would you like to build?</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Describe your idea. AI agents will plan, build, and deliver autonomously.
        </p>
      </div>
      <div className="grid w-full max-w-2xl grid-cols-1 gap-2 sm:grid-cols-2">
        {EXAMPLES.map((example) => {
          const Icon = ICON_MAP[example.icon];
          return (
            <button
              key={example.text}
              onClick={() => onExampleClick(example.text)}
              className="group flex items-start gap-3 rounded-xl border border-border bg-card p-3.5 text-left transition-all hover:border-primary/30 hover:bg-accent/50"
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" />
              <div>
                <p className="text-xs font-medium text-muted-foreground">{example.category}</p>
                <p className="text-sm text-foreground">{example.text}</p>
              </div>
            </button>
          );
        })}
      </div>

      {/* Mode distinction */}
      <div className="mt-8 w-full max-w-2xl rounded-xl border border-border bg-card/50 p-4">
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground/60">Choose your workflow</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex items-start gap-3 rounded-lg border border-primary/20 bg-primary/5 p-3">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div>
              <p className="text-sm font-medium">Quick Build</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                自然言語で即座にプロトタイプを生成
              </p>
            </div>
          </div>
          <Link
            to={`/p/${projectSlug}/lifecycle/research`}
            className="flex items-start gap-3 rounded-lg border border-border p-3 transition-colors hover:border-primary/30 hover:bg-accent/50"
          >
            <Layers className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">Product Lifecycle</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                調査→設計→開発→デプロイの段階的プロセス
              </p>
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
}
