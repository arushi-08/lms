"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { adminFetch, type AdminCourse } from "@/lib/admin-client";

/**
 * The list is rendered by the server component above; this component only
 * mutates and then asks the server to re-render.
 *
 * Fetching here in an effect would mean a render with no data, a setState, and
 * a second render — the skeleton flash on every visit — as well as duplicating
 * the fetch the server already has a token for.
 */
export function CourseList({ initialCourses }: { initialCourses: AdminCourse[] }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const courses = initialCourses;
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    try {
      await adminFetch("/api/admin/courses", {
        method: "POST",
        body: { title: title.trim() },
      });
      setTitle("");
      setError(null);
      startTransition(() => router.refresh());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the course.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text sm:text-3xl">
            Courses
          </h1>
          <p className="mt-1.5 text-sm text-muted">
            Create, edit and publish. No code changes required.
          </p>
        </div>
      </div>

      <Card className="mt-8">
        <CardBody>
          <form onSubmit={create} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Field
                label="New course"
                placeholder="e.g. Foundations of Practice"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <Button type="submit" loading={creating || pending} disabled={!title.trim()}>
              Create draft
            </Button>
          </form>
        </CardBody>
      </Card>

      {error ? (
        <Alert tone="danger" className="mt-6">
          {error}
        </Alert>
      ) : null}

      <div className="mt-8">
        {courses.length === 0 ? (
          <EmptyState
            title="No courses yet"
            description="Create your first one above. It starts as a draft, so nothing is public until you publish it."
          />
        ) : (
          <ul className="grid gap-3">
            {courses.map((course) => (
              <li key={course.id}>
                <Card className="transition-[border-color] duration-200 hover:border-border-strong">
                  <CardBody className="flex flex-col gap-4 py-4 sm:flex-row sm:items-center">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="truncate font-medium text-text">{course.title}</h2>
                        <Badge tone={course.status === "published" ? "success" : "neutral"}>
                          {course.status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-subtle">
                        {course.module_count} module{course.module_count === 1 ? "" : "s"} ·{" "}
                        {course.lesson_count} lesson{course.lesson_count === 1 ? "" : "s"} ·{" "}
                        {course.student_count} student
                        {course.student_count === 1 ? "" : "s"}
                      </p>
                    </div>
                    <Link href={`/admin/courses/${course.id}`} className="shrink-0">
                      <Button variant="secondary" size="sm">
                        Edit
                      </Button>
                    </Link>
                  </CardBody>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
