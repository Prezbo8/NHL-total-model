"""Goalie on the second night of a back-to-back: when a team plays on consecutive days, does it matter whether
its starter ALSO played yesterday (tired goalie) or is a rested backup?

(1) Goalie level: goals saved above expected per game (xG faced - goals) for starters by rest.
(2) Team level: opponent's goals vs the model's projection (real starters, b2b already applied), by case.
(3) If there's an effect: extra opponent scoring when the starter played yesterday, learned from earlier
    seasons only, judged on accuracy and SLAM/1U (real starters, as the last pre-game run knows them).

  python3 research/goalie_b2b.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
from math import lgamma

import numpy as np
import pandas as pd

import dashboard
import history as h
import model as m
import split_model as sm


def main():
    starter, _, gg = m.load_goalies()
    gg = gg.dropna(subset=["gameDate"]).copy()
    gg["day"] = pd.to_datetime(gg.gameDate.astype(int).astype(str))
    played = set(zip(gg.playerId, gg.day))
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=True, record_detail=True).merge(g[["gameId", "hg", "ag", "h_b2b", "a_b2b"]], on="gameId")
    p["day"] = pd.to_datetime(p.gameDate.astype(str))
    for side in ("home", "away"):
        gid_team = list(zip(p.gameId, p[side]))
        p[f"{side}_g"] = [starter.get(k) for k in gid_team]
        p[f"{side}_gtired"] = [(gp, d - pd.Timedelta(days=1)) in played if gp is not None else False
                               for gp, d in zip(p[f"{side}_g"], p.day)]

    # (1) goalie level, starters 2021-26
    st = gg[gg.season.between(2021, 2025)].merge(pd.DataFrame(
        [(gid, t, gp) for (gid, t), gp in starter.items()], columns=["gameId", "team", "playerId"]), on=["gameId", "playerId"])
    st["tired"] = [(gp, d - pd.Timedelta(days=1)) in played for gp, d in zip(st.playerId, st.day)]
    st["gsax"] = st.xGoals - st.goals
    print("(1) starters' goals saved above expected per game (+ = better than expected)")
    for name, x in (("played yesterday too", st[st.tired]), ("rested", st[~st.tired])):
        se = x.gsax.std() / np.sqrt(len(x))
        print(f"  {name:22s} {len(x):6d} starts   GSAx/game {x.gsax.mean():+.3f} (± {2 * se:.3f})   save quality: "
              f"{x.goals.sum() / x.xGoals.sum():.3f} goals per xG")

    # (2) team level: the b2b team's OPPONENT scoring vs projection
    rows = []
    for r in p[p.season.between(2021, 2025)].itertuples():
        for side, opp_goals, opp_lam, b2b, other_b2b in (("home", r.ag, r.lam_a, r.h_b2b, r.a_b2b), ("away", r.hg, r.lam_h, r.a_b2b, r.h_b2b)):
            case = ("not on a back-to-back" if not b2b else
                    "b2b, starter played yesterday" if getattr(r, f"{side}_gtired") else "b2b, rested goalie starts")
            rows.append((r.season, case, opp_goals, opp_lam))
    t = pd.DataFrame(rows, columns=["season", "case", "goals", "lam"])
    print("\n(2) goals scored AGAINST the team, actual / projected (model already applies the b2b +6.5%)")
    print(f"  {'case':32s} {'team-games':>10s} {'ratio':>6s} {'2021-23':>8s} {'2023-26':>8s}")
    for case, x in t.groupby("case"):
        r_ = lambda y: y.goals.sum() / y.lam.sum()
        print(f"  {case:32s} {len(x):10d} {r_(x):6.3f} {r_(x[x.season <= 2022]):8.3f} {r_(x[x.season >= 2023]):8.3f}")

    # (3) adjustment from earlier seasons only
    lp = lambda k_, lam: k_ * np.log(lam) - lam - np.array([lgamma(v + 1) for v in k_])
    out_rows = []
    base = t[t.case == "not on a back-to-back"]
    for s, x in p.groupby("season"):
        tr = t[t.season.between(2021, s - 1)]
        f = 1.0
        if len(tr):
            tired = tr[tr.case == "b2b, starter played yesterday"]
            rest = tr[tr.case == "b2b, rested goalie starts"]
            f = 1 + 0.5 * ((tired.goals.sum() / tired.lam.sum()) / (rest.goals.sum() / rest.lam.sum()) - 1)
        kh = np.where(x.away_gtired & x.a_b2b, f, 1.0)  # home scores more when the AWAY starter is tired
        ka = np.where(x.home_gtired & x.h_b2b, f, 1.0)
        out_rows.append(x.assign(lam_h=x.lam_h * kh, lam_a=x.lam_a * ka, proj=x.lam_h * kh + x.lam_a * ka, f=f))
    q = pd.concat(out_rows)
    del base
    print(f"\n(3) factor 2026-27 would use: +{q[q.season == q.season.max()].f.iloc[0] - 1:.1%} to the opponent when the starter played yesterday")
    lines = h.lines()
    print(f"{'version (real starters)':26s} {'goal LL 23-26':>13s}   {'SLAM+1U open':>32s}   {'SLAM+1U close':>32s}")
    for name, v in (("current", p), ("+ tired-goalie factor", q)):
        tt = v[v.season.between(2023, 2025)]
        ll = -np.mean(np.r_[lp(tt.hg.values, tt.lam_h.values), lp(tt.ag.values, tt.lam_a.values)])
        d = h.flagged(v).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        o = []
        for when in ("open", "close"):
            b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            o.append(f"{len(b)} {b.prof.sum():+.1f}u {b.prof.mean():+.1%} ({hv[0]:+.1%}/{hv[1]:+.1%})")
        print(f"{name:26s} {ll:13.4f}   {o[0]:>32s}   {o[1]:>32s}")


if __name__ == "__main__":
    main()
