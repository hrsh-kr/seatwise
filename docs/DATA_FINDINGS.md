# Data findings (15 Nov 2026)

## Layout
- `data/extracted/October-Delhi.csv`: tickets (original zip in `data/raw/`, checksum verified)
- `data/gtfs/`: Delhi bus static GTFS v32 (from the portal)
- `data/metro/gtfs`, `gates`, `footfall` (metadata only), `parking`: DMRC files
- `docs/`: portal metadata PDFs and the GTFS-RT access instructions

## Tickets
- 2,559,899 rows, 1–31 Oct. 2,259 routes, 6,809 vehicles. 93% single-passenger tickets.
- `ticket_type_id` is always 1 and `amount` is never 0: there is no flag for free-fare or pass riders.
- Daily volume: weekdays about 92–103k, weekends about 35–75k. Low days: 2 Oct (41k), 18 Oct (35k), 20 Oct (49k).
- **`vehicle_number` is missing on 48.5% of rows, at random within each route-day-hour** (5th to 95th percentile of null share is 25–70%, never all-null or all-known). Every trip therefore has about half its tickets carrying a vehicle number. That is enough to rebuild trips from vehicle plus time, then attach the unlabelled tickets by route, time and stop.
- Peaks: 8–10 am about 26% of tickets, 5–8 pm about 24%, midday dip.

## GTFS (bus)
- 2,574 routes, 80k trips, 6,862 stops (4,378 unique names after normalising), **one service id running all 7 days**. The timetable has no weekday/weekend difference and about 18 scheduled trips per route-direction. Day-type differences must come from tickets, not from the schedule.
- `direction_id` is empty. Direction is already in `route_short_name` (`102AUP`, `102ADOWN`), which matches the ticket `route` field. 98.2% of ticket rows match a route. Unmatched examples: `567BSTLUP`, `ML96UP`, `522BDOWN2`.
- Loader (`crowdplan/gtfs.py`) now handles this. It takes about 90 s to load, so cache the result.

## Stop-name matching: the main data-cleaning problem
- Exact match within the route's own GTFS stops covers only about 64% of start stops.
- Mismatches are mostly real stops that GTFS names differently (`Badarpur Border (T)` and similar). Examples: `Mahipal Pur (Nh8)`, `Kapashera Crossing`, `West Patel Nagar`.
- Fuzzy matching lifts weighted coverage to about 90% at a score of 85, but it also makes wrong matches (for example `S J Hospital` to `T B Hospital`). Use it with a high threshold and manual aliases for the top 100 or so unmatched names.
- Stops missing from GTFS are disproportionately terminals and big interchanges, so dropping unmatched tickets would bias loads low where crowding matters. Resolve them rather than discard.

## Implications for the model
1. Rebuild trips from vehicle plus time (a new trip starts on a long gap or when the stop sequence resets). Use the schedule only as a fallback.
2. Only about half of each trip's tickets are labelled, and the data is a 3–4% sample on top of that, so expansion factors are essential.
3. Treat the three low-volume days as anomalies (holidays) and keep them out of weekday and weekend averages.

## Still missing
- Metro hourly footfall and monthly OD data (approval-based; only the metadata PDF was available).
- GTFS-RT feed and API key.
- Bus length or vehicle type.

## Update: first pipeline run (one weekday, 14 Oct)
Code: `crowdplan/prep.py` (stop resolver, trip reconstruction, per-trip loads). Network cache: `outputs/network.pkl`.

**Stop resolution (share of ticket stop mentions, weighted)**: exact 64%, normalised 2.5%, distinctive-token match 4.9%, fuzzy (>=90) 5.4%, geo-snap to the route 6.7%, **unresolved 16.6%** (was 26.7% with exact/fuzzy only). 83% of boardings now have a position on the route. Remaining unresolved names mostly do not exist in the GTFS at all.

**The sample is thinner than assumed.** About 98k tickets/day against about 80k scheduled trips/day in the GTFS: **about 1.2 tickets per scheduled trip**. Trip-level loads from tickets alone are pure noise, so per-trip reconstruction is only a diagnostic. The crowding model has to be statistical: pool across days, stretches and neighbouring time bands, with a thinned-Poisson / gamma-Poisson model and partial pooling, and report intervals. Expect about 8 sampled passengers per route-stretch-30-minute-band cell on weekdays, so use wider bands (peak/off-peak blocks) where cells stay sparse.

**Likely route-level bias**: 80% of tickets are on AC buses (cluster fleet), so e-ticket penetration probably differs by operator and route. A single scale-up factor is not safe: treat penetration as a per-operator parameter and show sensitivity.

**Trips scheduled vs run**: the denominator (buses actually operated per route-hour) comes from the GTFS schedule for now. Real trip counts from the GPS archive would be better and are on the Phase 2 list.

## Update: pooled model v0 and the denominator problem
Code: `crowdplan/model.py` (gamma-Poisson, pooled over days, stretches and half-hours), `crowdplan/evaluate.py`.

Works: held-out weekdays (train 1-21 Oct, test 22-30 Oct): the 80% predictive interval covers 78% of cells at overdispersion phi=2 and 85% at phi=4 (68% at phi=1, i.e. plain Poisson is overconfident because one ticket spans about 12 stretches). The model beats a route-by-band baseline (deviance skill 0.50). City weekday profile peaks at 09:00 and 19:00 (about 5x and 3.4x the midday level); Saturday is 0.80x and Sunday 0.54x of weekday.

