"""Offensive zone time (NHL EDGE): does a team's share of time in the offensive / defensive zone add anything
beyond the model? EDGE has season totals from 2021-22, so each team gets LAST season's numbers (like team
speed), z-scored within the season. Cached in data/team_zone_time.csv.

(1) team goals vs projection against own offensive-zone time and the opponent's defensive-zone time.
(2) P(7+) with the game's combined offensive-zone time added (walk-forward, test 2023-26).
(3) a small projection adjustment fit on earlier seasons only, judged on accuracy and SLAM/1U.
(4) SLAM/1U by thirds of combined offensive-zone time.

  python3 research/studies/zone_time.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import json
import os
import time
import urllib.request
from math import lgamma

import numpy as np
import pandas as pd

import dashboard
import history as h
import model as m
import paths
import split_model as sm

CACHE = paths.data("team_zone_time.csv")
URL = "https://api-web.nhle.com/v1/edge/team-zone-time-details/{}/{}/2"


def zone_data():
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE)
    ids = {t["triCode"]: t["id"] for t in json.load(urllib.request.urlopen(m.fetch("https://api.nhle.com/stats/rest/en/team"), timeout=30))["data"]}
    g = sm.load_split()
    rows = []
    for s in range(2021, 2026):
        for t in sorted(set(g[g.season == s].home)):
            try:
                d = json.load(urllib.request.urlopen(m.fetch(URL.format(ids[t], s * 10000 + s + 1)), timeout=30))
                es = next(x for x in d["zoneTimeDetails"] if x["strengthCode"] == "es")
                rows.append({"season": s, "team": t, "oz": es["offensiveZonePctg"], "dz": es["defensiveZonePctg"], "nz": es["neutralZonePctg"]})
            except Exception as e:
                print(f"  skipped {t} {s}: {e}")
            time.sleep(0.2)
    z = pd.DataFrame(rows)
    z.to_csv(CACHE, index=False)
    return z


def main():
    z = zone_data()
    for c in ("oz", "dz", "nz"):
        z[f"{c}_z"] = z.groupby("season")[c].transform(lambda s: (s - s.mean()) / s.std())
    prev = z.assign(season=z.season + 1)
    prev.loc[prev.team == "ARI", "team"] = "UTA"  # franchise move: last season's numbers carry over
    look = {(r.season, r.team): r for r in prev.itertuples()}

    g = sm.load_split()
    p = sm.walk_split(g, known_starters=False, record_detail=True).merge(g[["gameId", "hg", "ag"]], on="gameId")
    for side in ("home", "away"):
        for c in ("oz_z", "dz_z"):
            p[f"{side}_{c}"] = [getattr(look.get((s, t)), c, np.nan) for s, t in zip(p.season, p[side])]
    p = p.dropna(subset=["home_oz_z", "away_oz_z"])
    p["game_oz"] = p.home_oz_z + p.away_oz_z
    print(f"games with last season's zone time: {len(p)} ({p.season.min()}-{str(p.season.max() + 1)[2:]})")
    print(f"corr of game offensive-zone time with projected total: {p[['game_oz', 'proj']].corr().iloc[0, 1]:+.3f}\n")

    # (1) team level
    rows = []
    for r in p.itertuples():
        rows.append((r.season, r.hg / r.lam_h - 1, r.home_oz_z, r.away_dz_z))
        rows.append((r.season, r.ag / r.lam_a - 1, r.away_oz_z, r.home_dz_z))
    t = pd.DataFrame(rows, columns=["season", "resid", "own_oz", "opp_dz"])
    print("(1) team goals vs projection, per 1 SD of last season's zone time (+ = scores more than projected)")
    for s, x in list(t.groupby("season")) + [("ALL", t)]:
        X = np.column_stack([np.ones(len(x)), x.own_oz, x.opp_dz])
        b = np.linalg.lstsq(X, x.resid.values, rcond=None)[0]
        lab = f"{s}-{str(s + 1)[2:]}" if s != "ALL" else "ALL"
        print(f"  {lab:8s} own offensive-zone time {b[1]:+.1%}   opponent's defensive-zone time {b[2]:+.1%}")

    # (2) P(7+) with game zone time, walk-forward
    out = []
    for s in sorted(p.season.unique()):
        tr = p[p.season < s]
        if tr.season.nunique() < 1 or s > 2025:
            continue
        te = p[p.season == s].copy()
        y = (tr.total >= 7).values.astype(float)
        gap = lambda d: (d.lam_h - d.lam_a).abs()
        b1 = m.logit_fit(np.column_stack([tr.proj, gap(tr)]), y)
        b2 = m.logit_fit(np.column_stack([tr.proj, gap(tr), tr.game_oz]), y)
        te["p1"] = 1 / (1 + np.exp(-(b1[0] + b1[1] * te.proj + b1[2] * gap(te))))
        te["p2"] = 1 / (1 + np.exp(-(b2[0] + b2[1] * te.proj + b2[2] * gap(te) + b2[3] * te.game_oz)))
        out.append(te)
    te = pd.concat(out)
    y = (te.total >= 7).values
    ll = lambda q: -np.mean(np.where(y, np.log(q), np.log(1 - q)))
    print(f"\n(2) P(7+) log loss {te.season.min()}-{str(te.season.max() + 1)[2:]} ({len(te)} games): live {ll(te.p1):.4f} | + zone time {ll(te.p2):.4f}  (lower = better)")

    # (3) projection adjustment from earlier seasons
    lp = lambda k_, lam: k_ * np.log(lam) - lam - np.array([lgamma(v + 1) for v in k_])
    adj = []
    for s, x in p.groupby("season"):
        tr = t[t.season < s]
        b = np.zeros(3)
        if len(tr):
            b = np.linalg.lstsq(np.column_stack([np.ones(len(tr)), tr.own_oz, tr.opp_dz]), tr.resid.values, rcond=None)[0] * 0.5
        kh = 1 + b[1] * x.home_oz_z + b[2] * x.away_dz_z
        ka = 1 + b[1] * x.away_oz_z + b[2] * x.home_dz_z
        adj.append(x.assign(lam_h=x.lam_h * kh, lam_a=x.lam_a * ka, proj=x.lam_h * kh + x.lam_a * ka))
    q = pd.concat(adj)
    lines = h.lines()
    full = sm.walk_split(g, known_starters=False, record_detail=True)
    print(f"\n(3) {'version':20s} {'goal LL 23-26':>13s}   {'SLAM+1U open':>32s}   {'SLAM+1U close':>32s}")
    for name, v in (("current", p), ("+ zone time", q)):
        tt = v[v.season.between(2023, 2025)]
        ll3 = -np.mean(np.r_[lp(tt.hg.values, tt.lam_h.values), lp(tt.ag.values, tt.lam_a.values)])
        vv = pd.concat([full[full.season < v.season.min()], v[full.columns.intersection(v.columns)]])  # 2020-21 kept for the cutoff
        d = h.flagged(vv).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2022) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        o = []
        for when in ("open", "close"):
            bb = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], when)
            hv = [bb[bb.season.isin(s)].prof.mean() for s in ((2022,), (2023, 2024, 2025))]
            o.append(f"{len(bb)} {bb.prof.sum():+.1f}u {bb.prof.mean():+.1%} ({hv[0]:+.1%}/{hv[1]:+.1%})")
        print(f"    {name:20s} {ll3:13.4f}   {o[0]:>32s}   {o[1]:>32s}")

    # (4) SLAM/1U by game zone time
    d = h.flagged(pd.concat([full[full.season < p.season.min()], p[full.columns]])).merge(lines, on=["gameDate", "home", "away"])
    d = d[(d.season >= 2022) & d.both].merge(p[["gameId", "game_oz"]], on="gameId")
    d = d[np.isin([dashboard.call(r, True) for r in d.itertuples()], ["SLAM", "1U"])]
    q1, q2 = np.quantile(p.game_oz, [1 / 3, 2 / 3])
    d["third"] = np.where(d.game_oz < q1, "low", np.where(d.game_oz < q2, "mid", "high"))
    print(f"\n(4) SLAM + 1U by both teams' offensive-zone time: {'when':5s} {'bets':>5s} {'W-L':>8s} {'ROI':>6s}")
    for th in ("low", "mid", "high"):
        for when in ("open", "close"):
            bb = h.bet_results(d[d.third == th], when)
            w, l_ = (bb.res > 0).sum(), (bb.res < 0).sum()
            print(f"    {th:4s} {when:5s} {len(bb):5d} {f'{w}-{l_}':>8s} {bb.prof.mean():+6.1%}")


if __name__ == "__main__":
    main()
