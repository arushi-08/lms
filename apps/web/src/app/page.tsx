import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { createClient } from "@/lib/supabase/server";

export const metadata = { title: "Courses" };

type CourseRow = {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  is_free: boolean;
  price_cents: number;
  currency: string;
  modules: { lessons: { id: string }[] }[];
};

function formatPrice(course: CourseRow) {
  if (course.is_free) return "Free";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: course.currency,
    maximumFractionDigits: 0,
  }).format(course.price_cents / 100);
}

export default async function CatalogPage() {
  const supabase = await createClient();

  // RLS restricts this to published courses; the query does not need to say so,
  // and could not be tricked into saying otherwise.
  const { data, error } = await supabase
    .from("courses")
    .select("id,slug,title,subtitle,is_free,price_cents,currency,modules(lessons(id))")
    .order("published_at", { ascending: false });

  const courses = (data ?? []) as CourseRow[];

  return (
    <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
      <header className="max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight text-text sm:text-4xl">
          Learn something properly
        </h1>
        <p className="mt-3 text-base text-muted sm:text-lg">
          Short lessons, real practice, and a certificate that means you actually
          finished.
        </p>
      </header>

      <section className="mt-10 sm:mt-14">
        {error ? (
          <EmptyState
            title="Courses could not be loaded"
            description="The catalog is temporarily unavailable. Refreshing usually fixes it."
          />
        ) : courses.length === 0 ? (
          <EmptyState
            title="No courses published yet"
            description="Once a course is published it will appear here."
            icon={
              <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
                <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H5.5A1.5 1.5 0 0 1 4 15.5Z" />
                <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H14a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h4.5a1.5 1.5 0 0 0 1.5-1.5Z" />
              </svg>
            }
          />
        ) : (
          <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {courses.map((course) => {
              const lessonCount = course.modules.reduce(
                (total, module) => total + module.lessons.length,
                0,
              );
              return (
                <li key={course.id}>
                  <Card className="group h-full transition-[border-color,box-shadow] duration-200 ease-brand hover:border-border-strong hover:shadow-md">
                    <CardBody className="flex h-full flex-col">
                      <div className="flex items-start justify-between gap-3">
                        <h2 className="text-lg font-semibold tracking-tight text-text">
                          <Link href={`/courses/${course.slug}`} className="after:absolute after:inset-0">
                            {course.title}
                          </Link>
                        </h2>
                        <Badge tone={course.is_free ? "accent" : "neutral"}>
                          {formatPrice(course)}
                        </Badge>
                      </div>
                      {course.subtitle ? (
                        <p className="mt-2 line-clamp-3 text-sm text-muted">
                          {course.subtitle}
                        </p>
                      ) : null}
                      <p className="mt-4 pt-4 text-xs text-subtle border-t border-border">
                        {lessonCount === 0
                          ? "No lessons yet"
                          : `${lessonCount} lesson${lessonCount === 1 ? "" : "s"}`}
                      </p>
                    </CardBody>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {courses.length > 0 ? (
        <div className="mt-12 flex justify-center">
          <Link href="/signup">
            <Button size="lg">Create a free account</Button>
          </Link>
        </div>
      ) : null}
    </div>
  );
}
