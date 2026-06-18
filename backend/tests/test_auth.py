"""认证相关测试"""
import pytest
from httpx import AsyncClient

from app.models import Employee


class TestAuth:
    """认证功能测试"""

    @pytest.mark.asyncio
    async def test_login_success(self, test_client: AsyncClient, test_employee: Employee):
        """测试正常登录"""
        response = await test_client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, test_client: AsyncClient, test_employee: Employee):
        """测试错误密码登录"""
        response = await test_client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "wrongpassword"}
        )
        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, test_client: AsyncClient):
        """测试不存在的用户登录"""
        response = await test_client.post(
            "/auth/login",
            json={"email": "nonexistent@example.com", "password": "password123"}
        )
        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_invalid_email_format(self, test_client: AsyncClient):
        """测试无效邮箱格式"""
        response = await test_client.post(
            "/auth/login",
            json={"email": "not-an-email", "password": "password123"}
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_protected_endpoint_without_token(self, test_client: AsyncClient):
        """测试无Token访问受保护端点"""
        response = await test_client.get("/tasks")
        # FastAPI 的 HTTPBearer 在无 token 时返回 401 或 403
        # 根据实际行为，可能是 401 (Unauthorized)
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_invalid_token(self, test_client: AsyncClient):
        """测试无效Token访问受保护端点"""
        response = await test_client.get(
            "/tasks",
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401  # Unauthorized - invalid token
