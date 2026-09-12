import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/server";

/**
 * The structural top bar: deep slate in both themes.
 *
 * This is the one part of the app that does not follow the light/dark switch,
 * and that is the point of the palette rather than an oversight. The chrome is
 * structure and the content area is the document; keeping the bar dark in light
 * mode frames the page instead of dissolving into it, and means the eye lands on
 * content rather than on navigation. Its colours come from the `--nav-*` tokens,
 * which are defined once in globals.css and barely move between themes.
 */
const NAV_LINK =
  "rounded px-2.5 py-1.5 text-sm text-nav-muted transition-colors " +
  "duration-[120ms] hover:bg-nav-hover hover:text-nav-text";

export async function SiteHeader() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  let isAdmin = false;
  if (user) {
    const { data: profile } = await supabase
      .from("profiles")
      .select("role")
      .eq("id", user.id)
      .single();
    isAdmin = profile?.role === "admin";
  }

  return (
    <header className="sticky top-0 z-40 border-b border-nav-border bg-nav">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:px-6">
        <Link
          href="/"
          className="flex items-center gap-2 text-[0.9375rem] font-semibold tracking-tight text-nav-text"
        >
          <span
            aria-hidden
            className="grid size-6 place-items-center rounded bg-accent-on-nav text-[0.6875rem] font-bold text-nav"
          >
            L
          </span>
          Academy
        </Link>

        <nav className="ml-2 hidden items-center gap-1 sm:flex">
          <Link href="/" className={NAV_LINK}>
            Courses
          </Link>
          {user ? (
            <>
              <Link href="/dashboard" className={NAV_LINK}>
                My learning
              </Link>
              <Link href="/account/security" className={NAV_LINK}>
                Security
              </Link>
            </>
          ) : null}
          {isAdmin ? (
            <>
              <Link href="/admin" className={NAV_LINK}>
                Admin
              </Link>
              <Link href="/admin/submissions" className={NAV_LINK}>
                Grading
              </Link>
            </>
          ) : null}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {user ? (
            <form action="/auth/signout" method="post">
              <Button type="submit" variant="on-nav" size="sm">
                Sign out
              </Button>
            </form>
          ) : (
            <>
              <Link href="/login">
                <Button variant="on-nav" size="sm">
                  Sign in
                </Button>
              </Link>
              <Link href="/signup" className="hidden sm:block">
                <Button variant="on-nav-solid" size="sm">
                  Create account
                </Button>
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
