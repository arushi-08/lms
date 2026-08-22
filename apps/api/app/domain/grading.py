"""Quiz grading.

Pure functions over plain values -- no database, no request context -- so the
rules can be tested exhaustively and read in one sitting.

The security-relevant property of this module is that :func:`grade_attempt`
iterates the *authoritative* question list loaded from the database and looks up
each answer, rather than iterating whatever the client submitted. A response
naming a question that is not part of the quiz is discarded rather than scored,
so a student cannot pad an attempt with invented questions they "answered
correctly". A question with no response is graded as wrong, so omitting the ones
you do not know is never better than guessing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

_WHITESPACE = re.compile(r"\s+")


class QuestionType(StrEnum):
    SINGLE = "single"
    MULTI = "multi"
    BOOLEAN = "boolean"
    SHORT_TEXT = "short_text"


@dataclass(frozen=True, slots=True)
class Question:
    """A question plus its answer key, as loaded with the service role."""

    id: UUID
    type: QuestionType
    points: int
    correct_option_ids: frozenset[UUID] = frozenset()
    correct_answers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Response:
    """One submitted answer. Comes from the client, so it is never trusted."""

    question_id: UUID
    selected_option_ids: frozenset[UUID] = frozenset()
    text_answer: str | None = None


@dataclass(frozen=True, slots=True)
class GradedResponse:
    question_id: UUID
    selected_option_ids: frozenset[UUID]
    text_answer: str | None
    is_correct: bool
    points_awarded: int


@dataclass(frozen=True, slots=True)
class AttemptResult:
    responses: tuple[GradedResponse, ...]
    points_earned: int
    points_possible: int
    score: Decimal
    passed: bool


def normalise_text(value: str) -> str:
    """Fold a free-text answer to its comparable form.

    Unicode-normalised, case-folded, trimmed, and internal whitespace collapsed,
    so "  The  Worked Example " matches "the worked example". Deliberately does
    not strip punctuation: if an answer's punctuation matters, the author should
    be able to require it by listing the exact accepted strings.
    """
    folded = unicodedata.normalize("NFKC", value).casefold().strip()
    return _WHITESPACE.sub(" ", folded)


def grade_question(question: Question, response: Response | None) -> GradedResponse:
    """Grade one question. An absent response is wrong, not skipped."""
    if response is None:
        return GradedResponse(question.id, frozenset(), None, False, 0)

    match question.type:
        case QuestionType.SINGLE | QuestionType.BOOLEAN:
            # Exactly one option, and it must be a correct one. Selecting several
            # options on a single-answer question is an invalid answer, not a
            # partially correct one.
            is_correct = (
                len(response.selected_option_ids) == 1
                and response.selected_option_ids <= question.correct_option_ids
            )
        case QuestionType.MULTI:
            # All-or-nothing: the selected set must equal the correct set. No
            # partial credit, so "select everything" scores zero rather than
            # most of the marks.
            is_correct = (
                bool(question.correct_option_ids)
                and response.selected_option_ids == question.correct_option_ids
            )
        case QuestionType.SHORT_TEXT:
            answer = response.text_answer
            is_correct = bool(answer) and normalise_text(answer) in {
                normalise_text(candidate) for candidate in question.correct_answers
            }

    return GradedResponse(
        question_id=question.id,
        selected_option_ids=response.selected_option_ids,
        text_answer=response.text_answer,
        is_correct=is_correct,
        points_awarded=question.points if is_correct else 0,
    )


def grade_attempt(
    questions: list[Question],
    responses: list[Response],
    passing_score: int,
) -> AttemptResult:
    """Grade a whole attempt against the quiz's real question list.

    ``questions`` is authoritative. Responses are indexed by question id and
    looked up; anything in ``responses`` that does not correspond to a real
    question is ignored entirely.
    """
    if not questions:
        raise ValueError("cannot grade an attempt against a quiz with no questions")

    # Last response wins if a client submits a question twice, which is the
    # forgiving reading of a double-click.
    by_question = {r.question_id: r for r in responses}

    graded = tuple(grade_question(q, by_question.get(q.id)) for q in questions)

    points_earned = sum(g.points_awarded for g in graded)
    points_possible = sum(q.points for q in questions)

    score = (
        Decimal(points_earned * 100) / Decimal(points_possible)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return AttemptResult(
        responses=graded,
        points_earned=points_earned,
        points_possible=points_possible,
        score=score,
        # >= so a passing_score of 70 means 70.00 passes.
        passed=score >= Decimal(passing_score),
    )
