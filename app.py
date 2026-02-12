@app.route('/harvest')
def harvest_menu():
    target_date = request.args.get('date', '2026-02-15')
    # This is the secret backdoor URL discovered in your code mountain
    data_url = "https://eatbetterday.ca/cart/checkout?read=1"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': f'https://eatbetterday.ca/currentmenu/?dd={target_date}'
    }
    
    try:
        # We ask for the DATA, not the WEBSITE
        response = requests.get(data_url, headers=headers, timeout=10)
        
        # If this returns JSON, we've struck gold. 
        # We'll search the response for the Meal IDs we know exist (305, 515, 537)
        code = response.text
        
        # Search for the IDs in the data feed
        found_ids = re.findall(r'\"mealid\":(\d+)', code) or re.findall(r'\"id\":(\d+)', code)
        
        unique_ids = sorted(list(set(found_ids)))
        
        if not unique_ids:
            return f"<h3>Backdoor Found, but No Meals in Feed</h3><p>Check the date: {target_date}. The server might need a cookie to show the menu.</p>"

        found_meals = []
        for m_id in unique_ids:
            img_url = f"https://eatbetterday.ca/data/meals/{m_id}.jpg"
            found_meals.append({
                "id": m_id,
                "image": img_url
            })
            
        html_out = f"<h3>BetterDay Backdoor Harvest: {target_date}</h3><p>Successfully bypassed the wall. Found {len(found_meals)} meals.</p><hr>"
        for meal in found_meals:
            html_out += f"""
            <div style="display:inline-block; margin:10px; text-align:center;">
                <img src="{meal['image']}" width="150" style="border-radius:10px;"><br>
                <b>ID: #{meal['id']}</b>
            </div>
            """
        return html_out

    except Exception as e:
        return f"Backdoor Error: {str(e)}"
