"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { AssignmentView } from "@/components/learn/assignment-view";
import { QuizRunner } from "@/components/learn/quiz-runner";
import { VideoPlayer } from "@/components/learn/video-player";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
import { adminFetch } from "@/lib/admin-client";
import type { Assignment, Quiz } from "@/lib/api";

type Lesson = {
  id: string;
  title: string;
  type: string;
  position: number;
  is_preview: boolean;
  duration_seconds?: number | null;
};

export function LessonView({
  courseSlug,
  lessons,
  currentIndex,
  quiz = null,
  assignment = null,
  assessmentError = null,
}: {
  courseSlug: string;
  lessons: Lesson[];
  currentIndex: number;
  quiz?: Quiz | null;
  assignment?: Assignment | null;
  assessmentError?: string | null;
}) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [percent, setPercent] = useState<number | null>(null);
  const [marking, setMarking] = useState(false);
  const [markError, setMarkError] = useState<string | null>(null);
  const lesson = lessons[currentIndex];
  const previous = currentIndex > 0 ? lessons[currentIndex - 1] : undefined;
  const next = currentIndex < lessons.length - 1 ? lessons[currentIndex + 1] : undefined;

  if (!lesson) return null;

  // Quizzes and assignments complete by being passed. Videos complete by being
  // watched -- but only once their length is known, so a lesson uploaded before
  // durations were recorded is not stranded.
  const canMarkComplete =
    lesson.type === "text" ||
    (lesson.type === "video" && !lesson.duration_seconds);

  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[1fr_18rem]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight text-text">
            {lesson.title}
          </h1>
          {lesson.is_preview ? <Badge tone="accent">Free preview</Badge> : null}
        </div>

        <div className="mt-4">
          {lesson.type === "video" ? (
            <VideoPlayer
              lessonId={lesson.id}
              onProgress={(p) => setPercent(p)}
            />
          ) : assessmentError ? (
            <EmptyState title="This lesson could not be loaded" description={assessmentError} />
          ) : lesson.type === "quiz" ? (
            quiz ? (
              <QuizRunner quiz={quiz} />
            ) : (
              <EmptyState
                title="No quiz here yet"
                description="An admin can add questions from the course editor."
              />
            )
          ) : lesson.type === "assignment" ? (
            assignment ? (
              <AssignmentView assignment={assignment} />
            ) : (
              <EmptyState
                title="No assignment here yet"
                description="An admin can write the brief from the course editor."
              />
            )
          ) : (
            <EmptyState
              title="Written lesson"
              description="Text lessons render here once the editor is wired up."
            />
          )}
        </div>

        {canMarkComplete ? (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              size="sm"
              loading={marking}
              onClick={async () => {
                setMarking(true);
                setMarkError(null);
                try {
                  const result = await adminFetch<{ course_progress_percent: number }>(
                    `/api/lessons/${lesson.id}/complete`,
                    { method: "POST" },
                  );
                  setPercent(result.course_progress_percent);
                  startTransition(() => router.refresh());
                } catch (cause) {
                  setMarkError(
                    cause instanceof Error ? cause.message : "Could not save that.",
                  );
                } finally {
                  setMarking(false);
                }
              }}
            >
              Mark as complete
            </Button>
            {markError ? (
              <span className="text-sm text-danger">{markError}</span>
            ) : null}
          </div>
        ) : null}

        {percent !== null ? (
          <div className="mt-4 flex items-center gap-3">
            <Progress value={percent} label="Course progress" className="max-w-xs" />
            <span className="text-xs tabular-nums text-subtle">
              {Math.round(percent)}% of the course
            </span>
          </div>
        ) : null}

        <div className="mt-6 flex items-center justify-between gap-3">
          {previous ? (
            <Link href={`/learn/${courseSlug}/${previous.id}`}>
              <Button variant="secondary" size="sm">
                ← {previous.title}
              </Button>
            </Link>
          ) : (
            <span />
          )}
          {next ? (
            <Link href={`/learn/${courseSlug}/${next.id}`}>
              <Button size="sm">{next.title} →</Button>
            </Link>
          ) : null}
        </div>
      </div>

      <aside>
        <Card>
          <CardBody className="p-3">
            <p className="px-2 pb-2 text-xs font-medium uppercase tracking-wide text-subtle">
              Lessons
            </p>
            <ol className="grid gap-0.5">
              {lessons.map((item, i) => (
                <li key={item.id}>
                  <Link
                    href={`/learn/${courseSlug}/${item.id}`}
                    aria-current={i === currentIndex ? "page" : undefined}
                    className={
                      "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors " +
                      (i === currentIndex
                        ? "bg-accent-subtle font-medium text-accent"
                        : "text-muted hover:bg-surface-hover hover:text-text")
                    }
                  >
                    <span className="w-4 shrink-0 text-xs tabular-nums opacity-70">
                      {item.position}
                    </span>
                    <span className="truncate">{item.title}</span>
                  </Link>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      </aside>
    </div>
  );
}
