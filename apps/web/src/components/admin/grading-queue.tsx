"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { adminFetch } from "@/lib/admin-client";

export type QueuedSubmission = {
  id: string;
  attempt_number: number;
  status: string;
  submitted_at: string;
  is_late: boolean;
  text_answer: string | null;
  link_url: string | null;
  score: number | null;
  passed: boolean | null;
  feedback: string | null;
  user_id: string;
  email: string;
  full_name: string | null;
  assignment_title: string;
  max_points: number;
  passing_score: number;
  course_title: string;
};

/**
 * The marking queue.
 *
 * Pass/fail is not a field here: the server derives it from the score and the
 * assignment's threshold. A grader who could set them independently could
 * record a failing score marked as passed, and the certificate rule reads the
 * verdict rather than the number.
 */
export function GradingQueue({ initial }: { initial: QueuedSubmission[] }) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight text-text sm:text-3xl">
        Marking
      </h1>
      <p className="mt-1.5 text-sm text-muted">
        {initial.length === 0
          ? "Nothing waiting."
          : `${initial.length} submission${initial.length === 1 ? "" : "s"} awaiting marking.`}
      </p>

      {error ? (
        <Alert tone="danger" className="mt-6">
          {error}
        </Alert>
      ) : null}

      <div className="mt-8 grid gap-4">
        {initial.length === 0 ? (
          <EmptyState
            title="No submissions to mark"
            description="When a student submits an assignment it appears here."
          />
        ) : (
          initial.map((submission) => (
            <SubmissionCard
              key={submission.id}
              submission={submission}
              onGraded={() => startTransition(() => router.refresh())}
              onError={setError}
            />
          ))
        )}
      </div>
    </div>
  );
}

function SubmissionCard({
  submission,
  onGraded,
  onError,
}: {
  submission: QueuedSubmission;
  onGraded: () => void;
  onError: (message: string) => void;
}) {
  const [score, setScore] = useState<number>(submission.score ?? 0);
  const [feedback, setFeedback] = useState(submission.feedback ?? "");
  const [busy, setBusy] = useState(false);

  const willPass = score >= submission.passing_score;

  return (
    <Card>
      <CardBody className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-text">
            {submission.full_name ?? submission.email}
          </span>
          <span className="text-xs text-subtle">{submission.email}</span>
          {submission.is_late ? <Badge tone="warning">Late</Badge> : null}
          <Badge>Attempt {submission.attempt_number}</Badge>
        </div>
        <p className="text-xs text-subtle">
          {submission.course_title} · {submission.assignment_title} · pass mark{" "}
          {submission.passing_score}%
        </p>

        {submission.text_answer ? (
          <p className="max-h-64 overflow-auto whitespace-pre-line rounded-md bg-surface-sunken p-3 text-sm text-muted">
            {submission.text_answer}
          </p>
        ) : null}
        {submission.link_url ? (
          <a
            href={submission.link_url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-sm font-medium text-accent hover:underline"
          >
            {submission.link_url}
          </a>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-[8rem_1fr_auto] sm:items-end">
          <Field
            label="Score %"
            type="number"
            min={0}
            max={100}
            value={score}
            onChange={(e) => setScore(Number(e.target.value))}
            hint={willPass ? "Will pass" : "Will not pass"}
          />
          <div className="grid gap-1.5">
            <label
              htmlFor={`feedback-${submission.id}`}
              className="text-sm font-medium text-text"
            >
              Feedback
            </label>
            <textarea
              id={`feedback-${submission.id}`}
              rows={3}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="What was good, and what to work on."
              className="w-full rounded-md border border-border bg-surface p-3 text-sm text-text placeholder:text-subtle"
            />
          </div>
          <Button
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await adminFetch(`/api/admin/submissions/${submission.id}/grade`, {
                  method: "POST",
                  body: { score, feedback: feedback.trim() || null },
                });
                onGraded();
              } catch (cause) {
                onError(
                  cause instanceof Error ? cause.message : "Could not save the mark.",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            Save mark
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
