import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-full border font-semibold leading-none transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-muted text-muted-foreground",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground",
        success: "border-transparent bg-success/20 text-success",
        warning: "border-transparent bg-warning/20 text-warning",
        outline: "text-foreground",
        required:
          "border-[color:var(--badge-required-border)] bg-[color:var(--badge-required-bg)] text-[color:var(--badge-required-text)]",
        optional:
          "border-[color:var(--badge-optional-border)] bg-[color:var(--badge-optional-bg)] text-[color:var(--badge-optional-text)]",
        assistive:
          "border-[color:var(--badge-assistive-border)] bg-[color:var(--badge-assistive-bg)] text-[color:var(--badge-assistive-text)]",
      },
      size: {
        default: "min-h-5 px-2.5 py-0.5 text-xs",
        compact: "min-h-5 px-2 py-0.5 text-[10px]",
        field: "min-h-7 px-3 py-1 text-[11px] tracking-[0.08em]",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant, size }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
