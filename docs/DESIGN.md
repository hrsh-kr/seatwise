# Seatwise design notes

Design principles: provenance first, one status colour per card, plain words.

**Principles**
- Light page (`#f4f7fb`), white 16 px cards, slate text, no glass, glow or purple gradients. A dark theme is provided as well (follows the system setting, toggle in the header, choice remembered). Band colours are re-tuned for contrast on dark cards, and the map tiles are inverted and muted.
- Hanken Grotesk (variable, self-hosted from `static/fonts`, OFL) with tabular numerals; big numerals are the main character of each card.
- Hero card with a soft wash of the current band colour at the top (seats green, standing amber, crowded red); the colour cross-fades over 700 ms.
- Provenance on every number: small hairline pill, "Modelled, 19 weekdays of October 2026 e-tickets, high confidence".
- Voice: lead with the answer, one sentence, say "not enough tickets to say" plainly, no exclamation marks, emoji or jargon.
- Motion explains: the number settles once, bars rise in sequence, `prefers-reduced-motion` turns it all off.
- Mobile first (390 px): map on top, content card below, floating pill navigation; a real two-column layout from 900 px.
- 44 px tap targets, keyboard-focusable cards and heatmap cells, text labels beside every colour.

**Seatwise additions**
- Crowding badge (meter bars plus label) and a per-stretch strip along each ride.
- "How full this bus is through the day" chart with your boarding time marked; tap a bar to leave then.
- Operator heatmap: routes by half-hour, shaded by share of full capacity.
- Assumptions drawer with the ticket-share slider.

**Added since:** English and Hindi (toggle in the header; Devanagari falls back to the system font, stop and route names stay in English), shareable links (the page state lives in the URL hash), examples, loading skeletons and error states with retry, a skip link, a values table behind each chart, 44 px targets and text labels beside every colour.
