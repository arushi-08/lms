import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type Tone = "info" | "success" | "warning" | "danger";

const TONES: Record<Tone, string> = {
  info: "bg-info-subtle text-info",
  success: "bg-success-subtle text-success",
  warning: "bg-warning-subtle text-warning",
  danger: "bg-danger-subtle text-danger",
};

export function Alert({
  tone = "info",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      // Errors interrupt; everything else waits for a pause in speech.
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "rounded-md px-3.5 py-2.5 text-sm font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}
