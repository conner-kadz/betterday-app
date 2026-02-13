from flask import Flask, render_template, request, make_response, redirect, url_for, Response
import requests
from datetime import datetime, timedelta
import os
import calendar
import re
import csv
import io

app = Flask(__name__)

# ==============================================================================
# CONFIGURATION & UTILITIES
# ==============================================================================
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

def get_nice_date(date_str):
    try:
        # Converts 2026-02-15 -> "Monday, Feb 15"
        dt = datetime.strptime(str(date_str).split('T')[0], '%Y-%m-%d')
        return dt.strftime('%A, %b %d')
    except: return date_str

def get_sunday_anchor(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        if "Date" in clean_date: return None
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        # Anchor is the Sunday of the week *before* delivery
        days_to_subtract = (delivery_date.weekday() + 1) % 7
        if days_to_subtract == 0: days_to_subtract = 7
        return (delivery_date - timedelta(days=days_to_subtract)).strftime('%Y-%m-%d')
    except: return None

def get_wednesday_deadline(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        # Deadline is Wednesday of the week *before* delivery
        days_to_subtract = (delivery_date.weekday() - 2) % 7
        if days_to_subtract <= 2: days_to_subtract += 7
        deadline = delivery_date - timedelta(days=days_to_subtract)
        # UPDATE: Added time format
        return deadline.strftime('%b %d @ 4:00 PM') 
    except: return "TBD"

@app.template_filter('decode_school')
def decode_school_filter(s):
    return str(s).replace('+', ' ')

@app.template_filter('is_past')
def is_past_filter(date_str):
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        return date_obj < datetime.now().date()
    except: return False


# ==============================================================================
# SECTION 1: THE FRONT DOOR (Principal Calendar)
# ==============================================================================

@app.route('/')
def index():
    taken = []
    try:
        # We fetch bookings to see what dates are taken
        r = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=8)
        taken_raw = r.json() if r.status_code == 200 else []
        
        # Extract just the dates for the calendar
        for row in taken_raw:
            if row and len(row) > 0 and "Date" not in str(row[0]):
                taken.append(str(row[0]).split('T')[0])
    except: pass
    
    now = datetime.now()
    view_m, view_y = int(request.args.get('m', now.month)), int(request.args.get('y', now.year))
    num_days = calendar.monthrange(view_y, view_m)[1]
    valid_dates = []
    
    for d in range(1, num_days + 1):
        date_obj = datetime(view_y, view_m, d)
        # Only show Mon-Wed (0, 1, 2)
        if date_obj.weekday() < 3: 
            ds = date_obj.strftime('%Y-%m-%d')
            valid_dates.append({
                'raw_date': ds, 
                'display': date_obj.strftime('%b %d'), 
                'taken': ds in taken, 
                'past': date_obj.date() < now.date()
            })
    return render_template('index.html', dates=valid_dates, month_name=calendar.month_name[view_m], year=view_y)

@app.route('/book/<date_raw>', methods=['GET', 'POST'])
def book(date_raw):
    if request.method == 'GET':
        return render_template('form.html', date_display=date_raw, raw_date=date_raw)
    
    # Submit booking to Sheet
    data = {
        "action": "book_principal", # Explicit Action
        "date": date_raw,
        "contact_name": request.form.get("contact_name"),
        "school_name": request.form.get("school_name"),
        "address": request.form.get("address"),
        "staff_count": request.form.get("staff_count"),
        "lunch_time": request.form.get("lunch_time"),
        "delivery_notes": request.form.get("delivery_notes")
    }
    requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=10)
    resp = make_response(render_template('success.html'))
    resp.set_cookie('user_booked_date', date_raw, max_age=60*60*24*30)
    return resp


# ==============================================================================
# SECTION 2: BD ADMIN (The Dashboard)
# ==============================================================================

@app.route('/BD-Admin')
def bd_admin():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=15)
        bookings_raw = response.json() if response.status_code == 200 else []
    except: bookings_raw = []

    refined = []
    for b in bookings_raw:
        try:
            # Skip header row and row indexes
            if "Date" in str(b[0]) or str(b[2]).isdigit(): continue
            d_date = str(b[0]).split('T')[0]
            status = str(b[7]) if len(b) > 7 else "New Booking"
            staff_count = str(b[4]) if len(b) > 4 else "0"

            refined.append({
                "delivery_date_raw": d_date,
                "delivery_date_display": get_nice_date(d_date),
                "school": str(b[2]),
                "status": status,
                "staff_count": staff_count,
                "deadline": get_wednesday_deadline(d_date)
            })
        except: continue
    return render_template('admin.html', bookings=refined)

