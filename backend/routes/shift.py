# shifts.py

from datetime import date, datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlmodel import Session, func, select
# Assuming models are correctly defined in these paths
from utils.auth import get_current_admin, get_current_employee
from models.postgres_models import Admin, Employee, ShiftAssignment, ShiftSwapRequest
from models.models import EmployeeCreate, EmployeeRead, EmployeeRole, ShiftAssignmentCreate, ShiftAssignmentRead
from database.db import get_session
from uuid import UUID
import calendar
from typing import Dict, List, Tuple, Optional
import random
import logging

shift_router = APIRouter()
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CRUD Endpoints ---
# [CRUD Endpoints remain unchanged - snipped for brevity]
@shift_router.post("/employees/", response_model=EmployeeRead, tags=["CRUD"])
def create_employee(employee: EmployeeCreate, session: Session = Depends(get_session)):
    # Consider adding DB unique constraint on name or check uniqueness here
    db_employee = Employee.model_validate(employee)
    session.add(db_employee)
    session.commit()
    session.refresh(db_employee)
    logging.info(f"Created employee: {db_employee.name} (ID: {db_employee.id})")
    return db_employee


@shift_router.get("/employees/", response_model=list[EmployeeRead], tags=["CRUD"])
def get_employees(
    role: EmployeeRole = EmployeeRole.ANNOTATION_TEAM,
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
):
    query = select(Employee).where(Employee.role == role).order_by(Employee.name)
    employees = session.exec(query).all()
    return employees

@shift_router.get("/employees/by-team", response_model=List[EmployeeRead], tags=["Employees"])
def get_employees_by_team(
    session: Session = Depends(get_session),
    current_employee: Employee = Depends(get_current_employee)
):
    query = (
        select(Employee)
        .where(Employee.role == current_employee.role)
        .order_by(Employee.name)
    )
    employees = session.exec(query).all()
    return employees

@shift_router.post("/shift_assignments/", response_model=ShiftAssignmentRead, tags=["CRUD"])
def create_shift_assignment(shift_assignment: ShiftAssignmentCreate, session: Session = Depends(get_session)):
    employee = session.get(Employee, shift_assignment.employee_id)
    if not employee:
         raise HTTPException(status_code=404, detail=f"Employee with ID {shift_assignment.employee_id} not found")
    # <<< MODIFIED: Check against SHIFT_NAMES keys for validation >>>
    if shift_assignment.shift not in SHIFT_NAMES.keys():
         raise HTTPException(status_code=400, detail=f"Invalid shift code: {shift_assignment.shift}. Valid codes: {list(SHIFT_NAMES.keys())}")

    db_shift = ShiftAssignment.model_validate(shift_assignment)
    session.add(db_shift)
    session.commit()
    session.refresh(db_shift)
    logging.info(f"Created shift assignment for Employee ID {db_shift.employee_id} on Day {db_shift.day}")
    return db_shift



@shift_router.get("/shift_assignments/", response_model=list[ShiftAssignmentRead], tags=["CRUD"])
def get_shift_assignments(
    session: Session = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)  
):
    assignments = session.exec(
        select(ShiftAssignment).order_by(ShiftAssignment.shift_date, ShiftAssignment.employee_id)
    ).all()
    return assignments



@shift_router.get("/shift_assignments/{employee_id}", response_model=list[ShiftAssignmentRead], tags=["CRUD"])
def get_shift_assignments_by_employee(employee_id: UUID, session: Session = Depends(get_session)):
    statement = select(ShiftAssignment).where(ShiftAssignment.employee_id == employee_id).order_by(ShiftAssignment.shift_date)
    shifts = session.exec(statement).all()
    if not shifts:
        # Check if employee exists even if they have no shifts
        employee = session.get(Employee, employee_id)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
    return shifts


@shift_router.delete("/employees/{employee_id}", tags=["CRUD"])
def delete_employee(employee_id: UUID, session: Session = Depends(get_session)):
    employee = session.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    employee_name = employee.name
    logging.warning(f"Attempting to delete employee '{employee_name}' (ID: {employee_id}) and their assignments.")

    # Delete shift swap requests involving this employee
    swap_requests = session.exec(
        select(ShiftSwapRequest).where(
            (ShiftSwapRequest.requester_id == employee_id) |
            (ShiftSwapRequest.receiver_id == employee_id)
        )
    ).all()
    num_swap_requests = len(swap_requests)
    for request in swap_requests:
        session.delete(request)
    if num_swap_requests > 0:
        logging.info(f"Deleted {num_swap_requests} shift swap requests related to employee '{employee_name}'.")

    # Delete shift assignments
    assignments_to_delete = session.exec(
        select(ShiftAssignment).where(ShiftAssignment.employee_id == employee_id)
    ).all()
    num_assignments = len(assignments_to_delete)
    for assignment in assignments_to_delete:
        session.delete(assignment)
    if num_assignments > 0:
        logging.info(f"Deleted {num_assignments} shift assignments for employee '{employee_name}'.")

    # Delete the employee
    session.delete(employee)
    session.commit()

    logging.info(f"Successfully deleted employee '{employee_name}'.")
    return {"detail": "Employee and related data deleted successfully"}



@shift_router.get("/user/employees/", response_model=list[EmployeeRead], tags=["User"])
def get_employees_user(
    session: Session = Depends(get_session),
    current_employee: Employee = Depends(get_current_employee) 
):
    """Get all employees - User/Employee access"""
    employees = session.exec(select(Employee).order_by(Employee.name)).all()
    return employees

@shift_router.get("/user/shift_assignments/", response_model=list[ShiftAssignmentRead], tags=["User"])
def get_shift_assignments_user(
    session: Session = Depends(get_session),
    current_employee: Employee = Depends(get_current_employee)  
):
    """Get all shift assignments - User/Employee access"""
    assignments = session.exec(
        select(ShiftAssignment).order_by(ShiftAssignment.shift_date, ShiftAssignment.employee_id)
    ).all()
    return assignments



@shift_router.delete("/shift_schedule/", tags=["CRUD"])
async def delete_shift_schedule(year: Optional[int] = None, month: Optional[int] = None, session: Session = Depends(get_session)):
    """Delete the entire shift schedule for the specified or current month."""
    now = datetime.now()
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month

    # Validate year and month
    try:
        total_days = calendar.monthrange(target_year, target_month)[1]
    except calendar.IllegalMonthError:
        raise HTTPException(status_code=400, detail="Invalid month or year")

    # Prevent deleting past months
    current_year, current_month = now.year, now.month
    if (target_year < current_year) or (target_year == current_year and target_month < current_month):
        raise HTTPException(status_code=400, detail="Cannot delete schedules for past months")

    # Calculate date range
    start_date = datetime(target_year, target_month, 1).date()
    end_date_exclusive = start_date + timedelta(days=total_days)  # Fixed: Removed redundant .date() call

    # Check if shifts exist
    existing_count = session.exec(
        select(func.count(ShiftAssignment.id)).where(
            ShiftAssignment.shift_date >= start_date,
            ShiftAssignment.shift_date < end_date_exclusive
        )
    ).one()

    if existing_count == 0:
        month_name = start_date.strftime('%B %Y')
        return {
            "message": f"No shift assignments found for {month_name}."
        }

    # Delete assignments
    try:
        delete_stmt = ShiftAssignment.__table__.delete().where(
            ShiftAssignment.shift_date >= start_date,
            ShiftAssignment.shift_date < end_date_exclusive
        )
        result = session.execute(delete_stmt)
        num_deleted = result.rowcount
        session.commit()
        logging.info(f"Deleted {num_deleted} shift assignments for {target_year}-{target_month:02d}.")
        month_name = start_date.strftime('%B %Y')
        return {
            "message": f"Successfully deleted {num_deleted} shift assignments for {month_name}."
        }
    except Exception as e:
        session.rollback()
        logging.error(f"Error deleting shift schedule for {target_year}-{target_month:02d}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete shift schedule: {e}")


