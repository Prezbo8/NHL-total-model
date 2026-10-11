"""Are the team ratings too extreme? Weak-vs-weak games score more than projected and strong-vs-strong a bit
less (research/studies combo/tier breakdowns, Oct 10 2026). Pulling ratings toward average = higher K (more
games of last season's prior before this season counts fully) and/or higher REGRESS (more summer pull).

Judged on: team-goal accuracy 2023-26 (real starters), the miss in games where both teams project in the
bottom / top fifth, and SLAM+1U (usual-starter guess, as the daily backtest).

  python3 research/studies/rating_shrink.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
from math import lgamma

import numpy as np

import dashboard
import history as h
import model as m
import split_model as sm

GRID = [(m.K, m.REGRESS), (20, m.REGRESS), (25, m.REGRESS), (30, m.REGRESS), (m.K, 0.45), (20, 0.45), (25, 0.45), (m.K, 0.25)]


def main():
    g = sm.load_split()
    lines = h.lines()
    lp = lambda k_, lam: k_ * np.log(lam) - lam - np.array([lgamma(v + 1) for v in k_])
    print(f"{'K':>3s} {'REGRESS':>7s} | {'goal LL 23-26':>13s} {'avg miss':>8s} | {'weak-vs-weak miss':>17s} {'strong-vs-strong miss':>21s} | "
          f"{'SLAM+1U open':>26s} | {'SLAM+1U close':>26s}")
    for k, reg in GRID:
        p = sm.walk_split(g, k=k, regress=reg, known_starters=True).merge(g[["gameId", "hg", "ag"]], on="gameId")
        t = p[p.season.between(2023, 2025)]
        ll = -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
        miss = np.mean(np.r_[np.abs(t.hg - t.lam_h), np.abs(t.ag - t.lam_a)])
        a = p[p.season.between(2021, 2025)]
        lo, hi = np.quantile(np.r_[a.lam_h, a.lam_a], [0.2, 0.8])
        weak = a[(a.lam_h <= lo) & (a.lam_a <= lo)]
        strong = a[(a.lam_h >= hi) & (a.lam_a >= hi)]
        wm, sm_ = (weak.total - weak.proj).mean(), (strong.total - strong.proj).mean()
        q = sm.walk_split(g, k=k, regress=reg, known_starters=False, record_detail=True)
        d = h.flagged(q).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        o = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            o.append(f"{len(b)} {b.prof.sum():+.1f}u ({hv[0]:+.1%}/{hv[1]:+.1%})")
        tag = "  <- current" if (k, reg) == (m.K, m.REGRESS) else ""
        print(f"{k:3d} {reg:7.2f} | {ll:13.5f} {miss:8.4f} | {wm:+8.2f} ({len(weak):4d}) {sm_:+12.2f} ({len(strong):4d}) | {o[0]:>26s} | {o[1]:>26s}{tag}")


if __name__ == "__main__":
    main()
