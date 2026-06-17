import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Employee, Meeting, MeetingStatus, Task
from app.schemas import (
    MeetingResponse,
    TaskExtractResponse,
    TaskResponse,
    TranscriptResponse,
    TranscriptSegmentResponse,
)
from app.services.asr_dispatch import dispatch_transcribe

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _ensure_nas_dir() -> Path:
    nas = Path(settings.nas_path)
    nas.mkdir(parents=True, exist_ok=True)
    return nas


@router.post("/upload", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
async def upload_meeting(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    nas_dir = _ensure_nas_dir()
    ext = Path(file.filename or "recording.wav").suffix or ".wav"
    file_id = str(uuid.uuid4())
    dest = nas_dir / f"{file_id}{ext}"

    content = await file.read()
    dest.write_bytes(content)

    meeting = Meeting(
        title=title or file.filename,
        nas_path=str(dest),
        original_filename=file.filename,
        file_size=len(content),
        status=MeetingStatus.uploaded,
        creator_id=current_user.id,
    )
    db.add(meeting)
    await db.flush()
    await db.refresh(meeting)

    dispatch_transcribe(meeting.id)
    return meeting


@router.get("", response_model=list[MeetingResponse])
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    result = await db.execute(select(Meeting).order_by(Meeting.created_at.desc()))
    return result.scalars().all()


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    result = await db.execute(
        select(Meeting)
        .options(selectinload(Meeting.segments))
        .where(Meeting.id == meeting_id)
    )
    meeting = result.scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    segments = sorted(meeting.segments, key=lambda s: s.sequence)
    return TranscriptResponse(
        meeting_id=meeting.id,
        status=meeting.status,
        segments=[TranscriptSegmentResponse.model_validate(s) for s in segments],
    )


@router.post("/{meeting_id}/extract-tasks", response_model=TaskExtractResponse)
async def extract_tasks(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    from app.agents.task_extract import run_task_extraction

    result = await db.execute(
        select(Meeting)
        .options(selectinload(Meeting.segments))
        .where(Meeting.id == meeting_id)
    )
    meeting = result.scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    if meeting.status != MeetingStatus.transcribed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Meeting not transcribed (status={meeting.status.value})",
        )
    tasks = await run_task_extraction(db, meeting)
    return TaskExtractResponse(
        meeting_id=meeting_id,
        tasks_created=len(tasks),
        tasks=[TaskResponse.model_validate(t) for t in tasks],
    )


@router.get("/{meeting_id}/tasks", response_model=list[TaskResponse])
async def list_meeting_tasks(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    result = await db.execute(select(Task).where(Task.meeting_id == meeting_id).order_by(Task.id))
    return result.scalars().all()


@router.post("/{meeting_id}/retranscribe", response_model=MeetingResponse)
async def retranscribe(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    meeting.status = MeetingStatus.uploaded
    meeting.asr_error = None
    await db.flush()
    dispatch_transcribe(meeting_id)
    await db.refresh(meeting)
    return meeting
