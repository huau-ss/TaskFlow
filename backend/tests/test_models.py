"""模型枚举和字段验证测试"""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Task, TaskStatus, Employee, Meeting, MeetingStatus,
    Message, MessageType, VoicePrint, TranscriptSegment
)
from app.auth import hash_password


class TestTaskStatusEnum:
    """任务状态枚举测试"""

    def test_all_statuses_defined(self):
        """验证所有任务状态都已定义"""
        expected_statuses = {
            "pending", "accepted", "rejected", "in_progress",
            "completed", "incomplete", "overdue", "escalated"
        }
        actual_statuses = {s.value for s in TaskStatus}
        assert expected_statuses == actual_statuses

    def test_status_values_are_strings(self):
        """验证状态值是字符串"""
        for status in TaskStatus:
            assert isinstance(status.value, str)


class TestMessageTypeEnum:
    """消息类型枚举测试"""

    def test_all_message_types_defined(self):
        """验证所有消息类型都已定义"""
        expected_types = {
            "task_created", "task_reminder", "task_escalation", "task_response"
        }
        actual_types = {m.value for m in MessageType}
        assert expected_types == actual_types


class TestMeetingStatusEnum:
    """会议状态枚举测试"""

    def test_all_meeting_statuses_defined(self):
        """验证所有会议状态都已定义"""
        expected_statuses = {"uploaded", "transcribing", "transcribed", "failed"}
        actual_statuses = {s.value for s in MeetingStatus}
        assert expected_statuses == actual_statuses


class TestEmployeeModel:
    """员工模型测试"""

    @pytest.mark.asyncio
    async def test_create_employee(self, test_session: AsyncSession):
        """测试创建员工"""
        employee = Employee(
            name="测试员工",
            email="model_test@example.com",
            password_hash=hash_password("password"),
            is_active=True,
        )
        test_session.add(employee)
        await test_session.commit()
        await test_session.refresh(employee)

        assert employee.id is not None
        assert employee.name == "测试员工"
        assert employee.email == "model_test@example.com"
        assert employee.is_active is True
        assert employee.created_at is not None

    @pytest.mark.asyncio
    async def test_employee_with_manager(self, test_session: AsyncSession):
        """测试员工与上级关系"""
        manager = Employee(
            name="经理",
            email="manager_test@example.com",
            password_hash=hash_password("password"),
        )
        test_session.add(manager)
        await test_session.flush()

        employee = Employee(
            name="下属",
            email="subordinate_test@example.com",
            password_hash=hash_password("password"),
            manager_id=manager.id,
        )
        test_session.add(employee)
        await test_session.commit()

        assert employee.manager_id == manager.id
        assert employee.manager.id == manager.id


class TestTaskModel:
    """任务模型测试"""

    @pytest.mark.asyncio
    async def test_create_task(self, test_session: AsyncSession, test_employee: Employee):
        """测试创建任务"""
        task = Task(
            title="测试任务",
            description="测试描述",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
            deadline=datetime.now(timezone.utc) + timedelta(days=7),
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        assert task.id is not None
        assert task.title == "测试任务"
        assert task.status == TaskStatus.pending
        assert task.executor_id == test_employee.id

    @pytest.mark.asyncio
    async def test_task_update_tracking(self, test_session: AsyncSession, test_employee: Employee):
        """测试任务状态更新"""
        task = Task(
            title="状态测试任务",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()

        # 更新状态
        task.status = TaskStatus.accepted
        await test_session.commit()
        await test_session.refresh(task)

        assert task.status == TaskStatus.accepted


class TestMessageModel:
    """消息模型测试"""

    @pytest.mark.asyncio
    async def test_create_message(self, test_session: AsyncSession, test_employee: Employee):
        """测试创建消息"""
        message = Message(
            type=MessageType.task_created,
            title="新任务通知",
            content="您有一个新任务",
            recipient_id=test_employee.id,
            is_read=False,
        )
        test_session.add(message)
        await test_session.commit()
        await test_session.refresh(message)

        assert message.id is not None
        assert message.type == MessageType.task_created
        assert message.is_read is False

    @pytest.mark.asyncio
    async def test_message_action_tracking(self, test_session: AsyncSession, test_employee: Employee):
        """测试消息操作追踪"""
        message = Message(
            type=MessageType.task_created,
            title="测试消息",
            recipient_id=test_employee.id,
        )
        test_session.add(message)
        await test_session.flush()

        # 添加操作记录
        from app.models import MessageAction
        action = MessageAction(
            message_id=message.id,
            action="accept",
            reason="测试接受",
        )
        test_session.add(action)
        await test_session.commit()

        assert action.id is not None
        assert action.action == "accept"
