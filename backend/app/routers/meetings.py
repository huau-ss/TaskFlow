import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Employee, Meeting, MeetingRelation, MeetingStatus, Task
from app.schemas import (
    MeetingResponse,
    MeetingRelationAnalyzeResponse,
    MeetingRelationResponse,
    TaskExtractResponse,
    TaskResponse,
    TranscriptResponse,
    TranscriptSegmentResponse,
)
from app.services.asr_dispatch import dispatch_transcribe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _user_can_access_meeting(meeting: Meeting, user: Employee) -> bool:
    """普通用户只能访问自己上传的会议；管理员不受限制。"""
    if user.is_admin:
        return True
    return meeting.creator_id == user.id


def _check_meeting_access(meeting: Meeting, user: Employee) -> None:
    if not _user_can_access_meeting(meeting, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问该会议",
        )


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
    await db.commit()

    dispatch_transcribe(meeting.id)
    return meeting


@router.get("", response_model=list[MeetingResponse])
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    query = select(Meeting).order_by(Meeting.created_at.desc())
    if not current_user.is_admin:
        query = query.where(Meeting.creator_id == current_user.id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    _check_meeting_access(meeting, current_user)
    return meeting


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    _check_meeting_access(meeting, current_user)

    from app.services.transcript_segment_storage import get_meeting_segments_async
    segments = await get_meeting_segments_async(db, meeting_id)
    return TranscriptResponse(
        meeting_id=meeting.id,
        status=meeting.status,
        segments=[TranscriptSegmentResponse.model_validate(s) for s in segments],
    )


@router.post("/{meeting_id}/extract-tasks", response_model=TaskExtractResponse)
async def extract_tasks(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
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
    _check_meeting_access(meeting, current_user)
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
    current_user: Employee = Depends(get_current_user),
):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    _check_meeting_access(meeting, current_user)

    result = await db.execute(select(Task).where(Task.meeting_id == meeting_id).order_by(Task.id))
    return result.scalars().all()


@router.post("/{meeting_id}/retranscribe", response_model=MeetingResponse)
async def retranscribe(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    _check_meeting_access(meeting, current_user)
    meeting.status = MeetingStatus.uploaded
    meeting.asr_error = None
    await db.flush()
    await db.commit()
    await db.refresh(meeting)
    dispatch_transcribe(meeting_id)
    return meeting


# ── 会议关联分析 ──────────────────────────────────────────────

@router.post("/relations/analyze", response_model=MeetingRelationAnalyzeResponse)
async def analyze_meeting_relations(
    meeting_ids: list[int] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    手动触发会议关联分析。

    管理员可分析所有会议；普通用户只能分析自己上传的会议。
    实际由 Celery 任务异步执行，接口立即返回已接收消息。
    """
    from sqlalchemy import func

    # 非管理员：限定只能分析自己上传的会议
    if current_user.is_admin:
        visible_filter = True
    else:
        visible_filter = Meeting.creator_id == current_user.id

    base_filter = Meeting.status.in_([MeetingStatus.transcribed, MeetingStatus.processed])
    if meeting_ids:
        count_result = await db.execute(
            select(func.count()).select_from(Meeting).where(
                Meeting.id.in_(meeting_ids),
                visible_filter,
                base_filter,
            )
        )
    else:
        count_result = await db.execute(
            select(func.count()).select_from(Meeting).where(visible_filter, base_filter)
        )
    meeting_count = count_result.scalar() or 0

    if meeting_count < 2:
        return MeetingRelationAnalyzeResponse(
            analyzed_count=meeting_count,
            new_relations=0,
            updated_relations=0,
            relations=[],
        )

    from app.tasks.relation_analysis import run_global_relation_analysis

    task = run_global_relation_analysis.delay()
    logger.info("关联分析任务已派发，task_id=%s，meeting_count=%d，user=%s", task.id, meeting_count, current_user.email)

    return MeetingRelationAnalyzeResponse(
        analyzed_count=meeting_count,
        new_relations=0,
        updated_relations=0,
        relations=[],
        task_id=task.id,
    )


@router.get("/relations", response_model=list[MeetingRelationResponse])
async def list_meeting_relations(
    meeting_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    获取会议关联列表。

    - 不传 meeting_id：返回与用户可访问会议相关的所有关联
    - 传入 meeting_id：返回与该会议相关的所有关联（需有访问权限）
    """
    # 收集用户可访问的会议 ID
    if current_user.is_admin:
        visible_ids_query = select(Meeting.id)
    else:
        visible_ids_query = select(Meeting.id).where(Meeting.creator_id == current_user.id)

    visible_ids_result = await db.execute(visible_ids_query)
    visible_meeting_ids = set(visible_ids_result.scalars().all())

    if meeting_id is not None:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        _check_meeting_access(meeting, current_user)
        query = select(MeetingRelation).where(
            (MeetingRelation.meeting_a_id == meeting_id) | (MeetingRelation.meeting_b_id == meeting_id)
        )
    else:
        if not visible_meeting_ids:
            return []
        query = select(MeetingRelation).where(
            MeetingRelation.meeting_a_id.in_(visible_meeting_ids)
            | MeetingRelation.meeting_b_id.in_(visible_meeting_ids)
        )

    query = query.order_by(MeetingRelation.confidence.desc())
    result = await db.execute(query)
    relations = result.scalars().all()

    # 预加载会议信息
    related_meeting_ids = set()
    for r in relations:
        related_meeting_ids.add(r.meeting_a_id)
        related_meeting_ids.add(r.meeting_b_id)

    meetings_map = {}
    if related_meeting_ids:
        meetings_result = await db.execute(select(Meeting).where(Meeting.id.in_(related_meeting_ids)))
        for m in meetings_result.scalars().all():
            meetings_map[m.id] = m

    return [
        MeetingRelationResponse(
            id=r.id,
            meeting_a_id=r.meeting_a_id,
            meeting_b_id=r.meeting_b_id,
            relation_type=r.relation_type.value,
            confidence=r.confidence,
            reason=r.reason,
            created_at=r.created_at,
            meeting_a_title=getattr(meetings_map.get(r.meeting_a_id), "title", None),
            meeting_b_title=getattr(meetings_map.get(r.meeting_b_id), "title", None),
            meeting_a_created_at=getattr(meetings_map.get(r.meeting_a_id), "created_at", None),
            meeting_b_created_at=getattr(meetings_map.get(r.meeting_b_id), "created_at", None),
        )
        for r in relations
    ]


@router.delete("/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting_relation(
    relation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """删除指定的会议关联（需有权限访问关联中的任一会议）"""
    rel = await db.get(MeetingRelation, relation_id)
    if not rel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")

    # 管理员可删除任意关联；普通用户需至少能访问关联中的任一会议
    if not current_user.is_admin:
        meeting_a = await db.get(Meeting, rel.meeting_a_id)
        meeting_b = await db.get(Meeting, rel.meeting_b_id)
        can_access_a = meeting_a and meeting_a.creator_id == current_user.id
        can_access_b = meeting_b and meeting_b.creator_id == current_user.id
        if not (can_access_a or can_access_b):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限删除该关联",
            )

    await db.delete(rel)
    await db.commit()


@router.get("/graph")
async def get_meeting_graph(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    获取会议关联图谱数据，用于前端可视化。

    管理员可查看全部图谱；普通用户只看到自己上传会议相关的图谱。
    """
    if current_user.is_admin:
        meetings_query = select(Meeting).order_by(Meeting.created_at.desc())
        relations_query = select(MeetingRelation)
    else:
        user_meeting_ids = select(Meeting.id).where(Meeting.creator_id == current_user.id)
        meetings_query = select(Meeting).where(Meeting.creator_id == current_user.id).order_by(Meeting.created_at.desc())
        relations_query = select(MeetingRelation).where(
            (MeetingRelation.meeting_a_id.in_(user_meeting_ids))
            | (MeetingRelation.meeting_b_id.in_(user_meeting_ids))
        )

    meetings_result = await db.execute(meetings_query)
    meetings = meetings_result.scalars().all()

    relations_result = await db.execute(relations_query)
    relations = relations_result.scalars().all()

    nodes = [
        {
            "id": m.id,
            "title": m.title or "(无标题)",
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "status": m.status.value,
        }
        for m in meetings
    ]

    edges = [
        {
            "id": r.id,
            "source": r.meeting_a_id,
            "target": r.meeting_b_id,
            "relation_type": r.relation_type.value,
            "confidence": r.confidence,
            "reason": r.reason,
        }
        for r in relations
    ]

    return {"nodes": nodes, "edges": edges}
