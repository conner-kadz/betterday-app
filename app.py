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
def get_progress(status_text):
    mapping = {
        "New Booking": 15,
        "Link Sent": 35,
        "In Progress": 60,
        "Orders Locked": 80,
        "Culinary Exported": 90,
        "Out for Delivery": 100
    }
    for key, val in mapping.items():
        if key in str(status_text):
            return val
    return 5

def get_sunday_anchor(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
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
        return deadline.strftime('%a, %b %d')
    except: return "TBD"

# --- ROUTES ---

@app.route('/amy-admin')
def amy_admin():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=15)
        bookings_raw = response.json() if response.status_code == 200 else []
    except: bookings_raw = []

    refined = []
    # Skip header row [0]
    for b in bookings_raw[1:]:
        try:
            if len(b) >= 3 and b[2]:
                d_date = str(b[0]).split('T')[0]
                status = str(b[7]) if len(b) > 7 else "New Booking"
                refined.append({
                    "delivery_date": d_date,
                    "school": str(b[2]),
                    "status": status,
                    "progress": get_progress(status),
                    "deadline": get_wednesday_deadline(d_date),
                    "anchor_sunday": get_sunday_anchor(d_date)
                })
        except: continue
    return render_template('admin.html', bookings=refined)

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

@app.route('/school-profile/<school_name>/<date>')
def school_profile(school_name, date):
    deadline = get_wednesday_deadline(date)
    return render_template('profile.html', school=school_name, date=date, deadline=deadline)

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
    return render_template('order_success.html', name=data['name'])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))
