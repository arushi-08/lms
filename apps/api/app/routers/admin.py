"""Admin authoring API.

Every route in this file depends on ``require_admin``, which re-reads
``profiles.role`` from the database rather than trusting the token's claim, so
revoking someone's admin rights takes effect on their next request instead of
at token expiry.

Mutations write an audit_log row inside the same transaction as the change. A
log written afterwards can be lost exactly when it matters most -- when the
request failed halfway.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from app.providers.video.base import VideoProviderError
from app.repositories import admin as repo
from app.security.deps import AdminDep, DatabaseDep, VideoProviderDep

router = APIRouter(prefix="/admin", tags=["admin"])


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def conflict(exc: repo.ConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ----------------------------------------------------------------- schemas --

class CreateCourse(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class UpdateCourse(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    description: str | None = None
    thumbnail_url: str | None = None
    is_free: bool | None = None
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    tax_rate_bps: int | None = Field(default=None, ge=0, le=10_000)
    access_type: Literal["lifetime", "time_limited"] | None = None
    access_days: int | None = Field(default=None, gt=0)
    completion_threshold: int | None = Field(default=None, ge=1, le=100)


class CreateModule(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class CreateLesson(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: Literal["video", "text", "quiz", "assignment"] = "video"


class UpdateLesson(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_preview: bool | None = None
    is_required: bool | None = None
    duration_seconds: int | None = Field(default=None, ge=0, le=86_400)
    content: dict[str, Any] | None = None


class Reorder(BaseModel):
    # Every child, in the order wanted. A partial list is rejected rather than
    # applied, because the result would be an order nobody chose.
    ids: list[UUID] = Field(min_length=1, max_length=500)


class GrantEnrollment(BaseModel):
    user_id: UUID
    course_id: UUID


class QuizSettings(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    passing_score: int = Field(default=70, ge=1, le=100)


class QuizOption(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    is_correct: bool = False


class QuestionInput(BaseModel):
    id: UUID | None = None
    type: Literal["single", "multi", "boolean", "short_text"]
    prompt: str = Field(min_length=1, max_length=2000)
    explanation: str | None = Field(default=None, max_length=2000)
    points: int = Field(default=1, ge=1, le=100)
    correct_answers: list[str] | None = None
    options: list[QuizOption] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _coherent(self) -> QuestionInput:
        # Caught here rather than at the database, so the author sees which
        # question is wrong instead of a constraint name.
        if self.type == "short_text":
            if not self.correct_answers:
                raise ValueError("a short-text question needs at least one accepted answer")
            return self
        if len(self.options) < 2:
            raise ValueError("a choice question needs at least two options")
        if not any(option.is_correct for option in self.options):
            raise ValueError("mark at least one option correct")
        if self.type in {"single", "boolean"} and sum(o.is_correct for o in self.options) != 1:
            raise ValueError("a single-answer question needs exactly one correct option")
        return self


class AssignmentInput(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=20_000)
    max_points: int | None = Field(default=None, ge=1, le=1000)
    passing_score: int | None = Field(default=None, ge=1, le=100)
    is_graded: bool | None = None
    allow_text: bool | None = None
    allow_link: bool | None = None
    due_at: datetime | None = None
    allow_late: bool | None = None


# ----------------------------------------------------------------- courses --

@router.get("/courses")
async def list_courses(admin: AdminDep, database: DatabaseDep) -> list[dict[str, Any]]:
    async with database.acquire() as conn:
        return await repo.list_courses(conn)


@router.post("/courses", status_code=status.HTTP_201_CREATED)
async def create_course(
    payload: CreateCourse, request: Request, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        course = await repo.create_course(conn, title=payload.title, created_by=admin.user_id)
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="course.create",
            entity_type="course",
            entity_id=str(course["id"]),
            diff={"title": payload.title},
            ip=client_ip(request),
        )
    return course


@router.get("/courses/{course_id}")
async def get_course(
    course_id: UUID, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.acquire() as conn:
        tree = await repo.get_course_tree(conn, course_id)
    if tree is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")
    return tree


@router.patch("/courses/{course_id}")
async def update_course(
    course_id: UUID,
    payload: UpdateCourse,
    request: Request,
    admin: AdminDep,
    database: DatabaseDep,
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    async with database.transaction() as conn:
        try:
            course = await repo.update_course(conn, course_id, changes)
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="course.update",
            entity_type="course",
            entity_id=str(course_id),
            diff=changes,
            ip=client_ip(request),
        )
    return {"id": str(course["id"]), "title": course["title"]}


@router.post("/courses/{course_id}/publish")
async def publish_course(
    course_id: UUID, request: Request, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        try:
            course = await repo.set_course_status(conn, course_id, "published")
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="course.publish",
            entity_type="course",
            entity_id=str(course_id),
            ip=client_ip(request),
        )
    return course


@router.post("/courses/{course_id}/unpublish")
async def unpublish_course(
    course_id: UUID, request: Request, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        try:
            course = await repo.set_course_status(conn, course_id, "draft")
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="course.unpublish",
            entity_type="course",
            entity_id=str(course_id),
            ip=client_ip(request),
        )
    return course


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: UUID, request: Request, admin: AdminDep, database: DatabaseDep
) -> None:
    async with database.transaction() as conn:
        try:
            await repo.delete_course(conn, course_id)
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="course.delete",
            entity_type="course",
            entity_id=str(course_id),
            ip=client_ip(request),
        )


# ----------------------------------------------------- modules and lessons --

@router.post("/courses/{course_id}/modules", status_code=status.HTTP_201_CREATED)
async def create_module(
    course_id: UUID, payload: CreateModule, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        module = await repo.create_module(conn, course_id, payload.title)
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="module.create",
            entity_type="module",
            entity_id=str(module["id"]),
        )
    return module


@router.post("/courses/{course_id}/modules/reorder")
async def reorder_modules(
    course_id: UUID, payload: Reorder, admin: AdminDep, database: DatabaseDep
) -> dict[str, str]:
    async with database.transaction() as conn:
        try:
            await repo.reorder_modules(conn, course_id, payload.ids)
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
    return {"status": "ok"}


@router.delete("/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_module(module_id: UUID, admin: AdminDep, database: DatabaseDep) -> None:
    async with database.transaction() as conn:
        await repo.delete_module(conn, module_id)
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="module.delete",
            entity_type="module",
            entity_id=str(module_id),
        )


@router.post("/modules/{module_id}/lessons", status_code=status.HTTP_201_CREATED)
async def create_lesson(
    module_id: UUID, payload: CreateLesson, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        lesson = await repo.create_lesson(
            conn, module_id, title=payload.title, lesson_type=payload.type
        )
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="lesson.create",
            entity_type="lesson",
            entity_id=str(lesson["id"]),
        )
    return lesson


@router.patch("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: UUID, payload: UpdateLesson, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    async with database.transaction() as conn:
        try:
            lesson = await repo.update_lesson(conn, lesson_id, changes)
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="lesson.update",
            entity_type="lesson",
            entity_id=str(lesson_id),
            diff={k: v for k, v in changes.items() if k != "content"},
        )
    return lesson


@router.post("/modules/{module_id}/lessons/reorder")
async def reorder_lessons(
    module_id: UUID, payload: Reorder, admin: AdminDep, database: DatabaseDep
) -> dict[str, str]:
    async with database.transaction() as conn:
        try:
            await repo.reorder_lessons(conn, module_id, payload.ids)
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
    return {"status": "ok"}


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(lesson_id: UUID, admin: AdminDep, database: DatabaseDep) -> None:
    async with database.transaction() as conn:
        await repo.delete_lesson(conn, lesson_id)
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="lesson.delete",
            entity_type="lesson",
            entity_id=str(lesson_id),
        )


# ------------------------------------------------------------------- video --

@router.post("/lessons/{lesson_id}/video/upload")
async def create_video_upload(
    lesson_id: UUID,
    request: Request,
    admin: AdminDep,
    database: DatabaseDep,
    provider: VideoProviderDep,
) -> dict[str, Any]:
    """Mint credentials for the browser to upload straight to the provider.

    The file never passes through this service: fifty course videos through a
    512 MB instance would be slow at best and would exhaust it at worst.
    """
    async with database.acquire() as conn:
        lesson = await repo.get_lesson_video(conn, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lesson not found")
    if lesson["type"] != "video":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="lesson is not a video lesson"
        )

    try:
        ticket = await provider.create_upload(f"lesson-{lesson_id}")
    except VideoProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="video service unavailable"
        ) from exc

    async with database.transaction() as conn:
        await repo.set_lesson_video(conn, lesson_id, video_id=ticket.video_id, status="uploading")
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="lesson.video.upload_started",
            entity_type="lesson",
            entity_id=str(lesson_id),
            diff={"video_id": ticket.video_id},
        )

    # The mock provider names its own endpoint with a site-relative path,
    # because it does not know this service's public URL. The browser would
    # resolve that against the *frontend* origin and POST the file to Next,
    # which has no such route. Absolutise it here, where the request knows.
    # VdoCipher returns an absolute URL, which passes through untouched.
    upload_url = ticket.upload_url
    if upload_url.startswith("/"):
        upload_url = str(request.base_url).rstrip("/") + upload_url

    return {
        "video_id": ticket.video_id,
        "upload_url": upload_url,
        "upload_fields": ticket.upload_fields,
    }


@router.get("/lessons/{lesson_id}/video/status")
async def refresh_video_status(
    lesson_id: UUID,
    admin: AdminDep,
    database: DatabaseDep,
    provider: VideoProviderDep,
) -> dict[str, Any]:
    """Poll the provider and record what it says.

    Encoding is not instant, so the admin UI has a real "still processing"
    state to render. The mock provider fakes that delay for the same reason.
    """
    async with database.acquire() as conn:
        lesson = await repo.get_lesson_video(conn, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lesson not found")
    if not lesson["video_id"]:
        return {"lesson_id": str(lesson_id), "video_status": "absent"}

    try:
        remote = await provider.get_status(lesson["video_id"])
    except VideoProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="video service unavailable"
        ) from exc

    mapped = {"ready": "ready", "processing": "processing", "failed": "failed"}.get(
        remote, "processing"
    )
    async with database.transaction() as conn:
        await repo.set_video_status(conn, lesson_id, mapped)

    return {"lesson_id": str(lesson_id), "video_status": mapped}


# ---------------------------------------------------------------- students --

@router.get("/students")
async def list_students(
    admin: AdminDep,
    database: DatabaseDep,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> list[dict[str, Any]]:
    async with database.acquire() as conn:
        return await repo.list_students(conn, limit=limit, offset=offset)


@router.post("/enrollments", status_code=status.HTTP_201_CREATED)
async def grant_enrollment(
    payload: GrantEnrollment, request: Request, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        try:
            enrollment = await repo.grant_enrollment(
                conn, user_id=payload.user_id, course_id=payload.course_id
            )
        except repo.ConflictError as exc:
            raise conflict(exc) from exc
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="enrollment.grant",
            entity_type="enrollment",
            entity_id=str(enrollment["id"]),
            diff={"user_id": str(payload.user_id), "course_id": str(payload.course_id)},
            ip=client_ip(request),
        )
    return {**enrollment, "id": str(enrollment["id"])}


@router.delete("/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_enrollment(
    enrollment_id: UUID, request: Request, admin: AdminDep, database: DatabaseDep
) -> None:
    async with database.transaction() as conn:
        await repo.revoke_enrollment(conn, enrollment_id)
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="enrollment.revoke",
            entity_type="enrollment",
            entity_id=str(enrollment_id),
            ip=client_ip(request),
        )


# --------------------------------------------------------- quiz authoring --

@router.put("/lessons/{lesson_id}/quiz")
async def upsert_quiz(
    lesson_id: UUID, payload: QuizSettings, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        quiz = await repo.upsert_quiz(
            conn, lesson_id, title=payload.title, passing_score=payload.passing_score
        )
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="quiz.upsert",
            entity_type="quiz",
            entity_id=str(quiz["id"]),
        )
    return {**quiz, "id": str(quiz["id"])}


@router.get("/lessons/{lesson_id}/quiz")
async def get_quiz_for_editing(
    lesson_id: UUID, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    """Returns the answer key. Admin only, by construction and by route."""
    async with database.acquire() as conn:
        quiz = await repo.get_quiz_for_editing(conn, lesson_id)
    if quiz is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no quiz yet")
    return quiz


@router.put("/quizzes/{quiz_id}/questions")
async def save_question(
    quiz_id: UUID, payload: QuestionInput, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        if payload.id is not None and await repo.question_has_responses(conn, payload.id):
            # Editing a question students have already answered would silently
            # rewrite the meaning of their recorded responses.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this question has already been answered; add a new one instead",
            )
        question_id = await repo.replace_question(
            conn,
            quiz_id=quiz_id,
            question_id=payload.id,
            question_type=payload.type,
            prompt=payload.prompt,
            explanation=payload.explanation,
            points=payload.points,
            correct_answers=payload.correct_answers,
            options=[option.model_dump() for option in payload.options],
        )
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="quiz.question.save",
            entity_type="quiz_question",
            entity_id=str(question_id),
        )
    return {"id": str(question_id)}


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: UUID, admin: AdminDep, database: DatabaseDep
) -> None:
    async with database.transaction() as conn:
        if await repo.question_has_responses(conn, question_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this question has already been answered and cannot be deleted",
            )
        await repo.delete_question(conn, question_id)
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="quiz.question.delete",
            entity_type="quiz_question",
            entity_id=str(question_id),
        )


# --------------------------------------------------- assignment authoring --

@router.put("/lessons/{lesson_id}/assignment")
async def upsert_assignment(
    lesson_id: UUID, payload: AssignmentInput, admin: AdminDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        assignment = await repo.upsert_assignment(
            conn, lesson_id, payload.model_dump(exclude_unset=True)
        )
        await repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="assignment.upsert",
            entity_type="assignment",
            entity_id=str(assignment["id"]),
        )
    return {**assignment, "id": str(assignment["id"]), "lesson_id": str(assignment["lesson_id"])}
