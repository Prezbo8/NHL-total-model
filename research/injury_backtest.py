"""Backtest the injury / lineup adjustment (src/injuries.py) on who actually dressed, 2021-26.

Missing = a regular (dressed in 5+ of the team's last 10 games this season) who isn't in tonight's 18
skaters, unless he has since dressed for another team (traded). Each team's first 5 games of a season are
skipped. Players are rated from seasons BEFORE the game's season only (no hindsight), with the live
formula: share of ice time x (player - replacement) x in_rating.

Uses actual lineups, so this is the best case: live, the model only knows the projected lineup.

  python3 research/injury_backtest.py      # needs data/dressed.csv (research/lineups_hist.py download)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from collections import defaultdict, deque

import numpy as np
import pandas as pd

import compare
import history
import injuries
import odds
import paths
import players
import split_model as sm

K, SECS = injuries.K, injuries.SKATER_SECONDS


def missing_effects(games, dressed):
    """{(gameId, team): (d_off list, d_def list)} for every team-game, from who didn't dress."""
    dz = dressed[dressed.pos != "G"]
    by_game = {k: set(v) for k, v in dz.groupby(["gameId", "team"]).playerId}
    sk = pd.read_csv(players.SKATERS)
    tables = {}
    out = {}
    last10 = defaultdict(lambda: deque(maxlen=10))  # team -> sets of dressed players, this season
    played_for = defaultdict(lambda: defaultdict(int))  # (season, team) -> player -> games dressed so far
    team_n = defaultdict(int)  # (season, team) -> games so far
    last_team = {}  # player -> team he last dressed for
    season_prev = None
    for g in games.sort_values(["gameDate", "gameId"]).itertuples():
        if g.season != season_prev:
            last10.clear(); season_prev = g.season
        if g.season not in tables:
            pt = players.player_table(g.season - 1).set_index("playerId")  # seasons before this one only
            last = sk[sk.season == g.season - 1].set_index("playerId")
            tables[g.season] = (pt, last)
        pt, last = tables[g.season]
        for team in (g.home, g.away):
            tonight = by_game.get((g.gameId, team))
            if tonight is None:
                continue
            hist = last10[team]
            d_off, d_def = [], []
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
                    gp_cur = played_for[(g.season, team)][p]
                    w_cur = gp_cur / n if n else 0.0
                    w_last = min(last.games_played.get(p, 0) / 82, 1.0) if last.team.get(p) == team else 0.0
                    in_rating = (K * w_last + n * w_cur) / (K + n)
                    share = r.toi_pg / SECS if r.toi_pg else 0.0
                    d_off.append(share * (r.f - players.REPLACEMENT[0]) * in_rating)
                    d_def.append(share * (players.REPLACEMENT[1] - r.a) * in_rating)
            out[(g.gameId, team)] = (d_off, d_def)
            hist.append(tonight)
            team_n[(g.season, team)] += 1
            for p in tonight:
                played_for[(g.season, team)][p] += 1
                last_team[p] = team
    return out


def adjusted(base, eff, scale=1.0, clamp=False, min_effect=0.002):
    """Projections with the injury adjustment applied (scale = multiplier on its size)."""
    p = base.copy()
    mult = {}
    for (gid, team), (do, dd) in eff.items():
        off = deff = 1.0
        for a, b in zip(do, dd):
            if clamp:
                a, b = max(a, 0.0), max(b, 0.0)
            if abs(a) + abs(b) < min_effect:
                continue
            off *= 1 - scale * a
            deff *= 1 + scale * b
        mult[(gid, team)] = (off, deff)
    one = (1.0, 1.0)
    p["lam_h"] = [lh * mult.get((gid, h), one)[0] * mult.get((gid, a), one)[1]
                  for gid, h, a, lh in zip(p.gameId, p.home, p.away, p.lam_h)]
    p["lam_a"] = [la * mult.get((gid, a), one)[0] * mult.get((gid, h), one)[1]
                  for gid, h, a, la in zip(p.gameId, p.home, p.away, p.lam_a)]
    p["proj"] = p.lam_h + p.lam_a
    return p


