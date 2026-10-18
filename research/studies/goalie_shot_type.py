"""Goalie vs shot-type matchup (suggestion #5, Oct 18 2026). The live goalie adjustment is one number per goalie (goals
saved above xG per xG faced). Some goalies are much better on high-danger chances than on the rest; if so, a goalie's
real edge tonight depends on how much of the opponent's xG comes from high-danger shots.

Goalie split, from the three seasons before the game's season (MoneyPuck season summaries, all situations,
data/mp_seasons/goalies_*.csv): hd = (HD xG - HD goals) / (HD xG + SHRINK), rest = the same for everything else.
Opponent profile: its share of xG from high-danger shots, last season blended with this season to date (last season
worth 15 games). Expected change to the goalie's skill tonight = (opp share - league share) x (hd - rest); the team's
projected goals are multiplied by (1 - c x that). c = 1 is the plain arithmetic, c = 0 the live model.
Actual starters (known_starters=True) on both sides, so the right goalie is matched.

  1. Is the split real? (hd - rest, earlier seasons vs the next season)
  2. Scorecard by c.

  python3 research/studies/goalie_shot_type.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import header, row, scorecard  # first: puts src/ on the path
import numpy as np
import pandas as pd

import paths
import split_model as sm
import model as m

MP = "https://moneypuck.com/moneypuck/playerData/seasonSummary/{}/regular/goalies.csv"
SHRINK = 40


def goalie_table(first=2017, last=2025):
    import players
    parts = []
    for s in range(first, last + 1):
        f = paths.data(f"mp_seasons/goalies_{s}.csv")
        if not _os.path.exists(f):
            _os.makedirs(_os.path.dirname(f), exist_ok=True)
            open(f, "wb").write(players.get(MP.format(s)))
        d = pd.read_csv(f)
        d = d[d.situation == "all"]
        parts.append(pd.DataFrame({"playerId": d.playerId, "season": s, "xg": d.xGoals, "g": d.goals,
                                   "hdxg": d.highDangerxGoals, "hdg": d.highDangerGoals}))
    return pd.concat(parts)


def splits(gt, s):
    """{playerId: hd skill - rest skill} from seasons s-3..s-1."""
    p = gt[gt.season.between(s - 3, s - 1)].groupby("playerId")[["xg", "g", "hdxg", "hdg"]].sum()
    hd = (p.hdxg - p.hdg) / (p.hdxg + SHRINK)
    rest = ((p.xg - p.hdxg) - (p.g - p.hdg)) / ((p.xg - p.hdxg) + SHRINK)
    return (hd - rest).to_dict()


def opp_share(first=2020):
    """{(gameId, team): the team's high-danger share of xG before that game, last season worth 15 games of it}, and the
    league share."""
    tg = sm.team_games(first - 1).sort_values(["date", "gameId"])
    lg = tg.hdxgF.sum() / tg.xgF.sum()
    out = {}
    for t, d in tg.groupby("team"):
        for s, ds in d.groupby("season"):
            prev = d[d.season == s - 1]
            prior = prev.hdxgF.sum() / prev.xgF.sum() if len(prev) and prev.xgF.sum() else lg
            xg_pg = prev.xgF.mean() if len(prev) else ds.xgF.mean()
            hd_sum, xg_sum = 15 * prior * xg_pg, 15 * xg_pg
            for gid, a, b in zip(ds.gameId, ds.hdxgF, ds.xgF):
                out[(gid, t)] = hd_sum / xg_sum
                hd_sum, xg_sum = hd_sum + a, xg_sum + b
    return out, lg


def main():
    gt = goalie_table()
    # 1. persistence of the split for goalies with real workloads
    pairs = []
    for s in range(2020, 2026):
        sp = splits(gt, s)
        nxt = gt[(gt.season == s) & (gt.xg >= 40)]
        for p_, xg, g, hx, hg in zip(nxt.playerId, nxt.xg, nxt.g, nxt.hdxg, nxt.hdg):
            if p_ in sp and hx > 0 and xg - hx > 0:
                pairs.append((sp[p_], (hx - hg) / hx - ((xg - hx) - (g - hg)) / (xg - hx)))
    a, b = np.array(pairs).T
    print(f"1. goalie high-danger minus other-shot skill, 3 earlier seasons vs the next season: r = {np.corrcoef(a, b)[0, 1]:.2f} "
          f"({len(pairs)} goalie-seasons with 40+ xG faced)\n")
    games = sm.load_split()
    share, lg = opp_share()
    starter = m.load_goalies()[0]
    base_p = sm.walk_split(games, known_starters=True, record_detail=True)
    feats = {}
    for s in range(2020, 2026):
        sp = splits(gt, s)
        for r in base_p[base_p.season == s].itertuples():
            for side, att, dfn in (("h", r.home, r.away), ("a", r.away, r.home)):
                g = starter.get((r.gameId, dfn))
                feats[(r.gameId, side)] = (share.get((r.gameId, att), lg) - lg) * sp.get(g, 0.0)
    f = np.array(list(feats.values()))
    print(f"   matchup term: sd {f.std():.4f}, 5th-95th pct {np.percentile(f, 5):+.4f} .. {np.percentile(f, 95):+.4f}\n")
    print("2. " + header(30))
    base = scorecard(base_p, games)
    print("   " + row("live, actual starters (c = 0)", base, 30))
    half = sm.EXTRA / 2
    for c in (1.0, 2.0, 4.0):
        q = base_p.copy()
        for side in ("h", "a"):
            x = np.array([feats.get((g, side), 0.0) for g in q.gameId])
            q[f"lam_{side}"] = (q[f"lam_{side}"] - half) * (1 - c * x) + half
        q["proj"] = q.lam_h + q.lam_a
        print("   " + row(f"c = {c}", scorecard(q, games), 30, base))


if __name__ == "__main__":
    main()
