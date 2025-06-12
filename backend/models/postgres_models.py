from datetime import date, datetime, timezone
from sqlmodel import Boolean, SQLModel, Field, Relationship
from typing import Optional, List
from sqlalchemy.dialects.postgresql import UUID as pgUUID
import uuid
from sqlalchemy import ForeignKey, Column, TIMESTAMP
from enum import Enum

# NEW: Employee Role Enum
class EmployeeRole(str, Enum):
    ANNOTATION_TEAM = "annotation_team"
    DEV_TEAM = "dev_team"
    INTERN = "intern"

class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    LEAVE = "leave"
    PENDING = "pending"

class LocationVerificationStatus(str, Enum):
    VERIFIED = "verified"
    PENDING = "pending"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"

class PhotoVerificationStatus(str, Enum):
    VERIFIED = "verified"
    PENDING = "pending"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"

class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class LeaveType(str, Enum):
    CASUAL = "casual"
    SICK = "sick"
    UNPAID = "unpaid"

class Session(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # Either employee_id or admin_id will be set, never both
    employee_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(pgUUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE")))
    
    admin_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(pgUUID(as_uuid=True), ForeignKey("admin.id", ondelete="CASCADE")))
    
    token: str

    created_at: datetime = Field(
    default_factory=lambda: datetime.now(timezone.utc),
    sa_column=Column(TIMESTAMP(timezone=True)))

    expires_at: datetime = Field(
    sa_column=Column(TIMESTAMP(timezone=True)))

    # Relationships
    employee: Optional["Employee"] = Relationship(back_populates="sessions")
    admin: Optional["Admin"] = Relationship(back_populates="sessions")

class Employee(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    
    # NEW: Role field with default to maintain backward compatibility
    role: EmployeeRole = Field(default=EmployeeRole.ANNOTATION_TEAM, index=True)
    
    sessions: List["Session"] = Relationship(back_populates="employee")
    shifts: List["ShiftAssignment"] = Relationship(back_populates="employee")
    attendance_records: List["Attendance"] = Relationship(back_populates="employee")
    leave_requests: List["LeaveRequest"] = Relationship(back_populates="employee", 
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
        )
    reports: List["Report"] = Relationship(back_populates="employee")

class ShiftAssignment(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    employee_id: uuid.UUID = Field(foreign_key="employee.id")
    day: int  
    shift: int 
    shift_date: date  
    employee: Optional[Employee] = Relationship(back_populates="shifts")
    attendance: Optional["Attendance"] = Relationship(back_populates="shift_assignment")

class Admin(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(index=True, unique=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    sessions: List["Session"] = Relationship(back_populates="admin")

class Attendance(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    employee_id: uuid.UUID = Field(
        sa_column=Column(pgUUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE"))
    )
    shift_assignment_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(pgUUID(as_uuid=True), ForeignKey("shiftassignment.id", ondelete="SET NULL"))
    )
   
    # Existing time fields
    clock_in_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True))
    )
    clock_out_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True))
    )
   
    # Existing status and date
    status: AttendanceStatus = Field(default=AttendanceStatus.PENDING)
    date: date
    notes: Optional[str] = Field(default=None)
    
    # NEW FIELDS - Photo related
    clock_in_photo_url: Optional[str] = Field(default=None, max_length=500)
    clock_out_photo_url: Optional[str] = Field(default=None, max_length=500)
    photo_verification_status: PhotoVerificationStatus = Field(default=PhotoVerificationStatus.NOT_REQUIRED)
    photo_verification_notes: Optional[str] = Field(default=None)
    
    # NEW FIELDS - Location related
    clock_in_latitude: Optional[float] = Field(default=None)
    clock_in_longitude: Optional[float] = Field(default=None)
    clock_in_location_address: Optional[str] = Field(default=None, max_length=500)
    clock_in_location_accuracy: Optional[float] = Field(default=None)  # in meters
    
    clock_out_latitude: Optional[float] = Field(default=None)
    clock_out_longitude: Optional[float] = Field(default=None)
    clock_out_location_address: Optional[str] = Field(default=None, max_length=500)
    clock_out_location_accuracy: Optional[float] = Field(default=None)  # in meters
    
    location_verification_status: LocationVerificationStatus = Field(default=LocationVerificationStatus.NOT_REQUIRED)
    location_verification_notes: Optional[str] = Field(default=None)
    
    # NEW FIELDS - Device and metadata
    clock_in_device_info: Optional[str] = Field(default=None, max_length=500)  # User agent, device details
    clock_out_device_info: Optional[str] = Field(default=None, max_length=500)
    
    # NEW FIELDS - IP tracking for security
    clock_in_ip_address: Optional[str] = Field(default=None, max_length=45)  # IPv6 max length
    clock_out_ip_address: Optional[str] = Field(default=None, max_length=45)
 
    # Relationships (unchanged)
    employee: "Employee" = Relationship(back_populates="attendance_records")
    shift_assignment: Optional["ShiftAssignment"] = Relationship(back_populates="attendance")
 
class LeaveRequest(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    employee_id: uuid.UUID = Field(foreign_key="employee.id")
    leave_type: LeaveType
    from_date: date
    to_date: date
    reason: str
    status: LeaveStatus = LeaveStatus.PENDING
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    
    # New fields for admin tracking
    last_updated_by_admin_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(pgUUID(as_uuid=True), ForeignKey("admin.id", ondelete="SET NULL"))
    )
    status_updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True))
    )

    employee: Optional["Employee"] = Relationship(
        back_populates="leave_requests",
        sa_relationship_kwargs={"passive_deletes": True}
    )
    
    # New relationship to Admin
    last_updated_by: Optional["Admin"] = Relationship()

class ShiftSwapRequest(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    requester_id: uuid.UUID = Field(foreign_key="employee.id")
    receiver_id: uuid.UUID = Field(foreign_key="employee.id")
    from_shift_id: uuid.UUID
    to_shift_id: uuid.UUID
    reason: str
    status: LeaveStatus = LeaveStatus.PENDING
    requested_at: datetime = Field(default_factory=datetime.utcnow)

    last_updated_by_admin_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(pgUUID(as_uuid=True), ForeignKey("admin.id", ondelete="SET NULL"))
    )
    status_updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True))
    )

    requester: Optional["Employee"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[ShiftSwapRequest.requester_id]"})
    receiver: Optional["Employee"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[ShiftSwapRequest.receiver_id]"})
    
    last_updated_by: Optional["Admin"] = Relationship()

class Report(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    employee_id: uuid.UUID = Field(
        sa_column=Column(pgUUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE"))
    )
    
    report_date: date = Field(default_factory=date.today, index=True)
    content: str
    
    viewed_by_admin: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(TIMESTAMP(timezone=True))
    )

    employee: Optional["Employee"] = Relationship(back_populates="reports")