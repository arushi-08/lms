"use client";

import Link from "next/link";
import { useState } from "react";

import { VideoPlayer } from "@/components/learn/video-player";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";

type Lesson = {
  id: string;
  title: string;
  type: string;
  position: number;
  is_preview: boolean;
};

export function LessonView({
  courseSlug,
  lessons,
  currentIndex,
}: {
  courseSlug: string;
  lessons: Lesson[];
  currentIndex: number;
}) {
  const [percent, setPercent] = useState<number | null>(null);
  const lesson = lessons[currentIndex];
  const previous = currentIndex > 0 ? lessons[currentIndex - 1] : undefined;
  const next = currentIndex < lessons.length - 1 ? lessons[currentIndex + 1] : undefined;

  if (!lesson) return null;

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
          ) : lesson.type === "quiz" ? (
            <EmptyState
              title="Quiz"
              description="Quizzes are coming next. The grading behind them is already built and tested."
            />
          ) : (
            <EmptyState
              title="Written lesson"
              description="Text lessons render here once the editor is wired up."
            />
          )}
        </div>

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
