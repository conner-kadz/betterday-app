from flask import Flask, render_template, request, make_response, redirect, url_for
import requests
from datetime import datetime, timedelta
import os
import calendar
import re
from bs4 import BeautifulSoup

app = Flask(__name__)

# --- FILTERS ---
@app.template_filter('is_past')
def is_past_filter(date_str):
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    return date_obj < datetime.now().date()

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

def get_taken_dates():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL, timeout=5)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"Error fetching from Google: {e}")
        return []

# --- ROUTES ---

@app.route('/')
def index():
    user_booking = request.cookies.get('user_booked_date')
    already_booked_error = request.args.get('error') == 'already_booked'
    taken = get_taken_dates()
    
    now = datetime.now()
    current_m = now.month
    current_y = now.year
    
    next_m = 1 if current_m == 12 else current_m + 1
    next_y = current_y + 1 if current_m == 12 else current_y

    view_m = int(request.args.get('m', current_m))
    view_y = int(request.args.get('y', current_y))

    is_viewing_next = (view_m == next_m)
    prev_url = url_for('index', m=current_m, y=current_y) if is_viewing_next else None
    next_url = url_for('index', m=next_m, y=next_y) if not is_viewing_next else None

    valid_dates = []
    slots_available = 0
    num_days = calendar.monthrange(view_y, view_m)[1]
    
    for d in range(1, num_days + 1):
        date_obj = datetime(view_y, view_m, d)
        if date_obj.weekday() < 3:
            date_str = date_obj.strftime('%Y-%m-%d')
            is_taken = date_str in taken
            is_past = date_obj.date() < now.date()
            
            if not is_taken and not is_past:
                slots_available += 1
                
            valid_dates.append({
                'raw_date': date_str,
                'display': date_obj.strftime('%A, %b %d'),
                'taken': is_taken,
                'past': is_past,
                'is_user_date': date_str == user_booking 
            })

    return render_template('index.html', 
                           dates=valid_dates, 
                           month_name=calendar.month_name[view_m],
                           year=view_y,
                           slots=slots_available,
                           prev_url=prev_url,
                           next_url=next_url,
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

@app.route('/harvest')
def harvest_menu():
    target_date = request.args.get('date')
    if not target_date:
        return "⚠️ Please add a date to the URL, e.g., /harvest?date=2026-02-15"

    url = f"https://eatbetterday.ca/currentmenu/?dd={target_date}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        selectors = soup.find_all('div', id=re.compile('^mealSelector'))
        
        if not selectors:
            return f"No meals found for {target_date}. The page might be hidden or structure changed."

        found_meals = []
        for box in selectors:
            meal_name = box.get('title')
            meal_id = box.get('id').replace('mealSelector', '')
            found_meals.append(f"<b>ID: #{meal_id}</b> | Name: {meal_name}")

        return "<h3>BetterDay Menu Harvest</h3>" + "<br>".join(found_meals)
    except Exception as e:
        return f"Harvest Failed: {str(e)}"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
