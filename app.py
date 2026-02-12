from flask import Flask, render_template, request, make_response, redirect
import requests
from datetime import datetime, timedelta
import os
import calendar

app = Flask(__name__)

# --- FILTERS ---
@app.template_filter('is_past')
def is_past_filter(date_str):
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    return date_obj < datetime.now().date()

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "YOUR_GOOGLE_SCRIPT_URL_HERE"

def get_taken_dates():
    try:
        response = requests.get(GOOGLE_SCRIPT_URL, timeout=5)
        return response.json() if response.status_code == 200 else []
    except:
        return []

@app.route('/')
def index():
    user_booking = request.cookies.get('user_booked_date')
    taken = get_taken_dates()
    
    # Get month/year from URL, default to current
    now = datetime.now()
    month = int(request.args.get('m', now.month))
    year = int(request.args.get('y', now.year))
    
    # Logic for scroller arrows
    prev_m = 12 if month == 1 else month - 1
    prev_y = year - 1 if month == 1 else year
    next_m = 1 if month == 12 else month + 1
    next_y = year + 1 if month == 12 else year

    month_dates = []
    # Calculate days for the selected month
    num_days = calendar.monthrange(year, month)[1]
    for day_num in range(1, num_days + 1):
        date_obj = datetime(year, month, day_num)
        date_str = date_obj.strftime('%Y-%m-%d')
        month_dates.append({
            'raw_date': date_str,
            'day_num': day_num,
            'weekday': date_obj.weekday(),
            'taken': date_str in taken
        })

    return render_template('index.html', 
                           dates=month_dates, 
                           month_name=calendar.month_name[month],
                           year=year,
                           prev_url=f"/?m={prev_m}&y={prev_y}",
                           next_url=f"/?m={next_m}&y={next_y}",
                           user_booking=user_booking)
