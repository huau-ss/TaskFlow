"""测试配置"""
import pytest
import asyncio
from typing import AsyncGenerator

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import Employee
from app.auth import hash_password


# 使用 SQLite 内存数据库进行测试
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def test_engine():
    """创建测试数据库引擎"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """创建测试数据库会话"""
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as session:
        yield session


@pytest.fixture(scope="function")
async def test_client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """创建测试客户端"""

    async def override_get_db():
        yield test_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def test_employee(test_session: AsyncSession) -> Employee:
    """创建测试员工"""
    employee = Employee(
        name="测试用户",
        email="test@example.com",
        password_hash=hash_password("password123"),
        is_active=True,
        is_admin=False,
    )
    test_session.add(employee)
    await test_session.commit()
    await test_session.refresh(employee)
    return employee


@pytest.fixture
async def test_admin(test_session: AsyncSession) -> Employee:
    """创建测试管理员"""
    admin = Employee(
        name="管理员",
        email="admin@example.com",
        password_hash=hash_password("admin123"),
        is_active=True,
        is_admin=True,
    )
    test_session.add(admin)
    await test_session.commit()
    await test_session.refresh(admin)
    return admin


@pytest.fixture
async def test_employee_with_manager(test_session: AsyncSession, test_admin: Employee) -> Employee:
    """创建有上级的测试员工"""
    employee = Employee(
        name="下属员工",
        email="subordinate@example.com",
        password_hash=hash_password("sub123"),
        is_active=True,
        is_admin=False,
        manager_id=test_admin.id,
    )
    test_session.add(employee)
    await test_session.commit()
    await test_session.refresh(employee)
    return employee


@pytest.fixture
async def auth_headers(test_client: AsyncClient, test_employee: Employee) -> dict:
    """获取认证头"""
    response = await test_client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "password123"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
