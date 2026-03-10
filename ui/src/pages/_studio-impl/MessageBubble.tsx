import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { formatDuration } from "@/lib/time";
import {
  CheckCircle2,
  XCircle,
  ShieldCheck,
  Copy,
  Check,
  ExternalLink,
  Eye,
  Bot,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type ChatMessage } from "./types";
import { ExecutionFlowBubble } from "./ExecutionFlowBubble";

// ─── Avatars ──────────────────────────────────────────

export function AgentAvatar({ name }: { name?: string }) {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10" title={name}>
      <Bot className="h-3.5 w-3.5 text-primary" />
    </div>
  );
}

export function UserAvatar() {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent">
      <User className="h-3.5 w-3.5 text-foreground" />
    </div>
  );
}

// ─── Elapsed Timer ────────────────────────────────────

export function ElapsedTimer({ startTime }: { startTime: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setElapsed(Date.now() - startTime), 1000);
    return () => clearInterval(interval);
  }, [startTime]);
  return (
    <span className="text-[11px] text-muted-foreground/60">
      {formatDuration(elapsed)}
    </span>
  );
}

// ─── Approval Bubble ──────────────────────────────────

export function ApprovalBubble({ approvalsPath }: { approvalsPath: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/10">
        <ShieldCheck className="h-3.5 w-3.5 text-amber-500" />
      </div>
      <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-amber-500/30 bg-card p-4">
        <p className="mb-1 text-sm font-medium">Approval needed</p>
        <p className="mb-3 text-xs text-muted-foreground">
          Agent action requires your approval before execution can continue.
        </p>
        <Link to={approvalsPath}>
          <Button size="sm" variant="outline" className="gap-1.5">
            <ExternalLink className="h-3 w-3" />
            承認ページで確認
          </Button>
        </Link>
      </div>
    </div>
  );
}

// ─── Message Bubble ───────────────────────────────────

export function MessageBubble({
  message,
  onCopyCode,
  copiedCode,
  onShowPreview,
}: {
  message: ChatMessage;
  onCopyCode: (code: string) => void;
  copiedCode: boolean;
  onShowPreview: () => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex items-start justify-end gap-3">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        <UserAvatar />
      </div>
    );
  }

  if (message.role === "system") {
    const isFailed = message.meta?.status === "failed";
    const isCompleted = message.meta?.status === "completed";
    return (
      <div className="flex justify-center">
        <div className={cn(
          "flex items-center gap-2 rounded-full px-3 py-1 text-xs",
          isFailed ? "bg-destructive/10 text-destructive" : isCompleted ? "bg-success/10 text-success" : "bg-muted text-muted-foreground",
        )}>
          {isFailed && <XCircle className="h-3 w-3" />}
          {isCompleted && <CheckCircle2 className="h-3 w-3" />}
          {message.content}
        </div>
      </div>
    );
  }

  if (message.role === "flow" && message.meta?.eventLog) {
    return (
      <ExecutionFlowBubble
        eventLog={message.meta.eventLog}
        executionSummary={message.meta.executionSummary}
        startedAt={message.meta.startedAt}
        completedAt={message.meta.completedAt}
      />
    );
  }

  if (message.role === "artifact" && message.meta?.code) {
    const code = message.meta.code;
    return (
      <div className="flex items-start gap-3">
        <AgentAvatar />
        <div className="max-w-[85%] space-y-2">
          <div className="rounded-2xl rounded-tl-sm border border-border bg-card p-4">
            <div className="mb-2 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              <span className="text-sm font-medium">Generated successfully</span>
              <Badge variant="secondary" className="text-[10px]">
                {code.length.toLocaleString()} chars
              </Badge>
            </div>

            {/* Mini preview */}
            <div
              className="mb-3 h-40 cursor-pointer overflow-hidden rounded-lg border border-border"
              onClick={onShowPreview}
            >
              <iframe
                srcDoc={code}
                title="Preview"
                className="pointer-events-none h-[600px] w-[1000px] origin-top-left scale-[0.28]"
                sandbox="allow-scripts"
              />
            </div>

            <div className="flex items-center gap-2">
              <Button variant="default" size="sm" className="gap-1.5" onClick={onShowPreview}>
                <Eye className="h-3 w-3" />
                Open Preview
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => onCopyCode(code)}
              >
                {copiedCode ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                {copiedCode ? "Copied" : "Copy Code"}
              </Button>
            </div>
          </div>

          {message.meta.cost != null && (
            <p className="text-[10px] text-muted-foreground/60">
              Cost: ${message.meta.cost.toFixed(4)}
              {message.meta.tokens && (
                <> | {message.meta.tokens.in.toLocaleString()} in + {message.meta.tokens.out.toLocaleString()} out tokens</>
              )}
            </p>
          )}
        </div>
      </div>
    );
  }

  // Agent message (default)
  return (
    <div className="flex items-start gap-3">
      <AgentAvatar />
      <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-card px-4 py-2.5 text-sm">
        <p className="whitespace-pre-wrap text-foreground">{message.content.replace(/\*\*(.*?)\*\*/g, "$1")}</p>
      </div>
    </div>
  );
}
