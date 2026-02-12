@app.route('/')
def index():
    user_booking = request.cookies.get('user_booked_date')
    taken = get_taken_dates()
    
    # Navigation logic for horizontal scrolling
    now = datetime.now()
    month = int(request.args.get('m', now.month))
    year = int(request.args.get('y', now.year))
    
    prev_m = 12 if month == 1 else month - 1
    prev_y = year - 1 if month == 1 else year
    next_m = 1 if month == 12 else month + 1
    next_y = year + 1 if month == 12 else year

    # Filtered List: Only Mon, Tue, Wed
    valid_dates = []
    slots_available = 0
    num_days = calendar.monthrange(year, month)[1]
    
    for d in range(1, num_days + 1):
        date_obj = datetime(year, month, d)
        if date_obj.weekday() < 3:  # Only Mon-Wed
            date_str = date_obj.strftime('%Y-%m-%d')
            is_taken = date_str in taken
            is_past = date_obj.date() < now.date()
            
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
