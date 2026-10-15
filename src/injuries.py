"""Skater injury adjustment.

Injured / suspended regulars (ESPN's injury list) are removed from their team and replaced by a
replacement-level skater, using each player's value from players.player_table():

  offense: team scores  (1 - share x (player offense - replacement offense) x in_rating)
  defense: opponent scores (1 + share x (replacement defense - player defense) x in_rating)

share     = his ice time per game / all skater ice time in a game (5 skaters x 60 min)
in_rating = how much of him is actually in the team's current rating: a player who has already
            missed most of the team's games is mostly gone from the numbers, so he's mostly not
            removed again (no double counting).

Backtested Oct 2026 (research/studies/injury_backtest.py) on who actually dressed in 14,898 team-games: goals vs
the model track the adjustment with a slope of ~1.3 in both 2021-24 and 2024-26 (1.0 = exactly right size),
and it improves accuracy vs closing and opening lines. Was 1.0x until Oct 10 2026, now 1.15x (SCALE): a step toward
the measured size, kept below it because live the lineup is only projected.
"""
import json
import urllib.request

import pandas as pd

import model as m
import players
from teams import TEAMS

ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
OUT_STATUSES = {"Out", "Injured Reserve", "Suspension"}  # Day-To-Day players usually play: shown, not adjusted
SKATER_SECONDS = 5 * 3600
K = m.K  # games of prior weight in the team ratings (same as the model)
SCALE = 1.15  # size of the adjustment: the backtest measures ~1.2x; 1.15x improved accuracy in every season (Oct 10 2026, research/studies/injury_115.py)


def fetch():
    """[{team, name, pos, status, ret, note}] from ESPN; team = NHL abbreviation."""
    by_name = {m.norm_name(v): k for k, v in TEAMS.items()}
    with urllib.request.urlopen(m.fetch(ESPN), timeout=30) as f:
        data = json.load(f)
    rows = []
    for t in data.get("injuries", []):
        team = by_name.get(m.norm_name(t.get("displayName", "")))
        if not team:
            continue
        for i in t.get("injuries", []):
            a = i.get("athlete", {})
            pos = a.get("position", {}).get("abbreviation", "")
            if pos == "G":  # goalies are handled through the starting goalie
                continue
            rows.append({"team": team, "name": a.get("displayName", ""), "pos": pos, "status": i.get("status", ""),
                         "ret": (i.get("details") or {}).get("returnDate"), "note": i.get("shortComment", "")})
    return rows


def _subseq(a, b):
    it = iter(b)
    return all(c in it for c in a)


def _loose(pt, name, team, pos=""):
    """Fallback name match on this team only: same first initial + same last name, allowing letters MoneyPuck dropped
    ('Oskar Bck' = ESPN 'Oskar Back') or a different first name ('Joseph Veleno' = 'Joe Veleno'). One match or none."""
    k = m.norm_name(name).split()
    if len(k) < 2:
        return pt.iloc[0:0]
    t = pt[(pt.team_cur == team) | (pt.team_last == team)]
    ok = [i for i, key in zip(t.index, t.key) if key.split() and key[0] == k[0][0]
          and (key.split()[-1] == k[-1] or (_subseq(key.split()[-1], k[-1]) and len(k[-1]) - len(key.split()[-1]) <= 3))]
    if not ok:  # new team, not in MoneyPuck's data yet: league-wide, same first name + dropped letters only
        ok = [i for i, key in zip(pt.index, pt.key) if key.split()[:1] == k[:1] and len(key.split()) == len(k)
              and key.split()[-1] != k[-1] and _subseq(key.split()[-1], k[-1]) and len(k[-1]) - len(key.split()[-1]) <= 3]
    return _by_pos(pt.loc[ok], pos) if ok else pt.iloc[0:0]


def _by_pos(cand, pos):
    """Several candidates (VAN has two Elias Petterssons): keep the one at the listed position (D vs forward), if unique."""
    if len(cand) > 1 and pos:
        cand = cand[(cand.position == "D") == (pos == "D")]
    return cand if len(cand) == 1 else cand.iloc[0:0]


