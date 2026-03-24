import { cva } from "class-variance-authority";

export const planningWorkspaceClassName = [
  "planning-workspace",
  "text-foreground",
  "bg-[radial-gradient(circle_at_top_left,rgba(108,177,241,0.14),transparent_28%),radial-gradient(circle_at_top_right,rgba(244,197,106,0.12),transparent_24%),linear-gradient(180deg,rgba(6,11,17,0.98),rgba(6,11,17,1))]",
].join(" ");

export const planningTopbarClassName = [
  "border-b",
  "border-[color:var(--planning-border)]",
  "bg-[linear-gradient(180deg,rgba(7,13,20,0.96),rgba(7,13,20,0.84))]",
  "backdrop-blur-xl",
].join(" ");

export const planningEyebrowClassName = "text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--planning-text-muted)]";
export const planningMicroLabelClassName = "text-[12px] font-medium uppercase tracking-[0.12em] text-[var(--planning-text-muted)]";
export const planningMutedCopyClassName = "text-sm text-[color:var(--planning-text-soft)]";
export const planningSectionTitleClassName = "text-sm font-semibold tracking-[0.01em] text-foreground";
export const planningBodyLabelClassName = "text-xs font-medium text-[color:var(--planning-text-soft)]";
export const planningDataValueClassName = "text-sm leading-6 text-foreground";
export const planningFieldClassName = [
  "w-full rounded-2xl border border-[color:var(--planning-border)] bg-[var(--planning-inset)]",
  "px-3 py-2 text-sm text-foreground shadow-[var(--planning-shadow-inset)]",
  "placeholder:text-[color:var(--planning-text-muted)] focus:outline-none",
  "focus:border-[color:var(--planning-border-strong)] focus:ring-2 focus:ring-[rgba(119,182,234,0.15)]",
].join(" ");

export const planningSurfaceVariants = cva(
  "rounded-[var(--planning-radius-panel)] border shadow-[var(--planning-shadow)] backdrop-blur-xl",
  {
    variants: {
      tone: {
        default: "border-[color:var(--planning-border)] bg-[var(--planning-surface)]",
        strong: "border-[color:var(--planning-border-strong)] bg-[var(--planning-surface-strong)]",
        accent: "border-[color:var(--planning-border-strong)] bg-[linear-gradient(180deg,var(--planning-accent-soft),var(--planning-surface-strong))]",
        subtle: "border-[color:var(--planning-border)] bg-[var(--planning-surface-muted)]",
        inset: "border-[color:var(--planning-border)] bg-[var(--planning-inset)] shadow-[var(--planning-shadow-inset)]",
        danger: "border-[color:var(--planning-danger-border)] bg-[var(--planning-danger-soft)]",
        warning: "border-[color:var(--planning-warning-border)] bg-[var(--planning-warning-soft)]",
        success: "border-[color:var(--planning-success-border)] bg-[var(--planning-success-soft)]",
      },
      padding: {
        none: "",
        sm: "p-3",
        md: "p-4 sm:p-5",
        lg: "p-5 sm:p-6",
      },
    },
    defaultVariants: {
      tone: "default",
      padding: "none",
    },
  },
);

export const planningDetailCardVariants = cva(
  "rounded-[1.15rem] border shadow-[var(--planning-shadow-soft)]",
  {
    variants: {
      tone: {
        default: "border-[color:var(--planning-border)] bg-[rgba(11,20,31,0.82)]",
        accent: "border-[color:var(--planning-border-strong)] bg-[rgba(103,176,237,0.1)]",
        warning: "border-[color:var(--planning-warning-border)] bg-[var(--planning-warning-soft)]",
        danger: "border-[color:var(--planning-danger-border)] bg-[var(--planning-danger-soft)]",
        success: "border-[color:var(--planning-success-border)] bg-[var(--planning-success-soft)]",
      },
      padding: {
        none: "",
        sm: "p-3",
        md: "p-4",
        lg: "p-5",
      },
    },
    defaultVariants: {
      tone: "default",
      padding: "md",
    },
  },
);