# ---------------------------------------------------------------------------------------------------
# MAIN LOGICS & CONFIGURATION
# ---------------------------------------------------------------------------------------------------

SHIFT_MAPPING = {'M': 1, 'E': 2, 'N': 3, 'O': 0}
SHIFTS = [1, 2, 3]  # Morning, Evening, Night
SHIFT_NAMES = {1: 'Morning', 2: 'Evening', 3: 'Night', 0: 'Off'}
TARGET_SHIFTS_PER_DAY = {1: 2, 2: 2, 3: 1}  # M=2, Strict E=2, Strict N=1, with 1 Off implied

# ----------------------------------- Constraint Checkers ------------------------------------------------------------

def is_shift_viable(employee_shifts: Dict[str, List[Optional[int]]], name: str, day: int, shift: Optional[int], total_days: int) -> bool:
    """Check if assigning 'shift' to 'name' on 'day' meets constraints."""
    if shift is None:
        return False
    if shift == 0:
        return True

    shifts_list = employee_shifts.get(name, [])
    if day >= len(shifts_list):
        logging.error(f"Index out of bounds for {name} on day {day+1}")
        return False

    prev_shift = shifts_list[day-1] if day > 0 else None
    prev_prev_shift = shifts_list[day-2] if day > 1 else None

    # Mandatory Off after N-N
    if day >= 2 and prev_prev_shift == 3 and prev_shift == 3:
        if shift != 0:
            return False

    # M-after-N constraint
    if shift == 1 and prev_shift == 3:
        return False

    # Max two consecutive nights
    if shift == 3 and prev_shift == 3 and prev_prev_shift == 3:
        return False

    # Avoid N -> E -> M pattern
    if shift == 1 and day >= 2 and prev_shift == 2 and prev_prev_shift == 3:
        return False

    # Special patterns ending in M
    if shift == 1:
        if day >= 3 and shifts_list[day-3:day] == [3, 2, 2]:
            return False
        if day >= 4:
            if shifts_list[day-4:day] in [[3, 2, 3, 2], [2, 3, 2, 2]]:
                return False

    return True

def check_future_m_after_n(employee_shifts: Dict[str, List[Optional[int]]], name: str, day: int, total_days: int) -> bool:
    """Checks if the shift on 'day' causes M-after-N tomorrow."""
    if name not in employee_shifts or day + 1 >= total_days:
        return True
    
    current_shift = employee_shifts[name][day]
    next_day_shift = employee_shifts[name][day+1]
    if current_shift == 3 and next_day_shift == 1:
        return False
    return True

# ------------------------------------------------- Night Shift Pair Assignment ------------------------------------------------------

def assign_night_shift_pairs(employee_shifts, employee_names, total_days, days_with_offs_count):
    """Assign N-N pairs with 10-11 day gaps and off days, respecting one off per day."""
    last_pair_end = {emp: -100 for emp in employee_names}
    night_assigned = [False] * total_days

    for day in range(total_days - 1):
        if night_assigned[day] or night_assigned[day + 1]:
            continue

        candidates = [emp for emp in employee_names if last_pair_end[emp] + 10 <= day and 
            employee_shifts[emp][day] is None and employee_shifts[emp][day + 1] is None and
            (day + 2 >= total_days or (employee_shifts[emp][day + 2] is None and days_with_offs_count[day + 2] == 0))]
        
        if candidates:
            emp = min(candidates, key=lambda x: last_pair_end[x])
            employee_shifts[emp][day] = 3
            employee_shifts[emp][day + 1] = 3
            night_assigned[day] = True
            night_assigned[day + 1] = True
            last_pair_end[emp] = day + 1
            if day + 2 < total_days:
                employee_shifts[emp][day + 2] = 0
                days_with_offs_count[day + 2] = 1

    # Assign single N for remaining days if necessary
    for day in range(total_days):
        if not night_assigned[day]:
            candidates = [emp for emp in employee_names if employee_shifts[emp][day] is None and 
                is_shift_viable(employee_shifts, emp, day, 3, total_days)]
            if candidates:
                emp = random.choice(candidates)
                employee_shifts[emp][day] = 3
                logging.info(f"Assigned single N to {emp} on day {day+1}")

# --------------------------------- Core Shift Generation ----------------------------------------------------------------

