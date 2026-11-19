# Technical note: Seatwise, a crowdedness-aware Delhi bus planner

Transport Stack Hackathon 2026, Problem 2. Code: this repository. Data: October 2026 e-ticket records (2,559,899 tickets), Delhi bus static GTFS v32, and two days of the October GPS feed (14 and 17 Oct) used only to count trips actually run.

## 1. What the data is, and why that decides the method
- **The tickets are a sample.** About 98,000 tickets a day against about 80,000 scheduled trips a day, roughly 1.2 tickets per trip. Problem 3's brief puts e-ticketing at 3-4% of bus tickets. A single trip's load cannot be read from its tickets; loads must be estimated statistically.
- **Half the rows have no vehicle number** (48.5%, spread at random within each route-day-hour), so grouping tickets by vehicle fails for half the data. We do not need trip grouping: the model works on cells pooled over days.
- **Stop names are messy.** Only 64% of ticket stop mentions match the route's GTFS stops exactly.
- **The timetable is a single service for all seven days**, so weekday/weekend differences must come from tickets.
- GPS check: 66,090 real trips against 71,662 scheduled on 14 Oct (median route ratio 1.00), about 11 trips per vehicle per day. The timetable is a good estimate of how many buses run in total, though their timing differs from the schedule.

## 2. Pipeline (`crowdplan/prep.py`)
1. Parse tickets; match the ticket `route` (e.g. `8UP`) to GTFS `route_short_name`, which already carries the direction (98.2% matched).
2. **Resolve each stop name to a position on the route's dominant stop sequence** with a tiered ladder: exact; normalised (abbreviations expanded, generic words such as "terminal" and "metro" dropped); distinctive-token equality (unique within the route); fuzzy match at score >= 90; and **geo-snap** (match the name anywhere in GTFS, then take the nearest stop on the route within 500 m). Shares of stop mentions: exact 64.0%, normalised 2.5%, distinctive-token 4.9%, fuzzy 5.3%, geo-snap 6.8%, unresolved 16.6%. 87% of boardings are positioned. Per-route resolved share is kept and used to scale counts back up.
3. **Alighting.** Where the ticket's end stop is unresolved or not after the boarding stop (14% of tickets), alighting is imputed as the route's median journey length. Early or late alighting is not observable; see limits.
4. **Anomalous days** (daily volume < 80% of the median of the same day type) are excluded: 2, 18, 19, 20 Oct.

## 3. Load model (`crowdplan/model.py`)
For route-direction r, day type d (weekday, Saturday, Sunday), departure half-hour band t and stretch s (the segment between consecutive stops):
- **Counts C(r,d,t,s):** each ticket adds its passenger count to every stretch between its boarding and alighting stop. The band is the half-hour of the trip's departure from the origin, implied from the boarding time minus the scheduled offset to the boarding stop. (Placing tickets by projected time at each stretch failed: real buses run slower than the timetable and tickets landed in bands with no scheduled buses.)
- **Exposure N(r,d,t,s):** trips run in that band covering that stretch. Taken from the GPS feed (trips with >= 30 positions and >= 10 minutes) on a reference day for weekdays and Saturdays, else from the timetable counting every trip on the route, not only the dominant pattern.
- **Sampled load per bus** rho = C/N. Counts and exposures are smoothed with a small kernel (3 half-hour bands by 5 stretches, effective sample size accounted for) and combined with a Gamma prior: rho ~ Gamma(a, b) with a = (C_eff + kappa * prior)/phi and b = (N_eff + kappa)/phi. phi inflates the variance because one ticket spans about 12 stretches, so counts are clumped, not independent. Cells with less than 3 smoothed trip-days of exposure are not reported.
- **Weekend cells** take the weekday along-route and time-of-day shape as their prior (strength 12 trip-days), scaled by the route's weekend/weekday ratio shrunk to the city ratio. This improved held-out Saturday fit by 6.8% in deviance.
- **True load** = rho / p, where p is the share of all riders who appear in the ticket sample. Reported as the posterior median and a 90% credible interval.
- **Crowding levels** for a 12 m bus: seats available <= 35 on board; standing room <= 60 (0.8 x crush capacity of 75); crowded above that. We also report P(crowded). Bus length is not in the data, so all buses are treated as 12 m.
- **The sampling fraction p is the weakest assumption.** The brief suggests 3-4%, so the default is 3.5%. Because our busiest routes would exceed physical capacity at 3.5%, each route also has a capacity floor: p is raised until the 99th-percentile weekday cell is at most 1.5 x crush capacity. This affects 20.3% of routes (median p stays 3.5%, 95th percentile 7.2%) and is an anchoring assumption, not an independent measurement. The interface exposes p as a slider (1.5-8%) so a planner can see how conclusions change.
- **Pass holders and ticketless riders** are inside p: p means the share of all riders visible as tickets, not the share of ticketed riders.

## 4. Journey planner (`crowdplan/planner.py`)
Walk (<= 1 km, detour factor 1.3, 4.5 km/h) to a stop, ride a direct bus or one transfer, walk to the destination, on the static timetable. Transfers need stops within 250 m of each other and a 2-minute buffer. Each ride is annotated stretch by stretch with the crowding of the trips the passenger would actually take. Options are ranked by generalised cost = minutes (including delay from leaving later) + comfort weight x crowd-minutes (weights per ride-minute: seats 0, standing 0.25, crowded 0.8). Three modes: faster (weight 0), balanced (1), more comfortable (3). The planner also evaluates leaving 20 and 40 minutes later, so a commuter sees when the same trip is quieter. Example: Anand Vihar ISBT to Connaught Place on a Tuesday at 08:30 gives a 45-minute fastest option with two buses.

