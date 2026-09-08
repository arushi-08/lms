"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { adminFetch } from "@/lib/admin-client";

type QuestionType = "single" | "multi" | "boolean" | "short_text";

type EditableOption = { text: string; is_correct: boolean };

type EditableQuestion = {
  id: string | null;
  type: QuestionType;
  prompt: string;
  points: number;
  options: EditableOption[];
  correct_answers: string[] | null;
};

const BLANK: EditableQuestion = {
  id: null,
  type: "single",
  prompt: "",
  points: 1,
  options: [
    { text: "", is_correct: true },
    { text: "", is_correct: false },
  ],
  correct_answers: null,
};

/**
 * Authoring for the two assessment lesson types, inline in the course editor.
 *
 * The answer key lives here and nowhere else in the frontend: the student-side
 * quiz payload is assembled by the API without those columns, so there is no
 * shared component that could accidentally render one in the wrong context.
 */
export function AssessmentEditor({
  lessonId,
  lessonType,
  onSaved,
}: {
  lessonId: string;
  lessonType: "quiz" | "assignment";
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Quiz state
  const [quizTitle, setQuizTitle] = useState("Knowledge check");
  const [passing, setPassing] = useState(70);
  const [question, setQuestion] = useState<EditableQuestion>(BLANK);

  // Assignment state
  const [title, setTitle] = useState("Assignment");
  const [instructions, setInstructions] = useState("");
  const [allowLink, setAllowLink] = useState(false);
  const [isGraded, setIsGraded] = useState(true);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await action();
      setNote(success);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        {lessonType === "quiz" ? "Edit quiz" : "Edit assignment"}
      </Button>
    );
  }

  return (
    <div className="mt-2 grid gap-3 rounded-md border border-border bg-surface p-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-text">
          {lessonType === "quiz" ? "Quiz" : "Assignment"}
        </p>
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>

      {error ? <Alert tone="danger">{error}</Alert> : null}
      {note ? <Alert tone="success">{note}</Alert> : null}

      {lessonType === "quiz" ? (
        <>
          <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
            <Field
              label="Quiz title"
              value={quizTitle}
              onChange={(e) => setQuizTitle(e.target.value)}
            />
            <Field
              label="Pass mark %"
              type="number"
              min={1}
              max={100}
              value={passing}
              onChange={(e) => setPassing(Number(e.target.value))}
            />
          </div>
          <div>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() =>
                run(
                  () =>
                    adminFetch(`/api/admin/lessons/${lessonId}/quiz`, {
                      method: "PUT",
                      body: { title: quizTitle, passing_score: passing },
                    }),
                  "Quiz settings saved.",
                )
              }
            >
              Save quiz settings
            </Button>
          </div>

          <hr className="border-border" />

          <p className="text-sm font-medium text-text">Add a question</p>
          <div className="grid gap-3">
            <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
              <Field
                label="Prompt"
                value={question.prompt}
                onChange={(e) => setQuestion({ ...question, prompt: e.target.value })}
              />
              <div className="grid gap-1.5">
                <label htmlFor="qtype" className="text-sm font-medium text-text">
                  Type
                </label>
                <select
                  id="qtype"
                  value={question.type}
                  onChange={(e) => {
                    const type = e.target.value as QuestionType;
                    setQuestion({
                      ...question,
                      type,
                      options:
                        type === "boolean"
                          ? [
                              { text: "True", is_correct: true },
                              { text: "False", is_correct: false },
                            ]
                          : BLANK.options,
                      correct_answers: type === "short_text" ? [""] : null,
                    });
                  }}
                  className="h-10 rounded-md border border-border bg-surface px-2 text-sm text-text"
                >
                  <option value="single">Single choice</option>
                  <option value="multi">Multiple choice</option>
                  <option value="boolean">True / false</option>
                  <option value="short_text">Short text</option>
                </select>
              </div>
            </div>

            {question.type === "short_text" ? (
              <Field
                label="Accepted answer"
                value={question.correct_answers?.[0] ?? ""}
                onChange={(e) =>
                  setQuestion({ ...question, correct_answers: [e.target.value] })
                }
                hint="Case and surrounding spaces are ignored when grading."
              />
            ) : (
              <div className="grid gap-2">
                <p className="text-sm font-medium text-text">
                  Options{" "}
                  <span className="font-normal text-subtle">
                    (tick the correct one
                    {question.type === "multi" ? "s" : ""})
                  </span>
                </p>
                {question.options.map((option, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input
                      type={question.type === "multi" ? "checkbox" : "radio"}
                      name="correct-option"
                      aria-label={`Option ${i + 1} is correct`}
                      checked={option.is_correct}
                      onChange={() =>
                        setQuestion({
                          ...question,
                          options: question.options.map((o, j) =>
                            question.type === "multi"
                              ? j === i
                                ? { ...o, is_correct: !o.is_correct }
                                : o
                              : { ...o, is_correct: j === i },
                          ),
                        })
                      }
                      className="size-4 accent-[var(--accent)]"
                    />
                    <input
                      aria-label={`Option ${i + 1} text`}
                      value={option.text}
                      placeholder={`Option ${i + 1}`}
                      onChange={(e) =>
                        setQuestion({
                          ...question,
                          options: question.options.map((o, j) =>
                            j === i ? { ...o, text: e.target.value } : o,
                          ),
                        })
                      }
                      className="h-9 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-subtle"
                    />
                  </div>
                ))}
                {question.type !== "boolean" ? (
                  <div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setQuestion({
                          ...question,
                          options: [...question.options, { text: "", is_correct: false }],
                        })
                      }
                    >
                      Add option
                    </Button>
                  </div>
                ) : null}
              </div>
            )}

            <div>
              <Button
                size="sm"
                loading={busy}
                disabled={!question.prompt.trim()}
                onClick={() =>
                  run(async () => {
                    const quiz = await adminFetch<{ id: string }>(
                      `/api/admin/lessons/${lessonId}/quiz`,
                      {
                        method: "PUT",
                        body: { title: quizTitle, passing_score: passing },
                      },
                    );
                    await adminFetch(`/api/admin/quizzes/${quiz.id}/questions`, {
                      method: "PUT",
                      body: {
                        type: question.type,
                        prompt: question.prompt,
                        points: question.points,
                        correct_answers: question.correct_answers,
                        options:
                          question.type === "short_text" ? [] : question.options,
                      },
                    });
                    setQuestion(BLANK);
                  }, "Question added.")
                }
              >
                Add question
              </Button>
            </div>
          </div>
        </>
      ) : (
        <div className="grid gap-3">
          <Field label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <div className="grid gap-1.5">
            <label htmlFor="instructions" className="text-sm font-medium text-text">
              Instructions
            </label>
            <textarea
              id="instructions"
              rows={5}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="What should the student produce?"
              className="w-full rounded-md border border-border bg-surface p-3 text-sm text-text placeholder:text-subtle"
            />
          </div>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm text-text">
              <input
                type="checkbox"
                checked={allowLink}
                onChange={(e) => setAllowLink(e.target.checked)}
                className="size-4 accent-[var(--accent)]"
              />
              Accept a link to work hosted elsewhere
            </label>
            <label className="flex items-center gap-2 text-sm text-text">
              <input
                type="checkbox"
                checked={isGraded}
                onChange={(e) => setIsGraded(e.target.checked)}
                className="size-4 accent-[var(--accent)]"
              />
              Must be passed for the certificate
            </label>
          </div>
          <div>
            <Button
              size="sm"
              loading={busy}
              disabled={!instructions.trim()}
              onClick={() =>
                run(
                  () =>
                    adminFetch(`/api/admin/lessons/${lessonId}/assignment`, {
                      method: "PUT",
                      body: {
                        title,
                        instructions,
                        allow_link: allowLink,
                        is_graded: isGraded,
                      },
                    }),
                  "Assignment saved.",
                )
              }
            >
              Save assignment
            </Button>
          </div>
          {!isGraded ? (
            <Badge tone="accent">
              Submitting is enough — this will not hold up a certificate
            </Badge>
          ) : null}
        </div>
      )}
    </div>
  );
}
