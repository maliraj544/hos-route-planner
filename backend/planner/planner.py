from datetime import datetime, timedelta
from math import radians, sin, cos, asin, sqrt
from time import sleep
import os
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"

# Set NOMINATIM_USER_AGENT in your environment to identify your app and provide a real contact email.
# Replace the example email below before relying on the public Nominatim service.
USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT",
    "HOSRoutePlanner/1.0 (contact: maliraj544@gmail.com)",
)

# Assignment assumptions + explicit planning assumptions.
MAX_DRIVING_HOURS = 11.0
MAX_WINDOW_HOURS = 14.0
REST_HOURS = 10.0
BREAK_AFTER_DRIVING_HOURS = 8.0
BREAK_HOURS = 0.5
CYCLE_LIMIT_HOURS = 70.0
RESTART_HOURS = 34.0
FUEL_EVERY_MILES = 1000.0
FUEL_DURATION_HOURS = 0.5
PICKUP_DROPOFF_HOURS = 1.0
TRUCK_PLANNING_SPEED_MPH = 50.0
START_HOUR = 6


def geocode_locations(locations):
    result = []
    cache = {}
    for text in locations:
        key = text.lower()
        if key in cache:
            result.append(cache[key])
            continue
        # Deliberately use direct user-triggered geocoding, not autocomplete.
        try:
            response = requests.get(
                NOMINATIM_URL,
                params={"q": text, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=15,
            )
            if response.status_code == 403:
                raise ValueError(
                    "Nominatim returned HTTP 403 Forbidden. Check that NOMINATIM_USER_AGENT "
                    "identifies HOSRoutePlanner and includes a real contact email. If it already "
                    "does, the public service may be blocking this request; try again later or "
                    "configure another geocoding provider."
                )
            response.raise_for_status()
            data = response.json()
            if not data:
                # Retry without country restriction for international test inputs.
                response = requests.get(
                    NOMINATIM_URL,
                    params={"q": text, "format": "jsonv2", "limit": 1},
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=15,
                )
                if response.status_code == 403:
                    raise ValueError(
                        "Nominatim returned HTTP 403 Forbidden. Check the app User-Agent/contact "
                        "email, or use another geocoding provider if the service is blocking requests."
                    )
                response.raise_for_status()
                data = response.json()
        except requests.Timeout as exc:
            raise ValueError(
                f"The geocoding service timed out while looking up '{text}'. Please try again."
            ) from exc
        except requests.RequestException as exc:
            raise ValueError(
                f"Could not contact the geocoding service for '{text}': {exc}"
            ) from exc
        if not data:
            raise ValueError(f"Could not geocode location: {text}")
        item = {
            "query": text,
            "lat": float(data[0]["lat"]),
            "lon": float(data[0]["lon"]),
            "display_name": data[0].get("display_name", text),
        }
        cache[key] = item
        result.append(item)
        sleep(1.05)
    return result


def route_locations(points):
    coords = ";".join(f"{p['lon']},{p['lat']}" for p in points)
    response = requests.get(
        f"{OSRM_URL}/{coords}",
        params={"overview": "full", "geometries": "geojson", "steps": "true"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("No drivable route was found for the supplied locations.")
    route = data["routes"][0]
    return {
        "distance_miles": route["distance"] / 1609.344,
        "osrm_duration_hours": route["duration"] / 3600,
        "geometry": route["geometry"],
        "legs": route.get("legs", []),
    }


def haversine_miles(a, b):
    lon1, lat1 = a
    lon2, lat2 = b
    r = 3958.7613
    dlon = radians(lon2 - lon1)
    dlat = radians(lat2 - lat1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(h))


def cumulative_geometry_miles(geometry):
    coords = geometry["coordinates"]
    cumulative = [0.0]
    for i in range(1, len(coords)):
        cumulative.append(cumulative[-1] + haversine_miles(coords[i-1], coords[i]))
    return coords, cumulative


def point_at_miles(coords, cumulative, target):
    if target <= 0:
        return coords[0]
    if target >= cumulative[-1]:
        return coords[-1]
    lo, hi = 0, len(cumulative) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cumulative[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    i = max(1, lo)
    before = cumulative[i - 1]
    span = cumulative[i] - before
    frac = 0 if span <= 0 else (target - before) / span
    a, b = coords[i - 1], coords[i]
    return [a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac]


def format_iso(dt):
    return dt.isoformat()


def add_segment(segments, status, start, end, location=None):
    if end <= start:
        return
    segments.append({
        "status": status,
        "start": format_iso(start),
        "end": format_iso(end),
        "location": location,
    })


def build_plan(points, route, current_cycle_used):
    # We use the route distance from OSRM as the mileage basis. The HOS clock uses
    # a conservative 50 mph truck-planning speed because the free route service
    # is a car-routing profile, not a certified commercial-truck ETA.
    total_miles = route["distance_miles"]
    coords, cumulative = cumulative_geometry_miles(route["geometry"])

    # Find the approximate route-mile positions of pickup and dropoff using each OSRM leg distance.
    leg1_miles = route["legs"][0]["distance"] / 1609.344 if route["legs"] else total_miles / 2
    waypoint_miles = [0.0, leg1_miles, total_miles]

    # Build readable turn-by-turn instructions from OSRM.
    instructions = []
    for leg in route["legs"]:
        for step in leg.get("steps", []):
            maneuver = step.get("maneuver", {})
            mtype = maneuver.get("type", "continue")
            modifier = maneuver.get("modifier")
            road = step.get("name") or "unnamed road"
            distance = step.get("distance", 0) / 1609.344
            if mtype == "depart":
                text = f"Depart onto {road}"
            elif mtype == "arrive":
                text = f"Arrive at destination via {road}"
            else:
                direction = f" {modifier}" if modifier else ""
                text = f"{mtype.replace('_', ' ').title()}{direction} onto {road}"
            instructions.append({"instruction": text, "miles": round(distance, 1)})

    now = datetime.now().replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    if now.hour < START_HOUR:
        now -= timedelta(days=1)
    duty_start = now
    drive_today = 0.0
    drive_since_break = 0.0
    cycle_used = float(current_cycle_used)
    progress_miles = 0.0
    next_fuel = FUEL_EVERY_MILES

    events = []
    timeline = []
    logs = {}
    current_location_label = points[0]["display_name"]

    def add_activity(kind, status, duration, miles=None, label=None):
        nonlocal now, cycle_used
        start = now
        end = now + timedelta(hours=duration)
        loc = point_at_miles(coords, cumulative, progress_miles)
        events.append({
            "type": kind,
            "label": label or kind,
            "start": format_iso(start),
            "end": format_iso(end),
            "location": {"lat": loc[1], "lon": loc[0]},
            "miles": round(progress_miles, 1),
        })
        add_segment(timeline, status, start, end, loc)
        now = end
        if status == "on_duty":
            cycle_used += duration
        return start, end

    def add_rest(hours, kind="sleeper"):
        nonlocal now, duty_start, drive_today, drive_since_break
        start = now
        end = now + timedelta(hours=hours)
        loc = point_at_miles(coords, cumulative, progress_miles)
        events.append({
            "type": "rest",
            "label": "10-hour sleeper/off-duty rest",
            "start": format_iso(start),
            "end": format_iso(end),
            "location": {"lat": loc[1], "lon": loc[0]},
            "miles": round(progress_miles, 1),
        })
        add_segment(timeline, kind, start, end, loc)
        now = end
        duty_start = now
        drive_today = 0.0
        drive_since_break = 0.0

    def flush_log(day):
        day_start = datetime(day.year, day.month, day.day)
        day_end = day_start + timedelta(days=1)
        day_segments = []
        totals = {"off_duty": 0.0, "sleeper": 0.0, "driving": 0.0, "on_duty": 0.0}
        for seg in timeline:
            s = datetime.fromisoformat(seg["start"])
            e = datetime.fromisoformat(seg["end"])
            if e <= day_start or s >= day_end:
                continue
            clipped_s = max(s, day_start)
            clipped_e = min(e, day_end)
            hours = (clipped_e - clipped_s).total_seconds() / 3600
            status = seg["status"]
            day_segments.append({
                "status": status,
                "start": format_iso(clipped_s),
                "end": format_iso(clipped_e),
                "start_hour": (clipped_s - day_start).total_seconds() / 3600,
                "end_hour": (clipped_e - day_start).total_seconds() / 3600,
            })
            totals[status] = round(totals.get(status, 0) + hours, 2)
        logs[str(day)] = {
            "date": str(day),
            "segments": day_segments,
            "totals": totals,
            "remarks": [],
        }

    # Start with off-duty midnight -> 06:00.
    day = now.date()
    add_segment(timeline, "off_duty", datetime(day.year, day.month, day.day), now)

    # Process current -> pickup -> dropoff.
    for target_index, target_mile in enumerate(waypoint_miles[1:], start=1):
        while progress_miles < target_mile - 0.01:
            # Cycle limit.
            if cycle_used >= CYCLE_LIMIT_HOURS - 0.001:
                add_segment(timeline, "off_duty", now, now + timedelta(hours=RESTART_HOURS))
                events.append({
                    "type": "restart",
                    "label": "34-hour cycle restart",
                    "start": format_iso(now),
                    "end": format_iso(now + timedelta(hours=RESTART_HOURS)),
                    "location": {
                        "lat": point_at_miles(coords, cumulative, progress_miles)[1],
                        "lon": point_at_miles(coords, cumulative, progress_miles)[0],
                    },
                    "miles": round(progress_miles, 1),
                })
                now += timedelta(hours=RESTART_HOURS)
                duty_start = now
                drive_today = 0
                drive_since_break = 0
                cycle_used = 0

            # 30-minute break after 8 cumulative driving hours.
            if drive_since_break >= BREAK_AFTER_DRIVING_HOURS - 0.001:
                add_activity("break", "off_duty", BREAK_HOURS, label="30-minute rest break")
                drive_since_break = 0.0
                continue

            window_used = (now - duty_start).total_seconds() / 3600
            window_left = MAX_WINDOW_HOURS - window_used
            drive_left = MAX_DRIVING_HOURS - drive_today
            break_drive_left = BREAK_AFTER_DRIVING_HOURS - drive_since_break
            cycle_left = CYCLE_LIMIT_HOURS - cycle_used

            if min(window_left, drive_left, break_drive_left, cycle_left) <= 0.001:
                add_rest(REST_HOURS)
                continue

            remaining_miles = target_mile - progress_miles
            miles_per_hour = TRUCK_PLANNING_SPEED_MPH
            max_drive_hours = min(window_left, drive_left, break_drive_left, cycle_left)
            max_miles = max_drive_hours * miles_per_hour

            # Stop for fuel at each 1,000-mile threshold.
            miles_to_fuel = max(0, next_fuel - progress_miles)
            chunk_miles = min(remaining_miles, max_miles)
            if miles_to_fuel > 0:
                chunk_miles = min(chunk_miles, miles_to_fuel)

            if chunk_miles <= 0.001:
                if progress_miles >= next_fuel - 0.01:
                    add_activity("fuel", "on_duty", FUEL_DURATION_HOURS, label="Fuel stop (30 min planning assumption)")
                    next_fuel += FUEL_EVERY_MILES
                    continue
                add_rest(REST_HOURS)
                continue

            hours = chunk_miles / miles_per_hour
            start = now
            end = now + timedelta(hours=hours)
            add_segment(timeline, "driving", start, end, point_at_miles(coords, cumulative, progress_miles + chunk_miles))
            events.append({
                "type": "driving",
                "label": "Driving",
                "start": format_iso(start),
                "end": format_iso(end),
                "location": {
                    "lat": point_at_miles(coords, cumulative, progress_miles + chunk_miles)[1],
                    "lon": point_at_miles(coords, cumulative, progress_miles + chunk_miles)[0],
                },
                "miles": round(progress_miles + chunk_miles, 1),
            })
            now = end
            progress_miles += chunk_miles
            drive_today += hours
            drive_since_break += hours
            cycle_used += hours

            if progress_miles >= next_fuel - 0.01 and progress_miles < target_mile - 0.01:
                add_activity("fuel", "on_duty", FUEL_DURATION_HOURS, label="Fuel stop (30 min planning assumption)")
                next_fuel += FUEL_EVERY_MILES

        # Mandatory pickup/dropoff service.
        if target_index == 1:
            add_activity("pickup", "on_duty", PICKUP_DROPOFF_HOURS, label="Pickup — 1 hour")
        else:
            add_activity("dropoff", "on_duty", PICKUP_DROPOFF_HOURS, label="Dropoff — 1 hour")

        # If the service ends at/after the 14-hour window, rest before any more driving.
        if target_index == 1 and progress_miles < total_miles - 0.01:
            if (now - duty_start).total_seconds() / 3600 >= MAX_WINDOW_HOURS - 0.001:
                add_rest(REST_HOURS)

    # Finish with off-duty after dropoff.
    add_segment(timeline, "off_duty", now, now + timedelta(hours=1))
    now += timedelta(hours=1)

    # Build logs for every calendar day touched.
    start_day = min(datetime.fromisoformat(s["start"]).date() for s in timeline)
    end_day = max(datetime.fromisoformat(s["end"]).date() for s in timeline)
    cursor = start_day
    while cursor <= end_day:
        flush_log(cursor)
        cursor += timedelta(days=1)

    # Add remarks from events to each day.
    for event in events:
        day_key = event["start"][:10]
        if day_key in logs:
            logs[day_key]["remarks"].append(
                f"{event['label']} at route mile {event['miles']:.1f}"
            )

    for log in logs.values():
        # Ensure 24-hour totals are represented in the log even if there are tiny gaps.
        total = sum(log["totals"].values())
        log["totals"]["total"] = round(total, 2)

    return {
        "assumptions": {
            "hos": "Property-carrying CMV, 70 hours / 8 days, no adverse driving conditions",
            "max_driving_hours": MAX_DRIVING_HOURS,
            "max_window_hours": MAX_WINDOW_HOURS,
            "daily_rest_hours": REST_HOURS,
            "break_after_driving_hours": BREAK_AFTER_DRIVING_HOURS,
            "fuel_every_miles": FUEL_EVERY_MILES,
            "fuel_stop_hours": FUEL_DURATION_HOURS,
            "pickup_dropoff_hours": PICKUP_DROPOFF_HOURS,
            "truck_planning_speed_mph": TRUCK_PLANNING_SPEED_MPH,
            "start_time": "06:00 home-terminal time",
        },
        "locations": points,
        "route": {
            "distance_miles": round(total_miles, 1),
            "osrm_duration_hours": round(route["osrm_duration_hours"], 2),
            "geometry": route["geometry"],
        },
        "instructions": instructions,
        "events": events,
        "logs": list(logs.values()),
        "summary": {
            "estimated_trip_days": len(logs),
            "final_route_miles": round(total_miles, 1),
            "current_cycle_used_hours": current_cycle_used,
            "final_cycle_used_hours": round(cycle_used, 2),
        },
    }
