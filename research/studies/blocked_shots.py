"""Blocked shots (Oct 19 2026): does shot blocking make the projection more accurate? xG (MoneyPuck) only counts
unblocked attempts, so a team that blocks a lot already looks better defensively; this asks whether blocks add
anything on top. MoneyPuck game file, all situations. For every team-game 2021-26, each team's numbers from its
earlier games this season only (shrunk toward league average by K games), centered on league average. Rink scorers
count blocks differently, so a second version uses road games only.
Features for a team's goals in a game:
  shot : share of the team's OWN attempts that get blocked (a team that can't get shots through)
  blk  : share of the OPPONENT's attempts it blocks (the defense's blocking)
  game : both teams' blocks a game, per 10 (a high-block matchup -> fewer goals for both = moves the total)
  0. is it a team trait? first half vs second half of each season (correlation), all games and road only
  1. slope of the team-goal miss (goals / projected - 1) per unit, 2021-23 and 2023-26
  2. scorecard (research/lib/judge.py), slopes fitted on 2021-23

  python3 research/studies/blocked_shots.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import header, row, scorecard  # first: puts src/ on the path
import numpy as np
import pandas as pd

import model as m
import split_model as sm

K = 10  # games of league average mixed into each team's rates
FEATS = (("game",), ("shot", "blk"), ("shot",), ("blk",))
UNIT = {"shot": 0.10, "blk": 0.10, "game": 10.0}  # slopes per 10 percentage points / per 10 blocks a game


def load_blocks(games):
    d = pd.read_csv(m.DATA, usecols=["gameId", "situation", "home_or_away", "playoffGame", "blockedShotAttemptsFor",
                                     "shotAttemptsFor", "blockedShotAttemptsAgainst", "shotAttemptsAgainst"])
    d = d[(d.playoffGame == 0) & (d.situation == "all")].drop_duplicates(["gameId", "home_or_away"])
    d = d[d.gameId.isin(games.gameId)]
    side = games.set_index("gameId")
    d["team"] = np.where(d.home_or_away == "HOME", side.home.reindex(d.gameId).values, side.away.reindex(d.gameId).values)
    d["season"] = side.season.reindex(d.gameId).values
    d["game_blocks"] = d.blockedShotAttemptsFor + d.blockedShotAttemptsAgainst
    return d.sort_values("gameId")


def rates(b, road_only):
    """Per team-game, before the game: shot (own attempts blocked %), blk (opponent attempts blocked %), game (blocks a
    game), each centered on league average. Returns home and away frames indexed by gameId."""
    lg = {"shot": b.blockedShotAttemptsFor.sum() / b.shotAttemptsFor.sum(), "game": b.game_blocks.mean()}
    lg["blk"] = lg["shot"]
    att = b.shotAttemptsFor.mean()
    out = []
    for _, x in b.groupby(["team", "season"]):
        x = x.copy()
        use = ((x.home_or_away == "AWAY") if road_only else pd.Series(True, index=x.index)).astype(int)
        prior = lambda s: (s * use).cumsum().shift(1).fillna(0)
        n = prior(pd.Series(1, index=x.index))
        x["shot"] = (prior(x.blockedShotAttemptsFor) + K * att * lg["shot"]) / (prior(x.shotAttemptsFor) + K * att) - lg["shot"]
        x["blk"] = (prior(x.blockedShotAttemptsAgainst) + K * att * lg["blk"]) / (prior(x.shotAttemptsAgainst) + K * att) - lg["blk"]
        x["game"] = (prior(x.game_blocks) + K * lg["game"]) / (n + K) - lg["game"]
        out.append(x)
    r = pd.concat(out)
    cols = ["gameId", "shot", "blk", "game"]
    return r[r.home_or_away == "HOME"][cols].set_index("gameId"), r[r.home_or_away == "AWAY"][cols].set_index("gameId")


def features(proj, b, road_only):
    rh, ra = rates(b, road_only)
    x = proj.join(rh.add_suffix("_H"), on="gameId").join(ra.add_suffix("_A"), on="gameId").dropna(subset=["shot_H", "shot_A"])
    x["shot_h"], x["shot_a"] = x.shot_H / UNIT["shot"], x.shot_A / UNIT["shot"]   # home goals: home's own attempts blocked
    x["blk_h"], x["blk_a"] = x.blk_A / UNIT["blk"], x.blk_H / UNIT["blk"]         # home goals: away team's blocking
    x["game_h"] = x["game_a"] = (x.game_H + x.game_A) / UNIT["game"]
    return x


def slope(x, games, seasons, feats):
    d = x[x.season.between(*seasons)].merge(games[["gameId", "hg", "ag"]], on="gameId")
    y = np.r_[d.hg / d.lam_h - 1, d.ag / d.lam_a - 1]
    X = np.column_stack([np.r_[d[f + "_h"], d[f + "_a"]] for f in feats])
    return np.linalg.lstsq(np.column_stack([np.ones(len(y)), X]), y, rcond=None)[0][1:]


def adjusted(p, x, b):
    q, xx = p.set_index("gameId").copy(), x.set_index("gameId")
    for s in ("h", "a"):
        q.loc[xx.index, f"lam_{s}"] = q.loc[xx.index, f"lam_{s}"] * (1 + sum(v * xx[f"{f}_{s}"] for f, v in b.items()))
    q["proj"] = q.lam_h + q.lam_a
    return q.reset_index()


def main():
    games = sm.load_split()
    proj = sm.walk_split(games, known_starters=False, record_detail=True)
    b = load_blocks(games)
    print(f"team-games matched: {len(b)} of {len(games) * 2}; league average {b.game_blocks.mean():.1f} blocks a game, "
          f"{b.blockedShotAttemptsFor.sum() / b.shotAttemptsFor.sum():.1%} of attempts blocked")

    print("\n0. Is it a team trait? first half vs second half of each season (correlation, 2021-26 average)")
    b = b.assign(shot_pct=b.blockedShotAttemptsFor / b.shotAttemptsFor, blk_pct=b.blockedShotAttemptsAgainst / b.shotAttemptsAgainst)
    for name, road in (("all games", False), ("road games only", True)):
        cells = []
        for col, lab in (("shot_pct", "own attempts blocked %"), ("blk_pct", "blocks opp attempts %"), ("game_blocks", "blocks a game")):
            r = []
            for _, x in b[b.season.between(2021, 2025)].groupby("season"):
                x = x[x.home_or_away == "AWAY"] if road else x
                x = x.assign(half=x.groupby("team").cumcount() < x.groupby("team").team.transform("size") / 2)
                r.append(x.groupby(["team", "half"])[col].mean().unstack().corr().iloc[0, 1])
            cells.append(f"{lab} {np.mean(r):.2f}")
        print(f"   {name:16s} " + ", ".join(cells))

    base = scorecard(proj, games)
    for name, road in (("ALL GAMES", False), ("ROAD GAMES ONLY (no rink scorer bias)", True)):
        x = features(proj, b, road)
        print(f"\n--- {name} ---")
        print("1. slope of team-goal miss (-0.02 = 2% fewer goals) per 10 pct points (shot, blk) / per 10 blocks a game (game)")
        for feats in FEATS[:2]:
            s1, s2 = slope(x, games, (2021, 2022), feats), slope(x, games, (2023, 2025), feats)
            print(f"   {' + '.join(feats):12s} 2021-23 {', '.join(f'{v:+.3f}' for v in s1):16s} 2023-26 {', '.join(f'{v:+.3f}' for v in s2)}")
        print("2. " + header(26))
        print("   " + row("model as is", base, 26))
        for feats in FEATS:
            fit = dict(zip(feats, slope(x, games, (2021, 2022), feats)))
            print("   " + row("+ " + " + ".join(feats), scorecard(adjusted(proj, x, fit), games), 26, base))


if __name__ == "__main__":
    main()
