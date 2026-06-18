"""API服务测试"""
import pytest
from httpx import AsyncClient

from app.models import Employee, Task, TaskStatus


class TestHealthEndpoint:
    """健康检查端点测试"""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, test_client: AsyncClient):
        """测试健康检查端点"""
        response = await test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_docs_endpoint(self, test_client: AsyncClient):
        """测试API文档端点"""
        response = await test_client.get("/docs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_endpoint(self, test_client: AsyncClient):
        """测试OpenAPI JSON端点"""
        response = await test_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data

    @pytest.mark.asyncio
    async def test_health_services_endpoint(self, test_client: AsyncClient):
        """测试服务健康检查端点"""
        response = await test_client.get("/health/services")
        assert response.status_code == 200
        data = response.json()
        assert "asr" in data
        assert "llm" in data
