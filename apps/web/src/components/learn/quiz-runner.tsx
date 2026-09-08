"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { adminFetch } from "@/lib/admin-client";
import type { AttemptResult, Quiz } from "@/lib/api";

/**
 * Takes a quiz.
 *
 * Grading happens entirely on the server; nothing here knows a correct answer,
 * and the result deliberately reports only which questions were right. With
 * unlimited retries, echoing the correct options back would let a student walk
 * to a perfect score one submission at a time.
 */
export function QuizRunner({ quiz }: { quiz: Quiz }) {
  const [answers, setAnswers] = useState<Record<string, Set<string>>>({});
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const exhausted =
    quiz.attempts_remaining !== null && quiz.attempts_remaining <= 0 && !result;

  function toggle(questionId: string, optionId: string, single: boolean) {
    setAnswers((current) => {
      const chosen = new Set(current[questionId] ?? []);
      if (single) {
        chosen.clear();
        chosen.add(optionId);
      } else if (chosen.has(optionId)) {
        chosen.delete(optionId);
      } else {
        chosen.add(optionId);
      }
      return { ...current, [questionId]: chosen };
    });
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await adminFetch<AttemptResult>(`/api/quizzes/${quiz.quiz_id}/attempts`, {
          method: "POST",
          body: {
            responses: quiz.questions.map((question) => ({
              question_id: question.id,
              selected_option_ids: [...(answers[question.id] ?? [])],
              text_answer: texts[question.id] ?? null,
            })),
          },
        }),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not submit the quiz.");
    } finally {
      setBusy(false);
    }
  }

  if (quiz.questions.length === 0) {
    return (
      <EmptyState
        title="This quiz has no questions yet"
        description="It will appear here once questions are added."
      />
    );
  }

  const verdictFor = (questionId: string) =>
    result?.results.find((r) => r.question_id === questionId);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold tracking-tight text-text">{quiz.title}</h2>
        <Badge>Pass mark {quiz.passing_score}%</Badge>
        {quiz.attempts_remaining !== null ? (
          <Badge tone={quiz.attempts_remaining > 0 ? "neutral" : "danger"}>
            {quiz.attempts_remaining} attempt
            {quiz.attempts_remaining === 1 ? "" : "s"} left
          </Badge>
        ) : null}
      </div>

      {result ? (
        <Alert tone={result.passed ? "success" : "warning"}>
          {result.passed ? "Passed" : "Not passed"} — {result.score}% (
          {result.points_earned} of {result.points_possible} points).{" "}
          {result.passed
            ? "This lesson is complete."
            : "Review the questions marked incorrect and try again."}
        </Alert>
      ) : null}

      {error ? <Alert tone="danger">{error}</Alert> : null}

      {quiz.questions.map((question, index) => {
        const verdict = verdictFor(question.id);
        return (
          <Card key={question.id}>
            <CardBody className="grid gap-3">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 text-xs tabular-nums text-subtle">
                  {index + 1}
                </span>
                <p className="flex-1 font-medium text-text">{question.prompt}</p>
                {verdict ? (
                  <Badge tone={verdict.is_correct ? "success" : "danger"}>
                    {verdict.is_correct ? "Correct" : "Incorrect"}
                  </Badge>
                ) : null}
              </div>

              {question.type === "short_text" ? (
                <input
                  aria-label={question.prompt}
                  value={texts[question.id] ?? ""}
                  disabled={Boolean(result)}
                  onChange={(e) =>
                    setTexts((t) => ({ ...t, [question.id]: e.target.value }))
                  }
                  placeholder="Your answer"
                  className="h-10 rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-subtle disabled:opacity-60"
                />
              ) : (
                <ul className="grid gap-1.5">
                  {question.options.map((option) => {
                    const single = question.type !== "multi";
                    const checked = answers[question.id]?.has(option.id) ?? false;
                    return (
                      <li key={option.id}>
                        <label
                          className={
                            "flex cursor-pointer items-center gap-2.5 rounded-md border px-3 py-2 text-sm transition-colors " +
                            (checked
                              ? "border-accent-border bg-accent-subtle text-text"
                              : "border-border hover:bg-surface-hover")
                          }
                        >
                          <input
                            type={single ? "radio" : "checkbox"}
                            name={question.id}
                            checked={checked}
                            disabled={Boolean(result)}
                            onChange={() => toggle(question.id, option.id, single)}
                            className="size-4 accent-[var(--accent)]"
                          />
                          <span>{option.text}</span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardBody>
          </Card>
        );
      })}

      <div className="flex items-center gap-3">
        {result ? (
          <Button
            variant="secondary"
            onClick={() => {
              setResult(null);
              setAnswers({});
              setTexts({});
            }}
            disabled={exhausted}
          >
            Try again
          </Button>
        ) : (
          <Button loading={busy} onClick={() => void submit()} disabled={exhausted}>
            Submit answers
          </Button>
        )}
        {exhausted ? (
          <span className="text-sm text-muted">No attempts remaining.</span>
        ) : null}
      </div>
    </div>
  );
}
