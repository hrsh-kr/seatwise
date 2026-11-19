"""Pooled gamma-Poisson model of on-board load per route-direction x stretch x half-hour x day type.

Idea. Each bus trip carries an unknown true load L(s) on stretch s. E-tickets are a thinned sample of riders
(fraction p0). So the sampled pax-stretch count C in a cell is ~ Poisson(p0 * L * trips_in_cell). We pool cells
over days, neighbouring stretches and neighbouring half-hours, put a Gamma prior on the sampled load per bus,
and report the posterior (median and 90% interval) scaled back by 1/p0.

    python -m crowdplan.model --prep outputs/prep_full --out outputs/model
"""
from __future__ import annotations
import argparse, json, pickle, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import ndimage, stats
from . import config as C
from .prep import load_network

BAND_S = 1800
NB = 48
KT = np.array([.5, 1., .5]); KT = KT / KT.sum()
KS = np.array([.25, .5, 1., .5, .25]); KS = KS / KS.sum()
ESS = (1 / np.sum(KT ** 2)) * (1 / np.sum(KS ** 2))       # cells' worth of information in a smoothed cell
KAPPA_W = 12.0     # prior strength for weekend cells (in smoothed trip-days)
M_SHRINK = 20.0    # weight on the city-wide weekend/weekday ratio when scaling a route's weekday shape
KAPPA = 1.0        # prior strength in (smoothed) trip-days
PHI = 2.0          # overdispersion inflation (tuned on held-out data, see evaluate())
P0 = 0.035         # effective e-ticket sampling fraction of all riders (brief: 3-4%); sensitivity reported
ANOMALY_FRAC = 0.8
CAP = 1.5      # 99th-percentile cell may not exceed this multiple of crush capacity
MIN_EXPOSURE = 3.0  # smoothed trip-days needed before a cell is reported
DAYTYPES = ("weekday", "saturday", "sunday")


def label_days(df: pd.DataFrame):
    daily = df.groupby("date").size()
    dow = daily.index.dayofweek
    dt = pd.Series(np.where(dow < 5, "weekday", np.where(dow == 5, "saturday", "sunday")), index=daily.index)
    med = daily.groupby(dt).median()
    anomalous = [d for d in daily.index if daily[d] < ANOMALY_FRAC * med[dt[d]]]
    return dt, anomalous, daily


GPS = {}   # (rd, daytype) -> trips actually run per departure half-hour (from the GPS feed, one reference day per type)
GPS_FILES = {"weekday": "outputs/gps/trips_2026_10_14.csv", "saturday": "outputs/gps/trips_2026_10_17.csv"}


