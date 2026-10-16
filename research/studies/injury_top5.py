"""When one of a team's top 5 attackers or top 5 defenders is out: how did the model do, and what did the injury
adjustment do to the projection?

Top 5 = the team's regulars (dressed in 5+ of its last 10 games) ranked by the model's effect if he sits, as the
dashboard's Key players: attackers by the effect on his team's goals, defenders by the effect on the opponent's.

A. BACKTEST 2021-26, who actually dressed (data/dressed.csv; ratings from earlier seasons only, as
   injury_backtest.py). For team-games with a top-5 attacker out (its own goals) / a top-5 defender out (the
   opponent's goals), and games with any top-5 player out (game totals): actual vs projected WITHOUT and WITH the live
   injury adjustment (1.15x): average miss (actual - projected; 0 = right on average) and deviance (lower = better).
   Team-games with no top-5 player out are the comparison.
B. THIS SEASON, live: top-5 players shown 'out' in that day's Key players (data/key_players/) who were also in the
   model's out list at the last run before puck drop; projection with the logged injury adjustment vs without it.

  python3 research/studies/injury_top5.py      # part A needs data/dressed.csv (research/lib/lineups_hist.py)
"""
import glob
import json
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from collections import defaultdict, deque

import numpy as np
import pandas as pd

import dashboard
import injuries
import paths
import players
import split_model as sm
from injury_backtest import adjusted

K, SECS, TOP = injuries.K, injuries.SKATER_SECONDS, 5


def regulars(games, dressed):
    """{(gameId, team): [(d_off, d_def, missing)]} for every regular, same rules as injury_backtest.missing_effects."""
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
            hist, rows = last10[team], []
            if len(hist) >= 5:
                counts = defaultdict(int)
                for s in hist:
                    for p in s:
                        counts[p] += 1
                n = team_n[(g.season, team)]
                for p, c in counts.items():
                    if c < 5 or last_team.get(p) != team or p not in pt.index:
                        continue
                    r = pt.loc[p]
                    w_cur = played_for[(g.season, team)][p] / n if n else 0.0
                    w_last = min(last.games_played.get(p, 0) / 82, 1.0) if last.team.get(p) == team else 0.0
                    in_rating = (K * w_last + n * w_cur) / (K + n)
                    share = r.toi_pg / SECS if r.toi_pg else 0.0
                    rows.append((share * (r.f - players.REPLACEMENT[0]) * in_rating,
                                 share * (players.REPLACEMENT[1] - r.a) * in_rating, p not in tonight))
                out[(g.gameId, team)] = rows
            hist.append(tonight)
            team_n[(g.season, team)] += 1
            for p in tonight:
                played_for[(g.season, team)][p] += 1
                last_team[p] = team
    return out


def dev(y, lam):
    return 2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / lam), 0) - (y - lam))


def line(name, y, base, adj):
    return (f"   {name:44s} {len(y):6d}  {y.mean():5.2f}  {base.mean():5.2f}  {adj.mean():5.2f}   {(y - base).mean():+6.3f}  {(y - adj).mean():+6.3f}"
            f"   {dev(y, base).mean():.4f}  {dev(y, adj).mean():.4f}")


HEAD = (f"   {'':44s} {'games':>6s}  {'goals':>5s}  {'proj':>5s}  {'+inj':>5s}   {'miss':>6s}  {'+inj':>6s}   {'dev':>6s}  {'+inj':>6s}"
        "\n   (proj = model without the injury adjustment, +inj = with it; miss = actual - projected, 0 = right on average)")


def part_a():
    games = sm.load_split()
    base = sm.walk_split(games, known_starters=False)
    reg = regulars(games, pd.read_csv(paths.data("dressed.csv")))
    eff = {k: ([a for a, b, mi in v if mi], [b for a, b, mi in v if mi]) for k, v in reg.items()}
    adj = adjusted(base, eff, scale=injuries.SCALE)
    tag = {}
    for k, v in reg.items():
        top_off = set(sorted(range(len(v)), key=lambda i: -v[i][0])[:TOP])
        top_def = set(sorted(range(len(v)), key=lambda i: -v[i][1])[:TOP])
        tag[k] = (sum(v[i][2] for i in top_off), sum(v[i][2] for i in top_def), sum(x[2] for x in v))
    x = base.merge(adj[["gameId", "lam_h", "lam_a", "proj"]], on="gameId", suffixes=("", "_adj")).merge(games[["gameId", "hg", "ag"]], on="gameId")
    x = x[x.season >= 2021]
    rows = []
    for r in x.itertuples():
        th, ta = tag.get((r.gameId, r.home)), tag.get((r.gameId, r.away))
        if th is None or ta is None:
            continue
        for team_t, opp_t, y, lb, la in ((th, ta, r.hg, r.lam_h, r.lam_h_adj), (ta, th, r.ag, r.lam_a, r.lam_a_adj)):
            rows.append({"season": r.season, "y": y, "base": lb, "adj": la, "off_out": team_t[0], "opp_def_out": opp_t[1]})
    t = pd.DataFrame(rows)
    gm = pd.DataFrame([{"season": r.season, "y": r.hg + r.ag, "base": r.proj, "adj": r.proj_adj,
                        "top_out": (tag[(r.gameId, r.home)][0] + tag[(r.gameId, r.home)][1] + tag[(r.gameId, r.away)][0] + tag[(r.gameId, r.away)][1]) > 0}
                       for r in x.itertuples() if (r.gameId, r.home) in tag and (r.gameId, r.away) in tag])
    print(f"A. BACKTEST 2021-26 (who actually dressed): {len(t)} team-games\n{HEAD}")
    for seasons, label in (((2021, 2025), "2021-26"), ((2021, 2022), "2021-23"), ((2023, 2025), "2023-26")):
        s, g = t[t.season.between(*seasons)], gm[gm.season.between(*seasons)]
        print(f"  {label}")
        q = s[s.off_out == 0]
        print(line("no top-5 attacker out -> own goals (compare)", q.y, q.base, q.adj))
        for n, lab in ((1, "top-5 attacker out -> his team's goals"), (2, "2+ top-5 attackers out -> his team's goals")):
            q = s[s.off_out >= n]
            print(line(lab, q.y, q.base, q.adj))
        q = s[s.opp_def_out == 0]
        print(line("no top-5 defender out -> opp goals (compare)", q.y, q.base, q.adj))
        for n, lab in ((1, "top-5 defender out -> opponent's goals"), (2, "2+ top-5 defenders out -> opponent's goals")):
            q = s[s.opp_def_out >= n]
            print(line(lab, q.y, q.base, q.adj))
        q = g[~g.top_out]
        print(line("no top-5 player out -> game total", q.y, q.base, q.adj))
        q = g[g.top_out]
        print(line("any top-5 player out -> game total", q.y, q.base, q.adj))


