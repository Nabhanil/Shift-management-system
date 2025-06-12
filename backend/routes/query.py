# BACKEND - Enhanced with Role-Based Access Control

from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, func, select
from typing import List, Optional
from uuid import UUID

from database.db import get_session
from models.postgres_models import (
    Admin, LeaveRequest, ShiftSwapRequest, Employee, LeaveStatus, EmployeeRole
)
from models.models import (
    LeaveRequestCreate, LeaveRequestRead, LeaveStatsResponse,
    ShiftSwapRequestCreate, ShiftSwapRequestRead
)
from utils.auth import (
    get_current_employee, get_current_admin, get_current_user,
    AccessControl, check_employee_access_to_resource
)
import logging
from sqlalchemy.orm import aliased

query_router = APIRouter()

logger = logging.getLogger(__name__)

# Enhanced leave types with role restrictions (using your LeaveType enum values)
LEAVE_TYPES = {
    "all": ["casual", "sick", "unpaid"],
    "annotation_team": ["casual", "sick", "unpaid"],
    "dev_team": ["casual", "sick", "unpaid"],
    "intern": ["casual", "sick"]  # Limited leave types for interns (no unpaid leave)
}

# Role hierarchy for access control
ROLE_HIERARCHY = {
    "dev_team": ["dev_team", "annotation_team", "intern"],  # Dev team can see all
    "annotation_team": ["annotation_team", "intern"],       # Annotation team can see annotation + intern
    "intern": ["intern"]                                   # Interns can only see intern data
}

def get_allowed_leave_types_for_role(role: str) -> List[str]:
    """Get allowed leave types based on employee role"""
    return LEAVE_TYPES.get(role, LEAVE_TYPES["intern"])

def get_viewable_roles(current_role: str) -> List[str]:
    """Get roles that current role can view based on hierarchy"""
    return ROLE_HIERARCHY.get(current_role, [current_role])

# -------------------- Employee Routes --------------------

@query_router.post("/leave", response_model=LeaveRequestRead, tags=["Emp_Query"])
def request_leave(
    leave_data: LeaveRequestCreate,
    db: Session = Depends(get_session),
    current_employee=Depends(get_current_employee)
):
    """Create leave request with role-based leave type validation"""
    logger.info(f"Creating {leave_data.leave_type} leave request for {current_employee.email} (Role: {current_employee.role.value})")

    # Validate if the employee's role can request this leave type
    allowed_leave_types = get_allowed_leave_types_for_role(current_employee.role.value)
    if leave_data.leave_type not in allowed_leave_types:
        raise HTTPException(
            status_code=403,
            detail=f"Your role ({current_employee.role.value}) is not authorized to request {leave_data.leave_type}. Allowed types: {', '.join(allowed_leave_types)}"
        )

    try:
        leave = LeaveRequest(
            employee_id=current_employee.id,
            leave_type=leave_data.leave_type,
            from_date=leave_data.from_date,
            to_date=leave_data.to_date,
            reason=leave_data.reason,
        )
        
        db.add(leave)
        db.commit()
        db.refresh(leave)
        
        logger.info(f"Successfully created leave request ID: {leave.id}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating leave request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to process leave request"
        )

    return LeaveRequestRead(
        id=leave.id,
        employee_id=leave.employee_id,
        employee_name=current_employee.name,
        leave_type=leave.leave_type,
        from_date=leave.from_date,
        to_date=leave.to_date,
        reason=leave.reason,
        status=leave.status,
        employee_role=leave.employee.role,
        requested_at=leave.requested_at
    )


@query_router.post("/swap", response_model=ShiftSwapRequestRead, tags=["Emp_Query"])
def request_swap(
    data: ShiftSwapRequestCreate,
    session: Session = Depends(get_session),
    current_employee=Depends(get_current_employee)
):
    """Create shift swap request with role-based validation"""
    if current_employee.id != data.requester_id:
        raise HTTPException(status_code=403, detail="Unauthorized to swap for another employee")

    receiver = session.get(Employee, data.receiver_id)
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    # Role-based swap restrictions
    viewable_roles = get_viewable_roles(current_employee.role.value)
    if receiver.role.value not in viewable_roles:
        raise HTTPException(
            status_code=403, 
            detail=f"You cannot request swaps with {receiver.role.value} role members. Your role ({current_employee.role.value}) can only interact with: {', '.join(viewable_roles)}"
        )

    swap = ShiftSwapRequest(**data.dict())
    session.add(swap)
    session.commit()
    session.refresh(swap)

    return ShiftSwapRequestRead(
        **swap.model_dump(),
        requester_name=current_employee.name,
        receiver_name=receiver.name
    )


