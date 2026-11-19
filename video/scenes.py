"""What happens on screen, anchored to words in each voice note (see build.py). Selectors refer to the deck and the app."""
import asyncio

DECK = "http://127.0.0.1:8765/video/slides/deck.html"
APP = "http://localhost:8000/"


def E(*steps):
    """A sequence of small on-screen steps, run when the anchored phrase is spoken."""
    async def run(r):
        for s in steps:
            k = s[0]
            if k == "clear": await r.clear()
            elif k == "box": await r.box(s[1], *(s[2:3] or [0]), *(s[3:4] or [10]))
            elif k == "mark": await r.mark(s[1], *(s[2:3] or [0]), *(s[3:4] or [4]))
            elif k == "click": await r.click(s[1], *(s[2:3] or [0]))
            elif k == "point": await r.point(s[1], *(s[2:3] or [0]))
            elif k == "wait": await r.wait(s[1], s[2] if len(s) > 2 else 1)
            elif k == "sleep": await asyncio.sleep(s[1])
            elif k == "slider": await r.slider(s[1], s[2], s[3])
            elif k == "do": await s[1](r)
    return run


def slide(n):
    async def pre(r):
        f = r.frame()
        if f and f.url.startswith(DECK):
            await r.js(f"()=>{{location.hash='#s{n}'}}"); await asyncio.sleep(0.3)
        else:
            await r.go(f"{DECK}#s{n}")
    return pre


async def app_fresh(r):
    await r.go(APP + "?demo=1")
    await r.wait("#form")


async def nth_card(r, which):
    """Index of the option card that is the fastest or the 50 minute one, found from the screen."""
    if which == "fastest":
        return await r.js("()=>[...document.querySelectorAll('.opt')].findIndex(o=>/Fastest/.test(o.querySelector('.pills').textContent))")
    return await r.js("()=>[...document.querySelectorAll('.opt')].findIndex(o=>+o.querySelector('.num').dataset.to===50)")


async def box_big(r, which):
    await r.clear(); i = await nth_card(r, which); i = 0 if i < 0 else i
    await r.box(".opt .big", i, 12)


async def expand_fastest(r):
    await r.clear(); i = await nth_card(r, "fastest"); i = 0 if i < 0 else i
    await r.click(".opt .hero", i, fx=.5, fy=.5)
    await asyncio.sleep(0.5)
    await r.box(".opt[aria-expanded=true] .strip", 0, 10)


async def click_red_cell(r):
    await r.clear()
    sel = "#heat td.c.l2.hi" if await r.js("()=>__d.exists('#heat td.c.l2.hi')") else "#heat td.c.l2"
    await r.click(sel, 0); await asyncio.sleep(0.2); await r.box(sel, 0, 6)


async def show_phone(r):
    await r.page.evaluate("phone(true)")
    await asyncio.sleep(0.8)


async def end_phone(r):
    await r.page.evaluate("phone(false)")
    await asyncio.sleep(0.8)
    await r.click("nav.tabs button[data-go=about]")
    await r.wait("#stats .stat", 6)


async def fast(r, sel):
    await r.js("([s])=>{__d.moveTo(s);__d.ripple(s);return __d.click(s)}", [sel])


async def theme_dark(r):
    await fast(r, "#lang"); await asyncio.sleep(0.5)
    await fast(r, "#theme"); await asyncio.sleep(1.1)
    await fast(r, "#theme"); await asyncio.sleep(0.3)


async def theme_light(r):
    await r.click("#theme")


