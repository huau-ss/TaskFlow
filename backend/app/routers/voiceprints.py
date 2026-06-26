"""声纹识别相关 API"""

from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import Employee, MeetingStatus, VoicePrint
from app.schemas import (
    TranscriptSegmentWithSpeaker,
    TranscriptWithSpeakers,
    VoicePrintBase64Request,
    VoicePrintListItem,
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

    # 保存临时文件（保留原始后缀），再用 ffmpeg 转为 16kHz mono WAV
    import subprocess
    import uuid
    orig_suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    raw_path = Path(f"/tmp/voiceprint_raw_{uuid.uuid4()}{orig_suffix}")
    wav_path = Path(f"/tmp/voiceprint_{uuid.uuid4()}.wav")
    raw_path.write_bytes(content)

    try:
        # ffmpeg 转 16kHz mono WAV
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(raw_path),
             "-ar", "16000", "-ac", "1", "-f", "wav", str(wav_path)],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"音频格式转换失败: {result.stderr.decode()[:200]}"
            )

        service = VoicePrintService(db)
        # 调用 ASR 服务提取声纹特征（同时获取实际音频时长）
        result = await service.extract_voice_embedding(wav_path)

        if not result or not result.get("embedding"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="无法从音频中提取声纹特征，请确保音频清晰且包含人声"
            )

        embedding = result["embedding"]
        audio_duration = result.get("duration")

        # 注册声纹（初始为未验证状态）
        voice_print = service.register_voice_print(
            employee_id=employee_id,
            embedding=embedding,
            source_audio_path=str(wav_path),
            audio_duration=audio_duration,
            note=note,
            is_verified=False,
        )
        
        await db.commit()
        await db.refresh(voice_print)
        
        return voice_print
        
    finally:
        # 清理临时文件
        if raw_path.exists():
            raw_path.unlink()
        if wav_path.exists():
            wav_path.unlink()


@router.post("/register-audio-base64", response_model=VoicePrintResponse, status_code=status.HTTP_201_CREATED)
async def register_voice_print_base64(
    req: VoicePrintBase64Request,
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
    employee = await db.get(Employee, req.employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="员工不存在")

    try:
        audio_data = base64.b64decode(req.audio_base64)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的 Base64 音频数据")

    # 保存原始数据再用 ffmpeg 转为 16kHz mono WAV
    import subprocess
    import uuid
    raw_path = Path(f"/tmp/voiceprint_raw_{uuid.uuid4()}.raw")
    wav_path = Path(f"/tmp/voiceprint_{uuid.uuid4()}.wav")
    raw_path.write_bytes(audio_data)

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(raw_path),
             "-ar", "16000", "-ac", "1", "-f", "wav", str(wav_path)],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"音频格式转换失败: {result.stderr.decode()[:200]}"
            )

        service = VoicePrintService(db)
        result = await service.extract_voice_embedding(wav_path)

        if not result or not result.get("embedding"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="无法从音频中提取声纹特征"
            )

        embedding = result["embedding"]
        audio_duration = result.get("duration")

        voice_print = service.register_voice_print(
            employee_id=req.employee_id,
            embedding=embedding,
            source_audio_path=str(wav_path),
            audio_duration=audio_duration,
            note=req.note,
            is_verified=False,
        )
        
        await db.commit()
        await db.refresh(voice_print)
        
        return voice_print
        
    finally:
        if raw_path.exists():
            raw_path.unlink()
        if wav_path.exists():
            wav_path.unlink()


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


