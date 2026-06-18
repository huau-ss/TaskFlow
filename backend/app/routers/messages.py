"""消息 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import Employee
from app.schemas import MessageListResponse, MessageResponse
from app.services import message as message_service

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("", response_model=MessageListResponse)
async def list_messages(
    unread_only: bool = Query(False, description="只返回未读消息"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取当前用户的消息列表"""
    messages, total = await message_service.get_user_messages(
        db, current_user.id, unread_only=unread_only, limit=limit, offset=offset
    )
    unread_count = await message_service.get_unread_count(db, current_user.id)

    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        unread_count=unread_count,
        total=total,
    )


@router.get("/unread-count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取未读消息数量"""
    count = await message_service.get_unread_count(db, current_user.id)
    return {"unread_count": count}


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取消息详情"""
    message = await message_service.get_message_by_id(db, message_id, current_user.id)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    return MessageResponse.model_validate(message)


@router.post("/{message_id}/read")
async def mark_as_read(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """标记消息为已读"""
    message = await message_service.mark_message_read(db, message_id, current_user.id)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    return {"success": True}


@router.post("/read-all")
async def mark_all_as_read(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """标记所有消息为已读"""
    from datetime import datetime
    from app.models import Message

    query = Message.__table__.update().where(
        Message.recipient_id == current_user.id,
        Message.is_read == False,
    ).values(is_read=True, read_at=datetime.utcnow())

    await db.execute(query)
    await db.commit()

    return {"success": True}
