from pydantic import BaseModel, EmailStr, validator
from uuid import UUID
from datetime import datetime, date, time
from enum import Enum
from typing import Dict, List, Optional

from sqlmodel import Field

# Employee Role Enum (matching SQL model)
class EmployeeRole(str, Enum):
    ANNOTATION_TEAM = "annotation_team"
    DEV_TEAM = "dev_team"
    INTERN = "intern"

# Role permissions helper - works with your auth.py
class RolePermissions:
    @staticmethod
    def can_request_leave(role: EmployeeRole) -> bool:
        """ANNOTATION_TEAM and DEV_TEAM can request leave, INTERN cannot"""
        return role.value in ["annotation_team", "dev_team"]
    
    @staticmethod
    def has_shift_schedule(role: EmployeeRole) -> bool:
        """Only ANNOTATION_TEAM has shift scheduling"""
        return role.value == "annotation_team"
    
    @staticmethod
    def can_clock_in_out(role: EmployeeRole) -> bool:
        """ANNOTATION_TEAM and DEV_TEAM can clock in/out, INTERN cannot"""
        return role.value in ["annotation_team", "dev_team"]
    
    @staticmethod
    def can_view_reports(role: EmployeeRole) -> bool:
        """All roles can view reports"""
        return True
    
    @staticmethod
    def has_fixed_hours(role: EmployeeRole) -> bool:
        """DEV_TEAM has fixed hours (10 AM - 6 PM)"""
        return role.value == "dev_team"
    
    @staticmethod
    def get_allowed_roles_for_attendance() -> List[str]:
        """Get list of role strings for your auth.py require_role()"""
        return ["annotation_team", "dev_team"]
    
    @staticmethod
    def get_allowed_roles_for_leave_requests() -> List[str]:
        """Get list of role strings for your auth.py require_role()"""
        return ["annotation_team", "dev_team"]
    
    @staticmethod
    def get_allowed_roles_for_shift_management() -> List[str]:
        """Get list of role strings for your auth.py require_role()"""
        return ["annotation_team"]

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

class LeaveType(str, Enum):
    CASUAL = "casual"
    SICK = "sick"
    UNPAID = "unpaid"

