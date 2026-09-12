import { cn } from "@/lib/cn";

type Props = {
  value: number;
  label?: string;
  className?: string;
};

export function Progress({ value, label, className }: Props) {
  const clamped = Math.max(0, Math.min(100, value));
  // Cobalt while there is work left, emerald once there is not. The colour is
  // the reward -- a finished module should look different across the room, not
  // just read 100%. The fill tokens rather than the text tokens: these are solid
  // areas, which is the role the specified mid-tones are right for.
  const complete = clamped >= 100;
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
        className={cn(
          "h-full rounded-full transition-[width,background-color] duration-[320ms] ease-brand",
          complete ? "bg-success-fill" : "bg-accent",
        )}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
