import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import hash_password
from app.database import get_db
from app.deps import get_current_user
from app.models import Employee
from app.schemas import EmployeeCreate, EmployeeResponse, EmployeeUpdate, EmployeeWithManager

router = APIRouter(prefix="/employees", tags=["employees"])


async def _validate_manager_chain(
    db: AsyncSession,
    employee_id: int,
    new_manager_id: int,
) -> None:
    """验证新的上级设置不会形成循环引用，抛出异常如果无效"""
    if employee_id == new_manager_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot set employee as their own manager",
        )

    visited: set[int] = {employee_id}
    current_id = new_manager_id
    depth = 0
    max_depth = 50

    while current_id is not None:
        if current_id in visited:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Circular reference detected: setting this manager would create a loop",
            )
        if depth > max_depth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager chain too deep",
            )

        visited.add(current_id)
        result = await db.execute(select(Employee).where(Employee.id == current_id))
        emp = result.scalar_one_or_none()
        if emp is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager not found",
            )
        current_id = emp.manager_id
        depth += 1


async def _check_email_uniqueness(
    db: AsyncSession,
    email: str,
    exclude_id: int | None = None,
) -> None:
    """检查邮箱是否已被其他员工使用"""
    query = select(Employee).where(
        Employee.email == email,
        Employee.is_active.is_(True),
    )
    if exclude_id is not None:
        query = query.where(Employee.id != exclude_id)

    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists",
        )


def _require_admin(current_user: Employee) -> None:
    """验证当前用户是管理员"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required",
        )


@router.get("", response_model=list[EmployeeResponse])
async def list_employees(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    result = await db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.id))
    return result.scalars().all()


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    _require_admin(current_user)

    await _check_email_uniqueness(db, body.email)

    if body.manager_id:
        result = await db.execute(select(Employee).where(Employee.id == body.manager_id))
        manager = result.scalar_one_or_none()
        if not manager:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager not found",
            )
        if not manager.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set inactive employee as manager",
            )

    employee = Employee(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        manager_id=body.manager_id,
    )
    db.add(employee)
    await db.flush()
    await db.refresh(employee)
    return employee


@router.post("/import-csv", status_code=status.HTTP_201_CREATED)
async def import_employees_csv(
    file: UploadFile = File(...),
    default_password: str = "demo123",
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    _require_admin(current_user)

    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    created = 0
    email_to_id: dict[str, int] = {}

    result = await db.execute(select(Employee))
    for emp in result.scalars().all():
        email_to_id[emp.email.lower()] = emp.id

    rows = list(reader)
    for row in rows:
        name = (row.get("name") or row.get("姓名") or "").strip()
        email = (row.get("email") or row.get("邮箱") or "").strip().lower()
        if not name or not email:
            continue
        if email in email_to_id:
            continue
        employee = Employee(
            name=name,
            email=email,
            password_hash=hash_password(default_password),
        )
        db.add(employee)
        await db.flush()
        email_to_id[email] = employee.id
        created += 1

    for row in rows:
        email = (row.get("email") or row.get("邮箱") or "").strip().lower()
        manager_email = (row.get("manager_email") or row.get("上级邮箱") or "").strip().lower()
        if not email or not manager_email:
            continue
        emp_id = email_to_id.get(email)
        mgr_id = email_to_id.get(manager_email)
        if emp_id and mgr_id:
            result = await db.execute(select(Employee).where(Employee.id == emp_id))
            employee = result.scalar_one_or_none()
            if employee:
                employee.manager_id = mgr_id

    await db.flush()
    return {"created": created, "total_in_csv": len(rows)}


@router.get("/{employee_id}", response_model=EmployeeWithManager)
async def get_employee(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    result = await db.execute(
        select(Employee).options(selectinload(Employee.manager)).where(Employee.id == employee_id)
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


@router.get("/{employee_id}/subordinates", response_model=list[EmployeeResponse])
async def get_subordinates(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    result = await db.execute(
        select(Employee).where(Employee.manager_id == employee_id, Employee.is_active.is_(True))
    )
    return result.scalars().all()


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: int,
    body: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    _require_admin(current_user)

    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if body.name is not None:
        employee.name = body.name

    if body.email is not None:
        await _check_email_uniqueness(db, body.email, exclude_id=employee_id)
        employee.email = body.email

    if body.manager_id is not None:
        await _validate_manager_chain(db, employee_id, body.manager_id)

        if not body.manager_id:
            employee.manager_id = None
        else:
            result = await db.execute(select(Employee).where(Employee.id == body.manager_id))
            manager = result.scalar_one_or_none()
            if not manager:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Manager not found",
                )
            if not manager.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot set inactive employee as manager",
                )
            employee.manager_id = body.manager_id

    if body.is_active is not None:
        if not body.is_active:
            subordinates_result = await db.execute(
                select(Employee).where(
                    Employee.manager_id == employee_id,
                    Employee.is_active.is_(True),
                )
            )
            subordinates = subordinates_result.scalars().all()
            if subordinates:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot deactivate: this employee has {len(subordinates)} active subordinates",
                )
        employee.is_active = body.is_active

    await db.flush()
    await db.refresh(employee)
    return employee


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    _require_admin(current_user)

    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if current_user.id == employee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    subordinates_result = await db.execute(
        select(Employee).where(
            Employee.manager_id == employee_id,
            Employee.is_active.is_(True),
        )
    )
    subordinates = subordinates_result.scalars().all()
    if subordinates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete: this employee has {len(subordinates)} active subordinates",
        )

    employee.is_active = False
