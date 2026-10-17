"""Power-play-specific injuries (suggestion #2, Oct 16 2026). The live injury adjustment removes a player by his
all-situations ice time and rating, so a PP1 quarterback counts the same as an even-strength player with the same
minutes and rating. Does losing power-play (or penalty-kill) time hurt MORE than the live adjustment already says?

Backtest 2021-26 on who actually dressed (data/dressed.csv), ratings from earlier seasons only (as injury_backtest.py).
For each team-game: pp_out = the share of the team's 5-on-4 ice time last season that belonged to regulars who did
not dress tonight (same team last season; a player new to the team uses his share on his old team); pk_out = the same
for 4-on-5 time. Residual = goals - projection WITH the live injury adjustment (1.15x).
  1. residual of the team's own goals by pp_out, and the opponent's goals by pk_out (0 = live adjustment is enough)
  2. fit goals x (1 - b x pp_out) and opponent goals x (1 + c x pk_out) on 2021-23, judge on 2023-26 (team-goal deviance)

  python3 research/studies/pp_injuries.py      # needs data/dressed.csv (research/lib/lineups_hist.py)
"""
import io
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from collections import defaultdict, deque

import numpy as np
import pandas as pd

import injuries
import paths
import players
import split_model as sm
from injury_backtest import adjusted
from injury_top5 import dev

K, SECS = injuries.K, injuries.SKATER_SECONDS
PP_FILE = paths.data("skater_special_teams.csv")


def special_teams(seasons=range(2019, 2026)):
    """Per player-season-team: 5on4 / 4on5 ice time and games (MoneyPuck season summaries; cached)."""
    if _os.path.exists(PP_FILE):
        return pd.read_csv(PP_FILE)
    parts = []
    for s in seasons:
        d = pd.read_csv(io.BytesIO(players.get(players.MP_SKATERS.format(s))))
        d = d[d.situation.isin(["5on4", "4on5"])]
        parts.append(d[["playerId", "season", "team", "situation", "games_played", "icetime"]])
    out = pd.concat(parts)
    out.to_csv(PP_FILE, index=False)
    return out


def shares(st):
    """{(season, playerId): (pp share of his team's 5on4 time, pk share of 4on5 time)} - per game, 1 = on for all of it."""
    st = st.replace({"team": injuries.m.MP_ABBR})
    out = {}
    for sit, i, skaters in (("5on4", 0, 5), ("4on5", 1, 4)):
        d = st[st.situation == sit].copy()
        team_pg = d.groupby(["season", "team"]).icetime.sum() / skaters  # the team's time in that situation
        team_pg = team_pg / d.groupby(["season", "team"]).games_played.max()
        d["share"] = (d.icetime / d.games_played.clip(lower=1)) / d.set_index(["season", "team"]).index.map(team_pg)
        for r in d.itertuples():
            v = out.setdefault((r.season, r.playerId), [0.0, 0.0])
            v[i] = min(r.share, 1.0)
    return out


def team_games(games, dressed, sh):
    """{(gameId, team): (live injury effects (d_off, d_def) of missing regulars, pp_out, pk_out)}."""
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
            if len(hist) >= 5:
                counts = defaultdict(int)
                for s in hist:
                    for p in s:
                        counts[p] += 1
                n = team_n[(g.season, team)]
                d_off, d_def, pp, pk = [], [], 0.0, 0.0
                for p, c in counts.items():
                    if c < 5 or p in tonight or last_team.get(p) != team or p not in pt.index:
                        continue
                    r = pt.loc[p]
                    w_cur = played_for[(g.season, team)][p] / n if n else 0.0
                    w_last = min(last.games_played.get(p, 0) / 82, 1.0) if last.team.get(p) == team else 0.0
                    in_rating = (K * w_last + n * w_cur) / (K + n)
                    share = r.toi_pg / SECS if r.toi_pg else 0.0
                    d_off.append(share * (r.f - players.REPLACEMENT[0]) * in_rating)
                    d_def.append(share * (players.REPLACEMENT[1] - r.a) * in_rating)
                    a, b = sh.get((g.season - 1, p), (0.0, 0.0))
                    pp += a; pk += b
                out[(g.gameId, team)] = ((d_off, d_def), pp, pk)
            hist.append(tonight)
            team_n[(g.season, team)] += 1
            for p in tonight:
                played_for[(g.season, team)][p] += 1
                last_team[p] = team
    return out


