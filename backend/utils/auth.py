from uuid import UUID
from fastapi import Depends, HTTPException, Header
from sqlmodel import Session, select
from models.postgres_models import Employee, Admin, EmployeeRole, Session as DBSession
from database.db import get_session
from typing import Optional, Union, List
from datetime import datetime

async def get_current_employee(
    authorization: str = Header(None),
    session: Session = Depends(get_session)
) -> Employee:
    """Get the current authenticated employee from the Authorization header"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    
    # Extract token and strip any whitespace
    token = authorization[7:].strip()
    
    # Find session by token
    db_session = session.exec(
        select(DBSession)
        .where(DBSession.token == token)
        .where(DBSession.employee_id != None)
        .where(DBSession.expires_at > datetime.utcnow())
    ).first()
    
    if not db_session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Get associated employee
    employee = session.get(Employee, db_session.employee_id)
    if not employee:
        raise HTTPException(status_code=401, detail="Employee not found")
    
    return employee

async def get_current_admin(
    authorization: str = Header(None),
    session: Session = Depends(get_session)
) -> Admin:
    """Get the current authenticated admin from the Authorization header"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    
    # Extract token and strip any whitespace
    token = authorization[7:].strip()
    
    # Find session by token
    db_session = session.exec(
        select(DBSession)
        .where(DBSession.token == token)
        .where(DBSession.admin_id != None)
        .where(DBSession.expires_at > datetime.utcnow())
    ).first()
    
    if not db_session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Get associated admin
    admin = session.get(Admin, db_session.admin_id)
    if not admin:
        raise HTTPException(status_code=401, detail="Admin not found")
    
    return admin

