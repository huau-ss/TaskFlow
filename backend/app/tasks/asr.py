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

    import re
    import time

    with httpx.Client(timeout=600.0) as client:
        # 上传音频到 ASR 服务
        with open(audio_path, "rb") as f:
            resp = client.post(
                settings.asr_diarize_url,
                files={"env_audio": (audio_path.name, f, "audio/wav")},
            )
        resp.raise_for_status()
        data = resp.json()

        # 如果直接返回 segments（同步模式），直接返回
        if "segments" in data or "utterances" in data or "results" in data:
            return data

        # 异步模式：轮询等待结果
        task_id = data.get("task_id")
        if not task_id:
            return data

        base_url = settings.asr_diarize_url.rsplit("/api", 1)[0]
        for _ in range(200):  # 最多等待 ~10 分钟
            time.sleep(3)
            status_resp = client.get(f"{base_url}/api/status/{task_id}")
            status_resp.raise_for_status()
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "failed":
                error = status_data.get("error", "ASR 处理失败")
                raise Exception(f"ASR 失败: {error}")

            if status in ("done", "completed"):
                # 获取结果
                result_resp = client.get(f"{base_url}/api/result/{task_id}")
                result_resp.raise_for_status()

                # 尝试 JSON 解析
                try:
                    result_data = result_resp.json()
                    if isinstance(result_data, (dict, list)):
                        return result_data
                except Exception:
                    pass

                # Markdown 格式解析
                md_text = result_resp.text
                return _parse_markdown_transcript(md_text)

        raise Exception("ASR 处理超时")


def _parse_markdown_transcript(md_text: str) -> dict:
    """解析 8002 返回的 Markdown 格式转写文本"""
    import re

    segments = []
    # 匹配 [HH:MM:SS] 或 [MM:SS] + **说话人 X**：内容
    pattern = r'\[(\d{1,2}:?\d{2}:\d{2})\]\s*\*\*(.+?)\*\*[：:]\s*(.+?)(?=\n\[|\Z)'
    matches = re.findall(pattern, md_text, re.DOTALL)

    for i, (timestamp, speaker, text) in enumerate(matches):
        # 解析时间戳为秒数
        parts = timestamp.split(":")
        if len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + int(parts[1])
        else:
            seconds = 0

        segments.append({
            "speaker_label": speaker.strip(),
            "text": text.strip(),
            "start_time": float(seconds),
            "end_time": None,
            "embedding": None,
            "sequence": i,
        })

    # 如果正则没匹配到，尝试按行解析
    if not segments:
        lines = md_text.strip().split("\n")
        idx = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("---"):
                continue
            # 简单匹配 **说话人** 格式
            m = re.match(r'\*\*(.+?)\*\*[：:]\s*(.+)', line)
            if m:
                segments.append({
                    "speaker_label": m.group(1).strip(),
                    "text": m.group(2).strip(),
                    "start_time": None,
                    "end_time": None,
                    "embedding": None,
                    "sequence": idx,
                })
                idx += 1

    # 如果完全无法解析，把整段文本作为一个片段
    if not segments and md_text.strip():
        segments.append({
            "speaker_label": "SPEAKER_0",
            "text": md_text.strip(),
            "start_time": None,
            "end_time": None,
            "embedding": None,
            "sequence": 0,
        })

    return {"segments": segments}


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


