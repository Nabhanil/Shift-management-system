import random # Although not strictly needed for *these* names, good practice if you wanted truly random generated names
import math

# --- Configuration ---
DAYS_PER_WEEK = 7
SHIFTS_PER_DAY = 3
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHIFT_NAMES = ["Morning (Shift 1)", "Afternoon (Shift 2)", "Night (Shift 3)"] # Example names, adjust if needed

# --- Data (Predefined Employees) ---
# List of 7 employee names - this replaces the input
PREDEFINED_EMPLOYEES = [
    "Alice",
    "Bob",
    "Charlie",
    "David",
    "Eve",
    "Frank",
    "Grace"
]

# --- Core Logic ---

def get_employees():
    """Returns the predefined list of employee names."""
    # We are skipping user input as requested
    print("Using predefined employee list:")
    for emp in PREDEFINED_EMPLOYEES:
        print(f"- {emp}")
    print("-" * 20) # Separator
    return PREDEFINED_EMPLOYEES

def assign_days_off(employees):
    """Assigns a unique day off to each employee in a rotating fashion."""
    num_employees = len(employees)
    if num_employees == 0:
        return {}

    employee_day_off = {}
    # Assign days off cyclically (Emp0 off on Day0, Emp1 off on Day1, ...)
    # The days off will cycle every 7 employees
    for i, employee in enumerate(employees):
        day_off_index = i % DAYS_PER_WEEK
        employee_day_off[employee] = day_off_index
    return employee_day_off

def generate_schedule(employees, employee_day_off):
    """Generates the weekly shift schedule."""
    num_employees = len(employees)
    # Check if enough employees to cover all shifts daily with days off
    if num_employees < (DAYS_PER_WEEK + SHIFTS_PER_DAY - 1): # A rough heuristic, 4 is the minimum for *some* coverage
         # A more precise check for 3 shifts/day, 1 day off per week requires at least 4 employees to guarantee coverage without repeats on a single day
         if num_employees < 4:
             print("\nWARNING: With less than 4 employees, it's impossible to cover all 3 shifts daily while giving everyone a day off.")
             print("The schedule generated will likely have 'UNASSIGNED' slots or require manual adjustment.")
         elif num_employees < DAYS_PER_WEEK: # If less than 7 employees, some days off will be repeated among staff
              print(f"\nINFO: With {num_employees} employees, some days off will be assigned to more than one person.")


    weekly_schedule = [[None for _ in range(SHIFTS_PER_DAY)] for _ in range(DAYS_PER_WEEK)]
    employee_shift_counts = {emp: 0 for emp in employees}
    employee_shift_type_counts = {emp: [0] * SHIFTS_PER_DAY for emp in employees} # [Morning, Afternoon, Night] counts

    current_employee_idx = 0 # Index to cycle through employees

    # Store who is assigned to each shift today to avoid assigning the same person multiple times *on the same day*
    # This is a simple way to add a basic constraint.
    assigned_today = set()

    for day_index in range(DAYS_PER_WEEK):
        assigned_today.clear() # Reset for the new day

        # Find the list of employees available today *before* assigning shifts
        available_employees_today = [
            emp for emp in employees if employee_day_off[emp] != day_index
        ]

        if len(available_employees_today) < SHIFTS_PER_DAY:
             print(f"Warning: Not enough staff available on {DAYS_OF_WEEK[day_index]} ({len(available_employees_today)} available, need {SHIFTS_PER_DAY}). Shifts for this day might be UNASSIGNED or require manual filling.")

        for shift_index in range(SHIFTS_PER_DAY):
            assigned = False
            # Limit attempts to prevent infinite loops if logic breaks, e.g., no available staff
            attempts = 0
            max_attempts = num_employees * 3 # Try cycling through employees a few times

            while attempts < max_attempts:
                # Get the potential candidate employee based on the global rotation index
                candidate_emp = employees[current_employee_idx % num_employees]

                # Check if the candidate is available today AND hasn't been assigned a shift yet today
                if employee_day_off[candidate_emp] != day_index and candidate_emp not in assigned_today:
                    # Found an available and eligible employee
                    weekly_schedule[day_index][shift_index] = candidate_emp
                    employee_shift_counts[candidate_emp] += 1
                    employee_shift_type_counts[candidate_emp][shift_index] += 1
                    assigned_today.add(candidate_emp) # Mark as assigned for today
                    current_employee_idx += 1 # Move to the next employee for the *next* slot anywhere in the week
                    assigned = True
                    break # Exit the while loop for this shift

                else:
                    # Candidate employee is either off today or already assigned today.
                    # Try the next employee in the overall rotation.
                    current_employee_idx += 1
                    attempts += 1 # Count this attempt

            if not assigned:
                 # This occurs if no available employee could be found after several cycles.
                 # With >= 4 employees, this *shouldn't* happen unless the no-repeat-on-same-day
                 # constraint makes it impossible (e.g., only 3 employees, all available).
                 weekly_schedule[day_index][shift_index] = "UNASSIGNED" # Mark as unassigned


    return weekly_schedule, employee_shift_counts, employee_shift_type_counts

