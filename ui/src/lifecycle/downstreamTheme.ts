import { cva } from "class-variance-authority";

export const downstreamWorkspaceClassName = "lifecycle-downstream-workspace text-foreground";

export const downstreamTopbarClassName = [
  "lifecycle-downstream-topbar",
  "border-b border-border/70",
].join(" ");

export const downstreamEyebrowClassName = "text-[11px] font-semibold tracking-[0.18em] text-muted-foreground";

export const downstreamSurfaceVariants = cva(
  "lifecycle-downstream-panel rounded-[1.8rem] border backdrop-blur-xl",
  {
    variants: {
      tone: {
        default: "border-border/70 bg-card/90",
        strong: "lifecycle-downstream-panel-strong border-border/70 bg-card/94",
        inset: "lifecycle-downstream-metric border-border/60 bg-background/82",
        subtle: "border-border/55 bg-muted/10",
        accent: "border-primary/18 bg-primary/5",
        success: "border-emerald-200 bg-emerald-50/70",
        warning: "border-amber-200 bg-amber-50/70",
        danger: "border-rose-200 bg-rose-50/70",
      },
      padding: {
        none: "",
        sm: "p-4",
        md: "p-5",
        lg: "p-6",
      },
    },
    defaultVariants: {
      tone: "default",
      padding: "none",
    },
  },
);

export const downstreamMetricVariants = cva(
  "lifecycle-downstream-metric rounded-[1.25rem] border border-border/60 bg-background/82",
  {
    variants: {
      padding: {
        sm: "p-3",
        md: "p-4",
      },
    },
    defaultVariants: {
      padding: "md",
    },
  },
);

export const downstreamActionVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-full border px-4 py-2 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55",
  {
    variants: {
      tone: {
        primary: "border-primary/20 bg-primary text-primary-foreground hover:bg-primary/90",
        secondary: "border-border/70 bg-background/82 text-foreground hover:bg-accent",
        muted: "border-border/70 bg-card/82 text-muted-foreground hover:bg-accent hover:text-foreground",
      },
    },
    defaultVariants: {
      tone: "secondary",
    },
  },
);
