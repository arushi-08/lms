import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "on-nav" | "on-nav-solid";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-on-accent hover:bg-accent-hover shadow-xs " +
    "active:translate-y-px",
  secondary:
    "bg-surface text-text border border-border hover:bg-surface-hover " +
    "hover:border-border-strong shadow-xs active:translate-y-px",
  ghost: "text-muted hover:text-text hover:bg-surface-hover",
  danger: "bg-danger-fill text-white hover:brightness-110 shadow-xs active:translate-y-px",
  // For the deep-slate top bar. The page-level variants cannot be reused there:
  // `secondary` is a white card on a dark bar, and `primary` at the specified
  // cobalt sits at 3.45:1 against slate-900 -- legible, but a call to action
  // that recedes into the chrome instead of standing out from it.
  "on-nav":
    "bg-nav-raised text-nav-text border border-nav-border hover:bg-nav-hover " +
    "hover:border-accent-on-nav active:translate-y-px",
  "on-nav-solid":
    "bg-accent-on-nav text-nav hover:brightness-110 shadow-xs active:translate-y-px",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5 rounded-md",
  md: "h-10 px-4 text-sm gap-2 rounded-md",
  lg: "h-12 px-6 text-base gap-2 rounded-lg",
};

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  children,
  ...props
}: Props) {
  return (
    <button
      // A loading button stays disabled so a double click cannot submit twice.
      disabled={disabled || loading}
      // Tells assistive tech the control is working, which a spinner alone does not.
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center font-medium",
        "transition-[background-color,border-color,color,transform] duration-[120ms] ease-brand",
        "disabled:pointer-events-none disabled:opacity-50",
        "whitespace-nowrap select-none",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {loading ? (
        <span
          aria-hidden
          className="size-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      ) : null}
      {children}
    </button>
  );
}
