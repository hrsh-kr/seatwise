"""Crowd-aware journey planner: walk -> bus/metro (-> change -> bus/metro) -> walk, on the static timetables.

Every bus ride is annotated with the modelled crowding of the stretches the passenger will sit through (metro legs
are routed but not crowding-modelled). Options are ranked by generalised cost = minutes (incl. delay from leaving
later) + comfort_weight * crowd-minutes. Stops are matched by position (KD-tree), so changes work between bus
stops that carry different names and between a bus stop and a metro station."""
from __future__ import annotations
import pickle
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from rapidfuzz import process, fuzz
from . import config as C
from . import model as M
from .gtfs import haversine_m, norm
from .prep import load_network, ABBR

NB = 48
BAND_S = 1800
WALK_MS = C.WALK_KMH / 3.6
SHIFTS_MIN = (0, 20, 40)
SENS_P = (0.02, 0.035, 0.06)
TRANSFER_RADIUS_M = 250
LAT0 = 28.6
METRO_COLOURS = {"R": "Red", "Y": "Yellow", "B": "Blue", "G": "Green", "V": "Violet", "P": "Pink", "M": "Magenta",
                 "O": "Airport Express", "A": "Aqua", "GR": "Grey"}


def daytype_of(d: datetime) -> str:
    return "weekday" if d.weekday() < 5 else ("saturday" if d.weekday() == 5 else "sunday")


def hhmm(sec: float) -> str:
    sec = int(sec)
    return f"{(sec // 3600) % 24:02d}:{(sec % 3600) // 60:02d}"


def _xy(lat, lon):
    lat = np.asarray(lat, float); lon = np.asarray(lon, float)
    return np.c_[(lon - 77.2) * 111320 * np.cos(np.radians(LAT0)), (lat - LAT0) * 110540]