@query_router.get("/leave/{employee_id}", response_model=List[LeaveRequestRead], tags=["Emp_Query"])
def get_employee_leaves(
    employee_id: UUID,
    session: Session = Depends(get_session),
    current_employee=Depends(get_current_employee)
):
    """Get employee leaves with role-based access control"""
    # Check if employee can access this data
    if current_employee.id != employee_id:
        # Check if current employee's role allows viewing other employees' data
        target_employee = session.get(Employee, employee_id)
        if not target_employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        viewable_roles = get_viewable_roles(current_employee.role.value)
        if target_employee.role.value not in viewable_roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Unauthorized to access leaves of {target_employee.role.value} role members"
            )

    leaves = session.exec(select(LeaveRequest).where(LeaveRequest.employee_id == employee_id)).all()
    
    # Get employee details for response
    employee = session.get(Employee, employee_id)
    employee_name = employee.name if employee else "Unknown"
    
    return [
        LeaveRequestRead(
            **leave.model_dump(), 
            employee_name=employee_name,
            employee_role=employee.role if employee else None
        ) 
        for leave in leaves
    ]


@query_router.get("/swap/{requester_id}", response_model=List[ShiftSwapRequestRead], tags=["Emp_Query"])
def get_employee_swaps(
    requester_id: UUID,
    session: Session = Depends(get_session),
    current_employee=Depends(get_current_employee)
):
    """Get employee swaps with role-based access control"""
    # Check if employee can access this data
    if current_employee.id != requester_id:
        # Check if current employee's role allows viewing other employees' data
        target_employee = session.get(Employee, requester_id)
        if not target_employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        viewable_roles = get_viewable_roles(current_employee.role.value)
        if target_employee.role.value not in viewable_roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Unauthorized to access swaps of {target_employee.role.value} role members"
            )

    swaps = session.exec(select(ShiftSwapRequest).where(ShiftSwapRequest.requester_id == requester_id)).all()
    response = []
    
    for swap in swaps:
        requester = session.get(Employee, swap.requester_id)
        receiver = session.get(Employee, swap.receiver_id)
        response.append(ShiftSwapRequestRead(
            **swap.model_dump(),
            requester_name=requester.name if requester else "Unknown",
            receiver_name=receiver.name if receiver else "Unknown"
        ))
    return response


@query_router.get("/available-leave-types", response_model=List[str], tags=["Emp_Query"])
def get_available_leave_types(
    current_employee=Depends(get_current_employee)
):
    """Get leave types available for current employee's role"""
    return get_allowed_leave_types_for_role(current_employee.role.value)


@query_router.get("/team-members", response_model=List[dict], tags=["Emp_Query"])
def get_team_members(
    session: Session = Depends(get_session),
    current_employee=Depends(get_current_employee)
):
    """Get team members that current employee can interact with"""
    viewable_roles = get_viewable_roles(current_employee.role.value)
    
    # Query employees with viewable roles
    employees = session.exec(
        select(Employee).where(Employee.role.in_(viewable_roles))
    ).all()
    
    return [
        {
            "id": emp.id,
            "name": emp.name,
            "email": emp.email,
            "role": emp.role.value,
            "is_current_user": emp.id == current_employee.id
        }
        for emp in employees
    ]


# -------------------- Admin Routes --------------------

@query_router.get("/admin/leave-types", response_model=List[str], tags=["Admin"])
def get_leave_types(
    search: Optional[str] = None,
    role_filter: Optional[str] = Query(None, description="Filter by employee role"),
    current_admin=Depends(get_current_admin)
):
    """Get leave types with optional role-based filtering"""
    # Get leave types based on role filter
    if role_filter and role_filter in LEAVE_TYPES:
        leave_types = LEAVE_TYPES[role_filter]
    else:
        leave_types = LEAVE_TYPES["all"]
    
    if not search:
        return leave_types
    
    # Filter leave types that contain the search term (case insensitive)
    filtered_types = [leave_type for leave_type in leave_types 
        if search.lower() in leave_type.lower()]
    
    return filtered_types


