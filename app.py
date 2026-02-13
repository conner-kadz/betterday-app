from flask import Flask, render_template, request, make_response, redirect, url_for
import requests
from datetime import datetime, timedelta
import os
import calendar
import re

app = Flask(__name__)

# --- CONFIGURATION ---
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKVyW7sguwUq3TYsk-xtIF2fLicefaxTwl_PHjQVjt5-OiBarPQ_nXb_0H927NXAMG0w/exec"

def get_sunday_anchor(delivery_date_str):
    try:
        delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d')
        days_to_subtract = (delivery_date.weekday() + 1) % 7
        if days_to_subtract == 0: days_to_subtract = 7
        return (delivery_date - timedelta(days=days_to_subtract)).strftime('%Y-%m-%d')
    except: return None

def get_wednesday_deadline(delivery_date_str):
    """ Calculates the Wednesday 4:00 PM deadline of the week BEFORE delivery """
    try:
        delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d')
        # Find the previous Wednesday (subtracting until we hit weekday 2)
        days_to_subtract = (delivery_date.weekday() - 2) % 7
        # If it's already Wednesday or Tuesday/Monday, we need to go back to the previous week
        if days_to_subtract <= 2:
            days_to_subtract += 7
        deadline = delivery_date - timedelta(days=days_to_subtract)
        return deadline.strftime('%a, %b %d at 4:00 PM')
    except: return "TBD"

# --- AMY'S COMMAND CENTER (CRM) ---
@app.route('/amy-admin')
def amy_admin():
    # In a live setup, we fetch from Google. For now, we structure the cards:
    try:
        # Action 'get_bookings' would be your Google Script fetching Sheet1
        response = requests.get(GOOGLE_SCRIPT_URL + "?action=get_bookings", timeout=15)
        bookings_raw = response.json() if response.status_code == 200 else []
    except:
        bookings_raw = []

    refined = []
    for b in bookings_raw:
        # Mapping Google Sheet columns to our Dashboard
        # Assuming: [Date, Contact, Email, School, Address, Count, Time, Notes, Status]
        delivery_date = b[0]
        refined.append({
            "school": b[3],
            "delivery_date": delivery_date,
            "contact": b[1],
            "email": b[2],
            "status": b[8] if len(b) > 8 else "New Booking",
            "deadline": get_wednesday_deadline(delivery_date),
            "anchor_sunday": get_sunday_anchor(delivery_date)
        })
    
    return render_template('admin.html', bookings=refined)

# --- TEACHER ORDERING ---
@app.route('/order/<delivery_date>')
def teacher_order(delivery_date):
    anchor_sunday = get_sunday_anchor(delivery_date)
    school_name = request.args.get('school', 'BetterDay School')
    deadline = get_wednesday_deadline(delivery_date)
    
    menu_items = []
    try:
        # Fetching the menu from the Buffer sheet
        response = requests.post(GOOGLE_SCRIPT_URL, json={"action": "get_menu", "sunday_anchor": anchor_sunday}, timeout=15)
        if response.status_code == 200:
            raw_menu = response.json().get('menu', [])
            for item in raw_menu:
                if item and "#" in str(item):
                    match = re.search(r'#(\d+)', str(item))
                    m_id = match.group(1) if match else "000"
                    m_name = str(item).split('#')[0].strip()
                    menu_items.append({"id": m_id, "name": m_name})
    except: pass

    return render_template('orderform.html', 
                           delivery_date=delivery_date, 
                           deadline=deadline,
                           menu=menu_items, 
                           school_name=school_name)

# --- (Other routes for index, book, and submit_order remain as they were) ---

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
