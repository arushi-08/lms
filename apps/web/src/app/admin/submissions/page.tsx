import { GradingQueue } from "@/components/admin/grading-queue";
import { EmptyState } from "@/components/ui/empty-state";
import { apiGet } from "@/lib/api-server";
import type { QueuedSubmission } from "@/components/admin/grading-queue";

export const metadata = { title: "Marking · Admin" };
export const dynamic = "force-dynamic";

export default async function SubmissionsPage() {
  let submissions: QueuedSubmission[] = [];
  let error: string | null = null;
  try {
    submissions = await apiGet<QueuedSubmission[]>("/api/admin/submissions");
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "The API is unreachable.";
  }

  if (error) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-text">Marking</h1>
        <div className="mt-8">
          <EmptyState title="Could not reach the API" description={error} />
        </div>
      </div>
    );
  }

  return <GradingQueue initial={submissions} />;
}
