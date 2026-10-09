"""Unknown starter: guess the usual starter (mode of the last 10) or blend the last-10 starters by share?

Stand-in for the morning, before goalies are confirmed. Compared with the real starter (known) as the ceiling.
Accuracy: Poisson log loss of each team's goals, 2023-26. Bets: flag rule + SLAM/1U, 2021-26.

  python3 research/studies/goalie_blend.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
from math import lgamma

import numpy as np

import dashboard
import history as h
import split_model as sm


def main():
    g = sm.load_split()
    variants = {"known starter (ceiling)": dict(known_starters=True), "guess: usual starter": dict(known_starters=False),
                "guess: blend last 10": dict(known_starters=False, guess="blend")}
    print(f"{'variant':26s} {'goal LL 2023-26':>15s}   {'SLAM+1U open':>22s}   {'SLAM+1U close':>22s}")
    for name, kw in variants.items():
        p = sm.walk_split(g, record_detail=True, **kw).merge(g[["gameId", "hg", "ag"]], on="gameId")
        t = p[p.season >= 2023]
        lp = lambda k, lam: k * np.log(lam) - lam - np.array([lgamma(x + 1) for x in k])
        ll = -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
        d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        out = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            w, l_ = (b.res > 0).sum(), (b.res < 0).sum()
            out.append(f"{w}-{l_} {b.prof.sum():+6.1f}u {b.prof.mean():+5.1%}")
        print(f"{name:26s} {ll:15.4f}   {out[0]:>22s}   {out[1]:>22s}")


if __name__ == "__main__":
    main()