async def get_current_user(
    authorization: str = Header(None),
    session: Session = Depends(get_session)
) -> Union[Employee, Admin]:
    """Get the current authenticated user (either employee or admin) from the Authorization header"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    
    # Extract token and strip any whitespace
    token = authorization[7:].strip()
    
    # Find session by token
    db_session = session.exec(
        select(DBSession)
        .where(DBSession.token == token)
        .where(DBSession.expires_at > datetime.utcnow())
    ).first()
    
    if not db_session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Check if it's an employee session
    if db_session.employee_id:
        employee = session.get(Employee, db_session.employee_id)
        if not employee:
            raise HTTPException(status_code=401, detail="Employee not found")
        return employee
    
    # Check if it's an admin session
    if db_session.admin_id:
        admin = session.get(Admin, db_session.admin_id)
        if not admin:
            raise HTTPException(status_code=401, detail="Admin not found")
        return admin
    
    raise HTTPException(status_code=401, detail="Invalid session")

def require_role(allowed_roles: list):
    """Decorator factory to create role-based access control dependencies"""
    def role_dependency(current_user: Employee = Depends(get_current_employee)):
        if hasattr(current_user, 'role') and current_user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_dependency

def require_admin_or_role(allowed_roles: list):
    """Dependency that allows either admin access or specific employee roles"""
    async def admin_or_role_dependency(
        authorization: str = Header(None),
        session: Session = Depends(get_session)
    ):
        current_user = await get_current_user(authorization, session)
        
        # If user is admin, allow access
        if isinstance(current_user, Admin):
            return current_user
        
        # If user is employee, check role
        if isinstance(current_user, Employee):
            if hasattr(current_user, 'role') and current_user.role.value in allowed_roles:
                return current_user
            else:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied. Required roles: {', '.join(allowed_roles)} or admin access"
                )
        
        raise HTTPException(status_code=401, detail="Invalid user type")
    
    return admin_or_role_dependency

def require_admin():
    """Dependency that requires admin access only"""
    async def admin_dependency(current_admin: Admin = Depends(get_current_admin)):
        return current_admin
    return admin_dependency

def require_admin_or_employee():
    """Dependency that allows both admin and any employee"""
    async def admin_or_employee_dependency(
        authorization: str = Header(None),
        session: Session = Depends(get_session)
    ):
        return await get_current_user(authorization, session)
    return admin_or_employee_dependency

def check_employee_access_to_resource(
    current_user: Union[Employee, Admin],
    resource_employee_id: UUID,
    allow_admin: bool = True
) -> bool:
    """
    Check if current user can access a resource belonging to a specific employee
    - Employees can only access their own resources
    - Admins can access all resources (if allow_admin=True)
    """
    # Admin has access to all resources
    if allow_admin and isinstance(current_user, Admin):
        return True
    
    # Employee can only access their own resources
    if isinstance(current_user, Employee):
        return current_user.id == resource_employee_id
    
    return False

def filter_employees_by_role(
    employees: List[Employee], 
    allowed_roles: Optional[List[EmployeeRole]] = None
) -> List[Employee]:
    """Filter employees by their roles"""
    if not allowed_roles:
        return employees
    
    role_values = [role.value for role in allowed_roles]
    return [emp for emp in employees if emp.role.value in role_values]

def get_role_based_query_filter(
    current_user: Union[Employee, Admin],
    requested_roles: Optional[List[EmployeeRole]] = None
) -> Optional[List[str]]:
    """
    Get role filter for database queries based on current user and requested roles
    - Admins can filter by any roles
    - Employees can only see their own role data
    """
    # Admin can see all roles or filter by requested roles
    if isinstance(current_user, Admin):
        if requested_roles:
            return [role.value for role in requested_roles]
        return None  # No filter, show all
    
    # Employees can only see their own role
    if isinstance(current_user, Employee):
        return [current_user.role.value]
    
    return []

# Enhanced role requirement with better error messages
def require_role_with_details(allowed_roles: list, operation_name: str = "this operation"):
    """Enhanced role requirement with descriptive error messages"""
    def role_dependency(current_user: Employee = Depends(get_current_employee)):
        if hasattr(current_user, 'role') and current_user.role.value not in allowed_roles:
            role_names = {
                'annotation_team': 'Annotation Team',
                'dev_team': 'Development Team', 
                'intern': 'Intern'
            }
            allowed_names = [role_names.get(role, role) for role in allowed_roles]
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied for {operation_name}. This feature is only available to: {', '.join(allowed_names)}. Your role: {role_names.get(current_user.role.value, current_user.role.value)}"
            )
        return current_user
    return role_dependency

# Helper for admin endpoints that need to respect employee role restrictions
def get_admin_with_role_context(allowed_employee_roles: Optional[List[str]] = None):
    """
    For admin endpoints that work with specific employee roles
    Returns admin but validates that the operation is valid for the specified roles
    """
    async def admin_role_context_dependency(
        current_admin: Admin = Depends(get_current_admin)
    ):
        # Admin has access, but we attach role context for business logic
        current_admin._context_allowed_roles = allowed_employee_roles
        return current_admin
    return admin_role_context_dependency

# Unified access control for endpoints that serve both admin and employees
class AccessControl:
    @staticmethod
    def employee_own_data_or_admin(resource_employee_id: UUID):
        """Employee can access own data, admin can access any data"""
        async def access_dependency(
            current_user: Union[Employee, Admin] = Depends(get_current_user)
        ):
            if not check_employee_access_to_resource(current_user, resource_employee_id):
                if isinstance(current_user, Employee):
                    raise HTTPException(
                        status_code=403,
                        detail="You can only access your own data"
                    )
                else:
                    raise HTTPException(
                        status_code=403,
                        detail="Access denied"
                    )
            return current_user
        return access_dependency
    
    @staticmethod
    def role_based_or_admin(allowed_roles: List[str], operation: str = "this operation"):
        """Either specific employee roles or admin access"""
        async def role_or_admin_dependency(
            current_user: Union[Employee, Admin] = Depends(get_current_user)
        ):
            if isinstance(current_user, Admin):
                return current_user
            
            if isinstance(current_user, Employee):
                if current_user.role.value not in allowed_roles:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Access denied for {operation}. Required roles: {', '.join(allowed_roles)}"
                    )
                return current_user
            
            raise HTTPException(status_code=401, detail="Invalid user type")
        return role_or_admin_dependency