## 5. Validation (`crowdplan/evaluate.py`, `outputs/model/validation.json`)
- **Held-out weekdays.** Fit on 1-21 Oct, predict counts for 22-30 Oct. At phi = 2 the 80% predictive interval covers 83.1% of cells; plain Poisson (phi = 1) covers 72.8%. Deviance skill versus a route-by-time-band baseline: 0.40. phi was chosen on this check.
- **Held-out Saturdays.** Train 3, 10, 17 Oct; test 24, 31 Oct. Weekday-shape prior: deviance 1.96M versus 2.11M Saturday-only; 91% interval coverage (conservative).
- **Known patterns.** City weekday load peaks at 08:30 (4.6x midday) and 19:00 (3.6x midday). Saturday carries 0.80x and Sunday 0.52x of weekday load. Modelled "crowded" share: weekday 2.8%, Saturday 1.9%, Sunday 0.7% of cells.
- **What this does not validate.** The held-out check predicts ticket counts, so it tests the shape and noise of the model, not absolute passenger numbers; there is no automatic-passenger-counter data to compare against.

## 6. Where the estimates are least reliable
1. **Absolute levels** depend on the sampling fraction p and the capacity floor. At 3.5% about 92% of weekday cells read "seats available", which is probably optimistic at real peaks. Relative crowding (route versus route, hour versus hour) is more reliable than the label.
2. **Sparse cells:** about 8 sampled passengers per route-stretch-half-hour on weekdays before pooling; weekend cells rest on 5 Saturdays and 3 Sundays. Confidence (low/medium/high) is shown next to every estimate.
3. **Unresolved stops:** 16.6% of stop mentions could not be placed, mostly names missing from GTFS. Terminals and interchanges are over-represented there.
4. **Alighting is inferred**: a ticket's end stop is a plan, and imputed for 14% of tickets.
5. **Time placement:** buses run off-timetable; weekday and Saturday exposure comes from one GPS day each, Sunday from the timetable.
6. **About 3% of tickets** carry route names that do not match GTFS (for example `YMSPLUS` with no direction); those routes show "no crowding data".
7. **All buses are assumed 12 m**; short buses would be crowded at lower loads.
8. **October only.** No seasonality, festivals or monsoon are covered, and "anomalous" days were excluded by a volume rule, not a calendar.
9. **Planner timings are timetable-based**, not live or GPS-speed based, and routes use their dominant stop pattern.

## 7. Reproducing
See the README. Pipeline stages run in about a minute on a laptop once the network cache is built; the API loads in about 12 s.

## 8. Credits
Open-source: pandas, NumPy, SciPy, RapidFuzz, FastAPI, Uvicorn, Leaflet, OpenStreetMap tiles. Data: Transport Stack (DTC / DoT, IIIT Delhi, ONDC e-ticketing). AI assistance (Claude) was used for code and drafting; the method decisions and checks were reviewed by the team.

## 9. Changes after the first review round
- **Cleaning.** Safe route-name fixes (punctuation, a trailing variant digit, EXT/EX) recover 8,300 tickets; real variants such as `729B` are left alone. A sixth stop-placement tier places a still-unresolved name between the boarding stops of tickets that end there and the alighting stops of tickets that start there (only when the interval is at most 4 stops wide): 1,239 names placed; on names we could hide and re-estimate, the median error is 1 stop and 90.6% are within 1 stop. Boardings placed on a route: 83.1% to 86.9%; tickets with both stops usable: 71.5% to 77.0%; alighting imputed: 13.9% to 11.3%. Fare stages are empty in this GTFS, so they could not be used.
- **Planner.** Access and changes are matched by position (KD-tree, 250 m changes) instead of by name; the metro GTFS is loaded and can be switched on (routed from the timetable, not crowding-modelled); "best time to leave" compares departures across a window; each option shows how its crowding label changes if the e-ticket share were 2%, 3.5% or 6%; each ride has a "why this estimate" panel (tickets pooled, trips, assumed share, capacity floor).
- **Operator and developer outputs.** `/operators/extra-bus` ranks where one more trip removes the most riders-times-stretches above the standing-room limit, assuming demand stays and is shared evenly. `/feeds/occupancy.json` and `.pb` publish a forecast of occupancy for every trip in service at a given time, with GTFS-Realtime `occupancy_status` and `occupancy_percentage`.
- **Validation re-run on the cleaned data:** 83.1% coverage of the 80% interval on held-out weekdays (phi = 2), skill 0.40; Saturday weekday-prior 1.96M against 2.11M deviance; AM peak 08:30, PM peak 19:00.
- **A check that did not work.** We tried to confirm the ticket signal against GPS dwell time at stops (stations with more boardings should hold buses longer). The correlation came out negative (Spearman about -0.23 across route-stops; too few route-stops remain within single routes to test). The GPS positions are coarse and include signal stops and stands, so this is inconclusive and is not claimed as validation (`scripts/dwell_check.py`).
