import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";

/**
 * POST only. A GET sign-out can be triggered by any image tag or link
 * prefetch on a page the user visits, which logs people out at random.
 */
export async function POST(request: Request) {
  const supabase = await createClient();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/", request.url), { status: 303 });
}
