from flask import Flask, render_template, request, make_response, redirect
import requests
from datetime import datetime, timedelta
import sqlite3
import os

app = Flask(__name__)

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

def get_taken_dates():
    try:
        # The app now "calls" Google to see what is booked
response = requests.get(GOOGLE_SCRIPT_URL)        if response.status_code == 200:
            return response.json() # Returns the list of dates from the Sheet
        return []
    except Exception as e:
        print(f"Error fetching from Google: {e}")
        return []

@app.route('/')
def index():
    # Check if this user already has a booking cookie
    user_booking = request.cookies.get('user_booked_date')
    
    taken = get_taken_dates()
    dates = []
    current = datetime.now()
    
    # Generate 4 weeks, but ONLY include Mon (0), Tue (1), and Wed (2)
    for i in range(28):
        day = current + timedelta(days=i)
        if day.weekday() < 3: # Monday, Tuesday, Wednesday only
            date_str = day.strftime('%Y-%m-%d')
            dates.append({
                'raw_date': date_str,
                'display': day.strftime('%A, %b %d'),
                'taken': date_str in taken,
                'is_user_date': date_str == user_booking
            })
    
    return render_template('index.html', dates=dates, user_booking=user_booking)

@app.route('/book/<date_raw>', methods=['GET', 'POST'])
def book(date_raw):
    # If they already have a cookie, don't let them see the form
    if request.cookies.get('user_booked_date'):
        return redirect('/')

    if request.method == 'POST':
        data = {
            "date": date_raw,
            "contact_name": request.form.get("contact_name"),
            "school_name": request.form.get("school_name"),
            "staff_count": request.form.get("staff_count"),
            "lunch_time": request.form.get("lunch_time"),
            "delivery_notes": request.form.get("delivery_notes")
        }
        
        # 1. Send to Google Sheets
        try:
            requests.post(GOOGLE_SCRIPT_URL, json=data)
        except:
            pass 

        # 2. Mark as taken locally
        conn = sqlite3.connect('bookings.db')
        conn.execute('INSERT OR REPLACE INTO taken_dates (date) VALUES (?)', (date_raw,))
        conn.commit()
        conn.close()
        
        # 3. Show success and "Plant" the cookie for 30 days
        resp = make_response(render_template('success.html'))
        resp.set_cookie('user_booked_date', date_raw, max_age=60*60*24*30)
        return resp

    return render_template('form.html', date_display=date_raw, raw_date=date_raw)

if __name__ == '__main__':
    # Initialize DB if it doesn't exist
    conn = sqlite3.connect('bookings.db')
    conn.execute('CREATE TABLE IF NOT EXISTS taken_dates (date TEXT PRIMARY KEY)')
    conn.close()
    
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
