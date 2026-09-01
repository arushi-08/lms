import { cn } from "@/lib/cn";

type Props = {
  value: number;
  label?: string;
  className?: string;
};

export function Progress({ value, label, className }: Props) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? "Progress"}
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken",
        className,
      )}
    >
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-[320ms] ease-brand"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
