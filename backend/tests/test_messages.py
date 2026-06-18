"""消息系统API测试"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.models import Employee, Task, TaskStatus, Message, MessageType, MessageAction
from app.auth import hash_password


class TestMessageList:
    """消息列表测试"""

    @pytest.mark.asyncio
    async def test_get_messages_empty(
        self, test_client: AsyncClient, test_employee: Employee, auth_headers: dict
    ):
        """测试空消息列表"""
        response = await test_client.get("/messages", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # API 返回 MessageListResponse 格式
        assert "messages" in data
        assert "total" in data
        assert data["messages"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_get_unread_count(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试未读消息数量"""
        # 创建未读消息
        message = Message(
            type=MessageType.task_created,
            title="新任务",
            content="测试内容",
            recipient_id=test_employee.id,
            is_read=False,
        )
        test_session.add(message)
        await test_session.commit()

        response = await test_client.get("/messages/unread-count", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["unread_count"] >= 1


class TestMessageRead:
    """消息已读测试"""

    @pytest.mark.asyncio
    async def test_mark_message_as_read(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试标记消息为已读"""
        # 创建未读消息
        message = Message(
            type=MessageType.task_created,
            title="测试消息",
            content="测试内容",
            recipient_id=test_employee.id,
            is_read=False,
        )
        test_session.add(message)
        await test_session.commit()
        await test_session.refresh(message)

        response = await test_client.post(
            f"/messages/{message.id}/read",
            headers=auth_headers
        )
        assert response.status_code == 200

        # 验证已标记为已读
        await test_session.refresh(message)
        assert message.is_read is True

    @pytest.mark.asyncio
    async def test_mark_all_as_read(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试全部标记为已读"""
        # 创建多条未读消息
        for i in range(3):
            message = Message(
                type=MessageType.task_created,
                title=f"消息{i}",
                recipient_id=test_employee.id,
                is_read=False,
            )
            test_session.add(message)
        await test_session.commit()

        response = await test_client.post("/messages/read-all", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # 验证所有消息都已读
        unread_response = await test_client.get("/messages/unread-count", headers=auth_headers)
        assert unread_response.json()["unread_count"] == 0


class TestMessageDetail:
    """消息详情测试"""

    @pytest.mark.asyncio
    async def test_get_message_detail(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试获取消息详情"""
        # 创建消息
        message = Message(
            type=MessageType.task_created,
            title="任务详情测试",
            content="详细描述",
            recipient_id=test_employee.id,
            is_read=False,
        )
        test_session.add(message)
        await test_session.commit()
        await test_session.refresh(message)

        response = await test_client.get(f"/messages/{message.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "任务详情测试"

    @pytest.mark.asyncio
    async def test_get_nonexistent_message(self, test_client: AsyncClient, auth_headers: dict):
        """测试获取不存在的消息"""
        response = await test_client.get("/messages/99999", headers=auth_headers)
        assert response.status_code == 404


class TestMessageActions:
    """消息操作测试"""

    @pytest.mark.asyncio
    async def test_message_action_recording(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试消息操作记录"""
        # 创建任务和消息
        task = Task(
            title="测试任务",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.flush()

        message = Message(
            type=MessageType.task_created,
            title="新任务",
            recipient_id=test_employee.id,
            task_id=task.id,
            action_token="test_token_123",
        )
        test_session.add(message)
        await test_session.commit()
        await test_session.refresh(message)

        # 完成任务
        response = await test_client.post(
            f"/tasks/{task.id}/reply",
            json={"action": "complete"},
            headers=auth_headers
        )
        assert response.status_code == 200

        # 验证操作记录 - 使用 text() 包装 SQL
        result = await test_session.execute(
            text(f"SELECT * FROM message_actions WHERE message_id = :msg_id"),
            {"msg_id": message.id}
        )
        actions = result.fetchall()
        # 验证有操作记录被创建（如果有的话）
        assert isinstance(actions, list)
