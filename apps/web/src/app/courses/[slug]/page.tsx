import Link from "next/link";
import { notFound } from "next/navigation";

import { EnrollButton } from "@/components/learn/enroll-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
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

type CourseRow = {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  description: string | null;
  is_free: boolean;
  price_cents: number;
  currency: string;
  modules: { id: string; title: string; position: number; lessons: Lesson[] }[];
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const supabase = await createClient();
  const { data } = await supabase
    .from("courses")
    .select("title,subtitle")
    .eq("slug", slug)
    .maybeSingle();
  return { title: data?.title ?? "Course", description: data?.subtitle ?? undefined };
}

function duration(seconds: number | null) {
  if (!seconds) return null;
  const m = Math.round(seconds / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export default async function CoursePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const supabase = await createClient();

  // RLS limits this to published courses, so an unpublished slug 404s here
  // without the query having to say so.
  const { data } = await supabase
    .from("courses")
    .select(
      "id,slug,title,subtitle,description,is_free,price_cents,currency," +
        "modules(id,title,position,lessons(id,title,type,position,is_preview,duration_seconds))",
    )
    .eq("slug", slug)
    .maybeSingle();

  if (!data) notFound();
  const course = data as unknown as CourseRow;

  const {
    data: { user },
  } = await supabase.auth.getUser();

  let enrolled = false;
  let progressPercent = 0;
  if (user) {
    const { data: enrollment } = await supabase
      .from("enrollments")
      .select("status,progress_percent")
      .eq("course_id", course.id)
      .maybeSingle();
    enrolled = enrollment?.status === "active";
    progressPercent = enrollment?.progress_percent ?? 0;
  }

  const modules = [...course.modules].sort((a, b) => a.position - b.position);
  const lessons = modules.flatMap((m) =>
    [...m.lessons].sort((a, b) => a.position - b.position),
  );
  const firstLesson = lessons[0];

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
      <Link href="/" className="text-sm text-muted transition-colors hover:text-text">
        ← All courses
      </Link>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-3xl font-semibold tracking-tight text-text">
            {course.title}
          </h1>
          <Badge tone={course.is_free ? "accent" : "neutral"}>
            {course.is_free
              ? "Free"
              : new Intl.NumberFormat(undefined, {
                  style: "currency",
                  currency: course.currency,
                  maximumFractionDigits: 0,
                }).format(course.price_cents / 100)}
          </Badge>
        </div>
        {course.subtitle ? (
          <p className="mt-2 text-lg text-muted">{course.subtitle}</p>
        ) : null}
        <p className="mt-3 text-sm text-subtle">
          {modules.length} module{modules.length === 1 ? "" : "s"} · {lessons.length}{" "}
          lesson{lessons.length === 1 ? "" : "s"}
        </p>
      </header>

      {enrolled ? (
        <Card className="mt-6">
          <CardBody className="flex flex-wrap items-center gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-text">You are enrolled</p>
              <div className="mt-2 flex items-center gap-3">
                <Progress value={progressPercent} className="max-w-xs" />
                <span className="text-xs tabular-nums text-subtle">
                  {Math.round(progressPercent)}%
                </span>
              </div>
            </div>
            {firstLesson ? (
              <Link href={`/learn/${course.slug}/${firstLesson.id}`}>
                <Button>{progressPercent > 0 ? "Continue" : "Start course"}</Button>
              </Link>
            ) : null}
          </CardBody>
        </Card>
      ) : (
        <div className="mt-6">
          <EnrollButton
            slug={course.slug}
            isFree={course.is_free}
            signedIn={Boolean(user)}
          />
        </div>
      )}

      {course.description ? (
        <p className="mt-8 whitespace-pre-line text-base text-muted">
          {course.description}
        </p>
      ) : null}

      <section className="mt-10">
        <h2 className="text-lg font-semibold tracking-tight text-text">Curriculum</h2>
        <div className="mt-4 grid gap-4">
          {modules.length === 0 ? (
            <EmptyState
              title="No lessons published yet"
              description="This course is still being put together."
            />
          ) : (
            modules.map((module) => (
              <Card key={module.id}>
                <CardBody>
                  <h3 className="font-medium text-text">{module.title}</h3>
                  <ul className="mt-3 grid gap-1.5">
                    {[...module.lessons]
                      .sort((a, b) => a.position - b.position)
                      .map((lesson) => {
                        const openable = enrolled || lesson.is_preview;
                        const row = (
                          <div className="flex items-center gap-3 rounded-md px-2 py-2 text-sm">
                            <span className="w-5 shrink-0 text-xs tabular-nums text-subtle">
                              {lesson.position}
                            </span>
                            <span
                              className={
                                openable ? "flex-1 text-text" : "flex-1 text-subtle"
                              }
                            >
                              {lesson.title}
                            </span>
                            {lesson.is_preview && !enrolled ? (
                              <Badge tone="accent">Free preview</Badge>
                            ) : null}
                            {duration(lesson.duration_seconds) ? (
                              <span className="text-xs text-subtle">
                                {duration(lesson.duration_seconds)}
                              </span>
                            ) : null}
                            {!openable ? (
                              <svg
                                viewBox="0 0 24 24"
                                className="size-3.5 text-subtle"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                                aria-label="Locked"
                              >
                                <rect x="4" y="10" width="16" height="10" rx="2" />
                                <path d="M8 10V7a4 4 0 0 1 8 0v3" />
                              </svg>
                            ) : null}
                          </div>
                        );
                        return (
                          <li key={lesson.id}>
                            {openable ? (
                              <Link
                                href={`/learn/${course.slug}/${lesson.id}`}
                                className="block rounded-md transition-colors hover:bg-surface-hover"
                              >
                                {row}
                              </Link>
                            ) : (
                              row
                            )}
                          </li>
                        );
                      })}
                  </ul>
                </CardBody>
              </Card>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