SCENES = [
    {"id": "01", "gap": 0.4, "pre": slide(1), "events": [
        ("Seatwise which is", E(("mark", "#s1 h1", 0, 8))),
        ("Problem 2", E(("clear",), ("box", "#s1 .meta", 0, 12))),
        ("how crowded Delhi buses", E(("clear",), ("box", "#s1 .bus", 0, 12))),
        ("next to the journey time", E(("clear",), ("box", "#s1 .badge", 0, 8), ("box", "#s1 .badge", 1, 8), ("box", "#s1 .badge", 2, 8)))]},
    {"id": "02", "gap": 0.7, "pre": slide(2), "events": [
        ("rank trips by time", E(("clear",), ("box", "#s2 .panel", 0, 6))),
        ("how full the bus", E(("clear",), ("box", "#s2 .panel", 1, 6))),
        ("two studies here", E(("clear",), ("box", "#s2 .q", 0, 6), ("box", "#s2 .q", 1, 6))),
        ("buses in Boston", E(("clear",), ("mark", "#s2 .cite b", 0, 4))),
        ("a metro system", E(("clear",), ("mark", "#s2 .cite b", 1, 4))),
        ("real cost for passengers", E(("clear",), ("box", "#s2 .big", 0, 14)))]},
    {"id": "03", "gap": 0.7, "pre": slide(3), "events": [
        ("The chart shows", E(("clear",), ("box", "#c3", 0, 8))),
        ("morning peak", E(("clear",), ("mark", "#c3 text.lab", 0, 6))),
        ("evening peak", E(("mark", "#c3 text.lab", 1, 6))),
        ("figures on the right", E(("clear",), ("box", "#s3 .tiles", 0, 8))),
        ("about one ticket per bus trip", E(("clear",), ("box", "#s3 .tile", 1, 6))),
        ("have no vehicle number", E(("clear",), ("box", "#s3 .tile", 2, 6))),
        ("stop names do not match", E(("clear",), ("box", "#s3 .tile", 3, 6)))]},
    {"id": "04", "gap": 0.7, "pre": slide(4), "events": [
        ("four steps", E(("clear",), ("box", "#s4 .steps", 0, 8))),
        ("first step", E(("clear",), ("box", "#s4 .step", 0, 6), ("box", "#c4", 0, 8))),
        ("match exactly", E(("clear",), ("box", "#c4 svg rect", 0, 6))),
        ("end up on a route", E(("clear",), ("mark", "#c4 p", 0, 6))),
        ("later steps scale", E(("clear",), ("box", "#s4 .step", 2, 6), ("box", "#s4 .step", 3, 6)))]},
    {"id": "05", "gap": 1.8, "pre": app_fresh, "events": [
        ("plan a trip", E(("box", "#form", 0, 8))),
        ("Seatwise lists several options", E(("clear",), ("click", "#go"), ("wait", ".opt", 3))),
        ("shows the journey time", E(("clear",), ("box", ".opt .big", 0, 12))),
        ("how full the ride", E(("clear",), ("mark", ".opt .badge", 0, 6)))]},
    {"id": "06", "gap": 0.6, "pre": lambda r: asyncio.sleep(0), "events": [
        ("The fastest option", lambda r: box_big(r, "fastest")),
        ("Another option takes", lambda r: box_big(r, "other")),
        ("coloured strip", expand_fastest),
        ("map colours the route", E(("clear",), ("box", "#map", 0, -6)))]},
    {"id": "07", "gap": 0.6, "pre": lambda r: asyncio.sleep(0), "events": [
        ("This chart shows", E(("clear",), ("box", ".opt[aria-expanded=true] .chart", 0, 8))),
        ("boarding time is marked", E(("clear",), ("box", ".opt[aria-expanded=true] .chart text.you", 0, 12))),
        ("Clicking a bar", E(("clear",), ("click", '.opt[aria-expanded=true] rect.bar[data-time^="19"]'), ("sleep", 1.0)))]},
    {"id": "08", "gap": 0.6, "pre": lambda r: asyncio.sleep(0), "events": [
        ("compare departure times", E(("clear",), ("click", "#winbtn"), ("wait", "#wincontent .wbar", 5), ("box", "#wincontent", 0, 8))),
        ("marks the best one", E(("clear",), ("box", "#wincontent g.wbar rect[stroke]", 0, 10)))]},
    {"id": "09", "gap": 0.6, "pre": lambda r: asyncio.sleep(0), "events": [
        ("Each estimate has a panel", E(("clear",), ("click", ".opt[aria-expanded=true] button.why"), ("wait", ".opt[aria-expanded=true] .whybox li", 3))),
        ("number of tickets", E(("clear",), ("mark", ".opt[aria-expanded=true] .whybox li", 1, 5))),
        ("number of buses", E(("clear",), ("mark", ".opt[aria-expanded=true] .whybox li", 2, 5))),
        ("share of riders", E(("clear",), ("mark", ".opt[aria-expanded=true] .whybox li", 4, 5)))]},
    {"id": "10", "gap": 0.6, "pre": lambda r: asyncio.sleep(0), "events": [
        ("That share is an assumption", E(("clear",), ("click", "#edit"), ("sleep", 0.4), ("click", "details.assume summary"), ("box", "#pf", 0, 14))),
        ("It can be adjusted here", E(("clear",), ("slider", "#pf", 3.5, 2.0), ("wait", ".opt .sens", 1))),
        ("line under each option", E(("clear",), ("mark", ".opt .sens", 0, 6))),
        ("capacity limit keeps", E(("clear",), ("box", ".opt .sens", 0, 8)))]},
    {"id": "11", "gap": 0.8, "pre": lambda r: r.click("nav.tabs button[data-go=ops]"), "events": [
        ("operators tab", E(("clear",), ("box", "nav.tabs button[data-go=ops]", 0, 6), ("wait", "#heat tbody tr", 10))),
        ("heatmap shows the busiest", E(("clear",), ("box", "#heat", 0, 8))),
        ("Green means", E(("clear",), ("mark", "#heat .legend span", 0, 6))),
        ("dark red", E(("clear",), ("mark", "#heat .legend span", 3, 6))),
        ("over capacity", click_red_cell)]},
    {"id": "12", "gap": 0.6, "pre": lambda r: asyncio.sleep(0), "events": [
        ("Below the heatmap", E(("clear",), ("box", "#extrah", 0, 10))),
        ("where one extra trip", E(("clear",), ("box", "#extra li", 0, 8))),
        ("assumes the demand stays", E(("clear",), ("mark", "#extra li .sub", 0, 6)))]},
    {"id": "13", "gap": 0.6, "tail": 3.2, "pre": lambda r: r.click("nav.tabs button[data-go=plan]"), "events": [
        ("English and Hindi", E(("clear",), ("click", "#lang"), ("sleep", 1.0))),
        ("light and dark", theme_dark),
        ("The layout is made", lambda r: show_phone(r))]},
    {"id": "14", "gap": 0.6, "pre": end_phone, "events": [
        ("Everything is also available", E(("clear",), ("box", ".links", 0, 10))),
        ("GTFS Realtime", E(("clear",), ("mark", ".links li", 2, 6)))]},
    {"id": "15", "gap": 1.8, "pre": slide(5), "events": [
        ("On the left", E(("clear",), ("box", "#c5a", 0, 8))),
        ("actual ticket counts", E(("clear",), ("box", "#c5a svg rect", 1, 6))),
        ("our target was eighty", E(("clear",), ("mark", '#c5a text[fill="#b3261e"]', 0, 6))),
        ("On the right", E(("clear",), ("box", "#c5b", 0, 8))),
        ("morning and evening peaks", E(("clear",), ("box", "#c5b circle", 0, 16), ("box", "#c5b circle", 1, 16))),
        ("limits are listed", E(("clear",), ("box", "#s5 .limits", 0, 8))),
        ("address is at the bottom", E(("clear",), ("box", "#s5 .repo", 0, 10)))]},
]