def generate_optimized_shifts(employee_names: List[str], total_days: int) -> Dict[str, List[Optional[int]]]:
    """Generate shift schedule: N=1, E=2 strict, M=2, with exactly 1 Off per day."""
    min_required_employees = TARGET_SHIFTS_PER_DAY[1] + TARGET_SHIFTS_PER_DAY[2] + TARGET_SHIFTS_PER_DAY[3] + 1  # 2+2+1+1=6
    if len(employee_names) < min_required_employees:
        raise ValueError(f"At least {min_required_employees} employees required.")

    employee_shifts = {name: [None] * total_days for name in employee_names}
    shift_counts = {name: {code: 0 for code in SHIFT_NAMES.keys()} for name in employee_names}
    days_with_offs_count = {day: 0 for day in range(total_days)}

    # Phase 0: Assign Night Shift Pairs
    logging.info("Starting Phase 0: Assign Night Shift Pairs and Off Days")
    assign_night_shift_pairs(employee_shifts, employee_names, total_days, days_with_offs_count)
    logging.info("Finished Phase 0.")

    # Phase 1: Assign Off Days
    logging.info("Starting Phase 1: Assign Off Days")
    last_off_day = {name: -10 for name in employee_names}
    weekday_offs = {name: set() for name in employee_names}
    max_offs = 5  # Adjusted to ~total_days/num_employees for 30 days, 6 employees
    max_consecutive_work_days = 7
    total_weeks = (total_days + 6) // 7

    for day in range(total_days):
        for employee in employee_names:
            if day >= max_consecutive_work_days:
                work_streak = True
                consecutive_work = 0
                for i in range(max_consecutive_work_days + 1):
                    check_day = day - i
                    if check_day < 0:
                        break
                    if employee_shifts[employee][check_day] == 0:
                        work_streak = False
                        break
                    if employee_shifts[employee][check_day] is not None:
                        consecutive_work += 1
                if work_streak and consecutive_work > max_consecutive_work_days:
                    if employee_shifts[employee][day] is None and days_with_offs_count[day] == 0 and shift_counts[employee][0] < max_offs:
                        employee_shifts[employee][day] = 0
                        shift_counts[employee][0] += 1
                        last_off_day[employee] = day
                        weekday_offs[employee].add(day % 7)
                        days_with_offs_count[day] += 1

    for week in range(total_weeks):
        week_start = week * 7
        week_end = min(week_start + 7, total_days)
        shuffled_employees = list(employee_names)
        random.shuffle(shuffled_employees)
        for employee in shuffled_employees:
            if shift_counts[employee][0] >= max_offs:
                continue
            has_off_this_week = any(employee_shifts[employee][d] == 0 for d in range(week_start, week_end) if d < total_days and employee_shifts[employee][d] is not None)
            if has_off_this_week:
                continue
            viable_off_days = []
            for day in range(week_start, week_end):
                if day >= total_days or employee_shifts[employee][day] is not None or days_with_offs_count[day] > 0:
                    continue
                day_weekday = day % 7
                is_same_weekday_as_prev = day_weekday in weekday_offs[employee]
                gap_from_last = day - last_off_day[employee] if last_off_day[employee] >= 0 else float('inf')
                gap_ok = 5 <= gap_from_last <= 7 if gap_from_last != float('inf') else True
                score = (abs(gap_from_last - 6) if gap_ok else 100, 1 if is_same_weekday_as_prev else 0)
                viable_off_days.append((score, day))
            if not viable_off_days or min(v[0] for v in viable_off_days)[0] >= 100:
                viable_off_days = [(1000, day) for day in range(week_start, week_end) if day < total_days and employee_shifts[employee][day] is None and days_with_offs_count[day] == 0]
            if viable_off_days:
                viable_off_days.sort(key=lambda x: x[0])
                best_day = viable_off_days[0][1]
                employee_shifts[employee][best_day] = 0
                shift_counts[employee][0] += 1
                last_off_day[employee] = best_day
                weekday_offs[employee].add(best_day % 7)
                days_with_offs_count[best_day] += 1

    # Ensure exactly one off per day
    for day in range(total_days):
        if days_with_offs_count[day] == 0:
            candidates = [emp for emp in employee_names if employee_shifts[emp][day] is None and shift_counts[emp][0] < max_offs]
            if candidates:
                emp = random.choice(candidates)
                employee_shifts[emp][day] = 0
                shift_counts[emp][0] += 1
                days_with_offs_count[day] = 1
            else:
                logging.warning(f"Could not find an employee to assign off on day {day+1}")
    logging.info("Finished Phase 1.")

    # Phase 2: Initial Shift Assignments
    logging.info("Starting Phase 2: Initial Shift Assignments (First 28 days)")
    for day in range(min(28, total_days)):
        available_today = [emp for emp in employee_names if employee_shifts[emp][day] is None]
        if not available_today:
            continue
        shift_counts_day = {s: sum(1 for emp in employee_names if employee_shifts[emp][day] == s) for s in SHIFTS}

        # Assign Evening (exactly 2)
        needed_e = max(0, TARGET_SHIFTS_PER_DAY[2] - shift_counts_day.get(2, 0))
        if needed_e > 0:
            candidates_e = [emp for emp in available_today if is_shift_viable(employee_shifts, emp, day, 2, total_days)]
            candidates_e.sort(key=lambda x: shift_counts[x][2])
            for emp in candidates_e[:needed_e]:
                employee_shifts[emp][day] = 2
                shift_counts[emp][2] += 1
                available_today.remove(emp)

        # Assign Morning (exactly 2)
        shift_counts_day = {s: sum(1 for emp in employee_names if employee_shifts[emp][day] == s) for s in SHIFTS}
        needed_m = max(0, TARGET_SHIFTS_PER_DAY[1] - shift_counts_day.get(1, 0))
        if needed_m > 0:
            candidates_m = [emp for emp in available_today if is_shift_viable(employee_shifts, emp, day, 1, total_days)]
            candidates_m.sort(key=lambda x: shift_counts[x][1])
            for emp in candidates_m[:needed_m]:
                employee_shifts[emp][day] = 1
                shift_counts[emp][1] += 1
                available_today.remove(emp)

        # Assign Night (exactly 1)
        shift_counts_day = {s: sum(1 for emp in employee_names if employee_shifts[emp][day] == s) for s in SHIFTS}
        needed_n = max(0, TARGET_SHIFTS_PER_DAY[3] - shift_counts_day.get(3, 0))
        if needed_n > 0:
            candidates_n = [emp for emp in available_today if is_shift_viable(employee_shifts, emp, day, 3, total_days)]
            candidates_n.sort(key=lambda x: shift_counts[x][3])
            for emp in candidates_n[:needed_n]:
                employee_shifts[emp][day] = 3
                shift_counts[emp][3] += 1
                available_today.remove(emp)

        # Fallback Assignment (no Off, leave as None if unassignable)
        for emp in available_today:
            assigned = False
            shift_counts_day = {s: sum(1 for e in employee_names if employee_shifts[e][day] == s) for s in SHIFTS}
            preferred_order = []
            if shift_counts_day.get(2, 0) < TARGET_SHIFTS_PER_DAY[2]:
                preferred_order.append(2)
            preferred_order.append(1)  # Always consider M
            if shift_counts_day.get(3, 0) < TARGET_SHIFTS_PER_DAY[3]:
                preferred_order.append(3)
            for shift_code in preferred_order:
                if is_shift_viable(employee_shifts, emp, day, shift_code, total_days):
                    employee_shifts[emp][day] = shift_code
                    shift_counts[emp][shift_code] += 1
                    assigned = True
                    break
            if not assigned:
                logging.warning(f"Could not assign viable shift for {emp} on day {day+1}. Leaving as None.")
    logging.info("Finished Phase 2.")

    # Phase 3: Apply 28-day Pattern
    logging.info("Starting Phase 3: Apply 28-day Pattern (Days 28+)")
    for day in range(28, total_days):
        equivalent_day_index = day % 28
        for emp in employee_names:
            if employee_shifts[emp][day] is None:
                pattern_shift = employee_shifts[emp][equivalent_day_index]
                if pattern_shift is None:
                    continue
                assigned_shift = pattern_shift
                if not is_shift_viable(employee_shifts, emp, day, assigned_shift, total_days):
                    assigned_shift = None
                    for alt_shift in [2, 1, 3]:
                        if is_shift_viable(employee_shifts, emp, day, alt_shift, total_days):
                            assigned_shift = alt_shift
                            break
                    if assigned_shift is None:
                        continue  # Leave as None instead of assigning Off
                employee_shifts[emp][day] = assigned_shift
                shift_counts[emp][assigned_shift] += 1
    logging.info("Finished Phase 3.")

    # Phase 4: Balancing Shifts
    logging.info("Starting Phase 4: Balancing Shifts")
    shift_counts = {name: {code: 0 for code in SHIFT_NAMES.keys()} for name in employee_names}
    for name in employee_names:
        for day_idx in range(total_days):
            shift = employee_shifts[name][day_idx]
            if shift is not None:
                shift_counts[name][shift] += 1

    MAX_BALANCE_ITERATIONS = 7
    for day in range(total_days):
        for iteration in range(MAX_BALANCE_ITERATIONS):
            made_change = False
            shift_assignments_day = {emp: employee_shifts[emp][day] for emp in employee_names}
            assigned_employees = {s: [emp for emp, shift in shift_assignments_day.items() if shift == s] for s in SHIFTS}
            shift_counts_day = {s: len(assigned_employees.get(s, [])) for s in SHIFTS}

            # Balance Evening (E=2 strict)
            current_e = shift_counts_day.get(2, 0)
            target_e = TARGET_SHIFTS_PER_DAY[2]
            if current_e > target_e:
                num_to_move = current_e - target_e
                candidates_e = sorted(assigned_employees.get(2, []), key=lambda x: shift_counts[x][2], reverse=True)
                moved_count = 0
                for emp in candidates_e:
                    if moved_count >= num_to_move:
                        break
                    dest_shift = 1 if is_shift_viable(employee_shifts, emp, day, 1, total_days) else None
                    if dest_shift:
                        employee_shifts[emp][day] = dest_shift
                        shift_counts[emp][2] -= 1
                        shift_counts[emp][dest_shift] += 1
                        shift_counts_day[2] -= 1
                        shift_counts_day[dest_shift] = shift_counts_day.get(dest_shift, 0) + 1
                        assigned_employees[2].remove(emp)
                        assigned_employees[dest_shift].append(emp)
                        moved_count += 1
                        made_change = True
            elif current_e < target_e:
                num_needed = target_e - current_e
                donors = []
                if shift_counts_day.get(1, 0) > TARGET_SHIFTS_PER_DAY[1]:
                    donors.extend([(e, 1) for e in assigned_employees.get(1, [])])
                donors.sort(key=lambda x: (not is_shift_viable(employee_shifts, x[0], day, 2, total_days), shift_counts[x[0]][2]))
                found = 0
                for emp, origin_shift in donors:
                    if found >= num_needed:
                        break
                    if is_shift_viable(employee_shifts, emp, day, 2, total_days):
                        employee_shifts[emp][day] = 2
                        shift_counts[emp][2] += 1
                        shift_counts[emp][origin_shift] -= 1
                        shift_counts_day[2] += 1
                        shift_counts_day[origin_shift] -= 1
                        assigned_employees[2].append(emp)
                        assigned_employees[origin_shift].remove(emp)
                        found += 1
                        made_change = True

            # Balance Night (N=1 strict)
            current_n = shift_counts_day.get(3, 0)
            target_n = TARGET_SHIFTS_PER_DAY[3]
            if current_n > target_n:
                num_to_move = current_n - target_n
                candidates_n = sorted(assigned_employees.get(3, []), key=lambda x: shift_counts[x][3], reverse=True)
                moved_count = 0
                for emp in candidates_n:
                    if moved_count >= num_to_move:
                        break
                    dest_shift = 1 if is_shift_viable(employee_shifts, emp, day, 1, total_days) else None
                    if dest_shift:
                        employee_shifts[emp][day] = dest_shift
                        shift_counts[emp][3] -= 1
                        shift_counts[emp][dest_shift] += 1
                        shift_counts_day[3] -= 1
                        shift_counts_day[dest_shift] = shift_counts_day.get(dest_shift, 0) + 1
                        assigned_employees[3].remove(emp)
                        assigned_employees[dest_shift].append(emp)
                        moved_count += 1
                        made_change = True

            if not made_change:
                break
    logging.info("Finished Phase 4.")

    # Phase 4.5: Guarantee Shift Presence
    logging.info("Starting Phase 4.5: Guarantee Shift Presence (M, E, N)")
    for day in range(total_days):
        needs_check = True
        check_iteration = 0
        max_check_iterations = 5
        while needs_check and check_iteration < max_check_iterations:
            needs_check = False
            check_iteration += 1
            shift_counts_day = {s: sum(1 for emp in employee_names if employee_shifts[emp][day] == s) for s in SHIFTS}
            assigned_working = sum(shift_counts_day.values())
            if assigned_working == 0:
                continue

            if shift_counts_day.get(2, 0) == 0:
                logging.warning(f"Phase 4.5 Fix (Day {day+1} Itr {check_iteration}): E=0. Attempting fix.")
                needs_check = True
                candidates = []
                m_workers = [e for e in employee_names if employee_shifts[e][day] == 1]
                n_workers = [e for e in employee_names if employee_shifts[e][day] == 3]
                if shift_counts_day.get(1, 0) > TARGET_SHIFTS_PER_DAY[1]:
                    candidates.extend([(e, 1) for e in m_workers])
                if shift_counts_day.get(3, 0) > TARGET_SHIFTS_PER_DAY[3]:
                    candidates.extend([(e, 3) for e in n_workers])
                if not candidates:
                    if shift_counts_day.get(1, 0) == TARGET_SHIFTS_PER_DAY[1]:
                        candidates.extend([(e, 1) for e in m_workers])
                    if shift_counts_day.get(3, 0) == TARGET_SHIFTS_PER_DAY[3]:
                        candidates.extend([(e, 3) for e in n_workers])
                moved = False
                if candidates:
                    candidates.sort(key=lambda x: (not is_shift_viable(employee_shifts, x[0], day, 2, total_days), shift_counts[x[0]][2], x[1] == 3))
                    for emp, origin in candidates:
                        if is_shift_viable(employee_shifts, emp, day, 2, total_days):
                            logging.info(f"  - Moving {emp} {SHIFT_NAMES[origin]}->E.")
                            employee_shifts[emp][day] = 2
                            shift_counts[emp][origin] -= 1
                            shift_counts[emp][2] += 1
                            moved = True
                            break
                if not moved:
                    logging.error(f"  - FAILED E fix (Day {day+1}): No viable candidate found from M/N.")
                if moved:
                    continue

            if shift_counts_day.get(1, 0) == 0:
                logging.warning(f"Phase 4.5 Fix (Day {day+1} Itr {check_iteration}): M=0. Attempting fix.")
                needs_check = True
                candidates = []
                e_workers = [e for e in employee_names if employee_shifts[e][day] == 2]
                n_workers = [e for e in employee_names if employee_shifts[e][day] == 3]
                if shift_counts_day.get(2, 0) > TARGET_SHIFTS_PER_DAY[2]:
                    candidates.extend([(e, 2) for e in e_workers])
                if shift_counts_day.get(3, 0) > TARGET_SHIFTS_PER_DAY[3]:
                    candidates.extend([(e, 3) for e in n_workers])
                if not candidates:
                    if shift_counts_day.get(2, 0) == TARGET_SHIFTS_PER_DAY[2]:
                        candidates.extend([(e, 2) for e in e_workers])
                    if shift_counts_day.get(3, 0) == TARGET_SHIFTS_PER_DAY[3]:
                        candidates.extend([(e, 3) for e in n_workers])
                moved = False
                if candidates:
                    candidates.sort(key=lambda x: (not is_shift_viable(employee_shifts, x[0], day, 1, total_days), shift_counts[x[0]][1], x[1] == 3))
                    for emp, origin in candidates:
                        if is_shift_viable(employee_shifts, emp, day, 1, total_days):
                            logging.info(f"  - Moving {emp} {SHIFT_NAMES[origin]}->M.")
                            employee_shifts[emp][day] = 1
                            shift_counts[emp][origin] -= 1
                            shift_counts[emp][1] += 1
                            moved = True
                            break
                if not moved:
                    logging.error(f"  - FAILED M fix (Day {day+1}): No viable candidate found from E/N.")
                if moved:
                    continue

            if shift_counts_day.get(3, 0) == 0:
                logging.warning(f"Phase 4.5 Fix (Day {day+1} Itr {check_iteration}): N=0. Attempting fix.")
                needs_check = True
                candidates = []
                m_workers = [e for e in employee_names if employee_shifts[e][day] == 1]
                e_workers = [e for e in employee_names if employee_shifts[e][day] == 2]
                if shift_counts_day.get(1, 0) > TARGET_SHIFTS_PER_DAY[1]:
                    candidates.extend([(e, 1) for e in m_workers])
                if shift_counts_day.get(2, 0) > TARGET_SHIFTS_PER_DAY[2]:
                    candidates.extend([(e, 2) for e in e_workers])
                if not candidates:
                    if shift_counts_day.get(1, 0) == TARGET_SHIFTS_PER_DAY[1]:
                        candidates.extend([(e, 1) for e in m_workers])
                    if shift_counts_day.get(2, 0) == TARGET_SHIFTS_PER_DAY[2]:
                        candidates.extend([(e, 2) for e in e_workers])
                moved = False
                if candidates:
                    candidates.sort(key=lambda x: (not is_shift_viable(employee_shifts, x[0], day, 3, total_days), shift_counts[x[0]][3], x[1] == 2))
                    for emp, origin in candidates:
                        if is_shift_viable(employee_shifts, emp, day, 3, total_days):
                            logging.info(f"  - Moving {emp} {SHIFT_NAMES[origin]}->N.")
                            employee_shifts[emp][day] = 3
                            shift_counts[emp][origin] -= 1
                            shift_counts[emp][3] += 1
                            moved = True
                            break
                if not moved:
                    logging.error(f"  - FAILED N fix (Day {day+1}): No viable candidate found from M/E.")
                if moved:
                    continue

        if check_iteration >= max_check_iterations:
            logging.error(f"Phase 4.5 FAILED to stabilize presence for Day {day+1} after {max_check_iterations} iterations.")
    logging.info("Finished Phase 4.5.")

    # Phase 4.6: Enforce at least one N-N block per employee
    logging.info("Starting Phase 4.6: Enforce at least one N-N block per employee")
    for emp in employee_names:
        shifts = employee_shifts[emp]
        has_nn = any(shifts[d] == 3 and shifts[d+1] == 3 for d in range(total_days - 1))
        if not has_nn:
            for day in range(total_days - 1):
                if (shifts[day] in [None, 1, 2]) and (shifts[day+1] in [None, 1, 2]):
                    if is_shift_viable(employee_shifts, emp, day, 3, total_days) and is_shift_viable(employee_shifts, emp, day+1, 3, total_days):
                        old1, old2 = shifts[day], shifts[day+1]
                        employee_shifts[emp][day] = 3
                        employee_shifts[emp][day+1] = 3
                        shift_counts[emp][old1] -= 1 if old1 is not None else 0
                        shift_counts[emp][old2] -= 1 if old2 is not None else 0
                        shift_counts[emp][3] += 2
                        logging.info(f"Enforced N-N for {emp} on days {day+1} and {day+2}")
                        break
            else:
                logging.warning(f"Could not find a viable N-N block for {emp}")

    # Phase 5: Final M-after-N Validation
    logging.info("Starting Phase 5: Final M-after-N Validation")
    for emp in employee_names:
        for day in range(1, total_days):
            prev_shift = employee_shifts[emp][day-1]
            current_shift = employee_shifts[emp][day]
            if current_shift == 1 and prev_shift == 3:
                logging.warning(f"Phase 5 Fix: M-after-N detected for {emp} on day {day+1}. Attempting fix.")
                original_shift = 1
                if is_shift_viable(employee_shifts, emp, day, 2, total_days):
                    logging.info(f"  - Swapping M -> E for {emp} on day {day+1}.")
                    employee_shifts[emp][day] = 2
                    shift_counts[emp][original_shift] -= 1
                    shift_counts[emp][2] += 1
                    shift_counts_day = {s: sum(1 for e in employee_names if employee_shifts[e][day] == s) for s in SHIFTS}
                    if shift_counts_day.get(2, 0) > TARGET_SHIFTS_PER_DAY[2]:
                        logging.warning(f"  - Swap M->E created E > {TARGET_SHIFTS_PER_DAY[2]} on day {day+1}. Attempting mitigation.")
                        if shift_counts_day.get(1, 0) < TARGET_SHIFTS_PER_DAY[1]:
                            candidates_e = [e for e in employee_names if employee_shifts[e][day] == 2 and e != emp]
                            candidates_e.sort(key=lambda x: shift_counts[x][1])
                            mitigated = False
                            for swap_emp in candidates_e:
                                if is_shift_viable(employee_shifts, swap_emp, day, 1, total_days):
                                    employee_shifts[swap_emp][day] = 1
                                    shift_counts[swap_emp][2] -= 1
                                    shift_counts[swap_emp][1] += 1
                                    logging.info(f"  - Mitigated by swapping {swap_emp} E -> M.")
                                    mitigated = True
                                    break
                            if not mitigated:
                                logging.warning(f"  - Mitigation failed: Could not swap another E -> M.")
                elif is_shift_viable(employee_shifts, emp, day, 0, total_days) and days_with_offs_count[day] == 0:
                    logging.warning(f"  - Cannot swap M->E. Swapping M -> Off for {emp} on day {day+1}.")
                    employee_shifts[emp][day] = 0
                    shift_counts[emp][original_shift] -= 1
                    shift_counts[emp][0] += 1
                    days_with_offs_count[day] = 1
                else:
                    logging.error(f"  - CRITICAL: Cannot fix M-after-N for {emp} on day {day+1}. Neither E nor Off is viable.")
    logging.info("Finished Phase 5.")

    # Phase 6: Final Pattern/Consecutive Night Correction
    logging.info("Starting Phase 6: Final Pattern/Consecutive Night Correction")
    for emp in employee_names:
        shifts = employee_shifts[emp]
        for day in range(2, total_days):
            if shifts[day-2] == 3 and shifts[day-1] == 3 and shifts[day] != 0 and shifts[day] is not None:
                logging.warning(f"Phase 6 Fix (N-N->Off Enforcement): Forcing Off for {emp} on day {day+1}. Was {SHIFT_NAMES.get(shifts[day], 'None')}.")
                orig_shift = shifts[day]
                employee_shifts[emp][day] = 0
                shifts[day] = 0
                if orig_shift in shift_counts[emp]:
                    shift_counts[emp][orig_shift] -= 1
                shift_counts[emp][0] = shift_counts[emp].get(0, 0) + 1
                days_with_offs_count[day] = 1

                shift_counts_day = {s: sum(1 for e in employee_names if employee_shifts[e][day] == s) for s in SHIFTS}
                target = TARGET_SHIFTS_PER_DAY.get(orig_shift)
                is_below_target = False
                if target is not None:
                    if orig_shift == 1:
                        is_below_target = shift_counts_day.get(1, 0) < target
                    elif orig_shift in [2, 3]:
                        is_below_target = shift_counts_day.get(orig_shift, 0) < target
                if is_below_target:
                    logging.warning(f"  - Day {day+1} count for {SHIFT_NAMES[orig_shift]} ({shift_counts_day.get(orig_shift, 0)}) now below target ({target}). Attempting replacement.")
                    candidates = [e for e in employee_names if e != emp and employee_shifts[e][day] != 0 and employee_shifts[e][day] is not None
                                  and is_shift_viable(employee_shifts, e, day, orig_shift, total_days)]
                    if candidates:
                        candidates.sort(key=lambda x: (shift_counts[x].get(orig_shift, 0), employee_shifts[x][day] != 1))
                        swap_emp = candidates[0]
                        current_shift_swap_emp = employee_shifts[swap_emp][day]
                        logging.info(f"  - Replacing by assigning {swap_emp} ({SHIFT_NAMES.get(current_shift_swap_emp, 'Off')} -> {SHIFT_NAMES[orig_shift]})")
                        employee_shifts[swap_emp][day] = orig_shift
                        if current_shift_swap_emp in shift_counts[swap_emp]:
                            shift_counts[swap_emp][current_shift_swap_emp] -= 1
                        shift_counts[swap_emp][orig_shift] = shift_counts[swap_emp].get(orig_shift, 0) + 1
                    else:
                        logging.warning(f"  - Could not find replacement candidate for {SHIFT_NAMES[orig_shift]}.")

        for day in range(3, total_days):
            if shifts[day] == 1:
                pattern_nem = day >= 2 and shifts[day-2:day] == [3, 2]
                pattern_nee = shifts[day-3:day] == [3, 2, 2]
                pattern_nene = day >= 4 and shifts[day-4:day] == [3, 2, 3, 2]
                pattern_enee = day >= 4 and shifts[day-4:day] == [2, 3, 2, 2]
                if pattern_nem:
                    logging.error(f"Phase 6 ERROR: N-E-M pattern detected for {emp} on day {day+1}. is_shift_viable failed? Forcing M->Off.")
                    force_off = True
                elif pattern_nee or pattern_nene or pattern_enee:
                    logging.warning(f"Phase 6 Fix (Pattern Violation): Forbidden pattern before M for {emp} on day {day+1}. Forcing M->Off.")
                    force_off = True
                else:
                    force_off = False
                if force_off:
                    employee_shifts[emp][day] = 0
                    shifts[day] = 0
                    shift_counts[emp][1] -= 1
                    shift_counts[emp][0] = shift_counts[emp].get(0, 0) + 1
                    days_with_offs_count[day] = 1

                    shift_counts_day = {s: sum(1 for e in employee_names if employee_shifts[e][day] == s) for s in SHIFTS}
                    if shift_counts_day.get(1, 0) < TARGET_SHIFTS_PER_DAY[1]:
                        logging.warning(f"  - Day {day+1} M count ({shift_counts_day.get(1, 0)}) now below target (>=2). Attempting replacement.")
                        candidates = [e for e in employee_names if e != emp and employee_shifts[e][day] in [2, 3] and is_shift_viable(employee_shifts, e, day, 1, total_days)]
                        if candidates:
                            candidates.sort(key=lambda x: (shift_counts[x].get(1, 0), employee_shifts[x][day] == 3))
                            swap_emp = candidates[0]
                            orig_shift_swap = employee_shifts[swap_emp][day]
                            logging.info(f"  - Replacing M by assigning {swap_emp} ({SHIFT_NAMES[orig_shift_swap]} -> M)")
                            employee_shifts[swap_emp][day] = 1
                            if orig_shift_swap in shift_counts[swap_emp]:
                                shift_counts[swap_emp][orig_shift_swap] -= 1
                            shift_counts[swap_emp][1] = shift_counts[swap_emp].get(1, 0) + 1
                        else:
                            logging.warning(f"  - Could not find replacement candidate for M on day {day+1}.")
    logging.info("Finished Phase 6.")

    # Final Check
    logging.info("Starting Final Balance and Presence Check.")
    final_errors = 0
    final_warnings = 0
    for day in range(total_days):
        counts = {s: sum(1 for n in employee_names if employee_shifts[n][day] == s) for s in SHIFTS}
        m, e, n = counts.get(1, 0), counts.get(2, 0), counts.get(3, 0)
        o = sum(1 for name in employee_names if employee_shifts[name][day] == 0)
        none_count = sum(1 for name in employee_names if employee_shifts[name][day] is None)
        working = m + e + n

        day_str = f"Day {day+1}"

        if none_count > 0:
            logging.error(f"{day_str} FINAL UNASSIGNED ERROR: {none_count} employees have None assignment.")
            final_errors += none_count

        if working > 0:
            target_met = (n == TARGET_SHIFTS_PER_DAY[3] and
                e == TARGET_SHIFTS_PER_DAY[2] and
                m >= TARGET_SHIFTS_PER_DAY[1])
            
            presence_met = (m > 0 and e > 0 and n > 0)
            if not presence_met:
                logging.error(f"{day_str} FINAL PRESENCE FAILED: M={m}, E={e}, N={n}. At least one required shift is missing.")
                final_errors += 1
            elif not target_met:
                logging.warning(f"{day_str} FINAL BALANCE WARNING: M={m}, E={e}, N={n}. (Expected N={TARGET_SHIFTS_PER_DAY[3]}, E={TARGET_SHIFTS_PER_DAY[2]}, M>={TARGET_SHIFTS_PER_DAY[1]}).")
                final_warnings += 1

        if o != 1:
            logging.error(f"{day_str} FINAL OFF ERROR: Found {o} employees Off (Exactly 1 required).")
            final_errors += 1

    if final_errors > 0:
        logging.error(f"Shift Generation Completed with {final_errors} CRITICAL ERRORS.")
    elif final_warnings > 0:
        logging.warning(f"Shift Generation Completed with {final_warnings} balance warnings.")
    else:
        logging.info("Shift Generation Completed. Final checks passed.")

    return employee_shifts


