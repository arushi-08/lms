import Link from "next/link";
import { notFound } from "next/navigation";

import { LessonView } from "@/components/learn/lesson-view";
import { apiGet } from "@/lib/api-server";
import type { Assignment, Quiz } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

type Lesson = {
  id: string;
  title: string;
  type: string;
  position: number;
  is_preview: boolean;
  duration_seconds: number | null;
};

export default async function LearnPage({
  params,
}: {
  params: Promise<{ slug: string; lessonId: string }>;
}) {
  const { slug, lessonId } = await params;
  const supabase = await createClient();

  const { data } = await supabase
    .from("courses")
    .select(
      "id,slug,title,modules(id,title,position," +
        "lessons(id,title,type,position,is_preview,duration_seconds))",
    )
    .eq("slug", slug)
    .maybeSingle();

  if (!data) notFound();
  const course = data as unknown as {
    id: string;
    slug: string;
    title: string;
    modules: { id: string; title: string; position: number; lessons: Lesson[] }[];
  };

  const ordered = [...course.modules]
    .sort((a, b) => a.position - b.position)
    .flatMap((m) => [...m.lessons].sort((a, b) => a.position - b.position));

  const index = ordered.findIndex((l) => l.id === lessonId);
  if (index === -1) notFound();
  const lesson = ordered[index]!;

  // Assessment content comes from the API rather than straight from Supabase:
  // the quiz payload has to be assembled with the answer key stripped, and the
  // assignment payload carries this student's own submission history.
  let quiz: Quiz | null = null;
  let assignment: Assignment | null = null;
  let assessmentError: string | null = null;

  try {
    if (lesson.type === "quiz") {
      quiz = await apiGet<Quiz>(`/api/quizzes/by-lesson/${lessonId}`);
    } else if (lesson.type === "assignment") {
      assignment = await apiGet<Assignment>(`/api/lessons/${lessonId}/assignment`);
    }
  } catch (cause) {
    assessmentError =
      cause instanceof Error ? cause.message : "Could not load this lesson.";
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <Link
        href={`/courses/${course.slug}`}
        className="text-sm text-muted transition-colors hover:text-text"
      >
        ← {course.title}
      </Link>
      <LessonView
        courseSlug={course.slug}
        lessons={ordered}
        currentIndex={index}
        quiz={quiz}
        assignment={assignment}
        assessmentError={assessmentError}
      />
    </div>
  );
}
