from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from uuid import UUID
from typing import List
from datetime import date

from database.db import get_session
from models.postgres_models import Report, Employee
from models.models import ReportCreate, ReportRead
from utils.auth import get_current_employee, get_current_admin

report_router = APIRouter()

# Employee: submit a daily report
@report_router.post(
    "/report",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Emp_Report"]
)
def create_report(
    payload: ReportCreate,
    db: Session = Depends(get_session),
    emp = Depends(get_current_employee)
):
    try:
        # Check if report already exists for today
        existing_report = db.exec(
            select(Report)
            .where(Report.employee_id == emp.id)
            .where(Report.report_date == date.today())
        ).first()
        
        if existing_report:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already submitted a report today"
            )

        report = Report(
            employee_id=emp.id,
            content=payload.content,
            report_date=date.today()
        )
        
        db.add(report)
        db.commit()
        db.refresh(report)
        
        return ReportRead(
            id=report.id,
            employee_id=emp.id,
            employee_name=emp.name,
            report_date=report.report_date,
            content=report.content,
            viewed_by_admin=report.viewed_by_admin,
            created_at=report.created_at
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating report: {str(e)}"
        )

# Employee: list own reports
@report_router.get(
    "/report",
    response_model=List[ReportRead],
    tags=["Emp_Report"]
)
def get_my_reports(
    db: Session = Depends(get_session),
    emp = Depends(get_current_employee)
):
    try:
        reports = db.exec(
            select(Report)
            .where(Report.employee_id == emp.id)
            .order_by(Report.report_date.desc())
        ).all()
        
        return [
            ReportRead(
                id=r.id,
                employee_id=r.employee_id,
                employee_name=emp.name,
                report_date=r.report_date,
                content=r.content,
                viewed_by_admin=r.viewed_by_admin,
                created_at=r.created_at
            )
            for r in reports
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching reports: {str(e)}"
        )

# Admin: list all reports with pagination
@report_router.get(
    "/admin/reports",
    response_model=List[ReportRead],
    tags=["Admin"]
)
def get_all_reports(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_session),
    admin = Depends(get_current_admin)
):
    try:
        # Get reports with employee data in single query
        reports = db.exec(
            select(Report, Employee)
            .join(Employee)
            .offset(skip)
            .limit(limit)
            .order_by(Report.report_date.desc())
        ).all()
        
        # Mark unviewed reports as viewed
        reports_to_update = [r for r, e in reports if not r.viewed_by_admin]
        for report in reports_to_update:
            report.viewed_by_admin = True
            db.add(report)
        db.commit()
        
        return [
            ReportRead(
                id=r.id,
                employee_id=r.employee_id,
                employee_name=e.name,
                report_date=r.report_date,
                content=r.content,
                viewed_by_admin=r.viewed_by_admin,
                created_at=r.created_at
            )
            for r, e in reports
        ]
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching reports: {str(e)}"
        )

# Admin: list reports by specific employee
@report_router.get(
    "/admin/reports/employee/{employee_id}",
    response_model=List[ReportRead],
    tags=["Admin"]
)
def get_reports_by_employee(
    employee_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_session),
    admin = Depends(get_current_admin)
):
    try:
        # Verify employee exists
        employee = db.get(Employee, employee_id)
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found"
            )

        # Get reports with single query
        reports = db.exec(
            select(Report)
            .where(Report.employee_id == employee_id)
            .offset(skip)
            .limit(limit)
            .order_by(Report.report_date.desc())
        ).all()
        
        # Mark unviewed reports as viewed
        reports_to_update = [r for r in reports if not r.viewed_by_admin]
        for report in reports_to_update:
            report.viewed_by_admin = True
            db.add(report)
        db.commit()
        
        return [
            ReportRead(
                id=r.id,
                employee_id=r.employee_id,
                employee_name=employee.name,
                report_date=r.report_date,
                content=r.content,
                viewed_by_admin=r.viewed_by_admin,
                created_at=r.created_at
            )
            for r in reports
        ]
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching reports: {str(e)}"
        )