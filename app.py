from flask import Flask, render_template, request, make_response, redirect, url_for, Response
import requests
from datetime import datetime, timedelta
import os
import calendar
import re
import csv
import io
import collections

app = Flask(__name__)

# CONFIGURATION
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

# HELPERS
def get_nice_date(date_str):
    try:
        dt = datetime.strptime(str(date_str).split('T')[0], '%Y-%m-%d')
        return dt.strftime('%A, %b %d')
    except: return date_str

def format_week_header(date_str):
    try:
        dt = datetime.strptime(str(date_str), '%Y-%m-%d')
        return dt.strftime('%b %d, %Y') # "Feb 23, 2026"
    except: return date_str

def get_sunday_anchor(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        days_to_subtract = (delivery_date.weekday() + 1) % 7
        if days_to_subtract == 0: days_to_subtract = 7
        return (delivery_date - timedelta(days=days_to_subtract)).strftime('%Y-%m-%d')
    except: return None

def get_deadline_obj(delivery_date_str):
    try:
        clean_date = str(delivery_date_str).split('T')[0]
        delivery_date = datetime.strptime(clean_date, '%Y-%m-%d')
        days_to_subtract = (delivery_date.weekday() - 2) % 7
        if days_to_subtract <= 2: days_to_subtract += 7
        deadline_date = delivery_date - timedelta(days=days_to_subtract)
        return deadline_date.replace(hour=16, minute=0, second=0)
    except: return None

@app.template_filter('decode_school')
def decode_school_filter(s):
    return str(s).replace('+', ' ')

# ROUTES
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

    if view_m == now.month:
        next_m = view_m + 1 if view_m < 12 else 1
        next_y = view_y if view_m < 12 else view_y + 1
        next_url = url_for('index', m=next_m, y=next_y)
        prev_url = None 
    elif (view_m == now.month + 1) or (now.month == 12 and view_m == 1):
        prev_url = url_for('index', m=now.month, y=now.year)
        next_url = None
    else: return redirect(url_for('index'))

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
        "email": request.form.get("email"),
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
    # 1. Fetch Bookings (School Profiles)
    try:
        r_books = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=10)
        bookings_raw = r_books.json() if r_books.status_code == 200 else []
    except: bookings_raw = []

    # 2. Fetch ALL Orders (To count meals)
    try:
        r_orders = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_all_orders"}, timeout=10)
        all_orders = r_orders.json() if r_orders.status_code == 200 else []
    except: all_orders = []

    # Count orders per school per date
    # Key: "SchoolName_2026-02-23" -> Count
    order_counts = {}
    for o in all_orders:
        key = f"{o['school']}_{o['date']}"
        order_counts[key] = order_counts.get(key, 0) + 1

    # 3. Build Timeline
    production_weeks = {} 

    for b in bookings_raw:
        try:
            if "Date" in str(b[0]) or str(b[2]).isdigit(): continue
            d_date = str(b[0]).split('T')[0]
            anchor = get_sunday_anchor(d_date)
            if not anchor: continue

            deadline_obj = get_deadline_obj(d_date)
            school_name = str(b[2])
            is_office = "Health" in school_name or "Headversity" in school_name

            # Lookup Order Count
            count_key = f"{school_name}_{d_date}"
            meals_ordered = order_counts.get(count_key, 0)

            booking_obj = {
                "delivery_date_raw": d_date,
                "delivery_date_display": get_nice_date(d_date),
                "school": school_name,
                "status": str(b[7]) if len(b) > 7 else "New Booking",
                "staff_count": str(b[4]) if len(b) > 4 else "0",
                "meals_ordered": meals_ordered,
                "deadline": deadline_obj.strftime('%b %d') if deadline_obj else "TBD",
                "type": "Office" if is_office else "School"
            }

            formatted_anchor = format_week_header(anchor) # "Feb 23, 2026"
            
            if formatted_anchor not in production_weeks: production_weeks[formatted_anchor] = {"anchor_id": anchor, "bookings": []}
            production_weeks[formatted_anchor]["bookings"].append(booking_obj)
        except: continue
    
    sorted_weeks = dict(sorted(production_weeks.items()))
    return render_template('admin.html', weeks=sorted_weeks)