class Planner:
    def __init__(self, gtfs_dir="data/gtfs", model_path="outputs/model/model.pkl", metro_dir="data/metro/gtfs"):
        self.net = load_network(gtfs_dir)
        with open(model_path, "rb") as f:
            blob = pickle.load(f)
        self.model = blob["model"]
        self.meta = {k: v for k, v in blob.items() if k != "model"}
        self.pats = dict(self.net.patterns)
        self.has_metro = False
        if Path(metro_dir).exists():
            try:
                mn = load_network(metro_dir, cache="outputs/network_metro.pkl")
                for rd, p in mn.patterns.items():
                    key = "METRO-" + rd
                    p.mode, p.rd = "metro", key
                    self.pats[key] = p
                self.has_metro = True
            except Exception as e:  # metro is an optional extra
                print("metro not loaded:", e)
        rds, idx, lat, lon = [], [], [], []
        self._off = {}
        for rd, p in self.pats.items():
            self._off[rd] = len(rds)
            rds += [rd] * p.n; idx += list(range(p.n)); lat += list(p.lat); lon += list(p.lon)
        self._g_rd, self._g_i = rds, np.array(idx)
        self._g_lat, self._g_lon = np.array(lat), np.array(lon)
        self.tree = cKDTree(_xy(self._g_lat, self._g_lon))
        a = self.net.all_stops
        self._names = [str(x) for x in a.stop_name]
        self._norm_names = [norm(x) for x in self._names]
        self._name_xy = {}
        for n, nn, la, lo in zip(self._names, self._norm_names, a.stop_lat, a.stop_lon):
            self._name_xy.setdefault(self._ex(nn), (n, float(la), float(lo)))
        for rd, p in self.pats.items():                      # metro stations are searchable places too
            if p.mode == "metro":
                for n, la, lo in zip(p.names, p.lat, p.lon):
                    self._name_xy.setdefault(self._ex(norm(n)), (str(n), float(la), float(lo)))
        self._arr, self._nearc = {}, {}

    # ---------- stops ----------
    @staticmethod
    def _ex(nn: str) -> str:
        """Expand abbreviations so 'dwarka sec 21' and 'dwarka sector 21' meet."""
        return " ".join(ABBR.get(t, t) for t in nn.split())

    def search_stops(self, q: str, k=8):
        import re
        q = self._ex(norm(q))
        if not q:
            return []
        nums = set(re.findall(r"\d+", q))
        hits = [(nn, v) for nn, v in self._name_xy.items() if q in nn]
        hits.sort(key=lambda h: (h[0] != q, not h[0].startswith(q), len(h[0])))      # exact, then prefix, then shortest
        res = [v for _, v in hits[:k]]
        if len(res) < k:
            for nn, score, _ in process.extract(q, list(self._name_xy), scorer=fuzz.WRatio, limit=k * 3):
                if score >= 85 and set(re.findall(r"\d+", nn)) == nums:      # typos are fine; a different number is not
                    t = self._name_xy[nn]
                    if t not in res:
                        res.append(t)
        return [{"name": str(a), "lat": float(b), "lon": float(c)} for a, b, c in res[:k]]

    def resolve_point(self, s: str):
        s = s.strip()
        try:
            la, lo = [float(x) for x in s.split(",")]
            return la, lo, f"{la:.4f},{lo:.4f}"
        except ValueError:
            pass
        r = self.search_stops(s, 1)
        if not r:
            raise ValueError(f"unknown place: {s}")
        return r[0]["lat"], r[0]["lon"], r[0]["name"]

    # ---------- timetable ----------
    def _trips(self, p, dt):
        key = "weekday" if dt == "weekday" else "weekend"
        return p.trips.get(key) or next(iter(p.trips.values()))

    def _arrivals(self, rd, dt, i):
        key = (rd, dt, i)
        if key not in self._arr:
            starts, offs = self._trips(self.pats[rd], dt)
            self._arr[key] = starts + offs[:, i]
        return self._arr[key]

    def _next_trip(self, rd, dt, i, ready):
        arr = self._arrivals(rd, dt, i)
        ok = np.flatnonzero(arr >= ready)
        return None if len(ok) == 0 else int(ok[np.argmin(arr[ok])])

    # ---------- access and changes by position ----------
    def _access(self, lat, lon, k=60):
        near = self.tree.query_ball_point(_xy([lat], [lon])[0], C.MAX_WALK_M)
        if not near:
            return []
        d = haversine_m(lat, lon, self._g_lat[near], self._g_lon[near])
        best = {}
        for g, dist in zip(near, d):
            best.setdefault(self._g_rd[g], []).append((float(dist), int(self._g_i[g])))
        out = []
        for rd, lst in best.items():
            for dist, i in sorted(lst)[:2]:
                out.append((rd, i, dist * C.WALK_DETOUR / WALK_MS))
        out.sort(key=lambda x: x[2])
        bus = [x for x in out if self.pats[x[0]].mode != "metro"][:k]
        metro = [x for x in out if self.pats[x[0]].mode == "metro"][:20]     # reserve room: metro stations are further away
        return bus + metro

    def _near_changes(self, rd, t):
        key = (rd, t)
        if key not in self._nearc:
            p = self.pats[rd]
            res = []
            for g in self.tree.query_ball_point(_xy([p.lat[t]], [p.lon[t]])[0], TRANSFER_RADIUS_M):
                rb = self._g_rd[g]
                if rb != rd:
                    dist = float(haversine_m(p.lat[t], p.lon[t], self._g_lat[g], self._g_lon[g]))
                    res.append((rb, int(self._g_i[g]), dist * C.WALK_DETOUR / WALK_MS))
            self._nearc[key] = res
        return self._nearc[key]

    # ---------- crowding ----------
    def _stretch_crowd(self, rd, dt, k, i, j, p_user):
        p = self.pats[rd]
        starts, offs = self._trips(p, dt)
        band = int((starts[k] // BAND_S) % NB)
        m = self.model.get((rd, dt))
        v = M.view(m, band, np.arange(i, j), p_user) if m is not None else None
        out = []
        for n_, s in enumerate(range(i, j)):
            dur = float(offs[k, s + 1] - offs[k, s])
            rec = {"from": p.names[s], "to": p.names[s + 1], "sec": dur, "level": None}
            if v is not None and v["ok"][n_]:
                rec.update(level=int(v["level"][n_]), load=float(v["p50"][n_]), lo=float(v["lo"][n_]),
                           hi=float(v["hi"][n_]), p_crowded=float(v["p_crowded"][n_]), conf=int(v["conf"][n_]))
            out.append(rec)
        return out

    @staticmethod
    def _summary(stretches):
        tot = sum(s["sec"] for s in stretches) or 1.0
        share = {0: 0.0, 1: 0.0, 2: 0.0, None: 0.0}
        for s in stretches:
            share[s["level"]] += s["sec"] / tot
        known = 1 - share[None]
        if known < 0.3:
            level = None
        elif share[2] >= 0.2:
            level = 2
        elif share[1] + share[2] >= 0.3:
            level = 1
        else:
            level = 0
        kn = [s for s in stretches if s["level"] is not None]
        worst = max(kn, key=lambda s: s["load"], default=None)
        wsum = sum(s["sec"] for s in kn) or 1.0
        share_hi = sum(s["sec"] for s in kn if s["conf"] >= 2) / wsum
        share_mid = sum(s["sec"] for s in kn if s["conf"] >= 1) / wsum
        conf_label = "high" if share_hi >= .6 else "medium" if share_mid >= .6 else "low"
        crowd_min = sum(C.CROWD_WEIGHT[s["level"]] * s["sec"] for s in stretches) / 60.0
        return {"level": level, "label": C.LEVEL_LABELS[level] if level is not None else "No crowding data",
                "share": {"seats": round(share[0], 2), "standing": round(share[1], 2), "crowded": round(share[2], 2),
                          "unknown": round(share[None], 2)},
                "worst": None if worst is None else {"from": worst["from"], "to": worst["to"], "load": round(worst["load"]),
                                                     "level": worst["level"]},
                "confidence": conf_label if kn else "none"}, crowd_min

    # ---------- search ----------
    def _candidates(self, O, D, t0, dt):
        dest_by_rd = {}
        for rd, j, w2 in D:
            dest_by_rd.setdefault(rd, []).append((j, w2))
        out = []
        for rd, i, w1 in O:
            k = self._next_trip(rd, dt, i, t0 + w1)
            if k is None:
                continue
            p = self.pats[rd]
            starts, offs = self._trips(p, dt)
            for j, w2 in dest_by_rd.get(rd, []):
                if j > i:
                    out.append((starts[k] + offs[k, j] + w2, ((rd, k, i, j),), w1, w2))
            for t in range(i + 3, p.n):
                at = starts[k] + offs[k, t]
                for rdB, tb, wc in self._near_changes(rd, t):
                    if rdB not in dest_by_rd:
                        continue
                    kB = self._next_trip(rdB, dt, tb, at + wc + C.TRANSFER_BUFFER_S)
                    if kB is None:
                        continue
                    sB, oB = self._trips(self.pats[rdB], dt)
                    if sB[kB] + oB[kB, tb] - at > 40 * 60:
                        continue
                    for j, w2 in dest_by_rd[rdB]:
                        if j - tb >= 3:
                            out.append((sB[kB] + oB[kB, j] + w2, ((rd, k, i, t), (rdB, kB, tb, j)), w1, w2))
        out.sort(key=lambda x: x[0])
        best, seen = [], {}
        for c in out:
            key = tuple(l[0] for l in c[1])
            seen[key] = seen.get(key, 0) + 1
            if seen[key] <= 2:
                best.append(c)
            if len(best) >= 60:
                break
        return best

    def _line(self, p):
        if p.mode != "metro":
            return None
        pre = (p.route_short or "").split("_")[0].upper()
        return (METRO_COLOURS.get(pre, "Metro") + " line") if pre != "RAPID" else "Rapid Metro"

    def _describe(self, cand, t_leave, t_orig, dt, o_name, d_name, shift, p_user):
        arr_final, legs, w1, w2 = cand
        L, crowd_min_total, bus_str = [], 0.0, []
        for rd, k, i, j in legs:
            p = self.pats[rd]
            starts, offs = self._trips(p, dt)
            metro = p.mode == "metro"
            st = self._stretch_crowd(rd, dt, k, i, j, p_user)
            if metro:
                summ = {"level": None, "label": "Crowding not modelled for metro", "share": {}, "worst": None, "confidence": "none"}
                sens = {}
            else:
                summ, cm = self._summary(st)
                crowd_min_total += cm
                bus_str += st
                sens = {str(sp): self._summary(self._stretch_crowd(rd, dt, k, i, j, sp))[0]["level"] for sp in SENS_P}
            L.append({"type": "metro" if metro else "bus", "route": rd, "line": self._line(p),
                      "board": str(p.names[i]), "alight": str(p.names[j]), "board_idx": i, "alight_idx": j,
                      "board_time": hhmm(starts[k] + offs[k, i]), "alight_time": hhmm(starts[k] + offs[k, j]),
                      "ride_min": round((offs[k, j] - offs[k, i]) / 60), "stops": j - i, "crowding": summ,
                      "sensitivity": sens,
                      "stretches": [{kk: vv for kk, vv in s.items() if kk != "sec"} | {"min": round(s["sec"] / 60, 1)} for s in st],
                      "path": [[float(p.lat[x]), float(p.lon[x])] for x in range(i, j + 1)],
                      "_board_sec": float(starts[k] + offs[k, i])})
        if bus_str:
            overall = self._summary(bus_str)[0]
        else:
            overall = {"level": None, "label": "Metro only: crowding not modelled", "share": {}, "worst": None, "confidence": "none"}
        sens_all = {}
        for sp in SENS_P:
            bs = []
            for rd, k, i, j in legs:
                if self.pats[rd].mode != "metro":
                    bs += self._stretch_crowd(rd, dt, k, i, j, sp)
            sens_all[str(sp)] = self._summary(bs)[0]["level"] if bs else None
        wait_min = (L[0]["_board_sec"] - (t_leave + w1)) / 60
        for l in L:
            l.pop("_board_sec")
        eff = (arr_final - t_orig) / 60
        return {"leave_at": hhmm(t_leave), "leave_later_min": shift, "arrive_at": hhmm(arr_final),
                "duration_min": round((arr_final - t_leave) / 60), "total_from_requested_min": round(eff),
                "walk_min": round((w1 + w2) / 60), "wait_min": round(max(wait_min, 0)), "transfers": len(L) - 1,
                "from_stop": L[0]["board"], "to_stop": L[-1]["alight"], "legs": L, "crowding": overall,
                "sensitivity": sens_all, "has_metro": any(l["type"] == "metro" for l in L),
                "_eff": eff, "_crowd_min": crowd_min_total, "_sig": tuple(legs), "from": o_name, "to": d_name}

    def plan(self, origin, dest, depart: datetime, priority="balanced", shifts=SHIFTS_MIN, top=5, p_user=M.P0,
             use_metro=False):
        olat, olon, oname = self.resolve_point(origin)
        dlat, dlon, dname = self.resolve_point(dest)
        if float(haversine_m(olat, olon, dlat, dlon)) < 300:
            return {"options": [], "note": "The origin and destination are within a few minutes' walk of each other."}
        O, D = self._access(olat, olon), self._access(dlat, dlon)
        if not use_metro:
            O = [x for x in O if self.pats[x[0]].mode != "metro"]
            D = [x for x in D if self.pats[x[0]].mode != "metro"]
        if not O or not D:
            return {"options": [], "note": "No bus stops within walking distance of the origin or destination."}
        dt = daytype_of(depart)
        t_orig = depart.hour * 3600 + depart.minute * 60
        w = C.COMFORT_W[priority]
        pool = {}
        for sh in shifts:
            t_leave = t_orig + sh * 60
            for cand in self._candidates(O, D, t_leave, dt):
                op = self._describe(cand, t_leave, t_orig, dt, oname, dname, sh, p_user)
                sig = op["_sig"]
                if sig not in pool or sh < pool[sig]["leave_later_min"]:
                    pool[sig] = op
        ops = list(pool.values())
        if not ops:
            return {"options": [], "note": "No journey found at this time."}
        cost = lambda o, ww: o["_eff"] + ww * o["_crowd_min"]
        chosen = {}
        for sh in shifts:
            sub = [o for o in ops if o["leave_later_min"] == sh]
            if sub:
                b = min(sub, key=lambda o: cost(o, w)); chosen[b["_sig"]] = b
        for ww in (0.0, 3.0):
            b = min(ops, key=lambda o: cost(o, ww)); chosen[b["_sig"]] = b
        res = sorted(chosen.values(), key=lambda o: cost(o, w))[:top]
        fast, cosy = min(ops, key=lambda o: cost(o, 0.0))["_sig"], min(ops, key=lambda o: cost(o, 3.0))["_sig"]
        for o in res:
            tags = []
            if o["_sig"] == fast: tags.append("Fastest")
            if o["_sig"] == cosy: tags.append("Most comfortable")
            if o["leave_later_min"]: tags.append(f"Leave {o['leave_later_min']} min later")
            if o["has_metro"]: tags.append("Uses metro")
            o["tags"] = tags
            o["score"] = round(cost(o, w), 1)
            for kx in ("_eff", "_crowd_min", "_sig"):
                o.pop(kx)
        return {"from": {"name": oname, "lat": olat, "lon": olon}, "to": {"name": dname, "lat": dlat, "lon": dlon},
                "daytype": dt, "priority": priority, "assumed_sampling_fraction": p_user,
                "basis": f"{self.meta['ndays'].get(dt, 0)} {dt}s of October 2026 e-tickets", "options": res,
                "note": "Crowding is a modelled estimate from sampled e-ticket data; metro legs are routed but not crowding-modelled."}

    def window(self, origin, dest, start: datetime, end: datetime, step_min=15, priority="balanced", p_user=M.P0,
               use_metro=False):
        """Best time to leave between start and end: plans one trip per step and compares them."""
        rows, t, w = [], start, C.COMFORT_W[priority]
        while t <= end:
            r = self.plan(origin, dest, t, priority, shifts=(0,), top=3, p_user=p_user, use_metro=use_metro)
            if r.get("options"):
                o = r["options"][0]
                cm = sum(C.CROWD_WEIGHT[s["level"]] * s["min"] for l in o["legs"] if l["type"] == "bus" for s in l["stretches"])
                rows.append({"leave": t.strftime("%H:%M"), "arrive": o["arrive_at"], "duration_min": o["duration_min"],
                             "level": o["crowding"]["level"], "label": o["crowding"]["label"],
                             "confidence": o["crowding"]["confidence"], "score": round(o["duration_min"] + w * cm, 1),
                             "routes": [l["line"] or l["route"].replace("UP", "").replace("DOWN", "") for l in o["legs"]]})
            t += timedelta(minutes=step_min)
        best = min(rows, key=lambda r: r["score"])["leave"] if rows else None
        return {"best_leave": best, "priority": priority, "assumed_sampling_fraction": p_user, "options": rows}
