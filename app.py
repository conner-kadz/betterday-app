from flask import Flask, render_template, request, make_response, redirect, url_for
import requests
from datetime import datetime
import os
import calendar
import re

app = Flask(__name__)

# --- FILTERS ---
@app.template_filter('is_past')
def is_past_filter(date_str):
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        return date_obj < datetime.now().date()
    except:
        return False

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

@app.route('/')
def index():
    user_booking = request.cookies.get('user_booked_date')
    already_booked_error = request.args.get('error') == 'already_booked'
    
    taken = []
    try:
        response = requests.get(GOOGLE_SCRIPT_URL, timeout=5)
        if response.status_code == 200:
            taken = response.json()
    except:
        pass
    
    now = datetime.now()
    view_m = int(request.args.get('m', now.month))
    view_y = int(request.args.get('y', now.year))
    num_days = calendar.monthrange(view_y, view_m)[1]
    
    valid_dates = []
    for d in range(1, num_days + 1):
        date_obj = datetime(view_y, view_m, d)
        if date_obj.weekday() < 3:
            date_str = date_obj.strftime('%Y-%m-%d')
            valid_dates.append({
                'raw_date': date_str,
                'display': date_obj.strftime('%A, %b %d'),
                'taken': date_str in taken,
                'past': date_obj.date() < now.date(),
                'is_user_date': date_str == user_booking 
            })

    return render_template('index.html', dates=valid_dates, month_name=calendar.month_name[view_m], year=view_y, user_booked_date=user_booking, already_booked_error=already_booked_error)

@app.route('/harvest')
def harvest_menu():
    target_date = request.args.get('date', '2026-02-15')
    url = f"https://eatbetterday.ca/currentmenu/?dd={target_date}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        # 1. Fetch the giant mountain of code
        response = requests.get(url, headers=headers, timeout=10)
        code = response.text
        
        # 2. Use a "Magnet" (Regex) to find every mealSelector ID and Title
        # Pattern: id="mealSelector537" ... title="Backroads Honey Hot Glazed Chicken"
        pattern = r'id="mealSelector(\d+)".*?title="(.*?)"'
        matches = re.findall(pattern, code, re.DOTALL)
        
        if not matches:
            return f"<h3>No Meal IDs found for {target_date}</h3><p>Sprwt is hiding the data well. Let's check the Pattern Hunter results.</p>"

        found_meals = []
        unique_check = set() # To avoid duplicates

        for m_id, m_name in matches:
            if m_id not in unique_check:
                unique_check.add(m_id)
                img_url = f"https://eatbetterday.ca/data/meals/{m_id}.jpg"
                found_meals.append({
                    "id": m_id,
                    "name": m_name,
                    "image": img_url
                })
        
        # 3. Build the beautiful "MVP" preview
        html_out = f"<h3>BetterDay Harvest: {target_date}</h3><p>Found {len(found_meals)} unique meals.</p><hr>"
        for meal in found_meals:
            html_out += f"""
            <div style="display:flex; align-items:center; margin-bottom:20px; border-bottom:1px solid #ddd; padding-bottom:10px;">
                <img src="{meal['image']}" width="120" style="border-radius:10px; margin-right:20px;">
                <div>
                    <b style="font-size:1.2em;">{meal['name']}</b><br>
                    <span style="color:#666;">Meal ID: #{meal['id']}</span>
                </div>
            </div>
            """
            
        return html_out

    except Exception as e:
        return f"Harvest Error: {str(e)}"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
