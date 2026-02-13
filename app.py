from flask import Flask, render_template, request, make_response, redirect, url_for
import requests
from datetime import datetime, timedelta
import os
import calendar
import re

app = Flask(__name__)

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

# --- UTILITIES ---
def get_sunday_anchor(delivery_date_str):
    """Finds the Sunday before the delivery date for Buffer Sheet matching"""
    try:
        delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d')
        # weekday(): Mon=0 ... Sun=6. Sunday anchor is previous Sunday.
        days_to_subtract = (delivery_date.weekday() + 1) % 7
        if days_to_subtract == 0: days_to_subtract = 7
        return (delivery_date - timedelta(days=days_to_subtract)).strftime('%Y-%m-%d')
    except: return None

def get_wednesday_deadline(delivery_date_str):
    """Calculates the Wednesday 4:00 PM deadline of the week BEFORE delivery"""
    try:
        delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d')
        # We need the Wednesday of the week prior to the delivery week.
        days_to_subtract = (delivery_date.weekday() - 2) % 7
        # Adjust to ensure we are looking at the previous week's Wednesday
        if days_to_subtract <= 2:
            days_to_subtract += 7
        deadline = delivery_date - timedelta(days=days_to_subtract)
        return deadline.strftime('%a, %b %d at 4:00 PM')
    except: return "TBD"

@app.template_filter('is_past')
def is_past_filter(date_str):
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        return date_obj < datetime.now().date()
    except: return False

# --- BOOKING CALENDAR ROUTES ---
def get_taken_dates():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL, timeout=10)
        return response.json() if response.status_code == 200 else []
    except: return []

@app.route('/')
def index():
    user_booking = request.cookies.get('user_booked_date')
    already_booked_error = request.args.get('error') == 'already_booked'
    taken = get_taken_dates()
    now = datetime.now()
    view_m = int(request.args.get('m', now.month))
    view_y = int(request.args.get('y', now.year))
    num_days = calendar.monthrange(view_y, view_m)[1]
    
    valid_dates = []
    for d in range(1, num_days + 1):
        date_obj = datetime(view_y, view_m, d)
        if date_obj.weekday() < 3: # Mon-Wed
            date_str = date_obj.strftime('%Y-%m-%d')
            valid_dates.append({
                'raw_date': date_str,
                'display': date_obj.strftime('%A, %b %d'),
                'taken': date_str in taken,
                'past': date_obj.date() < now.date(),
                'is_user_date': date_str == user_booking 
            })
    return render_template('index.html', dates=valid_dates, month_name=calendar.month_name[view_m], year=view_y, user_booked_date=user_booking, already_booked_error=already_booked_error)

@app.route('/book/<date_raw>', methods=['GET', 'POST'])
def book(date_raw):
    if request.cookies.get('user_booked_date'):
        return redirect(url_for('index', error='already_booked'))
    date_obj = datetime.strptime(date_raw, '%Y-%m-%d')
    date_formatted = date_obj.strftime('%A, %b %d')

    if request.method == 'GET':
        return render_template('form.html', date_display=date_formatted, raw_date=date_raw)

    if request.method == 'POST':
        data = {
            "date": date_raw,
            "contact_name": request.form.get("contact_name"),
            "contact_email": request.form.get("contact_email"),
            "school_name": request.form.get("school_name"),
            "address": request.form.get("address"),
            "staff_count": request.form.get("staff_count"),
            "lunch_time": request.form.get("lunch_time"),
            "delivery_notes": request.form.get("delivery_notes")
        }
        try:
            requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=10)
        except: pass
        resp = make_response(render_template('success.html'))
        resp.set_cookie('user_booked_date', date_raw, max_age=60*60*24*30)
        return resp

# --- AMY'S COMMAND CENTER (CRM) ---
@app.route('/amy-admin')
def amy_admin():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=15)
        bookings_raw = response.json() if response.status_code == 200 else []
    except:
        bookings_raw = []

    refined = []
    for b in bookings_raw:
        # Columns: [Date, Contact, Email, School, Address, Count, Time, Notes, Status]
        d_date = b[0]
        refined.append({
            "school": b[3],
            "delivery_date": d_date,
            "status": b[8] if len(b) > 8 else "New Booking",
            "deadline": get_wednesday_deadline(d_date),
            "anchor_sunday": get_sunday_anchor(d_date)
        })
    return render_template('admin.html', bookings=refined)

# --- TEACHER ORDERING ---
@app.route('/order/<delivery_date>')
def teacher_order(delivery_date):
    anchor_sunday = get_sunday_anchor(delivery_date)
    school_name = request.args.get('school', 'BetterDay School')
    deadline = get_wednesday_deadline(delivery_date)
    
    menu_items = []
    try:
        response = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor_sunday}, timeout=15)
        if response.status_code == 200:
            raw_menu = response.json().get('menu', [])
            for item in raw_menu:
                if item and "#" in str(item):
                    match = re.search(r'#(\d+)', str(item))
                    m_id = match.group(1) if match else "000"
                    m_name = str(item).split('#')[0].strip()
                    menu_items.append({"id": m_id, "name": m_name})
    except: pass

    return render_template('orderform.html', delivery_date=delivery_date, deadline=deadline, menu=menu_items, school_name=school_name)

@app.route('/submit-order', methods=['POST'])
def submit_order():
    order_data = {
        "action": "submit_teacher_order",
        "name": request.form.get('teacher_name'),
        "meal_id": request.form.get('meal_id'),
        "delivery_date": request.form.get('delivery_date'),
        "school": request.form.get('school_name'),
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    try:
        requests.post(GOOGLE_SCRIPT_URL, json=order_data, timeout=10)
        return render_template('order_success.html', name=order_data["name"], date=order_data["delivery_date"])
    except:
        return "CRM Error: Could not save order."

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
