"""Progress accrual, with emphasis on what a hostile client can claim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.progress import (
    FIRST_HEARTBEAT_ALLOWANCE_SECONDS,
    MAX_CREDIT_PER_HEARTBEAT_SECONDS,
    Heartbeat,
    ProgressState,
    apply_heartbeat,
    completion_target,
    course_progress_percent,
    is_course_complete,
    mark_complete,
    resolve_expiry,
)

T0 = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
LESSON = 600  # ten minutes


def beat(watched: int, at: datetime, position: int | None = None) -> Heartbeat:
    return Heartbeat(watched_seconds=watched, position_seconds=position or watched, at=at)


class TestClamping:
    def test_first_heartbeat_is_capped_by_the_opening_allowance(self) -> None:
        # The classic attack: one request claiming the whole lesson.
        update = apply_heartbeat(
            ProgressState(),
            beat(99_999, T0),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.credited_seconds == FIRST_HEARTBEAT_ALLOWANCE_SECONDS
        assert update.watched_seconds == FIRST_HEARTBEAT_ALLOWANCE_SECONDS
        assert update.clamped
        assert not update.completed

    def test_normal_playback_is_credited_in_full(self) -> None:
        state = ProgressState(watched_seconds=100, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(120, T0 + timedelta(seconds=20)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.credited_seconds == 20
        assert not update.clamped

    def test_double_speed_playback_is_not_treated_as_cheating(self) -> None:
        # 40s of content in 20s of wall clock is exactly what 2x looks like.
        state = ProgressState(watched_seconds=100, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(140, T0 + timedelta(seconds=20)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.credited_seconds == 40
        assert not update.clamped

    def test_beyond_max_playback_rate_is_clamped(self) -> None:
        # 100s of content in 20s is 5x, which the player cannot produce.
        state = ProgressState(watched_seconds=100, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(200, T0 + timedelta(seconds=20)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.credited_seconds == 50  # 20 * 2.0 * 1.25
        assert update.clamped

    def test_long_idle_gap_does_not_bank_credit(self) -> None:
        # Open the tab, wait an hour, claim everything. The per-beat ceiling is
        # what stops elapsed time alone from authorising the claim.
        state = ProgressState(watched_seconds=0, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(LESSON, T0 + timedelta(hours=1)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.credited_seconds == MAX_CREDIT_PER_HEARTBEAT_SECONDS
        assert not update.completed

    def test_replayed_or_skewed_beat_credits_nothing(self) -> None:
        state = ProgressState(watched_seconds=100, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(500, T0 - timedelta(seconds=30)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.credited_seconds == 0
        assert update.watched_seconds == 100

    def test_rewinding_never_subtracts_watched_time(self) -> None:
        state = ProgressState(watched_seconds=300, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(50, T0 + timedelta(seconds=20), position=50),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.watched_seconds == 300
        assert update.last_position_seconds == 50

    def test_watched_never_exceeds_duration(self) -> None:
        state = ProgressState(watched_seconds=590, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(700, T0 + timedelta(seconds=30)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.watched_seconds == LESSON

    def test_position_is_clamped_to_duration(self) -> None:
        update = apply_heartbeat(
            ProgressState(last_heartbeat_at=T0),
            beat(10, T0 + timedelta(seconds=10), position=99_999),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.last_position_seconds == LESSON

    def test_negative_position_is_floored(self) -> None:
        update = apply_heartbeat(
            ProgressState(last_heartbeat_at=T0),
            beat(10, T0 + timedelta(seconds=10), position=-5),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.last_position_seconds == 0


class TestCompletion:
    def test_completes_at_the_threshold(self) -> None:
        state = ProgressState(watched_seconds=500, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(540, T0 + timedelta(seconds=40)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.watched_seconds == 540
        assert update.completed
        assert update.completed_at == T0 + timedelta(seconds=40)

    def test_does_not_complete_below_the_threshold(self) -> None:
        state = ProgressState(watched_seconds=490, last_heartbeat_at=T0)
        update = apply_heartbeat(
            state,
            beat(530, T0 + timedelta(seconds=40)),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert not update.completed

    def test_completion_is_monotonic(self) -> None:
        done = ProgressState(
            watched_seconds=600, completed=True, completed_at=T0, last_heartbeat_at=T0
        )
        update = apply_heartbeat(
            done,
            beat(5, T0 + timedelta(seconds=20), position=5),
            duration_seconds=LESSON,
            threshold_percent=90,
        )
        assert update.completed
        assert update.completed_at == T0

    def test_unknown_duration_never_auto_completes(self) -> None:
        update = apply_heartbeat(
            ProgressState(last_heartbeat_at=T0),
            beat(10_000, T0 + timedelta(seconds=60)),
            duration_seconds=None,
            threshold_percent=90,
        )
        assert not update.completed

    def test_mark_complete_is_explicit_and_idempotent(self) -> None:
        first = mark_complete(ProgressState(), T0)
        assert first.completed and first.completed_at == T0
        later = mark_complete(
            ProgressState(completed=True, completed_at=T0), T0 + timedelta(days=1)
        )
        assert later.completed_at == T0

    @pytest.mark.parametrize(
        ("duration", "threshold", "expected"),
        [(600, 90, 540), (100, 90, 90), (7, 90, 7), (1, 90, 1), (600, 100, 600)],
    )
    def test_completion_target_rounds_up_but_never_past_the_end(
        self, duration: int, threshold: int, expected: int
    ) -> None:
        assert completion_target(duration, threshold) == expected


class TestCourseLevelRules:
    def test_progress_percentage(self) -> None:
        assert course_progress_percent(4, 1) == 25.0
        assert course_progress_percent(3, 3) == 100.0

    def test_empty_course_is_zero_percent_not_complete(self) -> None:
        assert course_progress_percent(0, 0) == 0.0
        assert not is_course_complete(
            required_total=0, required_completed=0, quizzes_total=0, quizzes_passed=0
        )

    def test_progress_cannot_exceed_one_hundred(self) -> None:
        assert course_progress_percent(2, 5) == 100.0

    def test_certificate_needs_lessons_and_quizzes(self) -> None:
        assert is_course_complete(
            required_total=5, required_completed=5, quizzes_total=2, quizzes_passed=2
        )

    def test_unpassed_quiz_blocks_the_certificate(self) -> None:
        assert not is_course_complete(
            required_total=5, required_completed=5, quizzes_total=2, quizzes_passed=1
        )

    def test_unwatched_lesson_blocks_the_certificate(self) -> None:
        assert not is_course_complete(
            required_total=5, required_completed=4, quizzes_total=2, quizzes_passed=2
        )


class TestExpiryResolution:
    def test_lifetime_has_no_expiry(self) -> None:
        assert resolve_expiry(access_type="lifetime", access_days=None, enrolled_at=T0) is None

    def test_time_limited_resolves_to_an_instant(self) -> None:
        assert resolve_expiry(
            access_type="time_limited", access_days=365, enrolled_at=T0
        ) == T0 + timedelta(days=365)

    def test_time_limited_without_days_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="access_days"):
            resolve_expiry(access_type="time_limited", access_days=None, enrolled_at=T0)
