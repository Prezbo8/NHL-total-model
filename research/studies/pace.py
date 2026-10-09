"""Pace: do two 'track meet' teams (lots of shot attempts for + against) go 7+ more often than their projected
total says? Team pace = shot attempts for + against per 60 (all situations), built before each game like the
ratings (last season pulled 1/3 to league average, worth 15 games, then this season's games).
Game pace = both teams' pace vs league, in SDs.

(1) P(7+) from projected total alone (live) vs projected total + game pace: log loss on 2023-26, walk-forward
    (fit on 2022..season-1, like the live calibration).
(2) Within SLAM + 1U, results by game-pace third (both halves, open and close).

  python3 research/studies/pace.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import numpy as np
import pandas as pd

import dashboard
import history as h
import model as m
import split_model as sm

K, REG = 15, 1 / 3


def team_pace():
    """{gameId: (home pace, away pace)} in attempts (for + against) per 60, pre-game only."""
    d = pd.read_csv(m.DATA, usecols=["season", "gameId", "playerTeam", "home_or_away", "gameDate", "situation",
                                     "playoffGame", "iceTime", "shotAttemptsFor", "shotAttemptsAgainst"])
    d = d[(d.situation == "all") & (d.playoffGame == 0) & (d.season >= sm.FIRST_SEASON)].sort_values(["gameDate", "gameId"])
    d["att"] = d.shotAttemptsFor + d.shotAttemptsAgainst
    out, prior, cur = {}, {}, {}
    for season, sg in d.groupby("season", sort=True):
        if cur:  # season over: this season's rate becomes next season's prior, pulled toward league average
            rates = {t: a / s * 3600 for t, (a, s) in cur.items()}
            lg = np.mean(list(rates.values()))
            prior = {t: (1 - REG) * r + REG * lg for t, r in rates.items()}
        lg0 = np.mean(list(prior.values())) if prior else sg.att.sum() / sg.iceTime.sum() * 3600
        cur = {}
        for gid, gg in sg.groupby("gameId", sort=False):
            pace = {}
            for r in gg.itertuples():
                a, s = cur.get(r.playerTeam, (0.0, 0.0))
                p0 = prior.get(r.playerTeam, lg0)
                pace[r.home_or_away] = (p0 * K * 3600 + a * 3600) / (K * 3600 + s)  # K games of 60 min of prior
            out[gid] = (pace.get("HOME"), pace.get("AWAY"))
            for r in gg.itertuples():
                a, s = cur.get(r.playerTeam, (0.0, 0.0))
                cur[r.playerTeam] = (a + r.att, s + r.iceTime)
    return out


def main():
    p = sm.walk_split(sm.load_split(), known_starters=False, record_detail=True)
    pace = team_pace()
    p["pace"] = [sum(pace.get(g, (np.nan, np.nan))) for g in p.gameId]
    p = p.dropna(subset=["pace"])
    p["pace_z"] = p.groupby("season").pace.transform(lambda s: (s - s.mean()) / s.std())
    print("corr of game pace with projected total:", round(p[p.season >= 2021][["pace", "proj"]].corr().iloc[0, 1], 3))

    # (1) does pace add to P(7+)?
    rows = []
    for s in range(2023, 2026):
        tr, te = p[p.season.between(2022, s - 1)], p[p.season == s].copy()
        y = (tr.total >= 7).values.astype(float)
        b1 = m.logit_fit(tr[["proj"]].values, y)
        b2 = m.logit_fit(tr[["proj", "pace_z"]].values, y)
        te["p1"] = 1 / (1 + np.exp(-(b1[0] + b1[1] * te.proj)))
        te["p2"] = 1 / (1 + np.exp(-(b2[0] + b2[1] * te.proj + b2[2] * te.pace_z)))
        print(f"  fit 2022-{str(s)[2:]}: pace coefficient {b2[2]:+.3f} per SD (projected total {b2[1]:+.3f} per goal)")
        rows.append(te)
    te = pd.concat(rows)
    y = (te.total >= 7).values
    ll = lambda q: -np.mean(np.where(y, np.log(q), np.log(1 - q)))
    print(f"P(7+) log loss 2023-26 ({len(te)} games): projected total only {ll(te.p1):.4f} | + pace {ll(te.p2):.4f}  (lower = better)")
    te["pace_t"] = pd.qcut(te.pace_z, 3, labels=["slow", "mid", "fast"])
    print(te.groupby("pace_t", observed=True).apply(lambda x: f"{len(x)} games, P7 {x.p1.mean():.1%} -> went 7+ {(x.total >= 7).mean():.1%}",
                                                    include_groups=False).to_string())

    # (2) SLAM + 1U by pace third (cut points from all 2021-26 games, so the same for every season)
    d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both]
    d = d[np.isin([dashboard.call(r, True) for r in d.itertuples()], ["SLAM", "1U"])]
    q1, q2 = np.quantile(p[p.season >= 2021].pace_z, [1 / 3, 2 / 3])
    d["pace_t"] = np.where(d.pace_z < q1, "slow", np.where(d.pace_z < q2, "mid", "fast"))
    print(f"\nSLAM + 1U by game pace (league thirds): {'when':5s} {'bets':>5s} {'W-L':>8s} {'win%':>6s} {'ROI':>6s}   2021-22 / 2023-25")
    for t in ("slow", "mid", "fast"):
        for when in ("open", "close"):
            b = h.bet_results(d[d.pace_t == t], when)
            w, l_ = (b.res > 0).sum(), (b.res < 0).sum()
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            print(f"  {t:5s} {when:5s} {len(b):5d} {f'{w}-{l_}':>8s} {w / (w + l_):6.1%} {b.prof.mean():+6.1%}   {hv[0]:+.1%} / {hv[1]:+.1%}")


if __name__ == "__main__":
    main()
