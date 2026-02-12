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
    
    # We use a real browser header to ensure Sprwt doesn't block the request
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        # Regex Magnet: Find every number inside the 'data/meals/' folder as seen in your screenshot
        # Pattern looks for 'data/meals/' then captures digits (\d+) before '.jpg'
        found_ids = re.findall(r'data/meals/(\d+)\.jpg', response.text)
        
        # Also look for meal names paired with IDs in the HTML
        name_matches = re.findall(r'id="mealSelector(\d+)".*?title="(.*?)"', response.text, re.DOTALL)
        name_map = {m_id: m_name for m_id, m_name in name_matches}

        unique_ids = sorted(list(set(found_ids)))
        
        if not unique_ids:
            return f"<h3>No Meal IDs found for {target_date}</h3><p>Sprwt might be hiding the links in a separate script. Try finding a link ending in .json in your Network tab.</p>"

        found_meals = []
        for m_id in unique_ids:
            # Pair ID with Name if found, otherwise use placeholder
            m_name = name_map.get(m_id, "Dish Found")
            img_url = f"https://eatbetterday.ca/data/meals/{m_id}.jpg"
            
            found_meals.append({
                "id": m_id,
                "name": m_name,
                "image": img_url
            })
            
        # Build a visual gallery for the Chef/Admin
        html_out = f"<h3>BetterDay Harvest: {target_date}</h3><p>Detected {len(found_meals)} unique meal IDs.</p><hr>"
        for meal in found_meals:
            html_out += f"""
            <div style="display:flex; align-items:center; margin-bottom:15px; border-bottom:1px solid #eee; padding-bottom:10px;">
                <img src="{meal['image']}" width="100" style="border-radius:8px; margin-right:15px; border:1px solid #ddd;">
                <div>
                    <b style="font-size:1.1em;">{meal['name']}</b><br>
                    <code style="background:#f4f4f4; padding:2px 5px;">ID: #{meal['id']}</code>
                </div>
            </div>
            """
        return html_out

    except Exception as e:
        return f"Harvest Error Details: {str(e)}"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