# ---------------------------------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------------------------------
@shift_router.post("/assign_shifts/", tags=["Automation"])
async def assign_shifts(
    year: Optional[int] = None, 
    month: Optional[int] = None, 
    force: bool = False,  # New parameter to force regeneration
    session: Session = Depends(get_session)
):
    """Generates and assigns shifts with N=1, E=2(strict), M>=2 targets and presence guarantee for annotation team and intern employees only."""
    now = datetime.now()
    # Use provided year/month or default to current
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month

    # Validate year and month
    try:
        total_days = calendar.monthrange(target_year, target_month)[1]
    except calendar.IllegalMonthError:
        raise HTTPException(status_code=400, detail="Invalid month or year")

    # Optional: Prevent generating shifts for past months or too far in the future
    current_year, current_month = now.year, now.month
    if (target_year < current_year) or (target_year == current_year and target_month < current_month):
        raise HTTPException(status_code=400, detail="Cannot generate shifts for past months")
    if target_year > current_year + 1:
        raise HTTPException(status_code=400, detail="Cannot generate shifts more than one year in the future")

    # Check if shifts already exist for this month
    start_date = datetime(target_year, target_month, 1)
    end_date_exclusive = (start_date + timedelta(days=total_days)).date()
    start_date_db = start_date.date()
    
    existing_count = session.exec(
        select(func.count(ShiftAssignment.id)).where(
            ShiftAssignment.shift_date >= start_date_db,
            ShiftAssignment.shift_date < end_date_exclusive
        )
    ).one()
    
    # If shifts exist and force=False, return a warning
    if existing_count > 0 and not force:
        month_name = start_date.strftime('%B %Y')
        return JSONResponse(
            status_code=409,  # Conflict status code
            content={
                "warning": f"Shifts already exist for {month_name}. {existing_count} assignments will be deleted and regenerated.",
                "message": "Please Wait for a moment Generating Schedule.",
                "month": month_name,
                "existing_assignments": existing_count
            }
        )

    # *** FILTER EMPLOYEES BY ROLE - Only annotation_team and intern ***
    employee_list = session.exec(
        select(Employee)
        .where(Employee.role.in_([EmployeeRole.ANNOTATION_TEAM, EmployeeRole.INTERN]))
        .order_by(Employee.name)
    ).all()
    
    min_required = TARGET_SHIFTS_PER_DAY[1] + TARGET_SHIFTS_PER_DAY[2] + TARGET_SHIFTS_PER_DAY[3] + 1
    if len(employee_list) < min_required:
        raise HTTPException(
            status_code=400, 
            detail=f"At least {min_required} annotation team and intern employees required (for M>=2, E=2, N=1 + Off coverage), found {len(employee_list)}"
        )

    employee_names = [emp.name for emp in employee_list]
    employee_id_map = {emp.name: emp.id for emp in employee_list}

    try:
        logging.info(f"Generating shifts for {len(employee_names)} annotation team and intern employees for {total_days} days ({target_year}-{target_month:02d})...")
        # Call the core generation function
        employee_shifts = generate_optimized_shifts(employee_names, total_days)
        logging.info("Shift generation logic completed.")

        # --- Clear & Store Assignments ---
        logging.info(f"Deleting existing assignments between {start_date_db} and {end_date_exclusive - timedelta(days=1)}")

        # Efficient delete using SQLModel/SQLAlchemy query execution
        try:
            delete_stmt = ShiftAssignment.__table__.delete().where(
                ShiftAssignment.shift_date >= start_date_db,
                ShiftAssignment.shift_date < end_date_exclusive
            )
            result = session.execute(delete_stmt)
            num_deleted = result.rowcount
            session.commit()
            if num_deleted > 0:
                logging.info(f"Deleted {num_deleted} existing assignments for {target_year}-{target_month:02d}.")
            else:
                logging.info(f"No existing assignments found for {target_year}-{target_month:02d} to delete.")
        except Exception as del_exc:
            session.rollback()
            logging.error(f"Error deleting existing shifts, attempting fetch-and-delete fallback: {del_exc}")
            # Fallback to fetch then delete
            existing_assignments = session.exec(select(ShiftAssignment).where(
                ShiftAssignment.shift_date >= start_date_db,
                ShiftAssignment.shift_date < end_date_exclusive
            )).all()
            num_deleted = len(existing_assignments)
            for assignment in existing_assignments:
                session.delete(assignment)
            if num_deleted > 0:
                session.commit()
                logging.info(f"Deleted {num_deleted} existing assignments (fallback method).")
            else:
                logging.info("No existing assignments found for the month to delete (fallback method).")

        logging.info("Storing newly generated assignments...")
        added_count = 0
        assignments_to_add = []
        for name, shifts in employee_shifts.items():
            emp_id = employee_id_map.get(name)
            if not emp_id:
                logging.warning(f"Skipping assignments for '{name}': ID not found.")
                continue
            for day_idx, shift_code in enumerate(shifts):
                if shift_code is not None:
                    current_date = (start_date + timedelta(days=day_idx)).date()
                    day_number = day_idx + 1
                    assignment = ShiftAssignment(
                        employee_id=emp_id,
                        day=day_number,
                        shift=shift_code,
                        shift_date=current_date
                    )
                    assignments_to_add.append(assignment)

        # Bulk add
        session.add_all(assignments_to_add)
        added_count = len(assignments_to_add)

        session.commit()
        logging.info(f"Successfully added {added_count} new shift assignments.")
        return {
            "message": f"Shifts successfully generated and assigned for annotation team and intern employees in {start_date.strftime('%B %Y')}. Added {added_count} assignments."
        }

    except ValueError as ve:
        session.rollback()
        logging.error(f"Value Error during generation: {ve}")
        raise HTTPException(status_code=400, detail=f"Failed generation: {ve}")
    except Exception as e:
        session.rollback()
        logging.exception("Unexpected error during assignment process.")
        raise HTTPException(status_code=500, detail=f"Unexpected error during assignment: {e}")

