import { useMemo, useState } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

function FitBounds({ points }) {
  const map = useMap();
  if (points.length) {
    const bounds = L.latLngBounds(points.map((p) => [p[1], p[0]]));
    map.fitBounds(bounds, { padding: [30, 30] });
  }
  return null;
}

function RouteMap({ plan }) {
  const coords = plan.route.geometry.coordinates || [];
  const line = coords.map(([lon, lat]) => [lat, lon]);
  const markers = plan.events.filter((e) =>
    ["pickup", "dropoff", "fuel", "rest", "restart"].includes(e.type)
  );

  const center = line.length ? line[Math.floor(line.length / 2)] : [39, -98];

  return (
    <div className="map-wrap">
      <MapContainer center={center} zoom={5} scrollWheelZoom className="map">
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; OpenStreetMap contributors'
        />
        <Polyline positions={line} pathOptions={{ weight: 5 }} />
        {plan.locations.map((p, i) => (
          <Marker key={`location-${i}`} position={[p.lat, p.lon]}>
            <Popup>
              <strong>{["Current", "Pickup", "Dropoff"][i]}</strong>
              <br />
              {p.display_name}
            </Popup>
          </Marker>
        ))}
        {markers.map((e, i) => (
          <Marker key={`event-${i}`} position={[e.location.lat, e.location.lon]}>
            <Popup>
              <strong>{e.label}</strong>
              <br />
              Route mile {e.miles}
              <br />
              {new Date(e.start).toLocaleString()}
            </Popup>
          </Marker>
        ))}
        <FitBounds points={coords} />
      </MapContainer>
      <div className="map-attribution-note">Routing: OSRM · Map data: OpenStreetMap</div>
    </div>
  );
}

function formatHours(value) {
  return `${Number(value || 0).toFixed(1)}h`;
}

