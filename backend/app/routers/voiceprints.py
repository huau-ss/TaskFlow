"""声纹识别相关 API"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import Employee, VoicePrint
from app.schemas import (
    TranscriptSegmentWithSpeaker,
    TranscriptWithSpeakers,
    VoicePrintResponse,
)
from app.services.voiceprint import VoicePrintService

router = APIRouter(prefix="/voiceprints", tags=["voiceprints"])


@router.post("", response_model=VoicePrintResponse, status_code=status.HTTP_201_CREATED)
async def register_voice_print(
    file: UploadFile = File(...),
    employee_id: int = Form(...),
    note: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    注册员工声纹（仅管理员可操作）

    上传一段员工录音（建议 5-30 秒），系统会：
    1. 提取声纹特征向量
    2. 存储到数据库

    注意：首次注册需要人工验证声纹有效性
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")

    # 验证员工存在
    employee = await db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="员工不存在")
    
    # 读取音频文件
    content = await file.read()
    
    # 保存临时文件用于提取声纹
    import uuid
    temp_path = Path(f"/tmp/voiceprint_{uuid.uuid4()}.wav")
    temp_path.write_bytes(content)
    
    try:
        service = VoicePrintService(db)
        # 调用 ASR 服务提取声纹特征
        embedding = await service.extract_voice_embedding(temp_path)
        
        if not embedding:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="无法从音频中提取声纹特征，请确保音频清晰且包含人声"
            )
        
        # 注册声纹（初始为未验证状态）
        voice_print = service.register_voice_print(
            employee_id=employee_id,
            embedding=embedding,
            source_audio_path=str(temp_path),
            audio_duration=len(content) / 16000 / 2,  # 估算时长
            note=note,
            is_verified=False
        )
        
        await db.commit()
        await db.refresh(voice_print)
        
        return voice_print
        
    finally:
        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink()


@router.post("/register-audio-base64", response_model=VoicePrintResponse, status_code=status.HTTP_201_CREATED)
async def register_voice_print_base64(
    employee_id: int,
    audio_base64: str,
    note: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    注册员工声纹（通过 Base64 编码的音频，仅管理员可操作）

    用于前端录音后直接上传声纹数据
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")

    import base64

    # 验证员工存在
    employee = await db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="员工不存在")
    
    try:
        audio_data = base64.b64decode(audio_base64)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的 Base64 音频数据")
    
    # 保存临时文件
    import uuid
    temp_path = Path(f"/tmp/voiceprint_{uuid.uuid4()}.wav")
    temp_path.write_bytes(audio_data)
    
    try:
        service = VoicePrintService(db)
        embedding = await service.extract_voice_embedding(temp_path)
        
        if not embedding:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="无法从音频中提取声纹特征"
            )
        
        voice_print = service.register_voice_print(
            employee_id=employee_id,
            embedding=embedding,
            source_audio_path=str(temp_path),
            audio_duration=len(audio_data) / 16000 / 2,
            note=note,
            is_verified=False
        )
        
        await db.commit()
        await db.refresh(voice_print)
        
        return voice_print
        
    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.post("/{voiceprint_id}/verify", response_model=VoicePrintResponse)
async def verify_voice_print(
    voiceprint_id: int,
    is_verified: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    验证声纹样本有效性（仅管理员可操作）

    管理员可以标记某条声纹为已验证，验证后的声纹会用于说话人识别
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")

    voice_print = await db.get(VoicePrint, voiceprint_id)
    if not voice_print:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="声纹不存在")

    voice_print.is_verified = is_verified
    await db.commit()
    await db.refresh(voice_print)

    return voice_print


@router.delete("/{voiceprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice_print(
    voiceprint_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """删除声纹样本（仅管理员可操作）"""
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")

    voice_print = await db.get(VoicePrint, voiceprint_id)
    if not voice_print:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="声纹不存在")

    await db.delete(voice_print)
    await db.commit()


@router.get("/employee/{employee_id}", response_model=list[VoicePrintResponse])
async def get_employee_voiceprints(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    """获取员工的所有声纹样本"""
    result = await db.execute(
        select(VoicePrint)
        .where(VoicePrint.employee_id == employee_id)
        .order_by(VoicePrint.created_at.desc())
    )
    return result.scalars().all()


@router.post("/recognize-meeting/{meeting_id}")
async def recognize_meeting_speakers(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    """
    对会议录音进行说话人识别
    
    返回识别后的转写文本，每个片段包含说话人信息
    """
    from app.models import Meeting, MeetingStatus, TranscriptSegment
    
    # 获取会议和转写片段
    result = await db.execute(
        select(Meeting)
        .options(selectinload(Meeting.segments))
        .where(Meeting.id == meeting_id)
    )
    meeting = result.scalar_one_or_none()
    
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
    
    if meeting.status != MeetingStatus.transcribed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"会议尚未完成转写 (status={meeting.status.value})"
        )
    
    if not meeting.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="会议没有转写片段"
        )
    
    # 调用声纹服务进行识别
    audio_path = Path(meeting.nas_path)
    service = VoicePrintService(db)
    
    # 获取所有验证过的声纹
    all_embeddings = service.get_all_verified_embeddings()
    
    if not all_embeddings:
        # 没有已注册的声纹，返回原始数据
        return TranscriptWithSpeakers(
            meeting_id=meeting_id,
            status=meeting.status,
            segments=[
                TranscriptSegmentWithSpeaker(
                    id=seg.id,
                    speaker_label=seg.speaker_label,
                    employee_id=None,
                    employee_name=None,
                    text=seg.text,
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    sequence=seg.sequence,
                    confidence=None
                )
                for seg in sorted(meeting.segments, key=lambda s: s.sequence)
            ]
        )
    
    # TODO: 实际上需要 ASR 服务返回每个 speaker 的 embedding
    # 这里需要根据实际的 ASR 服务能力来实现
    # 临时方案：假设 ASR 返回的 speaker_label 保持一致，直接使用
    
    return TranscriptWithSpeakers(
        meeting_id=meeting_id,
        status=meeting.status,
        segments=[
            TranscriptSegmentWithSpeaker(
                id=seg.id,
                speaker_label=seg.speaker_label,
                employee_id=seg.employee_id,
                employee_name=seg.employee.name if seg.employee else None,
                text=seg.text,
                start_time=seg.start_time,
                end_time=seg.end_time,
                sequence=seg.sequence,
                confidence=1.0 if seg.employee_id else None
            )
            for seg in sorted(meeting.segments, key=lambda s: s.sequence)
        ]
    )
