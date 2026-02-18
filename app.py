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
# CONFIGURATION
# ==============================================================================
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"
# Replace with your actual Google Sheet URL for the "Teacher Bookings" button
TEACHER_SHEET_URL = "https://docs.google.com/spreadsheets" 

# ==============================================================================
# HELPERS
# ==============================================================================
def get_nice_date(date_str):
    try:
        dt = datetime.strptime(str(date_str).split('T')[0], '%Y-%m-%d')
        return dt.strftime('%A, %b %d')
    except: return date_str

def get_sunday_anchor(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        if "Date" in clean_date: return None
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        days_to_subtract = (delivery_date.weekday() + 1) % 7
        if days_to_subtract == 0: days_to_subtract = 7
        return (delivery_date - timedelta(days=days_to_subtract)).strftime('%Y-%m-%d')
    except: return None

def get_deadline_obj(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        # Deadline is Wednesday of the week *before* delivery
        days_to_subtract = (delivery_date.weekday() - 2) % 7
        if days_to_subtract <= 2: days_to_subtract += 7
        deadline_date = delivery_date - timedelta(days=days_to_subtract)
        return deadline_date.replace(hour=16, minute=0, second=0)
    except: return None

def get_menu_map(delivery_date):
    # Helper to get ID -> Name mapping
    anchor = get_sunday_anchor(delivery_date)
    mapping = {}
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor}, timeout=10)
        if r.status_code == 200:
            for item in r.json().get('menu', []):
                if "#" in str(item):
                    m = re.search(r'#(.*)', str(item)) # Capture everything after #
                    if m:
                        m_id = m.group(1).strip()
                        m_name = str(item).split('#')[0].strip()
                        mapping[m_id] = m_name
    except: pass
    return mapping

@app.template_filter('decode_school')
def decode_school_filter(s):
    return str(s).replace('+', ' ')

# ==============================================================================
# ROUTES
# ==============================================================================

@app.route('/')
def index():
    taken = []
    try:
        r = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=8)
        taken_raw = r.json() if r.status_code == 200 else []
        for row in taken_raw:
            if row and len(row) > 0 and "Date" not in str(row[0]):
                taken.append(str(row[0]).split('T')[0])
    except: pass
    
    now = datetime.now()
    view_m = int(request.args.get('m', now.month))
    view_y = int(request.args.get('y', now.year))

    # Next/Prev Logic
    if view_m == now.month:
        next_m = view_m + 1 if view_m < 12 else 1
        next_y = view_y if view_m < 12 else view_y + 1
        next_url = url_for('index', m=next_m, y=next_y)
        prev_url = None 
    elif (view_m == now.month + 1) or (now.month == 12 and view_m == 1):
        prev_url = url_for('index', m=now.month, y=now.year)
        next_url = None
    else:
        return redirect(url_for('index'))

    num_days = calendar.monthrange(view_y, view_m)[1]
    valid_dates = []
    
    for d in range(1, num_days + 1):
        date_obj = datetime(view_y, view_m, d)
        if date_obj.weekday() < 3: 
            ds = date_obj.strftime('%Y-%m-%d')
            valid_dates.append({
                'raw_date': ds, 
                'display': date_obj.strftime('%A, %b %d'), 
                'taken': ds in taken, 
                'past': date_obj.date() < now.date()
            })

    return render_template('index.html', dates=valid_dates, month_name=calendar.month_name[view_m], year=view_y, prev_url=prev_url, next_url=next_url)

@app.route('/book/<date_raw>', methods=['GET', 'POST'])
def book(date_raw):
    if request.method == 'GET':
        return render_template('form.html', date_display=date_raw, raw_date=date_raw)
    
    data = {
        "action": "book_principal",
        "date": date_raw,
        "contact_name": request.form.get("contact_name"),
        "email": request.form.get("email"), # <--- NEW FIELD
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

@app.route('/BD-Admin')
def bd_admin():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=15)
        bookings_raw = response.json() if response.status_code == 200 else []
    except: bookings_raw = []

    refined = []
    for b in bookings_raw:
        try:
            if "Date" in str(b[0]) or str(b[2]).isdigit(): continue
            d_date = str(b[0]).split('T')[0]
            deadline_obj = get_deadline_obj(d_date)
            
            refined.append({
                "delivery_date_raw": d_date,
                "delivery_date_display": get_nice_date(d_date),
                "school": str(b[2]),
                "status": str(b[7]) if len(b) > 7 else "New Booking",
                "staff_count": str(b[4]) if len(b) > 4 else "0",
                "deadline": deadline_obj.strftime('%b %d') if deadline_obj else "TBD"
            })
        except: continue
    return render_template('admin.html', bookings=refined)

