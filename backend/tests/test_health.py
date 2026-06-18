"""健康检查接口测试"""
import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """健康检查端点测试"""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, test_client: AsyncClient):
        """测试基础健康检查"""
        response = await test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "asr_diarize_url" in data
        assert "llm_url" in data

    @pytest.mark.asyncio
    async def test_health_services_endpoint(self, test_client: AsyncClient):
        """测试服务健康检查"""
        response = await test_client.get("/health/services")
        assert response.status_code == 200
        data = response.json()
        assert "asr" in data
        assert "llm" in data
