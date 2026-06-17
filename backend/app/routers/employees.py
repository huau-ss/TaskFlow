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
    _: Employee = Depends(get_current_user),
):
    existing = await db.execute(select(Employee).where(Employee.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    if body.manager_id:
        mgr = await db.get(Employee, body.manager_id)
        if not mgr:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Manager not found")
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
    _: Employee = Depends(get_current_user),
):
    """Import org structure from CSV: name,email,manager_email"""
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
            employee = await db.get(Employee, emp_id)
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
    result = await db.execute(
        select(Employee).where(Employee.manager_id == employee_id, Employee.is_active.is_(True))
    )
    return result.scalars().all()


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: int,
    body: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    employee = await db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    if body.name is not None:
        employee.name = body.name
    if body.email is not None:
        employee.email = body.email
    if body.manager_id is not None:
        employee.manager_id = body.manager_id
    if body.is_active is not None:
        employee.is_active = body.is_active
    await db.flush()
    await db.refresh(employee)
    return employee


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_user),
):
    employee = await db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    employee.is_active = False
