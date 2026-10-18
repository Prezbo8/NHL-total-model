"""Shooter talent (suggestion #4, Oct 18 2026). Some players beat their xG year after year (elite shooters), so a team
dressing several of them should out-finish its xG. Each skater's finishing skill = (goals - xG) / (xG + SHRINK) over
the three seasons before the game's season (MoneyPuck season summaries, all situations; data/mp_seasons/, cached by
this script's first run). A team's finishing edge tonight = the skill of the skaters who actually dressed
(data/dressed.csv), weighted by their individual xG per game in those seasons. The projection's scaled part is
multiplied by (1 + c x edge); c = 0 is the live model.

  1. Does finishing skill repeat? (player goals - xG, earlier seasons vs the next season)
  2. Scorecard by c (and by SHRINK).

  python3 research/studies/shooter_talent.py      # needs data/dressed.csv (research/lib/lineups_hist.py)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import header, row, scorecard  # first: puts src/ on the path
import numpy as np
import pandas as pd

import paths
import split_model as sm

MP = "https://moneypuck.com/moneypuck/playerData/seasonSummary/{}/regular/skaters.csv"


def seasons_table(first=2017, last=2025):
    """playerId, season, games, ixg, goals (all situations), downloaded once into data/mp_seasons/."""
    import players
    parts = []
    for s in range(first, last + 1):
        f = paths.data(f"mp_seasons/skaters_{s}.csv")
        if not _os.path.exists(f):
            _os.makedirs(_os.path.dirname(f), exist_ok=True)
            open(f, "wb").write(players.get(MP.format(s)))
        d = pd.read_csv(f)
        d = d[d.situation == "all"]
        parts.append(pd.DataFrame({"playerId": d.playerId, "season": s, "games": d.games_played, "ixg": d.I_F_xGoals, "goals": d.I_F_goals}))
    return pd.concat(parts)


def skills(st, shrink):
    """{(season, playerId): (finishing skill, xG per game)} from the three seasons before `season`."""
    out = {}
    for s in range(2020, 2027):
        past = st[st.season.between(s - 3, s - 1)].groupby("playerId")[["games", "ixg", "goals"]].sum()
        past = past[past.games > 0]
        sk = (past.goals - past.ixg) / (past.ixg + shrink)
        for pid, v, xpg in zip(past.index, sk, past.ixg / past.games):
            out[(s, pid)] = (v, xpg)
    return out


def edges(dressed, sk):
    """{(gameId, team): xG-weighted finishing skill of the skaters who dressed}."""
    dz = dressed[dressed.pos != "G"]
    out = {}
    for (gid, team), d in dz.groupby(["gameId", "team"]):
        s = int(str(gid)[:4])
        vals = [sk.get((s, p)) for p in d.playerId]
        vals = [v for v in vals if v]
        w = sum(x for _, x in vals)
        out[(gid, team)] = sum(v * x for v, x in vals) / w if w else 0.0
    # centered per season: players who keep dressing are better finishers than average, which would otherwise lift
    # every projection; only a team's edge over the league's typical lineup should count
    by_s = {}
    for (gid, _), v in out.items():
        by_s.setdefault(int(str(gid)[:4]), []).append(v)
    mean = {s: np.mean(v) for s, v in by_s.items()}
    return {k: v - mean[int(str(k[0])[:4])] for k, v in out.items()}


def adjusted(p, edge, c):
    q = p.copy()
    half = sm.EXTRA / 2
    for side, team in (("h", "home"), ("a", "away")):
        e = np.array([edge.get((g, t), 0.0) for g, t in zip(q.gameId, q[team])])
        q[f"lam_{side}"] = (q[f"lam_{side}"] - half) * (1 + c * e) + half
    q["proj"] = q.lam_h + q.lam_a
    return q


def main():
    st = seasons_table()
    games = sm.load_split()
    # 1. persistence: skill from s-3..s-1 vs the same player's goals - xG in season s (per xG)
    sk = skills(st, 30)
    nxt = st[(st.season >= 2020) & (st.ixg >= 10)]
    pairs = [(sk[(s, p)][0], (g - x) / x) for p, s, g, x in zip(nxt.playerId, nxt.season, nxt.goals, nxt.ixg) if (s, p) in sk]
    a, b = np.array(pairs).T
    print(f"1. finishing skill (3 earlier seasons, shrunk) vs next season's (goals - xG) / xG: r = {np.corrcoef(a, b)[0, 1]:.2f} "
          f"({len(pairs)} player-seasons with 10+ xG); slope {np.polyfit(a, b, 1)[0]:.2f}\n")
    dressed = pd.read_csv(paths.data("dressed.csv"))
    base_p = sm.walk_split(games, known_starters=False, record_detail=True)
    print("2. " + header(30))
    base = scorecard(base_p, games)
    print("   " + row("live (c = 0)", base, 30))
    for shrink in (30, 60):
        edge = edges(dressed, skills(st, shrink))
        e = np.array(list(edge.values()))
        print(f"   -- shrink {shrink} xG: team edge sd {e.std():.3f}, 5th-95th pct {np.percentile(e, 5):+.3f} .. {np.percentile(e, 95):+.3f}")
        for c in (0.25, 0.5, 1.0):
            print("   " + row(f"c = {c}", scorecard(adjusted(base_p, edge, c), games), 30, base))


if __name__ == "__main__":
    main()
