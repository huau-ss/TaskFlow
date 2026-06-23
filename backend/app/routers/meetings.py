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
    await db.commit()

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
    await db.commit()
    await db.refresh(meeting)
    dispatch_transcribe(meeting_id)
    return meeting


# ── 会议关联分析 ──────────────────────────────────────────────

@router.post("/relations/analyze", response_model=MeetingRelationAnalyzeResponse)
async def analyze_meeting_relations(
    meeting_ids: list[int] | None = None,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    """
    分析会议之间的关联关系（LLM 自动识别）。

    - 不传 meeting_ids：分析所有已转录会议
    - 传入 meeting_ids 列表：只分析指定的会议
    """
    from app.agents.meeting_relation import analyze_relations

    meeting_count = 0
    if meeting_ids:
        result = await db.execute(
            select(Meeting).where(
                Meeting.id.in_(meeting_ids),
                Meeting.status == MeetingStatus.transcribed,
            )
        )
    else:
        result = await db.execute(
            select(Meeting).where(Meeting.status == MeetingStatus.transcribed)
        )
    all_meetings = result.scalars().all()
    meeting_count = len(all_meetings)

    if meeting_count < 2:
        return MeetingRelationAnalyzeResponse(
            analyzed_count=meeting_count,
            new_relations=0,
            updated_relations=0,
            relations=[],
        )

    new_rels = await analyze_relations(db, meeting_ids)
    await db.commit()

    relations_resp = [
        MeetingRelationResponse(
            id=r.id,
            meeting_a_id=r.meeting_a_id,
            meeting_b_id=r.meeting_b_id,
            relation_type=r.relation_type.value,
            confidence=r.confidence,
            reason=r.reason,
            created_at=r.created_at,
        )
        for r in new_rels
    ]
    return MeetingRelationAnalyzeResponse(
        analyzed_count=meeting_count,
        new_relations=len(new_rels),
        updated_relations=0,
        relations=relations_resp,
    )


@router.get("/relations", response_model=list[MeetingRelationResponse])
async def list_meeting_relations(
    meeting_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    """
    获取会议关联列表。

    - 不传 meeting_id：返回所有关联
    - 传入 meeting_id：返回与该会议相关的所有关联
    """
    query = select(MeetingRelation).order_by(MeetingRelation.confidence.desc())
    if meeting_id is not None:
        query = query.where(
            (MeetingRelation.meeting_a_id == meeting_id)
            | (MeetingRelation.meeting_b_id == meeting_id)
        )

    result = await db.execute(query)
    relations = result.scalars().all()

    # 预加载会议信息
    meeting_ids = set()
    for r in relations:
        meeting_ids.add(r.meeting_a_id)
        meeting_ids.add(r.meeting_b_id)

    meetings_map = {}
    if meeting_ids:
        meetings_result = await db.execute(
            select(Meeting).where(Meeting.id.in_(meeting_ids))
        )
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
    _: Employee = Depends(get_current_user),
):
    """删除指定的会议关联（用户可手动纠正 LLM 的错误判断）"""
    rel = await db.get(MeetingRelation, relation_id)
    if not rel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")
    await db.delete(rel)
    await db.commit()


@router.get("/graph")
async def get_meeting_graph(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    """
    获取会议关联图谱数据，用于前端可视化。

    返回格式：
    {
        "nodes": [{"id", "title", "created_at", "status"}],
        "edges": [{"id", "source", "target", "relation_type", "confidence", "reason"}]
    }
    """
    meetings_result = await db.execute(
        select(Meeting).order_by(Meeting.created_at.desc())
    )
    meetings = meetings_result.scalars().all()

    relations_result = await db.execute(select(MeetingRelation))
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
