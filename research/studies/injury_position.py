"""Injured defensemen (Nov 10 2026 audit, M1): the live injury adjustment rates every skater against ALL skaters
(players.player_table) and one replacement level (0.90 offense / 1.10 defense). Half the offense rating is individual
goals and points, so most defensemen rate below replacement and losing one RAISES his team's projected goals.
Tested: rate forwards against forwards and defensemen against defensemen (player_table by_position=True); then the live
rating with the missing defensemen's effects shrunk (offense side x1/6 or x0; both sides x1/6), since the data says the
defensemen's part is about 6x too big (slope +0.17).

Same data and method as injury_backtest.py: who actually dressed 2021-26, players rated from seasons BEFORE the game,
the live size (injuries.SCALE). Prints the rating spread by position, how well each position's adjustment explains
goals the model missed (slope 1.0 = right size; a negative slope = the wrong direction), the shared scorecard with
error bars (research/lib/judge.py), and accuracy in team-games with a defenseman out.

  python3 research/studies/injury_position.py      # needs data/dressed.csv (research/lib/lineups_hist.py download)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from judge import ci_row, header, noise, row, scorecard, team_dev  # first: puts src/ on the path

import numpy as np
import pandas as pd

import injuries
import paths
import players
import split_model as sm
from injury_backtest import adjusted, missing_effects


def spread(season=2025):
    for label, kw in (("live (all skaters)", {}), ("by position", {"by_position": True})):
        t = players.player_table(season, **kw)
        t = t[t.toi_pg > 0]
        for g, x in t.groupby(t.position.eq("D").map({True: "D", False: "F"})):
            print(f"  {label:20s} {g}: {len(x):4d} players, median offense {x.f.median():.3f}, "
                  f"below the {players.REPLACEMENT[0]} replacement {(x.f < players.REPLACEMENT[0]).mean():.0%}, "
                  f"median defense {x.a.median():.3f}")


def fit_by_position(base, games, eff, pos):
    """Slope of (goals / projection - 1) on what the adjustment says, split into the missing forwards' part and the
    missing defensemen's part (own offense + the opponent's missing players' defense side), 2021-26."""
    x = base.merge(games[["gameId", "hg", "ag"]], on="gameId")
    rows = []
    for r in x[x.season >= 2021].itertuples():
        for team, opp, goals, lam in ((r.home, r.away, r.hg, r.lam_h), (r.away, r.home, r.ag, r.lam_a)):
            k, ko = (r.gameId, team), (r.gameId, opp)
            if k not in eff or ko not in eff:
                continue
            part = {"F": 0.0, "D": 0.0}
            for do, p_ in zip(eff[k][0], pos[k]):
                part[p_] -= do
            for dd, p_ in zip(eff[ko][1], pos[ko]):
                part[p_] += dd
            rows.append((goals / lam - 1, part["F"] * injuries.SCALE, part["D"] * injuries.SCALE))
    t = pd.DataFrame(rows, columns=["resid", "F", "D"])
    X = np.c_[np.ones(len(t)), t.F, t.D]
    beta = np.linalg.lstsq(X, t.resid.values, rcond=None)[0]
    return beta[1], beta[2], t.D.mean(), (t.D != 0).mean()


def shrink_d(eff, pos, k_off=1.0, k_def=1.0):
    """The live effects with each missing defenseman's offense / defense effect multiplied by k_off / k_def."""
    return {k: ([a * (k_off if p_ == "D" else 1.0) for a, p_ in zip(do, pos[k])],
                [b * (k_def if p_ == "D" else 1.0) for b, p_ in zip(dd, pos[k])]) for k, (do, dd) in eff.items()}


def main():
    games = sm.load_split()
    dressed = pd.read_csv(paths.data("dressed.csv"))
    base = sm.walk_split(games, known_starters=False, record_detail=True)
    print("Ratings, 2025-26 table (regulars with ice time):")
    spread()
    live_eff, pos = missing_effects(games, dressed, positions=True)
    new_eff = missing_effects(games, dressed, table=lambda s: players.player_table(s, by_position=True))
    print("\nDoes each position's adjustment explain goals the model missed? (slope 1.0 = right size, < 0 = wrong way)")
    for label, eff in (("live", live_eff), ("by position", new_eff)):
        sf, sd, md, share = fit_by_position(base, games, eff, pos)
        print(f"  {label:12s} forwards slope {sf:+.2f} | defensemen slope {sd:+.2f} "
              f"(mean D effect on a team's goals {md:+.4f}; {share:.0%} of team-games have one)")
    live = adjusted(base, live_eff, scale=injuries.SCALE)
    new = adjusted(base, new_eff, scale=injuries.SCALE)
    w = 34
    print("\n" + header(w))
    sc_live = scorecard(live, games)
    print(row("no injury adjustment", scorecard(base, games), w))
    print(row("live adjustment", sc_live, w))
    ci = noise(live, new, games)
    print(row("by position", scorecard(new, games), w, ci=ci))
    print(ci_row(ci, w))
    for label, k_off, k_def in (("D offense x1/6", 1 / 6, 1.0), ("D offense x0", 0.0, 1.0), ("D both sides x1/6", 1 / 6, 1 / 6)):
        v = adjusted(base, shrink_d(live_eff, pos, k_off, k_def), scale=injuries.SCALE)
        ci = noise(live, v, games)
        print(row(label, scorecard(v, games), w, ci=ci))
        print(ci_row(ci, w))
        sf, sd, md, _ = fit_by_position(base, games, shrink_d(live_eff, pos, k_off, k_def), pos)
        print(f"  {'':{w}s} forwards slope {sf:+.2f} | defensemen slope {sd:+.2f} (mean D effect {md:+.4f})")
    d_games = {gid for (gid, t), p_ in pos.items() if "D" in p_}
    only = dict.fromkeys(d_games, True)
    print(f"\nTeam-goal deviance in games with a defenseman out ({len(d_games)} games), lower = better:")
    for label, p in (("no adjustment", base), ("live", live), ("by position", new)):
        print(f"  {label:14s} 2021-23 {team_dev(p, games, (2021, 2022), only):.5f}   2023-26 {team_dev(p, games, (2023, 2025), only):.5f}")


if __name__ == "__main__":
    main()
