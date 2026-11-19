"""Minimal static-GTFS loader: one dominant stop pattern per (route, direction)."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import pandas as pd
from . import config as C


def norm_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def hms_to_s(col: pd.Series) -> np.ndarray:
    p = col.astype(str).str.strip().str.split(":", expand=True).astype(int)
    return (p[0] * 3600 + p[1] * 60 + p[2]).to_numpy()


@dataclass
class Pattern:
    rd: str                      # e.g. "8UP" (matches the ticket 'route' field)
    route_short: str
    direction: int
    names: list
    norm_names: list
    lat: np.ndarray
    lon: np.ndarray
    length_m: int
    trips: dict = field(default_factory=dict)   # daytype -> (starts[n], offs[n, stops])
    off_med: np.ndarray | None = None
    route_id: str = ""
    trip_ids: dict = field(default_factory=dict)   # daytype -> trip ids aligned with trips[daytype]
    mode: str = "bus"
    stop_ids: list = field(default_factory=list)
    N0: np.ndarray | None = None      # scheduled trips per day by (departure half-hour band, stretch), ALL trips on the route

    @property
    def n(self):
        return len(self.names)

    @property
    def seats(self):
        return C.SEATS.get(self.length_m, C.SEATS[C.DEFAULT_LENGTH_M])

    @property
    def crush(self):
        return C.CRUSH.get(self.length_m, C.CRUSH[C.DEFAULT_LENGTH_M])


class Network:
    def __init__(self, gtfs_dir):
        d = Path(gtfs_dir)
        stops = pd.read_csv(d / "stops.txt", dtype={"stop_id": str})
        routes = pd.read_csv(d / "routes.txt", dtype={"route_id": str, "route_short_name": str})
        trips = pd.read_csv(d / "trips.txt", dtype={"route_id": str, "trip_id": str, "service_id": str})
        # Delhi feed: direction_id is empty; the direction is already in route_short_name ("102AUP").
        trips["direction_id"] = pd.to_numeric(trips.get("direction_id"), errors="coerce").fillna(0).astype(int)
        st = pd.read_csv(d / "stop_times.txt", dtype={"trip_id": str, "stop_id": str},
                         usecols=["trip_id", "arrival_time", "stop_id", "stop_sequence"])
        lengths = {}
        if (d / "bus_lengths.csv").exists():
            bl = pd.read_csv(d / "bus_lengths.csv", dtype={"route_short_name": str})
            lengths = dict(zip(bl.route_short_name.str.upper(), bl.length_m))

        # service id -> daytype
        svc = {"weekday": set(trips.service_id), "weekend": set(trips.service_id)}
        if (d / "calendar.txt").exists():
            cal = pd.read_csv(d / "calendar.txt", dtype={"service_id": str})
            wk = cal[["monday", "tuesday", "wednesday", "thursday", "friday"]].sum(axis=1) >= 3
            we = cal[["saturday", "sunday"]].sum(axis=1) >= 1
            svc = {"weekday": set(cal.service_id[wk]), "weekend": set(cal.service_id[we])}

        self.all_stops = stops[["stop_name", "stop_lat", "stop_lon"]].copy()
        sname = dict(zip(stops.stop_id, stops.stop_name))
        slat = dict(zip(stops.stop_id, stops.stop_lat))
        slon = dict(zip(stops.stop_id, stops.stop_lon))
        short = dict(zip(routes.route_id, routes.route_short_name))

        st = st.sort_values(["trip_id", "stop_sequence"])
        seq = st.groupby("trip_id")["stop_id"].agg("|".join)
        tr = trips.set_index("trip_id").join(seq.rename("seq"), how="inner")
        tr["n"] = tr.seq.str.count(r"\|") + 1
        # dominant pattern per (route, direction): most trips, then most stops
        cnt = tr.groupby(["route_id", "direction_id", "seq"]).size().rename("c").reset_index()
        cnt["n"] = cnt.seq.str.count(r"\|") + 1
        best = cnt.sort_values(["c", "n"], ascending=False).drop_duplicates(["route_id", "direction_id"])

        arr_all = hms_to_s(st["arrival_time"])
        st = st.assign(arr=arr_all)
        self.patterns: dict[str, Pattern] = {}
        for _, r in best.iterrows():
            ids = r.seq.split("|")
            rs = str(short.get(r.route_id, r.route_id)).strip()
            rd = rs.upper()
            if not rd.endswith(("UP", "DOWN")):
                rd += "UP" if int(r.direction_id) == 0 else "DOWN"
            if rd in self.patterns:
                continue
            p = Pattern(rd, rs, int(r.direction_id), [sname[i] for i in ids],
                        [norm(sname[i]) for i in ids],
                        np.array([slat[i] for i in ids]), np.array([slon[i] for i in ids]),
                        int(lengths.get(rs.upper(), C.DEFAULT_LENGTH_M)))
            p.route_id = str(r.route_id); p.stop_ids = ids
            tids = tr.index[(tr.route_id == r.route_id) & (tr.direction_id == r.direction_id) & (tr.seq == r.seq)]
            sub = st[st.trip_id.isin(set(tids))]
            for dt in ("weekday", "weekend"):
                t_dt = tr.loc[tids]
                t_dt = t_dt.index[t_dt.service_id.isin(svc[dt])]
                if len(t_dt) == 0:
                    continue
                s2 = sub[sub.trip_id.isin(set(t_dt))].sort_values(["trip_id", "stop_sequence"])
                mat = s2["arr"].to_numpy().reshape(len(t_dt), len(ids)).astype(float)
                tid_arr = s2["trip_id"].drop_duplicates().to_numpy()
                order = np.argsort(mat[:, 0])
                mat = mat[order]
                starts = mat[:, 0].copy()
                p.trips[dt] = (starts, mat - starts[:, None])
                p.trip_ids[dt] = tid_arr[order]
            if p.trips:
                allo = np.vstack([v[1] for v in p.trips.values()])
                p.off_med = np.median(allo, axis=0)
                self.patterns[rd] = p

        self._build_exposure(st, tr)

        # stop table for walking access
        names, lat, lon = {}, {}, {}
        for p in self.patterns.values():
            for nm, nn, la, lo in zip(p.names, p.norm_names, p.lat, p.lon):
                names.setdefault(nn, nm); lat.setdefault(nn, la); lon.setdefault(nn, lo)
        self.stop_norm = list(names)
        self.stop_name = np.array([names[k] for k in self.stop_norm])
        self.stop_lat = np.array([lat[k] for k in self.stop_norm])
        self.stop_lon = np.array([lon[k] for k in self.stop_norm])
        self.incidence: dict[str, list] = {}
        for rd, p in self.patterns.items():
            for i, nn in enumerate(p.norm_names):
                self.incidence.setdefault(nn, []).append((rd, i))


def _build_exposure(self, st, tr):
    """Scheduled trips per (half-hour, stretch) from every trip on a route, mapped onto the dominant pattern."""
    NB = 48
    rid2rd = {p.route_id: rd for rd, p in self.patterns.items()}
    idxmap = {}
    for rd, p in self.patterns.items():
        m = {}
        for i, sid in enumerate(p.stop_ids):
            m.setdefault(sid, i)
        idxmap[rd] = m
        p.N0 = np.zeros((NB, p.n - 1))
    tid = st.trip_id.to_numpy(); sid = st.stop_id.to_numpy(); arr = st.arr.to_numpy().astype(float)
    cut = np.flatnonzero(tid[1:] != tid[:-1]) + 1
    starts = np.r_[0, cut]; ends = np.r_[cut, len(tid)]
    route_of = tr.route_id.to_dict()
    for a, b in zip(starts, ends):
        rd = rid2rd.get(route_of.get(tid[a]))
        if rd is None:
            continue
        m = idxmap[rd]
        ii, aa, last = [], [], -1
        for x, t in zip(sid[a:b], arr[a:b]):
            i = m.get(x, -1)
            if i > last:
                ii.append(i); aa.append(t); last = i
        if len(ii) < 2:
            continue
        sr = np.arange(ii[0], ii[-1])
        pat = self.patterns[rd]
        implied_start = float(np.median(np.array(aa) - pat.off_med[np.array(ii)]))   # trip departure time at the origin
        band = int((implied_start // 1800) % NB)
        pat.N0[band, sr] += 1


Network._build_exposure = _build_exposure



def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    a = np.radians(lat2 - lat1)
    b = np.radians(lon2 - lon1)
    h = np.sin(a / 2) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(b / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(h))
