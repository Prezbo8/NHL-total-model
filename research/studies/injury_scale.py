"""Injury strength: the live adjustment at 1.0x (what runs) vs 1.15x / 1.3x / none, on who actually dressed 2021-26.
Re-checks the earlier finding (slope ~1.3) by half, then judges each size on team-goal accuracy and SLAM/1U bets.

  python3 research/studies/injury_scale.py      # needs data/dressed.csv (research/lib/lineups_hist.py download)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import numpy as np
import pandas as pd

import dashboard
import history as h
import injury_backtest as ib
import paths
import split_model as sm


def main():
    games = sm.load_split()
    dressed = pd.read_csv(paths.data("dressed.csv"))
    base = sm.walk_split(games, known_starters=False, record_detail=True)
    eff = ib.missing_effects(games, dressed)

    # slope by season: 1.0 = the live adjustment is the right size
    x = base.merge(games[["gameId", "hg", "ag"]], on="gameId")
    rows = []
    for r in x.itertuples():
        for team, opp, goals, lam in ((r.home, r.away, r.hg, r.lam_h), (r.away, r.home, r.ag, r.lam_a)):
            if (r.gameId, team) in eff and (r.gameId, opp) in eff:
                rows.append((r.season, goals / lam - 1, -sum(eff[(r.gameId, team)][0]) + sum(eff[(r.gameId, opp)][1])))
    t = pd.DataFrame(rows, columns=["season", "resid", "expected"])
    t = t[t.season.between(2021, 2025)].dropna()  # 2026-27: each team's first 5 games are skipped, so nothing yet
    print("slope of (goals vs model) on (injury adjustment): 1.0 = right size, 1.3 = 30% too small")
    for name, sel in (("2021-26", t.season >= 2021), ("2021-23", t.season.between(2021, 2022)), ("2023-26", t.season >= 2023)):
        u = t[sel]
        boots = [np.polyfit(*u.sample(len(u), replace=True, random_state=i)[["expected", "resid"]].T.values, 1)[0] for i in range(300)]
        print(f"  {name}: {len(u)} team-games, slope {np.polyfit(u.expected, u.resid, 1)[0]:.2f} (90% range {np.percentile(boots, 5):.2f}..{np.percentile(boots, 95):.2f})")
    for s, u in t.groupby("season"):
        print(f"    {s}-{str(s + 1)[2:]}: slope {np.polyfit(u.expected, u.resid, 1)[0]:.2f}")

    print(f"\n{'size':22s} {'team dev 23-26':>14s}   {'SLAM+1U open: n units ROI (21-22/23-25)':>40s}   {'SLAM+1U close':>36s}")
    lines = h.lines()
    for name, p in (("none (backtest)", base), ("1.0x (live)", ib.adjusted(base, eff)),
                    ("1.15x", ib.adjusted(base, eff, scale=1.15)), ("1.3x", ib.adjusted(base, eff, scale=1.3))):
        d = h.flagged(p).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        out = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            out.append(f"{len(b)} {b.prof.sum():+.1f}u {b.prof.mean():+.1%} ({hv[0]:+.1%}/{hv[1]:+.1%})")
        print(f"{name:22s} {ib.team_dev(p, games, (2023, 2025)):14.4f}   {out[0]:>40s}   {out[1]:>36s}")


if __name__ == "__main__":
    main()
