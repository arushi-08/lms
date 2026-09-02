import { CourseList } from "@/components/admin/course-list";
import { EmptyState } from "@/components/ui/empty-state";
import { apiGet } from "@/lib/api-server";
import type { AdminCourse } from "@/lib/admin-client";

export const metadata = { title: "Courses · Admin" };

// Admin data is never cacheable: it is per-user and changes on every edit.
export const dynamic = "force-dynamic";

export default async function AdminCoursesPage() {
  let courses: AdminCourse[] = [];
  let error: string | null = null;

  try {
    courses = await apiGet<AdminCourse[]>("/api/admin/courses");
  } catch (cause) {
    // The backend being down should read as "the API is unreachable", not as
    // "you have no courses" — those need very different reactions.
    error = cause instanceof Error ? cause.message : "The API is unreachable.";
  }

  if (error) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-text">Courses</h1>
        <div className="mt-8">
          <EmptyState
            title="Could not reach the API"
            description={`${error} Check the backend is running and NEXT_PUBLIC_API_URL is correct.`}
          />
        </div>
      </div>
    );
  }

  return <CourseList initialCourses={courses} />;
}
