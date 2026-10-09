"""Time of season: does scoring vs the projection follow the calendar, the same way every season?

(1) actual - projected total by month, every season 2021-26 (after the Oct 8 shorthanded/shootout fix).
(2) A month adjustment, walk-forward: each season's month factors come only from EARLIER seasons
    (actual / projected goals in that month, shrunk halfway to 1), applied to both teams' projections.
    Judged on team-goal accuracy and the flag / SLAM / 1U backtest, open and close, both halves.

  python3 research/studies/month_effect.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
from math import lgamma

import numpy as np
import pandas as pd

import dashboard
import history as h
import split_model as sm

MONTHS = [10, 11, 12, 1, 2, 3, 4]
NAMES = {10: "Oct", 11: "Nov", 12: "Dec", 1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr"}


def main():
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=False, record_detail=True).merge(g[["gameId", "hg", "ag"]], on="gameId")
    p["month"] = (p.gameDate // 100) % 100
    p.loc[p.month == 5, "month"] = 4  # a few early-May finales count as April
    p.loc[p.month.isin([7, 8, 9]), "month"] = 10
    a = p[p.season.between(2021, 2025)]

    print("(1) actual minus projected total goals, by month")
    print(f"{'season':8s} " + " ".join(f"{NAMES[mo]:>6s}" for mo in MONTHS))
    for s, x in a.groupby("season"):
        r = x.groupby("month").apply(lambda y: (y.total - y.proj).mean(), include_groups=False)
        print(f"{s}-{str(s + 1)[2:]:4s} " + " ".join(f"{r.get(mo, np.nan):+6.2f}" for mo in MONTHS))
    r = a.groupby("month").apply(lambda y: (y.total - y.proj).mean(), include_groups=False)
    se = a.groupby("month").apply(lambda y: (y.total - y.proj).std() / np.sqrt(len(y)), include_groups=False)
    print(f"{'ALL':8s} " + " ".join(f"{r[mo]:+6.2f}" for mo in MONTHS))
    print(f"{'±2 SE':8s} " + " ".join(f"{2 * se[mo]:6.2f}" for mo in MONTHS))
    print("months above/below the season's own average, how many of 5 seasons agree:")
    dev = a.groupby(["season", "month"]).apply(lambda y: (y.total - y.proj).mean(), include_groups=False).unstack()
    dev = dev.sub(dev.mean(axis=1), axis=0)
    print(f"{'':8s} " + " ".join(f"{(np.sign(dev[mo]) == np.sign(dev[mo].mean())).sum():>4d}/5" for mo in MONTHS))

    # (2) walk-forward month factors
    def factors(train):
        f = {}
        for mo in MONTHS:
            x = train[train.month == mo]
            raw = (x.hg.sum() + x.ag.sum()) / (x.lam_h.sum() + x.lam_a.sum())
            f[mo] = raw
        base = (train.hg.sum() + train.ag.sum()) / (train.lam_h.sum() + train.lam_a.sum())
        return {mo: 1 + 0.5 * (v / base - 1) for mo, v in f.items()}  # relative to the season level, shrunk halfway
    adj = []
    for s, x in p.groupby("season"):
        prev = p[p.season.between(2021, s - 1)]
        f = factors(prev) if len(prev) else {mo: 1.0 for mo in MONTHS}
        k = x.month.map(f).fillna(1.0).values
        adj.append(x.assign(lam_h=x.lam_h * k, lam_a=x.lam_a * k, proj=(x.lam_h + x.lam_a) * k, mf=k))
    q = pd.concat(adj)
    last = factors(p[p.season.between(2021, 2025)])
    print("\nmonth factors from 2021-26 (what 2026-27 would use): " + "  ".join(f"{NAMES[mo]} {last[mo] - 1:+.1%}" for mo in MONTHS))

    lp = lambda k_, lam: k_ * np.log(lam) - lam - np.array([lgamma(v + 1) for v in k_])
    lines = h.lines()
    print(f"\n{'version':22s} {'goal LL 23-26':>13s}   {'flagged close':>24s}   {'SLAM+1U open':>32s}   {'SLAM+1U close':>32s}")
    for name, v in (("current", p), ("+ month factors", q)):
        t = v[v.season.between(2023, 2025)]
        ll = -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
        d = h.flagged(v).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        fb = h.bet_results(d, "close")
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        out = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            out.append(f"{len(b)} {b.prof.sum():+.1f}u {b.prof.mean():+.1%} ({hv[0]:+.1%}/{hv[1]:+.1%})")
        print(f"{name:22s} {ll:13.4f}   {f'{len(fb)} {fb.prof.mean():+.1%}':>24s}   {out[0]:>32s}   {out[1]:>32s}")


if __name__ == "__main__":
    main()
