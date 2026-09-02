"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { VideoUpload } from "@/components/admin/video-upload";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import {
  adminFetch,
  type AdminCourseTree,
  type AdminLesson,
  type AdminModule,
} from "@/lib/admin-client";

function move<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item as T);
  return next;
}

/**
 * Reordering is up/down buttons rather than drag-and-drop.
 *
 * Deliberate: buttons work with a keyboard, with a screen reader and on a
 * phone, all of which drag-and-drop handles badly without a lot of extra code.
 * Lessons are appended in order as they are created, so reordering is the
 * exception rather than the routine. Drag can be layered on later without
 * changing the API, which takes the complete ordering either way.
 */
export function CourseEditor({ course }: { course: AdminCourseTree }) {
  const router = useRouter();
  const courseId = course.id;
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newModule, setNewModule] = useState("");

  // Mutate, then ask the server component to re-render. The tree is never
  // fetched twice, and there is no window where the UI shows stale positions.
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      startTransition(() => router.refresh());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  const working = busy || pending;

  async function reorderModules(modules: AdminModule[]) {
    // The API requires the complete ordering, so send every id.
    await adminFetch(`/api/admin/courses/${courseId}/modules/reorder`, {
      method: "POST",
      body: { ids: modules.map((m) => m.id) },
    });
  }

  async function reorderLessons(module: AdminModule, lessons: AdminLesson[]) {
    await adminFetch(`/api/admin/modules/${module.id}/lessons/reorder`, {
      method: "POST",
      body: { ids: lessons.map((l) => l.id) },
    });
  }

  const published = course.status === "published";
  const lessonCount = course.modules.reduce((n, m) => n + m.lessons.length, 0);

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
      <Link
        href="/admin/courses"
        className="text-sm text-muted transition-colors hover:text-text"
      >
        ← All courses
      </Link>

      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-text">
              {course.title}
            </h1>
            <Badge tone={published ? "success" : "neutral"}>{course.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-muted">
            {course.modules.length} module{course.modules.length === 1 ? "" : "s"} ·{" "}
            {lessonCount} lesson{lessonCount === 1 ? "" : "s"}
          </p>
        </div>

        <Button
          variant={published ? "secondary" : "primary"}
          loading={working}
          onClick={() =>
            run(() =>
              adminFetch(
                `/api/admin/courses/${courseId}/${published ? "unpublish" : "publish"}`,
                { method: "POST" },
              ),
            )
          }
        >
          {published ? "Unpublish" : "Publish"}
        </Button>
      </div>

      {error ? (
        <Alert tone="danger" className="mt-6">
          {error}
        </Alert>
      ) : null}

      <div className="mt-8 grid gap-4">
        {course.modules.length === 0 ? (
          <EmptyState
            title="No modules yet"
            description="Add a module below, then put lessons inside it."
          />
        ) : (
          course.modules.map((module, moduleIndex) => (
            <Card key={module.id}>
              <CardBody className="grid gap-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="flex-1 truncate font-medium text-text">{module.title}</h2>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Move ${module.title} up`}
                      disabled={moduleIndex === 0 || working}
                      onClick={() =>
                        run(() => reorderModules(move(course.modules, moduleIndex, -1)))
                      }
                    >
                      ↑
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Move ${module.title} down`}
                      disabled={moduleIndex === course.modules.length - 1 || working}
                      onClick={() =>
                        run(() => reorderModules(move(course.modules, moduleIndex, 1)))
                      }
                    >
                      ↓
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Delete ${module.title}`}
                      disabled={working}
                      onClick={() => {
                        if (
                          !confirm(
                            `Delete "${module.title}" and its ${module.lessons.length} lesson(s)? This cannot be undone.`,
                          )
                        )
                          return;
                        void run(() =>
                          adminFetch(`/api/admin/modules/${module.id}`, { method: "DELETE" }),
                        );
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {module.lessons.length === 0 ? (
                  <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-sm text-subtle">
                    No lessons in this module yet.
                  </p>
                ) : (
                  <ul className="grid gap-2">
                    {module.lessons.map((lesson, lessonIndex) => (
                      <li
                        key={lesson.id}
                        className="rounded-md border border-border bg-surface-sunken/50 px-3 py-2.5"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="w-6 shrink-0 text-xs tabular-nums text-subtle">
                            {lesson.position}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-sm text-text">
                            {lesson.title}
                          </span>
                          <Badge>{lesson.type}</Badge>
                          {lesson.is_preview ? <Badge tone="accent">preview</Badge> : null}
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`Move ${lesson.title} up`}
                              disabled={lessonIndex === 0 || working}
                              onClick={() =>
                                run(() =>
                                  reorderLessons(
                                    module,
                                    move(module.lessons, lessonIndex, -1),
                                  ),
                                )
                              }
                            >
                              ↑
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`Move ${lesson.title} down`}
                              disabled={lessonIndex === module.lessons.length - 1 || working}
                              onClick={() =>
                                run(() =>
                                  reorderLessons(module, move(module.lessons, lessonIndex, 1)),
                                )
                              }
                            >
                              ↓
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`${lesson.is_preview ? "Unset" : "Set"} ${lesson.title} as preview`}
                              disabled={working}
                              onClick={() =>
                                run(() =>
                                  adminFetch(`/api/admin/lessons/${lesson.id}`, {
                                    method: "PATCH",
                                    body: { is_preview: !lesson.is_preview },
                                  }),
                                )
                              }
                            >
                              {lesson.is_preview ? "Unpreview" : "Preview"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`Delete ${lesson.title}`}
                              disabled={working}
                              onClick={() => {
                                if (!confirm(`Delete "${lesson.title}"?`)) return;
                                void run(() =>
                                  adminFetch(`/api/admin/lessons/${lesson.id}`, {
                                    method: "DELETE",
                                  }),
                                );
                              }}
                            >
                              Delete
                            </Button>
                          </div>
                        </div>

                        {lesson.type === "video" ? (
                          <div className="mt-2 pl-6">
                            <VideoUpload lesson={lesson} onChanged={() => startTransition(() => router.refresh())} />
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}

                <AddLesson moduleId={module.id} onAdded={() => startTransition(() => router.refresh())} />
              </CardBody>
            </Card>
          ))
        )}
      </div>

      <Card className="mt-6">
        <CardBody>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              if (!newModule.trim()) return;
              void run(async () => {
                await adminFetch(`/api/admin/courses/${courseId}/modules`, {
                  method: "POST",
                  body: { title: newModule.trim() },
                });
                setNewModule("");
              });
            }}
          >
            <div className="flex-1">
              <Field
                label="Add a module"
                placeholder="e.g. Getting started"
                value={newModule}
                onChange={(e) => setNewModule(e.target.value)}
              />
            </div>
            <Button type="submit" variant="secondary" disabled={!newModule.trim() || working}>
              Add module
            </Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}

function AddLesson({ moduleId, onAdded }: { moduleId: string; onAdded: () => void }) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<"video" | "text" | "quiz">("video");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-center"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!title.trim()) return;
        setBusy(true);
        try {
          await adminFetch(`/api/admin/modules/${moduleId}/lessons`, {
            method: "POST",
            body: { title: title.trim(), type },
          });
          setTitle("");
          onAdded();
        } finally {
          setBusy(false);
        }
      }}
    >
      <input
        aria-label="New lesson title"
        placeholder="New lesson title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="h-9 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-subtle hover:border-border-strong"
      />
      <select
        aria-label="Lesson type"
        value={type}
        onChange={(e) => setType(e.target.value as typeof type)}
        className="h-9 rounded-md border border-border bg-surface px-2 text-sm text-text"
      >
        <option value="video">Video</option>
        <option value="text">Text</option>
        <option value="quiz">Quiz</option>
      </select>
      <Button type="submit" variant="secondary" size="sm" loading={busy} disabled={!title.trim()}>
        Add lesson
      </Button>
    </form>
  );
}
