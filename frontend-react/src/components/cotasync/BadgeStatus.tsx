import { cn } from "@/lib/utils";

type Tone = "success" | "error" | "warning" | "neutral" | "info";

const toneClass: Record<Tone, string> = {
  success: "bg-success/15 text-success border border-success/30",
  error: "bg-destructive/15 text-destructive border border-destructive/30",
  warning: "bg-warning/20 text-warning-foreground border border-warning/40",
  info: "bg-primary/10 text-primary border border-primary/20",
  neutral: "bg-muted text-muted-foreground border border-border",
};

export function BadgeStatus({
  children,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
        toneClass[tone],
        className,
      )}
    >
      <span
        className={cn("h-1.5 w-1.5 rounded-full", {
          "bg-success": tone === "success",
          "bg-destructive": tone === "error",
          "bg-warning": tone === "warning",
          "bg-primary": tone === "info",
          "bg-muted-foreground": tone === "neutral",
        })}
      />
      {children}
    </span>
  );
}
