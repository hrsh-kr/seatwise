"""Step 1: tickets -> resolved stop positions -> reconstructed bus trips -> per-trip load profiles.

    python -m crowdplan.prep --tickets data/extracted/October-Delhi.csv --gtfs data/gtfs \
        --out outputs/prep [--dates 2026-10-14]

Outputs (in --out):
  tickets_resolved.parquet-like pickle  : every ticket with route index, boarding/alighting stop index, trip id
  trips.csv                            : one row per reconstructed trip
  loads.pkl                            : {trip_id: load vector per stretch}
  prep_report.json                     : coverage / quality numbers
"""
from __future__ import annotations
import argparse, json, pickle, time
from pathlib import Path
import numpy as np
import pandas as pd
from rapidfuzz import process, fuzz
from .gtfs import Network, norm, haversine_m

ABBR = {"sec": "sector", "ngr": "nagar", "ext": "extension", "xing": "crossing", "rly": "railway",
        "stn": "station", "opp": "opposite", "nr": "near", "bdr": "border", "mkt": "market"}
DROP = {"terminal", "metro", "station", "stand", "bus", "stop", "t"}
GENERIC = {"sector", "nagar", "village", "road", "market", "chowk", "crossing", "colony", "extension", "block",
           "phase", "stage", "gate", "main", "depot", "border", "bridge", "flyover", "railway", "near", "opposite"}
GEO_MAX_M = 500


def distinct(n2: str) -> frozenset:
    return frozenset(t for t in n2.split() if t not in GENERIC)
SPLIT_GAP_S = 30 * 60          # a vehicle silent for this long starts a new trip
RESET_BACK = 3                 # boarding index falling this far below the running max = new trip (after min gap)
RESET_MIN_GAP_S = 5 * 60
ASSIGN_TOL_S = 12 * 60         # max |ticket time - predicted time at stop| for attaching an unlabelled ticket
FUZZY_CUTOFF = 90


def norm2(s: str) -> str:
    toks = [ABBR.get(t, t) for t in norm(s).split()]
    return " ".join(t for t in toks if t not in DROP)


def route_aliases(known: set) -> dict:
    """Safe spelling fixes for ticket route names: punctuation (ML96UP -> ML-96UP), a trailing variant digit
    (522BDOWN2 -> 522BDOWN) and EXT/EX. Only unique matches are used; real variants (729B vs 729) are left alone."""
    import re
    key = lambda x: re.sub(r"[^A-Z0-9]", "", x)
    by_key = {}
    for k in known:
        by_key.setdefault(key(k), set()).add(k)
    def fix(r):
        for cand in (key(r), re.sub(r"(UP|DOWN)\d+$", r"\1", key(r)), key(r).replace("EXT", "EX")):
            m = by_key.get(cand)
            if m and len(m) == 1:
                return next(iter(m))
        return None
    return fix


