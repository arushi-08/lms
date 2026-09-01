import { cn } from "@/lib/cn";

/** Placeholder block. Give it the shape of the thing it stands in for. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-surface-sunken", className)}
    />
  );
}