@shift_router.get("/shift_pairing/", tags=["Automation"])
def get_shift_pairing(year: Optional[int] = None, month: Optional[int] = None, session: Session = Depends(get_session)):
    """ Retrieves shift pairings based on stored data. Reflects N=1, E=2, M>=2 targets. """
    try:
        # Default to current year and month if not provided
        now = datetime.now()
        target_year = year if year is not None else now.year
        target_month = month if month is not None else now.month

        # Validate year and month
        if target_year < 2000 or target_year > 2100:
            raise HTTPException(status_code=400, detail="Year must be between 2000 and 2100")
        if target_month < 1 or target_month > 12:
            raise HTTPException(status_code=400, detail="Month must be between 1 and 12")

        # Prevent past months (same validation as /assign_shifts/)
        current_year, current_month = now.year, now.month
        if target_year < current_year or (target_year == current_year and target_month < current_month):
            raise HTTPException(status_code=400, detail="Cannot retrieve pairings for past months")

        # Log the parameters for debugging
        logging.info(f"Fetching shift pairings for {target_year}-{target_month:02d}")

        # Calculate date range
        total_days = calendar.monthrange(target_year, target_month)[1]
        start_date = datetime(target_year, target_month, 1)
        end_date_exclusive = start_date + timedelta(days=total_days)

        # Fetch assignments with employee data eagerly
        stmt = select(ShiftAssignment, Employee).join(Employee).where(
            ShiftAssignment.shift_date >= start_date.date(),
            ShiftAssignment.shift_date < end_date_exclusive.date()
        ).order_by(ShiftAssignment.shift_date, Employee.name)
        results = session.exec(stmt).all()

        # Initialize structure to hold shifts per employee per day
        employee_shifts_by_date: Dict[date, Dict[int, List[str]]] = {
            (start_date + timedelta(days=d)).date(): {s: [] for s in SHIFTS}
            for d in range(total_days)
        }

        # Populate the structure
        for assignment, employee in results:
            shift_date = assignment.shift_date
            shift_code = assignment.shift
            if shift_date in employee_shifts_by_date and shift_code in employee_shifts_by_date[shift_date]:
                employee_shifts_by_date[shift_date][shift_code].append(employee.name)

        # Generate pairings day by day
        shift_pairs_report = {}
        for day_idx in range(total_days):
            current_date = (start_date + timedelta(days=day_idx)).date()
            day_pairings_output: Dict[str, List[Tuple[str, Optional[str]]]] = {}
            shift_groups = employee_shifts_by_date.get(current_date, {})

            for shift_code in SHIFTS:
                shift_name = SHIFT_NAMES.get(shift_code)
                if not shift_name:
                    continue

                employees = shift_groups.get(shift_code, [])
                if not employees:
                    continue

                random.shuffle(employees)
                pairs = []
                target = TARGET_SHIFTS_PER_DAY.get(shift_code)
                actual_count = len(employees)

                # Log warnings for deviations from target
                if shift_code in [2, 3] and actual_count != target:
                    logging.warning(f"[Pairing] Day {day_idx+1} ({current_date}) {shift_name}: Expected {target}, Found {actual_count} -> {employees}")
                elif shift_code == 1 and actual_count < target:
                    logging.warning(f"[Pairing] Day {day_idx+1} ({current_date}) {shift_name}: Expected >={target}, Found {actual_count} -> {employees}")

                # Generate pairs
                idx = 0
                while idx < actual_count:
                    emp1 = employees[idx]
                    emp2 = employees[idx+1] if idx+1 < actual_count else None
                    
                    if shift_code == 3:  # Night shift (target = 2)
                        if idx == 0:  # Only show the first pair, ignore extras
                            pairs.append((emp1, emp2))
                        break  # Don't process any more employees for night shift
                    elif shift_code == 2:  # Evening shift (target = 2)
                        if idx == 0:  # Only show the first pair, ignore extras
                            if emp2 is None:
                                pairs.append((emp1, "MISSING PARTNER (Check Logs)"))
                            else:
                                pairs.append((emp1, emp2))
                        break  # Don't process any more employees for evening shift
                    elif shift_code == 1:  # Morning shift (target >= 2)
                        pairs.append((emp1, emp2))
                        idx += 2
                if pairs:
                    day_pairings_output[shift_name] = pairs

            shift_pairs_report[day_idx + 1] = {
                "date": current_date.strftime("%Y-%m-%d"),
                "day_name": current_date.strftime("%A"),
                "pairings": day_pairings_output
            }

        return shift_pairs_report

    except calendar.IllegalMonthError:
        raise HTTPException(status_code=400, detail="Invalid month")
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error retrieving pairings")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve pairings: {e}")


