# Seatwise: crowdedness-aware Delhi bus journey planner
Transport Stack Hackathon 2026, Problem 2. Estimates how crowded Delhi buses are by route, stretch and time of day from
sampled October 2026 e-ticket data, and shows that crowding next to every journey option.

## Demo video
A 4 minute 20 second walkthrough with narration (720p, 9 MB) is in [`video/seatwise-demo.mp4`](video/seatwise-demo.mp4): the problem and the data on slides, then the app, then validation and limits. The narration text is in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

## Run it (Python 3.12+)
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# data (not in git), see "Data" below
.venv/bin/python -m crowdplan.prep --skip-trips --out outputs/prep_full      # tickets -> stop positions (~20 s)
.venv/bin/python -m crowdplan.model                                          # pooled load model (~20 s)
.venv/bin/python -m crowdplan.evaluate                                       # held-out validation + pattern checks
.venv/bin/python -m uvicorn crowdplan.api:app --port 8000                    # API + UI at http://localhost:8000
```
Optional (better trip counts): `python scripts/fetch_gps_days.py 2026-10-14 2026-10-17` (range-reads two days from the remote archive, about 8 GB unpacked), then `scripts/gps_trips.sh 2026_10_14` and `scripts/gps_trips.sh 2026_10_17`. The model uses `outputs/gps/trips_*.csv` when present.

## Data (not in git)
- **Tickets** (public): `https://pub-091bd9e794bb4877b10b29e6df80f065.r2.dev/2026-10/October-Delhi.csv.zip` (66 MB; verify with `SHA256SUMS` in the same folder). Unzip to `data/extracted/October-Delhi.csv`.
- **Bus static GTFS**: sign up at https://delhi.transportstack.in, request "Delhi Buses: GTFS Static Data", unzip into `data/gtfs/` (`routes.txt`, `trips.txt`, `stops.txt`, `stop_times.txt`, ...).
- **GPS** (optional): see the last line of the run steps. Without it the model falls back to timetable trip counts.
- The first run builds a GTFS cache (`outputs/network.pkl`, about 2 minutes); later runs reuse it. Whole pipeline: about 5 minutes on a laptop. Checked from a fresh clone: validation reproduces (83.1% coverage, 08:30 morning peak) and the API and UI serve.

## API
- `GET /journeys?from=Anand Vihar Isbt&to=Connaught Place&depart=2026-10-20T18:00&priority=balanced|fastest|comfortable`
- All crowding endpoints accept `p` (assumed e-ticket share of riders, default 0.035) for sensitivity; a per-route capacity floor always applies.
- `GET /routes/{route}/crowding?daytype=weekday&time=18:00`  (per-stretch load, 90% interval, confidence)
- `GET /operators/overloaded?daytype=weekday&time=18:00`
- `GET /journeys/window?from=&to=&date=&start=&end=` (best time to leave), `GET /routes/{route}/why?board=&alight=&time=` (evidence behind an estimate)
- `GET /operators/heatmap`, `GET /operators/extra-bus` (where one more trip helps most)
- `GET /feeds/occupancy.json?time=18:00` and `/feeds/occupancy.pb` (predicted occupancy, GTFS-Realtime VehiclePosition)
- `GET /stops?q=`, `GET /health`, `GET /validation`, interactive docs at `/docs`; `/journeys` takes `metro=true` to include the metro

## Method in one paragraph
Tickets are a thinned sample of riders. Each ticket's boarding/alighting stops are resolved to positions on the route
(exact, normalised, distinctive-token, fuzzy, geo-snap tiers), and its pax count is added to every stretch it covers, in the
half-hour band of the trip's departure. Dividing by trips actually run (GPS-observed where available, else timetable) gives
sampled load per bus; a pooled gamma-Poisson model (smoothing across stretches and neighbouring half-hours, overdispersion
tuned on held-out days, phi=2) gives a posterior, scaled by an assumed sampling fraction (3.5%, raised per route where the implied
load would exceed 1.5x crush capacity). Levels: seats (<= 35), standing (<= 60), crowded (> 60) for a 12 m bus.

## Design
See [docs/DESIGN.md](docs/DESIGN.md) (provenance-first design principles).

## Known limits (read before trusting numbers)
- Absolute load depends on the assumed sampling fraction; relative crowding (route vs route, hour vs hour) is more reliable.
- Timings in the planner are timetable-based, not live traffic. One transfer maximum. Dominant stop pattern per route.
- 17% of ticket stop mentions could not be placed on a route; weekend estimates (5 Saturdays, 3 Sundays) are noisier.
- Bus length is not in the data: every bus is treated as 12 m.