export const planningMetricTileVariants = cva(
  "rounded-[1rem] border px-3 py-3 shadow-[var(--planning-shadow-soft)]",
  {
    variants: {
      tone: {
        default: "border-[color:var(--planning-border)] bg-[var(--planning-inset)]",
        accent: "border-[color:var(--planning-border-strong)] bg-[var(--planning-accent-soft)]",
        warning: "border-[color:var(--planning-warning-border)] bg-[var(--planning-warning-soft)]",
      },
    },
    defaultVariants: {
      tone: "default",
    },
  },
);

export const planningSoftBadgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium",
  {
    variants: {
      tone: {
        default: "border-[color:var(--planning-border)] bg-[var(--planning-inset)] text-[color:var(--planning-text-soft)]",
        accent: "border-[color:var(--planning-border-strong)] bg-[var(--planning-accent-soft)] text-[color:var(--planning-accent-strong)]",
        warning: "border-[color:var(--planning-warning-border)] bg-[var(--planning-warning-soft)] text-[color:var(--planning-warning-strong)]",
        danger: "border-[color:var(--planning-danger-border)] bg-[var(--planning-danger-soft)] text-[color:var(--planning-danger-strong)]",
        success: "border-[color:var(--planning-success-border)] bg-[var(--planning-success-soft)] text-[color:var(--planning-success-strong)]",
      },
    },
    defaultVariants: {
      tone: "default",
    },
  },
);

export const planningChipVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-medium tracking-[0.12em] uppercase",
  {
    variants: {
      tone: {
        default: "border-[color:var(--planning-border)] bg-[var(--planning-inset)] text-[color:var(--planning-text-soft)]",
        accent: "border-[color:var(--planning-border-strong)] bg-[var(--planning-accent-soft)] text-[color:var(--planning-accent-strong)]",
        danger: "border-[color:var(--planning-danger-border)] bg-[var(--planning-danger-soft)] text-[color:var(--planning-danger-strong)]",
        warning: "border-[color:var(--planning-warning-border)] bg-[var(--planning-warning-soft)] text-[color:var(--planning-warning-strong)]",
        success: "border-[color:var(--planning-success-border)] bg-[var(--planning-success-soft)] text-[color:var(--planning-success-strong)]",
      },
    },
    defaultVariants: {
      tone: "default",
    },
  },
);

export const planningTabVariants = cva(
  "shrink-0 inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-200",
  {
    variants: {
      active: {
        true: "border-[color:var(--planning-border-strong)] bg-[linear-gradient(180deg,var(--planning-accent-soft),rgba(10,18,28,0.94))] text-[color:var(--planning-accent-strong)] shadow-[var(--planning-shadow-soft)]",
        false: "border-transparent bg-transparent text-[color:var(--planning-text-soft)] hover:border-[color:var(--planning-border)] hover:bg-[var(--planning-surface-muted)] hover:text-foreground",
      },
    },
    defaultVariants: {
      active: false,
    },
  },
);

export const planningActionVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-full border px-4 py-2 text-xs font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-55",
  {
    variants: {
      tone: {
        primary: "border-[color:var(--planning-border-strong)] bg-[linear-gradient(135deg,var(--planning-accent-strong),var(--planning-accent))] text-[color:var(--planning-ink)] hover:brightness-105",
        secondary: "border-[color:var(--planning-border)] bg-[var(--planning-surface-strong)] text-foreground hover:border-[color:var(--planning-border-strong)] hover:bg-[var(--planning-surface)]",
        tonal: "border-[color:var(--planning-border-strong)] bg-[var(--planning-accent-soft)] text-[color:var(--planning-accent-strong)] hover:bg-[rgba(116,190,255,0.2)]",
        danger: "border-[color:var(--planning-danger-border)] bg-[var(--planning-danger-soft)] text-[color:var(--planning-danger-strong)] hover:bg-[rgba(255,122,94,0.16)]",
        muted: "border-[color:var(--planning-border)] bg-[var(--planning-inset)] text-[color:var(--planning-text-soft)] hover:text-foreground",
      },
    },
    defaultVariants: {
      tone: "secondary",
    },
  },
);
