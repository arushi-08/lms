import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
import { createClient } from "@/lib/supabase/server";

export const metadata = { title: "My learning" };

type EnrollmentRow = {
  id: string;
  progress_percent: number;
  completed_at: string | null;
  expires_at: string | null;
  status: string;
  courses: { slug: string; title: string; subtitle: string | null } | null;
};

export default async function DashboardPage() {
  const supabase = await createClient();

  // The route is already guarded in middleware; this is the second check, so a
  // middleware matcher change can never silently expose the page.
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  // RLS scopes these to the signed-in user. There is no user_id filter here
  // because there does not need to be one, and one could be dropped.
  const [{ data: enrollmentData }, { data: certificateData }] = await Promise.all([
    supabase
      .from("enrollments")
      .select("id,progress_percent,completed_at,expires_at,status,courses(slug,title,subtitle)")
      .order("enrolled_at", { ascending: false }),
    supabase
      .from("certificates")
      .select("serial,issued_at,revoked_at,course_id,courses(title)")
      .order("issued_at", { ascending: false }),
  ]);

  const enrollments = (enrollmentData ?? []) as unknown as EnrollmentRow[];
  const certificates = (certificateData ?? []) as unknown as {
    serial: string;
    issued_at: string;
    revoked_at: string | null;
    courses: { title: string } | null;
  }[];

  const active = enrollments.filter((e) => e.status === "active");

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight text-text sm:text-3xl">
        My learning
      </h1>

      <section className="mt-8">
        {active.length === 0 ? (
          <EmptyState
            title="You are not enrolled in anything yet"
            description="Browse the catalog and pick a course to get started."
            action={
              <Link href="/">
                <Button>Browse courses</Button>
              </Link>
            }
          />
        ) : (
          <ul className="grid gap-4">
            {active.map((enrollment) => {
              const course = enrollment.courses;
              const done = enrollment.completed_at !== null;
              return (
                <li key={enrollment.id}>
                  <Card className="transition-[border-color] duration-200 hover:border-border-strong">
                    <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-center">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h2 className="truncate text-base font-semibold text-text">
                            {course?.title ?? "Untitled course"}
                          </h2>
                          {done ? <Badge tone="success">Completed</Badge> : null}
                        </div>
                        {course?.subtitle ? (
                          <p className="mt-1 truncate text-sm text-muted">
                            {course.subtitle}
                          </p>
                        ) : null}
                        <div className="mt-3 flex items-center gap-3">
                          <Progress
                            value={enrollment.progress_percent}
                            label={`${course?.title ?? "Course"} progress`}
                            className="max-w-xs"
                          />
                          <span className="shrink-0 text-xs tabular-nums text-subtle">
                            {Math.round(enrollment.progress_percent)}%
                          </span>
                        </div>
                      </div>
                      {course ? (
                        <Link href={`/courses/${course.slug}`} className="shrink-0">
                          <Button variant={done ? "secondary" : "primary"} size="sm">
                            {enrollment.progress_percent > 0 ? "Continue" : "Start"}
                          </Button>
                        </Link>
                      ) : null}
                    </CardBody>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="mt-12">
        <h2 className="text-lg font-semibold tracking-tight text-text">
          Certificates
        </h2>
        <div className="mt-4">
          {certificates.length === 0 ? (
            <EmptyState
              title="No certificates yet"
              description="Finish every required lesson and pass the quizzes to earn one."
            />
          ) : (
            <ul className="grid gap-3">
              {certificates.map((certificate) => (
                <li key={certificate.serial}>
                  <Card>
                    <CardBody className="flex items-center justify-between gap-4 py-4">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-text">
                          {certificate.courses?.title ?? "Course"}
                        </p>
                        <p className="mt-0.5 text-xs text-subtle">
                          Issued{" "}
                          {new Date(certificate.issued_at).toLocaleDateString(undefined, {
                            year: "numeric",
                            month: "long",
                            day: "numeric",
                          })}
                        </p>
                      </div>
                      {certificate.revoked_at ? (
                        <Badge tone="danger">Revoked</Badge>
                      ) : (
                        <Link href={`/verify/${certificate.serial}`}>
                          <Button variant="secondary" size="sm">
                            View
                          </Button>
                        </Link>
                      )}
                    </CardBody>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
