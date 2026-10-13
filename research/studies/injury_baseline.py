"""Who replaces a missing player? The live injury adjustment measures each missing regular against a REPLACEMENT-level
skater (call-up: 90% of average offense, 110% of average goals against). Alternative: his minutes go to the team's
2nd/3rd-line players moving up, i.e. a better baseline (closer to an average skater) -> smaller effects.

Same data as injury_backtest.py (who actually dressed, 2021-26, ratings from seasons before the game only); player
ratings are unchanged, only the baseline each missing player is measured against moves. Live size 1.15x throughout.
Reports projection accuracy first (team-goal deviance, log loss vs closing / opening totals), then the measured slope
(1.0 = 1.15x is exactly the right size at that baseline; above 1 = effect too small).

  python3 research/studies/injury_baseline.py      # needs data/dressed.csv (research/lib/lineups_hist.py download)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from collections import defaultdict, deque

import numpy as np
import pandas as pd

import compare
import injuries
import odds
import paths
import players
import split_model as sm
from injury_backtest import adjusted, team_dev

K, SECS = injuries.K, injuries.SKATER_SECONDS


def missing_parts(games, dressed):
    """{(gameId, team): [(share x in_rating, f, a)]} for each missing regular (same rules as injury_backtest.missing_effects),
    so the effect can be recomputed against any baseline: share x in_rating x (f - base_off), x (base_def - a)."""
    dz = dressed[dressed.pos != "G"]
    by_game = {k: set(v) for k, v in dz.groupby(["gameId", "team"]).playerId}
    sk = pd.read_csv(players.SKATERS)
    tables, out = {}, {}
    last10 = defaultdict(lambda: deque(maxlen=10))
    played_for = defaultdict(lambda: defaultdict(int))
    team_n = defaultdict(int)
    last_team = {}
    season_prev = None
    for g in games.sort_values(["gameDate", "gameId"]).itertuples():
        if g.season != season_prev:
            last10.clear(); season_prev = g.season
        if g.season not in tables:
            tables[g.season] = (players.player_table(g.season - 1).set_index("playerId"), sk[sk.season == g.season - 1].set_index("playerId"))
        pt, last = tables[g.season]
        for team in (g.home, g.away):
            tonight = by_game.get((g.gameId, team))
            if tonight is None:
                continue
            hist = last10[team]
            parts = []
            if len(hist) >= 5:
                counts = defaultdict(int)
                for s in hist:
                    for p in s:
                        counts[p] += 1
                n = team_n[(g.season, team)]
                for p, c in counts.items():
                    if c < 5 or p in tonight or last_team.get(p) != team or p not in pt.index:
                        continue
                    r = pt.loc[p]
                    w_cur = played_for[(g.season, team)][p] / n if n else 0.0
                    w_last = min(last.games_played.get(p, 0) / 82, 1.0) if last.team.get(p) == team else 0.0
                    in_rating = (K * w_last + n * w_cur) / (K + n)
                    share = r.toi_pg / SECS if r.toi_pg else 0.0
                    parts.append((share * in_rating, r.f, r.a))
            out[(g.gameId, team)] = parts
            hist.append(tonight)
            team_n[(g.season, team)] += 1
            for p in tonight:
                played_for[(g.season, team)][p] += 1
                last_team[p] = team
    return out


def effects(parts, base_off, base_def):
    return {k: ([w * (f - base_off) for w, f, a in v], [w * (base_def - a) for w, f, a in v]) for k, v in parts.items()}


def slope(base, eff, games):
    x = base.merge(games[["gameId", "hg", "ag"]], on="gameId")
    rows = []
    for r in x.itertuples():
        for team, opp, goals, lam in ((r.home, r.away, r.hg, r.lam_h), (r.away, r.home, r.ag, r.lam_a)):
            if (r.gameId, team) in eff and (r.gameId, opp) in eff and r.season >= 2021:
                rows.append((goals / lam - 1, -sum(eff[(r.gameId, team)][0]) + sum(eff[(r.gameId, opp)][1])))
    t = np.array(rows)
    return np.polyfit(t[:, 1], t[:, 0], 1)[0] / injuries.SCALE  # 1.0 = the live 1.15x is exactly the right size


def main():
    games = sm.load_split()
    base = sm.walk_split(games, known_starters=False)
    parts = missing_parts(games, pd.read_csv(paths.data("dressed.csv")))
    print(f"{'baseline (offense / defense)':42s} {'team dev 21-26':>14s} {'team dev 24-26':>14s} {'LL close':>9s} {'LL open':>8s} {'slope':>6s}")
    print(f"{'no injury adjustment':42s} {team_dev(base, games, (2021, 2025)):14.4f} {team_dev(base, games, (2024, 2025)):14.4f} "
          f"{compare.score(base, odds.ODDS)[1]:9.4f} {compare.score(base, odds.ODDS_OPEN)[1]:8.4f}")
    for name, bo, bd in (("call-up 0.90 / 1.10 (live)", 0.90, 1.10), ("between 0.95 / 1.05", 0.95, 1.05),
                         ("2nd/3rd-line player 1.00 / 1.00 (average)", 1.00, 1.00), ("worse than call-up 0.85 / 1.15", 0.85, 1.15)):
        eff = effects(parts, bo, bd)
        p = adjusted(base, eff, scale=injuries.SCALE)
        print(f"{name:42s} {team_dev(p, games, (2021, 2025)):14.4f} {team_dev(p, games, (2024, 2025)):14.4f} "
              f"{compare.score(p, odds.ODDS)[1]:9.4f} {compare.score(p, odds.ODDS_OPEN)[1]:8.4f} {slope(base, eff, games):6.2f}")


if __name__ == "__main__":
    main()