@shift_router.post("/adjust_shift/", tags=["Automation"])
async def adjust_shift(
    employee_id: UUID, 
    days: list[int], 
    new_shifts: list[int], 
    year: Optional[int] = None, 
    month: Optional[int] = None, 
    session: Session = Depends(get_session)
):
    """ Manually adjust/create shift with validation. """
    
    action = "unchanged"
    last_assignment = None
    employee = session.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    current_year = year if year else datetime.now().year
    current_month = month if month else datetime.now().month
    
    for i, day in enumerate(days):
        try:
            shift_date = datetime(current_year, current_month, day).date()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid day {day}")

        if new_shifts[i] not in SHIFT_NAMES:
            raise HTTPException(status_code=400, detail=f"Invalid shift code")

        prev_date = shift_date - timedelta(1)
        prev_assign = session.exec(select(ShiftAssignment).where(
            ShiftAssignment.employee_id == employee_id,
            ShiftAssignment.shift_date == prev_date
        )).first()
        prev_shift = prev_assign.shift if prev_assign else None
        
        # if new_shifts[i] == 1 and prev_shift == 3:
        #     raise HTTPException(status_code=400, detail="Adjustment failed: M-after-N.")
        # if new_shifts[i] == 3 and prev_shift == 3:
        #     raise HTTPException(status_code=400, detail="Adjustment failed: N-after-N.")

        assignment = session.exec(select(ShiftAssignment).where(
            ShiftAssignment.employee_id == employee_id,
            ShiftAssignment.shift_date == shift_date
        )).first()
        
        if not assignment:
            assignment = ShiftAssignment(
                employee_id=employee_id,
                day=day,
                shift=new_shifts[i],
                shift_date=shift_date
            )
            session.add(assignment)
            action = "created"
            logging.info(f"Creating shift for {employee.name} on {shift_date}: {SHIFT_NAMES[new_shifts[i]]}")
        elif assignment.shift != new_shifts[i]:
            logging.info(f"Adjusting shift for {employee.name} on {shift_date} from {SHIFT_NAMES[assignment.shift]} to {SHIFT_NAMES[new_shifts[i]]}")
            assignment.shift = new_shifts[i]
            if action == "unchanged":
                action = "adjusted"
        
        # Check for imbalance
        assignments_day = session.exec(select(ShiftAssignment).where(ShiftAssignment.shift_date == shift_date)).all()
        counts = {s: 0 for s in SHIFTS}
        current_assign = {a.employee_id: a.shift for a in assignments_day}
        current_assign[employee_id] = new_shifts[i]
        
        for _, sc in current_assign.items():
            if sc in counts:
                counts[sc] += 1
                
        n_ok = counts[3] == 1
        e_ok = counts[2] == 2
        m_ok = counts.get(1, 0) >= 2
        
        # if not (n_ok and e_ok and m_ok):
        #     logging.warning(f"Manual '{action}' on {shift_date} resulted in imbalance: M={counts.get(1, 0)}, E={counts[2]}, N={counts[3]}")
        
        last_assignment = assignment
        
    if action != "unchanged":
        session.commit()
        if last_assignment:
            session.refresh(last_assignment)

    return {
        "message": f"Shift {action} successfully for {employee.name}",
        "assignment": ShiftAssignmentRead.model_validate(last_assignment.model_dump()) if last_assignment else None
    }


