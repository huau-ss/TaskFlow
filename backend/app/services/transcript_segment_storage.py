"""转写片段 NAS 存储服务

存储策略：
- 转写完成后，将片段写入 NAS JSON 文件
- 数据库 transcript_segments 表仍保留完整数据（向后兼容）
- 后续读取优先从 NAS（快速），NAS 不可用时回退 DB

文件命名：/home/admin/nas/meetings/transcript_segments/{meeting_id}.json
文件格式：
{
  "meeting_id": 123,
  "segments": [
    {
      "id": 1,
      "speaker_label": "SPEAKER_00",
      "employee_id": 5,
      "text": "请在下周三前完成调研报告。",
      "start_time": 0.0,
      "end_time": 5.0,
      "sequence": 0
    }
  ]
}
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models import TranscriptSegment

logger = logging.getLogger(__name__)


def _get_segments_dir() -> Path:
    """获取片段存储目录，确保存在"""
    root = Path(settings.transcript_segments_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _segments_file(meeting_id: int) -> Path:
    """获取指定会议的片段文件路径"""
    return _get_segments_dir() / f"{meeting_id}.json"


def save_segments(meeting_id: int, segments: list[dict]) -> str | None:
    """
    将转写片段写入 NAS JSON 文件。

    Args:
        meeting_id: 会议 ID（用作文件名）
        segments: 片段列表，每项包含 id/speaker_label/employee_id/text/
                  start_time/end_time/sequence

    Returns:
        NAS 文件路径，失败返回 None
    """
    try:
        payload = {
            "meeting_id": meeting_id,
            "segments": [
                {
                    "id": seg.get("id"),
                    "speaker_label": seg.get("speaker_label"),
                    "employee_id": seg.get("employee_id"),
                    "text": seg.get("text"),
                    "start_time": seg.get("start_time"),
                    "end_time": seg.get("end_time"),
                    "sequence": seg.get("sequence"),
                }
                for seg in segments
                if seg.get("text", "").strip()
            ],
        }
        path = _segments_file(meeting_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"转写片段已保存至 NAS: {path}")
        return str(path)
    except Exception as e:
        logger.warning(f"写入 NAS 转写片段失败: {e}")
        return None


def load_segments(meeting_id: int) -> list[dict] | None:
    """
    从 NAS JSON 文件读取转写片段。

    Returns:
        片段列表，文件不存在或读取失败返回 None（调用方应回退 DB）
    """
    try:
        path = _segments_file(meeting_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("segments", [])
    except Exception as e:
        logger.warning(f"读取 NAS 转写片段失败 (meeting_id={meeting_id}): {e}")
        return None


def delete_segments(meeting_id: int) -> bool:
    """删除指定会议的 NAS 片段文件"""
    try:
        path = _segments_file(meeting_id)
        if path.exists():
            path.unlink()
            logger.info(f"已删除 NAS 转写片段: {path}")
        return True
    except Exception as e:
        logger.warning(f"删除 NAS 转写片段失败: {e}")
        return False


# ── 统一读取入口：NAS 优先，回退 DB ────────────────────────────────

async def get_meeting_segments_async(
    db: AsyncSession, meeting_id: int
) -> list[TranscriptSegment]:
    """
    统一读取会议转写片段：NAS-first，NAS 不可用时回退 DB。

    适用于所有 async 上下文（FastAPI 路由、LangGraph 节点等）。
    """
    # 优先从 NAS 读取
    nas_segments = load_segments(meeting_id)
    if nas_segments is not None:
        logger.debug(f"会议 {meeting_id} 从 NAS 读取 {len(nas_segments)} 个片段")
        return [
            TranscriptSegment(
                id=seg["id"] or 0,
                meeting_id=meeting_id,
                speaker_label=seg["speaker_label"],
                employee_id=seg.get("employee_id"),
                text=seg["text"],
                start_time=seg.get("start_time"),
                end_time=seg.get("end_time"),
                sequence=seg.get("sequence") or 0,
            )
            for seg in nas_segments
            if seg.get("text", "").strip()
        ]

    # 回退到 DB
    result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting_id)
        .order_by(TranscriptSegment.sequence)
    )
    segments = list(result.scalars().all())
    logger.debug(f"会议 {meeting_id} 从 DB 回退读取 {len(segments)} 个片段")
    return segments


def get_meeting_segments_sync(
    db: Session, meeting_id: int
) -> list[TranscriptSegment]:
    """
    统一读取会议转写片段（同步版本）：NAS-first，NAS 不可用时回退 DB。

    适用于 Celery worker 等同步上下文。
    """
    nas_segments = load_segments(meeting_id)
    if nas_segments is not None:
        logger.debug(f"会议 {meeting_id} 从 NAS 读取 {len(nas_segments)} 个片段")
        return [
            TranscriptSegment(
                id=seg["id"] or 0,
                meeting_id=meeting_id,
                speaker_label=seg["speaker_label"],
                employee_id=seg.get("employee_id"),
                text=seg["text"],
                start_time=seg.get("start_time"),
                end_time=seg.get("end_time"),
                sequence=seg.get("sequence") or 0,
            )
            for seg in nas_segments
            if seg.get("text", "").strip()
        ]

    segments = list(
        db.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.sequence)
        ).scalars().all()
    )
    logger.debug(f"会议 {meeting_id} 从 DB 回退读取 {len(segments)} 个片段")
    return segments