@app.route('/school-profile/<school_name>/<date>')
def school_profile(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    
    data = {}
    try:
        # One fast call to get everything
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=12)
        data = r.json()
    except: pass

    # Unpack safely
    staff_count = int(data.get('staff_count', 0))
    orders = data.get('orders', [])
    order_count = len(orders)
    
    return render_template('profile.html', 
                         school=clean_school_name, 
                         date=date, 
                         deadline=get_wednesday_deadline(date), 
                         staff=staff_count, 
                         orders=order_count,
                         display_date=get_nice_date(date),
                         info=data) 

@app.route('/update-booking', methods=['POST'])
def update_booking():
    school = request.form.get('school')
    date = request.form.get('date')
    status = request.form.get('status')
    email = request.form.get('email')
    
    try:
        payload = {
            "action": "update_booking",
            "school": school,
            "date": date,
            "status": status,
            "email": email
        }
        requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=8)
    except: pass
    
    return redirect(url_for('school_profile', school_name=school.replace(' ', '+'), date=date))


@app.route('/download-csv/<school_name>/<date>')
def download_csv(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    try:
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload)
        data = r.json()
        orders = data.get('orders', [])
    except: orders = []

    # Create CSV
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Teacher Name', 'Dish ID']) # Header
    for o in orders:
        cw.writerow([o['teacher'], o['meal_id']])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={clean_school_name}_orders.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/picklist/<school_name>/<date>')
def picklist_print(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    try:
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload)
        data = r.json()
        orders = data.get('orders', [])
    except: orders = []
    
    # Group by dish for summary
    summary = {}
    for o in orders:
        mid = o['meal_id']
        summary[mid] = summary.get(mid, 0) + 1
        
    return render_template('picklist.html', school=clean_school_name, date=date, orders=orders, summary=summary)


# ==============================================================================
# SECTION 3: TEACHER ORDERS (User Interface)
# ==============================================================================

@app.route('/order/<delivery_date>')
def teacher_order(delivery_date):
    # --- NEW: COOKIE GUARD ---
    # 1. Check if they already have the cookie for this date
    if request.cookies.get(f'ordered_{delivery_date}'):
        # If yes, send them straight to success page with "existing=True"
        school = request.args.get('school', 'BetterDay School')
        share_link = url_for('teacher_order', delivery_date=delivery_date, school=school, _external=True)
        return render_template('order_success.html', share_link=share_link, existing=True)

    # 2. If no cookie, proceed normally
    anchor = get_sunday_anchor(delivery_date)
    school = request.args.get('school', 'BetterDay School')
    deadline = get_wednesday_deadline(delivery_date)
    menu = []
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor}, timeout=15)
        if r.status_code == 200:
            for item in r.json().get('menu', []):
                if "#" in str(item):
                    m = re.search(r'#(\d+)', str(item))
                    m_id = m.group(1) if m else "000"
                    m_name = str(item).split('#')[0].strip()
                    menu.append({"id": m_id, "name": m_name})
    except: pass
    return render_template('orderform.html', delivery_date=delivery_date, deadline=deadline, menu=menu, school_name=school)

@app.route('/submit-order', methods=['POST'])
def submit_order():
    school_name = request.form.get('school_name')
    delivery_date = request.form.get('delivery_date')

    data = {
        "action": "submit_teacher_order",
        "name": request.form.get('teacher_name'),
        "meal_id": request.form.get('meal_id'),
        "delivery_date": delivery_date,
        "school": school_name,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    try:
        requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=5)
    except: pass
    
    # Generate Share Link
    share_link = url_for('teacher_order', delivery_date=delivery_date, school=school_name, _external=True)
    
    # --- NEW: SET COOKIE ---
    # Create the response object
    resp = make_response(render_template('order_success.html', share_link=share_link, existing=False))
    
    # Stamp the browser with a 30-day cookie
    resp.set_cookie(f'ordered_{delivery_date}', 'true', max_age=60*60*24*30)
    
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))
