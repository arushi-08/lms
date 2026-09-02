"use client";

/** Browser-side admin calls, with the current session's token attached. */
import { ApiError, apiFetch } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

async function token(): Promise<string | null> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

export async function adminFetch<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, accessToken: await token() });
}

export { ApiError };

export type AdminCourse = {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  status: "draft" | "published" | "archived";
  is_free: boolean;
  price_cents: number;
  currency: string;
  module_count: number;
  lesson_count: number;
  student_count: number;
  updated_at: string;
};

export type AdminLesson = {
  id: string;
  module_id: string;
  title: string;
  slug: string;
  type: "video" | "text" | "quiz";
  position: number;
  is_preview: boolean;
  is_required: boolean;
  duration_seconds: number | null;
  video_id: string | null;
  video_status: "absent" | "uploading" | "processing" | "ready" | "failed";
  has_quiz: boolean;
};

export type AdminModule = {
  id: string;
  title: string;
  description: string | null;
  position: number;
  lessons: AdminLesson[];
};

export type AdminCourseTree = {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  status: "draft" | "published" | "archived";
  modules: AdminModule[];
};
