from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Meeting, MeetingStatus, TranscriptSegment
from app.tasks.celery_app import celery_app

sync_engine = create_engine(settings.database_url_sync)
SyncSession = sessionmaker(sync_engine)


def _parse_asr_response(data: dict | list) -> list[dict]:
    """Normalize ASR API response into segment dicts."""
    segments: list[dict] = []

    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                segments.append(
                    {
                        "speaker_label": str(item.get("speaker", item.get("speaker_label", f"SPEAKER_{i}"))),
                        "text": item.get("text", item.get("transcript", "")),
                        "start_time": item.get("start", item.get("start_time")),
                        "end_time": item.get("end", item.get("end_time")),
                        "embedding": item.get("embedding"),  # 声纹特征向量（如果有）
                        "sequence": i,
                    }
                )
        return segments

    if isinstance(data, dict):
        if "segments" in data:
            raw = data["segments"]
        elif "utterances" in data:
            raw = data["utterances"]
        elif "results" in data:
            raw = data["results"]
        else:
            text = data.get("text", data.get("transcript", ""))
            if text:
                segments.append(
                    {
                        "speaker_label": "SPEAKER_0",
                        "text": text,
                        "start_time": None,
                        "end_time": None,
                        "embedding": None,
                        "sequence": 0,
                    }
                )
            return segments

        for i, item in enumerate(raw):
            segments.append(
                {
                    "speaker_label": str(item.get("speaker", item.get("speaker_label", f"SPEAKER_{i}"))),
                    "text": item.get("text", item.get("transcript", "")),
                    "start_time": item.get("start", item.get("start_time")),
                    "end_time": item.get("end", item.get("end_time")),
                    "embedding": item.get("embedding"),  # 声纹特征向量
                    "sequence": i,
                }
            )
    return segments


def _mock_transcript_segments() -> list[dict]:
    return [
        {
            "speaker_label": "SPEAKER_0",
            "text": "李明，请在下周三之前完成用户调研报告。",
            "start_time": 0.0,
            "end_time": 5.0,
            "embedding": None,
            "sequence": 0,
        },
        {
            "speaker_label": "SPEAKER_1",
            "text": "王芳负责整理会议纪要，本周五前发给张经理。",
            "start_time": 5.0,
            "end_time": 10.0,
            "embedding": None,
            "sequence": 1,
        },
    ]


def _call_asr_api(audio_path: Path) -> dict | list:
    if settings.mock_asr:
        return {"segments": _mock_transcript_segments()}

    with httpx.Client(timeout=600.0) as client:
        with open(audio_path, "rb") as f:
            resp = client.post(
                settings.asr_diarize_url,
                files={"file": (audio_path.name, f, "audio/wav")},
            )
        resp.raise_for_status()
        return resp.json()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot_product = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot_product / (norm_a * norm_b))


def _recognize_speaker(db, embedding: list[float]) -> tuple[int | None, float]:
    """
    识别说话人，返回 (employee_id, confidence)
    """
    import json

    from sqlalchemy import select
    from app.models import VoicePrint

    # 获取所有已验证的声纹
    result = db.execute(
        select(VoicePrint).where(VoicePrint.is_verified == True)
    )
    voice_prints = result.scalars().all()
    
    if not voice_prints:
        return None, 0.0
    
    # 按员工分组，计算平均 embedding
    from collections import defaultdict
    employee_embeddings: dict[int, list[list[float]]] = defaultdict(list)
    
    for vp in voice_prints:
        try:
            emb = json.loads(vp.embedding)
            if isinstance(emb, list):
                employee_embeddings[vp.employee_id].append(emb)
        except (json.JSONDecodeError, TypeError):
            continue
    
    if not employee_embeddings:
        return None, 0.0
    
    best_employee_id = None
    best_similarity = 0.0
    
    for emp_id, embeddings in employee_embeddings.items():
        # 计算该员工的平均声纹
        avg_emb = np.mean(embeddings, axis=0).tolist()
        similarity = cosine_similarity(embedding, avg_emb)
        
        if similarity > best_similarity:
            best_similarity = similarity
            best_employee_id = emp_id
    
    # 置信度阈值
    MIN_THRESHOLD = 0.5
    
    if best_similarity < MIN_THRESHOLD:
        return None, best_similarity
    
    return best_employee_id, best_similarity


