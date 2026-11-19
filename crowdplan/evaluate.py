"""Validation of the load model: held-out-week predictive check and known-pattern checks.

    python -m crowdplan.evaluate
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
from . import model as M
from .prep import load_network


def poisson_dev(y, mu):
    mu = np.maximum(mu, 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return 2 * np.sum(t - (y - mu))


def main(prep="outputs/prep_full", gtfs="data/gtfs", out="outputs/model", split="2026-10-21"):
    net = load_network(gtfs)
    M.load_gps(net)
    df = pd.read_pickle(Path(prep) / "tickets_resolved.pkl"); df["date"] = pd.to_datetime(df.date)
    res = pd.read_csv(Path(prep) / "route_resolution.csv").set_index("rd").res_share.to_dict()
    dtmap, anomalous, daily = M.label_days(df)
    df = df[~df.date.isin(anomalous)]
    wk = df[df.date.map(dtmap) == "weekday"]
    span = float(np.average(wk.a_idx - wk.b_idx, weights=wk.pc))
    train = wk[wk.date <= split]; test = wk[wk.date > split]
    dtr, dte = train.date.nunique(), test.date.nunique()
    Ctr = {rd: M.count_cells(g, net.patterns[rd]) for rd, g in train.groupby("rd")}
    Cte = {rd: M.count_cells(g, net.patterns[rd]) for rd, g in test.groupby("rd")}
    report = {"mean_ticket_span_stretches": round(span, 2), "train_days": int(dtr), "test_days": int(dte),
              "excluded_anomalous_days": [str(d.date()) for d in anomalous]}

    # --- held-out predictive check, tuning the overdispersion phi ---
    out_phi = {}
    for phi in (1.0, 2.0, 4.0, 7.0, 10.0):
        cov, width, n = 0, 0.0, 0
        dev_m = dev_b1 = 0.0
        for rd, Ct in Cte.items():
            if rd not in Ctr or rd not in net.patterns:
                continue
            p = net.patterns[rd]
            N0 = M.get_N0(p, 'weekday')
            r = res.get(rd, 1.0)
            a, b, Ce, Ne = M.posterior(Ctr[rd], N0 * dtr, r, phi)
            e = N0 * dte
            m = (e > 0) & (Ne >= M.MIN_EXPOSURE)
            if not m.any():
                continue
            # predictive for pseudo-count Y = C/phi
            pr = b / (b + e / phi)
            lo = stats.nbinom.ppf(0.10, a, pr) * phi
            hi = stats.nbinom.ppf(0.90, a, pr) * phi
            y = Ct
            cov += int(((y >= lo - 1e-9) & (y <= hi + 1e-9))[m].sum()); n += int(m.sum())
            width += float(np.nansum((hi - lo)[m]))
            mu_model = (a / b) * r * e
            # baseline: route-band mean across stretches (no along-route profile, no smoothing)
            rate_b = Ctr[rd].sum(1, keepdims=True) / np.maximum((N0 * dtr).sum(1, keepdims=True), 1e-9) * r
            mu_b1 = np.repeat(rate_b, N0.shape[1], axis=1) * e
            dev_m += poisson_dev(y[m], mu_model[m]); dev_b1 += poisson_dev(y[m], mu_b1[m])
        out_phi[phi] = {"coverage_80pct_interval": round(cov / n, 3), "mean_interval_width": round(width / n, 2),
                        "deviance_model": round(dev_m, 1), "deviance_route_band_baseline": round(dev_b1, 1),
                        "skill_vs_baseline": round(1 - dev_m / dev_b1, 3)}
    report["heldout_by_phi"] = out_phi

    # --- held-out Saturdays: does borrowing the weekday shape help? train 3,10,17 Oct; test 24,31 Oct ---
    sat = df[df.date.map(dtmap) == "saturday"]
    s_tr, s_te = sat[sat.date <= "2026-10-17"], sat[sat.date > "2026-10-17"]
    d_tr, d_te = s_tr.date.nunique(), s_te.date.nunique()
    Cs_tr = {rd: M.count_cells(g, net.patterns[rd]) for rd, g in s_tr.groupby("rd")}
    Cs_te = {rd: M.count_cells(g, net.patterns[rd]) for rd, g in s_te.groupby("rd")}
    Cw = {rd: M.count_cells(g, net.patterns[rd]) for rd, g in wk.groupby("rd")}
    nwk = wk.date.nunique()
    out_sat = {}
    for use_prior in (False, True):
        cov = n = 0; dev = 0.0
        for rd, Ct in Cs_te.items():
            if rd not in Cs_tr:
                continue
            p = net.patterns[rd]; N0 = M.get_N0(p, "saturday"); r = res.get(rd, 1.0)
            pc = None
            if use_prior and rd in Cw:
                a_w, b_w, Ce_w, Ne_w = M.posterior(Cw[rd], M.get_N0(p, "weekday") * nwk, r, M.PHI)
                Ce = M.ESS * M.smooth(Cs_tr[rd] / max(r, .3)); Ne = M.ESS * M.smooth(N0 * d_tr)
                rate_w = a_w / b_w; wd_eq = (rate_w * Ne).sum()
                ratio_city = 0.8
                base = wd_eq / max(Ne.sum(), 1e-9)
                scale = (Ce.sum() + M.M_SHRINK * ratio_city * base) / max(wd_eq + M.M_SHRINK * base, 1e-9)
                pc = scale * rate_w
            a, b, Ce, Ne = M.posterior(Cs_tr[rd], N0 * d_tr, r, M.PHI, prior_cell=pc)
            e = N0 * d_te; m = (e > 0) & (Ne >= M.MIN_EXPOSURE)
            if not m.any():
                continue
            mu = (a / b) * r * e
            pr = b / (b + e / M.PHI)
            lo = stats.nbinom.ppf(.10, a, pr) * M.PHI; hi = stats.nbinom.ppf(.90, a, pr) * M.PHI
            cov += int(((Ct >= lo - 1e-9) & (Ct <= hi + 1e-9))[m].sum()); n += int(m.sum())
            dev += poisson_dev(Ct[m], mu[m])
        out_sat["with_weekday_prior" if use_prior else "saturday_only"] = {"deviance": round(dev, 1), "coverage_80pct_interval": round(cov / n, 3)}
    report["heldout_saturday"] = out_sat

    # --- known-pattern checks on the fitted model ---
    cnt, ndays = M.fit_counts(df, net, dtmap)
    prof = {dt: np.zeros(M.NB) for dt in M.DAYTYPES}; expo = {dt: np.zeros(M.NB) for dt in M.DAYTYPES}
    for (rd, dt), C in cnt.items():
        p = net.patterns[rd]; N0 = M.get_N0(p, dt) * ndays[dt]
        prof[dt] += C.sum(1) / max(res.get(rd, 1.0), .3); expo[dt] += N0.sum(1)
    city = {dt: (prof[dt] / np.maximum(expo[dt], 1e-9)) / M.P0 for dt in M.DAYTYPES}
    hours = {dt: {f"{b//2:02d}:{(b%2)*30:02d}": round(float(city[dt][b]), 1) for b in range(10, 46) if expo[dt][b] > 0}
             for dt in M.DAYTYPES}
    wd = city["weekday"]
    am = int(np.argmax(wd[10:24]) + 10); pm = int(np.argmax(wd[28:46]) + 28)
    mid = wd[24:30].mean()
    report["city_average_load_per_bus_stretch"] = {
        "weekday_am_peak": f"{am//2:02d}:{(am%2)*30:02d}", "weekday_pm_peak": f"{pm//2:02d}:{(pm%2)*30:02d}",
        "am_peak_over_midday": round(float(wd[am] / mid), 2), "pm_peak_over_midday": round(float(wd[pm] / mid), 2)}
    tot = {dt: float(prof[dt].sum() / max(expo[dt].sum(), 1e-9) / M.P0) for dt in M.DAYTYPES}
    report["mean_load_by_daytype"] = {k: round(v, 1) for k, v in tot.items()}
    report["weekend_vs_weekday_ratio"] = {"saturday": round(tot["saturday"] / tot["weekday"], 2),
                                          "sunday": round(tot["sunday"] / tot["weekday"], 2)}
    summ = pd.read_csv(Path(out) / "route_summary.csv")
    top = (summ[(summ.daytype == "weekday") & (summ.sampled_pax > 500)].sort_values("peak_ratio", ascending=False)
           .head(10)[["rd", "peak_load", "peak_ratio", "share_crowded"]])
    report["busiest_routes_weekday"] = top.round(2).to_dict("records")
    report["city_profile_weekday"] = hours["weekday"]
    Path(out, "validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "city_profile_weekday"}, indent=2))


if __name__ == "__main__":
    main()