@app.route('/culinary-summary/<sunday>')
def culinary_summary(sunday):
    # Fetch ALL orders (which now have dish names!)
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_all_orders"}, timeout=20)
        all_orders = r.json()
    except: all_orders = []

    totals = {} # { "Meat": { "Dish Name": count }, "Plant-Based": { "Dish Name": count } }
    total_count = 0
    
    # We rely on the NEW columns from Sheet (Dish Name & Diet)
    # If old order (no dish name), we fallback gracefully
    
    for o in all_orders:
        anchor = get_sunday_anchor(o['date'])
        if anchor == sunday:
            # Handle Data Warehouse Columns (if they exist in JSON response)
            # We need to make sure get_all_orders sends these. 
            # *See Note below about updating get_all_orders logic in app.py if using JSON indices*
            # Assuming 'o' has keys from get_all_orders logic below
            
            dish_name = o.get('dish_name') or f"Dish #{o['meal_id']}"
            diet = o.get('diet') or "Unknown"
            
            # Grouping
            cat = "Plant-Based" if "Plant" in diet or "Vegan" in diet else "Meat"
            
            if cat not in totals: totals[cat] = {}
            if dish_name not in totals[cat]: totals[cat][dish_name] = 0
            
            totals[cat][dish_name] += 1
            total_count += 1

    return render_template('culinary_picklist.html', sunday=format_week_header(sunday), totals=totals, total_count=total_count)

@app.route('/school-profile/<school_name>/<date>')
def school_profile(school_name, date):
    clean_school_name = school_name.replace('+', ' ')
    data = {}
    try:
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=12)
        data = r.json()
    except: pass

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
                         info=data) 

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
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload)
        orders = r.json().get('orders', [])
        
        # New: If orders have Dish Name embedded, use it. Else fetch map.
        # For now, let's assume we fetch map for safety until all data is migrated
        anchor = get_sunday_anchor(date)
        menu_map = {}
        r_menu = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor}, timeout=10)
        if r_menu.status_code == 200:
            data = r_menu.json()
            for item in data.get('meat', []) + data.get('vegan', []):
                menu_map[str(item['id'])] = item['name']
    except: orders = []; menu_map = {}

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Teacher Name', 'Dish ID', 'Dish Name']) 
    for o in orders:
        mid = str(o['meal_id']).strip()
        # Prefer stored name, fallback to map
        d_name = o.get('dish_name') or menu_map.get(mid, 'Unknown Dish')
        cw.writerow([o['teacher'], mid, d_name])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={clean_school_name}_orders.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/picklist/<school_name>/<date>')
def picklist_print(school_name, date):
    # Similar logic to CSV but render HTML
    clean_school_name = school_name.replace('+', ' ')
    try:
        payload = {"action": "get_profile_data", "school": clean_school_name, "date": date}
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload)
        orders = r.json().get('orders', [])
        
        anchor = get_sunday_anchor(date)
        menu_map = {}
        r_menu = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor}, timeout=10)
        if r_menu.status_code == 200:
            data = r_menu.json()
            for item in data.get('meat', []) + data.get('vegan', []):
                menu_map[str(item['id'])] = item['name']
    except: orders = []; menu_map = {}
    
    summary = {}
    for o in orders:
        mid = str(o['meal_id']).strip()
        name = o.get('dish_name') or menu_map.get(mid, f"Dish #{mid}")
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
    
    meat_menu = []
    vegan_menu = []
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            meat_menu = data.get('meat', [])
            vegan_menu = data.get('vegan', [])
    except: pass
    
    return render_template('orderform.html', 
                         delivery_date=delivery_date, 
                         deadline=deadline_str, 
                         meat_menu=meat_menu, 
                         vegan_menu=vegan_menu, 
                         school_name=school)

@app.route('/submit-order', methods=['POST'])
def submit_order():
    school = request.form.get('school_name')
    date = request.form.get('delivery_date')
    
    # We receive Dish Name and Diet hidden fields from form? 
    # Or we can look them up here? 
    # Better to look up here to avoid form tampering, BUT for simplicity/speed let's trust the form
    # Wait, the form cards need hidden inputs for name/diet.
    # Actually, easier: pass just ID, and let the JS populate hidden name fields.
    
    # Let's pass the logic:
    # 1. User picks ID.
    # 2. JS fills hidden "dish_name" and "diet".
    
    try:
        requests.post(GOOGLE_SCRIPT_URL, json={
            "action": "submit_teacher_order",
            "name": request.form.get('teacher_name'),
            "meal_id": request.form.get('meal_id'),
            "dish_name": request.form.get('dish_name'), # New
            "diet": request.form.get('dish_diet'),      # New
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