def _extract_segment_embedding(audio_path: Path, start_time: float | None, end_time: float | None) -> list[float] | None:
    """从完整音频中截取片段，调用本地 embedding 服务提取声纹向量"""
    import subprocess
    import tempfile
    import httpx

    if start_time is None:
        return None

    duration = None
    if end_time is not None and end_time > start_time:
        duration = end_time - start_time
    else:
        duration = 5.0  # 默认截取 5 秒

    embedding_url = getattr(settings, "embedding_url", "http://localhost:8003")

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        # 用 ffmpeg 截取片段并转为 16kHz mono WAV
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-t", str(min(duration, 30)),  # 最长 30 秒
                "-i", str(audio_path),
                "-ar", "16000", "-ac", "1", "-f", "wav",
                tmp_path
            ],
            capture_output=True, timeout=30,
        )

        if result.returncode != 0 or not Path(tmp_path).exists():
            return None

        # 调用本地 embedding 服务
        with open(tmp_path, "rb") as f:
            resp = httpx.post(
                f"{embedding_url}/api/embeddings",
                files={"file": ("segment.wav", f, "audio/wav")},
                timeout=30.0,
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("embedding")

    except Exception as e:
        logger.warning(f"提取片段声纹失败: {e}")
        return None
    finally:
        if 'tmp_path' in locals():
            Path(tmp_path).unlink(missing_ok=True)


def _recognize_meeting_speakers(db, meeting_id: int, segments: list[dict], audio_path: Path | None = None) -> list[dict]:
    """
    对会议的每个片段进行说话人识别

    优先使用 ASR 返回的 embedding，如果没有则用本地 embedding 服务从音频片段中提取。

    Args:
        db: 数据库会话
        meeting_id: 会议 ID
        segments: ASR 返回的片段列表
        audio_path: 原始音频文件路径（用于截取片段提取声纹）

    Returns:
        带有识别结果的片段列表
    """
    recognized_segments = []
    for seg in segments:
        embedding = seg.get("embedding")

        # 如果 ASR 没返回 embedding，从音频片段中提取
        if not embedding and audio_path and seg.get("start_time") is not None:
            embedding = _extract_segment_embedding(
                audio_path,
                seg.get("start_time"),
                seg.get("end_time"),
            )

        if embedding:
            employee_id, confidence = _recognize_speaker(db, embedding)
        else:
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
        
        # 进行说话人识别（传入音频路径用于本地声纹提取）
        recognized_segments = _recognize_meeting_speakers(db, meeting_id, segments, audio_path=audio_path)
        
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

        # 自动触发任务提取 + 通知推送
        tasks_created = 0
        notifications_sent = 0
        try:
            import asyncio
            from app.agents.task_extract import run_task_extraction
            from app.agents.task_notification import send_task_notifications

            async def _auto_extract_and_notify():
                from app.database import async_session
                async with async_session() as adb:
                    try:
                        fresh_meeting = await adb.get(Meeting, meeting_id)
                        if not fresh_meeting:
                            return 0, 0

                        # 重新加载 segments 关系
                        from sqlalchemy import select as sa_select
                        from sqlalchemy.orm import selectinload
                        result = await adb.execute(
                            sa_select(Meeting)
                            .options(selectinload(Meeting.segments))
                            .where(Meeting.id == meeting_id)
                        )
                        fresh_meeting = result.scalar_one_or_none()
                        if not fresh_meeting or not fresh_meeting.segments:
                            return 0, 0

                        tasks = await run_task_extraction(adb, fresh_meeting)
                        await adb.commit()

                        msg_count = await send_task_notifications(adb, tasks)
                        return len(tasks), msg_count
                    except Exception as e:
                        logger.warning(f"自动任务提取失败: {e}")
                        await adb.rollback()
                        return 0, 0

            tasks_created, notifications_sent = asyncio.run(_auto_extract_and_notify())
            logger.info(f"会议 {meeting_id}: 提取 {tasks_created} 个任务, 发送 {notifications_sent} 条通知")
        except Exception as e:
            logger.warning(f"自动任务提取/通知失败: {e}")

        return {
            "meeting_id": meeting_id,
            "segments": len(segments),
            "recognized_speakers": sum(1 for s in recognized_segments if s.get("employee_id")),
            "tasks_created": tasks_created,
            "notifications_sent": notifications_sent,
        }


@celery_app.task(name="transcribe_meeting", bind=True, max_retries=3)
def transcribe_meeting(self, meeting_id: int) -> dict:
    result = run_transcribe_meeting(meeting_id)
    if "error" in result and self.request.retries < self.max_retries:
        raise self.retry(exc=Exception(result["error"]), countdown=60)
    return result
