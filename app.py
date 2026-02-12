from flask import Flask, render_template, request, make_response, redirect, url_for
import requests
from datetime import datetime
import os
import calendar
import re

app = Flask(__name__)

# --- RESTORED FILTERS ---
@app.template_filter('is_past')
def is_past_filter(date_str):
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        return date_obj < datetime.now().date()
    except:
        return False

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

# --- RESTORED BOOKING ROUTES ---

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

@app.route('/harvest')
def harvest_menu():
    target_date = request.args.get('date', '2026-02-15')
    
    # This is the "Secret Data Link" we found in your Network Tab screenshot
    # It returns a clean list of data instead of a messy website
    api_url = "https://eatbetterday.ca/cart/checkout?read=1"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': f'https://eatbetterday.ca/currentmenu/?dd={target_date}'
    }
    
    try:
        # We ask the server for the raw data feed
        response = requests.get(api_url, headers=headers, timeout=10)
        
        # We search this feed for "mealid":XXX or "id":XXX
        # Since this is a data feed, the IDs are much easier to find
        data_ids = re.findall(r'"mealid":(\d+)', response.text) or re.findall(r'"id":(\d+)', response.text)
        
        unique_ids = sorted(list(set(data_ids)))
        
        if not unique_ids:
            return f"<h3>Backdoor Active - No Meals Found</h3><p>The API responded, but returned no meals for {target_date}. Sprwt might require a login session cookie.</p>"

        found_meals = []
        for m_id in unique_ids:
            img_url = f"https://eatbetterday.ca/data/meals/{m_id}.jpg"
            found_meals.append({
                "id": m_id,
                "image": img_url
            })
            
        html_out = f"<h3>BetterDay API Harvest: {target_date}</h3><p>Bypassed the website shell. Found {len(found_meals)} meal entries in the database.</p><hr>"
        for meal in found_meals:
            html_out += f"""
            <div style="display:inline-block; margin:15px; text-align:center;">
                <img src="{meal['image']}" width="150" style="border-radius:12px; border:1px solid #ddd;"><br>
                <b style="font-family:sans-serif;">ID: #{meal['id']}</b>
            </div>
            """
        return html_out

    except Exception as e:
        return f"API Harvest Error: {str(e)}"
        
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
