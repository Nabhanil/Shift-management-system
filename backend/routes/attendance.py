import uuid
import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlmodel import Session, select
from typing import List, Optional
from datetime import datetime, date, timezone
from models.postgres_models import Admin, Employee, Attendance, AttendanceStatus, ShiftAssignment, PhotoVerificationStatus, LocationVerificationStatus
from models.models import (
    AttendanceCreate, AttendanceRead, AttendanceUpdate, AttendanceWithEmployeeRead, 
    ClockInRequest, ClockOutRequest, LocationData, DeviceInfo, PhotoUploadResponse,
    LocationValidationResponse, PhotoVerification, LocationVerification,
    RolePermissions, EmployeeRole, AttendanceOverviewResponse, AttendanceSummaryByRole,
    FixedHoursAttendance
)
from database.db import get_session
from utils.auth import get_current_employee, get_current_admin, require_role, require_admin_or_role
from utils.img_loc import (
    validate_and_process_photo, validate_location, get_address_from_coordinates,
    get_client_ip, serialize_device_info
)
from dateutil import parser as dateutil_parser

attendance_router = APIRouter()

def get_timestamp(client_timestamp_str: Optional[str] = None) -> datetime:
    """
    Parses the client's ISO timestamp string if provided and valid.
    Falls back to server's current UTC time if not provided or invalid.
    """
    if client_timestamp_str:
        try:
            parsed_time = dateutil_parser.isoparse(client_timestamp_str)
            if parsed_time.tzinfo is not None and parsed_time.tzinfo.utcoffset(parsed_time) is not None:
                print(f"Using client timestamp (UTC): {parsed_time}")
                return parsed_time.astimezone(timezone.utc)
            else:
                print(f"Warning: Client timestamp '{client_timestamp_str}' parsed as naive. Falling back to server time.")
                return datetime.now(timezone.utc)
        except (ValueError, TypeError) as e:
            print(f"Warning: Could not parse client timestamp '{client_timestamp_str}'. Error: {e}. Falling back to server time.")
            return datetime.now(timezone.utc)
    else:
        print("No client timestamp provided. Using server timestamp (UTC).")
        return datetime.now(timezone.utc)