@shift_router.post("/swap_shifts/", tags=["Automation"])
async def swap_shifts( employee1_id: UUID, employee2_id: UUID, day: int, year: Optional[int] = None, month: Optional[int] = None, session: Session = Depends(get_session) ):
    """ Swap shifts between two employees with validation. """
    current_year=year if year else datetime.now().year; current_month=month if month else datetime.now().month
    try: shift_date = datetime(current_year, current_month, day).date()
    except ValueError: raise HTTPException(status_code=400, detail=f"Invalid day {day}")
    if employee1_id == employee2_id: raise HTTPException(status_code=400, detail="Cannot swap same employee.")

    emp1 = session.get(Employee, employee1_id); emp2 = session.get(Employee, employee2_id)
    if not emp1 or not emp2: raise HTTPException(status_code=404, detail="Employee(s) not found")

    assign_list = session.exec(select(ShiftAssignment).where( ShiftAssignment.shift_date == shift_date, ShiftAssignment.employee_id.in_([employee1_id, employee2_id]) )).all()
    a1 = next((a for a in assign_list if a.employee_id == employee1_id), None); a2 = next((a for a in assign_list if a.employee_id == employee2_id), None)
    s1 = a1.shift if a1 else 0; s2 = a2.shift if a2 else 0 # Default to Off (0) if no assignment
    if s1 == s2: raise HTTPException(status_code=400, detail=f"Both have same shift ({SHIFT_NAMES.get(s1)})")

    logging.info(f"Attempt swap on {shift_date}: {emp1.name}({SHIFT_NAMES.get(s1)}) <=> {emp2.name}({SHIFT_NAMES.get(s2)})")
    prev_date = shift_date - timedelta(days=1)
    prev_assign = session.exec(select(ShiftAssignment).where( ShiftAssignment.shift_date == prev_date, ShiftAssignment.employee_id.in_([employee1_id, employee2_id]) )).all()
    prev_s={a.employee_id: a.shift for a in prev_assign}; prev_s1=prev_s.get(employee1_id); prev_s2=prev_s.get(employee2_id)

    # Validate swap constraints
    if s2 == 1 and prev_s1 == 3: raise HTTPException(status_code=400, detail=f"Swap failed: M-after-N for {emp1.name}")
    if s1 == 1 and prev_s2 == 3: raise HTTPException(status_code=400, detail=f"Swap failed: M-after-N for {emp2.name}")
    if s2 == 3 and prev_s1 == 3: raise HTTPException(status_code=400, detail=f"Swap failed: N-after-N for {emp1.name}")
    if s1 == 3 and prev_s2 == 3: raise HTTPException(status_code=400, detail=f"Swap failed: N-after-N for {emp2.name}")

    # Perform swap (handle creation/deletion for Off days)
    if s2 == 0: # E1 gets Off
        if a1: session.delete(a1)
    else: # E1 gets s2
        if a1: a1.shift = s2
        else: a1 = ShiftAssignment(employee_id=employee1_id, day=day, shift=s2, shift_date=shift_date); session.add(a1)
    if s1 == 0: # E2 gets Off
        if a2: session.delete(a2)
    else: # E2 gets s1
        if a2: a2.shift = s1
        else: a2 = ShiftAssignment(employee_id=employee2_id, day=day, shift=s1, shift_date=shift_date); session.add(a2)

    session.commit(); logging.info(f"Swap successful on {shift_date}")
    return { "message": f"Shifts swapped successfully for {emp1.name} and {emp2.name} on {shift_date}", "new_shifts": { emp1.name: SHIFT_NAMES.get(s2, "Off"), emp2.name: SHIFT_NAMES.get(s1, "Off") } }