class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class LocationData(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    accuracy: Optional[float] = Field(None, ge=0, description="Location accuracy in meters")
    address: Optional[str] = Field(None, max_length=500, description="Human readable address")

# Device info model
class DeviceInfo(BaseModel):
    user_agent: Optional[str] = None
    platform: Optional[str] = None
    browser: Optional[str] = None
    device_type: Optional[str] = None

# Clock-in request - simplified, role validation handled by auth.py
class ClockInRequest(BaseModel):
    employee_id: UUID
    client_timestamp: Optional[str] = None
    location: Optional[LocationData] = None
    device_info: Optional[DeviceInfo] = None
    # Note: photo will be handled as multipart file upload separately

class ClockOutRequest(BaseModel):
    employee_id: UUID
    client_timestamp: Optional[str] = None
    location: Optional[LocationData] = None
    device_info: Optional[DeviceInfo] = None
    # Note: photo will be handled as multipart file upload separately

# Enhanced attendance creation model
class AttendanceCreate(BaseModel):
    employee_id: UUID
    date: date
    shift_assignment_id: Optional[UUID] = None
    status: AttendanceStatus = AttendanceStatus.PENDING
    notes: Optional[str] = None
    
    # Location data
    clock_in_location: Optional[LocationData] = None
    clock_out_location: Optional[LocationData] = None
    
    # Photo URLs (set after upload)
    clock_in_photo_url: Optional[str] = None
    clock_out_photo_url: Optional[str] = None

class AttendanceUpdate(BaseModel):
    status: Optional[AttendanceStatus] = None
    notes: Optional[str] = None
    photo_verification_status: Optional[PhotoVerificationStatus] = None
    location_verification_status: Optional[LocationVerificationStatus] = None
    photo_verification_notes: Optional[str] = None
    location_verification_notes: Optional[str] = None

# Comprehensive read model
class AttendanceRead(BaseModel):
    id: UUID
    employee_id: Optional[UUID]
    date: date
    clock_in_time: Optional[datetime] = None
    clock_out_time: Optional[datetime] = None
    status: AttendanceStatus
    shift_assignment_id: Optional[UUID] = None
    notes: Optional[str] = None
    
    # Photo fields
    clock_in_photo_url: Optional[str] = None
    clock_out_photo_url: Optional[str] = None
    photo_verification_status: PhotoVerificationStatus
    photo_verification_notes: Optional[str] = None
    
    # Location fields
    clock_in_latitude: Optional[float] = None
    clock_in_longitude: Optional[float] = None
    clock_in_location_address: Optional[str] = None
    clock_in_location_accuracy: Optional[float] = None
    
    clock_out_latitude: Optional[float] = None
    clock_out_longitude: Optional[float] = None
    clock_out_location_address: Optional[str] = None
    clock_out_location_accuracy: Optional[float] = None
    
    location_verification_status: LocationVerificationStatus
    location_verification_notes: Optional[str] = None
    
    # Device and IP info
    clock_in_device_info: Optional[str] = None
    clock_out_device_info: Optional[str] = None
    clock_in_ip_address: Optional[str] = None
    clock_out_ip_address: Optional[str] = None

class AttendanceWithEmployeeRead(AttendanceRead):
    employee_name: str
    employee_role: EmployeeRole

# Photo upload response model
class PhotoUploadResponse(BaseModel):
    photo_url: str
    message: str
    file_size: int
    upload_timestamp: datetime

# Location validation response
class LocationValidationResponse(BaseModel):
    is_valid: bool
    message: str
    distance_from_office: Optional[float] = None  # in meters
    verification_status: LocationVerificationStatus

# Verification models for admin
class PhotoVerification(BaseModel):
    attendance_id: UUID
    verification_status: PhotoVerificationStatus
    verification_notes: Optional[str] = None

class LocationVerification(BaseModel):
    attendance_id: UUID
    verification_status: LocationVerificationStatus
    verification_notes: Optional[str] = None

# SignupData with role
class SignupData(BaseModel):
    name: str
    email: str
    password: str
    role: EmployeeRole = EmployeeRole.ANNOTATION_TEAM  # Default for backward compatibility
    joining_date: Optional[date] = None  # New field for employee joining date

class SigninData(BaseModel):
    email: str
    password: str

# EmployeeCreate with role
class EmployeeCreate(BaseModel):
    name: str
    role: EmployeeRole = EmployeeRole.ANNOTATION_TEAM  # Default for backward compatibility

# EmployeeRead with role-based computed properties
class EmployeeRead(BaseModel):
    id: UUID
    name: str
    role: EmployeeRole

class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com"
            }
        }

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "otp": "123456"
            }
        }

class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str
    confirm_password: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "reset_token": "abc123def456...",
                "new_password": "newPassword123",
                "confirm_password": "newPassword123"
            }
        }
    
    # Computed properties based on role - helpful for frontend
    @property
    def can_request_leave(self) -> bool:
        return RolePermissions.can_request_leave(self.role)
    
    @property
    def has_shift_schedule(self) -> bool:
        return RolePermissions.has_shift_schedule(self.role)
    
    @property
    def can_clock_in_out(self) -> bool:
        return RolePermissions.can_clock_in_out(self.role)
    
    @property
    def has_fixed_hours(self) -> bool:
        return RolePermissions.has_fixed_hours(self.role)
    
    class Config:
        from_attributes = True

# ShiftAssignmentCreate - only for annotation_team
class ShiftAssignmentCreate(BaseModel):
    employee_id: UUID
    day: int 
    shift: int  
    shift_date: datetime  

class ShiftAssignmentRead(BaseModel):
    id: UUID
    employee_id: UUID
    day: int
    shift: int
    shift_date: datetime 

class AdminSignin(BaseModel):
    email: str
    username: str
    password: str

class AdminRead(BaseModel):
    id: UUID
    username: str
    email: str

# LeaveRequestCreate - role validation handled by auth.py
class LeaveRequestCreate(BaseModel):
    employee_id: UUID
    leave_type: LeaveType
    from_date: date
    to_date: date
    reason: str