def part_b():
    log = dashboard.current(pd.read_csv(paths.data("paper_trades.csv")))
    log = log[log.final_total.notna()]
    kp = {}
    for f in glob.glob(paths.data("key_players/*.json")):
        d = json.load(open(f))
        kp[d["date"]] = (d.get("rebuilt", False), d["teams"])
    rows = []
    for r in log.itertuples():
        if r.date not in kp:
            continue
        rebuilt, teams = kp[r.date]
        for side, opp in (("away", "home"), ("home", "away")):
            team, oteam = getattr(r, side), getattr(r, opp)
            model_out = {n.split("|")[0].split(" (")[0] for n in str(getattr(r, f"{side}_out")).split("; ") if n and n != "nan"}
            opp_out = {n.split("|")[0].split(" (")[0] for n in str(getattr(r, f"{opp}_out")).split("; ") if n and n != "nan"}
            t, o = teams.get(team, {}), teams.get(oteam, {})
            off = [p["name"] for p in t.get("off", []) if p["status"] == "out" and injuries.m.norm_name(p["name"]) in {injuries.m.norm_name(x) for x in model_out}]
            dfn = [p["name"] for p in o.get("def", []) if p["status"] == "out" and injuries.m.norm_name(p["name"]) in {injuries.m.norm_name(x) for x in opp_out}]
            goals = r.final_away if side == "away" and hasattr(r, "final_away") else None
            lam = getattr(r, f"proj_{side}")
            inj = getattr(r, f"{side}_inj")
            rows.append({"date": r.date, "team": team, "lam": lam, "base": lam / (1 + inj) if pd.notna(inj) else lam, "inj": inj,
                         "off": off, "def_opp": dfn, "total": r.final_total, "goals": goals})
    t = pd.DataFrame(rows)
    return t, log


def main():
    if _os.path.exists(paths.data("dressed.csv")):
        part_a()
    else:
        print("A. skipped: data/dressed.csv not downloaded (research/lib/lineups_hist.py)")
    part_b_print()


def part_b_print():
    import urllib.request
    import model as m
    t, log = part_b()
    # each team's goals in finished games (NHL scores, shootout winner +1 as on the sportsbook total)
    goals = {}
    for day in sorted(t.date.unique()):
        with urllib.request.urlopen(m.fetch(f"https://api-web.nhle.com/v1/score/{day}"), timeout=30) as f:
            for g in json.load(f).get("games", []):
                if g["gameType"] == 2 and g["gameState"] in ("OFF", "FINAL"):
                    goals[(day, g["awayTeam"]["abbrev"])] = g["awayTeam"]["score"]
                    goals[(day, g["homeTeam"]["abbrev"])] = g["homeTeam"]["score"]
    t["y"] = [goals.get((d, tm)) for d, tm in zip(t.date, t.team)]
    t = t[t.y.notna() & t.inj.notna()]  # Oct 1-2: injury adjustment not logged yet
    print(f"\nB. THIS SEASON, live (last pre-game run; {t.date.min()} to {t.date.max()}, {len(t)} team-games)\n{HEAD}")
    print(line("no top-5 player out on either side", t[(t.off.str.len() == 0) & (t.def_opp.str.len() == 0)].y,
               t[(t.off.str.len() == 0) & (t.def_opp.str.len() == 0)].base, t[(t.off.str.len() == 0) & (t.def_opp.str.len() == 0)].lam))
    q = t[t.off.str.len() > 0]
    print(line("top-5 attacker out -> his team's goals", q.y, q.base, q.lam))
    q2 = t[t.def_opp.str.len() > 0]
    print(line("top-5 defender out -> opponent's goals", q2.y, q2.base, q2.lam))
    print("\n   each team-game with a top-5 attacker out:")
    for r in q.sort_values("date").itertuples():
        print(f"   {r.date} {r.team:4s} out: {', '.join(r.off):40s} proj {r.base:.2f} -> {r.lam:.2f} ({r.inj:+.1%})  scored {int(r.y)}")


if __name__ == "__main__":
    main()
