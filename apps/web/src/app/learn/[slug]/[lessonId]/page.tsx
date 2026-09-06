import Link from "next/link";
import { notFound } from "next/navigation";

import { LessonView } from "@/components/learn/lesson-view";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

type Lesson = {
  id: string;
  title: string;
  type: string;
  position: number;
  is_preview: boolean;
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
    .select("id,slug,title,modules(id,title,position,lessons(id,title,type,position,is_preview))")
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
      />
    </div>
  );
}
