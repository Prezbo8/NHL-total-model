"""Goalie workload (suggestion #6, Oct 18 2026). goalie_b2b.py tested a starter playing both nights of a back-to-back
(rejected). This tests the rest of workload: a heavy week (3+ starts in the 6 days before tonight, so 4 in 7) and
rust (first start after 14+ days without one, e.g. back from injury or a long stretch as the backup).
Actual starters (known_starters=True), so the workload belongs to the goalie who played. Residual = goals the
goalie's team allowed - the projection; a factor per group is fit on 2021-23 and judged on 2023-26.

  python3 research/studies/goalie_workload.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import header, row, scorecard  # first: puts src/ on the path
import numpy as np
import pandas as pd

import model as m
import split_model as sm


def groups(games):
    """{(gameId, team): 'heavy' / 'rust' / 'normal'} for the team's starter that night."""
    starter = m.load_goalies()[0]
    g = games.sort_values(["gameDate", "gameId"])
    dates = dict(zip(g.gameId, pd.to_datetime(g.gameDate.astype(str))))
    hist, out = {}, {}
    for gid, h, a in zip(g.gameId, g.home, g.away):
        d = dates[gid]
        for t in (h, a):
            p = starter.get((gid, t))
            if p is None:
                continue
            past = hist.get(p, [])
            recent = sum(1 for x in past if 0 < (d - x).days <= 6)
            gap = (d - past[-1]).days if past else None
            out[(gid, t)] = "heavy" if recent >= 3 else "rust" if gap is not None and gap >= 14 else "normal"
            hist.setdefault(p, []).append(d)
    return out


def main():
    games = sm.load_split()
    grp = groups(games)
    p = sm.walk_split(games, known_starters=True, record_detail=True)
    x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
    rows = []
    for r in x.itertuples():  # goals allowed by each goalie's team = the OTHER side's goals
        rows.append({"gameId": r.gameId, "season": r.season, "side": "a", "grp": grp.get((r.gameId, r.home), "normal"), "y": r.ag, "lam": r.lam_a})
        rows.append({"gameId": r.gameId, "season": r.season, "side": "h", "grp": grp.get((r.gameId, r.away), "normal"), "y": r.hg, "lam": r.lam_h})
    t = pd.DataFrame(rows)
    t = t[t.season >= 2021]
    print("1. goals allowed vs projection, by the starter's workload (actual / projected)")
    fit = {}
    for lab, ss in (("2021-23", (2021, 2022)), ("2023-26", (2023, 2025))):
        s = t[t.season.between(*ss)]
        parts = []
        for gname in ("normal", "heavy", "rust"):
            q = s[s.grp == gname]
            ratio = q.y.sum() / q.lam.sum()
            parts.append(f"{gname}: {len(q):5d} starts, {ratio:.3f}")
            if lab == "2021-23":
                fit[gname] = ratio / (s[s.grp == "normal"].y.sum() / s[s.grp == "normal"].lam.sum())
        print(f"   {lab}  " + "   ".join(parts))
    print(f"   fitted on 2021-23 (vs normal starts): heavy x{fit['heavy']:.3f}, rust x{fit['rust']:.3f}\n")
    print("2. " + header(30))
    base = scorecard(p, games)
    print("   " + row("live, actual starters", base, 30))
    half = sm.EXTRA / 2
    for label, f in (("fitted heavy + rust", fit), ("heavy only", {**fit, "rust": 1.0}), ("rust only", {**fit, "heavy": 1.0})):
        q = p.copy()
        for side, opp in (("h", "away"), ("a", "home")):  # home goals depend on the away starter
            mult = np.array([f.get(grp.get((g, t_), "normal"), 1.0) if grp.get((g, t_), "normal") != "normal" else 1.0
                             for g, t_ in zip(q.gameId, q[opp])])
            q[f"lam_{side}"] = (q[f"lam_{side}"] - half) * mult + half
        q["proj"] = q.lam_h + q.lam_a
        print("   " + row(label, scorecard(q, games), 30, base))


if __name__ == "__main__":
    main()
