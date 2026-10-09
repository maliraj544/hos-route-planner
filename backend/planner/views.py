import json
from datetime import datetime, timedelta
from math import hypot
from time import sleep

import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .planner import build_plan, geocode_locations, route_locations

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "HOSRoutePlanner/1.0 (assessment project; contact: developer@example.com)"

@csrf_exempt
def health(request):
    return JsonResponse({"status": "ok"})

@csrf_exempt
def plan_trip(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        current = str(payload.get("current_location", "")).strip()
        pickup = str(payload.get("pickup_location", "")).strip()
        dropoff = str(payload.get("dropoff_location", "")).strip()
        cycle = float(payload.get("current_cycle_used", 0))

        if not current or not pickup or not dropoff:
            return JsonResponse({"error": "Current, pickup and dropoff locations are required."}, status=400)
        if cycle < 0 or cycle > 70:
            return JsonResponse({"error": "Current Cycle Used must be between 0 and 70 hours."}, status=400)

        locations = [current, pickup, dropoff]
        points = geocode_locations(locations)
        route = route_locations(points)
        plan = build_plan(points, route, cycle)

        return JsonResponse(plan)
    except requests.RequestException as exc:
        return JsonResponse({"error": f"Map service error: {exc}"}, status=502)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": f"Unexpected planner error: {exc}"}, status=500)