# --- Display Functions ---

def display_schedule(weekly_schedule, employees, employee_day_off, employee_shift_counts, employee_shift_type_counts):
    """Prints the schedule and summary."""
    num_employees = len(employees)

    print("\n--- Weekly Shift Schedule ---")

    # Print Days Off
    print("\nAssigned Days Off:")
    # Sort employees by day off for cleaner output
    sorted_employees_by_day_off = sorted(employees, key=lambda emp: employee_day_off[emp])
    for employee in sorted_employees_by_day_off:
        day_index = employee_day_off[employee]
        print(f"- {employee}: {DAYS_OF_WEEK[day_index]}")

    # Print Schedule Table
    print("\nSchedule:")
    # Header row
    header = ["Day"] + SHIFT_NAMES
    # Calculate column widths based on potential employee name length
    day_col_width = 10
    shift_col_width = 18 # Allow a bit more space for names

    print(f"{header[0]:<{day_col_width}}", end="") # Day column header
    for shift_name in header[1:]:
        print(f"| {shift_name:<{shift_col_width}}", end="") # Shift columns header
    print("\n" + "-" * (day_col_width + (shift_col_width + 3) * SHIFTS_PER_DAY + 1)) # Separator line

    # Rows for each day
    for day_index, day_schedule in enumerate(weekly_schedule):
        print(f"{DAYS_OF_WEEK[day_index]:<{day_col_width}}", end="")
        for shift_index, employee in enumerate(day_schedule):
             emp_name = employee if employee else "---" # Use "---" for None/UNASSIGNED
             print(f"| {emp_name:<{shift_col_width}}", end="")
        print() # Newline after each day

    # Print Fairness Summary
    print("\n--- Shift Distribution Summary ---")
    # Calculate average shifts per employee
    total_shifts = DAYS_PER_WEEK * SHIFTS_PER_DAY
    avg_shifts = total_shifts / num_employees if num_employees > 0 else 0
    print(f"Total shifts to cover per week: {total_shifts}")
    print(f"Number of employees: {num_employees}")
    print(f"Target average shifts per employee: {avg_shifts:.2f}") # Expected if perfectly balanced

    print("\nEmployee Shift Counts:")
    # Header for summary
    summary_header = ["Employee", "Total Shifts"] + SHIFT_NAMES
    # Calculate column widths for summary based on longest name/header
    emp_summary_width = max(len(emp) for emp in employees + [summary_header[0]])
    total_shifts_width = max(len(str(total_shifts)), len(summary_header[1]))
    shift_type_width = max(len(header) for header in SHIFT_NAMES)

    print(f"{summary_header[0]:<{emp_summary_width}} | {summary_header[1]:<{total_shifts_width}} | {summary_header[2]:<{shift_type_width}} | {summary_header[3]:<{shift_type_width}} | {summary_header[4]:<{shift_type_width}}")
    print("-" * (emp_summary_width + 3 + total_shifts_width + 3 + shift_type_width + 3 + shift_type_width + 3 + shift_type_width)) # Separator

    # Data rows for each employee
    # Sort employees alphabetically for consistent summary output
    sorted_employees = sorted(employees)
    for employee in sorted_employees:
        total = employee_shift_counts.get(employee, 0) # Use .get() in case an employee somehow didn't get counted
        shift_types = employee_shift_type_counts.get(employee, [0] * SHIFTS_PER_DAY)
        print(f"{employee:<{emp_summary_width}} | {total:<{total_shifts_width}} | {shift_types[0]:<{shift_type_width}} | {shift_types[1]:<{shift_type_width}} | {shift_types[2]:<{shift_type_width}}")

    print("-" * (emp_summary_width + 3 + total_shifts_width + 3 + shift_type_width + 3 + shift_type_width + 3 + shift_type_width)) # Separator


# --- Main Execution ---

if __name__ == "__main__":
    # Directly call get_employees which now returns the predefined list
    team_employees = get_employees()

    if not team_employees:
        print("No employees available in the predefined list. Exiting.")
    else:
        employee_days_off = assign_days_off(team_employees)
        weekly_schedule, shift_counts, shift_type_counts = generate_schedule(team_employees, employee_days_off)
        display_schedule(weekly_schedule, team_employees, employee_days_off, shift_counts, shift_type_counts)