@router.get("/employee/{employee_id}", response_model=list[VoicePrintListItem])
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
    current_user: Employee = Depends(get_current_user),
):
    """
    对会议录音进行说话人识别（重识别）。

    从原始音频提取声纹 embedding，按 speaker_label 聚合后与已注册声纹匹配，
    将结果回填到 TranscriptSegment。
    """
    from collections import defaultdict

    import httpx
    from app.config import settings
    from app.models import Meeting, TranscriptSegment

    meeting = await db.get(Meeting, meeting_id, options=[selectinload(Meeting.segments)])
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")

    if not current_user.is_admin and meeting.creator_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问该会议")

    if meeting.status != MeetingStatus.transcribed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"会议尚未完成转写 (status={meeting.status.value})"
        )

    if not meeting.segments:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议没有转写片段")

    audio_path = Path(meeting.nas_path)
    if not audio_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="音频文件不存在")

    service = VoicePrintService(db)
    all_embeddings = service.get_all_verified_embeddings()
    if not all_embeddings:
        return _build_response(meeting, [])

    # 调用 FunASR 提取会议音频的 embedding
    funasr_url = getattr(settings, "funasr_url", "http://localhost:8005")
    try:
        with httpx.Client(timeout=600.0) as client:
            with open(audio_path, "rb") as f:
                resp = client.post(
                    f"{funasr_url}/api/transcribe",
                    files={"file": (audio_path.name, f, "audio/wav")},
                )
            resp.raise_for_status()
            funasr_result = resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"FunASR 服务不可用: {e}"
        )

    segments_raw = funasr_result.get("segments", [])
    if not segments_raw:
        return _build_response(meeting, [])

    # 按 speaker_label 聚合 embedding
    speaker_embeddings: dict[str, list[list[float]]] = defaultdict(list)
    for seg in segments_raw:
        label = seg.get("speaker_label", "?")
        emb = seg.get("embedding")
        if emb and isinstance(emb, list) and len(emb) > 0:
            speaker_embeddings[label].append(emb)

    # 聚合后逐人匹配
    speaker_match: dict[str, tuple[int | None, float]] = {}
    for spk, embs in speaker_embeddings.items():
        avg_emb = list(np.mean(embs, axis=0))
        emp_id, conf = service.recognize_speaker(avg_emb)
        speaker_match[spk] = (emp_id, conf)

    # 回填到数据库
    label_to_name: dict[str, str] = {}
    for spk, (emp_id, _) in speaker_match.items():
        if emp_id is not None:
            emp = await db.get(Employee, emp_id)
            if emp:
                label_to_name[spk] = emp.name

    updated = 0
    for seg in meeting.segments:
        emp_id, conf = speaker_match.get(seg.speaker_label, (None, 0.0))
        seg.employee_id = emp_id
        updated += 1

    await db.commit()
    logger.info(f"[recognize-meeting] 更新 {updated} 个片段的 employee_id")

    # 回填后从 NAS 重新读取（NAS 已有最新数据），兜底 DB
    from app.services.transcript_segment_storage import get_meeting_segments_async
    segments = await get_meeting_segments_async(db, meeting_id)
    return _build_response_from_segments(
        meeting.id, meeting.status, segments, speaker_match, label_to_name
    )


def _build_response(
    meeting,
    speaker_match: dict[str, tuple[int | None, float]] | None = None,
    label_to_name: dict[str, str] | None = None,
) -> TranscriptWithSpeakers:
    """构造响应，将 speaker_match 映射应用到 meeting.segments"""
    segs = []
    for seg in sorted(meeting.segments, key=lambda s: s.sequence):
        emp_id = None
        conf = None
        if speaker_match is not None:
            emp_id, conf = speaker_match.get(seg.speaker_label, (None, 0.0))
        else:
            emp_id = seg.employee_id
            conf = 1.0 if emp_id else None

        emp_name = None
        if label_to_name:
            emp_name = label_to_name.get(seg.speaker_label)
        elif emp_id and seg.employee:
            emp_name = seg.employee.name

        segs.append(
            TranscriptSegmentWithSpeaker(
                id=seg.id,
                speaker_label=seg.speaker_label,
                employee_id=emp_id,
                employee_name=emp_name,
                text=seg.text,
                start_time=seg.start_time,
                end_time=seg.end_time,
                sequence=seg.sequence,
                confidence=conf,
            )
        )
    return TranscriptWithSpeakers(
        meeting_id=meeting.id,
        status=meeting.status,
        segments=segs,
    )


def _build_response_from_segments(
    meeting_id: int,
    status: MeetingStatus,
    segments: list,
    speaker_match: dict[str, tuple[int | None, float]] | None = None,
    label_to_name: dict[str, str] | None = None,
) -> TranscriptWithSpeakers:
    """从片段列表构造响应（NAS-first 读取后使用）"""
    segs = []
    for seg in sorted(segments, key=lambda s: s.sequence):
        emp_id = None
        conf = None
        if speaker_match is not None:
            emp_id, conf = speaker_match.get(seg.speaker_label, (None, 0.0))
        else:
            emp_id = getattr(seg, "employee_id", None)
            conf = 1.0 if emp_id else None

        emp_name = None
        if label_to_name:
            emp_name = label_to_name.get(seg.speaker_label)

        segs.append(
            TranscriptSegmentWithSpeaker(
                id=getattr(seg, "id", 0),
                speaker_label=getattr(seg, "speaker_label", "?"),
                employee_id=emp_id,
                employee_name=emp_name,
                text=getattr(seg, "text", ""),
                start_time=getattr(seg, "start_time", None),
                end_time=getattr(seg, "end_time", None),
                sequence=getattr(seg, "sequence", 0),
                confidence=conf,
            )
        )
    return TranscriptWithSpeakers(
        meeting_id=meeting_id,
        status=status,
        segments=segs,
    )
