import { cn } from "@/lib/utils";

interface AvatarProps {
  login: string;
  src?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZES = { sm: "h-6 w-6 text-[10px]", md: "h-8 w-8 text-xs", lg: "h-10 w-10 text-sm" };

const COLORS = [
  "bg-blue-600", "bg-emerald-600", "bg-purple-600", "bg-amber-600",
  "bg-rose-600", "bg-cyan-600", "bg-indigo-600", "bg-teal-600",
];

function hashColor(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return COLORS[Math.abs(h) % COLORS.length];
}

export function Avatar({ login, src, size = "md", className }: AvatarProps) {
  if (src) {
    return (
      <img
        src={src}
        alt={login}
        className={cn("rounded-full object-cover", SIZES[size], className)}
      />
    );
  }
  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full font-medium text-white uppercase",
        SIZES[size],
        hashColor(login),
        className,
      )}
      title={login}
    >
      {login.slice(0, 2)}
    </div>
  );
}
