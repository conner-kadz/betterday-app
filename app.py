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
    """Calculates the Sunday prior to delivery for the Menu Buffer sheet"""
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        if "Date" in clean_date: return None
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        # Sunday anchor is previous Sunday.
        days_to_subtract = (delivery_date.weekday() + 1) % 7
        if days_to_subtract == 0: days_to_subtract = 7
        return (delivery_date - timedelta(days=days_to_subtract)).strftime('%Y-%m-%d')
    except: return None

def get_wednesday_deadline(delivery_date_str):
    """Calculates the Wednesday 4:00 PM deadline of the week BEFORE delivery"""
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        if "Date" in clean_date: return "TBD"
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        days_to_subtract = (delivery_date.weekday() - 2) % 7
        if days_to_subtract <= 2:
            days_to_subtract += 7
        deadline = delivery_date - timedelta(days=days_to_subtract)
        return deadline.strftime('%a, %b %d')
    except: return "TBD"

@app.template_filter('is_past')
def is_past_filter(date_str):
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        return date_obj < datetime.now().date()
    except: return False

# --- 1. PRINCIPAL BOOKING CALENDAR ---
@app.route('/')
def index():
    taken = []
    try:
        r = requests.get(GOOGLE_SCRIPT_URL, timeout=10)
        taken = r.json() if r.status_code == 200 else []
    except: pass
    
    now = datetime.now()
    view_m, view_y = int(request.args.get('m', now.month)), int(request.args.get('y', now.year))
    num_days = calendar.monthrange(view_y, view_m)[1]
    valid_dates = []
    for d in range(1, num_days + 1):
        date_obj = datetime(view_y, view_m, d)
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
    
    data = {
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

# --- 2. THE DROP DASHBOARD (CRM) ---
@app.route('/amy-admin')
def amy_admin():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=15)
        bookings_raw = response.json() if response.status_code == 200 else []
    except: bookings_raw = []

    refined = []
    # Skip header row with [1:]
    for b in bookings_raw[1:]:
        try:
            if len(b) >= 3 and b[2]:
                d_date = str(b[0]).split('T')[0]
                refined.append({
                    "delivery_date": d_date,
                    "contact": str(b[1]),
                    "school": str(b[2]),
                    "status": str(b[7]) if len(b) > 7 else "🆕 New Booking",
                    "deadline": get_wednesday_deadline(d_date),
                    "anchor_sunday": get_sunday_anchor(d_date)
                })
        except: continue
    return render_template('admin.html', bookings=refined)

@app.route('/school-profile/<school_name>/<date>')
def school_profile(school_name, date):
    deadline = get_wednesday_deadline(date)
    return render_template('profile.html', school=school_name, date=date, deadline=deadline)

# --- 3. TEACHER ORDERING ---
@app.route('/order/<delivery_date>')
def teacher_order(delivery_date):
    anchor = get_sunday_anchor(delivery_date)
    school = request.args.get('school', 'BetterDay School')
    deadline = get_wednesday_deadline(delivery_date)
    menu = []
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor}, timeout=15)
        if r.status_code == 200:
            for item in r.json().get('menu', []):
                if "#" in str(item):
                    id_match = re.search(r'#(\d+)', str(item))
                    m_id = id_match.group(1) if id_match else "000"
                    m_name = str(item).split('#')[0].strip()
                    menu.append({"id": m_id, "name": m_name})
    except: pass
    return render_template('orderform.html', delivery_date=delivery_date, deadline=deadline, menu=menu, school_name=school)

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
    requests.post(GOOGLE_SCRIPT_URL, json=order_data, timeout=10)
    return render_template('order_success.html', name=order_data["name"])

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