@shift_router.get("/employee_schedule/{employee_id}", tags=["Reports"])
def get_employee_schedule( employee_id: UUID, year: Optional[int] = None, month: Optional[int] = None, session: Session = Depends(get_session) ):
    """ Get the monthly schedule for a specific employee. Defaults Off if no assignment. """
    current_year=year if year else datetime.now().year
    current_month=month if month else datetime.now().month

    employee = session.get(Employee, employee_id)
    if not employee: raise HTTPException(status_code=404, detail="Employee not found")

    try:
        start_date = datetime(current_year, current_month, 1).date()
        num_days = calendar.monthrange(current_year, current_month)[1]
        end_date = start_date + timedelta(days=num_days - 1) # Inclusive end date
    except ValueError: raise HTTPException(status_code=400, detail="Invalid year or month combination")
    except calendar.IllegalMonthError: raise HTTPException(status_code=400, detail="Invalid month")

    # Fetch assignments for the month
    stmt = select(ShiftAssignment).where(
        ShiftAssignment.employee_id == employee_id,
        ShiftAssignment.shift_date >= start_date,
        ShiftAssignment.shift_date <= end_date
    ).order_by(ShiftAssignment.shift_date)
    assignments = session.exec(stmt).all()
    assign_map = {a.shift_date: a for a in assignments}

    schedule = []
    stats = {code: 0 for code in SHIFT_NAMES.keys()}
    weekday_offs = {} # Track count of offs per weekday {0: Mon, 1: Tue, ...}

    for day_num in range(num_days):
        current_date = start_date + timedelta(days=day_num)
        assignment = assign_map.get(current_date)
        shift_code = assignment.shift if assignment else 0 # Default to Off
        shift_name = SHIFT_NAMES.get(shift_code, "Unknown")

        schedule.append({
            "day": day_num + 1,
            "date": current_date.strftime("%Y-%m-%d"),
            "weekday": current_date.strftime("%A"),
            "shift_code": shift_code,
            "shift_name": shift_name
        })

        # Update stats
        if shift_code in stats: stats[shift_code] += 1
        if shift_code == 0:
            weekday = current_date.weekday()
            weekday_offs[weekday] = weekday_offs.get(weekday, 0) + 1

    # Determine if off days fall on varied weekdays
    varied_weekoffs = True # Default to True if 0 or 1 off days
    if stats.get(0, 0) > 1: # Only check variety if more than one off day
        varied_weekoffs = len(weekday_offs) > 1

    return {
        "employee_id": employee.id,
        "employee_name": employee.name,
        "month": f"{current_year}-{current_month:02d}",
        "schedule": schedule,
        "statistics": {SHIFT_NAMES[k]: v for k,v in stats.items() if k in SHIFT_NAMES},
        "varied_weekoffs": varied_weekoffs
    }