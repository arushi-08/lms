"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { adminFetch } from "@/lib/admin-client";
import type { Assignment } from "@/lib/api";

function when(value: string) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Submit work and read the feedback on it.
 *
 * Resubmission creates a new attempt rather than replacing the last one, so a
 * student can still see the work a piece of feedback was written about.
 */
export function AssignmentView({ assignment }: { assignment: Assignment }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [link, setLink] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const latest = assignment.submissions[0];
  const overdue =
    assignment.due_at !== null && new Date(assignment.due_at) < new Date();
  const closed = overdue && !assignment.allow_late;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminFetch(`/api/assignments/${assignment.assignment_id}/submissions`, {
        method: "POST",
        body: {
          text_answer: text.trim() || null,
          link_url: link.trim() || null,
        },
      });
      setText("");
      setLink("");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not submit.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold tracking-tight text-text">
            {assignment.title}
          </h2>
          {assignment.is_graded ? (
            <Badge>Pass mark {assignment.passing_score}%</Badge>
          ) : (
            <Badge tone="accent">Not graded</Badge>
          )}
          {assignment.due_at ? (
            <Badge tone={overdue ? "warning" : "neutral"}>
              Due {when(assignment.due_at)}
            </Badge>
          ) : null}
        </div>
        <p className="mt-3 whitespace-pre-line text-sm text-muted">
          {assignment.instructions}
        </p>
      </div>

      {assignment.submissions.length > 0 ? (
        <section className="grid gap-3">
          <h3 className="text-sm font-medium text-text">Your submissions</h3>
          {assignment.submissions.map((submission) => (
            <Card key={submission.id}>
              <CardBody className="grid gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-text">
                    Attempt {submission.attempt_number}
                  </span>
                  <span className="text-xs text-subtle">
                    {when(submission.submitted_at)}
                  </span>
                  {submission.is_late ? <Badge tone="warning">Late</Badge> : null}
                  {submission.status === "graded" ? (
                    <Badge tone={submission.passed ? "success" : "danger"}>
                      {submission.score}% · {submission.passed ? "Passed" : "Not passed"}
                    </Badge>
                  ) : (
                    <Badge>Awaiting grading</Badge>
                  )}
                </div>
                {submission.text_answer ? (
                  <p className="whitespace-pre-line rounded-md bg-surface-sunken p-3 text-sm text-muted">
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
                {submission.feedback ? (
                  <div className="rounded-md border-l-2 border-accent bg-accent-subtle/40 p-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-subtle">
                      Feedback
                    </p>
                    <p className="mt-1 whitespace-pre-line text-sm text-text">
                      {submission.feedback}
                    </p>
                  </div>
                ) : null}
              </CardBody>
            </Card>
          ))}
        </section>
      ) : null}

      {closed ? (
        <Alert tone="warning">
          The deadline has passed and this assignment no longer accepts submissions.
        </Alert>
      ) : (
        <Card>
          <CardBody>
            <form onSubmit={submit} className="grid gap-4">
              <h3 className="text-sm font-medium text-text">
                {latest ? "Submit another attempt" : "Your submission"}
              </h3>
              {error ? <Alert tone="danger">{error}</Alert> : null}
              {overdue ? (
                <Alert tone="warning">
                  Past the deadline — this will be marked late.
                </Alert>
              ) : null}

              {assignment.allow_text ? (
                <div className="grid gap-1.5">
                  <label
                    htmlFor="assignment-text"
                    className="text-sm font-medium text-text"
                  >
                    Your answer
                  </label>
                  <textarea
                    id="assignment-text"
                    rows={8}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Write your response here."
                    className="w-full rounded-md border border-border bg-surface p-3 text-sm text-text placeholder:text-subtle hover:border-border-strong"
                  />
                </div>
              ) : null}

              {assignment.allow_link ? (
                <Field
                  label="Link to your work"
                  type="url"
                  value={link}
                  onChange={(e) => setLink(e.target.value)}
                  placeholder="https://"
                  hint="A document, video or repository."
                />
              ) : null}

              <div>
                <Button
                  type="submit"
                  loading={busy}
                  disabled={!text.trim() && !link.trim()}
                >
                  Submit
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
