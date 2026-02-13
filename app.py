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
        # DEBUG: Print to Render logs so we can see the raw data
        print(f"RAW DATA FROM SHEET: {bookings_raw[:3]}") 
    except Exception as e:
        print(f"Error fetching: {e}")
        bookings_raw = []

    refined = []
    # We skip the header row. 
    # Based on your CSV: 0=Date, 1=Contact, 2=School, 7=Status
    for row in bookings_raw:
        try:
            # CHECK: If the first item is "Lunch Date", it's the header. Skip it.
            if "Date" in str(row[0]):
                continue
            
            # CHECK: If the school name is just a number (like '2'), 
            # we check if we need to shift our index.
            school_val = str(row[2])
            date_val = str(row[0]).split('T')[0]
            
            # If school_val is a number, the columns are shifted in the API response
            if school_val.isdigit() and len(row) > 3:
                # Emergency fallback: try index 3 if index 2 is a digit
                school_val = str(row[3]) 

            status_val = str(row[7]) if len(row) > 7 else "New Booking"

            refined.append({
                "delivery_date": date_val,
                "school": school_name_cleaner(school_val),
                "status": status_val,
                "progress": get_progress(status_val),
                "deadline": get_wednesday_deadline(date_val),
                "anchor_sunday": get_sunday_anchor(date_val)
            })
        except:
            continue
    return render_template('admin.html', bookings=refined)

def school_name_cleaner(val):
    # Safety check to ensure we aren't displaying a raw index
    if val == "1" or val == "2" or val == "0":
        return "Unknown School (Check Columns)"
    return val

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