def main():
    games = sm.load_split()
    sh = shares(special_teams())
    tg = team_games(games, pd.read_csv(paths.data("dressed.csv")), sh)
    base = sm.walk_split(games, known_starters=False)
    adj = adjusted(base, {k: v[0] for k, v in tg.items()}, scale=injuries.SCALE)
    x = adj.merge(games[["gameId", "hg", "ag", "pp_goalsFor", "pk_goalsAgainst"]], on="gameId")
    x = x[x.season >= 2021]
    rows = []
    for r in x.itertuples():
        th, ta = tg.get((r.gameId, r.home)), tg.get((r.gameId, r.away))
        if th is None or ta is None:
            continue
        # home: own goals vs its pp_out; the away team's pk_out raises home goals. away: the mirror image.
        rows.append({"season": r.season, "y": r.hg, "lam": r.lam_h, "pp_out": th[1], "opp_pk_out": ta[2]})
        rows.append({"season": r.season, "y": r.ag, "lam": r.lam_a, "pp_out": ta[1], "opp_pk_out": th[2]})
    t = pd.DataFrame(rows)
    t["res"] = t.y - t.lam
    print(f"{len(t)} team-games 2021-26 with lineups. Residual = goals - projection with the live injury adjustment.\n")
    for col, label in (("pp_out", "own PP time missing (share of last season's 5on4 minutes)"),
                       ("opp_pk_out", "opponent's PK time missing (share of its 4on5 minutes)")):
        print(f"1. {label}")
        bins = [-0.01, 0.0, 0.15, 0.4, 10]
        names = ["none", "0-15%", "15-40%", "40%+"]
        for seasons, lab in (((2021, 2022), "2021-23"), ((2023, 2025), "2023-26")):
            s = t[t.season.between(*seasons)]
            cut = pd.cut(s[col], bins, labels=names)
            parts = "  ".join(f"{n}: {len(q):5d} g, res {q.res.mean():+.3f}" for n, q in s.groupby(cut, observed=True))
            print(f"   {lab}  {parts}")
    print("\n2. fit on 2021-23, judge on 2023-26 (team-goal deviance, lower = better)")
    tr, te = t[t.season.between(2021, 2022)], t[t.season.between(2023, 2025)]

    def apply(s, b, c):
        return s.lam * (1 - b * s.pp_out) * (1 + c * s.opp_pk_out)
    grid = np.round(np.arange(-0.10, 0.31, 0.02), 2)
    best = min(((dev(tr.y, apply(tr, b, c)).mean(), b, c) for b in grid for c in grid))
    _, b, c = best
    print(f"   live (b = c = 0):         2021-23 {dev(tr.y, tr.lam).mean():.5f}   2023-26 {dev(te.y, te.lam).mean():.5f}")
    print(f"   fitted b = {b:+.2f}, c = {c:+.2f}:  2021-23 {dev(tr.y, apply(tr, b, c)).mean():.5f}   2023-26 {dev(te.y, apply(te, b, c)).mean():.5f}")
    for bb, cc in ((b, 0.0), (0.0, c)):
        print(f"   only b = {bb:+.2f}, c = {cc:+.2f}:  2021-23 {dev(tr.y, apply(tr, bb, cc)).mean():.5f}   2023-26 {dev(te.y, apply(te, bb, cc)).mean():.5f}")
    print(f"   (b = {b:+.2f}: a team missing its whole PP1 unit, ~60% of PP time, scores {b * 0.6:.1%} fewer goals beyond the live adjustment)")


if __name__ == "__main__":
    main()
