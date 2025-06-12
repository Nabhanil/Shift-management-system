from datetime import datetime, timedelta
import calendar

# Base Data
employee_names = [
    "Simanti Das", "Mampi Deb", "Suman Saha", "Amit Debnath",
    "Bipul Nath", "Hritika Dey", "Riya Barman"
]

base_pattern = [
    ['O', 'M', 'M', 'E', 'E', 'N', 'N'],
    ['N', 'O', 'M', 'M', 'E', 'E', 'N'],
    ['N', 'N', 'O', 'M', 'M', 'E', 'E'],
    ['E', 'N', 'N', 'O', 'M', 'M', 'E'],
    ['E', 'E', 'N', 'N', 'O', 'M', 'M'],
    ['M', 'E', 'E', 'N', 'N', 'O', 'M'],
    ['M', 'M', 'E', 'E', 'N', 'N', 'O']
]

shift_mapping = {'M': 1, 'E': 2, 'N': 3, 'O': 0}
numerical_base = [
    [shift_mapping[shift] for shift in row] for row in base_pattern
]

now = datetime.now()
year = now.year
month = now.month
total_days = calendar.monthrange(year, month)[1]

def generate_scalable_shifts(n_employees, total_days):
    employee_shifts = {}

    for i in range(n_employees):
        base_emp_idx = i % 7
        weekly_pattern = numerical_base[base_emp_idx]

        full_month_pattern = []
        num_weeks = (total_days + 6) // 7  # Round up
        consecutive_nights = 0  # Track consecutive night shifts

        for week in range(num_weeks):
            rotated_week = weekly_pattern[week % 7:] + weekly_pattern[:week % 7]
            for d in range(7):
                day_index = week * 7 + d
                if day_index >= total_days:
                    break
                shift_for_day = rotated_week[d]

                if len(full_month_pattern) > 0 and full_month_pattern[-1] == 3 and shift_for_day == 1:
                    shift_for_day = 2  # Change Morning (1) to Evening (2) if the previous shift was Night (3)

                # After two consecutive Night shifts, the next shift is Off (O)
                if consecutive_nights == 2:
                    shift_for_day = 0  # Set to Off (O) after two consecutive Night shifts
                    consecutive_nights = 0  

                
                if shift_for_day == 3:
                    consecutive_nights += 1
                else:
                    consecutive_nights = 0  

                full_month_pattern.append(shift_for_day)

        name = employee_names[i] if i < len(employee_names) else f"Employee {i+1}"
        employee_shifts[name] = full_month_pattern

    for day in range(total_days):
        m = e = n = 0
        for emp in employee_shifts:
            shift = employee_shifts[emp][day]
            if shift == 1: m += 1
            elif shift == 2: e += 1
            elif shift == 3: n += 1
        assert m >= 1, f"Day {day+1} missing Morning shift"
        assert e >= 1, f"Day {day+1} missing Evening shift"
        assert n >= 1, f"Day {day+1} missing Night shift"

    return employee_shifts


def generate_shift_pairs(employee_shifts, total_days):
    shift_names = {1: 'Morning', 2: 'Evening', 3: 'Night'}
    shift_pairs_by_day = {}

    for day in range(total_days):
        shift_groups = {1: [], 2: [], 3: []}
        for emp_name, schedule in employee_shifts.items():
            shift = schedule[day]
            if shift in shift_groups:
                shift_groups[shift].append(emp_name)
        
        day_pairing = {}
        for shift_code, employees in shift_groups.items():
            pairs = [tuple(employees[i:i+2]) for i in range(0, len(employees), 2)]
            if len(employees) % 2 != 0:
                pairs[-1] = (pairs[-1][0], None)
            day_pairing[shift_names[shift_code]] = pairs

        shift_pairs_by_day[day + 1] = day_pairing
    
    return shift_pairs_by_day


shifts = generate_scalable_shifts(len(employee_names), total_days)
shift_pairs = generate_shift_pairs(shifts, total_days)

print(f"\n📅 Shift Pairing for {calendar.month_name[month]} {year} ({total_days} days)")
print("-" * 50)

# Start date for the month
start_date = datetime(year, month, 1)

for day, shifts_for_day in shift_pairs.items():
    current_date = start_date + timedelta(days=day - 1)
    formatted_date = current_date.strftime("%Y-%m-%d (%A)")  # Example: 2025-04-19 (Saturday)
    
    print(f"\n🗓️ {formatted_date}:")
    for shift, pairs in shifts_for_day.items():
        print(f"  🕒 {shift} Shift:")
        for pair in pairs:
            emp1 = pair[0]
            emp2 = pair[1] if pair[1] else "(No Partner)"
            print(f"    - {emp1} & {emp2}")