function DailyLog({ log, plan }) {
  const gridX = 61;
  const gridWidth = 394;
  const rowY = {
    off_duty: 160,
    sleeper: 184,
    driving: 208,
    on_duty: 232,
  };
  const stroke = {
    off_duty: "#36506d",
    sleeper: "#5d7da5",
    driving: "#17243b",
    on_duty: "#8b5e2d",
  };

  const toX = (hour) => gridX + (hour / 24) * gridWidth;

  return (
    <div className="log-card paper-log-card">
      <div className="paper-log">
        <img src="/blank-paper-log.png" alt="FMCSA driver daily log template" />
        <svg className="paper-overlay" viewBox="0 0 513 518" aria-label={`Completed daily log for ${log.date}`}>
          {/* Header fields */}
          <text x="174" y="27" className="log-text strong">{log.date}</text>
          <text x="98" y="75" className="log-text">{plan.summary.final_route_miles} mi</text>
          <text x="237" y="75" className="log-text">HOS Route Planner</text>
          <text x="260" y="100" className="log-text">Assessment Demo</text>
          <text x="94" y="122" className="log-text">TRUCK-01</text>

          {/* Duty-status lines over the supplied blank grid */}
          {log.segments.map((segment, i) => {
            const x1 = toX(segment.start_hour);
            const x2 = toX(segment.end_hour);
            const y = rowY[segment.status];
            if (y === undefined || x2 <= x1) return null;
            return (
              <line
                key={i}
                x1={x1}
                x2={x2}
                y1={y}
                y2={y}
                stroke={stroke[segment.status]}
                strokeWidth="5"
                strokeLinecap="square"
                opacity="0.9"
              />
            );
          })}

          {/* Remarks */}
          {log.remarks.slice(0, 6).map((remark, i) => (
            <text key={i} x="72" y={285 + i * 15} className="log-text small">
              {remark.slice(0, 68)}
            </text>
          ))}
        </svg>
      </div>

      <div className="paper-log-caption">
        <div>
          <strong>{log.date}</strong>
          <span>Off duty {formatHours(log.totals.off_duty)}</span>
          <span>Sleeper {formatHours(log.totals.sleeper)}</span>
          <span>Driving {formatHours(log.totals.driving)}</span>
          <span>On duty {formatHours(log.totals.on_duty)}</span>
        </div>
        <div className="remarks">
          <strong>Generated from the HOS schedule</strong>
          <span>30-minute break, fuel, pickup/dropoff and 10-hour rest periods are shown on the grid.</span>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [form, setForm] = useState({
    current_location: "Chicago, IL",
    pickup_location: "Dallas, TX",
    dropoff_location: "Los Angeles, CA",
    current_cycle_used: 0,
  });
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const update = (key) => (e) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const runPlanner = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setPlan(null);

    try {
      const response = await fetch(`${API_URL}/api/plan/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          current_cycle_used: Number(form.current_cycle_used),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Planner failed.");
      setPlan(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const stopCount = useMemo(
    () => (plan ? plan.events.filter((e) => ["fuel", "rest", "restart"].includes(e.type)).length : 0),
    [plan]
  );

  return (
    <main>
      <header className="hero">
        <div className="hero-inner">
          <div className="brand">HOS<span>ROUTE</span></div>
          <div className="hero-copy">
            <p className="eyebrow">Full-stack developer assessment</p>
            <h1>Plan a compliant truck trip.<br /><em>See the route. Read the logs.</em></h1>
            <p>
              Enter the trip details and generate route instructions, HOS rest/fuel stops,
              and daily ELD-style log sheets.
            </p>
          </div>
        </div>
      </header>

      <section className="container">
        <form className="planner-card" onSubmit={runPlanner}>
          <div className="section-heading">
            <div>
              <span className="eyebrow">Trip inputs</span>
              <h2>Build your route plan</h2>
            </div>
            <span className="assumption-pill">70 hrs / 8 days</span>
          </div>

          <div className="form-grid">
            <label>
              Current location
              <input value={form.current_location} onChange={update("current_location")} placeholder="e.g. Chicago, IL" />
            </label>
            <label>
              Pickup location
              <input value={form.pickup_location} onChange={update("pickup_location")} placeholder="e.g. Dallas, TX" />
            </label>
            <label>
              Dropoff location
              <input value={form.dropoff_location} onChange={update("dropoff_location")} placeholder="e.g. Los Angeles, CA" />
            </label>
            <label>
              Current cycle used (hours)
              <input type="number" min="0" max="70" step="0.1" value={form.current_cycle_used} onChange={update("current_cycle_used")} />
            </label>
          </div>

          <div className="assumptions">
            <span>11h max driving</span>
            <span>14h duty window</span>
            <span>30m break after 8h driving</span>
            <span>Fuel every 1,000 mi</span>
            <span>1h pickup / dropoff</span>
            <span>50 mph planning speed</span>
          </div>

          <button className="primary-btn" disabled={loading}>
            {loading ? "Planning route…" : "Generate HOS plan →"}
          </button>

          {error && <div className="error">{error}</div>}
        </form>

        {plan && (
          <>
            <section className="summary-grid">
              <div className="stat-card"><span>Route</span><strong>{plan.summary.final_route_miles} mi</strong></div>
              <div className="stat-card"><span>Planning days</span><strong>{plan.summary.estimated_trip_days}</strong></div>
              <div className="stat-card"><span>HOS stops</span><strong>{stopCount}</strong></div>
              <div className="stat-card"><span>Cycle used after plan</span><strong>{formatHours(plan.summary.final_cycle_used_hours)}</strong></div>
            </section>

            <section className="results-grid">
              <div className="panel map-panel">
                <div className="panel-title">
                  <div><span className="eyebrow">01 · Route</span><h2>Route & HOS stops</h2></div>
                  <span>{plan.route.distance_miles} miles</span>
                </div>
                <RouteMap plan={plan} />
              </div>

              <div className="panel">
                <div className="panel-title">
                  <div><span className="eyebrow">02 · Instructions</span><h2>Turn-by-turn</h2></div>
                  <span>{plan.instructions.length} steps</span>
                </div>
                <div className="instruction-list">
                  {plan.instructions.slice(0, 35).map((item, i) => (
                    <div className="instruction" key={i}>
                      <span className="instruction-number">{String(i + 1).padStart(2, "0")}</span>
                      <span>{item.instruction}</span>
                      <small>{item.miles} mi</small>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-title">
                <div><span className="eyebrow">03 · Schedule</span><h2>Stops & duty timeline</h2></div>
                <span>{plan.events.length} events</span>
              </div>
              <div className="event-list">
                {plan.events.map((event, i) => (
                  <div className={`event event-${event.type}`} key={i}>
                    <div className="event-dot" />
                    <div className="event-main">
                      <strong>{event.label}</strong>
                      <span>{new Date(event.start).toLocaleString()} → {new Date(event.end).toLocaleTimeString()}</span>
                    </div>
                    <small>mile {event.miles}</small>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel logs-panel">
              <div className="panel-title">
                <div><span className="eyebrow">04 · ELD / RODS</span><h2>Daily log sheets</h2></div>
                <span>{plan.logs.length} sheet(s)</span>
              </div>
              <p className="muted">
                These are generated from the same timeline used for the route plan. The grid follows
                the four FMCSA duty statuses: Off Duty, Sleeper Berth, Driving, and On Duty (Not Driving).
              </p>
              <div className="logs">
                {plan.logs.map((log) => <DailyLog key={log.date} log={log} plan={plan} />)}
              </div>
            </section>

            <footer className="footer-note">
              <strong>Assessment assumptions:</strong> property-carrying CMV, 70-hour/8-day limit,
              no adverse conditions, fuel every 1,000 miles, and 1 hour for pickup/dropoff.
              The planner additionally uses a conservative 50 mph truck-planning speed and 30 minutes
              per fuel stop because those values are not specified in the assessment.
            </footer>
          </>
        )}
      </section>
    </main>
  );
}
