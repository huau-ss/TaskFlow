"""会议转写相关端点：LLM 优化、HTML 导出。"""

import json
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Employee, Meeting, TranscriptSegment

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _build_llm_client() -> httpx.AsyncClient:
    """构建 LLM HTTP 客户端（兼容 OpenAI 协议）。"""
    return httpx.AsyncClient(
        base_url=settings.llm_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key or 'not-needed'}",
            "Content-Type": "application/json",
        },
        timeout=120.0,
    )


def _speaker_to_letter(label: str) -> str:
    """SPEAKER_00 → A, SPEAKER_01 → B, ..."""
    if label.upper().startswith("SPEAKER_"):
        try:
            idx = int(label.rsplit("_", 1)[-1])
            return chr(ord("A") + idx)
        except (ValueError, IndexError):
            return label
    return label


def _format_segments_with_letters(segments: list[dict]) -> str:
    """格式化转写文本，说话人标签用 A/B/C 格式。"""
    lines = []
    for seg in sorted(segments, key=lambda s: s.get("sequence", 0)):
        speaker = _speaker_to_letter(seg.get("speaker_label", "?"))
        text = seg.get("text", "")
        lines.append(f"{speaker}：{text}")
    return "\n\n".join(lines)


OPTIMIZE_SYSTEM = """你是专业的会议纪要整理助手。请将以下语音转写文本优化为书面表达：

1. 去除口头禅和冗余词（如"嗯"、"啊"、"那个"、重复的话）
2. 修正语音识别的常见误差（同音字错误、断句错误）
3. 重组段落逻辑，使内容更连贯易读
4. 保留所有关键信息、决策、数据
5. 将说话人标签 SPEAKER_XX 替换为字母标识（A、B、C、D...），格式为 "A：内容"
6. 不要添加原文没有的内容
7. 保持原有的段落结构，不要过度合并

直接输出优化后的文本，不要加任何前缀或说明。"""


@router.post("/{meeting_id}/optimize")
async def optimize_transcript(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """对已转写的会议文本做 LLM 优化，去除口头禅、修正误差、重组逻辑。

    优化结果会持久化到 Meeting.optimized_text 字段。
    """
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not current_user.is_admin and meeting.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问该会议")
    if meeting.status.value != "transcribed":
        raise HTTPException(
            status_code=400,
            detail=f"Meeting not transcribed (status={meeting.status.value})",
        )

    # 如果已有优化结果，直接返回
    if meeting.optimized_text:
        segments_result = await db.execute(
            select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
        )
        segments = segments_result.scalars().all()
        return {
            "meeting_id": meeting_id,
            "verbatim_text": _format_segments_with_letters([
                {
                    "speaker_label": s.speaker_label,
                    "text": s.text,
                    "sequence": s.sequence,
                }
                for s in segments
            ]),
            "optimized_text": meeting.optimized_text,
            "speaker_count": len(set(s.speaker_label for s in segments)),
        }

    # 加载转写片段
    segments_result = await db.execute(
        select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
    )
    segments = segments_result.scalars().all()

    if not segments:
        raise HTTPException(status_code=400, detail="No transcript segments found")

    # 格式化转写文本（用 A/B/C 格式）
    verbatim_text = _format_segments_with_letters([
        {
            "speaker_label": s.speaker_label,
            "text": s.text,
            "sequence": s.sequence,
        }
        for s in segments
    ])

    # 调用 LLM 优化
    try:
        async with _build_llm_client() as client:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": OPTIMIZE_SYSTEM},
                        {"role": "user", "content": verbatim_text},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 8192,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # 提取 LLM 回复
        optimized = data["choices"][0]["message"]["content"].strip()

        # 持久化
        meeting.optimized_text = optimized
        await db.commit()
        await db.refresh(meeting)

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 优化失败: {e}")

    speaker_count = len(set(s.speaker_label for s in segments))
    return {
        "meeting_id": meeting_id,
        "verbatim_text": verbatim_text,
        "optimized_text": optimized,
        "speaker_count": speaker_count,
    }


@router.get("/{meeting_id}/export/html", response_class=HTMLResponse)
async def export_transcript_html(
    meeting_id: int,
    version: str = Query("both", description="显示模式: both, verbatim, optimized"),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """导出会议转写结果为 HTML 页面。

    参数:
    - version=both: 双栏对比（逐字稿 + 优化稿），默认
    - version=verbatim: 仅逐字稿
    - version=optimized: 仅优化稿
    """
    if version not in ("both", "verbatim", "optimized"):
        raise HTTPException(status_code=400, detail="version 必须是 both, verbatim 或 optimized")

    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not current_user.is_admin and meeting.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问该会议")
    if meeting.status.value != "transcribed":
        raise HTTPException(status_code=400, detail="Meeting not transcribed")

    # 加载转写片段
    segments_result = await db.execute(
        select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
    )
    segments = segments_result.scalars().all()

    if not segments:
        raise HTTPException(status_code=400, detail="No transcript segments found")

    verbatim_text = _format_segments_with_letters([
        {
            "speaker_label": s.speaker_label,
            "text": s.text,
            "sequence": s.sequence,
        }
        for s in segments
    ])

    optimized_text = meeting.optimized_text

    if version == "optimized" and not optimized_text:
        raise HTTPException(
            status_code=400,
            detail="暂无优化稿。请先调用 POST /transcripts/{meeting_id}/optimize 生成优化稿。",
        )

    title = meeting.title or meeting.original_filename or f"会议 #{meeting_id}"

    from app.services.transcript_export import build_transcript_page
    html_content = build_transcript_page(
        title=title,
        meeting_id=meeting_id,
        verbatim_text=verbatim_text,
        optimized_text=optimized_text,
        version=version,  # type: ignore[arg-type]
    )
    return HTMLResponse(content=html_content)


@router.get("/{meeting_id}/segments")
async def get_transcript_segments(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取会议转写片段列表，说话人标签转换为 A/B/C 格式。"""
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not current_user.is_admin and meeting.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问该会议")

    segments_result = await db.execute(
        select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
    )
    segments = segments_result.scalars().all()

    return {
        "meeting_id": meeting_id,
        "status": meeting.status.value,
        "segments": [
            {
                "id": s.id,
                "speaker_label": s.speaker_label,
                "speaker_display": _speaker_to_letter(s.speaker_label),
                "employee_id": s.employee_id,
                "text": s.text,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "sequence": s.sequence,
            }
            for s in segments
        ],
    }
