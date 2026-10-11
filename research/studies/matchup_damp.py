"""Dampen the matchup math: each side's distance from league average enters as (rating / average) ** damp,
so two strong (or two weak) units don't stack at full strength. Motivation: games where both teams project
in the top fifth score 0.35 under projection (5v5 part -0.47), bottom fifth 0.62 over (5v5 +0.38).
damp = 1.0 is the live model. Judged on team-goal accuracy, the extreme misses, then SLAM+1U.

  python3 research/studies/matchup_damp.py
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


def main():
    g = sm.load_split()
    lines = h.lines()
    lp = lambda k_, lam: k_ * np.log(lam) - lam - np.array([lgamma(v + 1) for v in k_])
    print(f"{'damp':>4s} | {'goal LL 23-26':>13s} {'2021-23':>8s} {'avg miss':>8s} | {'weak-vs-weak':>12s} {'strong-vs-strong':>16s} | "
          f"{'P(7+) LL 23-26':>14s} | {'SLAM+1U open':>26s} | {'SLAM+1U close':>26s}")
    for damp in (1.0, 0.9, 0.8, 0.7, 0.6):
        p = sm.walk_split(g, known_starters=True, damp=damp).merge(g[["gameId", "hg", "ag"]], on="gameId")
        ll = lambda t: -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
        t, t0 = p[p.season.between(2023, 2025)], p[p.season.between(2021, 2022)]
        miss = np.mean(np.r_[np.abs(t.hg - t.lam_h), np.abs(t.ag - t.lam_a)])
        a = p[p.season.between(2021, 2025)]
        lo, hi = np.quantile(np.r_[a.lam_h, a.lam_a], [0.2, 0.8])
        wk, st = a[(a.lam_h <= lo) & (a.lam_a <= lo)], a[(a.lam_h >= hi) & (a.lam_a >= hi)]
        q = sm.walk_split(g, known_starters=False, record_detail=True, damp=damp)
        pr = []
        for s in range(2023, 2026):
            cal = m.fit_calibration(q[q.season.between(2022, s - 1)])
            x = q[q.season == s]
            pr.append((m.p_from(cal, 7, x.proj.values, (x.lam_h - x.lam_a).abs().values), (x.total >= 7).values))
        pp_, yy = np.concatenate([a_ for a_, _ in pr]), np.concatenate([b_ for _, b_ in pr])
        p7ll = -np.mean(np.where(yy, np.log(pp_), np.log(1 - pp_)))
        d = h.flagged(q).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        o = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            hv = [b[b.season.isin(s_)].prof.mean() for s_ in ((2021, 2022), (2023, 2024, 2025))]
            o.append(f"{len(b)} {b.prof.sum():+.1f}u ({hv[0]:+.1%}/{hv[1]:+.1%})")
        tag = "  <- current" if damp == 1.0 else ""
        print(f"{damp:4.1f} | {ll(t):13.5f} {ll(t0):8.5f} {miss:8.4f} | {(wk.total - wk.proj).mean():+6.2f} ({len(wk):3d}) {(st.total - st.proj).mean():+9.2f} ({len(st):3d}) | "
              f"{p7ll:14.5f} | {o[0]:>26s} | {o[1]:>26s}{tag}")


if __name__ == "__main__":
    main()