# Enhanced Clock-In endpoint with role-based access control
@attendance_router.post("/clock-in", response_model=AttendanceRead, tags=["Attendance"])
async def clock_in(
    request: Request,
    employee_id: str = Form(...),
    client_timestamp: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    location_accuracy: Optional[float] = Form(None),
    device_info: Optional[str] = Form(None),  # JSON string
    photo: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
    current_employee: Employee = Depends(require_role(RolePermissions.get_allowed_roles_for_attendance()))
):
    """Enhanced clock in with photo and location support - State-based logic"""
    
    # Convert employee_id to UUID
    try:
        employee_uuid = uuid.UUID(employee_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid employee ID format")
    
    # Security check - employee can only clock in for themselves
    if current_employee.id != employee_uuid:
        raise HTTPException(status_code=403, detail="You can only clock in for yourself")

    # Check if this role can clock in/out
    if not RolePermissions.can_clock_in_out(current_employee.role):
        raise HTTPException(
            status_code=403, 
            detail=f"Role '{current_employee.role.value}' is not allowed to clock in/out"
        )

    event_time_utc = get_timestamp(client_timestamp)
    client_ip = get_client_ip(request)
    
    # Check if employee has any open attendance (clocked in but not clocked out)
    open_attendance = session.exec(
        select(Attendance)
        .where(Attendance.employee_id == current_employee.id)
        .where(Attendance.clock_in_time.is_not(None))
        .where(Attendance.clock_out_time.is_(None))
    ).first()

    if open_attendance:
        raise HTTPException(
            status_code=400, 
            detail="You are already clocked in. Please clock out first before clocking in again."
        )

    # Find shift assignment for today (only for roles that have shift schedules)
    shift_id = None
    if RolePermissions.has_shift_schedule(current_employee.role):
        today = event_time_utc.date()
        today_shift = session.exec(
            select(ShiftAssignment)
            .where(ShiftAssignment.employee_id == current_employee.id)
            .where(ShiftAssignment.shift_date == today) 
        ).first()
        shift_id = today_shift.id if today_shift else None

    # Process photo if provided
    photo_url = None
    photo_verification_status = PhotoVerificationStatus.NOT_REQUIRED
    
    if photo:
        try:
            # file_path, metadata = await validate_and_process_photo(
            #     photo, str(current_employee.id)
            # )
            # # Store relative path or URL based on your setup
            # photo_url = f"/uploads/attendance_photos/{metadata['processed_filename']}"
            minio_url, metadata = await validate_and_process_photo(
                    photo, str(current_employee.id)
                )
            photo_url = minio_url 

            photo_verification_status = PhotoVerificationStatus.PENDING
            print(f"Photo processed successfully: {photo_url}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Photo processing failed: {str(e)}")

    # Process location if provided
    location_address = None
    location_verification_status = LocationVerificationStatus.NOT_REQUIRED
    location_verification_notes = None
    
    if latitude is not None and longitude is not None:
        # Validate location
        location_validation = validate_location(latitude, longitude, location_accuracy)
        
        if not location_validation["is_valid"]:
            # You can choose to reject or just mark as failed
            location_verification_status = LocationVerificationStatus.FAILED
            location_verification_notes = location_validation["message"]
        else:
            location_verification_status = LocationVerificationStatus.VERIFIED
            location_verification_notes = location_validation["message"]
        
        # Get address asynchronously and serialize to JSON string
        try:
            location_data = await get_address_from_coordinates(latitude, longitude)
            # Convert dictionary to JSON string if it's a dictionary
            if isinstance(location_data, dict):
                location_address = json.dumps(location_data)
            else:
                location_address = location_data
        except Exception as e:
            print(f"Error getting address: {e}")
            location_address = None

    # Process device info
    device_info_str = None
    if device_info:
        try:
            # Validate JSON and serialize
            device_data = json.loads(device_info)
            device_info_str = serialize_device_info(device_data)
        except json.JSONDecodeError:
            print("Invalid device info JSON provided")

    # Create new attendance record
    attendance = Attendance(
        employee_id=current_employee.id,
        date=event_time_utc.date(),  # Still store date for reporting purposes
        clock_in_time=event_time_utc, 
        shift_assignment_id=shift_id,
        status=AttendanceStatus.PRESENT,
        # Photo fields
        clock_in_photo_url=photo_url,
        photo_verification_status=photo_verification_status,
        # Location fields
        clock_in_latitude=latitude,
        clock_in_longitude=longitude,
        clock_in_location_address=location_address,
        clock_in_location_accuracy=location_accuracy,
        location_verification_status=location_verification_status,
        location_verification_notes=location_verification_notes,
        # Device and IP
        clock_in_device_info=device_info_str,
        clock_in_ip_address=client_ip
    )
    session.add(attendance)
    session.commit()
    session.refresh(attendance)
    return attendance


# Enhanced Clock-Out endpoint with state-based logic
@attendance_router.post("/clock-out", response_model=AttendanceRead, tags=["Attendance"])
async def clock_out(
    request: Request,
    employee_id: str = Form(...),
    client_timestamp: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    location_accuracy: Optional[float] = Form(None),
    device_info: Optional[str] = Form(None),  # JSON string
    photo: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
    current_employee: Employee = Depends(require_role(RolePermissions.get_allowed_roles_for_attendance()))
):
    """Enhanced clock out with photo and location support - State-based logic"""
    
    # Convert employee_id to UUID
    try:
        employee_uuid = uuid.UUID(employee_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid employee ID format")
    
    # Security check
    if current_employee.id != employee_uuid:
        raise HTTPException(status_code=403, detail="You can only clock out for yourself")

    # Check if this role can clock in/out
    if not RolePermissions.can_clock_in_out(current_employee.role):
        raise HTTPException(
            status_code=403, 
            detail=f"Role '{current_employee.role.value}' is not allowed to clock in/out"
        )

    event_time_utc = get_timestamp(client_timestamp)
    client_ip = get_client_ip(request)

    # Find the open attendance record (clocked in but not clocked out)
    attendance = session.exec(
        select(Attendance)
        .where(Attendance.employee_id == current_employee.id)
        .where(Attendance.clock_in_time.is_not(None))
        .where(Attendance.clock_out_time.is_(None))
    ).first()

    if not attendance:
        raise HTTPException(
            status_code=404, 
            detail="No open clock-in record found. Please clock in first."
        )

    # Process photo if provided
    clock_out_photo_url = None
    if photo:
        try:
            # file_path, metadata = await validate_and_process_photo(
            #     photo, str(current_employee.id)
            # )
            # clock_out_photo_url = f"/uploads/attendance_photos/{metadata['processed_filename']}"
            # print(f"Clock-out photo processed successfully: {clock_out_photo_url}")
                minio_url, metadata = await validate_and_process_photo(
                    photo, str(current_employee.id)
                )
                clock_out_photo_url = minio_url
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Photo processing failed: {str(e)}")

    # Process location if provided
    clock_out_address = None
    if latitude is not None and longitude is not None:
        # Validate location
        location_validation = validate_location(latitude, longitude, location_accuracy)
        
        # Update verification status if location was previously verified
        if not location_validation["is_valid"] and attendance.location_verification_status == LocationVerificationStatus.VERIFIED:
            attendance.location_verification_status = LocationVerificationStatus.FAILED
            attendance.location_verification_notes = f"Clock-out location invalid: {location_validation['message']}"
        
        # Get address and serialize to JSON string
        try:
            location_data = await get_address_from_coordinates(latitude, longitude)
            # Convert dictionary to JSON string if it's a dictionary
            if isinstance(location_data, dict):
                clock_out_address = json.dumps(location_data)
            else:
                clock_out_address = location_data
        except Exception as e:
            print(f"Error getting clock-out address: {e}")
            clock_out_address = None

    # Process device info
    device_info_str = None
    if device_info:
        try:
            device_data = json.loads(device_info)
            device_info_str = serialize_device_info(device_data)
        except json.JSONDecodeError:
            print("Invalid device info JSON provided")

    # Update attendance record
    attendance.clock_out_time = event_time_utc
    attendance.clock_out_photo_url = clock_out_photo_url
    attendance.clock_out_latitude = latitude
    attendance.clock_out_longitude = longitude
    attendance.clock_out_location_address = clock_out_address
    attendance.clock_out_location_accuracy = location_accuracy
    attendance.clock_out_device_info = device_info_str
    attendance.clock_out_ip_address = client_ip

    session.commit()
    session.refresh(attendance)
    return attendance

# Employee endpoint with role-based access
@attendance_router.get("/my-attendance", response_model=List[AttendanceRead], tags=["Attendance"])
def get_my_attendance(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: Session = Depends(get_session),
    current_employee: Employee = Depends(get_current_employee)
):
    """Get the current employee's attendance records within a date range"""
    query = select(Attendance).where(Attendance.employee_id == current_employee.id)
    
    if start_date:
        query = query.where(Attendance.date >= start_date)
    if end_date:
        query = query.where(Attendance.date <= end_date)
    
    query = query.order_by(Attendance.date.desc())
    results = session.exec(query).all()
    return results

# New endpoint for role-specific attendance overview (Admin only)
@attendance_router.get("/overview", response_model=AttendanceOverviewResponse, tags=["Admin"])
def get_attendance_overview(
    target_date: Optional[date] = None,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Get attendance overview by role for admin dashboard"""
    if not target_date:
        target_date = date.today()
    
    # Get all employees grouped by role
    employees_by_role = session.exec(
        select(Employee.role, Employee.id, Employee.name)
        .order_by(Employee.role, Employee.name)
    ).all()
    
    # Get attendance for the target date
    attendance_records = session.exec(
        select(Attendance)
        .where(Attendance.date == target_date)
    ).all()
    
    # Create attendance lookup
    attendance_lookup = {record.employee_id: record for record in attendance_records}
    
    # Group employees by role
    role_groups = {}
    for emp_role, emp_id, emp_name in employees_by_role:
        if emp_role not in role_groups:
            role_groups[emp_role] = []
        role_groups[emp_role].append(emp_id)
    
    # Calculate statistics by role
    summary_by_role = []
    total_summary = {
        "total_employees": 0,
        "present_today": 0,
        "absent_today": 0,
        "late_today": 0,
        "on_leave_today": 0,
        "pending_today": 0
    }
    
    for role, employee_ids in role_groups.items():
        role_stats = {
            "present_today": 0,
            "absent_today": 0,
            "late_today": 0,
            "on_leave_today": 0,
            "pending_today": 0
        }
        
        for emp_id in employee_ids:
            attendance = attendance_lookup.get(emp_id)
            if attendance:
                if attendance.status == AttendanceStatus.PRESENT:
                    role_stats["present_today"] += 1
                elif attendance.status == AttendanceStatus.ABSENT:
                    role_stats["absent_today"] += 1
                elif attendance.status == AttendanceStatus.LATE:
                    role_stats["late_today"] += 1
                elif attendance.status == AttendanceStatus.LEAVE:
                    role_stats["on_leave_today"] += 1
                elif attendance.status == AttendanceStatus.PENDING:
                    role_stats["pending_today"] += 1
            else:
                # No attendance record = absent
                role_stats["absent_today"] += 1
        
        summary_by_role.append(AttendanceSummaryByRole(
            role=role,
            total_employees=len(employee_ids),
            **role_stats
        ))
        
        # Add to total summary
        total_summary["total_employees"] += len(employee_ids)
        for key in role_stats:
            total_summary[key] += role_stats[key]
    
    return AttendanceOverviewResponse(
        summary_by_role=summary_by_role,
        total_summary=total_summary,
        date=target_date
    )

# New endpoint for fixed hours tracking (Dev team specific)
@attendance_router.get("/fixed-hours", response_model=List[FixedHoursAttendance], tags=["Admin"])
def get_fixed_hours_attendance(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Get fixed hours attendance tracking for dev team"""
    if not start_date:
        start_date = date.today()
    if not end_date:
        end_date = start_date
    
    # Get dev team employees
    dev_employees = session.exec(
        select(Employee)
        .where(Employee.role == EmployeeRole.DEV_TEAM)
    ).all()
    
    # Get their attendance records
    attendance_records = session.exec(
        select(Attendance)
        .where(Attendance.employee_id.in_([emp.id for emp in dev_employees]))
        .where(Attendance.date >= start_date)
        .where(Attendance.date <= end_date)
    ).all()
    
    # Create attendance lookup
    attendance_lookup = {}
    for record in attendance_records:
        key = (record.employee_id, record.date)
        attendance_lookup[key] = record
    
    # Build fixed hours attendance data
    fixed_hours_data = []
    
    current_date = start_date
    while current_date <= end_date:
        for employee in dev_employees:
            attendance = attendance_lookup.get((employee.id, current_date))
            
            hours_worked = None
            is_late = False
            
            if attendance and attendance.clock_in_time and attendance.clock_out_time:
                # Calculate hours worked
                time_diff = attendance.clock_out_time - attendance.clock_in_time
                hours_worked = time_diff.total_seconds() / 3600  # Convert to hours
                
                # Check if late (after 10:00 AM)
                expected_start = datetime.combine(current_date, datetime.min.time().replace(hour=10))
                if attendance.clock_in_time.replace(tzinfo=None) > expected_start:
                    is_late = True
            
            fixed_hours_data.append(FixedHoursAttendance(
                employee_id=employee.id,
                employee_name=employee.name,
                date=current_date,
                actual_clock_in=attendance.clock_in_time if attendance else None,
                actual_clock_out=attendance.clock_out_time if attendance else None,
                is_late=is_late,
                hours_worked=hours_worked,
                status=attendance.status if attendance else AttendanceStatus.ABSENT
            ))
        
        current_date = date.fromordinal(current_date.toordinal() + 1)
    
    return fixed_hours_data

# Role-based attendance filtering for admin
@attendance_router.get("/by-role/{role}", response_model=List[AttendanceWithEmployeeRead], tags=["Admin"])
def get_attendance_by_role(
    role: EmployeeRole,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[AttendanceStatus] = None,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Get attendance records filtered by employee role"""
    statement = (
        select(
            Attendance,
            Employee.name.label("employee_name"),
            Employee.role.label("employee_role")
        )
        .join(Employee, Employee.id == Attendance.employee_id)
        .where(Employee.role == role)
    )

    if start_date:
        statement = statement.where(Attendance.date >= start_date)
    if end_date:
        statement = statement.where(Attendance.date <= end_date)
    if status:
        statement = statement.where(Attendance.status == status)

    statement = statement.order_by(Attendance.date.desc(), Employee.name)
    results = session.exec(statement).all()

    return [
        AttendanceWithEmployeeRead(
            **attendance.dict(),
            employee_name=employee_name,
            employee_role=employee_role
        )
        for attendance, employee_name, employee_role in results
    ]

# Photo verification by admin
@attendance_router.post("/verify-photo", response_model=AttendanceRead, tags=["Admin"])
def verify_photo(
    verification: PhotoVerification,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Admin endpoint to verify attendance photos"""
    attendance = session.get(Attendance, verification.attendance_id)
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    attendance.photo_verification_status = verification.verification_status
    if verification.verification_notes:
        attendance.photo_verification_notes = verification.verification_notes
    
    session.commit()
    session.refresh(attendance)
    return attendance

# Location verification by admin
@attendance_router.post("/verify-location", response_model=AttendanceRead, tags=["Admin"])
def verify_location_endpoint(
    verification: LocationVerification,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Admin endpoint to verify attendance locations"""
    attendance = session.get(Attendance, verification.attendance_id)
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    attendance.location_verification_status = verification.verification_status
    if verification.verification_notes:
        attendance.location_verification_notes = verification.verification_notes
    
    session.commit()
    session.refresh(attendance)
    return attendance

# Admin endpoint for specific employee attendance
@attendance_router.get("/employees/{employee_id}/attendance", response_model=List[AttendanceWithEmployeeRead], tags=["Admin"])
def get_employee_attendance(
    employee_id: uuid.UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Get attendance records for a specific employee"""
    statement = (
        select(
            Attendance,
            Employee.name.label("employee_name"),
            Employee.role.label("employee_role")
        )
        .join(Employee, Employee.id == Attendance.employee_id)
        .where(Attendance.employee_id == employee_id)
    )

    if start_date:
        statement = statement.where(Attendance.date >= start_date)
    if end_date:
        statement = statement.where(Attendance.date <= end_date)

    statement = statement.order_by(Attendance.date.desc())
    results = session.exec(statement).all()

    return [
        AttendanceWithEmployeeRead(
            **attendance.dict(),
            employee_name=employee_name,
            employee_role=employee_role
        )
        for attendance, employee_name, employee_role in results
    ]

# Enhanced admin endpoint for all attendance with role-based filtering
@attendance_router.get("/attendance", response_model=List[AttendanceWithEmployeeRead], tags=["Admin"])
def get_all_attendance(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[AttendanceStatus] = None,
    role: Optional[EmployeeRole] = None,
    photo_verification_status: Optional[PhotoVerificationStatus] = None,
    location_verification_status: Optional[LocationVerificationStatus] = None,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Enhanced admin endpoint with role-based filtering"""
    statement = (
        select(
            Attendance,
            Employee.name.label("employee_name"),
            Employee.role.label("employee_role")
        )
        .join(Employee, Employee.id == Attendance.employee_id)
    )

    if start_date:
        statement = statement.where(Attendance.date >= start_date)
    if end_date:
        statement = statement.where(Attendance.date <= end_date)
    if status:
        statement = statement.where(Attendance.status == status)
    if role:
        statement = statement.where(Employee.role == role)
    if photo_verification_status:
        statement = statement.where(Attendance.photo_verification_status == photo_verification_status)
    if location_verification_status:
        statement = statement.where(Attendance.location_verification_status == location_verification_status)

    statement = statement.where(Attendance.employee_id.is_not(None))
    statement = statement.order_by(Attendance.date.desc(), Employee.role, Employee.name)

    results = session.exec(statement).all()

    return [
        AttendanceWithEmployeeRead(
            **attendance.dict(),
            employee_name=employee_name,
            employee_role=employee_role
        )
        for attendance, employee_name, employee_role in results
    ]

# Admin endpoint to update attendance
@attendance_router.patch("/attendance/{attendance_id}", response_model=AttendanceRead, tags=["Admin"])
def update_attendance(
    attendance_id: uuid.UUID,
    attendance_update: AttendanceUpdate,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Admin endpoint to update an attendance record"""
    attendance = session.get(Attendance, attendance_id)
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    attendance_data = attendance_update.dict(exclude_unset=True)
    for key, value in attendance_data.items():
        setattr(attendance, key, value)
    
    session.commit()
    session.refresh(attendance)
    return attendance

# Admin endpoint to manually mark attendance
@attendance_router.post("/admin/mark-attendance", response_model=AttendanceRead, tags=["Admin"])
def admin_mark_attendance(
    attendance: AttendanceCreate,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    """Admin endpoint to manually mark attendance for an employee"""
    # Verify employee exists and get their role
    employee = session.get(Employee, attendance.employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    existing = session.exec(
        select(Attendance)
        .where(Attendance.employee_id == attendance.employee_id)
        .where(Attendance.date == attendance.date)
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400, 
            detail="Attendance record already exists for this date"
        )
    
    new_attendance = Attendance(
        employee_id=attendance.employee_id,
        date=attendance.date,
        status=attendance.status,
        shift_assignment_id=attendance.shift_assignment_id,
        notes=attendance.notes
    )
    
    session.add(new_attendance)
    session.commit()
    session.refresh(new_attendance)
    return new_attendance