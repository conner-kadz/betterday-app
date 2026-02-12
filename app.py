from flask import Flask, render_template, request, make_response, redirect
import requests
from datetime import datetime, timedelta
import os
import calendar

# Initialize the Flask app (Fixes NameError: name 'app' is not defined)
app = Flask(__name__)

# --- FILTERS ---
@app.template_filter('is_past')
def is_past_filter(date_str):
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    return date_obj < datetime.now().date()

# --- CONFIGURATION ---
# Replace with your actual Google Script URL from the 'Manage Deployments' menu
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
    taken = get_taken_dates()
    
    # Navigation logic for horizontal scrolling
    now = datetime.now()
    month = int(request.args.get('m', now.month))
    year = int(request.args.get('y', now.year))
    
    # Math for the Prev/Next arrow links
    prev_m = 12 if month == 1 else month - 1
    prev_y = year - 1 if month == 1 else year
    next_m = 1 if month == 12 else month + 1
    next_y = year + 1 if month == 12 else year

    # Filtered List: Only Mon (0), Tue (1), Wed (2)
    valid_dates = []
    slots_available = 0
    num_days = calendar.monthrange(year, month)[1]
    
    for d in range(1, num_days + 1):
        date_obj = datetime(year, month, d)
        if date_obj.weekday() < 3:  # Monday, Tuesday, Wednesday only
            date_str = date_obj.strftime('%Y-%m-%d')
            is_taken = date_str in taken
            is_past = date_obj.date() < now.date()
            
            # Count how many slots are actually bookable for the header
            if not is_taken and not is_past:
                slots_available += 1
                
            valid_dates.append({
                'raw_date': date_str,
                'display': date_obj.strftime('%A, %b %d'),
                'taken': is_taken,
                'past': is_past
            })

    return render_template('index.html', 
                           dates=valid_dates, 
                           month_name=calendar.month_name[month],
                           year=year,
                           slots=slots_available,
                           prev_url=f"/?m={prev_m}&y={prev_y}",
                           next_url=f"/?m={next_m}&y={next_y}")

@app.route('/book/<date_raw>', methods=['GET', 'POST'])
def book(date_raw):
    # Prevent users from booking twice if they have the cookie
    if request.cookies.get('user_booked_date'):
        return redirect('/')

    if request.method == 'POST':
        # Data sent to Google Sheets (Matches Column A through G)
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
            print("Google Sync failed.")

        # Show the success screen
        resp = make_response(render_template('success.html'))
        # Save a cookie so they don't book multiple dates
        resp.set_cookie('user_booked_date', date_raw, max_age=60*60*24*30)
        return resp

    # GET request: Load the booking form (Triggered by the 'Select' button)
    return render_template('form.html', date_display=date_raw, raw_date=date_raw)

if __name__ == '__main__':
    # Render binds to the PORT environment variable automatically
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