def load_network(gtfs_dir: str, cache: str = "outputs/network.pkl") -> Network:
    p = Path(cache)
    if p.exists():
        with open(p, "rb") as f:
            return pickle.load(f)
    net = Network(gtfs_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(net, f)
    return net


def resolve_stops(df: pd.DataFrame, net: Network) -> tuple[pd.DataFrame, dict]:
    """Add b_idx (boarding) and a_idx (alighting) = position in the route's dominant stop pattern."""
    maps = {}
    for rd, p in net.patterns.items():
        ex, ex2, lst = {}, {}, []
        for i, (n1) in enumerate(p.norm_names):
            ex.setdefault(n1, i)
            n2 = norm2(p.names[i])
            ex2.setdefault(n2, i)
        keys2 = list(ex2)
        dsets = {}
        for k, i in ex2.items():
            dsets.setdefault(distinct(k), []).append(i)
        maps[rd] = (ex, ex2, keys2, [ex2[k] for k in keys2], dsets)
    g_keys, g_xy = {}, {}
    for nm, la, lo in zip(net.all_stops.stop_name, net.all_stops.stop_lat, net.all_stops.stop_lon):
        g_xy.setdefault(norm2(nm), []).append((la, lo))
    g_keys = list(g_xy)

    raw = pd.concat([df[["rd", "start_stop_name"]].set_axis(["rd", "name"], axis=1),
                     df[["rd", "end_stop_name"]].set_axis(["rd", "name"], axis=1)])
    u = raw.value_counts().reset_index(name="cnt")
    tiers, res = [], []
    for rd, name, cnt in zip(u.rd, u.name, u.cnt):
        ex, ex2, keys2, idx2, dsets = maps[rd]
        n1 = norm(name)
        if n1 in ex:
            res.append(ex[n1]); tiers.append("exact"); continue
        n2 = norm2(name)
        if n2 in ex2:
            res.append(ex2[n2]); tiers.append("normalised"); continue
        d = distinct(n2)
        if d and len(dsets.get(d, [])) == 1:
            res.append(dsets[d][0]); tiers.append("distinctive-tokens"); continue
        if keys2 and n2:
            m = process.extractOne(n2, keys2, scorer=fuzz.token_sort_ratio, score_cutoff=FUZZY_CUTOFF)
            if m:
                res.append(idx2[m[2]]); tiers.append("fuzzy"); continue
        if n2:
            gm = n2 if n2 in g_xy else None
            if gm is None:
                m = process.extractOne(n2, g_keys, scorer=fuzz.token_sort_ratio, score_cutoff=95)
                gm = m[0] if m else None
            if gm is not None:
                p = net.patterns[rd]
                best_d, best_i = 1e9, -1
                for la, lo in g_xy[gm]:
                    dd = haversine_m(la, lo, p.lat, p.lon)
                    k = int(np.argmin(dd))
                    if dd[k] < best_d:
                        best_d, best_i = dd[k], k
                if best_d <= GEO_MAX_M:
                    res.append(best_i); tiers.append("geo-snap"); continue
        res.append(-1); tiers.append("unresolved")
    u["idx"], u["tier"] = res, tiers
    lut = {(r, n): i for r, n, i in zip(u.rd, u.name, u.idx)}
    df["b_idx"] = [lut[(r, n)] for r, n in zip(df.rd, df.start_stop_name)]
    df["a_idx"] = [lut[(r, n)] for r, n in zip(df.rd, df.end_stop_name)]
    w = u.groupby("tier").cnt.sum()
    report = {"stop_name_resolution_share": (w / w.sum()).round(4).to_dict()}
    df, extra = constraint_tier(df, net)
    report.update(extra)
    return df, report


def _bounds(df):
    """Per (route, name) interval of possible positions from the resolved ends of tickets that touch the name."""
    lo = df[(df.a_idx < 0) & (df.b_idx >= 0)].groupby(["rd", "end_stop_name"]).b_idx.quantile(0.95).add(1)
    hi = df[(df.b_idx < 0) & (df.a_idx >= 0)].groupby(["rd", "start_stop_name"]).a_idx.quantile(0.05).sub(1)
    return lo, hi


def constraint_tier(df, net):
    """Place a still-unresolved stop between the boarding stops of tickets that end there and the alighting stops of
    tickets that start there (only when the interval is at most 4 stops wide). Accuracy is measured on resolved names."""
    lo, hi = _bounds(df)
    names = {}
    for rd, nm in set(lo.index) | set(hi.index):
        l = lo.get((rd, nm)); h = hi.get((rd, nm))
        if l is not None and h is not None and not np.isnan(l) and not np.isnan(h) and 0 <= h - l <= 4:
            names[(rd, nm)] = int(round((l + h) / 2))
    nb = na = 0
    key_b = list(zip(df.rd, df.start_stop_name)); key_a = list(zip(df.rd, df.end_stop_name))
    nb_arr = np.array([names.get(k, -1) for k in key_b]); na_arr = np.array([names.get(k, -1) for k in key_a])
    mb = (df.b_idx.to_numpy() < 0) & (nb_arr >= 0); ma = (df.a_idx.to_numpy() < 0) & (na_arr >= 0)
    df.loc[mb, "b_idx"] = nb_arr[mb]; df.loc[ma, "a_idx"] = na_arr[ma]
    # accuracy probe: hide resolved names one at a time (sampled) and see how close the same estimator gets
    probe = df[(df.b_idx >= 0) & (df.a_idx >= 0)].sample(min(len(df), 300000), random_state=1)
    err = []
    lo2 = probe[probe.a_idx >= 0].groupby(["rd", "end_stop_name"]).b_idx.quantile(0.95).add(1)
    hi2 = probe[probe.b_idx >= 0].groupby(["rd", "start_stop_name"]).a_idx.quantile(0.05).sub(1)
    truth = probe.groupby(["rd", "end_stop_name"]).a_idx.agg(lambda v: v.mode().iat[0])
    for k, l in lo2.items():
        h = hi2.get((k[0], k[1]))
        if h is not None and 0 <= h - l <= 4 and k in truth.index:
            err.append(abs(round((l + h) / 2) - truth[k]))
    out = {"constraint_tier_names_placed": len(names), "constraint_tier_rows_boarding": int(mb.sum()),
           "constraint_tier_rows_alighting": int(ma.sum())}
    if err:
        out["constraint_tier_probe_median_error_stops"] = float(np.median(err)); out["constraint_tier_probe_share_within_1"] = round(float(np.mean(np.array(err) <= 1)), 3)
    return df, out


def split_trips(lab: pd.DataFrame) -> pd.Series:
    """Trip ids for vehicle-labelled tickets: same vehicle+route+date, split on long gaps or sequence reset."""
    lab = lab.sort_values(["vehicle_number", "rd", "date", "secs"])
    key = (lab.vehicle_number.astype(str) + "|" + lab.rd + "|" + lab.date.astype(str)).to_numpy()
    t = lab.secs.to_numpy(); b = lab.b_idx.to_numpy()
    tid = np.zeros(len(lab), dtype=np.int64)
    cur, last_key, last_t, runmax = -1, None, 0.0, -1
    for k in range(len(lab)):
        new = key[k] != last_key
        if not new:
            gap = t[k] - last_t
            if gap > SPLIT_GAP_S or (b[k] >= 0 and runmax - b[k] >= RESET_BACK and gap > RESET_MIN_GAP_S):
                new = True
        if new:
            cur += 1; runmax = -1
        tid[k] = cur; last_key = key[k]; last_t = t[k]
        if b[k] > runmax:
            runmax = b[k]
    return pd.Series(tid, index=lab.index)


def run(tickets, gtfs_dir, out, dates=None, skip_trips=False):
    t0 = time.time()
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    net = load_network(gtfs_dir)
    df = pd.read_csv(tickets, dtype={"vehicle_number": str})
    rep = {"tickets_raw": int(len(df))}
    df["t"] = pd.to_datetime(df.created_at.str[:19], errors="coerce")
    df = df.dropna(subset=["t", "route", "start_stop_name", "end_stop_name"])
    df["date"] = df.t.dt.normalize()
    if dates:
        df = df[df.date.isin(pd.to_datetime(dates))]
    df["secs"] = (df.t - df.date).dt.total_seconds()
    df["rd"] = df.route.astype(str).str.strip().str.upper()
    df["pc"] = pd.to_numeric(df.passenger_count, errors="coerce").fillna(1).clip(1, 10)
    df["vehicle_number"] = df.vehicle_number.where(~df.vehicle_number.isin(["NULL", "null", "", "nan"]))
    kn = set(net.patterns); fix = route_aliases(kn)
    miss = df.loc[~df.rd.isin(kn), "rd"]
    amap = {r: fix(r) for r in miss.unique()}
    amap = {r: a for r, a in amap.items() if a}
    rep["route_alias_rows_recovered"] = int(miss.isin(amap).sum())
    df["rd"] = df.rd.replace(amap)
    known = df.rd.isin(kn)
    rep["dropped_unknown_route_share"] = round(float((~known).mean()), 4)
    df = df[known].copy()
    rep["tickets_used"] = int(len(df))
    print(f"[{time.time()-t0:5.0f}s] loaded {len(df):,} tickets", flush=True)

    df, r = resolve_stops(df, net)
    rep.update(r)
    both = (df.b_idx >= 0) & (df.a_idx > df.b_idx)
    rep["usable_ticket_share"] = round(float(both.mean()), 4)
    rep["boarding_resolved_share"] = round(float((df.b_idx >= 0).mean()), 4)
    rep["alighting_wrong_direction_share"] = round(float(((df.a_idx >= 0) & (df.b_idx >= 0) & (df.a_idx <= df.b_idx)).mean()), 4)
    print(f"[{time.time()-t0:5.0f}s] stops resolved: {rep['stop_name_resolution_share']}", flush=True)

    # Alighting fix-up: if the ticket's end stop is unresolved or behind the boarding stop, impute the route median length.
    med_len = {}
    ok = df[both]
    for rd, g in ok.groupby("rd"):
        med_len[rd] = max(1, int(np.median(g.a_idx - g.b_idx)))
    (df.groupby("rd").b_idx.apply(lambda v: float((v >= 0).mean())).rename("res_share")
       .to_csv(out / "route_resolution.csv"))
    df = df[df.b_idx >= 0].copy()
    n_stops = df.rd.map({rd: p.n for rd, p in net.patterns.items()})
    imp = ~((df.a_idx > df.b_idx))
    df["a_imp"] = imp
    guess = df.b_idx + df.rd.map(med_len).fillna(4)
    df.loc[imp, "a_idx"] = np.minimum(guess[imp], n_stops[imp] - 1)
    df = df[(df.b_idx < n_stops - 1) & (df.a_idx > df.b_idx)].copy()
    rep["alighting_imputed_share"] = round(float(df.a_imp.mean()), 4)

    if skip_trips:
        df["trip"] = -1
        keep = ["rd", "date", "secs", "pc", "b_idx", "a_idx", "a_imp", "trip", "vehicle_number", "is_ac", "amount"]
        df[keep].to_pickle(out / "tickets_resolved.pkl")
        rep["runtime_s"] = round(time.time() - t0)
        (out / "prep_report.json").write_text(json.dumps(rep, indent=2, default=str))
        print(json.dumps(rep, indent=2, default=str))
        return
    # Trips from vehicle-labelled tickets
    df["trip"] = -1
    lab = df[df.vehicle_number.notna()]
    tid = split_trips(lab)
    df.loc[tid.index, "trip"] = tid.to_numpy()
    print(f"[{time.time()-t0:5.0f}s] {tid.nunique():,} trips from {len(lab):,} labelled tickets", flush=True)

    # Per-trip reference time offset: t0 = median(secs - median scheduled offset[b_idx])
    off = {rd: p.off_med for rd, p in net.patterns.items()}
    lab = df.loc[tid.index]
    lab_off = np.array([off[r][i] for r, i in zip(lab.rd, lab.b_idx)])
    tr = pd.DataFrame({"trip": lab.trip.to_numpy(), "rd": lab.rd.to_numpy(), "date": lab.date.to_numpy(),
                       "d": lab.secs.to_numpy() - lab_off, "secs": lab.secs.to_numpy()})
    trips = tr.groupby("trip").agg(rd=("rd", "first"), date=("date", "first"), t0=("d", "median"),
                                   t_first=("secs", "min"), t_last=("secs", "max"), n_lab=("d", "size")).reset_index()

    # Attach unlabelled tickets to the trip (same route+date) whose predicted time at the boarding stop is closest
    unl = df[df.trip < 0]
    assigned = np.full(len(unl), -1, dtype=np.int64)
    pos = {ix: k for k, ix in enumerate(unl.index)}
    tg = {key: g for key, g in trips.groupby(["rd", "date"])}
    n_amb = 0
    for key, g in unl.groupby(["rd", "date"]):
        cand = tg.get(key)
        if cand is None:
            continue
        T0 = cand.t0.to_numpy()[None, :]
        o = off[key[0]][g.b_idx.to_numpy()][:, None]
        pred = T0 + o
        dist = np.abs(g.secs.to_numpy()[:, None] - pred)
        j = dist.argmin(axis=1)
        best = dist[np.arange(len(g)), j]
        good = best <= ASSIGN_TOL_S
        ids = np.where(good, cand.trip.to_numpy()[j], -1)
        for ix, v in zip(g.index, ids):
            assigned[pos[ix]] = v
    df.loc[unl.index, "trip"] = assigned
    rep["labelled_share"] = round(float((df.index.isin(lab.index)).mean()), 4)
    rep["unlabelled_attached_share"] = round(float((assigned >= 0).mean()), 4)
    print(f"[{time.time()-t0:5.0f}s] unlabelled attached: {rep['unlabelled_attached_share']:.1%}", flush=True)

    # Per-trip load profile (boarding +pc at b, -pc at a), stretches = stops-1
    att = df[df.trip >= 0]
    loads = {}
    for (trip, rd), g in att.groupby(["trip", "rd"]):
        n = net.patterns[rd].n
        d = np.zeros(n + 1)
        np.add.at(d, g.b_idx.to_numpy(), g.pc.to_numpy())
        np.add.at(d, g.a_idx.to_numpy(), -g.pc.to_numpy())
        loads[int(trip)] = np.cumsum(d)[: n - 1].astype(np.float32)
    trips["peak_load"] = trips.trip.map(lambda k: float(loads[k].max()) if k in loads else 0.0)
    trips["n_tix_total"] = trips.trip.map(att.groupby("trip").size()).fillna(0).astype(int)
    trips.to_csv(out / "trips.csv", index=False)
    with open(out / "loads.pkl", "wb") as f:
        pickle.dump(loads, f)
    keep = ["rd", "date", "secs", "pc", "b_idx", "a_idx", "a_imp", "trip", "vehicle_number", "is_ac", "amount"]
    df[keep].to_pickle(out / "tickets_resolved.pkl")
    rep.update({"trips": int(len(trips)), "median_tickets_per_trip": float(trips.n_tix_total.median()),
                "trips_per_day_median": float(trips.groupby("date").size().median()),
                "runtime_s": round(time.time() - t0)})
    (out / "prep_report.json").write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps(rep, indent=2, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickets", default="data/extracted/October-Delhi.csv")
    ap.add_argument("--gtfs", default="data/gtfs")
    ap.add_argument("--out", default="outputs/prep")
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--skip-trips", action="store_true")
    a = ap.parse_args()
    run(a.tickets, a.gtfs, a.out, a.dates, a.skip_trips)