@query_router.get("/admin/team-roles", response_model=List[dict], tags=["Admin"])
def get_team_roles(
    current_admin=Depends(get_current_admin)
):
    """Get all available team roles with statistics"""
    return [
        {"role": "dev_team", "display_name": "Development Team", "hierarchy_level": 1},
        {"role": "annotation_team", "display_name": "Annotation Team", "hierarchy_level": 2},
        {"role": "intern", "display_name": "Intern", "hierarchy_level": 3}
    ]


@query_router.get("/admin/leaves", response_model=LeaveStatsResponse, tags=["Admin"])
def get_all_leave_requests(
    employee_id: Optional[UUID] = None,
    leave_type: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    team_role: Optional[str] = Query(None, description="Filter by employee role/team"),
    session: Session = Depends(get_session),
    current_admin=Depends(get_current_admin)
):
    """Get all leave requests with enhanced filtering including team roles"""
    # Base query for detailed leave requests
    detail_query = select(
        LeaveRequest,
        Employee.name.label("employee_name"),
        Employee.role.label("employee_role"),
        Employee.email.label("employee_email"),
        Admin.username.label("admin_username")
    ).outerjoin(
        Employee, LeaveRequest.employee_id == Employee.id
    ).outerjoin(
        Admin, LeaveRequest.last_updated_by_admin_id == Admin.id
    )
    
    # Base query for counts aggregation
    count_query = select(
        LeaveRequest.leave_type,
        func.count(LeaveRequest.id).label("count")
    ).outerjoin(
        Employee, LeaveRequest.employee_id == Employee.id
    ).group_by(LeaveRequest.leave_type)
    
    # Team role stats query
    team_stats_query = select(
        Employee.role.label("team_role"),
        func.count(LeaveRequest.id).label("count")
    ).outerjoin(
        Employee, LeaveRequest.employee_id == Employee.id
    ).group_by(Employee.role)
    
    # Apply filters to all queries
    filters = []
    if employee_id:
        filters.append(LeaveRequest.employee_id == employee_id)
    if leave_type:
        filters.append(LeaveRequest.leave_type == leave_type)
    if status:
        filters.append(LeaveRequest.status == status)
    if start_date:
        filters.append(LeaveRequest.from_date >= start_date)
    if end_date:
        filters.append(LeaveRequest.to_date <= end_date)
    if team_role:
        filters.append(Employee.role == team_role)

    if filters:
        detail_query = detail_query.where(*filters)
        count_query = count_query.where(*filters)
        team_stats_query = team_stats_query.where(*filters)
    
    # Execute count queries
    count_result = session.exec(count_query).all()
    leave_counts = {row[0]: row[1] for row in count_result}
    total_leaves = sum(leave_counts.values())
    
    # Execute team stats query
    team_stats_result = session.exec(team_stats_query).all()
    team_stats = {row[0].value if row[0] else "unknown": row[1] for row in team_stats_result}
    
    # Execute detail query
    detail_result = session.exec(detail_query).all()
    leaves_response = []
    
    for row in detail_result:
        leave_request = row[0]
        employee_name = row[1] or "Unknown"
        employee_role = row[2].value if row[2] else "Unknown"
        employee_email = row[3] or "Unknown"
        admin_username = row[4]

        response_data = leave_request.model_dump()
        response_data["employee_name"] = employee_name
        response_data["employee_role"] = employee_role
        response_data["employee_email"] = employee_email
        response_data["last_updated_by_admin_username"] = admin_username
        
        leaves_response.append(response_data)

    # Enhanced response with team statistics
    return LeaveStatsResponse(
        leave_counts=leave_counts,
        total_leaves=total_leaves,
        team_stats=team_stats,
        leaves=leaves_response
    )


