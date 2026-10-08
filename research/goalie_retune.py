"""Goalie adjustment retune with 2025-26 included: shrink (G_SHRINK), carry-over (G_DECAY), and re-centering
(subtract a constant from every goalie's skill so the average adjustment is ~0 instead of ~-2.7%).

Accuracy: Poisson log loss of each team's goals 2023-26 with the real starter (the last pre-game run has it).
Bets: flag rule + SLAM/1U 2021-26, as the daily backtest runs them (usual-starter guess). When re-centering,
the Gl tier cutoffs move by the same amount so the AVOID rule sees the same goalies as strong.

  python3 research/goalie_retune.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
from math import lgamma

import numpy as np

import dashboard
import history as h
import model as m
import split_model as sm

BASE_TIERS = dashboard.TIERS["gadj"]
SKILL = m.GoalieSkill.skill


def setup(shrink, decay, center):
    m.GoalieSkill.__init__.__defaults__ = (shrink, decay)
    m.GoalieSkill.skill = lambda self, p: SKILL(self, p) - center
    dashboard.TIERS["gadj"] = tuple(c + center for c in BASE_TIERS)


def run(g, shrink, decay, center):
    setup(shrink, decay, center)
    p = sm.walk_split(g, known_starters=True).merge(g[["gameId", "hg", "ag"]], on="gameId")
    t = p[p.season >= 2023]
    lp = lambda k, lam: k * np.log(lam) - lam - np.array([lgamma(x + 1) for x in k])
    ll = -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
    bias = (t.total - t.proj).mean()
    q = sm.walk_split(g, known_starters=False, record_detail=True)
    d = h.flagged(q).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both]
    c = np.array([dashboard.call(r, True) for r in d.itertuples()])
    out = []
    for when in ("open", "close"):
        b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
        hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
        out.append(f"{len(b):4d} {b.prof.sum():+6.1f}u {b.prof.mean():+5.1%} ({hv[0]:+.1%}/{hv[1]:+.1%})")
    return ll, bias, out


def main():
    g = sm.load_split()
    grid = [(200, 0.7, 0.0)] + [(s, 0.7, 0.0) for s in (100, 150, 300, 400)] + [(200, d, 0.0) for d in (0.5, 0.85, 1.0)] \
        + [(200, 0.7, c) for c in (0.01, 0.02, 0.027)]
    print(f"{'shrink':>6s} {'decay':>5s} {'center':>6s} {'goal LL':>8s} {'bias':>6s}   "
          f"{'SLAM+1U open: n units ROI (21-22/23-25)':>40s}   {'SLAM+1U close':>40s}")
    for s, d, c in grid:
        ll, bias, out = run(g, s, d, c)
        tag = "  <- current" if (s, d, c) == (200, 0.7, 0.0) else ""
        print(f"{s:6d} {d:5.2f} {c:6.3f} {ll:8.4f} {bias:+6.2f}   {out[0]:>40s}   {out[1]:>40s}{tag}")


if __name__ == "__main__":
    main()
