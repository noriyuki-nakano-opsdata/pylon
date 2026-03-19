import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type MonacoApi = typeof import("monaco-editor");

interface MonacoCodeSurfaceProps {
  value: string;
  language: string;
  path?: string;
  label: string;
  className?: string;
  minimap?: boolean;
  wordWrap?: "off" | "on";
}

function sanitizeModelPath(path: string) {
  return path.replace(/^\/+/, "").replace(/\s+/g, "-");
}

function fallbackPath(language: string, label: string) {
  const stem = label.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "scratch";
  const extension = language === "css"
    ? "css"
    : language === "html"
      ? "html"
      : language === "javascript"
        ? "js"
        : language === "typescript"
          ? "tsx"
          : "txt";
  return `${stem}.${extension}`;
}

function StaticCodeSurface({
  value,
  className,
  status,
}: {
  value: string;
  className?: string;
  status?: ReactNode;
}) {
  const lines = useMemo(() => (value || " ").split(/\r?\n/), [value]);

  return (
    <div className={cn("relative h-full min-h-0 overflow-hidden bg-[#0a0f16]", className)}>
      {status ? (
        <div className="absolute right-3 top-3 z-10 rounded-full border border-white/10 bg-black/35 px-3 py-1 text-[10px] font-medium tracking-[0.16em] text-slate-400 backdrop-blur">
          {status}
        </div>
      ) : null}
      <div className="h-full overflow-auto">
        <div className="grid min-w-max grid-cols-[auto_minmax(56rem,1fr)] font-mono text-[12px] text-slate-200">
          <div className="border-r border-white/8 bg-[#0d131d] px-3 py-4 text-right text-slate-600">
            {lines.map((_, index) => (
              <div key={`fallback-line-${index + 1}`} className="h-6 leading-6">
                {index + 1}
              </div>
            ))}
          </div>
          <div className="px-4 py-4">
            {lines.map((line, index) => (
              <div key={`fallback-content-${index + 1}`} className="whitespace-pre leading-6 text-slate-100">
                {line.length > 0 ? line : " "}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function MonacoCodeSurface({
  value,
  language,
  path,
  label,
  className,
  minimap = false,
  wordWrap = "off",
}: MonacoCodeSurfaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<ReturnType<MonacoApi["editor"]["create"]> | null>(null);
  const modelRef = useRef<ReturnType<MonacoApi["editor"]["createModel"]> | null>(null);
  const [monacoApi, setMonacoApi] = useState<MonacoApi | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "fallback">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const shouldBootMonaco = import.meta.env.MODE !== "test";

  useEffect(() => {
    if (!shouldBootMonaco) {
      setLoadState("fallback");
      return;
    }

    let cancelled = false;

    void import("./monacoRuntime")
      .then(({ loadMonaco }) => loadMonaco())
      .then((runtime) => {
        if (cancelled) return;
        runtime.editor.setTheme("pylon-ide");
        setMonacoApi(runtime);
        setLoadState("ready");
      })
      .catch((error) => {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : "Failed to load Monaco");
        setLoadState("fallback");
      });

    return () => {
      cancelled = true;
      modelRef.current?.dispose();
      modelRef.current = null;
      editorRef.current?.dispose();
      editorRef.current = null;
    };
  }, [shouldBootMonaco]);

  useEffect(() => {
    if (!monacoApi || !containerRef.current || loadState !== "ready") return;

    if (!editorRef.current) {
      editorRef.current = monacoApi.editor.create(containerRef.current, {
        automaticLayout: true,
        contextmenu: false,
        cursorBlinking: "smooth",
        cursorSmoothCaretAnimation: "on",
        fontFamily: "\"IBM Plex Mono\", \"SFMono-Regular\", Consolas, monospace",
        fontLigatures: true,
        fontSize: 12.5,
        glyphMargin: false,
        lineDecorationsWidth: 0,
        lineHeight: 22,
        lineNumbersMinChars: 3,
        minimap: { enabled: minimap },
        overviewRulerBorder: false,
        padding: { top: 14, bottom: 18 },
        readOnly: true,
        renderValidationDecorations: "off",
        roundedSelection: false,
        scrollBeyondLastLine: false,
        scrollbar: {
          alwaysConsumeMouseWheel: false,
          horizontalScrollbarSize: 10,
          verticalScrollbarSize: 10,
        },
        smoothScrolling: true,
        stickyScroll: { enabled: true },
        wordWrap,
      });
    }

    editorRef.current.updateOptions({
      minimap: { enabled: minimap },
      wordWrap,
    });

    const previousModel = modelRef.current;
    const uri = monacoApi.Uri.parse(`file:///${sanitizeModelPath(path ?? fallbackPath(language, label))}`);
    const nextModel = monacoApi.editor.createModel(value || "", language, uri);

    modelRef.current = nextModel;
    editorRef.current.setModel(nextModel);
    editorRef.current.setScrollPosition({ scrollTop: 0, scrollLeft: 0 });

    previousModel?.dispose();

    return () => {
      if (modelRef.current === nextModel) {
        modelRef.current = null;
      }
      nextModel.dispose();
    };
  }, [language, label, loadState, minimap, monacoApi, path, value, wordWrap]);

  if (loadState !== "ready") {
    return (
      <StaticCodeSurface
        value={value}
        className={className}
        status={loadError ? (
          <span className="inline-flex items-center gap-1.5">
            <AlertCircle className="h-3.5 w-3.5 text-amber-300" />
            Monaco fallback
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-300" />
            Booting Monaco
          </span>
        )}
      />
    );
  }

  return (
    <div className={cn("relative h-full min-h-0 overflow-hidden bg-[#0a0f16]", className)}>
      <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-full border border-white/10 bg-black/35 px-3 py-1 text-[10px] font-medium tracking-[0.16em] text-slate-400 backdrop-blur">
        MONACO / READ ONLY
      </div>
      <div ref={containerRef} className="h-full w-full" aria-label={label} />
    </div>
  );
}