@query_router.get("/admin/swaps", response_model=List[ShiftSwapRequestRead], tags=["Admin"])
def get_all_swap_requests(
    team_role: Optional[str] = Query(None, description="Filter by requester team role"),
    status: Optional[str] = Query(None, description="Filter by status"),
    session: Session = Depends(get_session),
    current_admin=Depends(get_current_admin)
):
    """Get all swap requests with enhanced filtering"""
    # Create aliases for Employee table to distinguish between requester and receiver
    RequesterEmployee = aliased(Employee)
    ReceiverEmployee = aliased(Employee)
    
    query = select(
        ShiftSwapRequest,
        RequesterEmployee.name.label("requester_name"),
        RequesterEmployee.role.label("requester_role"),
        RequesterEmployee.email.label("requester_email"),
        ReceiverEmployee.name.label("receiver_name"),
        ReceiverEmployee.role.label("receiver_role"),
        ReceiverEmployee.email.label("receiver_email"),
        Admin.username.label("admin_username")
    ).outerjoin(
        RequesterEmployee, ShiftSwapRequest.requester_id == RequesterEmployee.id
    ).outerjoin(
        ReceiverEmployee, ShiftSwapRequest.receiver_id == ReceiverEmployee.id
    ).outerjoin(
        Admin, ShiftSwapRequest.last_updated_by_admin_id == Admin.id
    )
    
    # Apply filters
    filters = []
    if team_role:
        filters.append(RequesterEmployee.role == team_role)
    if status:
        filters.append(ShiftSwapRequest.status == status)
    
    if filters:
        query = query.where(*filters)
   
    result = session.exec(query).all()
    response = []
   
    for row in result:
        swap = row[0]
        requester_name = row[1] or "Unknown"
        requester_role = row[2].value if row[2] else "Unknown"
        requester_email = row[3] or "Unknown"
        receiver_name = row[4] or "Unknown"
        receiver_role = row[5].value if row[5] else "Unknown" 
        receiver_email = row[6] or "Unknown"
        admin_username = row[7]
       
        response_data = swap.model_dump()
        response_data["requester_name"] = requester_name
        response_data["requester_role"] = requester_role
        response_data["requester_email"] = requester_email
        response_data["receiver_name"] = receiver_name
        response_data["receiver_role"] = receiver_role
        response_data["receiver_email"] = receiver_email
        response_data["last_updated_by_admin_username"] = admin_username
       
        response.append(ShiftSwapRequestRead(**response_data))
   
    return response


@query_router.patch("/admin/leave/{leave_id}/status", response_model=LeaveRequestRead, tags=["Admin"])
def update_leave_status(
    leave_id: UUID,
    status: LeaveStatus,
    session: Session = Depends(get_session),
    current_admin=Depends(get_current_admin)
):
    """Update leave status with admin tracking"""
    # Get the leave request
    leave_request = session.get(LeaveRequest, leave_id)
    if not leave_request:
        raise HTTPException(status_code=404, detail="Leave request not found")
    
    # Update status with admin tracking
    leave_request.status = status
    leave_request.last_updated_by_admin_id = current_admin.id
    leave_request.status_updated_at = datetime.now(timezone.utc)
    
    # Save changes
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)
    
    # Get employee and admin information
    employee = session.get(Employee, leave_request.employee_id)
    admin = session.get(Admin, current_admin.id)
    
    # Prepare response data for LeaveRequestRead model
    response_data = leave_request.model_dump()
    response_data["employee_name"] = employee.name if employee else "Unknown"
    response_data["employee_role"] = employee.role.value if employee and employee.role else "Unknown"
    response_data["employee_email"] = employee.email if employee else "Unknown"
    response_data["last_updated_by_admin_username"] = admin.username if admin else None
    
    # Return response
    return LeaveRequestRead(**response_data)


@query_router.patch("/admin/swap/{swap_id}/status", response_model=ShiftSwapRequestRead, tags=["Admin"])
def update_swap_status(
    swap_id: UUID,
    status: LeaveStatus,
    session: Session = Depends(get_session),
    current_admin=Depends(get_current_admin)
):
    """Update swap status with admin tracking"""
    swap = session.get(ShiftSwapRequest, swap_id)
    if not swap:
        raise HTTPException(status_code=404, detail="Swap request not found")
    
    # Update status with admin tracking
    swap.status = status
    swap.last_updated_by_admin_id = current_admin.id
    swap.status_updated_at = datetime.now(timezone.utc)
    
    session.add(swap)
    session.commit()
    session.refresh(swap)
    
    # Get employee and admin information
    requester = session.get(Employee, swap.requester_id)
    receiver = session.get(Employee, swap.receiver_id)
    admin = session.get(Admin, current_admin.id)
    
    # Prepare response
    response_data = swap.model_dump()
    response_data["requester_name"] = requester.name if requester else "Unknown"
    response_data["requester_role"] = requester.role.value if requester and requester.role else "Unknown"
    response_data["requester_email"] = requester.email if requester else "Unknown"
    response_data["receiver_name"] = receiver.name if receiver else "Unknown"
    response_data["receiver_role"] = receiver.role.value if receiver and receiver.role else "Unknown"
    response_data["receiver_email"] = receiver.email if receiver else "Unknown"
    response_data["last_updated_by_admin_username"] = admin.username if admin else None
    
    return ShiftSwapRequestRead(**response_data)