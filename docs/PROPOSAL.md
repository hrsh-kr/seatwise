# Proposal: Seatwise, honest crowding estimates for Delhi's buses

**Team:** Team Rocket (Abhishek Jha, 2022023; Harsh Kumar, 2022198; Shreyashi Binod Kumar, 2022486)  **Problem:** 2, Crowdedness-aware journey planner

## The problem
A packed bus is slow, uncomfortable and often skipped, yet journey planners rank trips only by time. Delhi records every e-ticket, but the data is a thin sample: about 1.2 tickets per bus trip, half without a vehicle number, with stop names that do not match the timetable. A naive per-route-hour count would mislead.

## Our solution
1. **A statistical load model** that treats tickets as a sample of riders and estimates on-board load per route, stretch and half-hour with an uncertainty range, rather than a single number. It pools across days and neighbouring stretches and times, and borrows the weekday pattern for weekends.
2. **A crowd-aware planner** that shows, next to each option, the expected crowding stretch by stretch, where it gets busiest, and how confident the estimate is. A commuter can choose faster or more comfortable, and see the effect of leaving 20 or 40 minutes later.
3. **An operator view**: a route-by-half-hour heatmap, the most loaded stretches, and an estimate of where one more trip relieves the most crowding.
4. **Best time to leave**, a "why this estimate" panel with the evidence behind every number, English and Hindi, and shareable links.
5. **A sensitivity control** for the one assumption the data cannot settle: what share of riders appears as tickets. Conclusions are shown to move or stay put as the planner changes it.

## Why it should win
- **Grounded in the data, and honest about it.** Stop names are resolved by a six-step ladder (87% of boardings positioned; accuracy of the last step measured at a median error of one stop), trip counts are checked against GPS, and every estimate carries a confidence tag.
- **Validated.** Held-out weeks: the 80% interval covers 83.1% of weekday cells and beats a route-by-time baseline; weekday peaks at 08:30 and 19:00, weekends at 0.80x (Saturday) and 0.52x (Sunday) of weekday load.
- **Both audiences.** Commuters get a one-glance badge (icon, label, confidence); operators get ranked overloaded stretches.
- **Reusable.** Predicted occupancy is already published as a GTFS-Realtime-style feed (`occupancy_status` and `occupancy_percentage` per trip, JSON and protobuf), so Transport Stack can adopt it.
- **Reproducible.** One command per stage, an API with interactive docs, a README and a technical note listing where estimates are least reliable.

## Prototype status (submitted with this proposal)
Working end to end on real data: pipeline, load model, planner, REST API (`/journeys`, `/journeys/window`, `/routes/{route}/crowding`, `/routes/{route}/why`, `/operators/heatmap`, `/operators/extra-bus`, `/feeds/occupancy.json|.pb`) and a map interface in English and Hindi, with an optional metro layer. Example: Anand Vihar ISBT to Connaught Place, Tuesday 08:30, 45 minutes with two buses.

## Plan if shortlisted (Phase 2)
- Find an independent signal for absolute load. A GPS dwell-time check was tried and did not work (the GPS is too coarse), so we would ask DTC or DIMTS for a small passenger-counter pilot, and test headway and speed signals from the real-time feed.
- Live bunching adjustment from the real-time positions (a bus right behind another is lighter), turning the forecast feed into a nowcast.
- Crowding for the metro, using hourly gate data if access is granted.
- Replace the brute-force planner with a proper multi-criteria router; add trip counts from more GPS days.
- Resolve the remaining unmatched stops and route names; add vehicle-size data if available.

## Limits we state up front
Absolute levels depend on the assumed ticket share (default 3.5%, from the brief), anchored by a per-route capacity floor; relative crowding is more reliable than the label. Timings are timetable-based. October data only. See the technical note.