@app.route('/school-profile/<school_name>/<date>')
def school_profile(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    data = {}
    try:
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=12)
        data = r.json()
    except: pass

    # Countdown Logic
    deadline_obj = get_deadline_obj(date)
    days_left = (deadline_obj - datetime.now()).days if deadline_obj else -1
    deadline_str = deadline_obj.strftime('%b %d @ 4:00 PM') if deadline_obj else "TBD"
    
    if days_left < 0: countdown_text = "⚠️ Orders Closed"
    elif days_left == 0: countdown_text = "🚨 Ends Today!"
    else: countdown_text = f"⏰ {days_left} Days Left"

    return render_template('profile.html', 
                         school=clean_school_name, 
                         date=date, 
                         display_date=get_nice_date(date),
                         deadline=deadline_str,
                         countdown=countdown_text,
                         staff=int(data.get('staff_count', 0)), 
                         orders=len(data.get('orders', [])),
                         info=data,
                         sheet_url=TEACHER_SHEET_URL) 

@app.route('/update-booking', methods=['POST'])
def update_booking():
    school = request.form.get('school')
    date = request.form.get('date')
    try:
        requests.post(GOOGLE_SCRIPT_URL, json={
            "action": "update_booking",
            "school": school,
            "date": date,
            "status": request.form.get('status'),
            "email": request.form.get('email')
        }, timeout=8)
    except: pass
    return redirect(url_for('school_profile', school_name=school.replace(' ', '+'), date=date))

@app.route('/download-csv/<school_name>/<date>')
def download_csv(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    try:
        # Get Orders
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload)
        orders = r.json().get('orders', [])
        # Get Names
        menu_map = get_menu_map(date)
    except: 
        orders = []
        menu_map = {}

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Teacher Name', 'Dish ID', 'Dish Name']) 
    for o in orders:
        mid = str(o['meal_id']).strip()
        cw.writerow([o['teacher'], mid, menu_map.get(mid, 'Unknown Dish')])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={clean_school_name}_orders.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/picklist/<school_name>/<date>')
def picklist_print(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    try:
        # Get Orders
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload)
        orders = r.json().get('orders', [])
        # Get Names
        menu_map = get_menu_map(date)
    except: 
        orders = []
        menu_map = {}
    
    # Summary
    summary = {}
    for o in orders:
        mid = str(o['meal_id']).strip()
        name = menu_map.get(mid, f"Dish #{mid}")
        if name not in summary: summary[name] = {"id": mid, "count": 0}
        summary[name]["count"] += 1
        
    return render_template('picklist.html', school=clean_school_name, date=date, summary=summary, total=len(orders))

@app.route('/order/<delivery_date>')
def teacher_order(delivery_date):
    if request.cookies.get(f'ordered_{delivery_date}'):
        school = request.args.get('school', 'BetterDay School')
        share_link = url_for('teacher_order', delivery_date=delivery_date, school=school, _external=True)
        return render_template('order_success.html', share_link=share_link, existing=True)

    anchor = get_sunday_anchor(delivery_date)
    school = request.args.get('school', 'BetterDay School')
    deadline_obj = get_deadline_obj(delivery_date)
    deadline_str = deadline_obj.strftime('%b %d @ 4:00 PM') if deadline_obj else "TBD"
    
    menu = []
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor}, timeout=15)
        if r.status_code == 200:
            for item in r.json().get('menu', []):
                if "#" in str(item):
                    m = re.search(r'#(.*)', str(item))
                    if m:
                        menu.append({"id": m.group(1).strip(), "name": str(item).split('#')[0].strip()})
    except: pass
    return render_template('orderform.html', delivery_date=delivery_date, deadline=deadline_str, menu=menu, school_name=school)

@app.route('/submit-order', methods=['POST'])
def submit_order():
    school = request.form.get('school_name')
    date = request.form.get('delivery_date')
    try:
        requests.post(GOOGLE_SCRIPT_URL, json={
            "action": "submit_teacher_order",
            "name": request.form.get('teacher_name'),
            "meal_id": request.form.get('meal_id'),
            "delivery_date": date,
            "school": school,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, timeout=5)
    except: pass
    
    share_link = url_for('teacher_order', delivery_date=date, school=school, _external=True)
    resp = make_response(render_template('order_success.html', share_link=share_link, existing=False))
    resp.set_cookie(f'ordered_{date}', 'true', max_age=60*60*24*30)
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))