class LeaveRequestRead(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    employee_role: EmployeeRole
    leave_type: LeaveType
    from_date: date
    to_date: date
    reason: str
    status: LeaveStatus
    requested_at: datetime
    employee_role: Optional[str] = None
    # New fields
    last_updated_by_admin_id: Optional[UUID] = None
    last_updated_by_admin_username: Optional[str] = None
    status_updated_at: Optional[datetime] = None

class LeaveStatsResponse(BaseModel):
    leave_counts: Dict[str, int]
    total_leaves: int
    leaves: List[LeaveRequestRead]
    
    # Role-based breakdown for admin dashboard
    leave_counts_by_role: Optional[Dict[str, Dict[str, int]]] = None

class ShiftSwapRequestCreate(BaseModel):
    requester_id: UUID
    receiver_id: UUID
    from_shift_id: UUID
    to_shift_id: UUID
    reason: str

class ShiftSwapRequestRead(BaseModel):
    id: UUID
    requester_id: UUID
    requester_name: str
    requester_role: EmployeeRole
    receiver_id: UUID
    receiver_name: str
    receiver_role: EmployeeRole
    from_shift_id: UUID
    to_shift_id: UUID
    reason: str
    status: LeaveStatus
    requested_at: datetime
    last_updated_by_admin_id: Optional[UUID] = None
    last_updated_by_admin_username: Optional[str] = None
    status_updated_at: Optional[datetime] = None

class ReportCreate(BaseModel):
    content: str

class ReportRead(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    employee_role: EmployeeRole
    report_date: date
    content: str
    viewed_by_admin: bool
    employee_role: Optional[str] = None
    created_at: datetime

# Role-specific response models for admin dashboard
class EmployeesByRoleResponse(BaseModel):
    role: EmployeeRole
    employees: List[EmployeeRead]
    total_count: int

class RoleStatsResponse(BaseModel):
    role_counts: Dict[str, int]
    total_employees: int
    employees_by_role: Dict[str, List[EmployeeRead]]

class EmployeeRoleUpdate(BaseModel):
    role: EmployeeRole

# Role-specific attendance summary for dashboard
class AttendanceSummaryByRole(BaseModel):
    role: EmployeeRole
    total_employees: int
    present_today: int
    absent_today: int
    late_today: int
    on_leave_today: int
    pending_today: int

class AttendanceOverviewResponse(BaseModel):
    summary_by_role: List[AttendanceSummaryByRole]
    total_summary: Dict[str, int]
    date: date

# Fixed hours tracking specifically for dev team
class FixedHoursAttendance(BaseModel):
    employee_id: UUID
    employee_name: str
    date: date
    expected_start: time = Field(default=time(10, 0))  # 10:00 AM
    expected_end: time = Field(default=time(18, 0))    # 6:00 PM
    actual_clock_in: Optional[datetime] = None
    actual_clock_out: Optional[datetime] = None
    is_late: bool = False
    hours_worked: Optional[float] = None
    status: AttendanceStatus = AttendanceStatus.PENDING

# Helper response for role permissions (useful for frontend)
class RolePermissionsResponse(BaseModel):
    role: EmployeeRole
    can_request_leave: bool
    has_shift_schedule: bool
    can_clock_in_out: bool
    has_fixed_hours: bool
    can_view_reports: bool
    
    @classmethod
    def for_role(cls, role: EmployeeRole):
        return cls(
            role=role,
            can_request_leave=RolePermissions.can_request_leave(role),
            has_shift_schedule=RolePermissions.has_shift_schedule(role),
            can_clock_in_out=RolePermissions.can_clock_in_out(role),
            has_fixed_hours=RolePermissions.has_fixed_hours(role),
            can_view_reports=RolePermissions.can_view_reports(role)
        )
    # Add these models to your existing models.py file

# Role filtering query parameters for admin endpoints
class RoleFilterParams(BaseModel):
    """Query parameters for filtering by roles"""
    roles: Optional[List[EmployeeRole]] = None
    include_all: bool = True  # If True, includes all roles when roles is None
    
    @validator('roles', pre=True)
    def parse_roles(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            # Handle comma-separated string: "annotation_team,dev_team"
            return [EmployeeRole(role.strip()) for role in v.split(',')]
        return v

# Enhanced pagination with role filtering
class PaginatedRoleFilter(BaseModel):
    """Base class for paginated responses with role filtering"""
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)
    roles: Optional[List[EmployeeRole]] = None
    search: Optional[str] = None  # For name/email search
    
    @validator('roles', pre=True)
    def parse_roles(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [EmployeeRole(role.strip()) for role in v.split(',')]
        return v

# Admin dashboard responses with role breakdowns
class AdminEmployeeListResponse(BaseModel):
    """Enhanced employee list response for admin with role filtering"""
    employees: List[EmployeeRead]
    total_count: int
    page: int
    limit: int
    total_pages: int
    role_filter: Optional[List[EmployeeRole]]
    role_breakdown: Dict[str, int]  # Count by role
    
class AdminAttendanceListResponse(BaseModel):
    """Enhanced attendance list response for admin with role filtering"""
    attendance_records: List[AttendanceWithEmployeeRead]
    total_count: int
    page: int
    limit: int
    total_pages: int
    date_filter: Optional[date]
    role_filter: Optional[List[EmployeeRole]]
    status_breakdown: Dict[str, int]  # Count by status
    role_breakdown: Dict[str, int]    # Count by role

class AdminLeaveRequestListResponse(BaseModel):
    """Enhanced leave request list response for admin with role filtering"""
    leave_requests: List[LeaveRequestRead]
    total_count: int
    page: int
    limit: int
    total_pages: int
    role_filter: Optional[List[EmployeeRole]]
    status_filter: Optional[List[LeaveStatus]]
    role_breakdown: Dict[str, int]
    status_breakdown: Dict[str, int]

# Fix the duplicate employee_role field in LeaveRequestRead
class LeaveRequestRead(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    employee_role: EmployeeRole  # Keep only one
    leave_type: LeaveType
    from_date: date
    to_date: date
    reason: str
    status: LeaveStatus
    requested_at: datetime
    # Admin tracking fields
    last_updated_by_admin_id: Optional[UUID] = None
    last_updated_by_admin_username: Optional[str] = None
    status_updated_at: Optional[datetime] = None

# Query filters for different endpoints
class AttendanceQueryFilters(BaseModel):
    """Query filters for attendance endpoints"""
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    roles: Optional[List[EmployeeRole]] = None
    status: Optional[List[AttendanceStatus]] = None
    employee_ids: Optional[List[UUID]] = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)
    
    @validator('roles', 'status', pre=True)
    def parse_list_params(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return v.split(',')
        return v

class LeaveRequestQueryFilters(BaseModel):
    """Query filters for leave request endpoints"""
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    roles: Optional[List[EmployeeRole]] = None
    status: Optional[List[LeaveStatus]] = None
    leave_types: Optional[List[LeaveType]] = None
    employee_ids: Optional[List[UUID]] = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)
    
    @validator('roles', 'status', 'leave_types', pre=True)
    def parse_list_params(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return v.split(',')
        return v

# Bulk operations for admin
class BulkEmployeeRoleUpdate(BaseModel):
    """For updating multiple employees' roles at once"""
    employee_ids: List[UUID]
    new_role: EmployeeRole
    
class BulkLeaveStatusUpdate(BaseModel):
    """For approving/rejecting multiple leave requests"""
    leave_request_ids: List[UUID]
    new_status: LeaveStatus
    admin_notes: Optional[str] = None

# Enhanced role permissions response with more detail
class DetailedRolePermissionsResponse(BaseModel):
    """Detailed role permissions for frontend configuration"""
    role: EmployeeRole
    permissions: Dict[str, bool]
    allowed_endpoints: List[str]
    restricted_endpoints: List[str]
    role_description: str
    
    @classmethod
    def for_role(cls, role: EmployeeRole):
        permissions = {
            "can_request_leave": RolePermissions.can_request_leave(role),
            "has_shift_schedule": RolePermissions.has_shift_schedule(role),
            "can_clock_in_out": RolePermissions.can_clock_in_out(role),
            "has_fixed_hours": RolePermissions.has_fixed_hours(role),
            "can_view_reports": RolePermissions.can_view_reports(role),
        }
        
        # Define role descriptions and endpoints
        role_configs = {
            EmployeeRole.ANNOTATION_TEAM: {
                "description": "Annotation team members with shift-based scheduling",
                "allowed": ["attendance", "leaves", "shifts", "reports", "clock_in_out"],
                "restricted": []
            },
            EmployeeRole.DEV_TEAM: {
                "description": "Development team with fixed hours (10 AM - 6 PM)",
                "allowed": ["attendance", "leaves", "reports", "clock_in_out"],
                "restricted": ["shifts"]
            },
            EmployeeRole.INTERN: {
                "description": "Interns with limited access",
                "allowed": ["reports"],
                "restricted": ["attendance", "leaves", "shifts", "clock_in_out"]
            }
        }
        
        config = role_configs[role]
        return cls(
            role=role,
            permissions=permissions,
            allowed_endpoints=config["allowed"],
            restricted_endpoints=config["restricted"],
            role_description=config["description"]
        )
    