"""Injury strength 1.0x (live) vs 1.15x: projection accuracy first (all games, by season, and the games where
injuries move a team's projection the most), then P(7+) and SLAM/1U. On who actually dressed, 2021-26.

  python3 research/studies/injury_115.py      # needs data/dressed.csv (research/lib/lineups_hist.py)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from math import lgamma

import numpy as np
import pandas as pd

import dashboard
import history as h
import injury_backtest as ib
import model as m
import paths
import split_model as sm


def main():
    g = sm.load_split()
    base = sm.walk_split(g, known_starters=False, record_detail=True)
    eff = ib.missing_effects(g, pd.read_csv(paths.data("dressed.csv")))
    v = {"1.0x (live)": ib.adjusted(base, eff, 1.0), "1.15x": ib.adjusted(base, eff, 1.15)}
    # how much injuries moved each team's projection at 1.0x
    a = v["1.0x (live)"].merge(base[["gameId", "lam_h", "lam_a"]], on="gameId", suffixes=("", "_0")).merge(g[["gameId", "hg", "ag"]], on="gameId")
    move = pd.concat([a.set_index("gameId").lam_h / a.set_index("gameId").lam_h_0 - 1,
                      a.set_index("gameId").lam_a / a.set_index("gameId").lam_a_0 - 1], axis=1).abs().max(axis=1)
    lp = lambda k, lam: k * np.log(lam) - lam - np.array([lgamma(x + 1) for x in k])

    def acc(p, sel=None):
        x = p.merge(g[["gameId", "hg", "ag"]], on="gameId")
        x = x[x.season.between(2021, 2025)]
        if sel is not None:
            x = x[x.gameId.isin(sel)]
        ll = -np.mean(np.r_[lp(x.hg.values, x.lam_h.values), lp(x.ag.values, x.lam_a.values)])
        err = np.mean(np.r_[np.abs(x.hg - x.lam_h), np.abs(x.ag - x.lam_a)])
        return ll, err, len(x)

    big = set(move[move >= 0.03].index)
    print("PROJECTION ACCURACY, team goals (lower = better)")
    print(f"{'':30s} {'1.0x log loss':>13s} {'1.15x':>8s} {'1.0x avg miss':>13s} {'1.15x':>7s} {'games':>6s}")
    for name, sel in (("all games 2021-26", None), ("games where injuries moved a team 3%+", big)):
        r1, r2 = acc(v["1.0x (live)"], sel), acc(v["1.15x"], sel)
        print(f"{name:30s} {r1[0]:13.5f} {r2[0]:8.5f} {r1[1]:13.4f} {r2[1]:7.4f} {r1[2]:6d}")
    for s in range(2021, 2026):
        ids = set(base[base.season == s].gameId)
        r1, r2 = acc(v["1.0x (live)"], ids), acc(v["1.15x"], ids)
        rb1, rb2 = acc(v["1.0x (live)"], ids & big), acc(v["1.15x"], ids & big)
        print(f"  {s}-{str(s + 1)[2:]}: all {r1[0]:.5f} vs {r2[0]:.5f} {'better' if r2[0] < r1[0] else 'worse'} | "
              f"big-injury games ({rb1[2]}) {rb1[0]:.5f} vs {rb2[0]:.5f} {'better' if rb2[0] < rb1[0] else 'worse'}")

    print("\nP(7+) accuracy 2023-26 (walk-forward fit)")
    for name, p in v.items():
        rows = []
        for s in range(2023, 2026):
            cal = m.fit_calibration(p[p.season.between(2022, s - 1)])
            x = p[p.season == s]
            rows.append(pd.DataFrame({"p": m.p_from(cal, 7, x.proj.values, (x.lam_h - x.lam_a).abs().values), "y": (x.total >= 7).values}))
        r = pd.concat(rows)
        print(f"  {name:12s} log loss {-np.mean(np.where(r.y, np.log(r.p), np.log(1 - r.p))):.5f}")

    print("\nSLAM + 1U (2021-26)")
    lines = h.lines()
    for name, p in v.items():
        d = h.flagged(p).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        out = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            out.append(f"{when} {len(b)} bets {b.prof.sum():+.1f}u {b.prof.mean():+.1%}")
        print(f"  {name:12s} " + " | ".join(out))


if __name__ == "__main__":
    main()
