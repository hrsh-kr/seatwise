# Seatwise demo video: narration script

About 5 minutes: roughly 2 minutes of slides (notes 01 to 04 and 15) and 3 minutes in the app (notes 05 to 14). Each numbered note is one voice recording, in order; the on-screen actions are listed under it. The slides carry the figures and quotes, so the narration summarises them instead of reading them out.

## Part 1: slides (about 1 minute 55 seconds)

### 01. Slide 1: Title (about 15 s)
> Hello everyone and thank you for watching. This video shows Seatwise which is our entry for Problem 2 of the Transport Stack Hackathon. Seatwise estimates how crowded Delhi buses are and shows that next to the journey time.

### 02. Slide 2: Planners show time but not crowding (about 19 s)
> Journey planners today rank trips by time and by the number of changes. They do not tell the rider how full the bus will be. The two studies here look at buses in Boston and at a metro system. Both find that crowding has a real cost for passengers.

### 03. Slide 3: The ticket data is rich but thin (about 26 s)
> The data is rich because Delhi records every e-ticket. The chart shows tickets through a typical weekday with a morning peak and an evening peak. The figures on the right show why the data needs care. We see only about one ticket per bus trip. Half of the tickets have no vehicle number and about a third of the stop names do not match the timetable exactly.

### 04. Slide 4: From a thin sample to a crowding estimate (about 25 s)
> Seatwise deals with this in four steps. The chart covers the first step which is placing ticket stop names on the right route. About two thirds match exactly and the rest are recovered in stages so that about eighty seven percent of boardings end up on a route. The later steps scale the sample up and add a range and a confidence to every estimate.

---

## Part 2: the app (about 3 minutes)

### 05. Planning a trip (about 15 s)
> Now let me show the app. I will plan a trip from Anand Vihar to Connaught Place on a weekday evening. Seatwise lists several options and each one shows the journey time and how full the ride is likely to be.

App: choose the first example, results load. Highlight the form, then the first card.

### 06. Reading an option (about 17 s)
> The fastest option takes forty six minutes and part of that ride is standing room. Another option takes fifty minutes and a seat is likely for most of the ride. The coloured strip shows the crowding along the ride and the map colours the route the same way so we can see where the bus gets busy.

App: highlight the fastest option's minutes and badge, then the fifty minute option's badge, then the strip, then the coloured route on the map.

### 07. Through the day (about 14 s)
> This chart shows how full this bus is through the day. Our boarding time is marked and we can see how the crowding changes around it. Clicking a bar plans the trip again for that time.

App: highlight the chart and the "you" marker, then click a bar.

### 08. Best time to leave (about 9 s)
> There is also a button to compare departure times. It checks departures over a few hours and marks the best one.

App: press the compare button, highlight the outlined bar.

### 09. The evidence (about 12 s)
> Each estimate has a panel that shows what it is based on. It lists the number of tickets behind it and the number of buses that ran and the share of riders we assumed.

App: open "Why this estimate", highlight each line as it is named.

### 10. The assumption (about 21 s)
> That share is an assumption because the data cannot tell us how many riders buy e-tickets. It can be adjusted here. Lowering it makes the buses look fuller and the line under each option shows how the label would change. A capacity limit keeps any route from showing more people than a bus can hold.

App: open Assumptions, drag the slider, highlight the "If the e-ticket share were" line.

### 11. For planners: the heatmap (about 15 s)
> The operators tab is meant for transport planners. The heatmap shows the busiest routes for every half hour. Green means seats are available and dark red means the bus is at or over capacity.

App: Operators tab, highlight a row, then a dark red cell, click it.

### 12. For planners: the extra trip (about 10 s)
> Below the heatmap is a ranking of where one extra trip would help most. It is a rough estimate and it assumes the demand stays the same.

App: scroll to the extra-trip list, highlight the top row.

### 13. Language, theme and phone (about 9 s)
> The app is available in English and Hindi and in light and dark mode. The layout is made for the phone first.

App: switch to Hindi and back, switch theme, then show the phone layout.

### 14. For developers (about 10 s)
> Everything is also available through an API. We publish the predicted occupancy as a feed in the GTFS Realtime format so other apps can use it.

App: About page developer links, then the feed in the browser.

---

## Part 3: closing slide (about 28 s)

### 15. Slide 5: Tested on days the model did not see
> These two charts show how well the model works. On the left about eighty three percent of the actual ticket counts fell inside the range the model gave and our target was eighty. On the right the model finds the morning and evening peaks of a weekday on its own. The limits are listed on the slide and the repository address is at the bottom. Thank you for watching.

---

## Timing and sources
Slides about 1 minute 55 seconds, the app about 2 minutes 50 seconds. Figures on the slides come from this project's own analysis or from Sánchez-Martínez et al. (2018), Hörcher et al. (2017) and Abisla (New America). Note 06 uses the 18:00 weekday trip: the fastest option takes 46 minutes with standing room for part of the ride and another takes 50 minutes with seats.