**Does not work yet: absolute load.** Busiest routes come out at implausible loads (hundreds to thousands per bus). Cause: the denominator. The GTFS lists about 40-110 trips/day for busy routes, but ticket-bearing vehicles alone (66/day on 717ADOWN, half of all rows unlabelled) each run several trips, so real trips are about 3-4x the timetable. Dividing sampled pax by scheduled trips overstates load. Shape (relative crowding between routes and hours) is probably usable, the level is not.

Fix: take actual trips per route-direction-half-hour from the October GPS feed (README: trip_id and vehicle_id per position). One archive day is about 0.47 GB compressed (3.4 GB unpacked), extractable on its own with range requests.

## Correction after the GPS check (supersedes the "denominator" paragraph above)
Two GPS days (14 Oct weekday, 17 Oct Saturday; `data/gps/`, aggregated to `outputs/gps/trips_*.csv`) show the **timetable is about right in total**: 66k real trips against 72k scheduled across 2,082 routes, median route ratio 1.00. The earlier "3-4x undercount" was a loader bug (only the dominant stop pattern's trips were counted). Fixed: exposure now counts every trip on the route (`Network._build_exposure`), and the model uses GPS-observed trips per departure half-hour where available (`model.load_gps`).
Other GPS facts: 6,032 vehicles, about 11 trips per vehicle per day, 28.8M positions per day; the feed includes cluster/EV buses (DL51...). Labelled tickets per trip are the same across vehicle classes (0.62 DTC, 0.65 EV, 0.53 other cluster), so e-ticket coverage does not differ by operator class.
Remaining problem: some busy routes imply loads far above bus capacity at p0 = 3.5% (e.g. 717DOWN has about 8 sampled tickets per trip). The model now enforces a physical constraint: per-route sampling fraction p_r >= p0, raised until the 99th-percentile cell is at most 1.5x crush capacity. This raises p for 20% of routes (median stays 0.035, 95th percentile 0.072). It anchors absolute levels on those routes; it does not make them independent estimates.

## Validation snapshot (outputs/model/validation.json)
- Held-out weekdays (train 1-21 Oct, test 22-30 Oct), overdispersion phi = 4: 80.4% coverage of the 80% predictive interval (calibrated); deviance skill 0.39 over a route-by-time-band baseline. phi = 1 (plain Poisson) covers only 64%.
- City weekday profile: AM peak 08:30 (4.6x midday), PM peak 19:00 (3.6x); Saturday 0.80x and Sunday 0.52x of weekday load.
- Known weakness: weekend cells (5 Saturdays, 3 Sundays after excluding anomalous days) show an inflated crowded share (about 20-25% against 14% on weekdays). Fix next: weekend prior borrowed from the weekday shape.

## Planner and UI (built)
`crowdplan/planner.py` (walk, direct and one-transfer bus search on the timetable; ranks by minutes + comfort weight x crowd-minutes; also evaluates leaving 20 and 40 minutes later), `crowdplan/api.py` (FastAPI), `static/index.html` (Leaflet map, commuter and operator views). Example: Anand Vihar ISBT to Connaught Place, Tuesday 08:30 gives 45 min fastest (two buses), matching the brief's example. Bug fixed on the way: transfers and walking access matched stops by name only, which joined different stops that share a name; they now use coordinates (250 m transfer radius, 1 km walk limit).
Known gap: about 3% of tickets carry route names that do not match GTFS (e.g. `YMSPLUS` without a direction), so a few routes show "No crowding data".

## Weekend fix
The earlier "weekend inflation" (20-25% crowded vs 14% on weekdays) was mostly an artifact: cells with zero sampled load had a NaN posterior, and NaN compared as "crowded" in my summary. After flooring the gamma shape the real shares are about 3% crowded on weekdays, 2% Saturday, 1% Sunday (92-98% seats-available cells), consistent with lower weekend demand.
Weekend cells now also borrow the weekday along-route / time-of-day shape (prior strength 12 trip-days, route weekend/weekday scale shrunk to the city ratio). Held-out Saturdays (train 3, 10, 17 Oct; test 24, 31 Oct): Poisson deviance 1.93M with the weekday prior vs 2.06M Saturday-only (6.5% better); 91% coverage of the 80% interval (conservative).
Overdispersion re-calibrated on held-out weekdays after the fixes: phi=2 gives 82.6% coverage of the 80% interval (phi=1: 72.8%, phi=4: 89.3%). Default is now phi=2.
Caution that remains: with p0=3.5% the model calls 92% of weekday cells "seats available", which is probably too optimistic for peak Delhi buses. The sampling fraction is the single most consequential assumption; a sensitivity control is the next feature.

## Sampling-fraction sensitivity (built)
The model now stores the sampled-load posterior (gamma shape and rate per cell) instead of pre-scaled loads. `model.view()` rescales at query time with p_eff = max(p_user, p_min), where p_min is the per-route capacity floor (99th-percentile weekday cell <= 1.5x crush). All crowding endpoints take `p`; the UI has a 1.5-8% slider (default 3.5%). Example, route 623UP at 08:30: p=0.07 gives 67 seats / 5 standing / 0 crowded stretches; p at or below the route's floor (0.037) gives 54 / 10 / 8.
Known quirk: a "change" can be a one-stop hop between two stops under 250 m apart (e.g. Anand Vihar ISBT to Anand Vihar ISBT Main Road). Worth filtering in a later pass.
