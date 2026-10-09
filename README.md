# HOS Route Planner — Django + React

A full-stack assessment implementation for a property-carrying truck HOS route planner.

## What it does

- Inputs: current location, pickup, dropoff, current cycle used.
- Geocodes the locations.
- Builds a route using OSRM.
- Displays an OpenStreetMap route.
- Plans 11-hour driving / 14-hour window constraints.
- Adds a 30-minute break after 8 cumulative driving hours.
- Adds fuel stops every 1,000 miles.
- Adds 1-hour pickup/dropoff service.
- Uses a 34-hour restart when the supplied 70-hour cycle is exhausted.
- Generates daily ELD-style 24-hour duty grids.
- Shows route instructions and a complete stop timeline.

## Explicit planning assumptions

The assessment specifies:
- property-carrying driver
- 70 hours / 8 days
- no adverse driving conditions
- fuel at least once every 1,000 miles
- 1 hour pickup/dropoff

It does not specify truck speed or fuel-stop duration, so this implementation makes those explicit:
- 50 mph conservative planning speed
- 30 minutes per fuel stop
- default duty start: 06:00 home-terminal time

The free OSRM route service is an OpenStreetMap-based routing engine and returns route geometry, distance, duration, and turn-by-turn steps. The frontend uses OpenStreetMap tiles with visible attribution.

## Run locally

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Create `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
```

## Deployment

### Backend — Render

Deploy the `backend` directory as a Python web service:

Build:
`pip install -r requirements.txt`

Start:
`gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`

Set:
- `DJANGO_SECRET_KEY`
- `CORS_ALLOWED_ORIGINS=https://YOUR-VERCEL-DOMAIN.vercel.app`

### Frontend — Vercel

Import the repository and set the root directory to `frontend`.

Build command:
`npm run build`

Output directory:
`dist`

Environment variable:
`VITE_API_URL=https://YOUR-RENDER-BACKEND.onrender.com`

## Important map-service note

This project intentionally does not implement Nominatim autocomplete. Location search is a direct user-triggered lookup. If the app is deployed beyond an assessment/demo, use a managed geocoding provider or your own service, cache results, and review the provider's current usage terms.

## 3–5 minute Loom outline

1. 0:00–0:30 — Problem and inputs.
2. 0:30–1:20 — Generate a trip and show map.
3. 1:20–2:00 — Explain HOS logic: 11h driving, 14h window, 30m break, 70/8, fuel, pickup/dropoff.
4. 2:00–2:50 — Show daily log sheets and remarks.
5. 2:50–3:30 — Show Django API and React component structure.
6. 3:30–4:00 — Deployment and design choices.

## Source basis

The HOS rules and log-grid terminology are based on the supplied FMCSA Interstate Truck Driver's Guide to Hours of Service (April 2022), especially the sections covering the 14-hour window, 11-hour driving limit, 30-minute break, 70/8-day limit, 34-hour restart, and RODS/log grid.
