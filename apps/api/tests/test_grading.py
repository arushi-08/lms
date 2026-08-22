"""Grading rules, including the ones that exist to stop cheating."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.domain.grading import (
    Question,
    QuestionType,
    Response,
    grade_attempt,
    grade_question,
    normalise_text,
)

OPT_A, OPT_B, OPT_C = uuid4(), uuid4(), uuid4()


def single(correct: UUID = OPT_A, points: int = 1) -> Question:
    return Question(uuid4(), QuestionType.SINGLE, points, frozenset({correct}))


def multi(*correct: UUID, points: int = 1) -> Question:
    return Question(uuid4(), QuestionType.MULTI, points, frozenset(correct))


def short(*answers: str, points: int = 1) -> Question:
    return Question(uuid4(), QuestionType.SHORT_TEXT, points, correct_answers=answers)


class TestSingleChoice:
    def test_correct_option_scores(self) -> None:
        q = single()
        g = grade_question(q, Response(q.id, frozenset({OPT_A})))
        assert g.is_correct and g.points_awarded == 1

    def test_wrong_option_scores_nothing(self) -> None:
        q = single()
        g = grade_question(q, Response(q.id, frozenset({OPT_B})))
        assert not g.is_correct and g.points_awarded == 0

    def test_selecting_everything_does_not_pass(self) -> None:
        # Otherwise "tick every box" would beat every single-answer question.
        q = single()
        g = grade_question(q, Response(q.id, frozenset({OPT_A, OPT_B, OPT_C})))
        assert not g.is_correct

    def test_selecting_nothing_is_wrong(self) -> None:
        q = single()
        assert not grade_question(q, Response(q.id, frozenset())).is_correct


class TestMultiSelect:
    def test_exact_set_scores(self) -> None:
        q = multi(OPT_A, OPT_B)
        assert grade_question(q, Response(q.id, frozenset({OPT_A, OPT_B}))).is_correct

    def test_subset_scores_nothing(self) -> None:
        q = multi(OPT_A, OPT_B)
        assert not grade_question(q, Response(q.id, frozenset({OPT_A}))).is_correct

    def test_superset_scores_nothing(self) -> None:
        q = multi(OPT_A, OPT_B)
        g = grade_question(q, Response(q.id, frozenset({OPT_A, OPT_B, OPT_C})))
        assert not g.is_correct

    def test_question_with_no_correct_options_is_never_correct(self) -> None:
        # A misauthored question must not be satisfied by submitting nothing.
        q = multi()
        assert not grade_question(q, Response(q.id, frozenset())).is_correct


class TestShortText:
    @pytest.mark.parametrize(
        "submitted",
        ["worked example", "Worked Example", "  WORKED   example  ", "\tworked example\n"],
    )
    def test_case_and_whitespace_are_forgiven(self, submitted: str) -> None:
        q = short("worked example")
        assert grade_question(q, Response(q.id, text_answer=submitted)).is_correct

    def test_any_listed_answer_is_accepted(self) -> None:
        q = short("mark model", "the mark model")
        assert grade_question(q, Response(q.id, text_answer="The MARK Model")).is_correct

    def test_different_answer_is_wrong(self) -> None:
        q = short("worked example")
        assert not grade_question(q, Response(q.id, text_answer="something else")).is_correct

    def test_empty_answer_is_wrong(self) -> None:
        q = short("worked example")
        assert not grade_question(q, Response(q.id, text_answer="")).is_correct

    def test_unicode_forms_compare_equal(self) -> None:
        # The answer key holds "cafe" + U+0301 (decomposed); the browser sends
        # U+00E9 (composed). Different bytes, identical on screen -- a student
        # typing the "wrong" one must not be marked wrong. Written as escapes
        # because the point of the test is invisible in rendered text.
        decomposed = "cafe\u0301"
        composed = "caf\u00e9"
        assert decomposed != composed
        q = short(decomposed)
        assert grade_question(q, Response(q.id, text_answer=composed)).is_correct

    def test_normalise_collapses_internal_whitespace(self) -> None:
        assert normalise_text("  A   B \n C ") == "a b c"


class TestUnanswered:
    def test_missing_response_is_wrong_not_skipped(self) -> None:
        q = single()
        g = grade_question(q, None)
        assert not g.is_correct and g.points_awarded == 0


class TestAttemptScoring:
    def test_score_is_percentage_of_points(self) -> None:
        q1, q2 = single(points=1), single(points=3)
        result = grade_attempt(
            [q1, q2],
            [Response(q1.id, frozenset({OPT_A}))],
            passing_score=20,
        )
        assert result.points_earned == 1
        assert result.points_possible == 4
        assert result.score == Decimal("25.00")

    def test_passing_boundary_is_inclusive(self) -> None:
        q1, q2 = single(), single()
        result = grade_attempt(
            [q1, q2],
            [Response(q1.id, frozenset({OPT_A}))],
            passing_score=50,
        )
        assert result.score == Decimal("50.00")
        assert result.passed

    def test_just_below_boundary_fails(self) -> None:
        qs = [single() for _ in range(3)]
        result = grade_attempt(
            qs, [Response(qs[0].id, frozenset({OPT_A}))], passing_score=50
        )
        assert result.score == Decimal("33.33")
        assert not result.passed

    def test_responses_for_unknown_questions_are_discarded(self) -> None:
        # A student cannot pad an attempt with invented questions they "passed".
        q = single()
        result = grade_attempt(
            [q],
            [
                Response(q.id, frozenset({OPT_B})),          # real, wrong
                Response(uuid4(), frozenset({OPT_A})),       # invented, correct
                Response(uuid4(), frozenset({OPT_A})),       # invented, correct
            ],
            passing_score=50,
        )
        assert result.points_possible == 1
        assert result.points_earned == 0
        assert len(result.responses) == 1
        assert not result.passed

    def test_duplicate_response_takes_the_last(self) -> None:
        q = single()
        result = grade_attempt(
            [q],
            [Response(q.id, frozenset({OPT_B})), Response(q.id, frozenset({OPT_A}))],
            passing_score=100,
        )
        assert result.passed

    def test_every_question_appears_in_the_result(self) -> None:
        qs = [single(), multi(OPT_A), short("x")]
        result = grade_attempt(qs, [], passing_score=50)
        assert {g.question_id for g in result.responses} == {q.id for q in qs}

    def test_empty_quiz_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError, match="no questions"):
            grade_attempt([], [], passing_score=50)

    def test_rounding_is_half_up(self) -> None:
        qs = [single() for _ in range(8)]
        answered = [Response(qs[i].id, frozenset({OPT_A})) for i in range(5)]
        result = grade_attempt(qs, answered, passing_score=60)
        assert result.score == Decimal("62.50")
