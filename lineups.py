"""Projected lineups (DailyFaceoff line combinations) checked against the official NHL roster.

A skater who is on his team's official NHL roster but NOT in DailyFaceoff's 18 dressed skaters is
treated as out for the game (healthy scratch, late injury, rest) - the same way injuries.py treats
an injured player. Players are matched by name or jersey number (handles 'Matt' vs 'Matthew').
Each team's lineup source + time is kept so the dashboard can show how fresh it is
('Last Game' = last game's lineup, not yet updated for tonight).
"""
import json
import re
import urllib.request

import model as m

DFO_LINES = "https://www.dailyfaceoff.com/teams/{}/line-combinations"
NHL_ROSTER = "https://api-web.nhle.com/v1/roster/{}/current"


def _next_data(url):
    html = urllib.request.urlopen(m.fetch(url), timeout=30).read().decode()
    return json.loads(re.search(r'__NEXT_DATA__" type="application/json">(.*?)</script>', html).group(1))


def team_slugs(day):
    """{NHL abbreviation: DailyFaceoff team slug} for teams playing on `day`."""
    from teams import TEAMS
    by_name = {m.norm_name(v): k for k, v in TEAMS.items()}
    games = _next_data(f"https://www.dailyfaceoff.com/starting-goalies/{day}")["props"]["pageProps"]["data"]
    return {by_name[m.norm_name(g[s + "TeamName"])]: g[s + "TeamSlug"]
            for g in games for s in ("home", "away") if m.norm_name(g[s + "TeamName"]) in by_name}


def projected_lineup(slug):
    c = _next_data(DFO_LINES.format(slug))["props"]["pageProps"]["combinations"]
    dressed, ir, gtd = [], [], []
    for p in c["players"]:
        g = p.get("groupName", "")
        entry = (m.norm_name(p["name"]), p.get("jerseyNumber"), p["name"])
        if g.startswith(("Forwards", "Defense")):
            dressed.append(entry)
            if p.get("gameTimeDecision"):
                gtd.append(p["name"])
        elif g == "Injured Reserve":
            ir.append(entry)
    return {"dressed": dressed, "ir": ir, "gtd": gtd, "source": c.get("sourceName") or "", "updated": c.get("updatedAt") or ""}


def nhl_roster(abbr):
    r = json.load(urllib.request.urlopen(m.fetch(NHL_ROSTER.format(abbr)), timeout=30))
    return [(p["id"], f"{p['firstName']['default']} {p['lastName']['default']}", p.get("sweaterNumber"))
            for grp in ("forwards", "defensemen") for p in r.get(grp, [])]


def outs(day, teams):
    """For each team playing: ({players on the roster but not in the projected lineup}, lineup info).
    Returns {abbr: {"missing": [(nhl_id, name, reason)], "gtd": [names], "source": str, "updated": str}}."""
    slugs = team_slugs(day)
    result = {}
    for abbr in teams:
        slug = slugs.get(abbr)
        if not slug:
            continue
        try:
            lu = projected_lineup(slug)
            roster = nhl_roster(abbr)
        except Exception as e:
            print(f"  (lineup check skipped for {abbr}: {e})")
            continue
        if len(lu["dressed"]) < 18:  # incomplete lineup posted: don't guess
            print(f"  (lineup check skipped for {abbr}: only {len(lu['dressed'])} skaters listed)")
            continue
        names = {n for n, _, _ in lu["dressed"]}
        numbers = {j for _, j, _ in lu["dressed"] if j is not None}
        ir_names = {n for n, _, _ in lu["ir"]}
        missing = []
        for pid, name, num in roster:
            if m.norm_name(name) in names or (num is not None and num in numbers):
                continue  # dressed
            reason = "IR (DailyFaceoff)" if m.norm_name(name) in ir_names else "not in lineup"
            missing.append((pid, name, reason))
        result[abbr] = {"missing": missing, "gtd": lu["gtd"], "source": lu["source"], "updated": lu["updated"]}
    return result
