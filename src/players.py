"""Player-based starting ratings.

A team's preseason rating = its current skaters' past on-ice expected goals
for/against per 60, weighted by how much each one plays. Catches summer roster
changes that last season's team numbers can't see.
"""
import io
import os
import time
import urllib.request

import pandas as pd
import paths

SKATERS = paths.data("skater_seasons.csv")
LINEUPS = paths.data("opening_lineups.csv")
MP_SKATERS = "https://moneypuck.com/moneypuck/playerData/seasonSummary/{}/regular/skaters.csv"
SEASON_W = (1.0, 0.5, 0.25)  # weight of the last 3 seasons
SHRINK_MIN = 400     # minutes of "replacement level" mixed into every player
REPLACEMENT = (0.9, 1.1)  # replacement player: 90% of avg xGF/60, 110% of avg xGA/60


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as f:
        return f.read()


def refresh_skaters(seasons):
    """MoneyPuck season totals per skater (all situations)."""
    old = pd.read_csv(SKATERS) if os.path.exists(SKATERS) else pd.DataFrame(columns=["season"])
    parts = [old[~old.season.isin(seasons)]]
    for s in seasons:
        d = pd.read_csv(io.BytesIO(get(MP_SKATERS.format(s))))
        d = d[d.situation == "all"]
        parts.append(d[["playerId", "season", "name", "team", "position", "games_played", "icetime", "OnIce_F_xGoals",
                        "OnIce_A_xGoals", "OnIce_F_goals", "OnIce_A_shotsOnGoal", "I_F_goals", "I_F_points"]])
        time.sleep(2)
    pd.concat(parts).to_csv(SKATERS, index=False)


# player rating = 50% advanced + 50% regular stats (weights fixed up front, not tuned)
OFFENSE = {"OnIce_F_xGoals": 0.5, "OnIce_F_goals": 1 / 6, "I_F_goals": 1 / 6, "I_F_points": 1 / 6}
DEFENSE = {"OnIce_A_xGoals": 0.5, "OnIce_A_shotsOnGoal": 0.5}


def player_table(season, min_season=2020, season_w=(1.0, 0.7, 0.4), offense=None, defense=None, shrink_min=None):
    """One row per skater: offense/defense ratios vs league average (1.0 = average, same 50% advanced /
    50% regular formula as roster_ratings, shrunk toward replacement for low minutes), plus games
    played and ice time per game this season and last. Uses seasons season-2..season (never before
    min_season), INCLUDING the current season - this is for live use, not backtests.
    season_w / offense / defense / shrink_min: research overrides (research/studies/player_weights.py); defaults = live."""
    offense, defense = offense or OFFENSE, defense or DEFENSE
    shrink_min = SHRINK_MIN if shrink_min is None else shrink_min
    sk = pd.read_csv(SKATERS)
    first = max(season - 2, min_season)
    past = sk[sk.season.between(first, season)].copy()
    past["w"] = past.season.map({season - i: w for i, w in enumerate(season_w)})
    stats = list(dict.fromkeys(list(offense) + list(defense)))
    lg = {c: past[c].sum() / past.icetime.sum() for c in stats}
    wt = past.assign(**{c: past[c] * past.w for c in stats + ["icetime"]})
    agg = wt.groupby("playerId")[stats + ["icetime"]].sum()
    shrink = shrink_min * 60
    agg["f"] = sum(w * (agg[c] + shrink * lg[c] * REPLACEMENT[0]) / (agg.icetime + shrink) / lg[c] for c, w in offense.items())
    agg["a"] = sum(w * (agg[c] + shrink * lg[c] * REPLACEMENT[1]) / (agg.icetime + shrink) / lg[c] for c, w in defense.items())
    cur = sk[sk.season == season].set_index("playerId")
    last = sk[sk.season == season - 1].set_index("playerId")
    latest = past.sort_values("season").groupby("playerId").last()
    out = agg[["f", "a"]].join(latest[["name", "team", "position"]])
    out["gp_cur"] = cur.games_played.reindex(out.index).fillna(0)
    out["team_cur"] = cur.team.reindex(out.index)
    out["gp_last"] = last.games_played.reindex(out.index).fillna(0)
    out["team_last"] = last.team.reindex(out.index)
    # ice time per game: this season once he has 5+ games, else last season
    toi_cur = (cur.icetime / cur.games_played).reindex(out.index)
    toi_last = (last.icetime / last.games_played).reindex(out.index)
    out["toi_pg"] = toi_cur.where(out.gp_cur >= 5, toi_last).fillna(toi_cur).fillna(0)
    return out.reset_index()


def roster_ratings(season, min_season=None):
    """{team: (offense, defense)} relative to league average (1.0 = average), from the team's
    opening lineup (time-on-ice weighted) and its players' stats in seasons before `season`
    (never before `min_season`)."""
    sk = pd.read_csv(SKATERS)
    lu = pd.read_csv(LINEUPS)
    lu = lu[lu.season == season]
    first = max(season - len(SEASON_W), min_season or 0)
    past = sk[sk.season.between(first, season - 1)].copy()
    if lu.empty or past.empty:
        return {}
    past["w"] = past.season.map({season - 1 - i: w for i, w in enumerate(SEASON_W)})
    stats = list(OFFENSE) + list(DEFENSE)
    for c in stats + ["icetime"]:
        past[c] = past[c] * past.w
    agg = past.groupby("playerId")[stats + ["icetime"]].sum()
    shrink = SHRINK_MIN * 60
    ratio = {}
    for c in stats:
        lg = sk[sk.season.between(first, season - 1)][c].sum() / sk[sk.season.between(first, season - 1)].icetime.sum()
        repl = REPLACEMENT[0] if c in OFFENSE else REPLACEMENT[1]
        ratio[c] = (agg[c] + shrink * lg * repl) / (agg.icetime + shrink) / lg
    agg["f"] = sum(w * ratio[c] for c, w in OFFENSE.items())
    agg["a"] = sum(w * ratio[c] for c, w in DEFENSE.items())
    w = lu.groupby(["team", "playerId"]).toi.sum().reset_index().join(agg[["f", "a"]], on="playerId")
    w["f"] = w.f.fillna(REPLACEMENT[0])  # no NHL history in the window = replacement level
    w["a"] = w.a.fillna(REPLACEMENT[1])
    out = {t: ((x.f * x.toi).sum() / x.toi.sum(), (x.a * x.toi).sum() / x.toi.sum()) for t, x in w.groupby("team")}
    mf = sum(v[0] for v in out.values()) / len(out)
    ma = sum(v[1] for v in out.values()) / len(out)
    return {t: (f / mf, a / ma) for t, (f, a) in out.items()}
