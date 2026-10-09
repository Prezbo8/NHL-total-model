"""Back-to-back retune with 2025-26 included. Projections are made with NO back-to-back adjustment (ratings
don't depend on it, so this is exact), then: (1) actual vs projected goals for the tired team, its opponent,
and both-tired games, by half; (2) a grid of factors judged on accuracy (2023-26) and the SLAM/1U backtest.

  python3 research/studies/b2b_retune.py
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
    m.B2B_TIRED, m.B2B_VS_TIRED = 1.0, 1.0  # project without back-to-backs
    base = sm.walk_split(g, known_starters=False, record_detail=True)
    known = sm.walk_split(g, known_starters=True)
    cols = ["gameId", "hg", "ag", "h_b2b", "a_b2b"]
    base, known = base.merge(g[cols], on="gameId"), known.merge(g[cols], on="gameId")
    known = known[known.season >= 2021]  # base keeps 2020: the flag cutoff for 2021 comes from it

    # 1. what back-to-backs did, relative to a projection that ignores them (real starters)
    print("actual / projected goals (no b2b in the projection), real starters")
    print(f"{'team':34s} {'team-games':>10s} {'2021-26':>8s} {'2021-23':>8s} {'2023-26':>8s}")
    k = known
    groups = {
        "tired team (opponent rested)": [(k.h_b2b & ~k.a_b2b, "h"), (k.a_b2b & ~k.h_b2b, "a")],
        "rested team facing a tired one": [(k.a_b2b & ~k.h_b2b, "h"), (k.h_b2b & ~k.a_b2b, "a")],
        "both tired (each team)": [(k.h_b2b & k.a_b2b, "h"), (k.h_b2b & k.a_b2b, "a")],
        "neither tired (baseline)": [(~k.h_b2b & ~k.a_b2b, "h"), (~k.h_b2b & ~k.a_b2b, "a")],
    }
    for name, parts in groups.items():
        def ratio(sel):
            gl = sum(k[mask & sel][f"{s}g"].sum() for mask, s in parts)
            pr = sum(k[mask & sel][f"lam_{s}"].sum() for mask, s in parts)
            return gl / pr
        n = sum(int(mask.sum()) for mask, _ in parts)
        allm = np.ones(len(k), bool)
        print(f"{name:34s} {n:10d} {ratio(allm):8.3f} {ratio(k.season.between(2021, 2022).values):8.3f} {ratio(k.season.between(2023, 2025).values):8.3f}")

    # 2. grid
    def apply(p, tired, vs):
        fh = np.where(p.h_b2b, tired, 1.0) * np.where(p.a_b2b, vs, 1.0)
        fa = np.where(p.a_b2b, tired, 1.0) * np.where(p.h_b2b, vs, 1.0)
        x = sm.EXTRA / 2  # the shorthanded/shootout amount isn't scaled by back-to-backs
        q = p.assign(lam_h=(p.lam_h - x) * fh + x, lam_a=(p.lam_a - x) * fa + x, home_b2badj=fh - 1, away_b2badj=fa - 1)
        return q.assign(proj=q.lam_h + q.lam_a)
    lp = lambda kk, lam: kk * np.log(lam) - lam - np.array([lgamma(x + 1) for x in kk])
    print(f"\n{'tired':>6s} {'vs tired':>8s} {'goal LL':>8s}   {'SLAM+1U open':>32s}   {'SLAM+1U close':>32s}")
    lines = h.lines()
    for tired, vs in [(0.92, 1.065), (1.0, 1.0), (0.90, 1.065), (0.94, 1.065), (0.96, 1.065), (0.92, 1.03), (0.92, 1.09), (0.94, 1.03)]:
        kq = apply(known, tired, vs)
        t = kq[kq.season >= 2023]
        ll = -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
        q = apply(base, tired, vs)
        d = h.flagged(q).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        out = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            out.append(f"{len(b)} {b.prof.sum():+.1f}u {b.prof.mean():+.1%} ({hv[0]:+.1%}/{hv[1]:+.1%})")
        tag = "  <- current" if (tired, vs) == (0.92, 1.065) else ""
        print(f"{tired:6.2f} {vs:8.3f} {ll:8.4f}   {out[0]:>32s}   {out[1]:>32s}{tag}")


if __name__ == "__main__":
    main()
