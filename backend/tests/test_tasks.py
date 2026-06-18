"""任务管理API测试"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, Task, TaskStatus, Meeting, Message, MessageType
from app.auth import hash_password


class TestTaskList:
    """任务列表测试"""

    @pytest.mark.asyncio
    async def test_list_tasks_empty(
        self, test_client: AsyncClient, test_employee: Employee, auth_headers: dict
    ):
        """测试空任务列表"""
        response = await test_client.get("/tasks", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["tasks"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_tasks_with_data(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试有数据的任务列表"""
        # 创建测试任务
        task = Task(
            title="测试任务",
            description="测试描述",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()

        response = await test_client.get("/tasks", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["title"] == "测试任务"

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_status(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试按状态过滤任务"""
        # 创建多个不同状态的任务
        for status in [TaskStatus.pending, TaskStatus.accepted, TaskStatus.completed]:
            task = Task(
                title=f"任务-{status.value}",
                status=status,
                executor_id=test_employee.id,
            )
            test_session.add(task)
        await test_session.commit()

        # 测试过滤 pending 状态
        response = await test_client.get("/tasks?status=pending", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_tasks_invalid_status(
        self, test_client: AsyncClient, auth_headers: dict
    ):
        """测试无效状态过滤"""
        response = await test_client.get("/tasks?status=invalid_status", headers=auth_headers)
        assert response.status_code == 400
        assert "Invalid status" in response.json()["detail"]


class TestTaskDetail:
    """任务详情测试"""

    @pytest.mark.asyncio
    async def test_get_task_success(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试获取任务详情"""
        task = Task(
            title="测试任务详情",
            description="详细描述",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        response = await test_client.get(f"/tasks/{task.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "测试任务详情"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, test_client: AsyncClient, auth_headers: dict):
        """测试获取不存在的任务"""
        response = await test_client.get("/tasks/99999", headers=auth_headers)
        assert response.status_code == 404
        assert "Task not found" in response.json()["detail"]


class TestTaskReply:
    """任务操作测试"""

    @pytest.mark.asyncio
    async def test_accept_task(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试接受任务"""
        task = Task(
            title="待接受任务",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        response = await test_client.post(
            f"/tasks/{task.id}/reply",
            json={"action": "accept"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["task"]["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_complete_task(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试完成任务"""
        task = Task(
            title="待完成任务",
            status=TaskStatus.in_progress,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        response = await test_client.post(
            f"/tasks/{task.id}/reply",
            json={"action": "complete"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["task"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_reject_task_without_reason(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试拒绝任务时不提供原因"""
        task = Task(
            title="待拒绝任务",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        response = await test_client.post(
            f"/tasks/{task.id}/reply",
            json={"action": "reject"},
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "Reason required" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_reject_task_with_reason(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试拒绝任务时提供原因"""
        task = Task(
            title="待拒绝任务",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        response = await test_client.post(
            f"/tasks/{task.id}/reply",
            json={"action": "reject", "reason": "任务冲突无法完成"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["task"]["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_mark_incomplete_with_reason(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试标记未完成并提供原因"""
        task = Task(
            title="未完成任务",
            status=TaskStatus.in_progress,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        response = await test_client.post(
            f"/tasks/{task.id}/reply",
            json={"action": "incomplete", "reason": "资源不足"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["task"]["status"] == "incomplete"

    @pytest.mark.asyncio
    async def test_invalid_action(self, test_client: AsyncClient, test_session: AsyncSession, test_employee: Employee, auth_headers: dict):
        """测试无效操作"""
        task = Task(
            title="测试任务",
            status=TaskStatus.pending,
            executor_id=test_employee.id,
        )
        test_session.add(task)
        await test_session.commit()
        await test_session.refresh(task)

        response = await test_client.post(
            f"/tasks/{task.id}/reply",
            json={"action": "invalid_action"},
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "Invalid action" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_reply_nonexistent_task(self, test_client: AsyncClient, auth_headers: dict):
        """测试操作不存在的任务"""
        response = await test_client.post(
            "/tasks/99999/reply",
            json={"action": "accept"},
            headers=auth_headers
        )
        assert response.status_code == 404