def _extract_speaker_embedding_from_audio(
    audio_path: Path, start_time: float, end_time: float
) -> list[float] | None:
    """
    从音频中提取特定时间段的声纹特征
    
    调用 ASR 服务的 embeddings 接口
    """
    # TODO: 如果 ASR 服务支持时间范围提取，则使用；否则需要音频切片
    # 目前假设 ASR 服务可以返回每个 speaker 的 embedding
    return None


def _recognize_meeting_speakers(db, meeting_id: int, segments: list[dict]) -> list[dict]:
    """
    对会议的每个片段进行说话人识别
    
    Args:
        db: 数据库会话
        meeting_id: 会议 ID
        segments: ASR 返回的片段列表
        
    Returns:
        带有识别结果的片段列表
    """
    # 如果 segments 中已经有 embedding，直接使用
    # 否则需要额外的声纹提取步骤
    
    recognized_segments = []
    for seg in segments:
        embedding = seg.get("embedding")
        
        if embedding:
            # 有声纹特征，进行识别
            employee_id, confidence = _recognize_speaker(db, embedding)
        else:
            # 没有声纹特征，标记为未知
            employee_id, confidence = None, 0.0
        
        recognized_segments.append({
            **seg,
            "employee_id": employee_id,
            "confidence": confidence
        })
    
    return recognized_segments


def run_transcribe_meeting(meeting_id: int) -> dict:
    """Core ASR pipeline: read audio from NAS, call :8002, persist transcript_segments."""
    with SyncSession() as db:
        meeting = db.get(Meeting, meeting_id)
        if not meeting:
            return {"error": "meeting not found"}

        meeting.status = MeetingStatus.transcribing
        db.commit()

        audio_path = Path(meeting.nas_path)
        if not audio_path.exists():
            meeting.status = MeetingStatus.failed
            meeting.asr_error = f"Audio file not found: {meeting.nas_path}"
            db.commit()
            return {"error": meeting.asr_error}

        try:
            data = _call_asr_api(audio_path)
        except Exception as exc:
            meeting.status = MeetingStatus.failed
            meeting.asr_error = str(exc)
            db.commit()
            return {"error": str(exc)}

        segments = _parse_asr_response(data)
        
        # 进行说话人识别
        recognized_segments = _recognize_meeting_speakers(db, meeting_id, segments)
        
        # 删除旧的转写片段
        db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id))
        
        for seg in recognized_segments:
            if not seg["text"].strip():
                continue
            db.add(
                TranscriptSegment(
                    meeting_id=meeting_id,
                    speaker_label=seg["speaker_label"],
                    employee_id=seg.get("employee_id"),  # 识别出的员工 ID
                    text=seg["text"],
                    start_time=seg.get("start_time"),
                    end_time=seg.get("end_time"),
                    sequence=seg["sequence"],
                )
            )

        meeting.status = MeetingStatus.transcribed
        meeting.asr_error = None
        db.commit()
        return {
            "meeting_id": meeting_id,
            "segments": len(segments),
            "recognized_speakers": sum(1 for s in recognized_segments if s.get("employee_id"))
        }


@celery_app.task(name="transcribe_meeting", bind=True, max_retries=3)
def transcribe_meeting(self, meeting_id: int) -> dict:
    result = run_transcribe_meeting(meeting_id)
    if "error" in result and self.request.retries < self.max_retries:
        raise self.retry(exc=Exception(result["error"]), countdown=60)
    return result
