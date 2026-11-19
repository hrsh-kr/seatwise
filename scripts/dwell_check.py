"""Independent check of the ticket-based crowding signal against GPS dwell time (one weekday).

Idea: a bus stands longer at stops where more people board. If the sampled e-ticket boardings per bus at a stop
track the dwell time of buses at that stop (measured from GPS, not from tickets), the tickets are measuring real demand.
Usage: python scripts/dwell_check.py 2026_10_14
"""
import json, sqlite3, sys
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import spearmanr
sys.path.insert(0, ".")
from crowdplan.prep import load_network
from crowdplan.planner import _xy

day = sys.argv[1] if len(sys.argv) > 1 else "2026_10_14"
date = day.replace("_", "-")
net = load_network("data/gtfs")
rid2rd = {p.route_id: rd for rd, p in net.patterns.items()}
con = sqlite3.connect(f"data/gps/bus_movements_{day}.db")
q = ("select vehicle_id, cast(route_id as integer) rid, cast(lat as real) lat, cast(lng as real) lng, "
     "cast(timestamp as integer) ts from vehicle_feed where speed < 1 and route_id is not null")
parts, n = [], 0
for ch in pd.read_sql(q, con, chunksize=1_000_000):
    ch["rd"] = ch.rid.astype(str).map(rid2rd); ch = ch.dropna(subset=["rd"]); parts.append(ch); n += len(ch)
gps = pd.concat(parts); print("stationary GPS points on known routes:", len(gps))

events = []
for rd, g in gps.groupby("rd"):
    p = net.patterns[rd]
    d, i = cKDTree(_xy(p.lat, p.lon)).query(_xy(g.lat.to_numpy(), g.lng.to_numpy()))
    g = g.assign(stop=i, dist=d)[d <= 40].sort_values(["vehicle_id", "stop", "ts"])
    if g.empty:
        continue
    new = (g.vehicle_id != g.vehicle_id.shift()) | (g.stop != g.stop.shift()) | (g.ts.diff() > 90)
    g["ev"] = new.cumsum()
    e = g.groupby("ev").agg(vehicle=("vehicle_id", "first"), stop=("stop", "first"), t0=("ts", "min"), t1=("ts", "max"), n=("ts", "size"))
    e["rd"] = rd; e["dwell"] = e.t1 - e.t0 + 5
    events.append(e[e.n >= 2])
ev = pd.concat(events)
ev = ev[(ev.dwell >= 5) & (ev.dwell <= 180)]     # drop depot-style stands
ev = ev[ev.apply(lambda r: 2 <= r.stop <= net.patterns[r.rd].n - 3, axis=1)]   # drop terminals
per = ev.groupby(["rd", "stop"]).agg(events=("dwell", "size"), dwell_s=("dwell", "mean")).reset_index()

tk = pd.read_pickle("outputs/prep_full/tickets_resolved.pkl"); tk["date"] = pd.to_datetime(tk.date)
tk = tk[tk.date == date]
board = tk.groupby(["rd", "b_idx"]).pc.sum().rename("tix").reset_index().rename(columns={"b_idx": "stop"})
m = per.merge(board, on=["rd", "stop"], how="left").fillna({"tix": 0})
m = m[m.events >= 8]; m["tix_per_event"] = m.tix / m.events
# within-route comparison removes route-level differences (signals, road type, operator)
m["tix_r"] = m.groupby("rd").tix_per_event.rank(pct=True); m["dwell_r"] = m.groupby("rd").dwell_s.rank(pct=True)
cnt = m.groupby("rd").size(); m = m[m.rd.isin(cnt[cnt >= 10].index)]
rho, pv = spearmanr(m.tix_r, m.dwell_r)
per_route = m.groupby("rd").apply(lambda g: spearmanr(g.tix_per_event, g.dwell_s)[0], include_groups=False).dropna()
print("routes:", len(per_route), "median within-route rho: %.3f; share positive: %.2f" % (per_route.median(), (per_route > 0).mean()))
m["bin"] = pd.qcut(m.tix_per_event.rank(method="first"), 5, labels=False)
tab = m.groupby("bin").agg(tickets_per_bus_stop=("tix_per_event", "mean"), mean_dwell_s=("dwell_s", "mean"), n=("rd", "size")).round(2)
print(tab.to_string()); print(f"Spearman rho={rho:.3f} (p={pv:.1e}) over {len(m)} route-stops")
out = {"median_within_route_rho": round(float(per_route.median()), 3), "share_routes_positive": round(float((per_route > 0).mean()), 3), "routes": int(len(per_route)), "date": date, "route_stops": int(len(m)), "spearman_rho": round(float(rho), 3), "p_value": float(pv),
       "quintiles": tab.reset_index().to_dict("records")}
json.dump(out, open("outputs/model/dwell_check.json", "w"), indent=2)
