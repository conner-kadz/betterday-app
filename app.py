from flask import Flask, render_template, request, make_response, redirect, url_for
import requests
from datetime import datetime, timedelta
import os
import calendar
import re

app = Flask(__name__)

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

# --- UTILITY: THE SUNDAY LOOK-BACK ---
def get_sunday_anchor(delivery_date_str):
    """ Finds the Sunday before the delivery date for Column H matching """
    try:
        # Expected format: '2026-03-02'
        delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d')
        # weekday() returns Mon=0, Sun=6.
        # To get the previous Sunday:
        days_to_subtract = (delivery_date.weekday() + 1) % 7
        # If the delivery is Sunday, we look back exactly one week
        if days_to_subtract == 0: 
            days_to_subtract = 7
            
        sunday_anchor = delivery_date - timedelta(days=days_to_subtract)
        return sunday_anchor.strftime('%Y-%m-%d')
    except Exception as e:
        print(f"Look-back error: {e}")
        return None

# --- FILTERS ---
@app.template_filter('is_past')
def is_past_filter(date_str):
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        return date_obj < datetime.now().date()
    except:
        return False

# --- EXISTING BOOKING LOGIC ---
def get_taken_dates():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL, timeout=5)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"Error fetching from Google: {e}")
        return []

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
        if date_obj.weekday() < 3: # Monday - Wednesday
            date_str = date_obj.strftime('%Y-%m-%d')
            valid_dates.append({
                'raw_date': date_str,
                'display': date_obj.strftime('%A, %b %d'),
                'taken': date_str in taken,
                'past': date_obj.date() < now.date(),
                'is_user_date': date_str == user_booking 
            })

    return render_template('index.html', 
                           dates=valid_dates, 
                           month_name=calendar.month_name[view_m], 
                           year=view_y, 
                           user_booked_date=user_booking, 
                           already_booked_error=already_booked_error)

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
            "school_name": request.form.get("school_name"),
            "address": request.form.get("address"),
            "staff_count": request.form.get("staff_count"),
            "lunch_time": request.form.get("lunch_time"),
            "delivery_notes": request.form.get("delivery_notes")
        }
        try:
            requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=5)
        except:
            pass

        resp = make_response(render_template('success.html'))
        resp.set_cookie('user_booked_date', date_raw, max_age=60*60*24*30)
        return resp

# --- AMY'S COMMAND CENTER (CRM VIEW) ---
@app.route('/amy-admin')
def amy_admin():
    # Placeholder for fetching all school bookings from Google Sheets
    # For testing, we mock the Hillside booking for March 2nd
    mock_bookings = [
        {
            "id": "101",
            "school": "Hillside Elementary",
            "delivery_date": "2026-03-02",
            "count": 45,
            "anchor_sunday": get_sunday_anchor("2026-03-02")
        }
    ]
    return render_template('admin.html', bookings=mock_bookings)

# --- TEACHER ORDERING LINK ---
@app.route('/order/<delivery_date>')
def teacher_order(delivery_date):
    # 1. Calculate the Sunday Anchor (e.g., March 2nd -> Feb 15th)
    anchor_sunday = get_sunday_anchor(delivery_date)
    
    menu_items = []
    try:
        # 2. Call your Google Script to get the real menu from the Buffer sheet
        response = requests.post(GOOGLE_SCRIPT_URL, json={
            "action": "get_menu",
            "sunday_anchor": anchor_sunday
        }, timeout=10)
        
        if response.status_code == 200:
            raw_data = response.json()
            raw_menu = raw_data.get('menu', [])
            
            # 3. Clean the names (extract the #ID and the Name)
            for item in raw_menu:
                if item and str(item).strip():
                    # Look for # followed by numbers (like #509)
                    match = re.search(r'#(\d+)', str(item))
                    m_id = match.group(1) if match else "000"
                    # Remove the ID from the name so it looks clean
                    m_name = str(item).split('#')[0].replace('\n', ' ').strip()
                    menu_items.append({"id": m_id, "name": m_name})
                    
    except Exception as e:
        print(f"Connection Error: {e}")

    # 4. Send the real menu to the page
    return render_template('orderform.html', 
                           delivery_date=delivery_date, 
                           anchor=anchor_sunday, 
                           menu=menu_items)

@app.route('/submit-order', methods=['POST'])
def submit_order():
    # Data from the Teacher
    teacher_name = request.form.get('teacher_name')
    meal_id = request.form.get('meal_id')
    
    # Metadata to keep Amy's CRM organized
    delivery_date = request.form.get('delivery_date')
    school_name = request.form.get('school_name')

    # The payload for Google Sheets
    order_data = {
        "action": "submit_teacher_order",
        "name": teacher_name,
        "meal_id": meal_id,
        "delivery_date": delivery_date,
        "school": school_name,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    try:
        # Pushing to your GOOGLE_SCRIPT_URL
        response = requests.post(GOOGLE_SCRIPT_URL, json=order_data, timeout=5)
        
        # We need a success page to tell the teacher "You're all set!"
        return render_template('order_success.html', name=teacher_name, date=delivery_date)
    except Exception as e:
        return f"CRM Error: Could not save order. Details: {str(e)}"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
