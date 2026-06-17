"""Seed admin user and sample org structure."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.auth import hash_password
from app.database import async_session
from app.models import Employee


async def seed():
    async with async_session() as db:
        existing = await db.execute(select(Employee).where(Employee.email == "admin@company.com"))
        if existing.scalar_one_or_none():
            print("Seed data already exists, skipping.")
            return

        admin = Employee(
            name="管理员",
            email="admin@company.com",
            password_hash=hash_password("admin123"),
            is_admin=True,
        )
        db.add(admin)
        await db.flush()

        manager = Employee(
            name="张经理",
            email="zhang@company.com",
            password_hash=hash_password("demo123"),
            manager_id=admin.id,
        )
        db.add(manager)
        await db.flush()

        emp1 = Employee(
            name="李明",
            email="liming@company.com",
            password_hash=hash_password("demo123"),
            manager_id=manager.id,
        )
        emp2 = Employee(
            name="王芳",
            email="wangfang@company.com",
            password_hash=hash_password("demo123"),
            manager_id=manager.id,
        )
        db.add_all([emp1, emp2])
        await db.commit()
        print("Seeded: admin@company.com / admin123, plus sample employees.")


if __name__ == "__main__":
    asyncio.run(seed())
