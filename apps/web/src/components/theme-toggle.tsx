"use client";

import { useSyncExternalStore } from "react";

type Theme = "light" | "dark";

/**
 * Reads the theme straight from the DOM rather than mirroring it into React
 * state.
 *
 * The inline script in the layout sets data-theme before first paint, so the
 * DOM is the source of truth and React is downstream of it. Copying it into
 * state inside an effect would mean rendering once with the wrong value and
 * then correcting — the flash this component exists to avoid.
 *
 * A MutationObserver keeps every instance in sync if the attribute is changed
 * anywhere else.
 */
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}

function getSnapshot(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function getServerSnapshot(): Theme {
  // The server cannot know the viewer's choice; the inline script corrects it
  // before anything is painted.
  return "light";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      // Private mode or blocked site data. The choice just will not persist.
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      className="grid size-9 place-items-center rounded-md text-muted transition-colors duration-[120ms] hover:bg-surface-hover hover:text-text"
    >
      <svg
        viewBox="0 0 24 24"
        className="size-4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        aria-hidden
      >
        {theme === "dark" ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path
              d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
              strokeLinecap="round"
            />
          </>
        ) : (
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" strokeLinejoin="round" />
        )}
      </svg>
    </button>
  );
}
