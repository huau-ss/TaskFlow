"""会议关联分析 Agent。

基于 LLM 自动分析已转录会议之间的关联关系：

关联类型：
- follow_up:      后续会议（同一议题的延续，如"需求评审"→"评审结果确认"）
- related:        相关会议（同项目/同客户讨论，无明确先后顺序）
- prerequisite:   前置会议（B 依赖 A 的结果才能进行）

分析策略：
1. 汇总所有已转录会议的关键信息（标题、时间、摘要）
2. 提取每个会议的主题关键词和关键议题
3. 两两对比，计算关联度
4. LLM 综合判断，输出带置信度和理由的关联关系
"""

import json
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Meeting, MeetingRelation, MeetingStatus, RelationType


class RelationState(TypedDict, total=False):
    meetings: list[dict]
    relations: list[dict]
    errors: list[str]


SYSTEM_PROMPT = """你是会议关联分析专家。根据多个会议的转写文本，分析它们之间的语义关联。

## 关联类型定义

- **follow_up**: 后续会议。特征：会议B提到"上次/上周/之前讨论的"、会议B是会议A的延续讨论、会议B的议题承接A的结论。
- **related**: 相关会议。同一个项目/客户的多个讨论、同一批人参与的不同议题、无明确先后但语义相关。
- **prerequisite**: 前置依赖。会议B的议题依赖会议A的结果才能确定（如方案确认后才能实施）。

## 输出格式

必须输出 JSON 数组，每项包含：
- meeting_a_id: 前置/前序会议 ID（数字）
- meeting_b_id: 后续/后序会议 ID（数字）
- relation_type: 关联类型（follow_up / related / prerequisite 之一）
- confidence: 置信度（0.0–1.0），数值越高越确定
- reason: 判断理由，说明从哪些文本内容推断出关联（100字以内）

**重要**：
- 只输出确定的关联（confidence >= 0.6），低于此阈值不要输出
- 不要臆造 ID，只使用输入中提供的 meeting_id
- meeting_a_id 和 meeting_b_id 不能相同
- 同一对会议只输出一次（选置信度最高的 relation_type）
- 若无任何关联，输出空数组 []

只输出 JSON，不要其他文字。"""


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.llm_url,
        api_key=settings.llm_api_key or "not-needed",
        model=settings.llm_model,
        temperature=0,
    )


async def _load_meetings(db: AsyncSession, meeting_ids: list[int] | None = None) -> list[dict]:
    """加载已转录/已处理会议及其转写文本"""
    query = select(Meeting).where(
        Meeting.status.in_([MeetingStatus.transcribed, MeetingStatus.processed])
    )
    if meeting_ids:
        query = query.where(Meeting.id.in_(meeting_ids))

    result = await db.execute(query.order_by(Meeting.created_at))
    meetings = result.scalars().all()

    from app.services.transcript_segment_storage import get_meeting_segments_async

    meeting_summaries = []
    for m in meetings:
        segments = await get_meeting_segments_async(db, m.id)

        full_text = "\n".join(
            f"[{s.speaker_label}]: {s.text}" for s in segments
        )
        # 取前 2000 字作为摘要（避免 token 过长）
        summary = full_text[:2000] if full_text else "(无转写文本)"

        meeting_summaries.append({
            "id": m.id,
            "title": m.title or "(无标题)",
            "created_at": m.created_at.isoformat() if m.created_at else "",
            "text": summary,
        })

    return meeting_summaries


async def _call_llm(meetings: list[dict]) -> list[dict]:
    """调用 LLM 分析会议关联"""
    llm = _build_llm()

    meetings_text = "\n".join(
        f"## Meeting {m['id']}: {m['title']} (创建时间: {m['created_at']})\n"
        f"转写摘要：\n{m['text']}\n"
        for m in meetings
    )

    prompt = f"请分析以下所有会议之间的关联关系：\n\n{meetings_text}"

    response = await llm.ainvoke(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )

    content = response.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        relations = json.loads(content)
        if not isinstance(relations, list):
            return []
        return relations
    except json.JSONDecodeError:
        return []


async def _persist_relations(db: AsyncSession, relations: list[dict]) -> list[MeetingRelation]:
    """持久化关联关系，返回新增或更新的 MeetingRelation 列表。

    存储规则：meeting_a_id < meeting_b_id（唯一约束）。
    - follow_up / prerequisite：A 是前序/前置，B 是后续/后置
    - related：无方向语义，小 ID 为 A
    """
    created_or_updated: list[MeetingRelation] = []
    for rel in relations:
        meeting_a_id = rel.get("meeting_a_id")
        meeting_b_id = rel.get("meeting_b_id")
        if not meeting_a_id or not meeting_b_id or meeting_a_id == meeting_b_id:
            continue

        # 统一小 ID 在前，符合数据库唯一约束
        stored_a_id, stored_b_id = (
            (meeting_a_id, meeting_b_id)
            if meeting_a_id < meeting_b_id
            else (meeting_b_id, meeting_a_id)
        )

        # 关联类型：follow_up / prerequisite 有方向性
        relation_type_str = rel.get("relation_type", "related")
        try:
            rel_type = RelationType(relation_type_str)
        except ValueError:
            rel_type = RelationType.related

        confidence = float(rel.get("confidence", 0))
        reason = rel.get("reason")

        # 检查是否已存在（按唯一约束查询）
        existing = await db.execute(
            select(MeetingRelation).where(
                and_(
                    MeetingRelation.meeting_a_id == stored_a_id,
                    MeetingRelation.meeting_b_id == stored_b_id,
                )
            )
        )
        existing_rel = existing.scalar_one_or_none()
        if existing_rel:
            existing_rel.confidence = confidence
            existing_rel.reason = reason
            existing_rel.relation_type = rel_type
            db.add(existing_rel)
            created_or_updated.append(existing_rel)
        else:
            new_rel = MeetingRelation(
                meeting_a_id=stored_a_id,
                meeting_b_id=stored_b_id,
                relation_type=rel_type,
                confidence=confidence,
                reason=reason,
            )
            db.add(new_rel)
            await db.flush()
            created_or_updated.append(new_rel)

    return created_or_updated


async def analyze_relations(
    db: AsyncSession, meeting_ids: list[int] | None = None
) -> list[MeetingRelation]:
    """
    主入口：分析会议关联并持久化。

    Args:
        db: 数据库会话
        meeting_ids: 可选，指定只分析这些会议；默认分析所有已转录会议

    Returns:
        新增或更新的 MeetingRelation 列表
    """
    meetings = await _load_meetings(db, meeting_ids)

    if len(meetings) < 2:
        return []  # 至少需要 2 个会议才能分析关联

    relations_raw = await _call_llm(meetings)
    if not relations_raw:
        return []

    created = await _persist_relations(db, relations_raw)
    return created


async def delete_relations_for_meeting(db: AsyncSession, meeting_id: int) -> int:
    """
    删除与某会议相关的所有关联关系（用于会议被删除时清理）。
    返回删除的记录数。
    """
    result = await db.execute(
        delete(MeetingRelation).where(
            or_(
                MeetingRelation.meeting_a_id == meeting_id,
                MeetingRelation.meeting_b_id == meeting_id,
            )
        )
    )
    return result.rowcount
