"""员工管理API测试"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, TaskStatus
from app.auth import hash_password
from app.models import Task


class TestEmployeeList:
    """员工列表测试"""

    @pytest.mark.asyncio
    async def test_list_employees(
        self, test_client: AsyncClient, test_admin: Employee, auth_headers: dict
    ):
        """测试获取员工列表"""
        response = await test_client.get("/employees", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # API 返回数组，不是 {total, employees} 对象
        assert isinstance(data, list)
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_list_employees_own_profile(
        self, test_client: AsyncClient, test_employee: Employee, auth_headers: dict
    ):
        """测试获取自己的员工信息"""
        response = await test_client.get(f"/employees/{test_employee.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_employee.email


class TestEmployeeCreate:
    """员工创建测试 - 需要管理员权限"""

    @pytest.mark.asyncio
    async def test_create_employee_by_admin(
        self, test_client: AsyncClient, test_admin: Employee, auth_headers: dict
    ):
        """测试管理员创建新员工"""
        # 使用管理员的 auth_headers
        admin_response = await test_client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin123"}
        )
        admin_token = admin_response.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        response = await test_client.post(
            "/employees",
            json={
                "name": "新员工",
                "email": "newemployee@example.com",
                "password": "password123",
                "manager_id": test_admin.id,
            },
            headers=admin_headers
        )
        assert response.status_code == 201  # 201 Created
        data = response.json()
        assert data["name"] == "新员工"
        assert data["email"] == "newemployee@example.com"

    @pytest.mark.asyncio
    async def test_create_employee_without_admin_fails(
        self, test_client: AsyncClient, test_admin: Employee, auth_headers: dict
    ):
        """测试非管理员创建员工失败（返回403）"""
        # 普通员工尝试创建（应该失败）
        response = await test_client.post(
            "/employees",
            json={
                "name": "非法创建",
                "email": "illegal@example.com",
                "password": "password123",
            },
            headers=auth_headers  # 普通员工的 token
        )
        assert response.status_code == 403
        assert "Admin permission required" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_employee_duplicate_email(
        self, test_client: AsyncClient, test_admin: Employee, auth_headers: dict
    ):
        """测试创建重复邮箱的员工"""
        # 使用管理员 token
        admin_response = await test_client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin123"}
        )
        admin_token = admin_response.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 先创建一个员工
        await test_client.post(
            "/employees",
            json={
                "name": "第一个员工",
                "email": "duplicate@example.com",
                "password": "password123",
            },
            headers=admin_headers
        )

        # 尝试用相同邮箱创建
        response = await test_client.post(
            "/employees",
            json={
                "name": "重复邮箱员工",
                "email": "duplicate@example.com",
                "password": "password123",
            },
            headers=admin_headers
        )
        # API 返回 409 Conflict，不是 400
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_employee_short_password(
        self, test_client: AsyncClient, test_admin: Employee, auth_headers: dict
    ):
        """测试创建密码过短的员工"""
        admin_response = await test_client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin123"}
        )
        admin_token = admin_response.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        response = await test_client.post(
            "/employees",
            json={
                "name": "短密码员工",
                "email": "short@example.com",
                "password": "123",
            },
            headers=admin_headers
        )
        assert response.status_code == 422  # Validation error


class TestEmployeeUpdate:
    """员工更新测试 - 需要管理员权限"""

    @pytest.mark.asyncio
    async def test_update_employee_by_admin(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_admin: Employee, auth_headers: dict
    ):
        """测试管理员更新员工信息"""
        admin_response = await test_client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin123"}
        )
        admin_token = admin_response.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 创建一个员工
        new_employee = Employee(
            name="待更新员工",
            email="toupdate@example.com",
            password_hash=hash_password("password123"),
        )
        test_session.add(new_employee)
        await test_session.commit()
        await test_session.refresh(new_employee)

        # 管理员更新员工
        response = await test_client.put(
            f"/employees/{new_employee.id}",
            json={"name": "已更新员工"},
            headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "已更新员工"

    @pytest.mark.asyncio
    async def test_update_employee_without_admin_fails(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_employee: Employee, auth_headers: dict
    ):
        """测试非管理员更新员工失败"""
        # 创建另一个员工
        other_employee = Employee(
            name="其他员工",
            email="other@example.com",
            password_hash=hash_password("password123"),
        )
        test_session.add(other_employee)
        await test_session.commit()
        await test_session.refresh(other_employee)

        # 普通员工尝试更新（应该失败）
        response = await test_client.put(
            f"/employees/{other_employee.id}",
            json={"name": "非法更新"},
            headers=auth_headers
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_employee_set_manager(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_admin: Employee, auth_headers: dict
    ):
        """测试设置员工上级"""
        admin_response = await test_client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin123"}
        )
        admin_token = admin_response.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 创建一个员工
        new_employee = Employee(
            name="待设置上级员工",
            email="withmanager@example.com",
            password_hash=hash_password("password123"),
        )
        test_session.add(new_employee)
        await test_session.commit()
        await test_session.refresh(new_employee)

        # 设置上级
        response = await test_client.put(
            f"/employees/{new_employee.id}",
            json={"manager_id": test_admin.id},
            headers=admin_headers
        )
        assert response.status_code == 200

        # 验证
        detail_response = await test_client.get(
            f"/employees/{new_employee.id}",
            headers=admin_headers
        )
        data = detail_response.json()
        assert data["manager_id"] == test_admin.id


class TestEmployeeHierarchy:
    """员工层级测试"""

    @pytest.mark.asyncio
    async def test_get_subordinates(
        self, test_client: AsyncClient, test_session: AsyncSession,
        test_admin: Employee, auth_headers: dict
    ):
        """测试获取下属列表"""
        admin_response = await test_client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin123"}
        )
        admin_token = admin_response.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 创建下属
        subordinate = Employee(
            name="下属员工",
            email="sub1@example.com",
            password_hash=hash_password("password123"),
            manager_id=test_admin.id,
        )
        test_session.add(subordinate)
        await test_session.commit()

        response = await test_client.get(
            f"/employees/{test_admin.id}/subordinates",
            headers=admin_headers
        )
        assert response.status_code == 200
        # API 返回数组，不是 {total, subordinates} 对象
        data = response.json()
        assert isinstance(data, list)
        assert any(s["email"] == "sub1@example.com" for s in data)
