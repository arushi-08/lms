import { Skeleton } from "@/components/ui/skeleton";

/** Shaped like the catalog it stands in for, so the page does not jump. */
export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
      <Skeleton className="h-10 w-80 max-w-full" />
      <Skeleton className="mt-3 h-6 w-full max-w-lg" />
      <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 sm:mt-14">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-44" />
        ))}
      </div>
    </div>
  );
}