def load_gps(net):
    cols = ["route_id", "trip_id", "vehicle_id", "t0", "t1", "n"]
    rid2rd = {p.route_id: rd for rd, p in net.patterns.items()}
    for dt, fn in GPS_FILES.items():
        if not Path(fn).exists():
            continue
        t = pd.read_csv(fn, names=cols, header=None, dtype={"route_id": str})
        t = t[(t.n >= 30) & ((t.t1 - t.t0) >= 600)]
        t["rd"] = t.route_id.map(rid2rd)
        t = t.dropna(subset=["rd"])
        t["band"] = (((t.t0 + 19800) % 86400) // BAND_S).astype(int)
        for (rd, band), c in t.groupby(["rd", "band"]).size().items():
            GPS.setdefault((rd, dt), np.zeros(NB))[band] = c
    return len(GPS)


def get_N0(p, dt):
    """Trips per day by (departure band, stretch): GPS-observed run frequency where available, else timetable."""
    base = sched_exposure(p)
    v = GPS.get((p.rd, dt))
    if v is None or v.sum() == 0:
        return base
    f = base.sum(0) / max(base.sum(0).max(), 1.0)     # share of trips that cover each stretch
    return v[:, None] * f[None, :]


def sched_exposure(p):
    if p.N0 is not None:
        return p.N0
    starts, offs = next(iter(p.trips.values()))
    S = p.n - 1
    t = starts[:, None] + offs[:, :S]
    band = ((t // BAND_S) % NB).astype(int)
    N0 = np.bincount((band * S + np.arange(S)[None, :]).ravel(), minlength=NB * S).reshape(NB, S).astype(float)
    return N0


def count_cells(g: pd.DataFrame, p) -> np.ndarray:
    """Sampled pax-stretch counts per (half-hour band, stretch) for one route and day type."""
    S = p.n - 1
    b = g.b_idx.to_numpy(); a = g.a_idx.to_numpy(); secs = g.secs.to_numpy(); pc = g.pc.to_numpy()
    L = a - b
    rep = np.repeat(np.arange(len(g)), L)
    start = np.cumsum(L) - L
    s = b[rep] + (np.arange(L.sum()) - np.repeat(start, L))
    # band = half-hour of the TRIP's departure from the origin (implied from the boarding time), same convention as
    # the scheduled exposure N0; schedule offsets cancel, and bus lateness only shifts both sides together.
    tb = ((secs - p.off_med[b]) // BAND_S % NB).astype(int)
    return np.bincount(tb[rep] * S + s, weights=pc[rep], minlength=NB * S).reshape(NB, S)


def smooth(A):
    return ndimage.convolve1d(ndimage.convolve1d(A, KT, axis=0, mode="constant"), KS, axis=1, mode="constant")


def posterior(Craw, Nraw, res, phi=PHI, prior_cell=None):
    """Gamma posterior (shape a, rate b) of sampled load per bus, plus the smoothed effective counts."""
    Ce = ESS * smooth(Craw / max(res, 0.3))
    Ne = ESS * smooth(Nraw)
    route_rate = Ce.sum() / max(Ne.sum(), 1e-9)
    row_ne = Ne.sum(1, keepdims=True)
    prior = np.where(row_ne >= 5.0, Ce.sum(1, keepdims=True) / np.maximum(row_ne, 1e-9), route_rate)
    kap = KAPPA
    if prior_cell is not None:          # weekend: borrow the weekday along-route/time-of-day shape
        prior, kap = prior_cell, KAPPA_W
    a = np.maximum((Ce + kap * prior) / phi, 1e-3)
    b = (Ne + kap) / phi
    return a, b, Ce, Ne


def summarise(a, b, p0=P0):
    sc = 1 / b
    return tuple(stats.gamma.ppf(q, a, scale=sc) / p0 for q in (.05, .5, .95))


def fit_counts(df, net, daymap):
    """{(rd, dt): (C, ndays)} using included days only."""
    out = {}
    df = df.assign(dt=df.date.map(daymap))
    ndays = df.groupby("dt").date.nunique().to_dict()
    for (rd, dt), g in df.groupby(["rd", "dt"]):
        p = net.patterns[rd]
        out[(rd, dt)] = count_cells(g, p)
    return out, ndays


def view(m, band, s_idx, p_user=P0):
    """Load quantiles, level, P(crowded) for given stretches at a chosen sampling fraction.
    The route's capacity floor p_min always applies: p_eff = max(p_user, p_min)."""
    a = m["a"][band, s_idx].astype(float); b = m["b"][band, s_idx].astype(float)   # band may be an array too
    ok = m["active"][band, s_idx]
    pe = max(p_user, m["p_min"])
    cap = CAP * m["crush"]
    lo, med, hi = (np.minimum(stats.gamma.ppf(q, a, scale=1 / b) / pe, cap) for q in (.05, .5, .95))
    lvl = level_of(med, m["seats"], m["crush"])
    pc = stats.gamma.sf(C.STANDING_FRAC * m["crush"] * pe, a, scale=1 / b)
    return {"ok": ok & np.isfinite(med), "lo": lo, "p50": med, "hi": hi, "level": lvl, "p_crowded": pc,
            "conf": m["conf"][band, s_idx], "p_eff": pe}


def level_of(load, seats, crush):
    return np.where(load <= seats, 0, np.where(load <= C.STANDING_FRAC * crush, 1, 2)).astype(np.uint8)


def run(prep_dir, gtfs_dir, out_dir, p0=P0, phi=PHI):
    t0 = time.time()
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    net = load_network(gtfs_dir)
    print('GPS exposure routes:', load_gps(net))
    df = pd.read_pickle(Path(prep_dir) / "tickets_resolved.pkl")
    df["date"] = pd.to_datetime(df.date)
    res = pd.read_csv(Path(prep_dir) / "route_resolution.csv").set_index("rd").res_share.to_dict()
    dtmap, anomalous, daily = label_days(df)
    keep = df[~df.date.isin(anomalous)]
    cnt, ndays = fit_counts(keep, net, dtmap)
    print(f"[{time.time()-t0:4.0f}s] counted cells for {len(cnt)} route-daytypes; excluded days: "
          f"{[str(d.date()) for d in anomalous]}; days per type {ndays}", flush=True)

    # Pass 1: posteriors in sampled units. Weekday first; weekend cells then borrow the weekday shape.
    post = {}
    def rate_tot(dt):
        c = n = 0.0
        for (rd, d), Craw in cnt.items():
            if d == dt:
                c += Craw.sum() / max(res.get(rd, 1.0), .3); n += (get_N0(net.patterns[rd], dt) * ndays[dt]).sum()
        return c / max(n, 1e-9)
    city = {dt: rate_tot(dt) for dt in DAYTYPES}
    ratio_city = {dt: city[dt] / city["weekday"] for dt in DAYTYPES}
    for (rd, dt), Craw in cnt.items():
        if dt != "weekday":
            continue
        p = net.patterns[rd]
        N0 = get_N0(p, dt)
        a, b, Ce, Ne = posterior(Craw, N0 * ndays[dt], res.get(rd, 1.0), phi)
        post[(rd, dt)] = (a, b, Ce, Ne, Craw)
    for (rd, dt), Craw in cnt.items():
        if dt == "weekday":
            continue
        p = net.patterns[rd]
        Nraw = get_N0(p, dt) * ndays[dt]
        r = res.get(rd, 1.0)
        pc = None
        if (rd, "weekday") in post:
            a_w, b_w, Ce_w, Ne_w, C_w = post[(rd, "weekday")]
            rate_w = a_w / b_w                                    # weekday sampled load per bus, per cell
            tot_wd = max(rate_w[Ne_w >= MIN_EXPOSURE].mean() if (Ne_w >= MIN_EXPOSURE).any() else 0.0, 1e-9)
            Ce = ESS * smooth(Craw / max(r, .3)); Ne = ESS * smooth(Nraw)
            # route-level weekend/weekday scale, shrunk to the city ratio
            wd_equiv = (rate_w * Ne).sum()
            scale = (Ce.sum() + M_SHRINK * ratio_city[dt] * (wd_equiv / max(Ne.sum(), 1e-9))) / max(wd_equiv + M_SHRINK * (wd_equiv / max(Ne.sum(), 1e-9)), 1e-9)
            pc = scale * rate_w
        a, b, Ce, Ne = posterior(Craw, Nraw, r, phi, prior_cell=pc)
        post[(rd, dt)] = (a, b, Ce, Ne, Craw)
    # Physical-plausibility constraint: per-route sampling fraction p_r >= p0, raised just enough that the 99th
    # percentile weekday cell does not exceed CAP x crush capacity.
    p_min = {}
    for (rd, dt), (a, b, Ce, Ne, Craw) in post.items():
        if dt != "weekday":
            continue
        act = Ne >= MIN_EXPOSURE
        p_min[rd] = float(np.quantile((a / b)[act], 0.99) / (CAP * net.patterns[rd].crush)) if act.any() else 0.0
    for (rd, dt) in post:
        p_min.setdefault(rd, 0.0)
    adj = np.array([v > p0 for v in p_min.values()])
    print(f"[{time.time()-t0:4.0f}s] routes whose sampling fraction is raised above p0={p0}: {adj.mean():.1%}", flush=True)

    model = {}
    rows = []
    for (rd, dt), (a, b, Ce, Ne, Craw) in post.items():
        p = net.patterns[rd]
        active = Ne >= MIN_EXPOSURE
        conf = np.where(Ce >= 80, 2, np.where(Ce >= 25, 1, 0)).astype(np.uint8)
        ent = {"a": a.astype(np.float32), "b": b.astype(np.float32), "conf": conf, "active": active,
               "ce": Ce.astype(np.float32), "n0": get_N0(p, dt).astype(np.float32), "days": int(ndays[dt]),
               "p_min": p_min[rd], "seats": p.seats, "crush": p.crush}
        model[(rd, dt)] = ent
        pe = max(p0, p_min[rd])
        lo, med, hi = (np.minimum(x, CAP * p.crush) for x in summarise(a, b, pe))
        med = np.where(active, med, np.nan)
        lvl = level_of(med, p.seats, p.crush)
        with np.errstate(invalid="ignore"):
            rows.append({"rd": rd, "daytype": dt, "peak_load": np.nanmax(med) if active.any() else np.nan,
                         "peak_ratio": np.nanmax(med / p.crush) if active.any() else np.nan,
                         "share_crowded": float(((lvl == 2) & active).sum() / max(active.sum(), 1)),
                         "share_standing_or_worse": float(((lvl >= 1) & active).sum() / max(active.sum(), 1)),
                         "sampled_pax": float(Craw.sum()), "stretches": p.n - 1, "p_eff": pe})
    summ = pd.DataFrame(rows)
    with open(out / "model.pkl", "wb") as f:
        pickle.dump({"model": model, "p0": p0, "phi": phi, "kappa": KAPPA, "anomalous_days": [str(d.date()) for d in anomalous],
                     "ndays": ndays}, f)
    summ.to_csv(out / "route_summary.csv", index=False)
    print(f"[{time.time()-t0:4.0f}s] model saved: {len(model)} route-daytypes", flush=True)
    return model, summ


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", default="outputs/prep_full")
    ap.add_argument("--gtfs", default="data/gtfs")
    ap.add_argument("--out", default="outputs/model")
    ap.add_argument("--p0", type=float, default=P0)
    ap.add_argument("--phi", type=float, default=PHI)
    a = ap.parse_args()
    run(a.prep, a.gtfs, a.out, a.p0, a.phi)