def team_dev(p, games, seasons):
    x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
    x = x[x.season.between(*seasons)]
    dev = lambda y, lam: 2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / lam), 0) - (y - lam))
    return np.concatenate([dev(x.hg, x.lam_h), dev(x.ag, x.lam_a)]).mean()


def rule(p, first=2024):
    d = history.flagged(p).merge(history.lines(), on=["gameDate", "home", "away"])
    d = d[d.season >= first]
    out = []
    for when in ("open", "close"):
        b = history.bet_results(d, when); dec = b[b.res != 0]
        out.append(f"{len(b)} bets {(dec.res > 0).mean():.1%} {b.prof.mean():+.1%}")
    return out


def main():
    games = sm.load_split()
    dressed = pd.read_csv(paths.data("dressed.csv"))
    base = sm.walk_split(games, known_starters=False)
    eff = missing_effects(games, dressed)
    tg = [(len(do), sum(do), sum(dd)) for (gid, t), (do, dd) in eff.items()]
    n_miss = np.array([x[0] for x in tg]); off = np.array([x[1] for x in tg])
    print(f"team-games with lineups: {len(eff)} | avg regulars missing: {n_miss.mean():.2f} | "
          f"avg offense removed: {off.mean():+.2%} (90th pct {np.quantile(off, 0.9):+.2%})")

    # does who's missing explain goals the model got wrong? (2021-26, team level)
    x = base.merge(games[["gameId", "hg", "ag"]], on="gameId")
    rows = []
    for r in x.itertuples():
        for team, opp, goals, lam in ((r.home, r.away, r.hg, r.lam_h), (r.away, r.home, r.ag, r.lam_a)):
            if (r.gameId, team) in eff and (r.gameId, opp) in eff:
                rows.append((r.season, goals / lam - 1, -sum(eff[(r.gameId, team)][0]), sum(eff[(r.gameId, opp)][1])))
    t = pd.DataFrame(rows, columns=["season", "resid_pct", "own_off", "opp_def"])
    t = t[t.season >= 2021]
    t["expected"] = t.own_off + t.opp_def  # what the adjustment says this team's scoring should change
    slope = np.polyfit(t.expected, t.resid_pct, 1)[0]
    print(f"\nGoals vs model explained by the adjustment (team-games 2021-26: {len(t)}): corr {t.expected.corr(t.resid_pct):+.3f}, "
          f"slope {slope:.2f} (1.0 = the adjustment is exactly the right size, 0 = no effect)")
    for s in ((2021, 2023), (2024, 2025)):
        u = t[t.season.between(*s)]
        print(f"   {s[0]}-{str(s[1] + 1)[2:]}: corr {u.expected.corr(u.resid_pct):+.3f}, slope {np.polyfit(u.expected, u.resid_pct, 1)[0]:.2f}")
    q = pd.qcut(t.expected, 5, labels=["biggest loss", "2", "3", "4", "smallest loss/gain"], duplicates="drop")
    print(t.groupby(q, observed=True).agg(team_games=("expected", "size"), adjustment=("expected", "mean"),
                                          goals_vs_model=("resid_pct", "mean")).round(4).to_string())

    print(f"\n{'variant':34s} {'team dev 24-26':>14s} {'LL close':>9s} {'LL open':>8s} | 2024-26 overs rule OPEN | CLOSE")
    variants = [("no adjustment (backtest baseline)", base)]
    for name, kw in (("live formula (all missing = out)", {}), ("live formula, hurt-only (clamped)", {"clamp": True}),
                     ("half size", {"scale": 0.5}), ("1.5x size", {"scale": 1.5}), ("2x size", {"scale": 2.0})):
        variants.append((name, adjusted(base, eff, **kw)))
    for name, p in variants:
        llc = compare.score(p, odds.ODDS)[1]; llo = compare.score(p, odds.ODDS_OPEN)[1]
        r = rule(p)
        print(f"{name:34s} {team_dev(p, games, (2024, 2025)):14.4f} {llc:9.4f} {llo:8.4f} | {r[0]} | {r[1]}")


if __name__ == "__main__":
    main()
