import type { InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";

import { cn } from "@/lib/cn";

type Props = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: ReactNode;
  error?: string | null;
};

/**
 * Label, input, hint and error as one unit.
 *
 * Bundled deliberately: a bare Input invites a label that is not actually
 * associated with it, and an error message that screen readers never announce.
 * Here the wiring cannot be forgotten.
 */
export function Field({ label, hint, error, className, id, ...props }: Props) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;

  return (
    <div className="grid gap-1.5">
      <label htmlFor={inputId} className="text-sm font-medium text-text">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={cn(hint && hintId, error && errorId) || undefined}
        className={cn(
          "h-10 w-full rounded-md border bg-surface px-3 text-sm text-text",
          "placeholder:text-subtle",
          "transition-[border-color,box-shadow] duration-[120ms] ease-brand",
          "hover:border-border-strong",
          "disabled:cursor-not-allowed disabled:opacity-60",
          error ? "border-danger" : "border-border",
          className,
        )}
        {...props}
      />
      {hint && !error ? (
        <p id={hintId} className="text-xs text-subtle">
          {hint}
        </p>
      ) : null}
      {error ? (
        // Announced when it appears, rather than only being visible.
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
