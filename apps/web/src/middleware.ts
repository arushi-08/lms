import type { NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/middleware";

export async function middleware(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  matcher: [
    // Everything except static assets, image files, and /auth.
    //
    // /auth is excluded deliberately. Those routes own their own cookies: the
    // callback is mid-PKCE-exchange, holding a code-verifier cookie that the
    // browser set and that only it should consume, and sign-out is removing
    // the session on purpose. Running a session refresh across either means a
    // second Supabase client writing auth cookies on the same request as the
    // one that is meant to be writing them, which is a race with nothing to
    // gain -- neither route needs a refreshed session to do its job.
    "/((?!_next/static|_next/image|favicon.ico|auth/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|avif|ico|woff2?)$).*)",
  ],
};