def resolve(pt, r):
    """The player_table row for an injury-list row {team, name, id?}, or None. pt needs key / key2 columns."""
    cand = pt[pt.playerId == r["id"]] if r.get("id") else pt[(pt.key == m.norm_name(r["name"])) | (pt.key2 == m.squash_name(r["name"]))]
    if len(cand) > 1:  # same name (two Sebastian Ahos): prefer the one on this team
        same = cand[(cand.team_cur == r["team"]) | (cand.team_last == r["team"]) | (cand.team == r["team"])]
        cand = same if len(same) else cand
        if len(cand) > 1 and r.get("pos"):
            cand = _by_pos(cand, r["pos"]) if len(_by_pos(cand, r["pos"])) else cand
    if cand.empty and not r.get("id"):
        cand = _loose(pt, r["name"], r["team"], r.get("pos", ""))
    return None if cand.empty else cand.iloc[0]


def adjustments(injured, season, team_games, team_gp=None):
    """{team: {"off": mult on its goals, "def": mult on its opponents' goals, "out": [(name, goals)], "dtd": [names]}}
    team_games: {team: games played this season} (for how much of each player is in the rating);
    team_gp: {(team, NHL id): his games for that team} (team_gp()), optional."""
    team_gp = team_gp or {}
    pt = players.player_table(season)
    pt["key"], pt["key2"] = pt.name.map(m.norm_name), pt.name.map(m.squash_name)
    out, counted = {}, set()
    for r in injured:
        o = out.setdefault(r["team"], {"off": 1.0, "def": 1.0, "out": [], "dtd": []})
        if r["status"] not in OUT_STATUSES:
            if r["status"] == "Day-To-Day":
                o["dtd"].append(r["name"])
            continue
        p = resolve(pt, r)
        if p is None:
            continue  # no NHL history since 2020 (prospect/depth player): nothing to remove
        if p.playerId in counted:  # same player listed twice under different spellings (ESPN / Rotowire / lineup)
            continue
        counted.add(p.playerId)
        d_off, d_def = _effect(p, r["team"], team_games.get(r["team"], 0), team_gp.get((r["team"], p.playerId)))
        if r.get("tag") == "scratch":
            # a healthy scratch is replaced by a normal roster player, not a better one: only count
            # the effect when a GOOD player sits (team scores less / allows more), never a boost
            d_off, d_def = max(d_off, 0.0), max(d_def, 0.0)
        if abs(d_off) + abs(d_def) < 0.002:  # depth player / long gone: not worth listing
            continue
        d_off, d_def = SCALE * d_off, SCALE * d_def
        o["off"] *= 1 - d_off
        o["def"] *= 1 + d_def
        o["out"].append((r["name"] + (f" ({r['tag']})" if r.get("tag") else ""), d_off, d_def))
    return out


def _effect(p, team, n, gp=None):
    """(offense, defense) effect of one player sitting, before SCALE: ice-time share x distance from a replacement
    player x in_rating. n = the team's games played this season; gp = his games for THIS team (NHL club stats) when
    known: MoneyPuck adds a traded player's games for both teams under his new team."""
    if gp is not None:
        w_cur = min(gp, n) / n if n else 0.0
    else:
        w_cur = p.gp_cur / n if n and p.team_cur == team else 0.0
    w_last = min(p.gp_last / 82, 1.0) if p.team_last == team else 0.0
    in_rating = (K * w_last + n * w_cur) / (K + n)
    share = p.toi_pg / SKATER_SECONDS
    return share * (p.f - players.REPLACEMENT[0]) * in_rating, share * (players.REPLACEMENT[1] - p.a) * in_rating


