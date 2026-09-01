/**
 * Client for the FastAPI backend.
 *
 * Everything privileged — playback grants, progress, grading — goes through
 * the API rather than straight to Supabase, because those paths need checks
 * (entitlement, clamping, server-side grading) that a database policy cannot
 * express on its own.
 */
import { env } from "@/lib/env";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  accessToken?: string | null;
  signal?: AbortSignal;
};

export async function apiFetch<T>(
  path: string,
  { method = "GET", body, accessToken, signal }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(`${env.apiUrl}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    // Surface the API's own message when it sends one; never invent detail.
    let detail = `request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Non-JSON error body; the status alone will have to do.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/* --- typed shapes mirroring the API's response models --------------------- */

export type PlaybackGrant = {
  lesson_id: string;
  otp: string;
  playback_info: string;
  expires_at: string;
  direct_url: string | null;
};

export type ProgressUpdate = {
  lesson_id: string;
  watched_seconds: number;
  last_position_seconds: number;
  completed: boolean;
  course_progress_percent: number;
  course_completed: boolean;
};

export type QuizOption = { id: string; text: string };

export type QuizQuestion = {
  id: string;
  type: "single" | "multi" | "boolean" | "short_text";
  prompt: string;
  points: number;
  position: number;
  options: QuizOption[];
};

export type Quiz = {
  quiz_id: string;
  lesson_id: string;
  title: string;
  passing_score: number;
  max_attempts: number | null;
  attempts_used: number;
  attempts_remaining: number | null;
  questions: QuizQuestion[];
};
