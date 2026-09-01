import type { ReactNode } from "react";

/**
 * The state a new install spends most of its life in.
 *
 * Every list in this app renders one of these rather than collapsing to
 * nothing — an empty page reads as a bug, and the first thing anyone sees
 * after setting the platform up is a catalog with no courses in it.
 */
export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-surface/50 px-6 py-14 text-center">
      {icon ? (
        <div className="mb-4 flex size-11 items-center justify-center rounded-full bg-surface-sunken text-subtle">
          {icon}
        </div>
      ) : null}
      <p className="text-base font-medium text-text">{title}</p>
      {description ? (
        <p className="mt-1.5 max-w-sm text-sm text-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
