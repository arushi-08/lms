"""Progress accrual and course completion.

Pure functions, no I/O.

Why clamping exists
-------------------
``watched_seconds`` is reported by the browser, and the browser is under the
student's control. Without a bound, one crafted request claiming
``watched_seconds = 99999`` completes a lesson, and enough of those mint a
certificate. So the server credits watch time itself, and treats the client's
number as a *claim* to be capped rather than a value to store.

Why the cap is not simply wall-clock time
-----------------------------------------
Players offer 1.5x and 2x speed, and a student watching at 2x genuinely consumes
two seconds of content per second of real time. Clamping to elapsed wall-clock
would mark honest fast-watchers as cheats. The allowance is therefore
``elapsed x MAX_PLAYBACK_RATE x TOLERANCE``, which admits every legitimate
playback speed the player offers plus jitter.

Why there is also a per-heartbeat ceiling
-----------------------------------------
Elapsed-time-only would leave a gap: open a lesson, wait an hour, then send a
single heartbeat claiming the whole thing. An hour of elapsed time would
authorise it. ``MAX_CREDIT_PER_HEARTBEAT`` caps any single beat, so credit
accrues only through a sustained series of them -- finishing a ten-minute lesson
takes at least five heartbeats, no matter how long the tab sat open.

None of this stops a determined attacker scripting heartbeats on a timer. It is
not meant to: it makes forging completion cost roughly as much real time as
watching, which is the point where cheating stops being worth it. Anything
stronger (focus tracking, interaction challenges) buys little and annoys honest
students.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Fastest speed the player offers. Keep in step with the frontend's speed menu.
MAX_PLAYBACK_RATE = 2.0
#: Slack for timer jitter, buffering and a late-delivered beat.
TOLERANCE = 1.25
#: Credit granted on the first beat of a session, when there is no previous
#: timestamp to measure against. Covers a lesson that buffered before beat one.
FIRST_HEARTBEAT_ALLOWANCE_SECONDS = 60
#: Hard ceiling on any single heartbeat, whatever the elapsed time.
MAX_CREDIT_PER_HEARTBEAT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class ProgressState:
    """What the database currently holds for this user and lesson."""

    watched_seconds: int = 0
    last_position_seconds: int = 0
    completed: bool = False
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """What the client claims. Every field is untrusted."""

    watched_seconds: int
    position_seconds: int
    at: datetime


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    watched_seconds: int
    last_position_seconds: int
    completed: bool
    completed_at: datetime | None
    last_heartbeat_at: datetime
    credited_seconds: int
    #: True when the claim exceeded the allowance and was cut down. Worth
    #: logging: a trickle is jitter, a pattern is someone poking at the API.
    clamped: bool


def _allowance(state: ProgressState, now: datetime) -> int:
    if state.last_heartbeat_at is None:
        return FIRST_HEARTBEAT_ALLOWANCE_SECONDS

    elapsed = (now - state.last_heartbeat_at).total_seconds()
    if elapsed <= 0:
        # Clock skew, a replayed beat, or two beats in the same instant.
        # Credit nothing rather than guessing.
        return 0

    return min(
        int(elapsed * MAX_PLAYBACK_RATE * TOLERANCE),
        MAX_CREDIT_PER_HEARTBEAT_SECONDS,
    )


def completion_target(duration_seconds: int, threshold_percent: int) -> int:
    """Watch seconds needed to complete a lesson of this length.

    Rounded up, then held to at most the lesson duration so a rounding artefact
    can never demand more seconds than the video contains.
    """
    target = math.ceil(duration_seconds * threshold_percent / 100)
    return min(target, duration_seconds)


def apply_heartbeat(
    state: ProgressState,
    heartbeat: Heartbeat,
    *,
    duration_seconds: int | None,
    threshold_percent: int,
) -> ProgressUpdate:
    """Fold one heartbeat into stored progress, crediting only what is earned."""
    claimed_delta = max(0, heartbeat.watched_seconds - state.watched_seconds)
    allowance = _allowance(state, heartbeat.at)
    credited = min(claimed_delta, allowance)

    watched = state.watched_seconds + credited
    if duration_seconds is not None:
        watched = min(watched, duration_seconds)

    position = max(0, heartbeat.position_seconds)
    if duration_seconds is not None:
        position = min(position, duration_seconds)

    # Completion is monotonic. Re-watching a finished lesson, or a later beat
    # arriving with a lower claim, must never un-complete it.
    completed = state.completed
    completed_at = state.completed_at
    if (
        not completed
        and duration_seconds
        and watched >= completion_target(duration_seconds, threshold_percent)
    ):
        completed = True
        completed_at = heartbeat.at

    return ProgressUpdate(
        watched_seconds=watched,
        last_position_seconds=position,
        completed=completed,
        completed_at=completed_at,
        last_heartbeat_at=heartbeat.at,
        credited_seconds=credited,
        clamped=claimed_delta > credited,
    )


def mark_complete(state: ProgressState, now: datetime) -> ProgressUpdate:
    """Explicit completion, for text lessons and for videos of unknown length."""
    return ProgressUpdate(
        watched_seconds=state.watched_seconds,
        last_position_seconds=state.last_position_seconds,
        completed=True,
        completed_at=state.completed_at or now,
        last_heartbeat_at=state.last_heartbeat_at or now,
        credited_seconds=0,
        clamped=False,
    )


def course_progress_percent(required_total: int, required_completed: int) -> float:
    """Percentage for the dashboard, over required lessons only.

    A course with no required lessons reads as 0%, not 100%: an empty course is
    not an achievement, and reporting it as finished would issue certificates
    for nothing.
    """
    if required_total <= 0:
        return 0.0
    ratio = min(required_completed, required_total) / required_total
    return round(ratio * 100, 2)


def is_course_complete(
    *,
    required_total: int,
    required_completed: int,
    quizzes_total: int,
    quizzes_passed: int,
) -> bool:
    """The certificate rule: every required lesson done, every quiz passed.

    Confirmed decision 4. A course with no required lessons never completes, for
    the same reason as above.
    """
    if required_total <= 0:
        return False
    return required_completed >= required_total and quizzes_passed >= quizzes_total


def resolve_expiry(
    *,
    access_type: str,
    access_days: int | None,
    enrolled_at: datetime,
) -> datetime | None:
    """Turn a course's access policy into a concrete instant for the enrolment.

    Resolved once, at enrolment, and stored -- so editing the course's policy
    afterwards cannot retroactively shorten access somebody already has.
    """
    if access_type == "lifetime":
        return None
    if not access_days or access_days <= 0:
        raise ValueError("time_limited access requires a positive access_days")
    return enrolled_at + timedelta(days=access_days)
