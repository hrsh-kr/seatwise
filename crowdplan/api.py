"""HTTP API + demo UI.   uvicorn crowdplan.api:app --port 8000"""
from __future__ import annotations
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from . import config as C
from . import model as M
from .planner import Planner, daytype_of, hhmm

S = {}


@asynccontextmanager
async def lifespan(app):
    S["pl"] = Planner()
    yield


app = FastAPI(title="Seatwise: crowdedness-aware Delhi bus journey planner", version="0.1", lifespan=lifespan,
              description="Journeys with modelled on-board crowding. Crowding comes from a pooled gamma-Poisson model of "
                          "sampled e-ticket data (October 2026). Estimates are statistical, not live counts.")


def _hm(t: str):
    try:
        h, m = t.split(":"); h, m = int(h), int(m)
        assert 0 <= h < 24 and 0 <= m < 60
        return h, m
    except Exception:
        raise HTTPException(400, "time must be HH:MM (00:00 to 23:59)")


def _band(t: str) -> int:
    h, m = _hm(t)
    return (h * 2 + m // 30) % 48


@app.get("/health")
def health():
    pl = S["pl"]
    return {"ok": True, "routes": len(pl.net.patterns), "route_daytypes_modelled": len(pl.model), **pl.meta}


@app.get("/stops")
def stops(q: str = Query(..., min_length=2), limit: int = 8):
    return S["pl"].search_stops(q, limit)


@app.get("/journeys")
def journeys(from_: str = Query(..., alias="from", description="stop name or 'lat,lon'"),
             to: str = Query(..., description="stop name or 'lat,lon'"),
             depart: str = Query("2026-10-20T18:00", description="ISO local time, e.g. 2026-10-20T18:00"),
             priority: str = Query("balanced", pattern="^(fastest|balanced|comfortable)$"),
             p: float = Query(M.P0, ge=0.005, le=0.3, description="assumed e-ticket share of all riders (sensitivity)"),
             metro: bool = Query(False, description="also route over the metro (routed, not crowding-modelled)")):
    try:
        d = datetime.fromisoformat(depart)
        return S["pl"].plan(from_, to, d, priority, p_user=p, use_metro=metro)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/routes/{rd}/crowding")
def route_crowding(rd: str, daytype: str = "weekday", time: str = "18:00", p: float = M.P0):
    pl = S["pl"]; rd = rd.upper()
    pat = pl.net.patterns.get(rd); m = pl.model.get((rd, daytype))
    if pat is None or m is None:
        raise HTTPException(404, "route or day type not modelled")
    b = _band(time); v = M.view(m, b, np.arange(pat.n - 1), p); out = []
    for s in range(pat.n - 1):
        ok = bool(v["ok"][s])
        out.append({"from": pat.names[s], "to": pat.names[s + 1], "level": int(v["level"][s]) if ok else None,
                    "label": C.LEVEL_LABELS[int(v["level"][s])] if ok else "No data",
                    "load_p50": round(float(v["p50"][s])) if ok else None,
                    "load_90pct_interval": [round(float(v["lo"][s])), round(float(v["hi"][s]))] if ok else None,
                    "p_crowded": round(float(v["p_crowded"][s]), 2) if ok else None,
                    "confidence": ["low", "medium", "high"][int(v["conf"][s])] if ok else None})
    return {"route": rd, "daytype": daytype, "departure_band": f"{b//2:02d}:{(b%2)*30:02d}", "assumed_sampling_fraction": v["p_eff"],
            "seats": pat.seats, "crush": pat.crush, "stretches": out}


@app.get("/operators/overloaded")
def overloaded(daytype: str = "weekday", time: str = "18:00", top: int = 20, min_confidence: int = 1, p: float = M.P0):
    pl = S["pl"]; b = _band(time); rows = []
    for (rd, dt), m in pl.model.items():
        if dt != daytype:
            continue
        sel = np.flatnonzero(m["active"][b] & (m["conf"][b] >= min_confidence))
        if len(sel) == 0:
            continue
        v = M.view(m, b, sel, p)
        k = int(np.argmax(v["p_crowded"] * 1e6 + v["lo"]))
        s = int(sel[k]); pat = pl.net.patterns[rd]
        rows.append({"route": rd, "from": pat.names[s], "to": pat.names[s + 1], "load_p50": round(float(v["p50"][k])),
                     "load_90pct_interval": [round(float(v["lo"][k])), round(float(v["hi"][k]))],
                     "capacity_crush": m["crush"], "load_over_crush": round(float(v["p50"][k]) / m["crush"], 2),
                     "p_crowded": round(float(v["p_crowded"][k]), 2),
                     "crowded_stretches": int((v["level"] == 2).sum())})
    rows.sort(key=lambda r: (-r["p_crowded"], -r["load_90pct_interval"][0], -r["load_p50"]))
    return {"daytype": daytype, "departure_band": f"{b//2:02d}:{(b%2)*30:02d}", "assumed_sampling_fraction": p, "rows": rows[:top]}


@app.get("/routes/{rd}/profile")
def route_profile(rd: str, board: int, alight: int, daytype: str = "weekday", p: float = M.P0):
    """How busy the ride from stop index `board` to `alight` is, for trips boarding through the day."""
    pl = S["pl"]; rd = rd.upper()
    pat = pl.net.patterns.get(rd); m = pl.model.get((rd, daytype))
    if pat is None or m is None or not (0 <= board < alight < pat.n):
        raise HTTPException(404, "route, day type or stop range not modelled")
    idx = np.arange(board, alight); out = []
    for b in range(10, 46):
        v = M.view(m, b, idx, p)
        ok = v["ok"]
        t = (b * 1800 + pat.off_med[board]) % 86400
        if ok.sum() < max(1, len(idx) // 2):
            out.append({"time": hhmm(t), "load": None, "level": None})
            continue
        j = int(np.argmax(np.where(ok, v["p50"], -1)))
        out.append({"time": hhmm(t), "load": round(float(v["p50"][j])), "level": int(v["level"][j]),
                    "p_crowded": round(float(v["p_crowded"][j]), 2), "confidence": int(v["conf"][ok].min())})
    return {"route": rd, "daytype": daytype, "seats": pat.seats, "crush": pat.crush, "assumed_sampling_fraction": p,
            "points": out, "note": "Busiest stretch of the ride; x axis is when the bus reaches your boarding stop."}


@app.get("/operators/heatmap")
def heatmap(daytype: str = "weekday", top: int = 24, p: float = M.P0):
    """Routes x half-hours: busiest-stretch load as a share of crush capacity."""
    pl = S["pl"]; cand = []
    for (rd, dt), m in pl.model.items():
        if dt != daytype:
            continue
        pe = max(p, m["p_min"]); mean = (m["a"] / m["b"]) / pe / m["crush"]
        ok = m["active"] & (m["conf"] >= 1)
        sc = np.where(ok, mean, 0).max(1)           # per band
        if sc.max() <= 0:
            continue
        cand.append((float((sc >= 0.8).sum() * 10 + sc.max()), rd))
    cand.sort(reverse=True); rows = []
    for _, rd in cand[:top]:
        m = pl.model[(rd, daytype)]; pat = pl.net.patterns[rd]; cells = []
        for b in range(10, 46):
            sel = np.flatnonzero(m["active"][b] & (m["conf"][b] >= 1))
            if len(sel) == 0:
                cells.append(None); continue
            v = M.view(m, b, sel, p)
            top3 = np.sort(v["p50"])[-3:]
            cells.append(round(float(top3.mean()) / m["crush"], 2))
        rows.append({"route": rd, "from": pat.names[0], "to": pat.names[-1], "cells": cells})
    return {"daytype": daytype, "bands": [f"{b//2:02d}:{(b%2)*30:02d}" for b in range(10, 46)], "assumed_sampling_fraction": p,
            "note": "Value = average of the three busiest stretches of a trip departing at that time, as a share of crush capacity (1.0 = full).", "rows": rows}


@app.get("/validation")
def validation():
    f = Path("outputs/model/validation.json")
    return json.loads(f.read_text()) if f.exists() else {}



def _sec(t: str) -> float:
    h, m = _hm(t)
    return h * 3600 + m * 60


@app.get("/journeys/window")
def journeys_window(from_: str = Query(..., alias="from"), to: str = Query(...), date: str = "2026-10-20",
                    start: str = "16:30", end: str = "19:30", step: int = Query(30, ge=10, le=60),
                    priority: str = Query("balanced", pattern="^(fastest|balanced|comfortable)$"),
                    p: float = Query(M.P0, ge=0.005, le=0.3), metro: bool = False):
    """When is the best time to leave between `start` and `end`? One planned trip per step, compared."""
    try:
        d0 = datetime.fromisoformat(f"{date}T{start}"); d1 = datetime.fromisoformat(f"{date}T{end}")
    except ValueError:
        raise HTTPException(400, "bad date or time")
    if (d1 - d0).total_seconds() > 6 * 3600:
        raise HTTPException(400, "window longer than 6 hours")
    try:
        return S["pl"].window(from_, to, d0, d1, step, priority, p, metro)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/routes/{rd}/why")
def why(rd: str, board: int, alight: int, time: str = "18:00", daytype: str = "weekday", p: float = M.P0):
    """What stands behind one estimate: tickets, trips, assumptions, and how sure we are."""
    pl = S["pl"]; rd = rd.upper()
    pat = pl.net.patterns.get(rd); m = pl.model.get((rd, daytype))
    if pat is None or m is None or not (0 <= board < alight < pat.n):
        raise HTTPException(404, "route, day type or stop range not modelled")
    band = int(((_sec(time) - pat.off_med[board]) // 1800) % 48)
    idx = np.arange(board, alight); v = M.view(m, band, idx, p)
    ok = v["ok"]
    if not ok.any():
        return {"route": rd, "available": False, "reason": "Too few tickets near this time to estimate."}
    j = int(np.argmax(np.where(ok, v["p50"], -1))); s = int(idx[j])
    ce = float(m["ce"][band, s]); trips_day = float(m["n0"][band, s]); mean_sampled = float(m["a"][band, s] / m["b"][band, s])
    conf = int(v["conf"][j])
    floor = m["p_min"] > p
    return {"route": rd, "available": True, "daytype": daytype, "departure_band": f"{band//2:02d}:{(band%2)*30:02d}",
            "stretch": {"from": pat.names[s], "to": pat.names[s + 1]},
            "estimate": {"load_p50": round(float(v["p50"][j])), "load_90pct_interval": [round(float(v["lo"][j])), round(float(v["hi"][j]))],
                         "p_crowded": round(float(v["p_crowded"][j]), 2), "level": C.LEVEL_LABELS[int(v["level"][j])]},
            "evidence": {"pooled_passenger_stretches": round(ce), "approx_tickets_behind_it": round(ce / 12.35),
                         "bus_trips_per_day_in_band": round(trips_day, 1), "days": m["days"],
                         "sampled_passengers_per_bus": round(mean_sampled, 2),
                         "confidence": ["low", "medium", "high"][conf],
                         "confidence_reason": "Fewer than 25 pooled passenger-stretches" if conf == 0 else ("25 to 80 pooled passenger-stretches" if conf == 1 else "More than 80 pooled passenger-stretches")},
            "assumptions": {"assumed_ticket_share": p, "share_used": round(float(v["p_eff"]), 4),
                            "capacity_floor_applied": bool(floor), "seats": pat.seats, "crush_capacity": pat.crush,
                            "standing_room_limit": round(C.STANDING_FRAC * pat.crush)},
            "formula": "load = sampled passengers per bus / share of riders who appear as e-tickets"}


@app.get("/operators/extra-bus")
def extra_bus(daytype: str = "weekday", time: str = "18:00", top: int = 15, p: float = M.P0):
    """Where would one more trip in this half-hour relieve the most crowding? Assumes demand stays and is shared evenly."""
    pl = S["pl"]; b = _band(time); rows = []
    for (rd, dt), m in pl.model.items():
        if dt != daytype:
            continue
        n = float(m["n0"][b].max())
        if n < 1:
            continue
        sel = np.flatnonzero(m["active"][b] & (m["conf"][b] >= 1))
        if len(sel) == 0:
            continue
        v = M.view(m, b, sel, p); thr = C.STANDING_FRAC * m["crush"]
        load = np.where(v["ok"], v["p50"], 0.0)
        before = float(np.maximum(0, load - thr).sum())
        if before <= 0:
            continue
        after = float(np.maximum(0, load * n / (n + 1) - thr).sum())
        rows.append({"route": rd, "trips_in_band_per_day": round(n, 1), "crowded_stretches": int((load > thr).sum()),
                     "passenger_stretches_over_limit_per_trip": round(before),
                     "relief_per_extra_trip": round(before * n - after * (n + 1)),
                     "busiest": pl.net.patterns[rd].names[int(sel[int(np.argmax(load))])]})
    rows.sort(key=lambda r: -r["relief_per_extra_trip"])
    return {"daytype": daytype, "departure_band": f"{b//2:02d}:{(b%2)*30:02d}", "assumed_sampling_fraction": p,
            "note": "Relief = riders-times-stretches above the standing-room limit removed per day by adding one trip, if demand stays and is shared evenly. A screening estimate, not a timetable.",
            "rows": rows[:top]}


def _occ_status(load, seats, crush):
    if load <= 0.05 * seats: return "EMPTY"
    if load <= 0.6 * seats: return "MANY_SEATS_AVAILABLE"
    if load <= seats: return "FEW_SEATS_AVAILABLE"
    if load <= C.STANDING_FRAC * crush: return "STANDING_ROOM_ONLY"
    if load <= crush: return "CRUSHED_STANDING_ROOM_ONLY"
    return "FULL"


def _occupancy(time: str, daytype: str, p: float, limit: int):
    pl = S["pl"]; t = _sec(time); out = []
    for rd, pat in pl.net.patterns.items():
        m = pl.model.get((rd, daytype))
        if m is None:
            continue
        starts, offs = pl._trips(pat, daytype)
        act = np.flatnonzero((starts <= t) & (t <= starts + offs[:, -1]))
        if len(act) == 0:
            continue
        key = "weekday" if daytype == "weekday" else "weekend"
        ids = pat.trip_ids.get(key)
        ss = np.array([max(0, min(pat.n - 2, int(np.searchsorted(offs[k], t - starts[k], side="right")) - 1)) for k in act])
        bands = ((starts[act] // 1800) % 48).astype(int)
        v = M.view(m, bands, ss, p)
        for n_, k in enumerate(act):
            if not v["ok"][n_]:
                continue
            load = float(v["p50"][n_]); s = int(ss[n_])
            out.append({"trip_id": str(ids[k]) if ids is not None else f"{rd}-{k}", "route": rd, "stop_sequence": s,
                        "next_stop": pat.names[s + 1], "lat": float(pat.lat[s]), "lon": float(pat.lon[s]),
                        "occupancy_status": _occ_status(load, pat.seats, pat.crush),
                        "occupancy_percentage": int(round(100 * load / pat.crush)), "predicted_load": round(load),
                        "confidence": ["low", "medium", "high"][int(v["conf"][n_])]})
            if len(out) >= limit:
                return out
    return out


@app.get("/feeds/occupancy.json")
def occupancy_json(time: str = "18:00", daytype: str = "weekday", p: float = M.P0, limit: int = Query(3000, le=20000)):
    """Predicted occupancy for every scheduled trip in service at `time` (a forecast, not a live count)."""
    return {"kind": "forecast", "daytype": daytype, "time": time, "assumed_sampling_fraction": p,
            "note": "Built from October 2026 e-tickets; fields follow GTFS-Realtime VehiclePosition occupancy_status.",
            "entities": _occupancy(time, daytype, p, limit)}


@app.get("/feeds/occupancy.pb")
def occupancy_pb(time: str = "18:00", daytype: str = "weekday", p: float = M.P0, limit: int = Query(3000, le=20000)):
    """The same forecast as a GTFS-Realtime FeedMessage (VehiclePosition with occupancy_status)."""
    try:
        from google.transit import gtfs_realtime_pb2 as g
    except ImportError:
        raise HTTPException(501, "install gtfs-realtime-bindings")
    from fastapi.responses import Response
    msg = g.FeedMessage(); msg.header.gtfs_realtime_version = "2.0"
    msg.header.incrementality = g.FeedHeader.FULL_DATASET; msg.header.timestamp = int(datetime(2026, 10, 20).timestamp()) + int(_sec(time))
    pl = S["pl"]
    for e in _occupancy(time, daytype, p, limit):
        ent = msg.entity.add(); ent.id = e["trip_id"]; vp = ent.vehicle
        vp.trip.trip_id = e["trip_id"]; vp.trip.route_id = str(pl.net.patterns[e["route"]].route_id)
        vp.position.latitude = e["lat"]; vp.position.longitude = e["lon"]; vp.current_stop_sequence = e["stop_sequence"]
        vp.occupancy_status = getattr(g.VehiclePosition, e["occupancy_status"]); vp.occupancy_percentage = max(0, e["occupancy_percentage"])
    return Response(msg.SerializeToString(), media_type="application/x-protobuf")


STATIC = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