def key_players(rosters, injured, lineup_info, season, team_games, top=5, team_gp=None, names=None):
    """Each team's top `top` attackers and defenders, ranked by the model's effect if he sits (as adjustments() would
    remove it: offense = his team's goals, defense = the opponent's goals), with tonight's status.
    rosters: {team: [NHL ids]}; players on the injury list count even when off the roster (IR).
    names: {NHL id: NHL name} (shown instead of MoneyPuck's, which drops accented letters).
    Returns {team: {"off": [{name, pos, impact, status}], "def": [...]}}; status = in / out / dtd / gtd / '' (no lineup)."""
    names = names or {}
    pt = players.player_table(season)
    pt["key"], pt["key2"] = pt.name.map(m.norm_name), pt.name.map(m.squash_name)
    out = {}
    for team, ids in rosters.items():
        hurt = [r for r in injured if r["team"] == team]
        by_id = {}
        for r in hurt:  # each injury row -> one NHL id (same matching as adjustments: twins, nicknames, accents)
            p_ = resolve(pt, r)
            if p_ is not None and (p_.playerId not in by_id or (r["status"] in OUT_STATUSES and by_id[p_.playerId]["status"] not in OUT_STATUSES)):
                by_id[p_.playerId] = r  # listed twice (ESPN day-to-day + not in lineup): 'out' wins, as in adjustments()
        d = pt[pt.playerId.isin(set(ids) | set(by_id))]
        d = d.drop_duplicates("playerId")
        n = team_games.get(team, 0)

        def row(p, k):
            r = by_id.get(p.playerId)
            if r is None:
                status = "in" if team in lineup_info else ""
            elif r["status"] in OUT_STATUSES:
                status = "out"
            else:
                status = "gtd" if r.get("note") == "game-time decision" else "dtd"
            eff = _effect(p, team, n, (team_gp or {}).get((team, p.playerId)))[k]
            if r is not None and r.get("tag") == "scratch":
                eff = max(eff, 0.0)  # same rule as adjustments(): a scratch is never a boost
            tag = (r or {}).get("tag") or ("IR" if r is not None and r["status"] == "Injured Reserve" else "")
            return {"name": names.get(p.playerId) or p["name"], "pos": p.position, "impact": round(SCALE * eff, 4), "status": status, "tag": tag}
        out[team] = {side: sorted((row(p, k) for _, p in d.iterrows()), key=lambda x: -x["impact"])[:top]
                     for k, side in ((0, "off"), (1, "def"))}
    return out


def lineup_changes(baseline, kp, old_changes, at, frozen=()):
    """Top-3 attackers whose status differs from the day's first run (baseline: {team: [{name, status, impact}]}).
    {team: [{name, from, to, impact, at}]}; 'at' = when the change was first seen (kept while it lasts). A player back
    to his first-run status drops off. Teams in frozen (game started) keep their old entries. 'in' and '' (no lineup
    posted yet, not injured) count as the same: a missing DailyFaceoff lineup is not a lineup change."""
    out = {}
    for team, v in kp.items():
        if team in frozen:
            if old_changes.get(team):
                out[team] = old_changes[team]
            continue
        now = {p["name"]: p["status"] for side in ("off", "def") for p in v[side]}
        seen = {c["name"]: c for c in old_changes.get(team, [])}
        ch = []
        for b in baseline.get(team, []):
            st = now.get(b["name"])
            if st is None or (st or "in") == (b["status"] or "in"):
                continue
            prev = seen.get(b["name"])
            ch.append({"name": b["name"], "from": b["status"], "to": st, "impact": b["impact"],
                       "at": prev["at"] if prev and prev["to"] == st else at})
        if ch:
            out[team] = ch
    return out


def team_gp(teams, season):
    """{(team, NHL id): games played for that team this season} from NHL club stats (a traded player has a row per team)."""
    out = {}
    for t in teams:
        url = f"https://api-web.nhle.com/v1/club-stats/{t}/{season}{season + 1}/2"
        with urllib.request.urlopen(m.fetch(url), timeout=30) as f:
            for p in json.load(f).get("skaters", []):
                out[(t, p["playerId"])] = p["gamesPlayed"]
    return out


def merge_lineups(injured, lineup_outs):
    """Add players missing from the projected lineup (lineups.outs) to ESPN's list, without duplicates.
    Game-time decisions become day-to-day. Returns the merged list."""
    merged = [dict(r) for r in injured]
    have = {(r["team"], m.norm_name(r["name"])): r for r in merged}
    for team, lu in lineup_outs.items():
        for pid, name, reason in lu["missing"]:
            r = have.get((team, m.norm_name(name)))
            if r is not None:
                if r["status"] == "Day-To-Day":  # day-to-day on ESPN but not in tonight's lineup: he's out
                    r.update(status="Out", id=pid, tag="scratch", note="day-to-day, not in lineup")
                continue  # otherwise ESPN already has him as out
            merged.append({"team": team, "name": name, "id": pid, "status": "Out",
                           "tag": "IR" if reason.startswith("IR") else "scratch", "pos": "", "ret": None, "note": reason})
        for name in lu["gtd"]:
            if (team, m.norm_name(name)) not in have:
                merged.append({"team": team, "name": name, "status": "Day-To-Day", "pos": "", "ret": None, "note": "game-time decision"})
    return merged


def team_games_this_season(games, season):
    g = games[games.season == season]
    return pd.concat([g.home, g.away]).value_counts().to_dict()
