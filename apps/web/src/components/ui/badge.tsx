import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-sunken text-muted border-border",
  accent: "bg-accent-subtle text-accent border-accent-border",
  success: "bg-success-subtle text-success border-transparent",
  warning: "bg-warning-subtle text-warning border-transparent",
  danger: "bg-danger-subtle text-danger border-transparent",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5",
        "text-xs font-medium",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}
