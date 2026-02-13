from flask import Flask, render_template, request, make_response, redirect, url_for, Response
import requests
from datetime import datetime, timedelta
import os
import calendar
import re
import csv
import io

app = Flask(__name__)

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

# --- UTILITIES ---
def get_nice_date(date_str):
    try:
        # Returns "Monday, Jan 5"
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

def get_wednesday_deadline(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        days_to_subtract = (delivery_date.weekday() - 2) % 7
        if days_to_subtract <= 2: days_to_subtract += 7
        deadline = delivery_date - timedelta(days=days_to_subtract)
        # Returns "Feb 11" (HTML adds the "Wednesday")
        return deadline.strftime('%b %d') 
    except: return "TBD"

@app.template_filter('decode_school')
def decode_school_filter(s):
    return str(s).replace('+', ' ')

# --- ROUTES ---

@app.route('/amy-admin')
def amy_admin():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=15)
        bookings_raw = response.json() if response.status_code == 200 else []
    except: bookings_raw = []

    refined = []
    for b in bookings_raw:
        try:
            if "Date" in str(b[0]) or str(b[2]).isdigit(): continue
            d_date = str(b[0]).split('T')[0]
            status = str(b[7]) if len(b) > 7 else "New Booking"
            
            refined.append({
                "delivery_date_raw": d_date,
                "delivery_date_display": get_nice_date(d_date),
                "school": str(b[2]),
                "status": status,
                "deadline": get_wednesday_deadline(d_date)
            })
        except: continue
    return render_template('admin.html', bookings=refined)

@app.route('/school-profile/<school_name>/<date>')
def school_profile(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    
    # 1. Get Staff Count
    staff_count = 0
    contact_email = ""
    try:
        r = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=10)
        for row in r.json():
            if str(row[2]) == clean_school_name and str(row[0]).split('T')[0] == date:
                staff_count = int(row[4]) if str(row[4]).isdigit() else 0
                # Assuming Contact Email is not in sheet yet, but if it was, we'd grab it here
                break
    except: pass

    # 2. Get Actual Orders
    order_count = 0
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_orders", "school": clean_school_name, "date": date}, timeout=10)
        orders = r.json()
        order_count = len(orders)
    except: pass

    deadline = get_wednesday_deadline(date)
    
    return render_template('profile.html', 
                         school=clean_school_name, 
                         date=date, 
                         deadline=deadline, 
                         staff=staff_count, 
                         orders=order_count,
                         display_date=get_nice_date(date))

@app.route('/download-csv/<school_name>/<date>')
def download_csv(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    
    # Fetch orders
    r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_orders", "school": clean_school_name, "date": date})
    orders = r.json()

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
    r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_orders", "school": clean_school_name, "date": date})
    orders = r.json()
    
    # Group by dish for summary
    summary = {}
    for o in orders:
        mid = o['meal_id']
        summary[mid] = summary.get(mid, 0) + 1
        
    return render_template('picklist.html', school=clean_school_name, date=date, orders=orders, summary=summary)

# --- TEACHER ORDERING ---
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
                    m = re.search(r'#(\d+)', str(item))
                    m_id = m.group(1) if m else "000"
                    m_name = str(item).split('#')[0].strip()
                    menu.append({"id": m_id, "name": m_name})
    except: pass
    return render_template('orderform.html', delivery_date=delivery_date, deadline=deadline, menu=menu, school_name=school)

@app.route('/submit-order', methods=['POST'])
def submit_order():
    data = {
        "action": "submit_teacher_order",
        "name": request.form.get('teacher_name'),
        "meal_id": request.form.get('meal_id'),
        "delivery_date": request.form.get('delivery_date'),
        "school": request.form.get('school_name'),
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=10)
    return "Order Submitted!" # Keep it simple for now

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))
