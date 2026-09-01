import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/server";

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
    <header className="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:px-6">
        <Link
          href="/"
          className="flex items-center gap-2 text-[0.9375rem] font-semibold tracking-tight text-text"
        >
          <span
            aria-hidden
            className="grid size-6 place-items-center rounded-md bg-accent text-[0.6875rem] font-bold text-on-accent"
          >
            L
          </span>
          Academy
        </Link>

        <nav className="ml-2 hidden items-center gap-1 sm:flex">
          <Link
            href="/"
            className="rounded-md px-2.5 py-1.5 text-sm text-muted transition-colors duration-[120ms] hover:bg-surface-hover hover:text-text"
          >
            Courses
          </Link>
          {user ? (
            <Link
              href="/dashboard"
              className="rounded-md px-2.5 py-1.5 text-sm text-muted transition-colors duration-[120ms] hover:bg-surface-hover hover:text-text"
            >
              My learning
            </Link>
          ) : null}
          {isAdmin ? (
            <Link
              href="/admin"
              className="rounded-md px-2.5 py-1.5 text-sm text-muted transition-colors duration-[120ms] hover:bg-surface-hover hover:text-text"
            >
              Admin
            </Link>
          ) : null}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {user ? (
            <form action="/auth/signout" method="post">
              <Button type="submit" variant="secondary" size="sm">
                Sign out
              </Button>
            </form>
          ) : (
            <>
              <Link href="/login">
                <Button variant="ghost" size="sm">
                  Sign in
                </Button>
              </Link>
              <Link href="/signup" className="hidden sm:block">
                <Button size="sm">Create account</Button>
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
