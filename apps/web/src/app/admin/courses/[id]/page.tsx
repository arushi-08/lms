import { notFound } from "next/navigation";

import { CourseEditor } from "@/components/admin/course-editor";
import { EmptyState } from "@/components/ui/empty-state";
import { ApiError } from "@/lib/api";
import { apiGet } from "@/lib/api-server";
import type { AdminCourseTree } from "@/lib/admin-client";

export const metadata = { title: "Edit course · Admin" };
export const dynamic = "force-dynamic";

export default async function AdminCoursePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let course: AdminCourseTree;
  try {
    course = await apiGet<AdminCourseTree>(`/api/admin/courses/${id}`);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) notFound();
    return (
      <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
        <EmptyState
          title="Could not load this course"
          description={
            cause instanceof Error
              ? cause.message
              : "The API is unreachable. Check the backend is running."
          }
        />
      </div>
    );
  }

  return <CourseEditor course={course} />;
}
